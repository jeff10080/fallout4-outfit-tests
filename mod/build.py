"""Compile and package the Fallout 4 outfit test mod."""

import argparse
from pathlib import Path
import re
import struct
import subprocess
import tempfile
from zipfile import ZIP_DEFLATED, ZipFile


HERE = Path(__file__).resolve().parent
STEM = "OutfitTests"
SCRIPT = "OutfitTestQuest"
CAMERA = "OutfitTestCamera"
PROPERTIES = {
    "TestCell": 0x0001F7A9,          # QASmoke
    "TestPistol": 0x00004822,        # 10mm
    "TestAmmo": 0x0001F276,          # Ammo10mm
    "SheatheAction": 0x00046BAF,     # ActionSheath
    "AimAction": 0x00004A57,         # ActionSighted
    "ReleaseAimAction": 0x00004A58,  # ActionSightedRelease
    "FireAction": 0x00004A5A,        # ActionFireSingle
    "ReloadAction": 0x00004A56,      # ActionReload
}


def pack_record(signature, form_id, version, fields):
    payload = b"".join(struct.pack("<4sH", key, len(value)) + value for key, value in fields)
    return struct.pack("<4sIIIIHH", signature, len(payload), 0, form_id, 0, version, 0) + payload


def group(signature, record):
    return struct.pack("<4sI4sI8x", b"GRUP", 24 + len(record), signature, 0) + record


def papyrus_string(value):
    encoded = value.encode("ascii")
    return struct.pack("<H", len(encoded)) + encoded


def quest_script(source):
    declared = set(re.findall(r"^\w+ Property (\w+) Auto Const$", source, re.MULTILINE))
    if declared != PROPERTIES.keys():
        raise ValueError(f"VMAD properties differ from {SCRIPT}.psc")

    fields = [struct.pack("<HHH", 6, 2, 1), papyrus_string(SCRIPT)]
    fields.append(struct.pack("<BH", 0, len(PROPERTIES)))
    for name, form_id in PROPERTIES.items():
        fields.extend((papyrus_string(name), struct.pack("<BBHHI", 1, 1, 0, 0xFFFF, form_id)))
    return b"".join(fields)


def make_plugin(source):
    header = pack_record(b"TES4", 0, 131, [
        (b"HEDR", struct.pack("<fII", 1.0, 2, 0x801)),
        (b"CNAM", b"Fallout 4 Outfit Tests\0"),
        (b"SNAM", b"Outfit testing in QASmoke\0"),
        (b"MAST", b"Fallout4.esm\0"),
        (b"DATA", bytes(8)),
        (b"INCC", bytes(4)),
    ])
    quest = pack_record(b"QUST", 0x01000800, 118, [
        (b"EDID", b"OutfitTestsQuest\0"),
        (b"VMAD", quest_script(source)),
        (b"DNAM", struct.pack("<H", 0x0011) + bytes(10)),
        (b"NEXT", b""),
        (b"ANAM", bytes(4)),
    ])
    return header + group(b"QUST", quest)


def build(compiler, imports, flags, bsarch, camera_dll, output):
    source = HERE / f"{SCRIPT}.psc"
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="outfit_tests_", dir=output.parent) as temp:
        temp = Path(temp)
        scripts = temp / "Data" / "Scripts"
        scripts.mkdir(parents=True)
        sequence = scripts.parent / "SEQ"
        sequence.mkdir()
        (sequence / f"{STEM}.seq").write_bytes(struct.pack("<I", 0x01000800))
        subprocess.run([
            compiler, ".", "--game=fallout4", "--release", "--strict",
            "--all-warnings-as-errors",
            "--import", ";".join(str(path) for path in imports),
            "--flags", flags, "--output", scripts,
        ], cwd=HERE, check=True)
        compiled_scripts = [scripts / f"{name}.pex" for name in (SCRIPT, CAMERA)]
        for pex in compiled_scripts:
            if pex.read_bytes()[:8] != bytes.fromhex("de c0 57 fa 03 09 02 00"):
                raise ValueError(f"{pex.name} is not Fallout 4 Papyrus bytecode")

        archive = temp / f"{STEM} - Main.ba2"
        subprocess.run([bsarch, "pack", scripts.parent, archive, "-fo4", "-q"], check=True)
        unpacked = temp / "unpacked"
        unpacked.mkdir()
        subprocess.run([bsarch, "unpack", archive, unpacked, "-q"], check=True)
        for pex in compiled_scripts:
            if (unpacked / "Scripts" / pex.name).read_bytes() != pex.read_bytes():
                raise ValueError(f"{pex.name} in the BA2 differs from the compiler output")

        plugin = make_plugin(source.read_text(encoding="utf-8"))
        with ZipFile(temp / output.name, "w", ZIP_DEFLATED) as package:
            package.writestr(f"{STEM}.esp", plugin)
            package.write(archive, archive.name)
            package.write(camera_dll, f"F4SE/Plugins/{CAMERA}.dll")
        with ZipFile(temp / output.name) as package:
            if package.testzip() is not None:
                raise ValueError("Mod ZIP integrity check failed")
        (temp / output.name).replace(output)
    print(output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", type=Path, required=True, help="Caprica executable")
    parser.add_argument("--imports", type=Path, nargs="+", required=True, help="Papyrus source directories")
    parser.add_argument("--flags", type=Path, required=True, help="Institute_Papyrus_Flags.flg")
    parser.add_argument("--camera-dll", type=Path, required=True, help="Compiled F4SE camera plugin")
    parser.add_argument("--bsarch", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    build(args.compiler.resolve(), [p.resolve() for p in args.imports], args.flags.resolve(),
          args.bsarch.resolve(), args.camera_dll.resolve(), args.output.resolve())
