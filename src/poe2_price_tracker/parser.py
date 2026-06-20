# Copyright (c) 2026 大狗狗
# This file is part of this project and is licensed under the GNU GPL-3.0-only.
# See the LICENSE file for details.

from __future__ import annotations

import re
from dataclasses import dataclass


CURRENCY_ALIASES = {
    "ex": "Exalted Orb",
    "exa": "Exalted Orb",
    "exalt": "Exalted Orb",
    "exalted": "Exalted Orb",
    "exalted orb": "Exalted Orb",
    "div": "Divine Orb",
    "divine": "Divine Orb",
    "divine orb": "Divine Orb",
    "chaos": "Chaos Orb",
    "chaos orb": "Chaos Orb",
    "regal": "Regal Orb",
    "regal orb": "Regal Orb",
    "alchemy": "Orb of Alchemy",
    "orb of alchemy": "Orb of Alchemy",
    "transmutation": "Orb of Transmutation",
    "orb of transmutation": "Orb of Transmutation",
    "augmentation": "Orb of Augmentation",
    "orb of augmentation": "Orb of Augmentation",
    "chance": "Orb of Chance",
    "orb of chance": "Orb of Chance",
    "vaal": "Vaal Orb",
    "vaal orb": "Vaal Orb",
    "mirror": "Mirror of Kalandra",
    "mirror of kalandra": "Mirror of Kalandra",
    "崇高": "Exalted Orb",
    "崇高石": "Exalted Orb",
    "神圣": "Divine Orb",
    "神圣石": "Divine Orb",
    "混沌": "Chaos Orb",
    "混沌石": "Chaos Orb",
}

NOISE_PREFIXES = (
    "requires",
    "level",
    "item level",
    "quality",
    "armour",
    "evasion",
    "energy shield",
    "rune sockets",
    "stack size",
    "shift click",
    "right click",
    "price",
    "listed",
    "seller",
    "stash",
)

PRICE_RE = re.compile(
    r"(?:~?price|price|listed for|售价|价格)?\s*[:：]?\s*"
    r"(?P<amount>\d+(?:[.,]\d+)?)\s*"
    r"(?:x\s*)?"
    r"(?P<currency>"
    r"exalted orb|divine orb|chaos orb|regal orb|orb of alchemy|"
    r"orb of transmutation|orb of augmentation|orb of chance|vaal orb|"
    r"mirror of kalandra|exalted|divine|chaos|regal|alchemy|"
    r"transmutation|augmentation|chance|vaal|mirror|exa|ex|div|"
    r"崇高石|崇高|神圣石|神圣|混沌石|混沌"
    r")\b",
    re.IGNORECASE,
)
NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?")


@dataclass(frozen=True)
class ParsedPrice:
    item_name: str
    amount: float | None
    currency: str
    confidence: float
    raw_text: str


@dataclass(frozen=True)
class ParsedItemPrice:
    item_name: str
    amount: float
    currency: str
    raw_text: str
    trend_percent: str = ""
    item_page_url: str = ""
    item_icon_url: str = ""
    currency_page_url: str = ""
    currency_icon_url: str = ""
    item_icon_path: str = ""
    currency_icon_path: str = ""
    item_icon_phash: str = ""
    currency_icon_phash: str = ""
    item_match_score: float = 0.0
    currency_match_score: float = 0.0


def clean_line(line: str) -> str:
    line = line.strip(" \t\r\n|•·")
    line = re.sub(r"\s+", " ", line)
    return line


def meaningful_lines(text: str) -> list[str]:
    lines = [clean_line(line) for line in text.splitlines()]
    lines = [line for line in lines if line]
    filtered = []
    for line in lines:
        lower = line.lower()
        if set(line) <= {"-", "=", "_"}:
            continue
        if any(lower.startswith(prefix) for prefix in NOISE_PREFIXES):
            continue
        filtered.append(line)
    return filtered


def normalize_currency(currency: str) -> str:
    key = " ".join(currency.strip().lower().split())
    return CURRENCY_ALIASES.get(key, currency.strip())


def find_price(text: str) -> tuple[float | None, str, int]:
    match = PRICE_RE.search(text)
    if not match:
        return None, "", -1
    amount = float(match.group("amount").replace(",", "."))
    currency = normalize_currency(match.group("currency"))
    return amount, currency, match.start()


def find_number(text: str) -> float | None:
    match = NUMBER_RE.search(text)
    if not match:
        return None
    return float(match.group(0).replace(",", "."))


def infer_item_name(text: str, price_index: int = -1) -> str:
    lines = meaningful_lines(text)
    if not lines:
        return ""

    if price_index >= 0:
        before = text[:price_index]
        before_lines = meaningful_lines(before)
        for line in reversed(before_lines):
            if not PRICE_RE.search(line):
                return line

    for line in lines:
        if not PRICE_RE.search(line):
            return line
    return lines[0]


def parse_ocr_text(text: str) -> ParsedPrice:
    amount, currency, price_index = find_price(text)
    item_name = infer_item_name(text, price_index)
    confidence = 0.25
    if item_name:
        confidence += 0.35
    if amount is not None and currency:
        confidence += 0.35
    if len(meaningful_lines(text)) >= 2:
        confidence += 0.05
    return ParsedPrice(
        item_name=item_name,
        amount=amount,
        currency=currency,
        confidence=min(confidence, 1.0),
        raw_text=text,
    )


def parse_item_price_rows(text: str, default_currency: str = "Exalted Orb") -> list[ParsedItemPrice]:
    rows: list[ParsedItemPrice] = []
    for line in meaningful_lines(text):
        cleaned = line.replace("Wiki", " ")
        numbers = list(NUMBER_RE.finditer(cleaned))
        if not numbers:
            continue
        price_match = numbers[0]
        item = cleaned[: price_match.start()].strip(" -|:：\t")
        item = re.sub(r"\s+", " ", item)
        if len(item) < 2:
            continue
        rows.append(
            ParsedItemPrice(
                item_name=item,
                amount=float(price_match.group(0).replace(",", ".")),
                currency=default_currency,
                raw_text=line,
            )
        )
    return rows
