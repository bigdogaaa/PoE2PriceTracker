from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


APP_DIR_NAME = "PoE2PriceTracker"


def default_data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / APP_DIR_NAME
    return Path.home() / f".{APP_DIR_NAME}"


@dataclass
class HotkeyConfig:
    lookup_hovered: str = "F1"
    capture_price: str = "F2"
    focus_search: str = "F3"


@dataclass
class AppConfig:
    data_dir: str = str(default_data_dir())
    screenshot_width: int = 760
    screenshot_height: int = 520
    tesseract_cmd: str = "tesseract"
    ocr_download_url: str = "https://digi.bib.uni-mannheim.de/tesseract/tesseract-ocr-w64-setup-5.4.0.20240606.exe"
    ocr_languages: str = "chi_sim+eng"
    ocr_psm: int = 6
    font_size: int = 15
    display_currency: str = "神圣石"
    page_size: int = 50
    manual_add_favorite: bool = True
    minimize_action: str = "ask"
    close_action: str = "ask"
    visible_columns: list[str] = field(
        default_factory=lambda: ["序号", "物品", "价格", "单位", "走势", "记录", "来源", "更新时间", "收藏"]
    )
    update_manifest: str = ""
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
        loaded.hotkeys.focus_search = "F3"
    if loaded.font_size < 15:
        loaded.font_size = 15
    ensure_dirs(loaded)
    save_config(loaded)
    return loaded


def save_config(config: AppConfig) -> None:
    ensure_dirs(config)
    with config.config_path.open("w", encoding="utf-8") as fh:
        json.dump(asdict(config), fh, ensure_ascii=False, indent=2)


def ensure_dirs(config: AppConfig) -> None:
    config.data_path.mkdir(parents=True, exist_ok=True)
    config.screenshots_path.mkdir(parents=True, exist_ok=True)
