from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from poe2_price_tracker.db import normalize_name  # noqa: E402
from poe2_price_tracker.poe2db_sync import (  # noqa: E402
    _download_icon,
    _fetch_html,
    _safe_asset_name,
    parse_economy_html,
)


def main() -> int:
    output_dir = SRC / "poe2_price_tracker" / "assets" / "icons" / "currency"
    output_dir.mkdir(parents=True, exist_ok=True)
    result = parse_economy_html(
        _fetch_html("https://poe2db.tw/cn/Economy_Currency"),
        "通货",
        "https://poe2db.tw/cn/Economy_Currency",
    )
    entries: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in result.rows:
        icon_url = row.item_icon_url
        if not icon_url:
            continue
        key = normalize_name(row.item_name)
        if key in seen:
            continue
        seen.add(key)
        local_path, phash = _download_icon(icon_url, output_dir, row.item_name, "")
        if not local_path:
            continue
        path = Path(local_path)
        target = output_dir / f"{_safe_asset_name(row.item_name)}{path.suffix or '.png'}"
        if path != target:
            target.write_bytes(path.read_bytes())
            try:
                path.unlink()
            except OSError:
                pass
        entries.append(
            {
                "name": row.item_name,
                "file": target.name,
                "page_url": row.item_page_url,
                "icon_url": icon_url,
                "phash": phash,
            }
        )
    entries.sort(key=lambda item: item["name"])
    (output_dir / "manifest.json").write_text(
        json.dumps(entries, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"synced {len(entries)} currency icons to {output_dir}")
    return 0 if entries else 1


if __name__ == "__main__":
    raise SystemExit(main())
