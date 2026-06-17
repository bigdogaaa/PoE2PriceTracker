from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from poe2_price_tracker.poe2db_sync import _fetch_html, parse_economy_html  # noqa: E402


def main() -> int:
    page = "https://poe2db.tw/cn/Economy_Currency"
    rows = parse_economy_html(_fetch_html(page), "通货", page).rows
    manifest_path = ROOT / "src" / "poe2_price_tracker" / "assets" / "icons" / "currency" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    by_name = {entry["name"]: entry for entry in manifest}
    page_names = {row.item_name for row in rows}
    missing = [row.item_name for row in rows if row.item_name not in by_name]
    extra = [name for name in by_name if name not in page_names]
    mismatches = []
    for row in rows:
        entry = by_name.get(row.item_name)
        if entry and entry.get("icon_url") != row.item_icon_url:
            mismatches.append(row.item_name)
    print(f"page_rows={len(rows)}")
    print(f"manifest_rows={len(manifest)}")
    print(f"missing={len(missing)}")
    print(f"extra={len(extra)}")
    print(f"icon_mismatches={len(mismatches)}")
    if missing:
        print("missing_names=" + ", ".join(missing))
    if extra:
        print("extra_names=" + ", ".join(extra))
    if mismatches:
        print("mismatch_names=" + ", ".join(mismatches))
    return 0 if len(rows) == len(manifest) and not missing and not extra and not mismatches else 1


if __name__ == "__main__":
    raise SystemExit(main())
