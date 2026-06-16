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

if (-not (Test-Path ".venv")) {
    Invoke-Checked "python" @("-m", "venv", ".venv")
}

$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
$RunPython = $VenvPython
& $RunPython -m pip --version | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Warning ".venv does not have pip. Falling back to the current Python interpreter."
    $RunPython = "python"
}

Invoke-Checked $RunPython @("-m", "pip", "install", "-r", "requirements.txt")
Invoke-Checked $RunPython @("-m", "pip", "install", "-e", ".")
Invoke-Checked $RunPython @("-m", "poe2_price_tracker")
