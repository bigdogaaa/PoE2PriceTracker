from poe2_price_tracker.parser import parse_ocr_text


def test_parse_price_with_previous_item_line():
    text = """
    Perfect Jeweller's Orb
    Stack Size: 1/20
    Price: 2 Divine Orb
    """
    parsed = parse_ocr_text(text)
    assert parsed.item_name == "Perfect Jeweller's Orb"
    assert parsed.amount == 2
    assert parsed.currency == "Divine Orb"


def test_parse_stash_price_syntax():
    text = """
    Orb of Alchemy
    --------
    ~price 5 ex
    """
    parsed = parse_ocr_text(text)
    assert parsed.item_name == "Orb of Alchemy"
    assert parsed.amount == 5
    assert parsed.currency == "Exalted Orb"


def test_parse_chinese_currency_alias():
    text = """
    Some Unique Item
    售价: 1 神圣石
    """
    parsed = parse_ocr_text(text)
    assert parsed.item_name == "Some Unique Item"
    assert parsed.amount == 1
    assert parsed.currency == "Divine Orb"
