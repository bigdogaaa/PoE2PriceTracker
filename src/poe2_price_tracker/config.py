from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


APP_DIR_NAME = "PoE2PriceTracker"
GITHUB_RELEASE_BASE = "https://github.com/bigdogaaa/PoE2PriceTracker/releases"
UPDATE_MANIFEST_URL = f"{GITHUB_RELEASE_BASE}/latest/download/latest.json"
LEGACY_RELEASE_REPO_DOWNLOAD_BASE = "https://gitee.com/BiGDoGaaa/poe2-price-tracker-release/releases/download"
LEGACY_SOURCE_REPO_DOWNLOAD_BASE = "https://gitee.com/BiGDoGaaa/poe2-price-tracker/releases/download"


def default_data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / APP_DIR_NAME
    return Path.home() / f".{APP_DIR_NAME}"


@dataclass
class HotkeyConfig:
    lookup_hovered: str = "F1"
    capture_price: str = "F2"
    focus_search: str = "Ctrl+Space"
    quick_price: str = "F4"


@dataclass
class AppConfig:
    data_dir: str = str(default_data_dir())
    screenshot_width: int = 760
    screenshot_height: int = 520
    ocr_engine: str = "rapidocr"
    font_size: int = 15
    display_currency: str = "神圣石"
    page_size: int = 25
    focus_search_rounded: bool = True
    focus_search_limit: int = 5
    manual_add_favorite: bool = True
    preload_ocr_on_start: bool = False
    screenshot_retention_count: int = 20
    show_ocr_review_details: bool = True
    minimize_action: str = "ask"
    close_action: str = "ask"
    visible_columns: list[str] = field(
        default_factory=lambda: ["序号", "图标", "物品", "价格", "单位", "走势", "记录", "来源", "更新时间", "收藏"]
    )
    update_manifest: str = UPDATE_MANIFEST_URL
    hotkeys: HotkeyConfig = field(default_factory=HotkeyConfig)

    @property
    def data_path(self) -> Path:
        return Path(self.data_dir)

    @property
    def database_path(self) -> Path:
        return self.data_path / "prices.sqlite3"

    @property
    def screenshots_path(self) -> Path:
        return self.data_path / "screenshots"

    @property
    def config_path(self) -> Path:
        return self.data_path / "config.json"


def _merge_dataclass(cls: type, data: dict[str, Any]):
    fields = {name for name in cls.__dataclass_fields__}  # type: ignore[attr-defined]
    filtered = {k: v for k, v in data.items() if k in fields}
    return cls(**filtered)


def load_config() -> AppConfig:
    config = AppConfig()
    path = config.config_path
    if not path.exists():
        ensure_dirs(config)
        save_config(config)
        return config

    with path.open("r", encoding="utf-8") as fh:
        raw = json.load(fh)

    hotkeys = raw.get("hotkeys", {})
    raw["hotkeys"] = _merge_dataclass(HotkeyConfig, hotkeys)
    loaded = _merge_dataclass(AppConfig, raw)
    if loaded.hotkeys.lookup_hovered == "Ctrl+Alt+P":
        loaded.hotkeys.lookup_hovered = "F1"
    if loaded.hotkeys.capture_price == "Ctrl+Alt+O":
        loaded.hotkeys.capture_price = "F2"
    if loaded.hotkeys.focus_search == "Ctrl+Alt+F":
        loaded.hotkeys.focus_search = "Ctrl+Space"
    if loaded.hotkeys.focus_search == "F3":
        loaded.hotkeys.focus_search = "Ctrl+Space"
    if loaded.font_size < 15:
        loaded.font_size = 15
    if loaded.page_size == 50:
        loaded.page_size = 25
    try:
        loaded.focus_search_limit = max(1, min(10, int(loaded.focus_search_limit or 5)))
    except (TypeError, ValueError):
        loaded.focus_search_limit = 5
    try:
        loaded.screenshot_retention_count = max(1, min(500, int(loaded.screenshot_retention_count or 20)))
    except (TypeError, ValueError):
        loaded.screenshot_retention_count = 20
    if "图标" not in loaded.visible_columns:
        try:
            index = loaded.visible_columns.index("物品")
        except ValueError:
            index = 1
        loaded.visible_columns.insert(index, "图标")
    if loaded.ocr_engine != "rapidocr":
        loaded.ocr_engine = "rapidocr"
    if (
        not loaded.update_manifest.strip()
        or LEGACY_SOURCE_REPO_DOWNLOAD_BASE in loaded.update_manifest
        or LEGACY_RELEASE_REPO_DOWNLOAD_BASE in loaded.update_manifest
    ):
        loaded.update_manifest = config.update_manifest
    ensure_dirs(loaded)
    save_config(loaded)
    return loaded


def save_config(config: AppConfig) -> None:
    try:
        ensure_dirs(config)
        with config.config_path.open("w", encoding="utf-8") as fh:
            json.dump(asdict(config), fh, ensure_ascii=False, indent=2)
    except OSError:
        return


def ensure_dirs(config: AppConfig) -> None:
    config.data_path.mkdir(parents=True, exist_ok=True)
    config.screenshots_path.mkdir(parents=True, exist_ok=True)
