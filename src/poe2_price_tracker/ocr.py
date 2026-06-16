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

    @staticmethod
    def _tessdata_dir(command: str) -> Path | None:
        path = Path(command)
        candidates = [
            path.parent / "tessdata",
            path.parent.parent / "tessdata",
        ]
        for candidate in candidates:
            if (candidate / "chi_sim.traineddata").exists() and (candidate / "eng.traineddata").exists():
                return candidate
        return None

    @staticmethod
    def _windows_startup_kwargs() -> dict:
        if sys.platform != "win32":
            return {}
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0
        return {
            "startupinfo": startupinfo,
            "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0),
        }

    def recognize(self, image_path: Path) -> OcrResult:
        resolved = self.resolved_command()
        if not resolved:
            return OcrResult(
                text="",
                engine="tesseract",
                ok=False,
                message="未找到本地 OCR。请在配置中选择 Tesseract 目录，或点击“自动准备 OCR”。",
            )

        tessdata_dir = self._tessdata_dir(resolved)
        cwd = str(Path(resolved).parent) if tessdata_dir else None
        tessdata_arg = "tessdata" if tessdata_dir and tessdata_dir.parent == Path(resolved).parent else str(tessdata_dir)
        cmd = [
            resolved,
            str(image_path),
            "stdout",
        ]
        if tessdata_dir:
            cmd.extend(["--tessdata-dir", tessdata_arg])
        cmd.extend([
            "--psm",
            str(self.psm),
            "--oem",
            "3",
            "-l",
            self.languages,
            "-c",
            "preserve_interword_spaces=1",
        ])
        try:
            completed = subprocess.run(
                cmd,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=8,
                cwd=cwd,
                **self._windows_startup_kwargs(),
            )
        except Exception as exc:
            return OcrResult("", "tesseract", False, str(exc))

        text = completed.stdout.strip()
        if completed.returncode != 0:
            return OcrResult(text, "tesseract", False, completed.stderr.strip())
        return OcrResult(text, "tesseract", bool(text), "")
