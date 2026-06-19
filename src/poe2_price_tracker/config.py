from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


APP_DIR_NAME = "PoE2PriceTracker"
GITHUB_RELEASE_BASE = "https://github.com/bigdogaaa/PoE2PriceTracker/releases"
GITHUB_UPDATE_MANIFEST_URL = f"{GITHUB_RELEASE_BASE}/latest/download/latest.json"
GITEE_RELEASE_REPO = "https://gitee.com/BiGDoGaaa/poe2pricetracker_version_info"
GITEE_UPDATE_MANIFEST_URL = f"{GITEE_RELEASE_REPO}/raw/master/latest.json"
LEGACY_QINIU_UPDATE_MANIFEST_URL = "http://tgu7052fc.hb-bkt.clouddn.com/poe2-price-tracker/latest.json"
UPDATE_MANIFEST_URL = GITHUB_UPDATE_MANIFEST_URL
LEGACY_RELEASE_REPO_DOWNLOAD_BASE = "https://gitee.com/BiGDoGaaa/poe2-price-tracker-release/releases/download"
LEGACY_SOURCE_REPO_DOWNLOAD_BASE = "https://gitee.com/BiGDoGaaa/poe2-price-tracker/releases/download"
GITEE_VERSION_INFO_REPO_MARKER = "gitee.com/bigdogaaa/poe2pricetracker_version_info"
GITEE_VERSION_INFO_RAW_MARKER = "raw.giteeusercontent.com/bigdogaaa/poe2pricetracker_version_info"


def default_ocr_cpu_threads() -> int:
    return max(1, (os.cpu_count() or 4) // 4)


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
    realtime_import: str = "F6"


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
    ocr_cpu_threads: int = field(default_factory=default_ocr_cpu_threads)
    ocr_execution_provider: str = "directml"
    ocr_low_priority: bool = True
    ocr_performance_configured: bool = False
    screenshot_retention_count: int = 20
    show_ocr_review_details: bool = True
    realtime_min_upvotes: int = 0
    price_share_service_url: str = "http://117.50.51.78:8787"
    auto_check_updates: bool = True
    update_sources_configured: bool = False
    minimize_action: str = "ask"
    close_action: str = "ask"
    visible_columns: list[str] = field(
        default_factory=lambda: ["序号", "图标", "物品", "价格", "单位", "走势", "记录", "来源", "评价", "更新时间", "收藏"]
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


def normalize_price_share_service_url(value: str, default: str) -> str:
    url = str(value or "").strip()
    if not url:
        url = default
    elif "://" not in url:
        url = "http://" + url
    if "127.0.0.1" in url or "localhost" in url.lower():
        url = default
    return url


def _split_update_manifest_sources(value: str) -> list[str]:
    sources: list[str] = []
    for line in str(value or "").replace(",", "\n").replace(";", "\n").splitlines():
        item = line.strip()
        if item:
            sources.append(item)
    return sources


def _is_obsolete_update_manifest_source(value: str) -> bool:
    item = str(value or "").strip()
    lower_item = item.lower()
    if not item:
        return True
    if item == GITEE_UPDATE_MANIFEST_URL:
        return True
    if LEGACY_QINIU_UPDATE_MANIFEST_URL in item:
        return True
    if LEGACY_SOURCE_REPO_DOWNLOAD_BASE in item:
        return True
    if LEGACY_RELEASE_REPO_DOWNLOAD_BASE in item:
        return True
    if GITEE_VERSION_INFO_REPO_MARKER in lower_item:
        return True
    if GITEE_VERSION_INFO_RAW_MARKER in lower_item:
        return True
    return False


def normalize_extra_update_manifest(value: str) -> str:
    sources: list[str] = []
    for item in _split_update_manifest_sources(value):
        if _is_obsolete_update_manifest_source(item):
            continue
        if item not in sources:
            sources.append(item)
    return "\n".join(sources)


def effective_update_manifest(value: str) -> str:
    sources = [GITEE_UPDATE_MANIFEST_URL]
    for item in _split_update_manifest_sources(normalize_extra_update_manifest(value)):
        if item not in sources:
            sources.append(item)
    return "\n".join(sources)


def should_reset_update_manifest(value: str) -> bool:
    return normalize_extra_update_manifest(value) != str(value or "").strip()


def load_config() -> AppConfig:
    config = AppConfig()
    path = config.config_path
    if not path.exists():
        ensure_dirs(config)
        save_config(config)
        return config

    with path.open("r", encoding="utf-8-sig") as fh:
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
    try:
        loaded.realtime_min_upvotes = max(0, min(999999, int(loaded.realtime_min_upvotes or 0)))
    except (TypeError, ValueError):
        loaded.realtime_min_upvotes = 0
    try:
        loaded.ocr_cpu_threads = max(0, min(64, int(loaded.ocr_cpu_threads or 0)))
    except (TypeError, ValueError):
        loaded.ocr_cpu_threads = 0
    if loaded.ocr_execution_provider not in {"cpu", "auto", "cuda", "directml"}:
        loaded.ocr_execution_provider = "directml"
    if not raw.get("ocr_performance_configured", False):
        if raw.get("ocr_execution_provider", "") in {"", "cpu", "auto"}:
            loaded.ocr_execution_provider = "directml"
        if int(loaded.ocr_cpu_threads or 0) <= 0:
            loaded.ocr_cpu_threads = default_ocr_cpu_threads()
    if "图标" not in loaded.visible_columns:
        try:
            index = loaded.visible_columns.index("物品")
        except ValueError:
            index = 1
        loaded.visible_columns.insert(index, "图标")
    if "评价" not in loaded.visible_columns:
        try:
            index = loaded.visible_columns.index("更新时间")
        except ValueError:
            index = len(loaded.visible_columns)
        loaded.visible_columns.insert(index, "评价")
    if loaded.ocr_engine != "rapidocr":
        loaded.ocr_engine = "rapidocr"
    loaded.price_share_service_url = normalize_price_share_service_url(
        getattr(loaded, "price_share_service_url", ""),
        config.price_share_service_url,
    )
    loaded.update_manifest = normalize_extra_update_manifest(loaded.update_manifest)
    if not raw.get("update_sources_configured", False) and not loaded.update_manifest:
        loaded.update_manifest = GITHUB_UPDATE_MANIFEST_URL
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
