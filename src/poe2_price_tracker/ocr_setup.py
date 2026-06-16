from __future__ import annotations

import subprocess
import urllib.request
from dataclasses import dataclass
from pathlib import Path


DEFAULT_TESSDATA_BASE = "https://digi.bib.uni-mannheim.de/tesseract/traineddata"
LANGUAGE_FILES = ("eng.traineddata", "chi_sim.traineddata", "osd.traineddata")


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


def prepare_tesseract_ocr(data_dir: Path, installer_url: str, progress=None) -> OcrSetupResult:
    if not installer_url.strip():
        return OcrSetupResult(False, Path(), "未配置 OCR 下载地址。")

    ocr_root = data_dir / "ocr"
    install_dir = ocr_root / "tesseract"
    tesseract_path = install_dir / "tesseract.exe"
    if tesseract_path.exists():
        return OcrSetupResult(True, tesseract_path, "OCR 已准备好。")

    installer = ocr_root / "downloads" / Path(installer_url).name
    if progress:
        progress(0, installer_url)
    _download(installer_url, installer, progress)

    install_dir.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        [str(installer), "/S", f"/D={install_dir}"],
        check=False,
        capture_output=True,
        text=True,
        timeout=180,
    )
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip() or f"安装器返回代码 {completed.returncode}"
        return OcrSetupResult(False, tesseract_path, message)

    tessdata = install_dir / "tessdata"
    tessdata.mkdir(parents=True, exist_ok=True)
    for name in LANGUAGE_FILES:
        target = tessdata / name
        if target.exists():
            continue
        url = f"{DEFAULT_TESSDATA_BASE}/{name}"
        if progress:
            progress(0, url)
        _download(url, target, progress)

    if not tesseract_path.exists():
        return OcrSetupResult(False, tesseract_path, "OCR 安装完成，但未找到 tesseract.exe。")
    return OcrSetupResult(True, tesseract_path, "OCR 已自动下载并配置完成。")
