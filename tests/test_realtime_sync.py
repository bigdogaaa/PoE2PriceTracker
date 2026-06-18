from pathlib import Path

from poe2_price_tracker.app import PriceTrackerApp
from poe2_price_tracker.db import PriceDatabase
from poe2_price_tracker.realtime_sync import RealtimeSyncClient, RemoteRealtimePrice
from poe2_price_tracker.secure_config import RedisCredentials


class _Var:
    def __init__(self):
        self.value = ""

    def set(self, value):
        self.value = value


def _remote(remote_key: str, upvotes: int = 0) -> RemoteRealtimePrice:
    return RemoteRealtimePrice(
        remote_key=remote_key,
        item_name="sync-item",
        item_match="",
        item_known=True,
        side="buy",
        amount=7,
        currency="Divine Orb",
        want_item="",
        have_item="",
        market_want_amount=0,
        market_have_amount=0,
        user_want_amount=0,
        user_have_amount=0,
        source="realtime-import",
        captured_at="2026-01-01T00:00:00+00:00",
        confidence=0.9,
        raw_text="",
        screenshot_path="",
        note="",
        upvotes=upvotes,
    )


def test_service_fetch_pages_uses_cursor_until_complete():
    client = RealtimeSyncClient(RedisCredentials(), service_url="http://share.test")
    calls = []
    responses = [
        {
            "ok": True,
            "records": [{"k": "remote:1", "n": "item-one", "a": 1, "c": "Divine Orb", "u": 2}],
            "next_cursor": "12",
            "complete": False,
        },
        {
            "ok": True,
            "records": [{"k": "remote:2", "n": "item-two", "a": 2, "c": "Exalted Orb", "u": 3}],
            "next_cursor": "0",
            "complete": True,
        },
    ]

    def fake_request(method, path, payload=None):
        calls.append((method, path, payload))
        return responses.pop(0)

    client._service_request = fake_request

    pages = list(client.fetch_pages(page_size=100))

    assert [page.cursor for page in pages] == ["12", "0"]
    assert [record.remote_key for page in pages for record in page.records] == ["remote:1", "remote:2"]
    assert "cursor=0" in calls[0][1]
    assert "cursor=12" in calls[1][1]


def test_realtime_sync_page_skips_unchanged_records_and_updates_changed_votes():
    db = PriceDatabase(Path(":memory:"))
    try:
        db.upsert_synced_realtime_price_record(
            remote_key="remote:1",
            item_name="sync-item",
            item_known=True,
            side="buy",
            amount=7,
            currency="Divine Orb",
            source="realtime-import",
            captured_at="2026-01-01T00:00:00+00:00",
            confidence=0.9,
            upvotes=1,
        )
        app = PriceTrackerApp.__new__(PriceTrackerApp)
        app.db = db
        app.status_var = _Var()
        app.realtime_sync_seen_count = 0
        app.realtime_sync_saved_count = 0
        app.realtime_sync_skipped_count = 0
        app.realtime_sync_remote_signatures = db.get_realtime_remote_signatures()
        app._set_progress_percent = lambda *_args: None

        app._finish_realtime_sync_page([_remote("remote:1", upvotes=1)], 1)

        assert app.realtime_sync_saved_count == 0
        assert app.realtime_sync_skipped_count == 1

        app._finish_realtime_sync_page([_remote("remote:1", upvotes=2)], 2)

        assert app.realtime_sync_saved_count == 1
        record = db.get_realtime_price_records(limit=1)[0]
        assert record.upvotes == 2
    finally:
        db.close()
