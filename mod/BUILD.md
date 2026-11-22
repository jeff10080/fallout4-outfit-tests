# Build the test mod

Use a Visual Studio x64 developer PowerShell on Windows. Gather the [F4SE 0.7.9 source](https://github.com/ianpatt/f4se), its [common headers](https://github.com/ianpatt/common), [Caprica](https://github.com/Orvid/Caprica), [BSArch](https://github.com/TES5Edit/TES5Edit/tree/dev-4.1.6/BSArch) and the Fallout 4 Creation Kit Papyrus sources and flags. For the F4SE Papyrus imports, use a directory containing `Input.psc` and `UI.psc` from F4SE 0.7.9.

Run both commands from the repository root, replacing each path with the location on your machine.

```powershell
./mod/build_camera.ps1 -F4SESource "<f4se-source>" -CommonSource "<common-parent>" -OutputDirectory "<build-directory>"
python mod/build.py --compiler "<Caprica.exe>" --imports "<Creation Kit Base source>" "<F4SE Papyrus imports>" --flags "<flags.flg>" --bsarch "<BSArch64.exe>" --camera-dll "<build-directory>/OutfitTestCamera.dll" --output "<output.zip>"
```

The include directory passed as `-CommonSource` must contain `common/IPrefix.h`. For the Papyrus imports, the compiler needs one definition for each script. Use the F4SE `Input` and `UI` definitions if the Creation Kit sources contain copies.

The build checks the compiled script format, the packaged script bytes and the ZIP. Install that ZIP with your mod manager and enable `OutfitTests.esp`. The ZIP contains the test plugin, its own scripts and the camera DLL. Install F4SE and the other runtime dependencies separately.
