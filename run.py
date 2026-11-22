"""Run and record in-game tests for installed Fallout 4 outfits."""

import argparse
import base64
import hashlib
import io
import json
import msvcrt
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
import tomllib

from PIL import Image
import psutil
import websocket

from motion_keys import SprintKeys, frame_lower_body


PRESETS = {
    name: (index, zone, side)
    for index, (name, zone, side) in enumerate((
        ("wrist-right", "wrist", "right"),
        ("wrist-inner", "wrist", "inner"),
        ("front", "full-body", "front"),
        ("back", "full-body", "back"),
        ("right", "full-body", "right"),
        ("left", "full-body", "left"),
        ("legs-right", "pelvis-to-feet", "right"),
        ("route-profile", "full-body", "right"),
        ("route-rear", "hips-and-thighs", "rear-three-quarter"),
        ("head", "head-and-neck", "front"),
        ("shoulder-right", "shoulder", "right"),
        ("arm-right", "elbow-and-forearm", "right"),
        ("torso", "torso", "front"),
        ("upper-back", "upper-back", "back"),
        ("hips", "hips-and-waist", "front-three-quarter"),
        ("knees-right", "knees", "right"),
        ("feet", "feet-and-ankles", "front-three-quarter"),
        ("shoulder-left", "shoulder", "left"),
        ("arm-left", "elbow-and-forearm", "left"),
        ("wrist-left", "wrist", "left"),
        ("legs-left", "pelvis-to-feet", "left"),
        ("knees-left", "knees", "left"),
        ("rifle-front", "hands-shoulders-and-sleeves", "front-three-quarter"),
    ))
}
PISTOL_CAPTURES = {"REST": 0.25, "AIMING": 0.3, "RELOADING": 0.8, "RELOADED": 0.25}
SCENARIOS = {
    "pistol": (0, ("wrist-right", "wrist-inner"), PISTOL_CAPTURES),
    "standing": (1, ("front", "back", "right", "left"), {"STANDING": 0.25}),
    "locomotion": (2, ("route-profile", "route-rear"), {
        "WALK": 0.0, "TURN": 0.0, "RUN": 0.0, "ROUTE_STOP": 0.25, "CROUCH_WALK": 0.0,
    }),
    "posture": (3, ("legs-right",), {"CROUCHED": 0.25, "STOOD_UP": 0.25, "SEATED": 0.25, "GOT_UP": 0.25}),
    "first-person": (4, ("first-person",), {"AIMING": 0.3, "RELOADING": 0.8, "PIPBOY": 0.95}),
    "workbench": (5, ("workbench",), {"BENCH_APPROACH": 0.25, "WORKBENCH": 0.6}),
    "rifle": (6, ("rifle-front",), PISTOL_CAPTURES),
    "sprint-jump": (7, ("motion-chase",), {"SPRINT": 0.1, "JUMP": 0.0, "LANDING": 0.0}),
}
STILL_NAMES = {"RELOADING": "during-reload"}
PATH_FIELDS = ("f4se_loader", "reference_save", "plugins_file", "obs_config", "output_directory")
TEXT_FIELDS = ("obs_scene", "obs_source")
SETUP_FIELDS = {*PATH_FIELDS, *TEXT_FIELDS, "capture_width"}


def read_setup(path):
    with path.open("rb") as file:
        setup = tomllib.load(file)
    if missing := SETUP_FIELDS - setup.keys():
        raise ValueError("Missing setup fields: " + ", ".join(sorted(missing)))
    if unknown := setup.keys() - SETUP_FIELDS:
        raise ValueError("Unknown setup fields: " + ", ".join(sorted(unknown)))
    for key in (*PATH_FIELDS, *TEXT_FIELDS):
        if not isinstance(setup[key], str) or not setup[key].strip():
            raise ValueError(f"{key} must be a nonempty string.")
    if type(setup["capture_width"]) is not int or not 320 <= setup["capture_width"] <= 4096:
        raise ValueError("capture_width must be an integer in the range 320 to 4096.")
    for key in PATH_FIELDS:
        setup[key] = (path.parent / setup[key]).resolve()
    return argparse.Namespace(**setup)


def verify_setup(setup, pieces):
    executable = setup.f4se_loader
    if executable.name.casefold() != "f4se_loader.exe" or not executable.is_file():
        raise ValueError("f4se_loader must point to the installed f4se_loader.exe.")
    if not (executable.parent / "f4se_1_11_240.dll").is_file():
        raise ValueError("Install the F4SE runtime for Fallout 4 1.11.240.")
    if setup.reference_save.suffix.casefold() != ".fos" or not setup.reference_save.is_file():
        raise ValueError("reference_save must point to an existing .fos file.")
    data = executable.parent / "Data"
    for name in ("OutfitTests.esp", "OutfitTests - Main.ba2", "F4SE/Plugins/OutfitTestCamera.dll"):
        if not (data / name).is_file():
            raise ValueError(f"Install the test mod file: {name}")
    auto = data / "F4SE/Plugins/po3_StartOnSave.ini"
    if not auto.is_file():
        raise ValueError("Install Start On Save AE and set Save File to the reference save name.")
    match = re.search(r"^[ \t]*Save File[ \t]*=[ \t]*([^\r\n]+)",
                      auto.read_text(encoding="utf-8-sig"), re.MULTILINE)
    if not match or match[1].strip().casefold() != setup.reference_save.stem.casefold():
        raise ValueError("Start On Save AE's Save File must match the reference save without its .fos extension.")
    activated = {line.strip().casefold() for line in setup.plugins_file.read_text(encoding="utf-8-sig").splitlines()}
    for plugin in {"OutfitTests.esp", *(plugin for plugin, _ in pieces)}:
        if not (data / plugin).is_file():
            raise ValueError(f"Plugin file is missing from Data: {plugin}")
        if plugin.casefold() != "fallout4.esm" and "*" + plugin.casefold() not in activated:
            raise ValueError(f"Enable {plugin} in the selected load order.")
    return data


class OBS:
    def __init__(self, setup):
        self.setup = setup

    def __enter__(self):
        config_path = self.setup.obs_config
        try:
            config = json.loads(config_path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            raise RuntimeError("Could not read the OBS WebSocket configuration.") from None
        if not (config.get("server_enabled") and config.get("auth_required") and config.get("server_password")):
            raise RuntimeError("Enable the authenticated WebSocket server in OBS.")
        self.socket = websocket.create_connection(
            f"ws://127.0.0.1:{config['server_port']}", timeout=10, suppress_origin=True,
        )
        self.request_id = 0
        try:
            challenge = json.loads(self.socket.recv())["d"]["authentication"]
            def digest(value):
                return base64.b64encode(hashlib.sha256(value.encode()).digest()).decode()
            secret = digest(config["server_password"] + challenge["salt"])
            authentication = digest(secret + challenge["challenge"])
            self.socket.send(json.dumps({
                "op": 1, "d": {"rpcVersion": 1, "authentication": authentication, "eventSubscriptions": 0},
            }))
            if json.loads(self.socket.recv())["op"] != 2:
                raise RuntimeError("OBS did not accept the WebSocket connection.")
        except BaseException:
            self.socket.close()
            raise
        return self

    def __exit__(self, *_):
        self.socket.close()

    def call(self, request, **data):
        self.request_id += 1
        request_id = str(self.request_id)
        self.socket.send(json.dumps({"op": 6, "d": {
            "requestType": request, "requestId": request_id, "requestData": data,
        }}))
        reply = json.loads(self.socket.recv())
        result = reply["d"]
        if reply["op"] != 7 or result["requestId"] != request_id:
            raise RuntimeError(f"Unexpected OBS response for {request}")
        status = result["requestStatus"]
        if not status["result"]:
            raise RuntimeError(f"OBS {request}: {status.get('comment', status['code'])}")
        return result.get("responseData", {})

    def check_scene(self):
        if self.call("GetRecordStatus")["outputActive"] or self.call("GetStreamStatus")["outputActive"]:
            raise RuntimeError("Stop existing OBS streams and recordings before testing.")
        scene, source = self.setup.obs_scene, self.setup.obs_source
        items = self.call("GetSceneItemList", sceneName=scene)["sceneItems"]
        enabled = [item for item in items if item["sceneItemEnabled"]]
        if len(enabled) != 1 or enabled[0]["sourceName"] != source:
            raise RuntimeError(f"OBS scene {scene} needs one enabled source named {source}.")
        capture = self.call("GetInputSettings", inputName=source)
        settings = capture["inputSettings"]
        if (capture["inputKind"] != "game_capture" or settings.get("capture_mode") != "window"
                or not settings.get("window", "").casefold().endswith(":fallout4.exe")):
            raise RuntimeError("Select a Game Capture source in window mode targeting Fallout4.exe.")

    def screenshot(self, width):
        result = self.call("GetSourceScreenshot", sourceName=self.setup.obs_source, imageFormat="png", imageWidth=width)
        return base64.b64decode(result["imageData"].split(",", 1)[1], validate=True)


def assert_game_closed():
    for process in psutil.process_iter(["name"], ad_value=""):
        if (process.info["name"] or "").lower() in {"fallout4.exe", "f4se_loader.exe"}:
            raise RuntimeError("Close the existing Fallout 4 session before testing.")


def read_phases(directory):
    path = directory / "phases.log"
    return path.read_text(encoding="utf-8", errors="replace").splitlines() if path.exists() else []


def phase_name(line):
    # The Papyrus string table can return another spelling of the same string.
    return line.partition(" ")[0].upper()


def wait_for(launcher, timeout, description, check):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if launcher.poll() is not None:
            raise RuntimeError(f"Fallout 4 exited while waiting for {description}.")
        if value := check():
            return value
        time.sleep(0.1)
    raise TimeoutError(f"Timed out waiting for {description}.")


def game_visible(obs):
    try:
        data = obs.screenshot(320)
    except RuntimeError:
        return False
    return inspect_capture(data)[0] is None


def inspect_capture(data):
    with Image.open(io.BytesIO(data)) as capture:
        luma = capture.convert("L")
        luminance = luma.histogram()
        signature = hashlib.sha256(luma.tobytes()).hexdigest()
    if sum(luminance[18:]) <= sum(luminance) * 0.05:
        return "black or loading screen", signature
    return None, signature


def describe_environment(setup, data, pieces):
    files = {
        "camera_sha256": data / "F4SE/Plugins/OutfitTestCamera.dll",
        "quest_archive_sha256": data / "OutfitTests - Main.ba2",
        "reference_save_sha256": setup.reference_save,
    }
    return {
        **{label: file_sha256(path) for label, path in files.items()},
        "cell": "QASmoke",
        "capture_width": setup.capture_width,
        "plugin_sha256": {plugin: file_sha256(data / plugin) for plugin, _ in pieces},
    }


def file_sha256(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def close_game(launcher, directory):
    (directory / "quit").touch()
    try:
        launcher.wait(timeout=12)
        return "graceful"
    except subprocess.TimeoutExpired:
        parent = psutil.Process(launcher.pid)
        for process in parent.children(recursive=True):
            if process.name().lower() == "fallout4.exe":
                process.terminate()
        launcher.wait(timeout=10)
        return "terminated after timeout"


def finish_video(obs, directory):
    original = Path(obs.call("StopRecord")["outputPath"]).resolve()
    if original.parent != directory:
        raise RuntimeError(f"OBS returned a recording outside the run directory: {original}")
    deadline = time.monotonic() + 10
    previous_size = None
    while time.monotonic() < deadline:
        size = original.stat().st_size if original.exists() else 0
        if size and size == previous_size and not obs.call("GetRecordStatus")["outputActive"]:
            try:
                return original.rename(directory / ("scenario" + original.suffix)).name
            except PermissionError:
                pass
        previous_size = size
        time.sleep(0.35)
    raise RuntimeError("OBS recording did not finalize.")


def execute(args, directory, result):
    setup = args.setup
    data = args.data
    executable = setup.f4se_loader
    assert_game_closed()
    with OBS(setup) as obs:
        obs.check_scene()
        previous_scene = obs.call("GetCurrentProgramScene")["currentProgramSceneName"]
        previous_record_directory = obs.call("GetRecordDirectory")["recordDirectory"]
        launcher = None
        recording = False
        record_directory_changed = False
        muted_inputs = []
        keys = SprintKeys()
        try:
            obs.call("SetCurrentProgramScene", sceneName=setup.obs_scene)
            result["environment"] = describe_environment(setup, data, args.pieces)
            settings = obs.call("GetVideoSettings")
            result["environment"]["obs_video"] = {
                name: settings[name] for name in ("outputWidth", "outputHeight", "fpsNumerator", "fpsDenominator")
            }
            extra = "".join(f"{plugin}\t{form_id}\n" for plugin, form_id in args.pieces[1:])
            (directory / "pieces.tsv").write_text(extra, encoding="ascii")
            print("Launching F4SE.", flush=True)
            scenario_id, views, capture_phases = SCENARIOS[args.scenario]
            if args.camera:
                views = (args.camera,)
            plugin, form_id = args.pieces[0]
            environment = dict(os.environ, FO4_OUTFIT_RUN=str(directory), FO4_OUTFIT_PLUGIN=plugin,
                               FO4_OUTFIT_FORM=str(form_id), FO4_OUTFIT_SCENARIO=str(scenario_id),
                               FO4_OUTFIT_CAMERA=str(PRESETS[args.camera][0] if args.camera else -1))
            launcher = subprocess.Popen([executable, "-waitforclose"], cwd=executable.parent, env=environment)
            wait_for(launcher, 120, "QASmoke", lambda: any(
                phase_name(phase) == "LOAD_READY" for phase in read_phases(directory)
            ))
            print("QASmoke ready. Checking OBS game capture.", flush=True)
            wait_for(launcher, 45, "a visible Fallout 4 frame in OBS", lambda: game_visible(obs))
            obs.call("SetRecordDirectory", recordDirectory=str(directory))
            record_directory_changed = True
            for name in set(obs.call("GetSpecialInputs").values()) - {None, ""}:
                if not obs.call("GetInputMute", inputName=name)["inputMuted"]:
                    obs.call("SetInputMute", inputName=name, inputMuted=True)
                    muted_inputs.append(name)
            obs.call("StartRecord")
            recording = True
            (directory / "go").touch()
            print("Recording. Scenario released.", flush=True)
            seen = set()
            expected = {(view, phase) for view in views for phase in capture_phases}
            phases_read = 0
            active_view = None
            previous_capture = None
            sprint_jump_key = None
            sprint_trigger = None

            def scenario_finished():
                nonlocal phases_read, active_view, previous_capture, sprint_jump_key, sprint_trigger
                keys.update(launcher)
                if sprint_trigger is not None and time.monotonic() >= sprint_trigger[1]:
                    keys.press((sprint_trigger[0],), launcher, 1.15)
                    sprint_trigger = None
                phases = read_phases(directory)
                for line in phases[phases_read:]:
                    phases_read += 1
                    phase = phase_name(line)
                    if phase == "VIEW":
                        active_view = line.partition(" ")[2].lower()
                    if phase == "MOTION_CAMERA" and args.scenario == "sprint-jump":
                        frame_lower_body(launcher)
                    if phase == "SPRINT_INPUT" and args.scenario == "sprint-jump":
                        forward, sprint, sprint_jump_key = map(int, line.split()[1:])
                        keys.press((forward,), launcher, 3.1)
                        sprint_trigger = (sprint, time.monotonic() + 0.3)
                    if phase == "JUMP_INPUT" and args.scenario == "sprint-jump" and sprint_jump_key is not None:
                        keys.press((sprint_jump_key,), launcher, 0.18)
                    key = (active_view, phase)
                    if key in expected and key not in seen:
                        pose = STILL_NAMES.get(phase, phase.lower().replace("_", "-"))
                        name = f"{active_view}-{pose}.png"
                        delay = capture_phases[phase]
                        time.sleep(delay)
                        image = obs.screenshot(setup.capture_width)
                        issue, signature = inspect_capture(image)
                        if not issue and previous_capture is not None and signature == previous_capture:
                            issue = "same pixels as the preceding capture"
                        previous_capture = signature
                        (directory / name).write_bytes(image)
                        timecode = obs.call("GetRecordStatus")["outputDuration"]
                        _, zone, side = PRESETS.get(
                            active_view, (None, "hands-and-sleeves", "player"),
                        )
                        result["screenshots"].append(name)
                        result["captures"].append({
                            "file": name, "pose": pose, "phase": phase, "preset": active_view,
                            "zone": zone, "side": side, "video_time_ms": timecode,
                            "delay_after_phase_ms": round(delay * 1000),
                            "quality": "REVIEW" if issue else "OK",
                        })
                        if issue:
                            result["capture_issues"].append({"file": name, "issue": issue})
                        seen.add(key)
                    if phase in {"COMPLETE", "FAILED"}:
                        return line
                    if phase == "ROUTE_TIMEOUT":
                        return "FAILED " + line
                return None

            timeout = 180 if args.scenario == "locomotion" else 105
            status = wait_for(launcher, timeout, "scenario completion", scenario_finished)
            if phase_name(status) != "COMPLETE":
                raise RuntimeError(status)
            if missing := expected - seen:
                raise RuntimeError(f"Missing captures: {sorted(missing)}")
        finally:
            try:
                try:
                    keys.release()
                finally:
                    if recording:
                        result["video"] = finish_video(obs, directory)
            finally:
                try:
                    if launcher is not None:
                        result["game_exit"] = close_game(launcher, directory)
                finally:
                    try:
                        if record_directory_changed:
                            obs.call("SetRecordDirectory", recordDirectory=previous_record_directory)
                    finally:
                        try:
                            for name in muted_inputs:
                                obs.call("SetInputMute", inputName=name, inputMuted=False)
                        finally:
                            obs.call("SetCurrentProgramScene", sceneName=previous_scene)


def run_case(args, directory):
    directory.mkdir()
    result = {
        "status": "FAILED", "scenario": args.scenario, "camera": args.camera or "scenario",
        "screenshots": [], "captures": [], "capture_issues": [],
        "pieces": [{"plugin": plugin, "local_form_id": form_id} for plugin, form_id in args.pieces],
    }
    try:
        execute(args, directory, result)
        result["status"] = "REVIEW" if result["capture_issues"] else "COMPLETE"
    except Exception as error:
        result["error"] = str(error)
    finally:
        result["phases"] = read_phases(directory)
        write_json(directory / "result.json", result)
    return {"scenario": args.scenario, "status": result["status"], "report": str(directory / "result.json")}


def parse_piece(value):
    plugin, separator, form = value.rpartition(":")
    if not separator or not re.fullmatch(r"[A-Za-z0-9_ .-]+\.(esp|esm|esl)", plugin, re.IGNORECASE):
        raise argparse.ArgumentTypeError("Use PLUGIN:FORM_ID, for example Outfit.esp:0x801.")
    try:
        form_id = int(form, 0)
    except ValueError:
        raise argparse.ArgumentTypeError("Use a decimal or hexadecimal local FormID.") from None
    if not 0 < form_id <= 0xFFFFFF:
        raise argparse.ArgumentTypeError("Use a nonzero local FormID.")
    return plugin, form_id


def batch_status(outcomes):
    for status in ("FAILED", "REVIEW"):
        if any(outcome["status"] == status for outcome in outcomes):
            return status
    return "COMPLETE"


def write_json(path, data):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def run_batch(args, scenarios):
    output = args.setup.output_directory
    output.mkdir(parents=True, exist_ok=True)
    batch = Path(tempfile.mkdtemp(prefix=time.strftime("%Y%m%d-%H%M%S-"), dir=output))
    outcomes = []
    for name in scenarios:
        case = argparse.Namespace(**(vars(args) | {"scenario": name}))
        outcomes.append(run_case(case, batch / name))
        if len(scenarios) > 1:
            status = batch_status(outcomes) if len(outcomes) == len(scenarios) else "RUNNING"
            write_json(batch / "suite.json", {"status": status, "scenarios": outcomes})
    status = batch_status(outcomes)
    report = batch / "suite.json" if len(scenarios) > 1 else outcomes[0]["report"]
    print(json.dumps({"status": status, "report": str(report)}), flush=True)
    return {"COMPLETE": 0, "FAILED": 1, "REVIEW": 3}[status]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--setup", required=True, type=Path, help="Path to your local TOML setup")
    parser.add_argument("--piece", dest="pieces", type=parse_piece, action="append", required=True,
                        help="Installed PLUGIN:FORM_ID. Repeat to equip several pieces.")
    parser.add_argument("--scenario", choices=[*SCENARIOS, "all"], action="append", required=True,
                        help="Repeat to select more than one scenario")
    parser.add_argument("--camera", choices=PRESETS, help="Select a single fixed camera for one scenario")
    parser.add_argument("--check", action="store_true", help="Validate the configured setup without opening Fallout 4")
    args = parser.parse_args()
    if args.scenario == ["all"]:
        scenarios = tuple(SCENARIOS)
    elif "all" in args.scenario:
        parser.error("--scenario all already includes every scenario")
    else:
        scenarios = tuple(dict.fromkeys(args.scenario))
    if args.camera and (len(scenarios) != 1 or scenarios[0] in {"first-person", "workbench", "sprint-jump"}):
        parser.error("Choose one fixed-camera scenario to use --camera.")
    if len({(p.casefold(), f) for p, f in args.pieces}) != len(args.pieces) or len(args.pieces) > 32:
        parser.error("Provide up to 32 distinct pieces.")
    try:
        args.setup = read_setup(args.setup.resolve())
        args.data = verify_setup(args.setup, args.pieces)
        if args.check:
            assert_game_closed()
            with OBS(args.setup) as obs:
                obs.check_scene()
            print(json.dumps({"status": "READY"}))
            return 0
        with (Path(tempfile.gettempdir()) / "fallout4-outfit-tests.lock").open("a+b") as lock:
            lock.seek(0)
            try:
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                parser.error("Another Fallout 4 outfit test is running on this computer.")
            return run_batch(args, scenarios)
    except (OSError, RuntimeError, ValueError, websocket.WebSocketException) as error:
        print(json.dumps({"status": "FAILED", "error": str(error)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
