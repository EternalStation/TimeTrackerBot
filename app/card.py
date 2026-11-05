"""Spent receipts: daily and weekly summaries drawn as store receipts (Pillow only, no emoji).

Both renderers take plain dicts (see `reports.day_receipt_data` / `reports.week_receipt_data`)
and return PNG bytes. Font: DejaVu Sans Mono (Regular + Bold), shipped in app/assets/fonts.
"""
from __future__ import annotations

import hashlib
import io
import random
from datetime import date
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .config import ASSETS_DIR
from .timeutil import fmt_dur

# brand
PAPER = "#FBF9F4"
INK = "#1D1D1F"
MUTED = "#8C8C8C"
RULE = "#C9C5BC"
RED = "#E5482F"
BACKDROP = "#1D1D1F"

CANVAS_W = 1080
WEEK_H = 1920
BACKDROP_PAD = 80
PAPER_W = 800
PAPER_PAD_X = 48
TOOTH_W = 25
TOOTH_H = 14
PAPER_PAD_Y = 22

DOW = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
MON = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]

TAGLINE = "YOUR DAY, ITEMIZED"


# --------------------------------------------------------------------------- text helpers

@lru_cache(maxsize=64)
def _font(bold: bool, size: int) -> ImageFont.FreeTypeFont:
    name = "DejaVuSansMono-Bold.ttf" if bold else "DejaVuSansMono.ttf"
    try:
        return ImageFont.truetype(str(ASSETS_DIR / "fonts" / name), size)
    except OSError:
        return ImageFont.load_default(size)


_OK_RANGES = ((0x20, 0x24F), (0x2010, 0x2027), (0x2190, 0x21FF), (0x2200, 0x22FF), (0x2500, 0x259F))


def clean(text: str) -> str:
    """Drop what the font cannot draw (emoji, joiners, control characters)."""
    out = []
    for ch in str(text or ""):
        o = ord(ch)
        if ch in "\n\r\t":
            out.append(" ")
        elif any(a <= o <= b for a, b in _OK_RANGES):
            out.append(ch)
    text = str(text or "")
    return " " * (len(text) - len(text.lstrip(" "))) + " ".join("".join(out).split())


def fit_px(text: str, font, max_px: float) -> str:
    """Shorten with an ellipsis until the text is at most max_px wide."""
    text = clean(text)
    if font.getlength(text) <= max_px:
        return text
    while text and font.getlength(text + "…") > max_px:
        text = text[:-1]
    return text.rstrip() + "…"


def wrap_lines(text: str, font, max_px: float, max_lines: int, first_prefix: str = "",
               next_prefix: str = "") -> list[str]:
    """Greedy word wrap to at most max_lines; if words are left over the last line ends with '…'."""
    words = clean(text).split()
    lines: list[str] = []
    cur, has, i = first_prefix, False, 0
    while i < len(words):
        trial = cur + (" " if has else "") + words[i]
        if not has or font.getlength(trial) <= max_px:
            cur = trial if has else fit_px(trial, font, max_px)
            has = True
            i += 1
            continue
        lines.append(cur)
        if len(lines) == max_lines:
            s = lines[-1]
            while s and font.getlength(s + "…") > max_px:
                s = s[:-1]
            lines[-1] = s.rstrip() + "…"
            return lines
        cur, has = next_prefix, False
    if has:
        lines.append(cur)
    return lines


def _day_label(d: date) -> str:
    return f"{DOW[d.weekday()]} {d.day:02d} {MON[d.month - 1]}"


def years_of_waste(minutes_per_day: float) -> int:
    """Days a year that would go to waste at this daily rate."""
    return int(round(minutes_per_day * 365 / 1440))


# --------------------------------------------------------------------------- receipt builder

class _Receipt:
    """Collects rows (height + draw function), then renders them on a torn paper strip."""

    def __init__(self, size: int):
        self.s = size
        self.reg = _font(False, size)
        self.bold = _font(True, size)
        self.inner = PAPER_W - 2 * PAPER_PAD_X
        self.adv = self.reg.getlength("M")
        self.cols = int(self.inner // self.adv)
        self.lh = round(size * 1.38)
        self.rows: list[tuple[int, object]] = []

    def _f(self, bold=False, scale=1.0):
        return _font(bold, max(10, round(self.s * scale)))

    # --- row builders
    def gap(self, h: int):
        self.rows.append((h, None))

    def center(self, text, scale=1.0, bold=False, fill=INK, spacing=0.0, h=None):
        font = self._f(bold, scale)
        text = clean(text)

        def draw(d, y, x0, x1):
            total = sum(font.getlength(c) for c in text) + spacing * (len(text) - 1)
            max_w = x1 - x0
            sp = spacing
            if total > max_w:
                sp = max(0.0, spacing - (total - max_w) / max(1, len(text) - 1))
                total = sum(font.getlength(c) for c in text) + sp * (len(text) - 1)
            x = (x0 + x1) / 2 - total / 2
            cy = y + self._h(h, scale) / 2
            for c in text:
                d.text((x, cy), c, font=font, fill=fill, anchor="lm")
                x += font.getlength(c) + sp
        self.rows.append((self._h(h, scale), draw))

    def _h(self, h, scale):
        return h if h is not None else round(self.lh * scale)

    def left(self, text, scale=1.0, bold=False, fill=INK, h=None):
        font = self._f(bold, scale)

        def draw(d, y, x0, x1):
            d.text((x0, y + self._h(h, scale) / 2), fit_px(text, font, x1 - x0), font=font, fill=fill, anchor="lm")
        self.rows.append((self._h(h, scale), draw))

    def lr(self, left, right, scale=1.0, bold=False, lfill=INK, rfill=None, h=None, bar=None):
        """Label on the left, value right-aligned. bar = (fraction, color) draws a thin bar between."""
        font = self._f(bold, scale)
        right = clean(right)
        rfill = rfill or lfill

        def draw(d, y, x0, x1):
            cy = y + self._h(h, scale) / 2
            rw = font.getlength(right)
            d.text((x1, cy), right, font=font, fill=rfill, anchor="rm")
            lt = fit_px(left, font, x1 - x0 - rw - self.adv * 2 * scale)
            d.text((x0, cy), lt, font=font, fill=lfill, anchor="lm")
            if bar and bar[0] > 0:
                bx0 = x0 + font.getlength(lt) + self.adv * 1.5
                bx1 = x1 - rw - self.adv * 1.5
                if bx1 - bx0 > 12:
                    w = max(6, (bx1 - bx0) * bar[0])
                    d.rectangle((bx0, cy - 5, bx0 + w, cy + 5), fill=bar[1])
        self.rows.append((self._h(h, scale), draw))

    def item(self, qty, name, waste, muted=False):
        font = self.reg
        star = _font(True, self.s)
        colw = self.adv * 9

        def draw(d, y, x0, x1):
            cy = y + self.lh / 2
            d.text((x0, cy), qty, font=font, fill=INK, anchor="lm")
            nx = x0 + colw
            avail = x1 - nx - self.adv * 2
            d.text((nx, cy), fit_px(name, font, avail), font=font, fill=MUTED if muted else INK, anchor="lm")
            if waste:
                d.text((x1, cy), "*", font=star, fill=RED, anchor="rm")
        self.rows.append((self.lh, draw))

    def col_header(self):
        font = _font(False, max(10, round(self.s * 0.8)))
        colw = self.adv * 9

        def draw(d, y, x0, x1):
            cy = y + self.lh * 0.8 / 2
            d.text((x0, cy), "QTY", font=font, fill=MUTED, anchor="lm")
            d.text((x0 + colw, cy), "ITEM", font=font, fill=MUTED, anchor="lm")
        self.rows.append((round(self.lh * 0.8), draw))

    def rule(self, double=False):
        def draw(d, y, x0, x1):
            ys = [y + 12] if not double else [y + 9, y + 17]
            for yy in ys:
                x = x0
                while x < x1:
                    d.line((x, yy, min(x + 9, x1), yy), fill=RULE if not double else MUTED, width=2)
                    x += 15
        self.rows.append((24 if not double else 26, draw))

    def barcode(self, seed: str, h=84, width=520):
        rng = random.Random(int(hashlib.sha256(seed.encode()).hexdigest()[:16], 16))

        def draw(d, y, x0, x1):
            x = (x0 + x1) / 2 - width / 2
            end = x + width
            bar = True
            while x < end:
                w = rng.choice((2, 2, 3, 4, 6)) if bar else rng.choice((2, 3, 4, 5))
                if bar:
                    d.rectangle((x, y + 4, min(x + w, end) - 1, y + h - 4), fill=INK)
                x += w
                bar = not bar
        self.rows.append((h, draw))

    # --- rendering
    def content_height(self) -> int:
        return sum(h for h, _ in self.rows)

    def paper_height(self) -> int:
        return 2 * TOOTH_H + 2 * PAPER_PAD_Y + self.content_height()

    def draw_onto(self, canvas: Image.Image, py0: int) -> None:
        px0 = (canvas.width - PAPER_W) // 2
        ph = self.paper_height()
        _paste_paper(canvas, px0, py0, PAPER_W, ph)
        d = ImageDraw.Draw(canvas)
        y = py0 + TOOTH_H + PAPER_PAD_Y
        x0, x1 = px0 + PAPER_PAD_X, px0 + PAPER_W - PAPER_PAD_X
        for h, fn in self.rows:
            if fn:
                fn(d, y, x0, x1)
            y += h


def _paste_paper(canvas: Image.Image, px0: int, py0: int, w: int, h: int) -> None:
    """Soft shadow + paper with zigzag top and bottom edges (supersampled mask)."""
    k = 3
    pts = []
    n = w // TOOTH_W
    for i in range(2 * n + 1):                      # top edge, left to right
        pts.append((px0 * k + i * TOOTH_W * k // 2, (py0 + (TOOTH_H if i % 2 == 0 else 0)) * k))
    for i in range(2 * n, -1, -1):                  # bottom edge, right to left
        pts.append((px0 * k + i * TOOTH_W * k // 2, (py0 + h - (TOOTH_H if i % 2 == 0 else 0)) * k))
    pad = 60
    box = (px0 - pad, py0 - pad, px0 + w + pad, py0 + h + pad)
    bw, bh = box[2] - box[0], box[3] - box[1]
    big = Image.new("L", (bw * k, bh * k), 0)
    ImageDraw.Draw(big).polygon([(x - box[0] * k, y - box[1] * k) for x, y in pts], fill=255)
    mask = big.resize((bw, bh), Image.LANCZOS)
    shadow = mask.filter(ImageFilter.GaussianBlur(16)).point(lambda v: int(v * 0.55))
    black = Image.new("RGB", (bw, bh), "#000000")
    canvas.paste(black, (box[0], box[1] + 12), shadow)
    canvas.paste(Image.new("RGB", (bw, bh), PAPER), (box[0], box[1]), mask)


def _png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def _order_no(seed_id: int, d: date, n: int | None) -> str:
    num = n if n else int(hashlib.sha256(f"{seed_id}:{d.isoformat()}".encode()).hexdigest()[:6], 16) % 10000
    return f"#{num % 10000:04d}-{d.month:02d}{d.day:02d}"


def _header(r: _Receipt, subtitle: str, spaced: float = 4.0):
    r.gap(6)
    r.center("SPENT", scale=2.3, bold=True, spacing=r.s * 0.5, h=round(r.s * 2.6))
    r.center(subtitle, scale=0.9, spacing=spaced, h=round(r.lh * 1.15))
    r.gap(6)
    r.rule()


# --------------------------------------------------------------------------- daily receipt

def collapse_items(items: list[dict], limit: int = 10) -> list[dict]:
    """Sorted by minutes desc; more than `limit` lines -> the tail is summed into 'Other'."""
    items = sorted((i for i in items if i["minutes"] > 0), key=lambda i: -i["minutes"])
    if len(items) <= limit:
        return items
    head, tail = items[:limit - 1], items[limit - 1:]
    return head + [{"name": "Other", "minutes": sum(i["minutes"] for i in tail),
                    "is_waste": all(i.get("is_waste") for i in tail)}]


def render_day_receipt(day: dict, bot_username: str = "") -> bytes:
    """day: date, day_n, day_total, items=[{name, minutes, is_waste}], tracked, untracked, waste,
    waste_share, limits=[{name, limit, used}], user_id."""
    d: date = day["date"]
    r = _Receipt(34)
    _header(r, TAGLINE, spaced=3)

    head = _day_label(d) + f" {d.year}"
    day_n, day_total = day.get("day_n"), day.get("day_total")
    r.lr(head, f"DAY {day_n}/{day_total}" if day_n and day_total and day_n <= day_total
         else (f"DAY {day_n}" if day_n else ""))
    r.lr("CASHIER", f"@{bot_username}" if bot_username else "SPENT")
    r.rule()

    items = collapse_items(day.get("items", []))
    if items:
        r.col_header()
        for it in items:
            r.item(fmt_dur(it["minutes"]), it["name"], bool(it.get("is_waste")))
    else:
        r.gap(6)
        r.center("NOTHING RUNG UP TODAY.", scale=1.0, bold=True)
        r.center("THE REGISTER IS EMPTY.", scale=0.85, fill=MUTED)
        r.gap(6)
    r.rule()

    r.lr("TRACKED", fmt_dur(day.get("tracked", 0)))
    r.lr("NOT TRACKED", fmt_dur(day.get("untracked", 0)))
    for g in (day.get("limits", []) if items else []):
        over = g["used"] - g["limit"]
        label = f"LIMIT  {clean(g['name'])} {fmt_dur(g['limit'])}"
        if over > 0:
            r.lr(label, "+" + fmt_dur(over), rfill=RED, bold=False)
        else:
            r.lr(label, "OK")
    r.rule(double=True)

    waste = day.get("waste", 0)
    r.gap(4)
    r.lr("TOTAL WASTED *" if waste else "TOTAL WASTED", fmt_dur(waste), scale=1.3, bold=True,
         lfill=RED if waste else INK, h=round(r.lh * 1.5))
    if not items:
        sub = "NOTHING TO CHARGE"
    elif waste == 0:
        sub = "CLEAN DAY. SUSPICIOUS."
    else:
        sub = f"{round(day.get('waste_share', 0) * 100)}% OF TRACKED"
    r.lr("", sub, scale=0.85, lfill=MUTED, h=round(r.lh * 0.95))
    r.rule(double=True)

    r.gap(2)
    r.left("IF EVERY DAY WAS LIKE TODAY:", scale=0.85, fill=MUTED, h=round(r.lh * 0.95))
    r.left(f"{years_of_waste(waste)} DAYS A YEAR", scale=1.3, bold=True, h=round(r.lh * 1.4))
    r.rule()

    r.left("* = what you call waste", scale=0.8, fill=MUTED, h=round(r.lh * 0.9))
    r.center("NO REFUNDS. SEE YOU TOMORROW.", scale=0.85, bold=True, h=round(r.lh * 1.2))
    r.gap(8)
    r.barcode(f"{day.get('user_id', 0)}:{d.isoformat()}")
    r.center(_order_no(day.get("user_id", 0), d, day_n), scale=0.8, spacing=3, fill=MUTED,
             h=round(r.lh * 1.2))
    r.gap(4)

    ph = r.paper_height()
    canvas = Image.new("RGB", (CANVAS_W, ph + 2 * BACKDROP_PAD), BACKDROP)
    r.draw_onto(canvas, BACKDROP_PAD)
    return _png(canvas)


# --------------------------------------------------------------------------- weekly receipt

def _week_receipt(week: dict, notes: list[str], bot_username: str, size: int,
                  n_cats: int, n_notes: int) -> _Receipt:
    r = _Receipt(size)
    start: date = week["start"]
    end: date = week["end"]
    _header(r, "WEEKLY RECEIPT", spaced=3)
    if start.year == end.year:
        rng = f"{start.day:02d} {MON[start.month - 1]} - {end.day:02d} {MON[end.month - 1]} {end.year}"
    else:
        rng = f"{start.day:02d} {MON[start.month - 1]} {start.year} - {end.day:02d} {MON[end.month - 1]} {end.year}"
    r.center(rng, scale=0.9, bold=True, h=round(r.lh * 1.1))
    r.center("CASHIER  " + (f"@{bot_username}" if bot_username else "SPENT"), scale=0.8, fill=MUTED,
             h=round(r.lh * 0.95))
    r.rule()

    days = week.get("days", [])
    biggest = max([x["waste_minutes"] for x in days], default=0) or 1
    for x in days:
        label = _day_label(x["date"])
        if x.get("tracked_minutes", 0) <= 0 and x["waste_minutes"] <= 0:
            r.lr(label, "no data", lfill=INK, rfill=MUTED)
        else:
            r.lr(label, "wasted " + fmt_dur(x["waste_minutes"]),
                 rfill=RED if x["waste_minutes"] > 0 else INK,
                 bar=(x["waste_minutes"] / biggest, RED) if x["waste_minutes"] > 0 else None)
    r.rule()

    top = [t for t in week.get("top", []) if t["minutes"] > 0]
    if n_cats and top:
        r.col_header()
        for t in top[:n_cats]:
            r.item(fmt_dur(t["minutes"]), t["name"], bool(t.get("is_waste")))
        r.rule()

    waste = week.get("waste_minutes", 0)
    per_day = week.get("waste_per_day", 0)
    r.rule(double=True)
    r.gap(2)
    r.lr("TOTAL WASTED *" if waste else "TOTAL WASTED", fmt_dur(waste), scale=1.25, bold=True,
         lfill=RED if waste else INK, h=round(r.lh * 1.5))
    r.lr("", f"≈ {fmt_dur(per_day)} A DAY", scale=0.85, lfill=MUTED, h=round(r.lh * 0.95))
    r.rule(double=True)

    r.gap(2)
    r.left("AT THIS PACE:", scale=0.85, fill=MUTED, h=round(r.lh * 0.95))
    r.left(f"{years_of_waste(per_day)} DAYS A YEAR", scale=1.3, bold=True, h=round(r.lh * 1.4))
    r.rule()

    notes = [n for n in (notes or []) if clean(n)][:n_notes]
    if notes:
        r.left("CASHIER'S NOTE:", scale=0.85, bold=True, h=round(r.lh * 1.05))
        font = r.reg
        for n in notes:
            for line in wrap_lines(n, font, r.inner, 2, "> ", "  "):
                r.left(line, scale=1.0, h=round(r.lh * 0.98))
            r.gap(round(r.lh * 0.18))
        r.rule()

    r.left("* = what you call waste", scale=0.8, fill=MUTED, h=round(r.lh * 0.9))
    r.gap(6)
    r.barcode(f"{week.get('user_id', 0)}:{start.isoformat()}:{end.isoformat()}", h=round(size * 2.3))
    footer = (f"@{bot_username} · " if bot_username else "") + "7-day time audit"
    r.center(footer, scale=0.78, fill=MUTED, h=round(r.lh * 1.15))
    r.gap(2)
    return r


def render_week_receipt(week: dict, insight_lines: list[str] | None = None, bot_username: str = "") -> bytes:
    """week: start, end, days=[{date, waste_minutes, tracked_minutes}], top=[{name, minutes, is_waste}],
    waste_minutes, waste_per_day, user_id. Always 1080x1920; content is cut, never overflowed."""
    notes = list(insight_lines or [])
    avail = WEEK_H - 2 * 56
    chosen = None
    for size in (34, 32, 30, 28, 26, 24):           # biggest type that holds everything
        r = _week_receipt(week, notes, bot_username, size, 6, 3)
        if r.paper_height() <= avail:
            chosen = r
            break
    if chosen is None:                              # cut: notes first, then categories
        size = 24
        for n_notes, n_cats in ((2, 6), (1, 6), (0, 6), (0, 5), (0, 4), (0, 3), (0, 2), (0, 1), (0, 0)):
            r = _week_receipt(week, notes, bot_username, size, n_cats, n_notes)
            chosen = r
            if r.paper_height() <= avail:
                break
    canvas = Image.new("RGB", (CANVAS_W, WEEK_H), BACKDROP)
    py0 = max(0, (WEEK_H - chosen.paper_height()) // 2)
    chosen.draw_onto(canvas, py0)
    return _png(canvas)
