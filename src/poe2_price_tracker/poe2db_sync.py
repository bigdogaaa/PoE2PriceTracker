from __future__ import annotations

import re
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from html import unescape

from .parser import ParsedItemPrice


BASE_URL = "https://poe2db.tw/cn"

ECONOMY_CATEGORIES = [
    ("通货", "Economy_Currency"),
    ("碎片", "Economy_Fragments"),
    ("驱灵仪式", "Economy_Ritual"),
    ("精华", "Economy_Essences"),
    ("裂隙", "Economy_Breach"),
    ("惊悸迷雾", "Economy_Delirium"),
    ("先祖秘藏", "Economy_Expedition"),
    ("符文", "Economy_Runes"),
    ("灵核", "Economy_Soul_Cores"),
    ("雕像", "Economy_Idols"),
    ("未切割的宝石", "Economy_Uncut_Gems"),
    ("深渊", "Economy_Abyss"),
    ("宝石", "Economy_Gems"),
    ("阿兹里神庙", "Economy_Atziris_Temple"),
]


@dataclass(frozen=True)
class Poe2dbSyncResult:
    rows: list[ParsedItemPrice]
    source_url: str
    category: str


@dataclass(frozen=True)
class Poe2dbSyncBatch:
    results: list[Poe2dbSyncResult]
    errors: list[str]


def _fetch_html(url: str) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) PoE2PriceTracker/0.1",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
        },
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.read().decode("utf-8", errors="replace")


def _strip_tags(value: str) -> str:
    value = re.sub(r"<script.*?</script>", " ", value, flags=re.S | re.I)
    value = re.sub(r"<style.*?</style>", " ", value, flags=re.S | re.I)
    value = re.sub(r"<[^>]+>", " ", value)
    return " ".join(unescape(value).split())


def _to_float(value: str) -> float | None:
    value = value.replace(",", "").strip()
    if not re.fullmatch(r"\d+(?:\.\d+)?", value):
        return None
    return float(value)


def _currency_from_href(href: str) -> str:
    if "Economy_divine" in href:
        return "神圣石"
    if "Economy_exalted" in href:
        return "崇高石"
    return href.replace("Economy_", "")


def _parse_value_cell(cell: str) -> tuple[float, str] | None:
    numbers = re.findall(r"\d+(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?", _strip_tags(cell))
    hrefs = re.findall(r'href="([^"]*Economy_[^"]+)"', cell)
    if not numbers or not hrefs:
        return None
    left_amount = _to_float(numbers[0])
    if left_amount is None:
        return None
    right_amount = 1.0
    if len(numbers) >= 2:
        parsed_right = _to_float(numbers[1])
        if parsed_right and parsed_right > 0:
            right_amount = parsed_right
    return left_amount / right_amount, _currency_from_href(hrefs[0])


def _parse_trend_cell(cell: str) -> str:
    text = _strip_tags(cell)
    match = re.search(r"[+-]\d+(?:\.\d+)?%", text)
    return match.group(0) if match else ""


def parse_economy_html(html: str, category: str, url: str) -> Poe2dbSyncResult:
    rows: list[ParsedItemPrice] = []
    for tr in re.findall(r"<tr\b.*?</tr>", html, flags=re.S | re.I):
        cells = re.findall(r"<t[dh]\b.*?</t[dh]>", tr, flags=re.S | re.I)
        if len(cells) < 2:
            continue
        name = _strip_tags(cells[0]).replace("Wiki", "").strip()
        if not name or name in {"名称", "Name"}:
            continue
        parsed_value = _parse_value_cell(cells[1])
        if parsed_value is None:
            continue
        amount, currency = parsed_value
        trend = _parse_trend_cell(cells[2]) if len(cells) > 2 else ""
        rows.append(
            ParsedItemPrice(
                item_name=name,
                amount=amount,
                currency=currency,
                raw_text=f"[{category}] {name} {amount:g} {currency} trend={trend}",
                trend_percent=trend,
            )
        )

    if rows:
        return Poe2dbSyncResult(rows, url, category)

    # Fallback for compact/static renderings: item link + Wiki + numeric value.
    text = _strip_tags(html)
    pattern = re.compile(
        r"(?P<name>[\u4e00-\u9fffA-Za-z0-9（）()：:·' -]{2,80})\s+Wiki\s+"
        r"(?P<value>\d+(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)"
    )
    seen = set()
    for match in pattern.finditer(text):
        name = " ".join(match.group("name").split()).strip()
        amount = _to_float(match.group("value"))
        if amount is None or name in seen or "Economy" in name:
            continue
        seen.add(name)
        rows.append(
            ParsedItemPrice(
                item_name=name,
                amount=amount,
                currency="崇高石",
                raw_text=f"[{category}] {name} {amount:g}",
            )
        )
    return Poe2dbSyncResult(rows, url, category)


def fetch_category_prices(category: str, slug: str) -> Poe2dbSyncResult:
    url = f"{BASE_URL}/{slug}"
    return parse_economy_html(_fetch_html(url), category, url)


def fetch_all_economy_prices(progress: Callable[[int, int, str, str], None] | None = None) -> Poe2dbSyncBatch:
    results = []
    errors = []
    total = len(ECONOMY_CATEGORIES)
    for index, (category, slug) in enumerate(ECONOMY_CATEGORIES, start=1):
        url = f"{BASE_URL}/{slug}"
        if progress:
            progress(index, total, category, url)
        try:
            result = fetch_category_prices(category, slug)
        except Exception as exc:
            errors.append(f"{category}: {exc}")
            continue
        if result.rows:
            results.append(result)
        else:
            errors.append(f"{category}: 未解析到数据")
    return Poe2dbSyncBatch(results, errors)


def fetch_currency_prices(url: str = f"{BASE_URL}/Economy_Currency") -> Poe2dbSyncResult:
    return parse_economy_html(_fetch_html(url), "通货", url)
