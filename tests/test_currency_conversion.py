from pathlib import Path

from poe2_price_tracker.db import PriceDatabase, canonical_currency, convert_amount, display_amount_for_item
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


def test_divine_rate_uses_inverse_exalted_quote_when_divine_latest_is_chaos():
    db = PriceDatabase(Path(":memory:"))
    try:
        db.add_price_record("神圣石", 9.54, "chaos", "poe2db-通货")
        db.add_price_record("崇高石", 0.00510204081632653, "神圣石", "poe2db-通货")

        rate = db.get_exalted_per_divine()
        chaos_rate = db.get_chaos_per_divine()

        assert round(rate) == 196
        assert round(chaos_rate, 2) == 9.54
        assert display_amount_for_item("神圣石", 9.54, "chaos", "神圣石", rate) == 1
        assert display_amount_for_item("神圣石", 9.54, "chaos", "崇高石", rate) == rate
        assert display_amount_for_item("神圣石", 9.54, "chaos", "混沌石", rate, chaos_rate) == chaos_rate
        assert canonical_currency("chaos") == "混沌石"
    finally:
        db.close()


def test_chaos_can_be_used_as_base_display_currency():
    db = PriceDatabase(Path(":memory:"))
    try:
        db.add_price_record("神圣石", 200, "崇高石", "poe2db-通货")
        db.add_price_record("神圣石", 10, "混沌石", "poe2db-通货")
        db.add_price_record("卡兰德的魔镜", 2, "神圣石", "test")

        exalted_rate = db.get_exalted_per_divine()
        chaos_rate = db.get_chaos_per_divine()

        assert chaos_rate == 10
        assert convert_amount(2, "神圣石", "混沌石", exalted_rate, chaos_rate) == 20
        assert convert_amount(20, "混沌石", "神圣石", exalted_rate, chaos_rate) == 2
        assert display_amount_for_item("混沌石", 1, "神圣石", "神圣石", exalted_rate, chaos_rate) == 0.1
    finally:
        db.close()


def test_divine_rate_prefers_poe2db_quote_over_realtime_import_noise():
    db = PriceDatabase(Path(":memory:"))
    try:
        db.add_price_record("崇高石", 0.005, "神圣石", "poe2db-通货")
        db.add_realtime_price_record("神圣石", "买入", 1, "崇高石", source="实时价格导入")

        assert db.get_exalted_per_divine() == 200
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
