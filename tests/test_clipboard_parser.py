from poe2_price_tracker.clipboard_parser import parse_poe_clipboard_item


def test_parse_rare_item_name_from_game_clipboard_text():
    text = """物品类别: 护甲
稀有度: 稀有
蛇牙 防身甲
小贩外衣
--------
品质: +22% (augmented)
物品等级: 82
"""

    item = parse_poe_clipboard_item(text)

    assert item.item_class == "护甲"
    assert item.rarity == "稀有"
    assert item.item_name == "蛇牙 防身甲"


def test_parse_currency_name_from_game_clipboard_text():
    text = """物品类别: 可堆叠通货
稀有度: 通货
神圣石
--------
堆叠数量: ...
"""

    item = parse_poe_clipboard_item(text)

    assert item.item_class == "可堆叠通货"
    assert item.rarity == "通货"
    assert item.item_name == "神圣石"
