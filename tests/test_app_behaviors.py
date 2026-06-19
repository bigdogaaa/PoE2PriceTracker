import shutil
import uuid
import queue
import time
from pathlib import Path
from types import SimpleNamespace

from poe2_price_tracker.app import PriceTrackerApp, _database_integrity_error, format_price_amount
from poe2_price_tracker import app as app_module
from poe2_price_tracker.db import PriceDatabase
from poe2_price_tracker.market_exchange import ParsedMarketExchange, ParsedRealtimePrice
from poe2_price_tracker.parser import ParsedItemPrice
from poe2_price_tracker.updater import UpdateInfo


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


def test_rating_fallback_text_keeps_icon_marker():
    assert PriceTrackerApp._rating_label_text("12", False) == "👍 12"
    assert PriceTrackerApp._rating_label_text("12", True) == " 12"
    assert PriceTrackerApp._rating_label_text("12", True, force_text_icon=True) == "👍 12"


def test_price_amount_format_respects_decimal_places():
    assert format_price_amount(1.2, 2) == "1.2"
    assert format_price_amount(1.236, 2) == "1.24"
    assert format_price_amount(12.9, 0) == "13"
    assert format_price_amount(1.23456789, 4) == "1.2346"


def test_update_notes_text_formats_manifest_notes():
    info = UpdateInfo(
        True,
        "0.4.9",
        "1.0.0",
        "",
        "",
        "发现新版本。",
        notes=("修复多屏截图", "", "性能优化"),
    )

    assert PriceTrackerApp._update_notes_text(info) == "- 修复多屏截图\n- 性能优化"
    assert PriceTrackerApp._update_notes_text(info, limit=1) == "- 修复多屏截图"


def test_update_notes_text_has_empty_fallback():
    info = UpdateInfo(True, "0.4.9", "1.0.0", "", "", "发现新版本。")

    assert PriceTrackerApp._update_notes_text(info) == "暂无更新说明。"


def test_database_integrity_error_detects_corrupt_sqlite():
    temp_dir = Path(f".tmp-corrupt-db-{uuid.uuid4().hex}")
    db_path = temp_dir / "prices.sqlite3"
    temp_dir.mkdir(parents=True, exist_ok=True)
    db_path.write_text("not sqlite", encoding="utf-8")

    try:
        assert "数据库" in _database_integrity_error(db_path)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_realtime_rating_available_uses_record_id_not_display_source():
    app = PriceTrackerApp.__new__(PriceTrackerApp)

    assert app._rating_available(1, "")
    assert app._rating_available(1, "同步来源")
    assert not app._rating_available(0, "实时价格导入-买入")


def test_quick_price_overlay_position_follows_pointer():
    assert PriceTrackerApp._quick_price_overlay_position((320, 240), (0, 0, 1920, 1080), 460, 260) == (344, 264)


def test_quick_price_overlay_position_avoids_empty_pointer_fallback():
    x, y = PriceTrackerApp._quick_price_overlay_position((0, 0), (0, 0, 1920, 1080), 460, 260)

    assert (x, y) != (24, 24)
    assert x > 300
    assert y >= 24


def test_screenshot_lookup_overlay_height_is_compact_for_few_rows():
    one_row = PriceTrackerApp._screenshot_lookup_overlay_height(62, 1, False)
    five_rows = PriceTrackerApp._screenshot_lookup_overlay_height(330, 5, False)
    scrollable = PriceTrackerApp._screenshot_lookup_overlay_height(340, 8, True)

    assert one_row < 160
    assert five_rows > one_row
    assert scrollable >= five_rows


def test_quick_price_trend_converts_history_to_latest_currency():
    app = PriceTrackerApp.__new__(PriceTrackerApp)
    app.db = _Db()
    history = [
        SimpleNamespace(amount=1, currency="神圣石"),
        SimpleNamespace(amount=200, currency="崇高石"),
    ]

    assert app._quick_price_trend(history, "崇高石") == "+100%"


def test_market_row_for_item_uses_market_trend_fallback_for_single_poe2db_record():
    db = PriceDatabase(Path(":memory:"))
    app = PriceTrackerApp.__new__(PriceTrackerApp)
    app.db = db
    app.config = SimpleNamespace(realtime_min_upvotes=0, display_currency="神圣石")
    app.display_currency_var = _Var("神圣石")
    try:
        db.add_price_record("先祖密藏日志", 12, "神圣石", "poe2db", raw_text="trend=-8%")

        row = app._market_row_for_item("先祖密藏日志")

        assert row is not None
        assert row.trend_percent == "-8%"
        assert app._stats_trend_percent("先祖密藏日志", "神圣石") == "-8%"
    finally:
        db.close()


def test_market_row_for_item_resolves_one_character_ocr_typo():
    db = PriceDatabase(Path(":memory:"))
    app = PriceTrackerApp.__new__(PriceTrackerApp)
    app.db = db
    app.config = SimpleNamespace(realtime_min_upvotes=0, display_currency="神圣石")
    app.display_currency_var = _Var("神圣石")
    try:
        db.add_price_record("先祖秘藏日志", 12, "神圣石", "poe2db", raw_text="trend=-8%")

        row = app._market_row_for_item("先祖密藏日志")

        assert row is not None
        assert row.item_name == "先祖秘藏日志"
        assert row.trend_percent == "-8%"
    finally:
        db.close()


def test_quick_price_uses_market_row_trend_matching_focus_search():
    db = PriceDatabase(Path(":memory:"))
    app = PriceTrackerApp.__new__(PriceTrackerApp)
    app.db = db
    app.config = SimpleNamespace(realtime_min_upvotes=0, display_currency="神圣石")
    app.display_currency_var = _Var("神圣石")
    captured = {}
    app._set_progress_idle = lambda *_args, **_kwargs: None

    def capture_overlay(title, price, subtitle, trend, *args):
        captured.update({"title": title, "price": price, "subtitle": subtitle, "trend": trend, "args": args})

    app._show_quick_price_overlay = capture_overlay
    try:
        db.add_price_record("先祖密藏日志", 12, "神圣石", "poe2db", raw_text="trend=-8%")
        focus_row = db.get_market_rows(query="先祖密藏日志", limit=1)[0]

        app._show_quick_price_for_text("物品类别: 日志\n稀有度: 普通\n先祖密藏日志\n--------")

        assert focus_row.trend_percent == "-8%"
        assert captured["title"] == "先祖密藏日志"
        assert captured["trend"] == focus_row.trend_percent
    finally:
        db.close()


def test_quick_price_converts_market_row_to_display_currency():
    db = PriceDatabase(Path(":memory:"))
    app = PriceTrackerApp.__new__(PriceTrackerApp)
    app.db = db
    app.config = SimpleNamespace(realtime_min_upvotes=0, display_currency="崇高石", price_decimal_places=3)
    app.display_currency_var = _Var("崇高石")
    captured = {}
    app._set_progress_idle = lambda *_args, **_kwargs: None

    def capture_overlay(title, price, subtitle, trend, *args):
        captured.update({"title": title, "price": price, "subtitle": subtitle, "trend": trend, "args": args})

    app._show_quick_price_overlay = capture_overlay
    try:
        db.add_price_record("测试物品", 1, "神圣石", "poe2db")
        db.add_price_record("神圣石", 100, "崇高石", "实时价格导入")

        app._show_quick_price_for_text("物品类别: 测试\n稀有度: 普通\n测试物品\n--------")

        assert captured["price"] == "100 崇高石"
    finally:
        db.close()


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
        assert "趋势：暂无" in label.text
        assert "实时价格导入-卖出" in label.text
        assert "2026-01-02" in label.text
    finally:
        db.close()


def test_realtime_current_price_prefers_valid_realtime_records_for_stats_and_trend():
    db = PriceDatabase(Path(":memory:"))
    try:
        db.add_price_record(
            "测试物品",
            999,
            "神圣石",
            "poe2db",
            captured_at="2026-01-03T00:00:00+00:00",
        )
        db.upsert_synced_realtime_price_record(
            remote_key="remote:item:1",
            item_name="测试物品",
            side="卖出",
            amount=10,
            currency="崇高石",
            source="实时价格导入",
            captured_at="2026-01-01T00:00:00+00:00",
            upvotes=2,
        )
        db.upsert_synced_realtime_price_record(
            remote_key="remote:item:2",
            item_name="测试物品",
            side="卖出",
            amount=12,
            currency="崇高石",
            source="实时价格导入",
            captured_at="2026-01-02T00:00:00+00:00",
            upvotes=2,
        )
        app = PriceTrackerApp.__new__(PriceTrackerApp)
        label = _Label()
        app.db = db
        app.realtime_import_labels = {"current_price": label}
        app.realtime_item_var = _Var("测试物品")
        app.realtime_currency_var = _Var("崇高石")
        app.display_currency_var = _Var("神圣石")
        app.config = SimpleNamespace(display_currency="神圣石")
        app._realtime_min_upvotes = lambda: 1

        app._update_realtime_current_price_label()

        assert "当前记录：12 崇高石" in label.text
        assert "趋势：+20%" in label.text
        assert "实时价格导入-卖出" in label.text
        assert "999" not in label.text
    finally:
        db.close()


def test_realtime_current_price_prefers_base_currency_realtime_pair_history():
    db = PriceDatabase(Path(":memory:"))
    try:
        db.add_price_record(
            "神圣石",
            150,
            "崇高石",
            "poe2db",
            captured_at="2026-01-03T00:00:00+00:00",
        )
        db.upsert_synced_realtime_price_record(
            remote_key="remote:currency:1",
            item_name="神圣石",
            side="卖出",
            amount=180,
            currency="崇高石",
            source="实时价格导入",
            captured_at="2026-01-01T00:00:00+00:00",
            upvotes=2,
        )
        db.upsert_synced_realtime_price_record(
            remote_key="remote:currency:2",
            item_name="神圣石",
            side="卖出",
            amount=181,
            currency="崇高石",
            source="实时价格导入",
            captured_at="2026-01-02T00:00:00+00:00",
            upvotes=2,
        )
        app = PriceTrackerApp.__new__(PriceTrackerApp)
        label = _Label()
        app.db = db
        app.realtime_import_labels = {"current_price": label}
        app.realtime_item_var = _Var("神圣石")
        app.realtime_currency_var = _Var("崇高石")
        app.display_currency_var = _Var("神圣石")
        app.config = SimpleNamespace(display_currency="神圣石")
        app._realtime_min_upvotes = lambda: 1

        app._update_realtime_current_price_label()

        assert "当前兑换：181 崇高石" in label.text
        assert "趋势：+1%" in label.text
        assert "实时价格导入-卖出" in label.text
        assert "150" not in label.text
    finally:
        db.close()


def test_update_check_worker_posts_failure_event_on_exception(monkeypatch):
    app = PriceTrackerApp.__new__(PriceTrackerApp)
    app.config = SimpleNamespace(update_manifest="")
    app.events = queue.Queue()

    def fail(_manifest, timeout=0):
        raise RuntimeError("boom")

    monkeypatch.setattr(app_module, "check_update", fail)

    app._check_update_worker(False)
    kind, info, silent = app.events.get_nowait()

    assert kind == "update_check_done"
    assert not info.available
    assert "boom" in info.message
    assert silent is False


def test_update_check_restarts_stale_pending_check(monkeypatch):
    app = PriceTrackerApp.__new__(PriceTrackerApp)
    app.updating = False
    app.update_checking = True
    app.update_check_started_at = time.monotonic() - 30
    app.update_check_token = 5
    app.latest_update_info = None
    app.config = SimpleNamespace(update_manifest="")
    app.progress_var = _Var()
    app.root = SimpleNamespace(after=lambda *_args, **_kwargs: None)
    app._set_manual_download_button_enabled = lambda *_args: None
    app._set_version_update_status = lambda *_args, **_kwargs: None
    app._set_progress_busy = lambda text: app.progress_var.set(text)
    started = {}

    class ImmediateThread:
        def __init__(self, target, args=(), daemon=False):
            self.target = target
            self.args = args
            self.daemon = daemon

        def start(self):
            started["args"] = self.args

    monkeypatch.setattr(app_module.threading, "Thread", ImmediateThread)
    app._check_update_worker = lambda *args: started.setdefault("worker_args", args)

    app.check_for_updates(silent=False)

    assert app.update_checking
    assert app.update_check_token > 5
    assert started["args"][0] is False
    assert app.progress_var.get() == "正在检查更新..."


def test_update_check_result_schedules_update_dialog():
    app = PriceTrackerApp.__new__(PriceTrackerApp)
    app.update_checking = True
    app.update_check_started_at = time.monotonic()
    app.latest_update_info = None
    app.progress_var = _Var()
    app.version_status_var = _Var()
    app.update_dialog_window = None
    app.update_dialog_version = ""
    app.root = SimpleNamespace(after_idle=lambda callback: callback())
    app._set_manual_download_button_enabled = lambda *_args: None
    app._set_version_update_status = lambda text, available=False: app.version_status_var.set(text)
    app._set_progress_then_idle = lambda text: app.progress_var.set(text)
    shown = {}
    app._show_update_available_dialog = lambda info: shown.setdefault("version", info.latest_version)
    info = UpdateInfo(True, "0.4.9", "1.0.0", "https://example.com/app.exe", "", "found")

    app._handle_update_check_result(info, silent=False)

    assert shown["version"] == "1.0.0"
    assert app.latest_update_info is info
    assert app.version_status_var.get()


def test_update_download_button_uses_ttk_supported_options():
    options = {"text": "手动下载", "command": lambda: None, "width": 10}
    unsupported = {"bg", "fg", "activebackground", "activeforeground", "relief", "padx"}

    assert unsupported.isdisjoint(options)
