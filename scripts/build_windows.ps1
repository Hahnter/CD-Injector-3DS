# Packages CD Injector 3DS as a standalone Windows app (folder + zip) with PyInstaller.
# Needs: Python 3.10+ with Pillow and PyInstaller, and resources/ filled by scripts/build_emulators.sh.
#
#   powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1 [-Python .venv\Scripts\python.exe] [-DistPath dist]
#
# Makes, in -DistPath:
#   CD-Injector-3DS\                                   the app (CD-Injector-3DS.exe), with its documents and licences
#   CD-Injector-3DS-v<version>-windows.zip             that folder, zipped
#   CD-Injector-3DS-v<version>-emulator-source.tar.gz  the patched emulator source (from build_emulators.sh)
#   SHA256SUMS.txt                                     checksums of both

param([string]$Python = "python", [string]$DistPath = "dist", [switch]$SkipChecks)

$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent $PSScriptRoot
Set-Location $Repo

foreach ($need in @("resources\cores\temperpce\emulator.elf", "resources\cores\picodrive\emulator.elf",
                    "resources\tools\windows\makerom.exe", "resources\tools\windows\bannertool.exe",
                    "dist\emulator-source.tar.gz")) {
    if (-not (Test-Path $need)) { throw "Missing $need - run scripts/build_emulators.sh first." }
}

# The last gate before anything is packaged: no hidden characters or metadata, and all the tests pass.
if (-not $SkipChecks) {
    & $Python scripts\hygiene.py
    if ($LASTEXITCODE -ne 0) { throw "scripts\hygiene.py found something: fix it (scripts\hygiene.py --fix) and build again." }
    & $Python -m unittest discover -s tests -t .
    if ($LASTEXITCODE -ne 0) { throw "The tests failed: nothing was packaged." }
}

$Version = & $Python -c "import cdinjector; print(cdinjector.VERSION)"
$Name = "CD Injector 3DS"                     # the app's name, as Windows shows it
$ExeName = "CD-Injector-3DS"                  # its file and folder name: no spaces, so the command line needs no quotes
$Base = "CD-Injector-3DS-v$Version"
$Build = Join-Path $Repo "build"

# Version details shown in the .exe's Properties window
$Nums = (($Version -split "\.") + @("0", "0", "0"))[0..3] -join ", "
New-Item -ItemType Directory -Force $Build | Out-Null
@"
VSVersionInfo(
  ffi=FixedFileInfo(filevers=($Nums), prodvers=($Nums)),
  kids=[StringFileInfo([StringTable('040904B0', [
    StringStruct('CompanyName', 'Hahnter'),
    StringStruct('FileDescription', '$Name'),
    StringStruct('FileVersion', '$Version'),
    StringStruct('InternalName', '$ExeName'),
    StringStruct('LegalCopyright', 'Copyright (c) 2026 Hahnter. MIT License; bundled components keep their own licences.'),
    StringStruct('OriginalFilename', '$ExeName.exe'),
    StringStruct('ProductName', '$Name'),
    StringStruct('ProductVersion', '$Version')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])]
)
"@ | Set-Content -Encoding ascii (Join-Path $Build "version_info.txt")     # ascii: no byte-order mark

# Absolute paths: PyInstaller reads relative ones from the spec file's folder (build\).
& $Python -m PyInstaller --noconfirm --clean --windowed --onedir `
    --name $ExeName `
    --version-file (Join-Path $Build "version_info.txt") `
    --add-data ((Join-Path $Repo "resources\cores") + ";resources\cores") `
    --add-data ((Join-Path $Repo "resources\tools\windows") + ";resources\tools\windows") `
    --add-data ((Join-Path $Repo "resources\fonts") + ";resources\fonts") `
    --exclude-module numpy `
    --distpath $DistPath --workpath (Join-Path $Build "pyinstaller") --specpath $Build `
    cd_injector.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

# Docs next to the .exe where people will see them, and the licences of everything packaged with it
$App = "$DistPath\$ExeName"
Copy-Item README.md, CHANGELOG.md, LICENSE, THIRD-PARTY-NOTICES.md, SECURITY.md $App
& $Python scripts\collect_licenses.py "$App\licenses"
if ($LASTEXITCODE -ne 0) { throw "Couldn't collect the licence texts" }
Copy-Item resources\fonts\OFL.txt "$App\licenses\M-PLUS-1p-OFL.txt"

$Zip = "$DistPath\$Base-windows.zip"
$Src = "$DistPath\$Base-emulator-source.tar.gz"
Copy-Item "dist\emulator-source.tar.gz" $Src -Force

# The zip is made by Python: PowerShell 5's Compress-Archive writes "\" into the names, which other unzip tools
# don't understand. The checksum file uses "\n" line ends so `sha256sum -c` works too, as does
# Get-FileHash <file> -Algorithm SHA256 on Windows.
& $Python scripts\package_release.py $App $Zip $Src "$DistPath\SHA256SUMS.txt"
if ($LASTEXITCODE -ne 0) { throw "Packaging the zip failed" }
Write-Output "Built $App\$ExeName.exe, $Zip and $Src"
Get-Content "$DistPath\SHA256SUMS.txt"
