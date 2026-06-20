param(
    [ValidateSet("syntax", "unit", "gui", "all", "clean")]
    [string]$Suite = "unit",
    [string]$K = "",
    [switch]$KeepCache
)

& (Join-Path $PSScriptRoot "test_runner.ps1") -Suite $Suite -K $K -KeepCache:$KeepCache
return

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$env:PYTHONDONTWRITEBYTECODE = "1"
$env:PYTHONPATH = "src"

function Invoke-PythonCheck {
    param([string]$Code)
    $TempFile = Join-Path $env:TEMP ("poe2_price_tracker_check_" + [guid]::NewGuid().ToString("N") + ".py")
    Set-Content -LiteralPath $TempFile -Value $Code -Encoding UTF8
    python -B $TempFile
    $Exit = $LASTEXITCODE
    Remove-Item -LiteralPath $TempFile -Force -ErrorAction SilentlyContinue
    if ($Exit -ne 0) {
        throw "Python check failed with exit code $Exit"
    }
}

Invoke-PythonCheck "import ast, pathlib; [ast.parse(p.read_text(encoding='utf-8'), filename=str(p)) for p in list(pathlib.Path('src').rglob('*.py')) + list(pathlib.Path('tests').rglob('*.py'))]; print('syntax ok')"
Invoke-PythonCheck @"
from poe2_price_tracker.parser import parse_ocr_text

p = parse_ocr_text("Orb of Alchemy\n--------\n~price 5 ex")
assert p.item_name == "Orb of Alchemy", p
assert p.amount == 5, p
assert p.currency == "Exalted Orb", p

q = parse_ocr_text("Some Unique Item\n\u552e\u4ef7: 1 \u795e\u5723\u77f3")
assert q.currency == "Divine Orb", q

r = parse_ocr_text("Perfect Jeweller's Orb\nStack Size: 1/20\nPrice: 2 Divine Orb")
assert r.item_name == "Perfect Jeweller's Orb", r
from poe2_price_tracker.parser import parse_item_price_rows
rows = parse_item_price_rows("卡兰德的魔镜 Wiki 2586\n辛格拉的发辫 Wiki 320")
assert rows[0].item_name == "卡兰德的魔镜", rows
assert rows[0].amount == 2586, rows
print("parser ok")
"@
Invoke-PythonCheck "import tempfile; from pathlib import Path; from poe2_price_tracker.db import PriceDatabase; db=PriceDatabase(Path(tempfile.gettempdir())/'poe2_price_tracker_smoke.sqlite3'); db.add_price_record('Orb of Alchemy', 5, 'Exalted Orb', 'test'); s=db.get_stats('orb alchemy'); assert s and s.latest_amount == 5; db.close(); print('db ok')"
