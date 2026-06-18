from pathlib import Path
import sqlite3
import uuid

from PIL import Image

from poe2_price_tracker.db import PriceDatabase, convert_amount
from poe2_price_tracker.market_exchange import derive_realtime_price, parse_market_exchange
from poe2_price_tracker.ocr import OcrBox, OcrResult


def box(text: str, left: int, top: int, right: int, bottom: int, score: float = 0.98) -> OcrBox:
    return OcrBox(
        text=text,
        score=score,
        points=((left, top), (right, top), (right, bottom), (left, bottom)),
    )


def _workspace_image_path() -> Path:
    path = Path(".tmp-market-exchange-tests")
    path.mkdir(exist_ok=True)
    return path / f"{uuid.uuid4().hex}.png"


def test_parse_market_exchange_uses_structure_and_currency_text():
    image_path = _workspace_image_path()
    Image.new("RGB", (900, 220), "#222").save(image_path)
    result = OcrResult(
        text="需求物品\n剥离石\n拥有物品\n神圣石\n1.05:1\n1:1",
        engine="rapidocr",
        ok=True,
        boxes=(
            box("需求物品", 110, 10, 200, 36),
            box("拥有物品", 700, 10, 790, 36),
            box("1.05:1", 420, 18, 500, 38),
            box("1:1", 440, 70, 500, 92),
            box("剥离石", 80, 70, 150, 94),
            box("神圣石", 690, 70, 760, 94),
        ),
    )

    parsed = parse_market_exchange(image_path, result)

    assert parsed.want_item == "剥离石"
    assert parsed.have_item == "神圣石"
    assert parsed.market_want_amount == 1.05
    assert parsed.market_have_amount == 1
    assert parsed.user_want_amount == 1
    assert parsed.user_have_amount == 1
    assert parsed.want_item_is_currency
    assert parsed.have_item_is_currency
    realtime = derive_realtime_price(parsed)
    assert realtime.item_name == "剥离石"
    assert realtime.side == "买入"
    assert realtime.amount == 1 / 1.05
    assert realtime.currency == "神圣石"


def test_parse_market_exchange_warns_when_no_currency_text_matches():
    image_path = _workspace_image_path()
    Image.new("RGB", (900, 220), "#222").save(image_path)
    result = OcrResult(
        text="需求物品\n未知甲\n拥有物品\n未知乙\n1:2\n1:2",
        engine="rapidocr",
        ok=True,
        boxes=(
            box("需求物品", 110, 10, 200, 36),
            box("拥有物品", 700, 10, 790, 36),
            box("1:2", 420, 18, 500, 38),
            box("1:2", 440, 70, 500, 92),
            box("未知甲", 80, 70, 150, 94),
            box("未知乙", 690, 70, 760, 94),
        ),
    )

    parsed = parse_market_exchange(image_path, result)

    assert not parsed.want_item_is_currency
    assert not parsed.have_item_is_currency
    assert "至少一边需要是通货" in parsed.message


def test_parse_market_exchange_derives_sell_price_when_left_is_trade_currency():
    image_path = _workspace_image_path()
    Image.new("RGB", (900, 220), "#222").save(image_path)
    result = OcrResult(
        text="需求物品\n崇高石\n拥有物品\n褪色危机碎片\n489:1\n489:1",
        engine="rapidocr",
        ok=True,
        boxes=(
            box("需求物品", 110, 10, 200, 36),
            box("拥有物品", 700, 10, 790, 36),
            box("489:1", 420, 18, 500, 38),
            box("489:1", 440, 70, 500, 92),
            box("崇高石", 80, 70, 150, 94),
            box("褪色危机碎片", 690, 70, 820, 94),
        ),
    )

    realtime = derive_realtime_price(parse_market_exchange(image_path, result))

    assert realtime.item_name == "褪色危机碎片"
    assert realtime.side == "卖出"
    assert realtime.amount == 489
    assert realtime.currency == "崇高石"


def test_realtime_price_record_mirrors_to_market_rows_with_dynamic_currency_conversion():
    db = PriceDatabase(Path(":memory:"))
    db.add_price_record("神圣石", 150, "崇高石", "test")
    db.add_realtime_price_record("褪色危机碎片", "买入", 7, "神圣石", source="实时价格导入")

    records = db.get_realtime_price_records()
    assert records[0].item_name == "褪色危机碎片"
    assert records[0].side == "买入"
    stats = db.get_stats("褪色危机碎片")
    assert stats is not None
    assert stats.latest_amount == 7
    assert convert_amount(stats.latest_amount, stats.latest_currency, "崇高石", db.get_exalted_per_divine()) == 1050


def test_realtime_price_import_keeps_each_snapshot_in_price_history():
    db = PriceDatabase(Path(":memory:"))
    try:
        first_id = db.add_realtime_price_record("测试物品", "买入", 7, "神圣石", source="实时价格导入")
        second_id = db.add_realtime_price_record("测试物品", "买入", 8, "神圣石", source="实时价格导入")

        records = db.get_recent_records("测试物品", limit=10)

        assert [record.amount for record in records] == [8, 7]
        assert [record.realtime_record_id for record in records] == [second_id, first_id]
        stats = db.get_stats("测试物品")
        assert stats is not None
        assert stats.count == 2
        assert stats.latest_amount == 8
    finally:
        db.close()


def test_deleting_item_removes_realtime_snapshots_so_repair_cannot_restore_them():
    db = PriceDatabase(Path(":memory:"))
    try:
        db.add_realtime_price_record("测试物品", "买入", 7, "神圣石", source="实时价格导入")
        db.add_realtime_price_record("测试物品", "买入", 8, "神圣石", source="实时价格导入")
        assert len(db.get_recent_records("测试物品", limit=10)) == 2

        db.delete_item("测试物品")
        assert db.get_recent_records("测试物品", limit=10) == []
        assert db.get_realtime_price_records(limit=10) == []

        db._repair_realtime_price_mirrors()
        assert db.get_recent_records("测试物品", limit=10) == []
        db.add_realtime_price_record("测试物品", "买入", 9, "神圣石", source="实时价格导入")
        records = db.get_recent_records("测试物品", limit=10)
        assert len(records) == 1
        assert records[0].amount == 9
    finally:
        db.close()


def test_realtime_min_upvotes_threshold_filters_untrusted_results():
    db = PriceDatabase(Path(":memory:"))
    first_id = db.add_realtime_price_record("测试物品", "买入", 7, "神圣石", source="实时价格导入")
    rows = db.get_market_rows(query="测试物品")
    assert len(rows) == 1
    assert rows[0].realtime_record_id == first_id

    assert db.get_market_rows(query="测试物品", min_realtime_upvotes=1) == []
    assert db.get_stats("测试物品", min_realtime_upvotes=1) is None
    assert db.vote_realtime_price_record(first_id, 1) == (1, 0)
    rows = db.get_market_rows(query="测试物品", min_realtime_upvotes=1)
    assert len(rows) == 1
    assert rows[0].realtime_record_id == first_id
    assert rows[0].realtime_upvotes == 1

    db.add_price_record("普通物品", 3, "神圣石", "poe2db-test")
    assert db.get_market_rows(query="普通物品", min_realtime_upvotes=99)


def test_synced_realtime_record_is_idempotent_and_updates_upvotes():
    db = PriceDatabase(Path(":memory:"))
    try:
        first_id = db.upsert_synced_realtime_price_record(
            remote_key="remote:test:1",
            item_name="sync-test-item",
            side="buy",
            amount=7,
            currency="Divine Orb",
            upvotes=3,
            captured_at="2026-01-01T00:00:00+00:00",
        )
        second_id = db.upsert_synced_realtime_price_record(
            remote_key="remote:test:1",
            item_name="sync-test-item",
            side="buy",
            amount=8,
            currency="Divine Orb",
            upvotes=1234,
            captured_at="2026-01-02T00:00:00+00:00",
        )

        assert second_id == first_id
        records = db.get_realtime_price_records(limit=10)
        assert len(records) == 1
        assert records[0].remote_key == "remote:test:1"
        assert records[0].upvotes == 1234
        rows = db.get_market_rows(query="sync-test-item", min_realtime_upvotes=1000)
        assert len(rows) == 1
        assert rows[0].latest_amount == 8
        assert rows[0].realtime_upvotes == 1234
        assert len(db.get_price_history("sync-test-item", limit=10)) == 1
    finally:
        db.close()


def test_sync_keeps_newer_realtime_snapshot_latest_when_old_remote_is_inserted_later():
    db = PriceDatabase(Path(":memory:"))
    try:
        db.upsert_synced_realtime_price_record(
            remote_key="remote:old",
            item_name="sync-order-item",
            side="buy",
            amount=3,
            currency="Divine Orb",
            upvotes=0,
            captured_at="2026-01-01T00:00:00+00:00",
        )
        db.delete_item("sync-order-item")

        local_id = db.add_realtime_price_record(
            "sync-order-item",
            "buy",
            9,
            "Divine Orb",
            source="realtime-import",
            remote_key="local:new",
        )
        db.vote_realtime_price_record(local_id, 1)
        local_record = db.get_realtime_price_record(local_id)
        assert local_record is not None

        db.upsert_synced_realtime_price_record(
            remote_key=local_record.remote_key,
            item_name=local_record.item_name,
            side=local_record.side,
            amount=local_record.amount,
            currency=local_record.currency,
            upvotes=1,
            captured_at=local_record.captured_at,
        )
        db.upsert_synced_realtime_price_record(
            remote_key="remote:old",
            item_name="sync-order-item",
            side="buy",
            amount=3,
            currency="Divine Orb",
            upvotes=0,
            captured_at="2026-01-01T00:00:00+00:00",
        )

        stats = db.get_stats("sync-order-item")
        assert stats is not None
        assert stats.latest_amount == 9
        assert stats.realtime_upvotes == 1
        rows = db.get_market_rows(query="sync-order-item")
        assert len(rows) == 1
        assert rows[0].latest_amount == 9
        assert rows[0].realtime_upvotes == 1
    finally:
        db.close()


def test_realtime_threshold_uses_latest_trusted_snapshot_instead_of_hiding_item():
    db = PriceDatabase(Path(":memory:"))
    try:
        trusted_id = db.upsert_synced_realtime_price_record(
            remote_key="remote:trusted-threshold-old",
            item_name="trusted-threshold-item",
            side="buy",
            amount=7,
            currency="Divine Orb",
            source="realtime-import",
            captured_at="2026-01-01T00:00:00+00:00",
        )
        for _ in range(3):
            db.vote_realtime_price_record(trusted_id, 1)
        db.upsert_synced_realtime_price_record(
            remote_key="remote:trusted-threshold-new",
            item_name="trusted-threshold-item",
            side="buy",
            amount=7,
            currency="Divine Orb",
            source="realtime-import",
            captured_at="2026-01-02T00:00:00+00:00",
        )

        latest = db.get_market_rows(query="trusted-threshold-item", min_realtime_upvotes=0)
        trusted = db.get_market_rows(query="trusted-threshold-item", min_realtime_upvotes=3)

        assert len(latest) == 1
        assert latest[0].realtime_upvotes == 0
        assert len(trusted) == 1
        assert trusted[0].realtime_record_id == trusted_id
        assert trusted[0].realtime_upvotes == 3
        stats = db.get_stats("trusted-threshold-item", min_realtime_upvotes=3)
        assert stats is not None
        assert stats.realtime_record_id == trusted_id
        assert stats.realtime_upvotes == 3
    finally:
        db.close()


def test_valid_realtime_price_takes_precedence_over_poe2db_records_for_same_item():
    db = PriceDatabase(Path(":memory:"))
    try:
        db.upsert_synced_realtime_price_record(
            remote_key="remote:preferred-realtime",
            item_name="preferred-item",
            side="buy",
            amount=7,
            currency="Divine Orb",
            upvotes=2,
            source="realtime-import",
            captured_at="2026-01-01T00:00:00+00:00",
        )
        db.add_price_record(
            "preferred-item",
            3,
            "Divine Orb",
            "poe2db-test",
            captured_at="2026-01-03T00:00:00+00:00",
        )

        rows = db.get_market_rows(query="preferred-item", min_realtime_upvotes=2)
        stats = db.get_stats("preferred-item", min_realtime_upvotes=2)
        history = db.get_price_history(
            "preferred-item",
            limit=10,
            min_realtime_upvotes=2,
            prefer_realtime_if_available=True,
        )

        assert len(rows) == 1
        assert rows[0].latest_amount == 7
        assert rows[0].source.startswith("realtime-import")
        assert rows[0].count == 1
        assert stats is not None
        assert stats.latest_amount == 7
        assert stats.count == 1
        assert [record.amount for record in history] == [7]
    finally:
        db.close()


def test_poe2db_price_is_used_when_realtime_price_is_below_threshold():
    db = PriceDatabase(Path(":memory:"))
    try:
        db.upsert_synced_realtime_price_record(
            remote_key="remote:below-threshold",
            item_name="fallback-item",
            side="buy",
            amount=7,
            currency="Divine Orb",
            upvotes=1,
            source="realtime-import",
            captured_at="2026-01-01T00:00:00+00:00",
        )
        db.add_price_record(
            "fallback-item",
            3,
            "Divine Orb",
            "poe2db-test",
            captured_at="2026-01-03T00:00:00+00:00",
        )

        rows = db.get_market_rows(query="fallback-item", min_realtime_upvotes=2)
        stats = db.get_stats("fallback-item", min_realtime_upvotes=2)

        assert len(rows) == 1
        assert rows[0].latest_amount == 3
        assert rows[0].source == "poe2db-test"
        assert stats is not None
        assert stats.latest_amount == 3
    finally:
        db.close()


def test_realtime_remote_key_migration_handles_old_database():
    db = PriceDatabase.__new__(PriceDatabase)
    db.path = Path(":memory:")
    db.conn = sqlite3.connect(":memory:")
    db.conn.row_factory = sqlite3.Row
    try:
        db.conn.execute(
            """
            CREATE TABLE realtime_price_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_name TEXT NOT NULL,
                item_match TEXT NOT NULL DEFAULT '',
                item_known INTEGER NOT NULL DEFAULT 0,
                side TEXT NOT NULL,
                amount REAL NOT NULL,
                currency TEXT NOT NULL,
                want_item TEXT NOT NULL DEFAULT '',
                have_item TEXT NOT NULL DEFAULT '',
                market_want_amount REAL NOT NULL DEFAULT 0,
                market_have_amount REAL NOT NULL DEFAULT 0,
                user_want_amount REAL NOT NULL DEFAULT 0,
                user_have_amount REAL NOT NULL DEFAULT 0,
                source TEXT NOT NULL,
                captured_at TEXT NOT NULL,
                confidence REAL NOT NULL DEFAULT 0,
                raw_text TEXT NOT NULL DEFAULT '',
                screenshot_path TEXT NOT NULL DEFAULT '',
                note TEXT NOT NULL DEFAULT ''
            )
            """
        )
        db.conn.commit()
        db.migrate()
        row = db.conn.execute("PRAGMA table_info(realtime_price_records)").fetchall()
        assert "remote_key" in {item["name"] for item in row}
        record_id = db.add_realtime_price_record("old-db-item", "buy", 1, "Divine Orb")
        record = db.get_realtime_price_record(record_id)
        assert record is not None
        assert record.remote_key.startswith("local:")
    finally:
        db.close()
