param(
    [string]$Version = "0.1.0",
    [string]$AppName = "PoE2PriceTracker",
    [string]$DownloadBaseUrl = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$ExePath = Join-Path $Root "dist\$AppName-$Version.exe"
$LegacyExePath = Join-Path $Root "dist\$AppName.exe"
$ReleaseDir = Join-Path $Root "release"

if (-not (Test-Path $ExePath)) {
    $ExePath = $LegacyExePath
}
if (-not (Test-Path $ExePath)) {
    throw "Build output not found. Run scripts\build.ps1 first."
}

New-Item -ItemType Directory -Force -Path $ReleaseDir | Out-Null
$Hash = (Get-FileHash $ExePath -Algorithm SHA256).Hash.ToLowerInvariant()

$AssetName = Split-Path -Leaf $ExePath
$DownloadUrl = $AssetName
if ($DownloadBaseUrl.Trim()) {
    $DownloadUrl = $DownloadBaseUrl.TrimEnd("/") + "/" + $AssetName
}

$Manifest = @{
    version = $Version
    download_url = $DownloadUrl
    sha256 = $Hash
} | ConvertTo-Json

$ManifestPath = Join-Path $ReleaseDir "latest.json"
$Manifest | Set-Content -Path $ManifestPath -Encoding UTF8

Write-Host "Release exe: $ExePath"
Write-Host "Manifest: $ManifestPath"
