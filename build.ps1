# Build dist\CocoPDF (portable folder), then dist\CocoPDF-<version>.msix (Microsoft Store)
# and dist\CocoPDF-Setup-<version>.exe (Inno Setup, skipped when Inno Setup is not installed).
# Exit codes are checked explicitly: PowerShell 5.1 turns PyInstaller's stderr logging into errors under "Stop".
$ErrorActionPreference = "Continue"
$python = "$env:USERPROFILE\.venvs\coco-pdf\Scripts\python.exe"
$iscc = "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
$makeappx = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin\*\x64\makeappx.exe" -ErrorAction SilentlyContinue |
    Sort-Object FullName | Select-Object -Last 1 -ExpandProperty FullName

Set-Location $PSScriptRoot
& $python -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "Tests failed" }
Remove-Item -Recurse -Force build, dist -ErrorAction SilentlyContinue
& $python -m PyInstaller coco-pdf.spec --noconfirm --log-level WARN
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

# MSIX: left unsigned, the Microsoft Store signs it on publication.
if (-not $makeappx) { throw "makeappx.exe not found: install the Windows SDK" }
$version = (Select-String -Path coco_pdf\__init__.py -Pattern '__version__ = "(.+)"').Matches[0].Groups[1].Value
$layout = "build\msix"
Copy-Item -Recurse dist\CocoPDF $layout
Copy-Item -Recurse msix\Assets "$layout\Assets"
(Get-Content msix\AppxManifest.xml -Raw -Encoding UTF8).Replace("{version}", "$version.0") |
    Set-Content "$layout\AppxManifest.xml" -Encoding UTF8
& $makeappx pack /o /d $layout /p "dist\CocoPDF-$version.msix"
if ($LASTEXITCODE -ne 0) { throw "makeappx failed" }

if (Test-Path $iscc) {
    & $iscc /Q installer.iss
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }
} else {
    Write-Warning "Inno Setup not found: setup .exe skipped"
}
Get-ChildItem dist\*.exe, dist\*.msix | Select-Object Name, @{n = "MB"; e = { [math]::Round($_.Length / 1MB, 1) } }
