from pathlib import Path

from poe2_price_tracker.bundled_assets import bundled_currency_manifest, seed_bundled_currency_icons


class FakeDb:
    def __init__(self):
        self.rows = []

    def upsert_icon_asset(self, name, kind, page_url="", icon_url="", local_path="", phash=""):
        self.rows.append(
            {
                "name": name,
                "kind": kind,
                "page_url": page_url,
                "icon_url": icon_url,
                "local_path": local_path,
                "phash": phash,
            }
        )


def test_bundled_currency_icons_seed_from_manifest():
    manifest = bundled_currency_manifest()
    assert len(manifest) >= 50
    assert any(entry["name"] == "崇高石" for entry in manifest)
    assert any(entry["name"] == "神圣石" for entry in manifest)

    db = FakeDb()
    seeded = seed_bundled_currency_icons(db)

    assert seeded == len(manifest)
    assert all(row["kind"] == "currency" for row in db.rows)
    assert all(Path(row["local_path"]).exists() for row in db.rows)
