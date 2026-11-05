import io

from PIL import Image

from app.card import render_week_card

STATS = {"days": 7, "waste_minutes": 1120, "waste_per_day": 160, "top": [
    {"name": "Work", "minutes": 1800, "is_waste": False, "color": "#4C7DF0"},
    {"name": "Social media", "minutes": 700, "is_waste": True, "color": "#F0564A"},
    {"name": "YouTube / TV", "minutes": 300, "is_waste": True, "color": "#F28C38"},
    {"name": "Eating", "minutes": 250, "is_waste": False, "color": "#5FA35A"},
    {"name": "Chores & cooking", "minutes": 120, "is_waste": False, "color": "#3A9BDC"}]}


def test_card_is_valid_png_1080x1350():
    data = render_week_card(STATS, "my_time_bot")
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    img = Image.open(io.BytesIO(data))
    img.load()
    assert img.format == "PNG" and img.size == (1080, 1350)


def test_card_handles_empty_and_long_names():
    empty = render_week_card({"days": 7, "waste_minutes": 0, "waste_per_day": 0, "top": []}, "")
    assert Image.open(io.BytesIO(empty)).size == (1080, 1350)
    long = dict(STATS, waste_minutes=99999, top=[dict(STATS["top"][1], name="A very long custom category")])
    assert Image.open(io.BytesIO(render_week_card(long, "bot"))).size == (1080, 1350)
