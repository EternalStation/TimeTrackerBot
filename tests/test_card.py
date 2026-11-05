import io
from datetime import date

from PIL import Image

from app.card import (collapse_items, fit_px, render_day_receipt, render_week_receipt, wrap_lines,
                      years_of_waste, _font)


def png(data: bytes) -> Image.Image:
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    img = Image.open(io.BytesIO(data))
    img.load()
    assert img.format == "PNG"
    return img


def reds(img) -> int:
    return sum(n for n, p in img.convert("RGB").getcolors(1 << 22)
               if abs(p[0] - 0xE5) < 8 and abs(p[1] - 0x48) < 8 and abs(p[2] - 0x2F) < 8)


def day(**kw):
    base = {"date": date(2026, 11, 5), "day_n": 3, "day_total": 7,
            "items": [{"name": "Work", "minutes": 190, "is_waste": False},
                      {"name": "Social media", "minutes": 125, "is_waste": True},
                      {"name": "Eating", "minutes": 60, "is_waste": False}],
            "tracked": 680, "untracked": 100, "waste": 165, "waste_share": 0.24,
            "limits": [{"name": "Social media", "limit": 60, "used": 125}], "user_id": 3}
    base.update(kw)
    return base


def week(n_cats=8, **kw):
    cats = [{"name": f"Category {i}", "minutes": 900 - i * 50, "is_waste": i % 3 == 1} for i in range(n_cats)]
    days = [{"date": date(2026, 10, 30 + i) if i < 2 else date(2026, 11, i - 1), "waste_minutes": 100 + 20 * i,
             "tracked_minutes": 600} for i in range(7)]
    base = {"start": date(2026, 10, 30), "end": date(2026, 11, 5), "days": days, "top": cats,
            "waste_minutes": 1120, "waste_per_day": 160, "user_id": 3}
    base.update(kw)
    return base


INSIGHTS = ["YouTube / TV was your biggest waste category, about 1h a day.",
            "Most of your waste time lands between 21:00 and 23:00.",
            "Monday was the heaviest day, with 3h 41m on waste."]


def test_day_receipt_png_width_and_height_follow_content():
    img = png(render_day_receipt(day(), "spent_bot"))
    assert img.width == 1080 and img.height > 1000
    more = png(render_day_receipt(day(items=[{"name": f"C{i}", "minutes": 30 + i, "is_waste": False}
                                             for i in range(9)]), "spent_bot"))
    assert more.height > img.height


def test_day_receipt_has_paper_zigzag_and_red_accent():
    img = png(render_day_receipt(day(), "spent_bot")).convert("RGB")
    assert img.getpixel((5, 5)) == (0x1D, 0x1D, 0x1F)                      # charcoal backdrop
    assert img.getpixel((540, 120)) == (0xFB, 0xF9, 0xF4)                  # paper
    assert max(img.getpixel((145, 82))) < 0x30                              # torn corner: backdrop (+shadow) shows
    assert reds(img) > 500


def test_empty_day_and_zero_waste():
    empty = png(render_day_receipt(day(items=[], tracked=0, untracked=0, waste=0, waste_share=0, limits=[]), ""))
    assert empty.width == 1080
    clean_items = [{"name": "Work", "minutes": 300, "is_waste": False}]
    zero = png(render_day_receipt(day(items=clean_items, waste=0, waste_share=0, limits=[]), "spent_bot"))
    assert zero.width == 1080
    assert reds(zero) == 0                                                       # nothing wasted, no red anywhere


def test_day_receipt_long_names_and_many_categories():
    items = [{"name": "A very long custom category name that cannot fit " + str(i), "minutes": 300 - i * 10,
              "is_waste": i % 2 == 0} for i in range(12)]
    img = png(render_day_receipt(day(items=items, limits=[{"name": "X" * 80, "limit": 30, "used": 90}],
                                     date=date(2026, 12, 31), day_n=12), "b" * 40))
    assert img.width == 1080
    lines = collapse_items(items)
    assert len(lines) == 10 and lines[-1]["name"] == "Other"
    assert lines[-1]["minutes"] == sum(i["minutes"] for i in items[9:])
    font = _font(False, 34)
    cut = fit_px(items[0]["name"], font, 300)
    assert cut.endswith("…") and font.getlength(cut) <= 300


def test_emoji_in_names_is_dropped_not_boxed():
    assert fit_px("🎮 Gaming", _font(False, 34), 500) == "Gaming"


def test_years_of_waste():
    assert years_of_waste(165) == 42 and years_of_waste(0) == 0


def test_week_receipt_is_exactly_1080x1920():
    img = png(render_week_receipt(week(), INSIGHTS, "spent_bot"))
    assert img.size == (1080, 1920)


def test_week_receipt_edge_cases_never_overflow():
    long_note = ["word " * 80, "x" * 200, "ok", "fourth ignored"]
    for w, notes in [(week(0, waste_minutes=0, waste_per_day=0, days=[]), []),
                     (week(12), long_note),
                     (week(6, top=[{"name": "N" * 90, "minutes": 100, "is_waste": True}] * 6), long_note),
                     (week(), INSIGHTS * 5),
                     (week(days=[{"date": date(2026, 11, 1), "waste_minutes": 0, "tracked_minutes": 0}] * 7), None)]:
        img = png(render_week_receipt(w, notes, ""))
        assert img.size == (1080, 1920)
        px = img.convert("RGB")
        # top and bottom 40px are plain backdrop: nothing drawn past the paper
        for y in (0, 20, 39, 1880, 1900, 1919):
            assert px.getpixel((540, y)) == (0x1D, 0x1D, 0x1F)


def test_wrap_lines_max_two_lines_with_ellipsis():
    font = _font(False, 34)
    lines = wrap_lines("word " * 60, font, 704, 2, "> ", "  ")
    assert len(lines) == 2 and lines[-1].endswith("…") and lines[0].startswith("> ")
    assert all(font.getlength(x) <= 704 for x in lines)
    assert wrap_lines("short note", font, 704, 2, "> ", "  ") == ["> short note"]
