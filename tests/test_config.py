from poe2_price_tracker.config import normalize_price_share_service_url


def test_local_price_share_service_url_is_migrated_to_default():
    default = "http://example.invalid:8787"

    assert normalize_price_share_service_url("http://127.0.0.1:8787", default) == default
    assert normalize_price_share_service_url("localhost:8787", default) == default
    assert normalize_price_share_service_url("", default) == default
    assert normalize_price_share_service_url("share.example.test:8787", default) == "http://share.example.test:8787"
