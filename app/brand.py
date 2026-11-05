"""Brand assets for the human to upload (BotFather): python -m app.brand [out_dir].

Not used by the bot at runtime. avatar.png 640x640, description.png 640x360.
"""
from __future__ import annotations

import io
import math
import sys
from datetime import date
from pathlib import Path

from PIL import Image, ImageDraw

from .card import BACKDROP, INK, PAPER, RED, RULE, render_day_receipt
from .config import ASSETS_DIR

K = 4  # supersampling


def render_avatar(size: int = 640) -> bytes:
    """Receipt with a torn bottom, three bold lines and a red asterisk. Stays inside the circle crop."""
    S = size * K
    img = Image.new("RGB", (S, S), BACKDROP)
    d = ImageDraw.Draw(img)
    w, h = int(S * 0.52), int(S * 0.66)
    x0, y0 = (S - w) // 2, int(S * 0.15)
    teeth = 6
    tw, th = w / teeth, int(S * 0.04)
    pts = [(x0, y0), (x0 + w, y0), (x0 + w, y0 + h - th)]
    for i in range(teeth * 2, -1, -1):
        pts.append((x0 + i * tw / 2, y0 + h - (th if i % 2 == 0 else 0)))
    d.polygon(pts, fill=PAPER)
    # three bold ink lines
    lx0, lx1 = x0 + w * 0.14, x0 + w * 0.86
    lh = int(S * 0.026)
    for i, frac in enumerate((1.0, 0.72, 0.86)):
        ly = y0 + h * (0.16 + 0.12 * i)
        d.rounded_rectangle((lx0, ly, lx0 + (lx1 - lx0) * frac, ly + lh), radius=lh // 2, fill=INK)
    d.line((lx0, y0 + h * 0.50, lx1, y0 + h * 0.50), fill=RULE, width=max(2, K * 2))
    # red asterisk: three crossing strokes with round ends
    cx, cy, r, sw = x0 + w / 2, y0 + h * 0.735, w * 0.17, int(S * 0.034)
    for ang in (90, 30, 150):
        a = math.radians(ang)
        p1 = (cx + r * math.cos(a), cy - r * math.sin(a))
        p2 = (cx - r * math.cos(a), cy + r * math.sin(a))
        d.line((p1, p2), fill=RED, width=sw)
        for p in (p1, p2):
            d.ellipse((p[0] - sw / 2, p[1] - sw / 2, p[0] + sw / 2, p[1] + sw / 2), fill=RED)
    img = img.resize((size, size), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def sample_day() -> dict:
    items = [("Work", 190, False), ("Social media", 125, True), ("Eating", 88, False),
             ("YouTube / TV", 40, True), ("Commute", 67, False), ("Exercise", 55, False)]
    waste = sum(m for _, m, w in items if w)
    tracked = sum(m for _, m, _ in items)
    return {"date": date(2026, 11, 5), "day_n": 3, "day_total": 7,
            "items": [{"name": n, "minutes": m, "is_waste": w} for n, m, w in items],
            "tracked": tracked, "untracked": 100, "waste": waste, "waste_share": waste / tracked,
            "limits": [{"name": "Social media", "limit": 60, "used": 125}], "user_id": 1}


def render_description_picture(day: dict | None = None, bot_username: str = "timetrakerbot") -> bytes:
    """640x360: the top of a daily receipt, scaled, on charcoal."""
    full = Image.open(io.BytesIO(render_day_receipt(day or sample_day(), bot_username))).convert("RGB")
    crop_h = round(full.width * 360 / 640)
    out = full.crop((0, 0, full.width, crop_h)).resize((640, 360), Image.LANCZOS)
    buf = io.BytesIO()
    out.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ASSETS_DIR / "brand"
    out.mkdir(parents=True, exist_ok=True)
    (out / "avatar.png").write_bytes(render_avatar())
    (out / "description.png").write_bytes(render_description_picture())
    print(f"wrote {out}/avatar.png and description.png")


if __name__ == "__main__":
    main()
