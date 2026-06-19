import shutil
from pathlib import Path

from PIL import Image

from poe2_price_tracker import screenshot


def test_capture_around_cursor_clamps_to_virtual_screen(monkeypatch):
    captured = {}
    output_dir = Path(".tmp-screenshot-test")

    monkeypatch.setattr(screenshot, "get_cursor_position", lambda: screenshot.Point(-900, 200))
    monkeypatch.setattr(screenshot, "get_virtual_screen_bounds", lambda: (-1280, 0, 1920, 1080))

    def fake_grab(*, bbox, all_screens):
        captured["bbox"] = bbox
        captured["all_screens"] = all_screens
        return Image.new("RGB", (bbox[2] - bbox[0], bbox[3] - bbox[1]))

    monkeypatch.setattr(screenshot.ImageGrab, "grab", fake_grab)
    monkeypatch.setattr(screenshot, "enhance_for_ocr", lambda image: image)
    monkeypatch.setattr(screenshot, "_save_png_fast", lambda image, path: captured.update(path=path))
    monkeypatch.setattr(screenshot, "prune_screenshots", lambda *_args, **_kwargs: None)

    try:
        path = screenshot.capture_around_cursor(output_dir, 760, 520)

        assert captured["bbox"] == (-1280, 0, -520, 520)
        assert captured["all_screens"] is True
        assert path.parent == output_dir
    finally:
        shutil.rmtree(output_dir, ignore_errors=True)
