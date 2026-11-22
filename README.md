# Fallout 4 Outfit Tests

Run a repeatable in-game test of an installed outfit. The runner loads a reference save, equips the pieces you select, plays the requested scenarios and captures them through OBS. It writes a JSON report that an agent can use to find the relevant still and the matching point in the recording.

## Set up your machine

1. Use a Windows desktop with Fallout 4 Steam **1.11.240**, [F4SE **0.7.9**](https://f4se.silverlock.org/), and Python 3.11 or later. Install dependencies with `python -m pip install -r requirements.txt`.
2. Build and install the [test mod](mod/BUILD.md), and enable `OutfitTests.esp` plus any plugins that supply your outfit pieces. The runner reads the files deployed in the game's `Data` directory and the active `plugins.txt` you specify.
3. Create a manual save inside `QASmoke`. You can reach the cell with `coc QASmoke` in the game console. Leave the character standing outside power armor. Close the game. Install [Start On Save AE](https://www.nexusmods.com/fallout4/mods/99192) and set its `Save File` entry to that save's filename without the `.fos` extension. The route and furniture scenarios use the layout of this cell.
4. In OBS, create a scene with one enabled Game Capture source targeting the Fallout 4 window. Fit the source to the canvas. Enable the authenticated OBS WebSocket server and leave OBS open and idle.

Create a TOML file for your machine. Paths can be absolute or relative to that file. Use single-quoted strings for paths with Windows backslashes. Supply each field.

| Field | Value |
| --- | --- |
| `f4se_loader` | Path to `f4se_loader.exe` in your Fallout 4 installation |
| `reference_save` | Path to the manual `.fos` save used by Start On Save AE |
| `plugins_file` | Path to the active Fallout 4 `plugins.txt` |
| `obs_config` | Path to OBS's WebSocket `config.json` |
| `obs_scene`, `obs_source` | Exact names of your test scene and Game Capture source |
| `capture_width` | Width of PNG captures in pixels, from 320 to 4096 |
| `output_directory` | Directory for reports, PNGs and recordings |

OBS owns the WebSocket password. Keep the TOML file and OBS configuration on your machine.

## Run a test

From the repository root, supply your setup path, the outfit pieces, and the scenarios you want to run. Replace the placeholders with values from your own setup. The local FormID must refer to an armor record. Repeat `--piece` for each piece.

```powershell
python run.py --setup "<setup.toml>" --piece "<plugin>:<local-form-id>" --scenario standing --check
python run.py --setup "<setup.toml>" --piece "<plugin>:<local-form-id>" --scenario standing
```

`--check` returns `READY` after it verifies the setup, installed plugin files and OBS scene. For a first game test you can select a vanilla armor record from `Fallout4.esm`. Use `python run.py --help` to list the scenarios and fixed camera angles.

Keep Fallout 4 in the foreground during `sprint-jump`. That scenario uses the game's keyboard bindings and the mouse wheel. The other scenarios use in-game scripting. Each scenario launches a fresh game session from the reference save.

The last line printed by a run is JSON containing the status and report path. A single scenario produces `result.json`. A multi-scenario run produces a `suite.json` with links to its per-scenario reports.

| Exit code | Status | Meaning |
| --- | --- | --- |
| 0 | `COMPLETE` | The expected phases and captures completed |
| 1 | `FAILED` | Open the report and check the error and the last phase |
| 2 | CLI usage error | Correct the arguments shown in the error |
| 3 | `REVIEW` | Check `capture_issues` for a black or repeated frame, then rerun the affected scenario |

For a fit review, open the relevant PNG and use its `video_time_ms` to find the gesture in the recording. The runner checks the capture and game sequence. Inspect the garment and framing in the resulting media.
