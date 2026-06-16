param(
    [string]$TesseractPath = "C:\Program Files\Tesseract-OCR"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Source = Resolve-Path -LiteralPath $TesseractPath
$Target = Join-Path $Root "tools\ocr\tesseract"

New-Item -ItemType Directory -Force -Path $Target | Out-Null
Copy-Item -LiteralPath (Join-Path $Source "tesseract.exe") -Destination $Target -Force

$SourceTessdata = Join-Path $Source "tessdata"
$TargetTessdata = Join-Path $Target "tessdata"
New-Item -ItemType Directory -Force -Path $TargetTessdata | Out-Null

foreach ($lang in @("eng.traineddata", "chi_sim.traineddata", "osd.traineddata")) {
    $file = Join-Path $SourceTessdata $lang
    if (Test-Path $file) {
        Copy-Item -LiteralPath $file -Destination $TargetTessdata -Force
    }
}

Get-ChildItem -LiteralPath $Source -Filter "*.dll" | Copy-Item -Destination $Target -Force
Write-Host "OCR bundle prepared: $Target"
