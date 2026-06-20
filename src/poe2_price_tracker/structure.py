# Copyright (c) 2026 大狗狗
# This file is part of this project and is licensed under the GNU GPL-3.0-only.
# See the LICENSE file for details.

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from .ocr import OcrBox, OcrResult
from .db import normalize_name
from .parser import ParsedItemPrice, meaningful_lines, normalize_currency

if TYPE_CHECKING:
    from .db import PriceDatabase


NUMBER_RE = re.compile(r"\d+(?:,\d{3})*(?:[.,]\d+)?|\d+(?:[.,]\d+)?")
UI_TEXT_CANDIDATE_BLOCKLIST = {
    "拥有物品",
    "擁有物品",
    "持有物品",
    "物品",
    "价格",
    "價格",
    "搜索",
    "搜尋",
    "查价",
    "查價",
}


def _primary_trade_currency(name: str) -> str:
    normalized = normalize_currency(name).strip().lower()
    raw = name.strip().lower()
    if normalized == "divine orb" or raw in {"神圣石", "divine", "divine orb"}:
        return "神圣石"
    if normalized == "exalted orb" or raw in {"崇高石", "exalted", "exalted orb", "ex"}:
        return "崇高石"
    return ""


@dataclass(frozen=True)
class Rect:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return max(0, self.right - self.left)

    @property
    def height(self) -> int:
        return max(0, self.bottom - self.top)

    @property
    def center_y(self) -> float:
        return (self.top + self.bottom) / 2


@dataclass(frozen=True)
class StructuredRow:
    item_text: str
    amount: float
    currency: str
    raw_text: str
    confidence: float
    row_rect: Rect
    item_rect: Rect | None
    price_rect: Rect | None
    currency_match_score: float = 0.0
    item_match_score: float = 0.0


@dataclass(frozen=True)
class RecognizedItemCandidate:
    item_name: str
    raw_text: str
    confidence: float
    item_match_score: float = 0.0


def _box_rect(box: OcrBox) -> Rect:
    if not box.points:
        return Rect(0, 0, 0, 0)
    xs = [point[0] for point in box.points]
    ys = [point[1] for point in box.points]
    return Rect(int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys)))


def _to_float(text: str) -> float | None:
    match = NUMBER_RE.search(text)
    if not match:
        return None
    value = match.group(0).replace(",", "")
    if value.count(".") == 0:
        value = value.replace("，", "")
    return float(value.replace("，", "").replace(",", ""))


def _clean_item_text(text: str) -> str:
    text = re.sub(r"\bWiki\b", " ", text, flags=re.I)
    text = re.sub(r"^\s*\d+\s*x\s*", " ", text, flags=re.I)
    text = re.sub(r"\bx\s*\d+\b", " ", text, flags=re.I)
    text = re.sub(r"\bLv\s*\d+\+?\b", " ", text, flags=re.I)
    text = re.sub(r"\d+\+?$", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" -|:：")


def _clean_candidate_text(text: str) -> str:
    text = _clean_item_text(text)
    text = re.sub(r"^\s*\d+\s*x\s*", " ", text, flags=re.I)
    text = re.sub(r"\b\d+(?:[.,]\d+)?\b", " ", text)
    text = re.sub(r"[⇆↔→←=+%/\\|]", " ", text)
    text = re.sub(r"\b(?:last|days|volume|traded|wiki|price)\b", " ", text, flags=re.I)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" -|:：")


def _looks_like_item_candidate(text: str) -> bool:
    cleaned = _clean_candidate_text(text)
    if len(cleaned) < 2:
        return False
    if normalize_name(cleaned) in {normalize_name(value) for value in UI_TEXT_CANDIDATE_BLOCKLIST}:
        return False
    if NUMBER_RE.fullmatch(cleaned):
        return False
    if cleaned.lower() in {"wiki", "price", "last days", "volume traded"}:
        return False
    return True


def _read_image(path: Path):
    try:
        import cv2
        import numpy as np

        data = np.fromfile(str(path), dtype=np.uint8)
        return cv2.imdecode(data, cv2.IMREAD_COLOR)
    except Exception:
        return None


def _detect_line_bands(image_path: Path, height: int) -> list[Rect]:
    image = _read_image(image_path)
    if image is None:
        return []
    try:
        import cv2
        import numpy as np

        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 40, 120)
        width = gray.shape[1]
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(40, width // 3), 1))
        horizontal = cv2.morphologyEx(edges, cv2.MORPH_OPEN, kernel)
        scores = horizontal.sum(axis=1)
        threshold = max(float(np.percentile(scores, 95)), float(scores.max()) * 0.35)
        ys = [index for index, score in enumerate(scores) if score >= threshold and score > 0]
        if len(ys) < 2:
            return []
        merged: list[int] = []
        for y in ys:
            if not merged or y - merged[-1] > 4:
                merged.append(int(y))
            else:
                merged[-1] = int((merged[-1] + y) / 2)
        bounds = [0] + [y for y in merged if 6 < y < height - 6] + [height]
        bands = []
        for top, bottom in zip(bounds, bounds[1:]):
            if bottom - top >= 18:
                bands.append(Rect(0, top, width, bottom))
        return bands
    except Exception:
        return []


def _group_boxes_by_rows(image_path: Path, boxes: tuple[OcrBox, ...]) -> list[tuple[Rect, list[OcrBox]]]:
    rects = [(box, _box_rect(box)) for box in boxes if box.text.strip()]
    if not rects:
        return []
    image = _read_image(image_path)
    width = image.shape[1] if image is not None else max(rect.right for _, rect in rects)
    height = image.shape[0] if image is not None else max(rect.bottom for _, rect in rects)
    bands = _detect_line_bands(image_path, height)
    grouped: list[tuple[Rect, list[OcrBox]]] = []
    if bands:
        for band in bands:
            row_boxes = [box for box, rect in rects if band.top <= rect.center_y <= band.bottom]
            if row_boxes:
                grouped.append((band, sorted(row_boxes, key=lambda item: _box_rect(item).left)))
        if grouped:
            return grouped

    ordered = sorted(rects, key=lambda pair: pair[1].center_y)
    heights = sorted(max(8, rect.height) for _, rect in ordered)
    gap = max(20, int(heights[len(heights) // 2] * 1.6))
    current: list[tuple[OcrBox, Rect]] = []
    for box, rect in ordered:
        if current and rect.center_y - sum(r.center_y for _, r in current) / len(current) > gap:
            grouped.append(_row_from_rects(current, width))
            current = []
        current.append((box, rect))
    if current:
        grouped.append(_row_from_rects(current, width))
    return grouped


def _row_from_rects(items: list[tuple[OcrBox, Rect]], width: int) -> tuple[Rect, list[OcrBox]]:
    top = min(rect.top for _, rect in items)
    bottom = max(rect.bottom for _, rect in items)
    boxes = sorted((box for box, _ in items), key=lambda item: _box_rect(item).left)
    return Rect(0, max(0, top - 6), width, bottom + 6), boxes


def _looks_like_price(text: str, rect: Rect, row_width: int) -> bool:
    if "%" in text or re.search(r"\bLv\s*\d+", text, re.I):
        return False
    if _to_float(text) is None:
        return False
    return rect.left >= row_width * 0.42 or len(NUMBER_RE.findall(text)) == 1


def _match_currency_icon(image_path: Path, row_rect: Rect, price_rect: Rect | None, db: "PriceDatabase | None") -> tuple[str, float]:
    if db is None or price_rect is None:
        return "", 0.0
    assets = [
        asset
        for asset in db.get_icon_assets("currency")
        if _primary_trade_currency(asset.name) and asset.local_path and Path(asset.local_path).exists()
    ]
    if not assets:
        return "", 0.0
    image = _read_image(image_path)
    if image is None:
        return "", 0.0
    try:
        import cv2

        height, width = image.shape[:2]
        left = max(price_rect.right - 2, 0)
        right = min(width, price_rect.right + max(44, row_rect.height * 2))
        top = max(0, row_rect.top)
        bottom = min(height, row_rect.bottom)
        roi = image[top:bottom, left:right]
        if roi.size == 0:
            return "", 0.0
        roi_gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        best_name = ""
        best_score = 0.0
        for asset in assets:
            template = _read_image(Path(asset.local_path))
            if template is None:
                continue
            template_gray = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
            for size in (18, 22, 26, 30, 34, 38, 42):
                if roi_gray.shape[0] < size or roi_gray.shape[1] < size:
                    continue
                resized = cv2.resize(template_gray, (size, size), interpolation=cv2.INTER_AREA)
                result = cv2.matchTemplate(roi_gray, resized, cv2.TM_CCOEFF_NORMED)
                _, score, _, _ = cv2.minMaxLoc(result)
                if score > best_score:
                    best_score = float(score)
                    best_name = _primary_trade_currency(asset.name)
        if best_score >= 0.48:
            return best_name, best_score
    except Exception:
        return "", 0.0
    return "", 0.0


def recognize_structured_prices(
    image_path: Path,
    ocr_result: OcrResult,
    db: "PriceDatabase | None" = None,
    default_currency: str = "Exalted Orb",
) -> list[ParsedItemPrice]:
    rows: list[ParsedItemPrice] = []
    for row_rect, row_boxes in _group_boxes_by_rows(image_path, ocr_result.boxes):
        row_width = max(row_rect.width, 1)
        priced: list[tuple[OcrBox, Rect, float]] = []
        for box in row_boxes:
            rect = _box_rect(box)
            amount = _to_float(box.text)
            if amount is not None and _looks_like_price(box.text, rect, row_width):
                priced.append((box, rect, amount))
        if not priced:
            continue
        scored_prices = []
        for candidate_box, candidate_rect, candidate_amount in priced:
            candidate_currency, candidate_icon_score = _match_currency_icon(
                image_path,
                row_rect,
                candidate_rect,
                db,
            )
            scored_prices.append(
                (
                    candidate_icon_score,
                    candidate_rect.left,
                    candidate_box,
                    candidate_rect,
                    candidate_amount,
                    candidate_currency,
                )
            )
        if any(score >= 0.48 for score, *_rest in scored_prices):
            _icon_score, _x, price_box, price_rect, amount, icon_currency = max(
                scored_prices,
                key=lambda item: (item[0], -item[1]),
            )
        else:
            _icon_score, _x, price_box, price_rect, amount, icon_currency = sorted(
                scored_prices,
                key=lambda item: item[1],
            )[-1]
        item_boxes = [
            (box, _box_rect(box))
            for box in row_boxes
            if _box_rect(box).right <= price_rect.left + 4
            and not NUMBER_RE.fullmatch(box.text.strip())
            and "Wiki" not in box.text
        ]
        if not item_boxes:
            item_boxes = [(box, _box_rect(box)) for box in row_boxes if _box_rect(box).left < price_rect.left]
        item_text = _clean_item_text(" ".join(box.text for box, _ in item_boxes))
        if not item_text:
            continue
        matched_item = item_text
        item_score = 0.0
        if db is not None:
            if hasattr(db, "match_item_name_strict"):
                matched_item, item_score = db.match_item_name_strict(item_text)
            else:
                matched_item, item_score = db.match_item_name(item_text, min_score=0.92)
        icon_score = _icon_score
        currency = icon_currency or _primary_trade_currency(default_currency) or "崇高石"
        confidence = min(
            1.0,
            0.35
            + min(price_box.score, 1.0) * 0.25
            + (0.2 if item_score >= 0.92 else 0.08)
            + (0.2 if icon_score >= 0.48 else 0.05),
        )
        raw = " | ".join(box.text for box in row_boxes)
        rows.append(
            ParsedItemPrice(
                item_name=matched_item,
                amount=amount,
                currency=currency,
                raw_text=f"{raw} structure_confidence={confidence:.2f}",
                item_match_score=item_score,
                currency_match_score=icon_score,
            )
        )
    return rows


def recognize_item_candidates(
    image_path: Path,
    ocr_result: OcrResult,
    db: "PriceDatabase | None" = None,
    min_score: float = 0.62,
) -> list[RecognizedItemCandidate]:
    raw_candidates: list[tuple[str, float]] = []

    for row_rect, row_boxes in _group_boxes_by_rows(image_path, ocr_result.boxes):
        row_text = " ".join(box.text for box in row_boxes)
        if _looks_like_item_candidate(row_text):
            score = sum(max(0.0, min(1.0, box.score)) for box in row_boxes) / max(1, len(row_boxes))
            raw_candidates.append((row_text, score))
        for box in row_boxes:
            if _looks_like_item_candidate(box.text):
                raw_candidates.append((box.text, max(0.0, min(1.0, box.score))))

    for line in meaningful_lines(ocr_result.text):
        if _looks_like_item_candidate(line):
            raw_candidates.append((line, 0.72))

    results: list[RecognizedItemCandidate] = []
    seen_raw: set[str] = set()
    seen_items: set[str] = set()
    for raw, ocr_score in raw_candidates:
        cleaned = _clean_candidate_text(raw)
        raw_key = normalize_name(cleaned)
        if not raw_key or raw_key in seen_raw:
            continue
        seen_raw.add(raw_key)
        item_name = cleaned
        match_score = 0.0
        if db is not None:
            if hasattr(db, "match_item_name_strict"):
                item_name, match_score = db.match_item_name_strict(cleaned)
            else:
                item_name, match_score = db.match_item_name(cleaned, min_score=max(min_score, 0.92))
        confidence = min(1.0, 0.25 + ocr_score * 0.25 + match_score * 0.5)
        if db is not None and match_score < 0.92:
            continue
        item_key = normalize_name(item_name)
        if not item_key or item_key in seen_items:
            continue
        seen_items.add(item_key)
        results.append(
            RecognizedItemCandidate(
                item_name=item_name,
                raw_text=raw,
                confidence=confidence,
                item_match_score=match_score,
            )
        )
    return results
