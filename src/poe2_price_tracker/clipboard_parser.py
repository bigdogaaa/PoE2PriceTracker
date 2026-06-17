from __future__ import annotations

from dataclasses import dataclass


SEPARATOR = "--------"
PREFIX_LABELS = ("物品类别:", "稀有度:")


@dataclass(frozen=True)
class ClipboardItem:
    item_name: str
    rarity: str = ""
    item_class: str = ""
    raw_text: str = ""


def _value_after_colon(line: str) -> str:
    for marker in (":", "："):
        if marker in line:
            return line.split(marker, 1)[1].strip()
    return ""


def parse_poe_clipboard_item(text: str) -> ClipboardItem:
    lines = [line.strip() for line in text.replace("\r\n", "\n").split("\n")]
    lines = [line for line in lines if line]
    item_class = ""
    rarity = ""
    rarity_index = -1
    for index, line in enumerate(lines):
        if line.startswith("物品类别"):
            item_class = _value_after_colon(line)
        elif line.startswith("稀有度"):
            rarity = _value_after_colon(line)
            rarity_index = index
            break

    search_from = rarity_index + 1 if rarity_index >= 0 else 0
    for line in lines[search_from:]:
        if line == SEPARATOR:
            break
        if not line or any(line.startswith(label) for label in PREFIX_LABELS):
            continue
        return ClipboardItem(line, rarity=rarity, item_class=item_class, raw_text=text)
    return ClipboardItem("", rarity=rarity, item_class=item_class, raw_text=text)
