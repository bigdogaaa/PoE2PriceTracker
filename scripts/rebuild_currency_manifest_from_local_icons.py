from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from poe2_price_tracker.poe2db_sync import _image_phash  # noqa: E402


ICON_DIR = SRC / "poe2_price_tracker" / "assets" / "icons" / "currency"


def _display_name(path: Path) -> str:
    name = path.stem
    if "_等级" in name:
        base, level = name.rsplit("_等级", 1)
        return f"{base}（等级{level}）"
    return name


def main() -> int:
    manifest_path = ICON_DIR / "manifest.json"
    old_entries = json.loads(manifest_path.read_text(encoding="utf-8"))
    icon_files = sorted(path for path in ICON_DIR.glob("*.png") if path.is_file())
    if len(icon_files) != len(old_entries):
        print(f"icon_files={len(icon_files)} manifest_rows={len(old_entries)}")
        return 1

    rebuilt: list[dict[str, str]] = []
    for path, old in zip(icon_files, old_entries, strict=True):
        rebuilt.append(
            {
                "name": _display_name(path),
                "file": path.name,
                "page_url": str(old.get("page_url", "")),
                "icon_url": str(old.get("icon_url", "")),
                "phash": _image_phash(path),
            }
        )

    manifest_path.write_text(json.dumps(rebuilt, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"rebuilt {len(rebuilt)} currency icon mappings from local files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
