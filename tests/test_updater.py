import hashlib
import json
import shutil
import zipfile
from pathlib import Path

from poe2_price_tracker import updater


def _tmp_dir(tmp_path: Path) -> Path:
    path = tmp_path / "updater"
    path.mkdir()
    return path


def test_check_update_accepts_channel_manifest_fields(monkeypatch, tmp_path):
    tmp_path = _tmp_dir(tmp_path)
    monkeypatch.setattr(updater, "__version__", "1.0.0")
    try:
        package = tmp_path / "PoE2PriceTracker-9.9.9.exe"
        package.write_bytes(b"test package")
        manifest = tmp_path / "latest.json"
        manifest.write_text(
            json.dumps(
                {
                    "version": "9.9.9",
                    "url": package.name,
                    "sha256": hashlib.sha256(package.read_bytes()).hexdigest(),
                    "size": package.stat().st_size,
                    "notes": ["channel source"],
                }
            ),
            encoding="utf-8",
        )

        info = updater.check_update(str(manifest))

        assert info.available
        assert info.download_url == package.name
        assert info.manifest_location == str(manifest)
        assert info.size == package.stat().st_size
        assert info.notes == ("channel source",)
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)


def test_check_update_falls_back_to_second_manifest(monkeypatch, tmp_path):
    tmp_path = _tmp_dir(tmp_path)
    monkeypatch.setattr(updater, "__version__", "1.0.0")
    try:
        good = tmp_path / "latest.json"
        good.write_text(json.dumps({"version": "2.0.0", "download_url": "app.exe"}), encoding="utf-8")
        missing = tmp_path / "missing.json"

        info = updater.check_update(f"{missing}\n{good}")

        assert info.available
        assert info.latest_version == "2.0.0"
        assert info.manifest_location == str(good)
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)


def test_check_update_stops_after_first_valid_manifest(monkeypatch):
    calls = []
    monkeypatch.setattr(updater, "__version__", "1.0.0")

    def fake_read_manifest(location, timeout=0):
        calls.append(location)
        return {"version": "2.0.0", "download_url": f"{location}.exe"}

    monkeypatch.setattr(updater, "_read_manifest", fake_read_manifest)

    info = updater.check_update("first\nsecond\nthird")

    assert info.available
    assert info.manifest_location == "first"
    assert calls == ["first"]


def test_check_update_accepts_utf8_sig_manifest(monkeypatch, tmp_path):
    tmp_path = _tmp_dir(tmp_path)
    monkeypatch.setattr(updater, "__version__", "1.0.0")
    try:
        manifest = tmp_path / "latest.json"
        manifest.write_text(
            "\ufeff" + json.dumps({"version": "2.0.0", "download_url": "app.exe"}),
            encoding="utf-8",
        )

        info = updater.check_update(str(manifest))

        assert info.available
        assert info.latest_version == "2.0.0"
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)


def test_check_update_reads_manual_download_urls(monkeypatch, tmp_path):
    tmp_path = _tmp_dir(tmp_path)
    monkeypatch.setattr(updater, "__version__", "1.0.0")
    try:
        manifest = tmp_path / "latest.json"
        manifest.write_text(
            json.dumps(
                {
                    "version": "2.0.0",
                    "download_url": "PoE2PriceTracker-2.0.0.exe",
                    "manual_urls": [{"name": "Quark", "url": "https://pan.quark.cn/s/example"}],
                }
            ),
            encoding="utf-8",
        )

        info = updater.check_update(str(manifest))

        assert info.available
        assert info.download_url == "PoE2PriceTracker-2.0.0.exe"
        assert info.manual_urls == ("https://pan.quark.cn/s/example",)
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)


def test_download_update_checks_size_and_sha256(tmp_path):
    tmp_path = _tmp_dir(tmp_path)
    try:
        package = tmp_path / "PoE2PriceTracker-2.0.0.exe"
        package.write_bytes(b"binary")
        digest = hashlib.sha256(package.read_bytes()).hexdigest()
        manifest = tmp_path / "latest.json"
        manifest.write_text(json.dumps({"version": "2.0.0", "download_url": package.name}), encoding="utf-8")
        info = updater.UpdateInfo(
            True,
            "1.0.0",
            "2.0.0",
            package.name,
            digest,
            "",
            str(manifest),
            package.stat().st_size,
        )

        result = updater.download_update(str(manifest), info, tmp_path / "updates")

        assert result.executable_path is not None
        assert result.executable_path.name == package.name
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)


def test_download_update_falls_back_to_download_mirror(tmp_path):
    tmp_path = _tmp_dir(tmp_path)
    try:
        package = tmp_path / "PoE2PriceTracker-2.0.0.exe"
        package.write_bytes(b"binary")
        missing = tmp_path / "missing.exe"
        digest = hashlib.sha256(package.read_bytes()).hexdigest()
        manifest = tmp_path / "latest.json"
        manifest.write_text(
            json.dumps(
                {
                    "version": "2.0.0",
                    "download_url": missing.name,
                    "download_urls": [missing.name, package.name],
                    "sha256": digest,
                    "size": package.stat().st_size,
                }
            ),
            encoding="utf-8",
        )
        info = updater.UpdateInfo(
            True,
            "1.0.0",
            "2.0.0",
            missing.name,
            digest,
            "",
            str(manifest),
            package.stat().st_size,
            (),
            (missing.name, package.name),
        )

        result = updater.download_update(str(manifest), info, tmp_path / "updates")

        assert result.executable_path is not None
        assert result.executable_path.read_bytes() == b"binary"
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)


def test_download_update_stages_executable_next_to_current_app_dir(tmp_path):
    tmp_path = _tmp_dir(tmp_path)
    try:
        package = tmp_path / "PoE2PriceTracker-2.0.0.zip"
        with zipfile.ZipFile(package, "w") as archive:
            archive.writestr("PoE2PriceTracker-2.0.0.exe", b"binary")
        digest = hashlib.sha256(package.read_bytes()).hexdigest()
        manifest = tmp_path / "latest.json"
        manifest.write_text(json.dumps({"version": "2.0.0", "download_url": package.name}), encoding="utf-8")
        info = updater.UpdateInfo(
            True,
            "1.0.0",
            "2.0.0",
            package.name,
            digest,
            "",
            str(manifest),
            package.stat().st_size,
        )
        app_dir = tmp_path / "app"
        app_dir.mkdir()

        result = updater.download_update(str(manifest), info, tmp_path / "updates", app_dir=app_dir)

        assert result.extract_dir.name == "extracted"
        assert result.executable_path == app_dir / "PoE2PriceTracker-2.0.0.exe"
        assert result.executable_path.read_bytes() == b"binary"
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)
