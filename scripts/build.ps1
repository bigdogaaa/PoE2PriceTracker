param(
    [string]$Python = "py",
    [string[]]$PythonArgs = @("-3.12"),
    [string]$AppName = "PoE2PriceTracker",
    [string]$Version = "",
    [switch]$OneFile
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (-not $Version) {
    $ProjectText = Get-Content -Path "pyproject.toml" -Raw
    if ($ProjectText -match 'version\s*=\s*"([^"]+)"') {
        $Version = $Matches[1]
    }
}
$BuildName = if ($OneFile -and $Version) { "$AppName-$Version" } else { $AppName }

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
Invoke-Checked $BuildPython @("-m", "pip", "install", "-r", "requirements.txt")

$PyInstallerArgs = @(
    "-m", "PyInstaller",
    "--noconfirm",
    "--clean",
    "--windowed",
    "--workpath", "build\$BuildName",
    "--exclude-module", "PIL.ImageQt",
    "--collect-all", "rapidocr",
    "--collect-binaries", "onnxruntime",
    "--hidden-import", "rapidocr",
    "--hidden-import", "onnxruntime",
    "--name", $BuildName,
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

$AssetBundle = Join-Path $Root "src\poe2_price_tracker\assets"
if (Test-Path $AssetBundle) {
    $PyInstallerArgs = $PyInstallerArgs[0..($PyInstallerArgs.Length - 2)] + @("--add-data", "src\poe2_price_tracker\assets;poe2_price_tracker\assets") + $PyInstallerArgs[($PyInstallerArgs.Length - 1)]
    Write-Host "Including bundled assets: $AssetBundle"
}

Invoke-Checked $BuildPython $PyInstallerArgs

if ($OneFile) {
    $BuiltPath = Join-Path $Root "dist\$BuildName.exe"
    Write-Host "Built: $BuiltPath"
}
else {
    $BuiltPath = Join-Path $Root "dist\$AppName\$AppName.exe"
    Write-Host "Built: $BuiltPath"
}
