"""Shareable weekly card: 1080x1350 PNG made with Pillow (no emoji, Inter font)."""
from __future__ import annotations

import io

from PIL import Image, ImageDraw, ImageFont

from .config import ASSETS_DIR
from .timeutil import fmt_dur

W, H = 1080, 1350
PAD = 80
BG = "#F6F7F9"
INK = "#14181F"
MUTED = "#6B7280"
WASTE_RED = "#E5483D"
TRACK = "#E6E9EE"


def _font(bold: bool, size: int) -> ImageFont.FreeTypeFont:
    name = "Inter-Bold.otf" if bold else "Inter-Regular.otf"
    try:
        return ImageFont.truetype(str(ASSETS_DIR / "fonts" / name), size)
    except OSError:
        return ImageFont.load_default(size)


def _fit(draw, text: str, bold: bool, size: int, max_w: int) -> ImageFont.FreeTypeFont:
    while size > 14 and draw.textlength(text, font=_font(bold, size)) > max_w:
        size -= 2
    return _font(bold, size)


def _spaced(draw, xy, text, font, fill, spacing):
    x, y = xy
    for ch in text:
        draw.text((x, y), ch, font=font, fill=fill)
        x += draw.textlength(ch, font=font) + spacing


def _hex(color: str | None, default: str) -> str:
    if color and len(color) == 7 and color.startswith("#"):
        return color
    return default


def render_week_card(stats: dict, bot_username: str) -> bytes:
    """stats: waste_minutes, waste_per_day, days, top=[{name, minutes, is_waste, color}]."""
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    inner = W - 2 * PAD

    _spaced(d, (PAD, 90), f"MY {stats.get('days', 7)}-DAY TIME AUDIT", _font(True, 30), MUTED, 4)

    big = fmt_dur(stats["waste_minutes"])
    d.text((PAD, 150), big, font=_fit(d, big, True, 200, inner), fill=WASTE_RED)
    line1 = "of my awake time went to things I call waste"
    d.text((PAD, 400), line1, font=_fit(d, line1, False, 40, inner), fill=INK)
    line2 = f"that's {fmt_dur(stats['waste_per_day'])} a day"
    d.text((PAD, 470), line2, font=_fit(d, line2, True, 48, inner), fill=INK)

    d.line((PAD, 590, W - PAD, 590), fill=TRACK, width=3)

    top = stats.get("top", [])[:5]
    y = 640
    if not top:
        d.text((PAD, y), "No time logged yet", font=_font(False, 36), fill=MUTED)
    biggest = max([t["minutes"] for t in top], default=1) or 1
    name_font, time_font, tag_font = _font(True, 36), _font(True, 36), _font(True, 20)
    for t in top:
        color = _hex(t.get("color"), WASTE_RED if t.get("is_waste") else "#4C7DF0")
        d.text((PAD, y), t["name"], font=name_font, fill=INK)
        if t.get("is_waste"):
            x = PAD + d.textlength(t["name"], font=name_font) + 18
            d.rounded_rectangle((x, y + 6, x + 100, y + 40), radius=8, fill=WASTE_RED)
            d.text((x + 50, y + 23), "WASTE", font=tag_font, fill="white", anchor="mm")
        label = fmt_dur(t["minutes"])
        d.text((W - PAD, y), label, font=time_font, fill=INK, anchor="ra")
        by = y + 58
        d.rounded_rectangle((PAD, by, W - PAD, by + 26), radius=13, fill=TRACK)
        fill_w = max(26, int(inner * t["minutes"] / biggest))
        d.rounded_rectangle((PAD, by, PAD + fill_w, by + 26), radius=13, fill=color)
        y += 124

    footer = f"tracked with @{bot_username}" if bot_username else "tracked with TimeTracker"
    d.text((PAD, H - 90), footer, font=_font(False, 30), fill=MUTED)

    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()
