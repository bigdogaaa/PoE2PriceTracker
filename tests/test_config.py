from poe2_price_tracker.config import AppConfig, GITEE_UPDATE_MANIFEST_URL, GITHUB_UPDATE_MANIFEST_URL, effective_update_manifest
from poe2_price_tracker.config import default_ocr_cpu_threads
from poe2_price_tracker.config import _apply_font_size_migration
from poe2_price_tracker.config import FONT_SIZE_MIGRATION_VERSION
from poe2_price_tracker.config import normalize_extra_update_manifest, should_reset_update_manifest
from poe2_price_tracker.config import normalize_price_share_service_url
from poe2_price_tracker.themes import THEME_LABELS, normalize_theme_key, theme_key_for_label, theme_label_for_key


def test_local_price_share_service_url_is_migrated_to_default():
    default = "http://example.invalid:8787"

    assert normalize_price_share_service_url("http://127.0.0.1:8787", default) == default
    assert normalize_price_share_service_url("localhost:8787", default) == default
    assert normalize_price_share_service_url("", default) == default
    assert normalize_price_share_service_url("share.example.test:8787", default) == "http://share.example.test:8787"


def test_update_manifest_default_is_kept():
    assert normalize_extra_update_manifest("") == ""
    assert effective_update_manifest("") == GITEE_UPDATE_MANIFEST_URL
    assert should_reset_update_manifest(GITEE_UPDATE_MANIFEST_URL)
    assert not should_reset_update_manifest(GITHUB_UPDATE_MANIFEST_URL)


def test_default_config_keeps_github_as_deletable_fallback_and_directml_ocr():
    config = AppConfig()

    assert config.update_manifest == GITHUB_UPDATE_MANIFEST_URL
    assert effective_update_manifest(config.update_manifest) == f"{GITEE_UPDATE_MANIFEST_URL}\n{GITHUB_UPDATE_MANIFEST_URL}"
    assert config.ocr_execution_provider == "directml"
    assert config.ocr_cpu_threads == default_ocr_cpu_threads()
    assert config.price_decimal_places == 3
    assert config.ui_theme == "poe2"
    assert config.font_size == 20


def test_font_size_migration_forces_twenty_once():
    config = AppConfig(font_size=13, font_size_configured=True, font_size_migration_version="")

    _apply_font_size_migration(config, {"font_size": 13, "font_size_configured": True})

    assert config.font_size == 20
    assert config.font_size_migration_version == FONT_SIZE_MIGRATION_VERSION

    config.font_size = 24
    _apply_font_size_migration(config, {"font_size_migration_version": FONT_SIZE_MIGRATION_VERSION})

    assert config.font_size == 24


def test_theme_keys_and_labels_are_stable():
    assert THEME_LABELS == ("白色", "深色", "黑金")
    assert normalize_theme_key("night") == "night"
    assert normalize_theme_key("unknown") == "default"
    assert theme_label_for_key("poe2") == "黑金"
    assert theme_key_for_label("深色") == "night"
    assert theme_key_for_label("bad label") == "default"


def test_legacy_update_manifests_are_reset():
    assert not should_reset_update_manifest("")
    assert should_reset_update_manifest("http://tgu7052fc.hb-bkt.clouddn.com/poe2-price-tracker/latest.json")
    assert should_reset_update_manifest("https://gitee.com/BiGDoGaaa/poe2pricetracker_version_info")
    assert should_reset_update_manifest("https://gitee.com/BiGDoGaaa/poe2pricetracker_version_info/releases/latest")


def test_extra_update_manifest_filters_builtin_and_keeps_custom_sources():
    custom = "https://example.invalid/latest.json"
    raw = f"{GITEE_UPDATE_MANIFEST_URL}\n{GITHUB_UPDATE_MANIFEST_URL}\n{custom}\n{custom}"

    assert normalize_extra_update_manifest(raw) == f"{GITHUB_UPDATE_MANIFEST_URL}\n{custom}"
    assert effective_update_manifest(raw) == f"{GITEE_UPDATE_MANIFEST_URL}\n{GITHUB_UPDATE_MANIFEST_URL}\n{custom}"
