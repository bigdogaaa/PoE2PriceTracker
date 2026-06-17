from __future__ import annotations

import ctypes
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageEnhance, ImageFilter, ImageGrab, ImageOps


@dataclass(frozen=True)
class Point:
    x: int
    y: int


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


def get_cursor_position() -> Point:
    point = POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(point))
    return Point(point.x, point.y)


def enhance_for_ocr(image: Image.Image) -> Image.Image:
    gray = image.convert("L")
    gray = ImageOps.autocontrast(gray)
    gray = ImageEnhance.Contrast(gray).enhance(2.2)
    gray = ImageEnhance.Sharpness(gray).enhance(1.6)
    scale = 3
    resized = gray.resize((gray.width * scale, gray.height * scale))
    return resized.filter(ImageFilter.SHARPEN)


def prune_screenshots(output_dir: Path, max_count: int = 20) -> None:
    try:
        max_count = max(1, int(max_count))
        images = sorted(
            [path for path in output_dir.glob("*.png") if path.is_file()],
            key=lambda path: (path.stat().st_mtime, path.name),
            reverse=True,
        )
    except Exception:
        return
    for old_path in images[max_count:]:
        try:
            old_path.unlink(missing_ok=True)
        except Exception:
            continue


def prepare_image_for_ocr(source_path: Path, output_dir: Path, prefix: str = "ocr", max_files: int = 20) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    image = Image.open(source_path)
    enhanced = enhance_for_ocr(image)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = output_dir / f"{prefix}-{stamp}.png"
    enhanced.save(path)
    prune_screenshots(output_dir, max_files)
    return path


def capture_around_cursor(
    output_dir: Path,
    width: int,
    height: int,
    prefix: str = "capture",
    max_files: int = 20,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    cursor = get_cursor_position()
    left = max(0, cursor.x - width // 2)
    top = max(0, cursor.y - height // 2)
    bbox = (left, top, left + width, top + height)
    image = ImageGrab.grab(bbox=bbox, all_screens=True)
    enhanced = enhance_for_ocr(image)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = output_dir / f"{prefix}-{stamp}.png"
    enhanced.save(path)
    prune_screenshots(output_dir, max_files)
    return path


def capture_full_screen(output_dir: Path, prefix: str = "screen", max_files: int = 20) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    image = ImageGrab.grab(all_screens=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = output_dir / f"{prefix}-{stamp}.png"
    image.save(path)
    prune_screenshots(output_dir, max_files)
    return path


def crop_image(
    source_path: Path,
    box: tuple[int, int, int, int],
    output_dir: Path,
    prefix: str,
    enhance: bool = True,
    max_files: int = 20,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    image = Image.open(source_path)
    left, top, right, bottom = box
    if right < left:
        left, right = right, left
    if bottom < top:
        top, bottom = bottom, top
    cropped = image.crop((left, top, right, bottom))
    output = enhance_for_ocr(cropped) if enhance else cropped
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = output_dir / f"{prefix}-{stamp}.png"
    output.save(path)
    prune_screenshots(output_dir, max_files)
    return path
