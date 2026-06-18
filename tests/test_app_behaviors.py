import shutil
import uuid
from pathlib import Path
from types import SimpleNamespace

from poe2_price_tracker.app import PriceTrackerApp
from poe2_price_tracker.parser import ParsedItemPrice


class _Var:
    def __init__(self):
        self.value = ""

    def set(self, value):
        self.value = value


class _Db:
    def get_exalted_per_divine(self):
        return 100

    def get_chaos_per_divine(self):
        return 1000


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
