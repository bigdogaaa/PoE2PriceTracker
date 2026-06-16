from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class OcrResult:
    text: str
    engine: str
    ok: bool
    message: str = ""


class TesseractOcr:
    def __init__(self, command: str = "tesseract", languages: str = "eng", psm: int = 6):
        self.command = command
        self.languages = languages
        self.psm = psm

    @staticmethod
    def _candidate_from_path(value: str) -> list[str]:
        if not value.strip():
            return []
        path = Path(value)
        if path.is_dir():
            return [str(path / "tesseract.exe"), *[str(match) for match in path.rglob("tesseract.exe")]]
        return [value]

    def resolved_command(self) -> str | None:
        bundle_roots = []
        if hasattr(sys, "_MEIPASS"):
            bundle_roots.append(Path(sys._MEIPASS))  # type: ignore[attr-defined]
        bundle_roots.append(Path(sys.executable).resolve().parent)
        candidates = [
            *self._candidate_from_path(self.command),
            *[
                str(root / "ocr" / "tesseract" / "tesseract.exe")
                for root in bundle_roots
            ],
            "tesseract",
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        ]
        for candidate in candidates:
            if Path(candidate).exists():
                return candidate
            found = shutil.which(candidate)
            if found:
                return found
        return None

    def available(self) -> bool:
        return self.resolved_command() is not None

    def recognize(self, image_path: Path) -> OcrResult:
        resolved = self.resolved_command()
        if not resolved:
            return OcrResult(
                text="",
                engine="tesseract",
                ok=False,
                message="未找到本地 OCR。请在配置中选择 Tesseract 目录，或点击“自动准备 OCR”。",
            )

        cmd = [
            resolved,
            str(image_path),
            "stdout",
            "--psm",
            str(self.psm),
            "--oem",
            "3",
            "-l",
            self.languages,
            "-c",
            "preserve_interword_spaces=1",
        ]
        try:
            completed = subprocess.run(
                cmd,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=8,
            )
        except Exception as exc:
            return OcrResult("", "tesseract", False, str(exc))

        text = completed.stdout.strip()
        if completed.returncode != 0:
            return OcrResult(text, "tesseract", False, completed.stderr.strip())
        return OcrResult(text, "tesseract", bool(text), "")
