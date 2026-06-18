import shutil
import uuid
from pathlib import Path
from types import SimpleNamespace

from poe2_price_tracker.app import PriceTrackerApp
from poe2_price_tracker.db import PriceDatabase
from poe2_price_tracker.market_exchange import ParsedMarketExchange, ParsedRealtimePrice
from poe2_price_tracker.parser import ParsedItemPrice


class _Var:
    def __init__(self, value=""):
        self.value = value

    def set(self, value):
        self.value = value

    def get(self):
        return self.value


class _Db:
    def get_exalted_per_divine(self):
        return 100

    def get_chaos_per_divine(self):
        return 1000


class _RealtimeDb:
    def __init__(self):
        self.record = None

    def add_realtime_price_record(self, **kwargs):
        self.record = kwargs
        return 123


class _Label:
    def __init__(self):
        self.text = ""

    def configure(self, **kwargs):
        if "text" in kwargs:
            self.text = kwargs["text"]


def test_ocr_row_confidence_prefers_structured_score():
    app = PriceTrackerApp.__new__(PriceTrackerApp)
    row = ParsedItemPrice(
        item_name="卡兰德的魔镜",
        amount=10,
        currency="神圣石",
        raw_text="row text structure_confidence=0.72",
        item_match_score=1.0,
        currency_match_score=1.0,
    )

    assert app._ocr_row_confidence(row) == 0.72


def test_economy_sync_cooldown_is_persisted():
    data_dir = Path(f".tmp-sync-state-{uuid.uuid4().hex}")
    if data_dir.exists():
        shutil.rmtree(data_dir, ignore_errors=True)
    app = PriceTrackerApp.__new__(PriceTrackerApp)
    app.config = SimpleNamespace(data_path=data_dir)

    try:
        assert app._economy_sync_remaining_seconds() == 0
        app._record_economy_sync_attempt()
        assert app._economy_sync_remaining_seconds() > 1700
        assert (data_dir / "sync_state.json").exists()
    finally:
        shutil.rmtree(data_dir, ignore_errors=True)


def test_positive_integer_setting_validation():
    assert PriceTrackerApp._validate_positive_integer_input("")
    assert PriceTrackerApp._validate_positive_integer_input("25")
    assert not PriceTrackerApp._validate_positive_integer_input("0")
    assert not PriceTrackerApp._validate_positive_integer_input("-1")
    assert not PriceTrackerApp._validate_positive_integer_input("1.5")


def test_nonnegative_integer_setting_validation():
    assert PriceTrackerApp._validate_nonnegative_integer_input("")
    assert PriceTrackerApp._validate_nonnegative_integer_input("0")
    assert PriceTrackerApp._validate_nonnegative_integer_input("3")
    assert not PriceTrackerApp._validate_nonnegative_integer_input("-1")
    assert not PriceTrackerApp._validate_nonnegative_integer_input("1.5")


def test_upvote_count_uses_thousands_separator():
    assert PriceTrackerApp._format_upvotes(0) == "0"
    assert PriceTrackerApp._format_upvotes(999) == "999"
    assert PriceTrackerApp._format_upvotes(1234) == "1,234"
    assert PriceTrackerApp._format_upvotes(1200345) == "1,200,345"


def test_realtime_rating_available_uses_record_id_not_display_source():
    app = PriceTrackerApp.__new__(PriceTrackerApp)

    assert app._rating_available(1, "")
    assert app._rating_available(1, "同步来源")
    assert not app._rating_available(0, "实时价格导入-买入")


def test_version_status_text_appends_status_after_version():
    text = PriceTrackerApp._version_status_text("最新版")

    assert text.startswith("v")
    assert text.endswith(" · 最新版")


def test_realtime_submission_credit_uses_new_items_and_significant_price_changes():
    app = PriceTrackerApp.__new__(PriceTrackerApp)
    app.db = _Db()
    app.status_var = _Var()
    app.realtime_sync_credit_score = 0.0
    app.realtime_sync_credit_prices = {}
    app.realtime_sync_free_uses = 1

    app._record_realtime_submission_credit("测试物品", 10, "神圣石")
    assert app.realtime_sync_credit_score == 1.0

    app._record_realtime_submission_credit("测试物品", 10.3, "神圣石")
    assert app.realtime_sync_credit_score == 1.0

    app._record_realtime_submission_credit("测试物品", 10.9, "神圣石")
    assert app.realtime_sync_credit_score == 1.5

    for index in range(4):
        app._record_realtime_submission_credit(f"新物品{index}", 1, "神圣石")

    assert app.realtime_sync_free_uses == 2
    assert app.realtime_sync_credit_score == 0.5


def test_realtime_import_save_uses_parsed_price_not_editable_fields():
    app = PriceTrackerApp.__new__(PriceTrackerApp)
    db = _RealtimeDb()
    app.db = db
    app.realtime_import_confirmed = True
    app.realtime_item_var = _Var("用户修正物品")
    app.realtime_side_var = _Var("卖出")
    app.realtime_amount_var = _Var("999999")
    app.realtime_currency_var = _Var("混沌石")
    app.market_exchange_parsed = ParsedMarketExchange(
        want_item="神圣石",
        have_item="崇高石",
        market_want_amount=1,
        market_have_amount=150,
        user_want_amount=1,
        user_have_amount=150,
        confidence=0.9,
    )
    app.realtime_price_parsed = ParsedRealtimePrice(
        item_name="神圣石",
        side="买入",
        amount=150,
        currency="崇高石",
        confidence=0.9,
    )
    app.market_exchange_raw_text = "raw"
    app.market_exchange_image_path = Path("shot.png")
    app.status_var = _Var()
    app._market_exchange_name_flags = lambda item_name: (item_name, False, False)
    app._record_realtime_submission_credit = lambda *_args: None
    app._submit_realtime_record_to_remote = lambda *_args: None
    app.refresh_market_table = lambda: None
    app.destroy_realtime_import_overlay = lambda: None

    app.save_market_exchange_record(show_message=False)

    assert db.record["item_name"] == "用户修正物品"
    assert db.record["side"] == "卖出"
    assert db.record["amount"] == 150
    assert db.record["currency"] == "崇高石"


def test_realtime_import_ratio_label_uses_market_ratio():
    parsed = ParsedMarketExchange(market_want_amount=1, market_have_amount=150)

    assert PriceTrackerApp._format_market_exchange_ratio(parsed) == "比例 1:150"
    assert PriceTrackerApp._format_market_exchange_ratio(ParsedMarketExchange()) == "比例未识别"


def test_realtime_current_price_uses_recognized_currency_unit_for_comparison():
    db = PriceDatabase(Path(":memory:"))
    try:
        db.add_price_record(
            "神圣石",
            181,
            "崇高石",
            "实时价格导入-卖出",
            captured_at="2026-01-02T00:00:00+00:00",
        )
        app = PriceTrackerApp.__new__(PriceTrackerApp)
        label = _Label()
        app.db = db
        app.realtime_import_labels = {"current_price": label}
        app.realtime_item_var = _Var("神圣石")
        app.realtime_currency_var = _Var("崇高石")
        app.display_currency_var = _Var("神圣石")
        app.config = SimpleNamespace(display_currency="神圣石")
        app._realtime_min_upvotes = lambda: 0

        app._update_realtime_current_price_label()

        assert "当前兑换：181 崇高石" in label.text
        assert "实时价格导入-卖出" in label.text
    finally:
        db.close()
