import shutil
import uuid
from pathlib import Path
from types import SimpleNamespace

from poe2_price_tracker.app import PriceTrackerApp
from poe2_price_tracker.parser import ParsedItemPrice


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
