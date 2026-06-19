from __future__ import annotations

import ctypes
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageEnhance, ImageFilter, ImageGrab, ImageOps

try:
    FAST_RESAMPLE = Image.Resampling.BILINEAR
except AttributeError:
    FAST_RESAMPLE = Image.BILINEAR


@dataclass(frozen=True)
class Point:
    x: int
    y: int


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


def get_virtual_screen_bounds() -> tuple[int, int, int, int]:
    try:
        user32 = ctypes.windll.user32
        left = int(user32.GetSystemMetrics(76))
        top = int(user32.GetSystemMetrics(77))
        width = int(user32.GetSystemMetrics(78))
        height = int(user32.GetSystemMetrics(79))
        if width > 0 and height > 0:
            return left, top, left + width, top + height
    except Exception:
        pass
    return 0, 0, 0, 0


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
    resized = gray.resize((gray.width * scale, gray.height * scale), resample=FAST_RESAMPLE)
    return resized.filter(ImageFilter.SHARPEN)


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S-%f")


def _save_png_fast(image: Image.Image, path: Path) -> None:
    image.save(path, optimize=False, compress_level=1)


def _normalize_box(box: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    left, top, right, bottom = box
    if right < left:
        left, right = right, left
    if bottom < top:
        top, bottom = bottom, top
    return left, top, right, bottom


def save_image(
    image: Image.Image,
    output_dir: Path,
    prefix: str,
    max_files: int = 20,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{prefix}-{_stamp()}.png"
    _save_png_fast(image, path)
    prune_screenshots(output_dir, max_files)
    return path


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
    path = output_dir / f"{prefix}-{_stamp()}.png"
    _save_png_fast(enhanced, path)
    prune_screenshots(output_dir, max_files)
    return path


def prepare_image_for_ocr_image(
    image: Image.Image,
    output_dir: Path,
    prefix: str = "ocr",
    max_files: int = 20,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    enhanced = enhance_for_ocr(image)
    path = output_dir / f"{prefix}-{_stamp()}.png"
    _save_png_fast(enhanced, path)
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
    screen_left, screen_top, screen_right, screen_bottom = get_virtual_screen_bounds()
    if screen_right > screen_left and screen_bottom > screen_top:
        max_left = max(screen_left, screen_right - width)
        max_top = max(screen_top, screen_bottom - height)
        left = max(screen_left, min(cursor.x - width // 2, max_left))
        top = max(screen_top, min(cursor.y - height // 2, max_top))
    else:
        left = max(0, cursor.x - width // 2)
        top = max(0, cursor.y - height // 2)
    bbox = (left, top, left + width, top + height)
    image = ImageGrab.grab(bbox=bbox, all_screens=True)
    enhanced = enhance_for_ocr(image)
    path = output_dir / f"{prefix}-{_stamp()}.png"
    _save_png_fast(enhanced, path)
    prune_screenshots(output_dir, max_files)
    return path


def capture_full_screen_image() -> Image.Image:
    return ImageGrab.grab(all_screens=True)


def capture_full_screen(output_dir: Path, prefix: str = "screen", max_files: int = 20) -> Path:
    return save_image(capture_full_screen_image(), output_dir, prefix, max_files)


def crop_image(
    source_path: Path | Image.Image,
    box: tuple[int, int, int, int],
    output_dir: Path,
    prefix: str,
    enhance: bool = True,
    max_files: int = 20,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    left, top, right, bottom = _normalize_box(box)
    if isinstance(source_path, Image.Image):
        cropped = source_path.crop((left, top, right, bottom))
    else:
        with Image.open(source_path) as image:
            cropped = image.crop((left, top, right, bottom))
    output = enhance_for_ocr(cropped) if enhance else cropped
    path = output_dir / f"{prefix}-{_stamp()}.png"
    _save_png_fast(output, path)
    prune_screenshots(output_dir, max_files)
    return path


def crop_and_prepare_for_ocr(
    source: Path | Image.Image,
    box: tuple[int, int, int, int],
    output_dir: Path,
    crop_prefix: str = "selected-area",
    ocr_prefix: str = "selected-area-ocr",
    max_files: int = 20,
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    left, top, right, bottom = _normalize_box(box)
    if isinstance(source, Image.Image):
        cropped = source.crop((left, top, right, bottom))
    else:
        with Image.open(source) as image:
            cropped = image.crop((left, top, right, bottom))

    crop_path = output_dir / f"{crop_prefix}-{_stamp()}.png"
    _save_png_fast(cropped, crop_path)
    enhanced = enhance_for_ocr(cropped)
    ocr_path = output_dir / f"{ocr_prefix}-{_stamp()}.png"
    _save_png_fast(enhanced, ocr_path)
    prune_screenshots(output_dir, max_files)
    return crop_path, ocr_path
