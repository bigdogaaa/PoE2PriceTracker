# Copyright (c) 2026 大狗狗
# This file is part of this project and is licensed under the GNU GPL-3.0-only.
# See the LICENSE file for details.

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from .currencies import BASE_CURRENCIES
from .db import normalize_name
from .ocr import OcrBox, OcrResult


@dataclass(frozen=True)
class ParsedMarketExchange:
    want_item: str = ""
    have_item: str = ""
    market_want_amount: float = 0.0
    market_have_amount: float = 0.0
    user_want_amount: float = 0.0
    user_have_amount: float = 0.0
    want_item_match: str = ""
    have_item_match: str = ""
    want_item_known: bool = False
    have_item_known: bool = False
    want_item_is_currency: bool = False
    have_item_is_currency: bool = False
    confidence: float = 0.0
    raw_text: str = ""
    message: str = ""


@dataclass(frozen=True)
class ParsedRealtimePrice:
    item_name: str = ""
    item_match: str = ""
    item_known: bool = False
    side: str = ""
    amount: float = 0.0
    currency: str = ""
    currency_side: str = ""
    item_side: str = ""
    confidence: float = 0.0
    message: str = ""


PRIMARY_TRADE_CURRENCIES = {"神圣石", "崇高石", "混沌石"}
PRIMARY_TRADE_CURRENCY_PRIORITY = ("神圣石", "混沌石", "崇高石")
_RATIO_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*[:：]\s*(\d+(?:[.,]\d+)?)")
_NUMBER_RE = re.compile(r"^\d+(?:[.,]\d+)?$")
_FRACTION_RE = re.compile(r"^\d+\s*/\s*\d+$")
_NOISE_WORDS = {
    "需求物品",
    "拥有物品",
    "市场比例",
    "通货兑换",
    "通货兄换",
    "下达订单",
    "列出的订单",
    "我的摊位",
    "购买",
}


def _to_float(value: str) -> float:
    try:
        return float(value.replace(",", "."))
    except ValueError:
        return 0.0


def _box_rect(box: OcrBox) -> tuple[float, float, float, float]:
    if not box.points:
        return (0.0, 0.0, 0.0, 0.0)
    xs = [point[0] for point in box.points]
    ys = [point[1] for point in box.points]
    return min(xs), min(ys), max(xs), max(ys)


def _center(box: OcrBox) -> tuple[float, float]:
    left, top, right, bottom = _box_rect(box)
    return (left + right) / 2, (top + bottom) / 2


def _box_height(box: OcrBox) -> float:
    _left, top, _right, bottom = _box_rect(box)
    return max(1.0, bottom - top)


def _horizontal_overlap_ratio(left_box: OcrBox, right_box: OcrBox) -> float:
    left_a, _top_a, right_a, _bottom_a = _box_rect(left_box)
    left_b, _top_b, right_b, _bottom_b = _box_rect(right_box)
    overlap = max(0.0, min(right_a, right_b) - max(left_a, left_b))
    width = max(1.0, min(right_a - left_a, right_b - left_b))
    return overlap / width


def _contains_cjk(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


def _join_item_name_parts(parts: list[str]) -> str:
    output = ""
    for part in [item.strip() for item in parts if item.strip()]:
        if not output:
            output = part
            continue
        if _contains_cjk(output) or _contains_cjk(part):
            output += part
        else:
            output += " " + part
    return output.strip()


def _merge_item_name_lines(primary: OcrBox, candidates: list[OcrBox]) -> str:
    parts = [primary.text.strip()]
    current = primary
    for candidate in sorted(candidates, key=lambda item: (_box_rect(item)[1], _box_rect(item)[0])):
        if candidate is primary:
            continue
        left, top, right, bottom = _box_rect(candidate)
        current_left, _current_top, current_right, current_bottom = _box_rect(current)
        if top < current_bottom - _box_height(current) * 0.35:
            continue
        vertical_gap = top - current_bottom
        max_gap = max(12.0, min(32.0, _box_height(current) * 1.1))
        if vertical_gap > max_gap:
            if top > current_bottom + max_gap:
                break
            continue
        if _horizontal_overlap_ratio(current, candidate) < 0.35:
            center_x, _center_y = _center(candidate)
            if center_x < current_left - 8 or center_x > current_right + 8:
                continue
        parts.append(candidate.text.strip())
        current = OcrBox(
            text=candidate.text,
            score=candidate.score,
            points=(
                (min(current_left, left), min(_box_rect(current)[1], top)),
                (max(current_right, right), min(_box_rect(current)[1], top)),
                (max(current_right, right), max(current_bottom, bottom)),
                (min(current_left, left), max(current_bottom, bottom)),
            ),
        )
        if len(parts) >= 3:
            break
    return _join_item_name_parts(parts)


def _is_ratio(text: str) -> bool:
    return bool(_RATIO_RE.search(text.replace(" ", "")))


def _parse_ratio(text: str) -> tuple[float, float]:
    match = _RATIO_RE.search(text.replace(" ", ""))
    if not match:
        return 0.0, 0.0
    return _to_float(match.group(1)), _to_float(match.group(2))


def _looks_like_item_name(text: str) -> bool:
    text = text.strip()
    if not text or text in _NOISE_WORDS:
        return False
    if _is_ratio(text) or _NUMBER_RE.match(text) or _FRACTION_RE.match(text):
        return False
    if len(text) <= 1:
        return False
    return any("\u4e00" <= ch <= "\u9fff" for ch in text) or any(ch.isalpha() for ch in text)


def _image_size(image_path: Path) -> tuple[int, int]:
    try:
        with Image.open(image_path) as image:
            return image.width, image.height
    except Exception:
        return 1, 1


def _label_box(boxes: list[OcrBox], label: str) -> OcrBox | None:
    for box in boxes:
        if label in box.text:
            return box
    return None


def _pick_item_near_label(boxes: list[OcrBox], label: str, width: int, side: str) -> str:
    anchor = _label_box(boxes, label)
    if anchor is None:
        return ""
    anchor_x, anchor_y = _center(anchor)
    candidates: list[tuple[float, float, OcrBox]] = []
    for box in boxes:
        if box is anchor:
            continue
        text = box.text.strip()
        if not _looks_like_item_name(text):
            continue
        x, y = _center(box)
        if side == "left" and x > width * 0.55:
            continue
        if side == "right" and x < width * 0.45:
            continue
        if y < anchor_y:
            continue
        distance = abs(x - anchor_x) * 0.35 + abs(y - anchor_y)
        candidates.append((distance, -box.score, box))
    candidates.sort()
    if not candidates:
        return ""
    primary = candidates[0][2]
    return _merge_item_name_lines(primary, [item[2] for item in candidates])


def _pick_item_by_region(boxes: list[OcrBox], side: str, width: int, height: int) -> str:
    if side == "left":
        candidates = [box for box in boxes if _center(box)[0] < width * 0.48 and _looks_like_item_name(box.text)]
        candidates.sort(key=lambda box: (_center(box)[1] > height * 0.72, _center(box)[0], -box.score))
    else:
        candidates = [box for box in boxes if _center(box)[0] > width * 0.52 and _looks_like_item_name(box.text)]
        candidates.sort(key=lambda box: (_center(box)[1] > height * 0.72, -_center(box)[0], -box.score))
    return _merge_item_name_lines(candidates[0], candidates) if candidates else ""


def _pick_item_name(boxes: list[OcrBox], side: str, width: int, height: int) -> str:
    if side == "left":
        return _pick_item_near_label(boxes, "需求物品", width, side) or _pick_item_by_region(boxes, side, width, height)
    return _pick_item_near_label(boxes, "拥有物品", width, side) or _pick_item_by_region(boxes, side, width, height)


def _pick_ratios(boxes: list[OcrBox]) -> tuple[tuple[float, float], tuple[float, float]]:
    ratio_boxes = [box for box in boxes if _is_ratio(box.text)]
    ratio_boxes.sort(key=lambda box: (_center(box)[1], _center(box)[0]))
    ratios = [_parse_ratio(box.text) for box in ratio_boxes]
    ratios = [ratio for ratio in ratios if ratio[0] > 0 and ratio[1] > 0]
    if not ratios:
        return (0.0, 0.0), (0.0, 0.0)
    if len(ratios) == 1:
        return ratios[0], ratios[0]
    return ratios[0], ratios[-1]


def _currency_names(db: Any | None = None) -> set[str]:
    names = set(BASE_CURRENCIES)
    names.update(
        {
            "崇高石",
            "神圣石",
            "混沌石",
            "富豪石",
            "点金石",
            "机会石",
            "瓦尔宝珠",
            "卡兰德的魔镜",
            "剥离石",
            "玻璃弹珠",
            "宝石匠的棱镜",
        }
    )
    if db is not None:
        try:
            names.update(asset.name for asset in db.get_icon_assets("currency") if asset.name)
        except Exception:
            pass
    return names


def _match_currency_name(name: str, db: Any | None = None) -> tuple[str, bool]:
    normalized = normalize_name(name)
    if not normalized:
        return "", False
    for currency in _currency_names(db):
        if normalize_name(currency) == normalized:
            return currency, True
    return name.strip(), False


def _is_primary_trade_currency(name: str, db: Any | None = None) -> bool:
    matched, is_currency = _match_currency_name(name, db)
    return is_currency and matched in PRIMARY_TRADE_CURRENCIES


def _match_known_item_name(name: str, db: Any | None = None) -> tuple[str, bool, bool]:
    currency_name, is_currency = _match_currency_name(name, db)
    if is_currency:
        return currency_name, True, True
    if db is None or not name.strip():
        return name.strip(), False, False
    try:
        matched, score = db.match_item_name_strict(name)
        if score >= 0.94 and normalize_name(matched) != normalize_name(name):
            return matched, True, False
        if score >= 0.94:
            return matched, True, False
    except Exception:
        pass
    try:
        matched, score = db.match_item_name(name, min_score=0.86)
        if score >= 0.86:
            matched_currency, matched_is_currency = _match_currency_name(matched, db)
            return matched_currency if matched_is_currency else matched, True, matched_is_currency
    except Exception:
        pass
    return name.strip(), False, False


def derive_realtime_price(parsed: ParsedMarketExchange, db: Any | None = None) -> ParsedRealtimePrice:
    want_name = parsed.want_item_match or parsed.want_item
    have_name = parsed.have_item_match or parsed.have_item
    want_is_primary = _is_primary_trade_currency(want_name, db)
    have_is_primary = _is_primary_trade_currency(have_name, db)
    want_is_currency = parsed.want_item_is_currency or _match_currency_name(want_name, db)[1]
    have_is_currency = parsed.have_item_is_currency or _match_currency_name(have_name, db)[1]

    if parsed.market_want_amount <= 0 or parsed.market_have_amount <= 0:
        return ParsedRealtimePrice(confidence=parsed.confidence, message="缺少市场比例")

    if want_is_primary and have_is_primary:
        want_currency = _match_currency_name(want_name, db)[0]
        have_currency = _match_currency_name(have_name, db)[0]
        preferred_item = next(
            (currency for currency in PRIMARY_TRADE_CURRENCY_PRIORITY if currency in {want_currency, have_currency}),
            want_currency,
        )
        if preferred_item == want_currency:
            amount = parsed.market_have_amount / parsed.market_want_amount
            return ParsedRealtimePrice(
                item_name=want_name,
                item_match=parsed.want_item_match,
                item_known=parsed.want_item_known,
                side="买入",
                amount=amount,
                currency=have_currency,
                currency_side="右侧",
                item_side="左侧",
                confidence=parsed.confidence,
                message="基础通货兑换",
            )
        amount = parsed.market_want_amount / parsed.market_have_amount
        return ParsedRealtimePrice(
            item_name=have_name,
            item_match=parsed.have_item_match,
            item_known=parsed.have_item_known,
            side="卖出",
            amount=amount,
            currency=want_currency,
            currency_side="左侧",
            item_side="右侧",
            confidence=parsed.confidence,
            message="基础通货兑换",
        )

    if have_is_primary and not want_is_primary:
        item_name = want_name
        item_match = parsed.want_item_match
        item_known = parsed.want_item_known
        amount = parsed.market_have_amount / parsed.market_want_amount
        currency = _match_currency_name(have_name, db)[0]
        return ParsedRealtimePrice(
            item_name=item_name,
            item_match=item_match,
            item_known=item_known,
            side="买入",
            amount=amount,
            currency=currency,
            currency_side="右侧",
            item_side="左侧",
            confidence=parsed.confidence,
        )

    if want_is_primary and not have_is_primary:
        item_name = have_name
        item_match = parsed.have_item_match
        item_known = parsed.have_item_known
        amount = parsed.market_want_amount / parsed.market_have_amount
        currency = _match_currency_name(want_name, db)[0]
        return ParsedRealtimePrice(
            item_name=item_name,
            item_match=item_match,
            item_known=item_known,
            side="卖出",
            amount=amount,
            currency=currency,
            currency_side="左侧",
            item_side="右侧",
            confidence=parsed.confidence,
        )

    if have_is_currency and not want_is_currency:
        item_name = want_name
        amount = parsed.market_have_amount / parsed.market_want_amount
        currency = _match_currency_name(have_name, db)[0]
        return ParsedRealtimePrice(
            item_name=item_name,
            item_match=parsed.want_item_match,
            item_known=parsed.want_item_known,
            side="买入",
            amount=amount,
            currency=currency,
            currency_side="右侧",
            item_side="左侧",
            confidence=max(0.0, parsed.confidence - 0.08),
            message="使用非核心通货作为价格单位",
        )

    if want_is_currency and not have_is_currency:
        item_name = have_name
        amount = parsed.market_want_amount / parsed.market_have_amount
        currency = _match_currency_name(want_name, db)[0]
        return ParsedRealtimePrice(
            item_name=item_name,
            item_match=parsed.have_item_match,
            item_known=parsed.have_item_known,
            side="卖出",
            amount=amount,
            currency=currency,
            currency_side="左侧",
            item_side="右侧",
            confidence=max(0.0, parsed.confidence - 0.08),
            message="使用非核心通货作为价格单位",
        )

    return ParsedRealtimePrice(
        confidence=parsed.confidence,
        message="没有识别到清晰的物品与通货关系",
    )


def parse_market_exchange(image_path: Path, result: OcrResult, db: Any | None = None) -> ParsedMarketExchange:
    width, height = _image_size(image_path)
    boxes = list(result.boxes)
    raw_text = result.text.strip()
    want_item = _pick_item_name(boxes, "left", width, height)
    have_item = _pick_item_name(boxes, "right", width, height)
    market_ratio, user_ratio = _pick_ratios(boxes)
    want_match, want_known, want_is_currency = _match_known_item_name(want_item, db)
    have_match, have_known, have_is_currency = _match_known_item_name(have_item, db)

    score_parts = []
    if want_item:
        score_parts.append(0.25)
    if have_item:
        score_parts.append(0.25)
    if market_ratio[0] > 0 and market_ratio[1] > 0:
        score_parts.append(0.25)
    if user_ratio[0] > 0 and user_ratio[1] > 0:
        score_parts.append(0.20)
    if boxes:
        score_parts.append(min(0.05, sum(max(0.0, min(1.0, box.score)) for box in boxes) / len(boxes) * 0.05))
    confidence = min(1.0, sum(score_parts))

    missing = []
    if not want_item:
        missing.append("需求物品")
    if not have_item:
        missing.append("拥有物品")
    if market_ratio[0] <= 0 or market_ratio[1] <= 0:
        missing.append("市场比例")
    if user_ratio[0] <= 0 or user_ratio[1] <= 0:
        missing.append("操作比例")
    if want_item and have_item and not (want_is_currency or have_is_currency):
        missing.append("至少一边需要是通货")
    message = "请修订：" + "、".join(missing) if missing else ""

    return ParsedMarketExchange(
        want_item=want_item,
        have_item=have_item,
        market_want_amount=market_ratio[0],
        market_have_amount=market_ratio[1],
        user_want_amount=user_ratio[0],
        user_have_amount=user_ratio[1],
        want_item_match=want_match if want_known else "",
        have_item_match=have_match if have_known else "",
        want_item_known=want_known,
        have_item_known=have_known,
        want_item_is_currency=want_is_currency,
        have_item_is_currency=have_is_currency,
        confidence=confidence,
        raw_text=raw_text,
        message=message or result.message,
    )
