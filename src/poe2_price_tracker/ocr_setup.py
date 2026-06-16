from __future__ import annotations

import subprocess
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


GITHUB_TESSDATA_BASE = "https://raw.githubusercontent.com/tesseract-ocr/tessdata/main"
LANGUAGE_FILES = ("eng.traineddata", "chi_sim.traineddata", "osd.traineddata")
MIN_LANGUAGE_FILE_SIZES = {
    "eng.traineddata": 10_000_000,
    "chi_sim.traineddata": 20_000_000,
    "osd.traineddata": 5_000_000,
}


@dataclass(frozen=True)
class OcrSetupResult:
    ok: bool
    tesseract_path: Path
    message: str


def _download(url: str, target: Path, progress=None) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)

    def report(block_count: int, block_size: int, total_size: int) -> None:
        if progress and total_size > 0:
            percent = min(100, int(block_count * block_size * 100 / total_size))
            progress(percent, url)

    urllib.request.urlretrieve(url, target, reporthook=report)


def _local_name(url: str) -> str:
    parsed = urlparse(url)
    name = Path(parsed.path).name
    return name or "ocr-package"


def find_tesseract(root: Path) -> Path | None:
    direct = root / "tesseract.exe"
    if direct.exists():
        return direct
    matches = list(root.rglob("tesseract.exe"))
    return matches[0] if matches else None


def _ensure_language_files(tessdata: Path, progress=None) -> None:
    tessdata.mkdir(parents=True, exist_ok=True)
    for name in LANGUAGE_FILES:
        target = tessdata / name
        min_size = MIN_LANGUAGE_FILE_SIZES.get(name, 1)
        if target.exists() and target.stat().st_size >= min_size:
            continue
        url = f"{GITHUB_TESSDATA_BASE}/{name}"
        if progress:
            progress(0, url)
        _download(url, target, progress)


def _language_files_ready(tessdata: Path) -> bool:
    return all(
        (tessdata / name).exists() and (tessdata / name).stat().st_size >= MIN_LANGUAGE_FILE_SIZES[name]
        for name in LANGUAGE_FILES
    )


def _windows_startup_kwargs() -> dict:
    import sys

    if sys.platform != "win32":
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = 0
    return {
        "startupinfo": startupinfo,
        "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0),
    }


def _install_from_zip(package: Path, install_dir: Path, progress=None) -> OcrSetupResult:
    install_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(package) as archive:
        archive.extractall(install_dir)
    tesseract_path = find_tesseract(install_dir)
    if not tesseract_path:
        return OcrSetupResult(False, install_dir / "tesseract.exe", "OCR 压缩包中未找到 tesseract.exe。")
    _ensure_language_files(tesseract_path.parent / "tessdata", progress)
    return OcrSetupResult(True, tesseract_path, "OCR 已自动下载并配置完成。")


def _install_from_exe(installer: Path, install_dir: Path, progress=None) -> OcrSetupResult:
    install_dir.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        [str(installer), "/S", f"/D={install_dir}"],
        check=False,
        capture_output=True,
        text=True,
        timeout=180,
        **_windows_startup_kwargs(),
    )
    tesseract_path = install_dir / "tesseract.exe"
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip() or f"安装器返回代码 {completed.returncode}"
        return OcrSetupResult(False, tesseract_path, message)
    _ensure_language_files(install_dir / "tessdata", progress)
    if not tesseract_path.exists():
        return OcrSetupResult(False, tesseract_path, "OCR 安装完成，但未找到 tesseract.exe。")
    return OcrSetupResult(True, tesseract_path, "OCR 已自动下载并配置完成。")


def prepare_tesseract_ocr(
    data_dir: Path,
    package_url: str,
    progress=None,
    install_dir: Path | None = None,
) -> OcrSetupResult:
    if not package_url.strip():
        return OcrSetupResult(False, Path(), "未配置 OCR 下载地址。")

    ocr_root = data_dir / "ocr"
    install_dir = install_dir or (ocr_root / "tesseract")
    existing = find_tesseract(install_dir)
    if existing and _language_files_ready(existing.parent / "tessdata"):
        return OcrSetupResult(True, existing, "OCR 已准备好。")

    package = ocr_root / "downloads" / _local_name(package_url)
    if progress:
        progress(0, package_url)
    _download(package_url, package, progress)

    suffix = package.suffix.lower()
    if suffix == ".zip":
        return _install_from_zip(package, install_dir, progress)
    if suffix == ".exe":
        return _install_from_exe(package, install_dir, progress)
    return OcrSetupResult(False, package, "不支持的 OCR 包格式，请使用 .zip 或 .exe。")
