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


def test_divine_rate_falls_back_to_older_valid_same_direction_quote():
    db = PriceDatabase(Path(":memory:"))
    try:
        db.add_price_record(
            "神圣石",
            181,
            "崇高石",
            "实时价格导入-卖出",
            captured_at="2026-01-01T00:00:00+00:00",
        )
        db.add_price_record(
            "神圣石",
            1,
            "崇高石",
            "实时价格导入-卖出",
            captured_at="2026-01-02T00:00:00+00:00",
        )

        assert db.get_exalted_per_divine() == 181
    finally:
        db.close()


def test_divine_rate_uses_latest_valid_realtime_base_currency_quote():
    db = PriceDatabase(Path(":memory:"))
    try:
        db.add_price_record(
            "神圣石",
            150,
            "崇高石",
            "poe2db-通货",
            captured_at="2026-01-01T00:00:00+00:00",
        )
        db.upsert_synced_realtime_price_record(
            remote_key="remote:divine-exalted-latest",
            item_name="神圣石",
            side="卖出",
            amount=181,
            currency="崇高石",
            source="实时价格导入",
            captured_at="2026-01-02T00:00:00+00:00",
        )

        assert db.get_exalted_per_divine() == 181
        rows = db.get_market_rows(query="神圣石", target_currency="崇高石")
        assert rows[0].latest_amount == 181
        assert rows[0].source == "实时价格导入-卖出"
    finally:
        db.close()


def test_divine_rate_uses_latest_valid_inverse_base_currency_quote():
    db = PriceDatabase(Path(":memory:"))
    try:
        db.add_price_record(
            "神圣石",
            150,
            "崇高石",
            "poe2db-通货",
            captured_at="2026-01-01T00:00:00+00:00",
        )
        db.upsert_synced_realtime_price_record(
            remote_key="remote:exalted-divine-latest",
            item_name="崇高石",
            side="买入",
            amount=1 / 181,
            currency="神圣石",
            source="实时价格导入",
            captured_at="2026-01-02T00:00:00+00:00",
        )

        assert round(db.get_exalted_per_divine()) == 181
    finally:
        db.close()


def test_chaos_rate_uses_latest_base_currency_quotes_across_three_currencies():
    db = PriceDatabase(Path(":memory:"))
    try:
        db.add_price_record(
            "神圣石",
            150,
            "崇高石",
            "poe2db-通货",
            captured_at="2026-01-01T00:00:00+00:00",
        )
        db.add_price_record(
            "神圣石",
            10,
            "混沌石",
            "poe2db-通货",
            captured_at="2026-01-01T00:00:01+00:00",
        )
        db.upsert_synced_realtime_price_record(
            remote_key="remote:divine-exalted-latest",
            item_name="神圣石",
            side="卖出",
            amount=181,
            currency="崇高石",
            source="实时价格导入",
            captured_at="2026-01-02T00:00:00+00:00",
        )
        db.upsert_synced_realtime_price_record(
            remote_key="remote:exalted-chaos-latest",
            item_name="混沌石",
            side="买入",
            amount=1 / 0.06,
            currency="崇高石",
            source="实时价格导入",
            captured_at="2026-01-02T00:00:01+00:00",
        )

        assert db.get_exalted_per_divine() == 181
        assert round(db.get_chaos_per_divine(), 2) == 10.86
        assert round(display_amount_for_item("混沌石", 1, "神圣石", "神圣石", 181, db.get_chaos_per_divine()), 4) == round(1 / 10.86, 4)
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


def test_market_trend_prefers_valid_realtime_history_over_poe2db_history():
    db = PriceDatabase(Path(":memory:"))
    try:
        db.add_price_record("趋势测试物品", 1, "神圣石", "poe2db", raw_text="trend=+9900%")
        db.add_price_record("趋势测试物品", 100, "神圣石", "poe2db", raw_text="trend=+9900%")
        db.add_realtime_price_record("趋势测试物品", "买入", 10, "神圣石", source="实时价格导入")
        db.add_realtime_price_record("趋势测试物品", "买入", 15, "神圣石", source="实时价格导入")

        rows = db.get_market_rows(query="趋势测试物品")

        assert len(rows) == 1
        assert rows[0].count == 2
        assert rows[0].source == "实时价格导入-买入"
        assert rows[0].sparkline == "▁█"
        assert rows[0].trend_percent == "+50%"
    finally:
        db.close()


def test_market_trend_does_not_fallback_to_poe2db_when_one_valid_realtime_point_exists():
    db = PriceDatabase(Path(":memory:"))
    try:
        db.add_price_record("单点实时趋势物品", 1, "神圣石", "poe2db", raw_text="trend=+100%")
        db.add_price_record("单点实时趋势物品", 2, "神圣石", "poe2db", raw_text="trend=+100%")
        db.add_realtime_price_record("单点实时趋势物品", "买入", 10, "神圣石", source="实时价格导入")

        rows = db.get_market_rows(query="单点实时趋势物品")

        assert len(rows) == 1
        assert rows[0].count == 1
        assert rows[0].source == "实时价格导入-买入"
        assert rows[0].sparkline == ""
        assert rows[0].trend_percent == ""
    finally:
        db.close()


def test_market_trend_falls_back_to_poe2db_when_no_valid_realtime_price_exists():
    db = PriceDatabase(Path(":memory:"))
    try:
        db.add_price_record("阈值趋势物品", 1, "神圣石", "poe2db", raw_text="trend=+100%")
        db.add_price_record("阈值趋势物品", 2, "神圣石", "poe2db", raw_text="trend=+100%")
        db.add_realtime_price_record("阈值趋势物品", "买入", 10, "神圣石", source="实时价格导入")

        rows = db.get_market_rows(query="阈值趋势物品", min_realtime_upvotes=1)

        assert len(rows) == 1
        assert rows[0].count == 2
        assert rows[0].source == "poe2db"
        assert rows[0].sparkline == "▁█"
        assert rows[0].trend_percent == "+100%"
    finally:
        db.close()


def test_ctrl_space_hotkey_is_supported():
    modifiers, key = parse_hotkey("Ctrl+Space")

    assert modifiers == MOD_CONTROL
    assert key == 0x20
