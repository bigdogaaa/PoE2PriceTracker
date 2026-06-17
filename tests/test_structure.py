import shutil
from pathlib import Path

from PIL import Image, ImageDraw

from poe2_price_tracker.db import IconAsset
from poe2_price_tracker.ocr import OcrBox, OcrResult
from poe2_price_tracker.structure import recognize_structured_prices


class FakeDb:
    def __init__(self, icon_path: Path | None = None):
        self.icon_path = icon_path

    def match_item_name(self, query: str, min_score: float = 0.72):
        values = {
            "卡兰德的魔镜": "卡兰德的魔镜",
            "神圣石": "神圣石",
        }
        return values.get(query, query), 1.0 if query in values else 0.0

    def get_icon_assets(self, kind: str = ""):
        if kind == "currency" and self.icon_path:
            return [IconAsset("神圣石", "currency", "", "", str(self.icon_path), "")]
        return []


def box(text: str, left: int, top: int, right: int, bottom: int, score: float = 0.98) -> OcrBox:
    return OcrBox(
        text=text,
        score=score,
        points=((left, top), (right, top), (right, bottom), (left, bottom)),
    )


def test_recognize_structured_prices_groups_rows_and_matches_items():
    tmp_path = Path(".tmp-structure-test")
    if tmp_path.exists():
        shutil.rmtree(tmp_path, ignore_errors=True)
    tmp_path.mkdir(parents=True, exist_ok=True)
    image_path = tmp_path / "table.png"
    image = Image.new("RGB", (640, 160), "#222222")
    draw = ImageDraw.Draw(image)
    for y in (24, 86):
        draw.rectangle((456, y, 480, y + 24), fill="#f2f2f2")
    image.save(image_path)
    icon_path = tmp_path / "divine.png"
    Image.new("RGB", (24, 24), "#f2f2f2").save(icon_path)
    db = FakeDb(icon_path)
    ocr = OcrResult(
        text="卡兰德的魔镜\n2586\n神圣石\n169",
        engine="rapidocr",
        ok=True,
        boxes=(
            box("卡兰德的魔镜", 44, 20, 210, 48),
            box("2586", 420, 20, 450, 48),
            box("41", 520, 20, 552, 48),
            box("神圣石", 44, 82, 140, 110),
            box("169", 420, 82, 450, 110),
            box("11", 520, 82, 552, 110),
        ),
    )

    rows = recognize_structured_prices(image_path, ocr, db=db, default_currency="Exalted Orb")

    assert [row.item_name for row in rows] == ["卡兰德的魔镜", "神圣石"]
    assert [row.amount for row in rows] == [2586.0, 169.0]
    assert all(row.currency == "神圣石" for row in rows)
    shutil.rmtree(tmp_path, ignore_errors=True)
