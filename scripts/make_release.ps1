param(
    [string]$Version = "0.1.0",
    [string]$AppName = "PoE2PriceTracker",
    [string]$DownloadBaseUrl = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$ExePath = Join-Path $Root "dist\$AppName.exe"
$FolderPath = Join-Path $Root "dist\$AppName"
$ReleaseDir = Join-Path $Root "release"
$ZipPath = Join-Path $ReleaseDir "PoE2PriceTracker-$Version.zip"

if ((-not (Test-Path $ExePath)) -and (-not (Test-Path $FolderPath))) {
    throw "Build output not found. Run scripts\build.ps1 first."
}

New-Item -ItemType Directory -Force -Path $ReleaseDir | Out-Null
if (Test-Path $ZipPath) {
    try {
        Remove-Item -LiteralPath $ZipPath -Force
    }
    catch {
        $Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
        $ZipPath = Join-Path $ReleaseDir "PoE2PriceTracker-$Version-$Stamp.zip"
        Write-Warning "Could not replace existing zip. Writing timestamped release: $ZipPath"
    }
}

if (Test-Path $FolderPath) {
    Compress-Archive -Path (Join-Path $FolderPath "*") -DestinationPath $ZipPath
}
else {
    Compress-Archive -Path $ExePath -DestinationPath $ZipPath
}
$Hash = (Get-FileHash $ZipPath -Algorithm SHA256).Hash.ToLowerInvariant()

$DownloadUrl = (Resolve-Path $ZipPath).Path
if ($DownloadBaseUrl.Trim()) {
    $DownloadUrl = $DownloadBaseUrl.TrimEnd("/") + "/" + (Split-Path -Leaf $ZipPath)
}

$Manifest = @{
    version = $Version
    download_url = $DownloadUrl
    sha256 = $Hash
} | ConvertTo-Json

$ManifestPath = Join-Path $ReleaseDir "latest.json"
$Manifest | Set-Content -Path $ManifestPath -Encoding UTF8

Write-Host "Release zip: $ZipPath"
Write-Host "Manifest: $ManifestPath"
