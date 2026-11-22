param(
    [Parameter(Mandatory)][string]$F4SESource,
    [Parameter(Mandatory)][string]$CommonSource,
    [Parameter(Mandatory)][string]$OutputDirectory
)

$ErrorActionPreference = 'Stop'
$f4se = (Resolve-Path -LiteralPath $F4SESource).Path
$common = (Resolve-Path -LiteralPath $CommonSource).Path
$output = (New-Item -ItemType Directory -Force -Path $OutputDirectory).FullName
$compiler = (Get-Command cl.exe -ErrorAction Stop).Source
$sources = @(
    'f4se/GameAPI.cpp'
    'f4se/GameExtraData.cpp'
    'f4se/GameTypes.cpp'
    'f4se/GameUtilities.cpp'
    'f4se/PapyrusArgs.cpp'
    'f4se/PapyrusInterfaces.cpp'
    'f4se/PapyrusValue.cpp'
    'f4se/PapyrusVM.cpp'
    'f4se_common/Relocation.cpp'
) | ForEach-Object { Join-Path $f4se $_ }
$options = @(
    '/nologo', '/std:c++20', '/EHsc', '/O2', '/MT', '/Gy', '/Gw', '/LD',
    '/DNDEBUG', '/DRUNTIME', '/DRUNTIME_VERSION=0x010B0F00',
    '/FIcommon/IPrefix.h', "/I$f4se", "/I$common"
)

Push-Location -LiteralPath $output
try {
    & $compiler @options (Join-Path $PSScriptRoot 'camera.cpp') @sources /link /OPT:REF /OPT:ICF /OUT:OutfitTestCamera.dll
    if ($LASTEXITCODE -ne 0) {
        throw "Camera compilation failed with exit code $LASTEXITCODE."
    }
}
finally {
    Pop-Location
}
