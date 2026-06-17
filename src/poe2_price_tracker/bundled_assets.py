from __future__ import annotations

import json
from importlib import resources

from .db import PriceDatabase


def _asset_root():
    return resources.files(__package__).joinpath("assets", "icons", "currency")


def bundled_currency_manifest() -> list[dict[str, str]]:
    manifest = _asset_root().joinpath("manifest.json")
    if not manifest.is_file():
        return []
    try:
        return json.loads(manifest.read_text(encoding="utf-8"))
    except Exception:
        return []


def seed_bundled_currency_icons(db: PriceDatabase) -> int:
    seeded = 0
    root = _asset_root()
    for entry in bundled_currency_manifest():
        name = str(entry.get("name", "")).strip()
        filename = str(entry.get("file", "")).strip()
        if not name or not filename:
            continue
        icon_path = root.joinpath(filename)
        if not icon_path.is_file():
            continue
        db.upsert_icon_asset(
            name,
            "currency",
            page_url=str(entry.get("page_url", "")),
            icon_url=str(entry.get("icon_url", "")),
            local_path=str(icon_path),
            phash=str(entry.get("phash", "")),
        )
        seeded += 1
    return seeded
