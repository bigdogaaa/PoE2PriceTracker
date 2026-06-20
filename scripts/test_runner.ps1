param(
    [ValidateSet("syntax", "unit", "gui", "all", "clean")]
    [string]$Suite = "unit",
    [string]$K = "",
    [switch]$KeepCache
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$env:PYTHONDONTWRITEBYTECODE = "1"
$env:PYTHONPATH = "src"
$env:POE2_PRICE_TRACKER_NO_ELEVATE = "1"
$env:POE2_UPDATE_CHANNEL = "test"

function Clear-TestCache {
    $patterns = @(".pytest_cache", ".mypy_cache", ".ruff_cache", ".test-cache")
    $targets = @()
    foreach ($name in $patterns) {
        $path = Join-Path $Root $name
        if (Test-Path -LiteralPath $path) {
            $targets += Get-Item -LiteralPath $path -Force
        }
    }
    $targets += Get-ChildItem -LiteralPath $Root -Force -Directory |
        Where-Object { $_.Name -like "pytest-cache-files-*" }

    $removed = 0
    $failed = 0
    foreach ($target in $targets) {
        $full = [System.IO.Path]::GetFullPath($target.FullName)
        if (-not $full.StartsWith($Root, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing to remove cache outside workspace: $full"
        }
        try {
            Remove-Item -LiteralPath $full -Recurse -Force -ErrorAction Stop
            $removed += 1
        }
        catch {
            $failed += 1
            Write-Warning "Could not remove test cache: $full"
        }
    }
    Write-Host "removed $removed test cache directories"
    if ($failed -gt 0) {
        Write-Warning "$failed test cache directories could not be removed. Run this clean step elevated if needed."
    }
}

function Invoke-PythonCode {
    param([string]$Code)
    $TempFile = Join-Path $env:TEMP ("poe2_price_tracker_check_" + [guid]::NewGuid().ToString("N") + ".py")
    Set-Content -LiteralPath $TempFile -Value $Code -Encoding UTF8
    try {
        python -B $TempFile
        if ($LASTEXITCODE -ne 0) {
            throw "Python check failed with exit code $LASTEXITCODE"
        }
    }
    finally {
        Remove-Item -LiteralPath $TempFile -Force -ErrorAction SilentlyContinue
    }
}

function Invoke-SyntaxCheck {
    Invoke-PythonCode @"
import ast
from pathlib import Path

paths = list(Path("src").rglob("*.py")) + list(Path("tests").rglob("*.py"))
for path in paths:
    ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
print(f"syntax ok ({len(paths)} files)")
"@
}

function Invoke-PytestSuite {
    param(
        [string]$Marker = "not gui and not integration and not slow",
        [switch]$RunGui
    )
    $args = @("-B", "-m", "pytest", "tests", "-q", "-m", $Marker)
    if ($K.Trim()) {
        $args += @("-k", $K)
    }
    if ($RunGui) {
        $args += "--run-gui"
    }
    python @args
    if ($LASTEXITCODE -ne 0) {
        throw "pytest failed with exit code $LASTEXITCODE"
    }
}

if (-not $KeepCache -or $Suite -eq "clean") {
    Clear-TestCache
}

switch ($Suite) {
    "clean" {
        return
    }
    "syntax" {
        Invoke-SyntaxCheck
    }
    "unit" {
        Invoke-SyntaxCheck
        Invoke-PytestSuite
    }
    "gui" {
        Invoke-PytestSuite -Marker "gui" -RunGui
    }
    "all" {
        Invoke-SyntaxCheck
        Invoke-PytestSuite -Marker "not gui"
        Invoke-PytestSuite -Marker "gui" -RunGui
    }
}

if (-not $KeepCache) {
    Clear-TestCache
}
