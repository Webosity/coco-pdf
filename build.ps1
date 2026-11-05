# Build dist\CocoPDF (portable folder) then dist\CocoPDF-Setup-<version>.exe
# Exit codes are checked explicitly: PowerShell 5.1 turns PyInstaller's stderr logging into errors under "Stop".
$ErrorActionPreference = "Continue"
$python = "$env:USERPROFILE\.venvs\coco-pdf\Scripts\python.exe"
$iscc = "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"

Set-Location $PSScriptRoot
& $python -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "Tests failed" }
Remove-Item -Recurse -Force build, dist -ErrorAction SilentlyContinue
& $python -m PyInstaller coco-pdf.spec --noconfirm --log-level WARN
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }
& $iscc /Q installer.iss
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }
Get-ChildItem dist\*.exe | Select-Object Name, @{n = "MB"; e = { [math]::Round($_.Length / 1MB, 1) } }
