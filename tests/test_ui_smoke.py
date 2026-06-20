from __future__ import annotations

import pytest

from poe2_price_tracker import app as app_module
from poe2_price_tracker.config import AppConfig
from poe2_price_tracker.db import MarketRow, PriceDatabase
from poe2_price_tracker.themes import theme_for_key


@pytest.fixture
def ui_app(monkeypatch, tmp_path):
    config = AppConfig(
        data_dir=str(tmp_path / "app-data"),
        auto_check_updates=False,
        preload_ocr_on_start=False,
        ui_theme="default",
        font_size=18,
    )
    monkeypatch.setattr(app_module, "tb", None)
    monkeypatch.setattr(app_module, "load_config", lambda: config)
    monkeypatch.setattr(app_module.PriceTrackerApp, "_make_ocr_engine", lambda self: None)
    monkeypatch.setattr(app_module.PriceTrackerApp, "_register_hotkeys", lambda self: None)
    monkeypatch.setattr(app_module.PriceTrackerApp, "_ensure_tray_icon", lambda self: None)
    monkeypatch.setattr(app_module.PriceTrackerApp, "_focus_main_window_once", lambda self: None)
    monkeypatch.setattr(app_module.PriceTrackerApp, "_watch_quick_price_overlay", lambda *args, **kwargs: None)
    monkeypatch.setattr(app_module, "PriceDatabase", lambda _path: PriceDatabase(app_module.Path(":memory:")))

    root = app_module.Tk()
    root.withdraw()
    app = app_module.PriceTrackerApp(root)
    _seed_lookup_records(app)
    try:
        yield app
    finally:
        for overlay_name in (
            "quick_price_overlay",
            "focus_search_overlay",
            "screenshot_lookup_overlay",
            "realtime_import_overlay",
            "update_dialog_window",
        ):
            overlay = getattr(app, overlay_name, None)
            if overlay is not None:
                try:
                    overlay.destroy()
                except Exception:
                    pass
        try:
            app.hotkeys.stop()
        except Exception:
            pass
        try:
            app.db.close()
        except Exception:
            pass
        try:
            root.destroy()
        except Exception:
            pass


def _pump(app, cycles: int = 2) -> None:
    for _ in range(cycles):
        app.root.update_idletasks()
        app.root.update()


def _walk_widgets(widget):
    yield widget
    for child in widget.winfo_children():
        yield from _walk_widgets(child)


def _seed_lookup_records(app) -> None:
    app.db.add_price_record(
        "Very Long Screenshot Lookup Item Name Alpha",
        1.234,
        "Divine Orb",
        "realtime",
        raw_text="trend=+12%",
        captured_at="2026-06-20T12:00:00+00:00",
    )
    app.db.add_price_record(
        "Very Long Screenshot Lookup Item Name Beta",
        5.678,
        "Divine Orb",
        "poe2db",
        raw_text="trend=-8%",
        captured_at="2026-06-19T12:00:00+00:00",
    )
    app.db.add_price_record(
        "Compact Search Target",
        42,
        "Exalted Orb",
        "manual",
        raw_text="trend=+3%",
        captured_at="2026-06-18T12:00:00+00:00",
    )
    app.db.add_price_record(
        "Unrelated Hidden Item",
        99,
        "Chaos Orb",
        "manual",
        raw_text="trend=+1%",
        captured_at="2026-06-17T12:00:00+00:00",
    )


def _tree_item_names(app) -> list[str]:
    return [str(app.market_tree.set(iid, "item")) for iid in app.market_tree.get_children("")]


def _visible_texts(widget) -> list[str]:
    texts = []
    for child in _walk_widgets(widget):
        try:
            text = child.cget("text")
        except Exception:
            continue
        if text:
            texts.append(str(text))
    return texts


def _assert_canvas_contains_children_bottom(canvas, content) -> None:
    canvas.update_idletasks()
    children = content.winfo_children()
    assert children
    canvas_bottom = canvas.winfo_rooty() + canvas.winfo_height()
    content_bottom = max(child.winfo_rooty() + max(child.winfo_height(), child.winfo_reqheight()) for child in children)
    assert content_bottom <= canvas_bottom


@pytest.mark.gui
def test_app_ui_smoke_startup_pages_theme_and_overlays(ui_app):
    app = ui_app

    for show_page in (
        app.show_market_page,
        app.show_favorites_page,
        app.show_manual_record_page,
        app.show_market_exchange_page,
        app.show_ocr_review_page,
        app.show_settings_page,
    ):
        show_page()
        _pump(app)
        assert app.content.winfo_children()

    app.show_market_page()
    _pump(app)

    assert app.market_tree.winfo_exists()
    assert str(app.market_tree.column("currency", option="anchor")) == "center"
    assert str(app.market_tree.column("source", option="anchor")) == "center"
    assert str(app.market_tree.column("updated", option="anchor")) == "center"

    app.search_var.set("Screenshot Lookup")
    app.refresh_market_table()
    _pump(app)
    names = _tree_item_names(app)
    assert names == [
        "Very Long Screenshot Lookup Item Name Alpha",
        "Very Long Screenshot Lookup Item Name Beta",
    ]

    app.search_var.set("No Such Item")
    app.refresh_market_table()
    _pump(app)
    assert _tree_item_names(app) == []

    app.search_var.set("")
    app.refresh_market_table()
    _pump(app)
    assert len(_tree_item_names(app)) >= 4

    app.config.font_size = 24
    app.settings_font_var.set("24")

    for theme_key in ("default", "night", "poe2"):
        app.config.ui_theme = theme_key
        app.theme = theme_for_key(theme_key)
        app._configure_style()
        app._apply_theme_to_widget_tree(app.root)
        app.show_market_page()
        _pump(app)

        assert app.sidebar.winfo_reqwidth() <= app.sidebar.winfo_width()
        assert app.market_tree.winfo_height() > 120

    app.config.font_size = 20
    app.settings_font_var.set("20")
    app.config.ui_theme = "poe2"
    app.theme = theme_for_key("poe2")
    app._configure_style()
    app._quick_price_anchor = (320, 240)

    app._show_quick_price_overlay(
        "Test Item",
        "1.234 Divine Orb",
        "realtime import",
        "+12%",
        rating_record_id=1,
        rating_source="realtime",
        rating_upvotes=3,
    )
    _pump(app)

    labels = app.quick_price_overlay_labels
    assert labels["price"].cget("fg") == app._overlay_price_color()
    assert labels["trend"].cget("fg") == app._overlay_trend_color("+12%")
    rating_children = labels["rating"].winfo_children()
    assert rating_children
    assert all(str(child.cget("highlightthickness")) == "0" for child in rating_children if "highlightthickness" in child.keys())

    app._show_quick_price_for_text("Compact Search Target")
    _pump(app)
    assert app.quick_price_overlay_labels["title"].cget("text") == "Compact Search Target"
    assert app.display_currency_var.get() in app.quick_price_overlay_labels["price"].cget("text")

    app._show_quick_price_for_text("Definitely Missing Item")
    _pump(app)
    assert app.quick_price_overlay_labels["title"].cget("text") == "Definitely Missing Item"
    assert "没有" in app.quick_price_overlay_labels["price"].cget("text") or "娌℃湁" in app.quick_price_overlay_labels["price"].cget("text")

    app.show_focus_search_overlay()
    app.focus_search_var.set("Screenshot Lookup")
    app.refresh_focus_search_results()
    _pump(app)
    focus_texts = _visible_texts(app.focus_search_results)
    assert any("Very Long Screenshot Lookup Item Name Alpha" in text for text in focus_texts)
    assert any("Very Long Screenshot Lookup Item Name Beta" in text for text in focus_texts)

    app.focus_search_var.set("Nothing Matches Here")
    app.refresh_focus_search_results()
    _pump(app)
    assert any("没有" in text or "娌℃湁" in text for text in _visible_texts(app.focus_search_results))
    app.destroy_focus_search_overlay()

    screenshot_rows = app.db.get_market_rows(query="Screenshot Lookup", sort_by="name", descending=False, limit=10)
    assert len(screenshot_rows) == 2

    app.config.font_size = 24
    app.settings_font_var.set("24")
    app._configure_style()
    app._current_monitor_work_area = lambda: (0, 0, 900, 360)
    app.show_screenshot_lookup_results([(row, 1.0, "raw") for row in screenshot_rows])
    _pump(app)

    assert app.screenshot_lookup_overlay is not None
    assert app.screenshot_lookup_overlay.winfo_exists()
    assert app.screenshot_lookup_overlay.winfo_height() <= app._screenshot_lookup_max_overlay_height()
    screenshot_texts = _visible_texts(app.screenshot_lookup_results)
    assert any("realtime" in text for text in screenshot_texts)
    assert any("poe2db" in text for text in screenshot_texts)
    assert any("2026-06-20" in text for text in screenshot_texts)
    assert any("2026-06-19" in text for text in screenshot_texts)
    price_boxes = [
        widget
        for widget in _walk_widgets(app.screenshot_lookup_results)
        if getattr(widget, "_screenshot_lookup_price_box", False)
    ]
    assert price_boxes
    price_labels = [
        widget
        for widget in _walk_widgets(app.screenshot_lookup_results)
        if getattr(widget, "_screenshot_lookup_price_value", False)
    ]
    rating_slots = [
        widget
        for widget in _walk_widgets(app.screenshot_lookup_results)
        if getattr(widget, "_screenshot_lookup_rating_slot", False)
    ]
    trend_labels = [
        widget
        for widget in _walk_widgets(app.screenshot_lookup_results)
        if getattr(widget, "_screenshot_lookup_trend_value", False)
    ]
    assert price_labels
    assert rating_slots
    assert trend_labels
    assert all(label.winfo_width() > 0 for label in price_labels)
    assert all(slot.winfo_width() >= app._rating_slot_width(app._scaled(19, 17, 28)) - 2 for slot in rating_slots)
    for label, slot in zip(price_labels, rating_slots):
        assert label.winfo_rootx() + label.winfo_width() <= slot.winfo_rootx()
    for label, slot in zip(trend_labels, rating_slots):
        assert label.winfo_rootx() + label.winfo_width() <= slot.winfo_rootx()
    canvas = app.screenshot_lookup_results_canvas
    scrollbar = app.screenshot_lookup_results_scrollbar
    assert canvas is not None
    assert scrollbar is not None
    scrollregion = tuple(int(float(value)) for value in str(canvas.cget("scrollregion")).split())
    if len(scrollregion) == 4 and scrollregion[3] > canvas.winfo_height():
        assert scrollbar.winfo_ismapped()

    app._choose_screenshot_lookup_item("Very Long Screenshot Lookup Item Name Alpha")
    _pump(app)
    assert app.search_var.get() == "Very Long Screenshot Lookup Item Name Alpha"


@pytest.mark.gui
def test_small_font_overlay_results_are_not_clipped_at_bottom(ui_app):
    app = ui_app
    app.config.font_size = 13
    app.settings_font_var.set("13")
    app._configure_style()
    app.config.ui_theme = "poe2"
    app.theme = theme_for_key("poe2")

    app.show_focus_search_overlay()
    app.focus_search_var.set("Screenshot Lookup")
    app.refresh_focus_search_results()
    _pump(app, 3)
    assert app.focus_search_results_canvas is not None
    assert app.focus_search_results is not None
    _assert_canvas_contains_children_bottom(app.focus_search_results_canvas, app.focus_search_results)
    app.destroy_focus_search_overlay()

    screenshot_rows = app.db.get_market_rows(query="Screenshot Lookup", sort_by="name", descending=False, limit=10)
    app._current_monitor_work_area = lambda: (0, 0, 900, 360)
    app.show_screenshot_lookup_results([(row, 1.0, "raw") for row in screenshot_rows])
    _pump(app, 3)
    assert app.screenshot_lookup_results_canvas is not None
    assert app.screenshot_lookup_results is not None
    _assert_canvas_contains_children_bottom(app.screenshot_lookup_results_canvas, app.screenshot_lookup_results)
