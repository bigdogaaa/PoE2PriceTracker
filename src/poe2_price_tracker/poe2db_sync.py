from __future__ import annotations

import re
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from html import unescape
from pathlib import Path
from urllib.parse import urljoin

from .parser import ParsedItemPrice


BASE_URL = "https://poe2db.tw/cn"
ROOT_URL = "https://poe2db.tw"

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


def _fetch_binary(url: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) PoE2PriceTracker/0.3",
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
            "Referer": f"{BASE_URL}/Economy_Currency",
        },
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.read()


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


def _absolute_url(url: str) -> str:
    if not url:
        return ""
    if url.startswith("//"):
        return "https:" + url
    return urljoin(ROOT_URL, url)


def _extract_images(cell: str) -> list[str]:
    values = []
    for match in re.finditer(r'<img\b[^>]*\bsrc="([^"]+)"', cell, flags=re.I):
        values.append(_absolute_url(unescape(match.group(1))))
    return values


def _extract_economy_hrefs(cell: str) -> list[str]:
    hrefs = []
    for match in re.finditer(r'href="([^"]*Economy_[^"]+)"', cell, flags=re.I):
        hrefs.append(_absolute_url(unescape(match.group(1))))
    return hrefs


def _safe_asset_name(name: str) -> str:
    value = re.sub(r"[^\w\u4e00-\u9fff.-]+", "_", name, flags=re.U).strip("_")
    return value[:80] or "asset"


def _image_phash(path: Path) -> str:
    try:
        import cv2
        import numpy as np

        data = np.fromfile(str(path), dtype=np.uint8)
        image = cv2.imdecode(data, cv2.IMREAD_GRAYSCALE)
        if image is None:
            return ""
        resized = cv2.resize(image, (32, 32), interpolation=cv2.INTER_AREA)
        dct = cv2.dct(np.float32(resized))
        low = dct[:8, :8]
        median = np.median(low[1:, 1:])
        bits = (low > median).flatten()
        value = 0
        for bit in bits:
            value = (value << 1) | int(bool(bit))
        return f"{value:016x}"
    except Exception:
        return ""


def _download_icon(icon_url: str, icon_dir: Path | None, name: str, kind: str, force: bool = False) -> tuple[str, str]:
    if not icon_url or icon_dir is None:
        return "", ""
    icon_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(icon_url.split("?", 1)[0]).suffix
    if not suffix or len(suffix) > 8:
        suffix = ".png"
    target = icon_dir / kind / f"{_safe_asset_name(name)}{suffix}"
    target.parent.mkdir(parents=True, exist_ok=True)
    if force or not target.exists() or target.stat().st_size == 0:
        target.write_bytes(_fetch_binary(icon_url))
    return str(target), _image_phash(target)


def _currency_from_href(href: str) -> str:
    if "Economy_divine" in href:
        return "神圣石"
    if "Economy_exalted" in href:
        return "崇高石"
    if "Economy_chaos" in href:
        return "混沌石"
    name = href.rsplit("/", 1)[-1].replace("Economy_", "")
    return unescape(name.replace("_", " "))


def _parse_value_cell(cell: str) -> tuple[float, str, str, str] | None:
    numbers = re.findall(r"\d+(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?", _strip_tags(cell))
    hrefs = _extract_economy_hrefs(cell)
    images = _extract_images(cell)
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
    return left_amount / right_amount, _currency_from_href(hrefs[0]), hrefs[0], images[0] if images else ""


def _parse_trend_cell(cell: str) -> str:
    text = _strip_tags(cell)
    match = re.search(r"[+-]\d+(?:\.\d+)?%", text)
    return match.group(0) if match else ""


def parse_economy_html(html: str, category: str, url: str, icon_dir: Path | None = None) -> Poe2dbSyncResult:
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
        amount, currency, currency_page_url, currency_icon_url = parsed_value
        trend = _parse_trend_cell(cells[2]) if len(cells) > 2 else ""
        item_hrefs = _extract_economy_hrefs(cells[0])
        item_images = _extract_images(cells[0])
        value_images = _extract_images(cells[1])
        item_page_url = item_hrefs[0] if item_hrefs else ""
        item_icon_url = item_images[0] if item_images else (value_images[1] if len(value_images) > 1 else "")
        currency_icon_path, currency_phash = _download_icon(currency_icon_url, icon_dir, currency, "currency")
        item_icon_path, item_phash = _download_icon(item_icon_url, icon_dir, name, "item")
        rows.append(
            ParsedItemPrice(
                item_name=name,
                amount=amount,
                currency=currency,
                raw_text=f"[{category}] {name} {amount:g} {currency} trend={trend}",
                trend_percent=trend,
                item_page_url=item_page_url,
                item_icon_url=item_icon_url,
                currency_page_url=currency_page_url,
                currency_icon_url=currency_icon_url,
                item_icon_path=item_icon_path,
                currency_icon_path=currency_icon_path,
                item_icon_phash=item_phash,
                currency_icon_phash=currency_phash,
                item_match_score=1.0 if item_phash else 0.0,
                currency_match_score=1.0 if currency_phash else 0.0,
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


def fetch_category_prices(category: str, slug: str, icon_dir: Path | None = None) -> Poe2dbSyncResult:
    url = f"{BASE_URL}/{slug}"
    return parse_economy_html(_fetch_html(url), category, url, icon_dir=icon_dir)


def fetch_all_economy_prices(
    progress: Callable[[int, int, str, str], None] | None = None,
    icon_dir: Path | None = None,
) -> Poe2dbSyncBatch:
    results = []
    errors = []
    total = len(ECONOMY_CATEGORIES)
    for index, (category, slug) in enumerate(ECONOMY_CATEGORIES, start=1):
        url = f"{BASE_URL}/{slug}"
        if progress:
            progress(index, total, category, url)
        try:
            result = fetch_category_prices(category, slug, icon_dir=icon_dir)
        except Exception as exc:
            errors.append(f"{category}: {exc}")
            continue
        if result.rows:
            results.append(result)
        else:
            errors.append(f"{category}: 未解析到数据")
    return Poe2dbSyncBatch(results, errors)


def fetch_currency_prices(url: str = f"{BASE_URL}/Economy_Currency", icon_dir: Path | None = None) -> Poe2dbSyncResult:
    return parse_economy_html(_fetch_html(url), "通货", url, icon_dir=icon_dir)
