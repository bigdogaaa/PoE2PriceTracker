param(
    [string]$Python = "py",
    [string[]]$PythonArgs = @("-3.12"),
    [string]$AppName = "PoE2PriceTracker",
    [string]$Version = "",
    [string]$Suffix = "",
    [switch]$Test,
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
$OneFile = $true

function ConvertTo-SafeNamePart {
    param([string]$Value)
    $Safe = ($Value.Trim() -replace '^[\s\-_]+', '' -replace '[\\/:*?"<>|\s]+', '-').Trim("-_.")
    return $Safe
}

if ($Test -and -not $Suffix.Trim()) {
    $Suffix = "test"
}

$SafeSuffix = ConvertTo-SafeNamePart $Suffix
$BuildName = if ($Version) { "$AppName-$Version" } else { $AppName }
if ($SafeSuffix) {
    $BuildName = "$BuildName-$SafeSuffix"
}

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
    "--optimize", "1",
    "--workpath", "build\$BuildName",
    "--distpath", "dist",
    "--onefile",
    "--icon", "src\poe2_price_tracker\assets\app_icon.ico",
    "--additional-hooks-dir", "scripts\pyinstaller_hooks",
    "--exclude-module", "PIL.ImageQt",
    "--exclude-module", "pandas",
    "--exclude-module", "pyarrow",
    "--exclude-module", "pytest",
    "--exclude-module", "matplotlib",
    "--exclude-module", "scipy",
    "--exclude-module", "sklearn",
    "--exclude-module", "IPython",
    "--exclude-module", "jupyter",
    "--exclude-module", "notebook",
    "--exclude-module", "torch",
    "--exclude-module", "tensorflow",
    "--exclude-module", "paddle",
    "--exclude-module", "paddleocr",
    "--exclude-module", "openvino",
    "--exclude-module", "tensorrt",
    "--exclude-module", "MNN",
    "--exclude-module", "sympy",
    "--exclude-module", "mpmath",
    "--exclude-module", "onnxruntime.tools",
    "--exclude-module", "onnxruntime.transformers",
    "--exclude-module", "rapidocr.inference_engine.pytorch",
    "--exclude-module", "rapidocr.inference_engine.paddle",
    "--exclude-module", "rapidocr.inference_engine.openvino",
    "--exclude-module", "rapidocr.inference_engine.tensorrt",
    "--exclude-module", "rapidocr.inference_engine.mnn",
    "--collect-data", "rapidocr",
    "--collect-binaries", "onnxruntime",
    "--hidden-import", "rapidocr",
    "--hidden-import", "rapidocr.inference_engine.onnxruntime",
    "--hidden-import", "onnxruntime",
    "--name", $BuildName,
    "--paths", "src",
    "src\poe2_price_tracker\__main__.py"
)

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

$StaticBundle = Join-Path $Root "static"
if (Test-Path $StaticBundle) {
    $PyInstallerArgs = $PyInstallerArgs[0..($PyInstallerArgs.Length - 2)] + @("--add-data", "static;static") + $PyInstallerArgs[($PyInstallerArgs.Length - 1)]
    Write-Host "Including static assets: $StaticBundle"
}

Invoke-Checked $BuildPython $PyInstallerArgs

$BuiltPath = Join-Path $Root "dist\$BuildName.exe"
$SpecPath = Join-Path $Root "$BuildName.spec"
if (Test-Path -LiteralPath $SpecPath) {
    Remove-Item -LiteralPath $SpecPath -Force
}
Write-Host "Built: $BuiltPath"
