from pathlib import Path

from poe2_price_tracker.db import PriceDatabase, convert_amount
from poe2_price_tracker.hotkeys import MOD_CONTROL, parse_hotkey


def test_divine_to_exalted_rate_uses_latest_database_record():
    db = PriceDatabase(Path(":memory:"))
    try:
        db.add_price_record("神圣石", 142, "崇高石", "test")
        assert db.get_exalted_per_divine() == 142
        assert convert_amount(2, "神圣石", "崇高石", db.get_exalted_per_divine()) == 284
        assert convert_amount(284, "崇高石", "神圣石", db.get_exalted_per_divine()) == 2
    finally:
        db.close()


def test_upsert_latest_price_record_updates_existing_item_latest_record():
    db = PriceDatabase(Path(":memory:"))
    try:
        first = db.upsert_latest_price_record("卡兰德的魔镜", 10, "神圣石", "截图识别")
        second = db.upsert_latest_price_record("卡兰德的魔镜", 12, "神圣石", "截图识别")
        records = db.get_recent_records("卡兰德的魔镜", limit=10)
        assert first == second
        assert len(records) == 1
        assert records[0].amount == 12
    finally:
        db.close()


def test_market_search_splits_terms_with_and_logic():
    db = PriceDatabase(Path(":memory:"))
    try:
        db.add_price_record("空白之兆预兆", 2, "神圣石", "test")
        db.add_price_record("空白裂隙石", 3, "神圣石", "test")
        db.add_price_record("混沌预兆", 4, "神圣石", "test")

        rows = db.get_market_rows(query="空白   预兆", limit=10)

        assert [row.item_name for row in rows] == ["空白之兆预兆"]
        assert db.count_market_rows(query="空白   预兆") == 1
    finally:
        db.close()


def test_market_trend_uses_local_history_when_enough_points_exist():
    db = PriceDatabase(Path(":memory:"))
    try:
        db.add_price_record("崇高石", 10, "金币", "poe2db", raw_text="trend=+90%")
        db.add_price_record("崇高石", 15, "金币", "poe2db", raw_text="trend=+90%")
        db.add_price_record("崇高石", 20, "金币", "poe2db", raw_text="trend=+90%")
        db.add_price_record("神圣石", 1, "崇高石", "poe2db", raw_text="trend=-12%")

        rows = {row.item_name: row for row in db.get_market_rows(limit=10)}

        assert rows["崇高石"].trend_percent == "+100%"
        assert rows["神圣石"].trend_percent == "-12%"
    finally:
        db.close()


def test_ctrl_space_hotkey_is_supported():
    modifiers, key = parse_hotkey("Ctrl+Space")

    assert modifiers == MOD_CONTROL
    assert key == 0x20
