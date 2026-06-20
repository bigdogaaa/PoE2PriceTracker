import os
import re
import shutil
import uuid
from pathlib import Path

import pytest


os.environ.setdefault("POE2_PRICE_TRACKER_NO_ELEVATE", "1")
os.environ.setdefault("POE2_UPDATE_CHANNEL", "test")
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
_ROOT = Path(__file__).resolve().parents[1]
_TEST_CACHE = _ROOT / ".test-cache" / "test-tmp"


def pytest_addoption(parser):
    parser.addoption(
        "--run-gui",
        action="store_true",
        default=False,
        help="Run tests marked as gui. They may create windows or affect focus.",
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--run-gui"):
        return
    skip_gui = pytest.mark.skip(reason="gui test skipped by default; pass --run-gui to run it")
    for item in items:
        if "gui" in item.keywords:
            item.add_marker(skip_gui)


@pytest.fixture
def tmp_path(request):
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", request.node.name)[:80]
    path = _TEST_CACHE / f"{safe_name}-{uuid.uuid4().hex}"
    path.mkdir(parents=True, exist_ok=False)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


@pytest.fixture(autouse=True)
def _block_unexpected_messageboxes(monkeypatch):
    try:
        from poe2_price_tracker import app as app_module
    except Exception:
        return

    def unexpected(name):
        def inner(*args, **kwargs):
            raise AssertionError(f"unexpected tkinter.messagebox.{name} during unit test")

        return inner

    for name in ("showinfo", "showwarning", "showerror", "askyesno"):
        monkeypatch.setattr(app_module.messagebox, name, unexpected(name), raising=False)
