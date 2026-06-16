param(
    [string]$Python = "py",
    [string[]]$PythonArgs = @("-3.12"),
    [string]$AppName = "PoE2PriceTracker",
    [switch]$OneFile
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Invoke-Checked {
    param([string]$Exe, [string[]]$ArgList)
    & $Exe @ArgList
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed: $Exe $($ArgList -join ' ')"
    }
}

function Invoke-Python {
    param([string[]]$ArgList)
    Invoke-Checked $Python ($PythonArgs + $ArgList)
}

if (-not (Test-Path ".build-venv")) {
    Invoke-Python @("-m", "venv", ".build-venv")
}

$BuildPython = Join-Path $Root ".build-venv\Scripts\python.exe"
& $BuildPython -m pip --version | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Warning ".build-venv does not have pip. Bootstrapping pip with the selected Python."
    Invoke-Python @("-m", "pip", "--python", $BuildPython, "install", "--upgrade", "pip")
}

Invoke-Checked $BuildPython @("-m", "pip", "install", "--upgrade", "pip")
Invoke-Checked $BuildPython @("-m", "pip", "install", "-r", "requirements-build.txt")

$PyInstallerArgs = @(
    "-m", "PyInstaller",
    "--noconfirm",
    "--clean",
    "--windowed",
    "--exclude-module", "numpy",
    "--exclude-module", "PIL.ImageQt",
    "--name", $AppName,
    "--paths", "src",
    "src\poe2_price_tracker\__main__.py"
)
if ($OneFile) {
    $PyInstallerArgs = $PyInstallerArgs[0..4] + @("--onefile") + $PyInstallerArgs[5..($PyInstallerArgs.Length - 1)]
}

$OcrBundle = Join-Path $Root "tools\ocr"
if (Test-Path $OcrBundle) {
    $PyInstallerArgs = $PyInstallerArgs[0..($PyInstallerArgs.Length - 2)] + @("--add-data", "tools\ocr;ocr") + $PyInstallerArgs[($PyInstallerArgs.Length - 1)]
    Write-Host "Including OCR bundle: $OcrBundle"
}

Invoke-Checked $BuildPython $PyInstallerArgs

if ($OneFile) {
    Write-Host "Built: $Root\dist\$AppName.exe"
}
else {
    Write-Host "Built: $Root\dist\$AppName\$AppName.exe"
}
