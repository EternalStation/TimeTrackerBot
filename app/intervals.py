"""Pure functions: no database, no Telegram, no clock reads.

All datetimes passed in here are timezone-aware. Spans are (start, end) tuples.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, tzinfo

from .timeutil import UTC, local_dt, local_midnight, parse_hm

Span = tuple[datetime, datetime]

MIN_FRAGMENT = timedelta(seconds=60)      # fragments shorter than this are dropped
MIN_PING_GAP = timedelta(minutes=10)      # do not ask about intervals shorter than this
FINAL_PING_GRACE = timedelta(seconds=120)  # scheduler ticks every 30 s; final ping may be a bit late


# --------------------------------------------------------------------------- free time / override

def subtract_intervals(span: Span, busy: list[Span]) -> list[Span]:
    """Parts of `span` not covered by `busy`. Fragments under one minute are skipped."""
    s, e = span
    out: list[Span] = []
    cur = s
    for bs, be in sorted(busy):
        if be <= cur:
            continue
        if bs >= e:
            break
        if bs > cur:
            out.append((cur, bs))
        cur = max(cur, be)
        if cur >= e:
            break
    if cur < e:
        out.append((cur, e))
    return [f for f in out if f[1] - f[0] >= MIN_FRAGMENT]


@dataclass
class OverridePlan:
    delete: list[int] = field(default_factory=list)
    # (entry_id, new_start, new_end); new_end None means "still running"
    update: list[tuple[int, datetime, datetime | None]] = field(default_factory=list)
    # (template_entry_id, start, end): new row copying category/source/ping/note from the template
    insert: list[tuple[int, datetime, datetime]] = field(default_factory=list)


def plan_override(existing: list[tuple[int, datetime, datetime | None]],
                  new_start: datetime, new_end: datetime, now: datetime) -> OverridePlan:
    """What to do with existing entries when a new, more precise entry covers [new_start, new_end].

    existing: (id, start, end) where end None = running timer (counts up to `now`).
    Overlapping entries are trimmed, split in two, or deleted.
    """
    plan = OverridePlan()
    for eid, a, b_raw in existing:
        running = b_raw is None
        b = now if running else b_raw
        if b <= new_start or a >= new_end:
            continue
        left = (a, new_start) if new_start - a >= MIN_FRAGMENT else None
        right = (new_end, b) if b - new_end >= MIN_FRAGMENT else None
        if running:
            # the timer keeps running from the end of the new entry
            plan.update.append((eid, max(a, new_end), None))
            if left:
                plan.insert.append((eid, left[0], left[1]))
        elif left and right:
            plan.update.append((eid, left[0], left[1]))
            plan.insert.append((eid, right[0], right[1]))
        elif left:
            plan.update.append((eid, left[0], left[1]))
        elif right:
            plan.update.append((eid, right[0], right[1]))
        else:
            plan.delete.append(eid)
    return plan


# --------------------------------------------------------------------------- windows and days

def awake_window(d: date, wake: str, sleep: str, tz: tzinfo) -> Span:
    """Awake window of local date d. Ends next day when sleep <= wake (e.g. 08:00 to 01:00)."""
    wt, st = parse_hm(wake), parse_hm(sleep)
    start = local_dt(d, wt, tz)
    end_date = d if st > wt else d + timedelta(days=1)
    return start, local_dt(end_date, st, tz)


def day_bounds(d: date, tz: tzinfo) -> Span:
    return local_midnight(d, tz), local_midnight(d + timedelta(days=1), tz)


def clip_span(span: Span, bounds: Span) -> Span | None:
    s, e = max(span[0], bounds[0]), min(span[1], bounds[1])
    return (s, e) if e > s else None


def clip_to_day(start: datetime, end: datetime, d: date, tz: tzinfo) -> Span | None:
    return clip_span((start, end), day_bounds(d, tz))


def minute_of_day(dt: datetime, d: date, tz: tzinfo, exact: bool = False) -> float | int:
    """Local wall-clock minutes from midnight of date d (0..1440)."""
    loc = dt.astimezone(tz)
    if loc.date() > d:
        return 1440
    if loc.date() < d:
        return 0
    val = loc.hour * 60 + loc.minute + loc.second / 60
    return val if exact else int(round(val))


def hm_str(minutes: int) -> str:
    minutes = minutes % 1440 if minutes >= 1440 else minutes
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def awake_spans_for_day(d: date, wake: str, sleep: str, tz: tzinfo) -> list[Span]:
    """Awake time that falls inside local day d: the tail of yesterday's window plus today's window."""
    bounds = day_bounds(d, tz)
    out = []
    for dd in (d - timedelta(days=1), d):
        c = clip_span(awake_window(dd, wake, sleep, tz), bounds)
        if c:
            out.append(c)
    return out


def _merge(spans: list[Span]) -> list[Span]:
    merged: list[Span] = []
    for s, e in sorted(spans):
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    return merged


def covered_seconds(spans: list[Span], within: list[Span]) -> float:
    total = 0.0
    for w in within:
        for s, e in _merge(spans):
            c = clip_span((s, e), w)
            if c:
                total += (c[1] - c[0]).total_seconds()
    return total


# --------------------------------------------------------------------------- aggregation

@dataclass
class DayStats:
    date: date
    awake_start_min: int
    awake_end_min: int
    awake_minutes: int
    tracked_minutes: int
    untracked_minutes: int
    waste_minutes: int
    waste_share: float
    totals: list[dict]          # [{"category_id", "minutes"}] sorted desc
    entries: list[dict]         # API-shaped, clipped to the day
    running: dict | None
    waste_by_hour: list[float]

    @property
    def logged(self) -> bool:
        return self.awake_minutes > 0 and self.tracked_minutes >= 0.5 * self.awake_minutes

    def minutes_for(self, category_id: int) -> int:
        for t in self.totals:
            if t["category_id"] == category_id:
                return t["minutes"]
        return 0


def day_stats(d: date, tz: tzinfo, wake: str, sleep: str, entries: list[dict],
              waste_ids: set[int], now: datetime, tracking_from: datetime | None = None) -> DayStats:
    """entries: dicts with id, category_id, start (aware), end (aware or None), source, note."""
    bounds = day_bounds(d, tz)
    main = clip_span(awake_window(d, wake, sleep, tz), bounds)
    awake_start_min = minute_of_day(main[0], d, tz) if main else 0
    awake_end_min = minute_of_day(main[1], d, tz) if main else 0

    # awake time that has already happened (and that the audit already covers)
    awake: list[Span] = []
    for s, e in awake_spans_for_day(d, wake, sleep, tz):
        e = min(e, now)
        if tracking_from:
            s = max(s, tracking_from)
        if e > s:
            awake.append((s, e))
    awake_minutes = int(round(sum((e - s).total_seconds() for s, e in awake) / 60))

    secs_by_cat: dict[int, float] = {}
    clipped_spans: list[Span] = []
    out_entries: list[dict] = []
    running = None
    hours = [0.0] * 24
    for en in sorted(entries, key=lambda x: x["start"]):
        is_running = en["end"] is None
        eff_end = now if is_running else en["end"]
        c = clip_span((en["start"], eff_end), bounds)
        if not c:
            continue
        clipped_spans.append(c)
        secs = (c[1] - c[0]).total_seconds()
        cid = en["category_id"]
        secs_by_cat[cid] = secs_by_cat.get(cid, 0.0) + secs
        smin = minute_of_day(c[0], d, tz)
        emin = minute_of_day(c[1], d, tz)
        out_entries.append({
            "id": en["id"], "category_id": cid,
            "start": hm_str(smin), "end": hm_str(emin),
            "start_min": smin, "end_min": emin,
            "source": en.get("source"), "note": en.get("note"),
        })
        if is_running:
            running = {"entry_id": en["id"], "category_id": cid, "start": hm_str(smin),
                       "start_min": smin,
                       "minutes": int((now - en["start"]).total_seconds() // 60)}
        if cid in waste_ids:
            a = minute_of_day(c[0], d, tz, exact=True)
            b = minute_of_day(c[1], d, tz, exact=True)
            for h in range(int(a // 60), min(24, int(math.ceil(b / 60)))):
                hours[h] += max(0.0, min(b, (h + 1) * 60) - max(a, h * 60))

    totals = [{"category_id": cid, "minutes": int(round(sec / 60))}
              for cid, sec in secs_by_cat.items()]
    totals = [t for t in totals if t["minutes"] > 0]
    totals.sort(key=lambda t: (-t["minutes"], t["category_id"]))
    tracked = sum(t["minutes"] for t in totals)
    waste = sum(t["minutes"] for t in totals if t["category_id"] in waste_ids)
    covered_awake = int(round(covered_seconds(clipped_spans, awake) / 60))
    untracked = max(0, awake_minutes - covered_awake)
    return DayStats(
        date=d, awake_start_min=awake_start_min, awake_end_min=awake_end_min,
        awake_minutes=awake_minutes, tracked_minutes=tracked, untracked_minutes=untracked,
        waste_minutes=waste, waste_share=round(waste / tracked, 3) if tracked else 0.0,
        totals=totals, entries=out_entries, running=running, waste_by_hour=hours,
    )


def active_day_count(start: date, end: date, today: date, challenge_start: date | None) -> int:
    """Days in [start, end] that count for averages: on/after challenge start, not in the future."""
    first = max(start, challenge_start) if challenge_start else start
    last = min(end, today)
    return max(1, (last - first).days + 1)


def week_stats(end: date, tz: tzinfo, wake: str, sleep: str, entries: list[dict],
               waste_ids: set[int], now: datetime, challenge_start: date | None = None,
               tracking_from: datetime | None = None, n_days: int = 7) -> dict:
    """Shape of GET /api/week (without `insight`). `entries` must cover n_days*2 days before `end`."""
    start = end - timedelta(days=n_days - 1)
    today = now.astimezone(tz).date()
    days_out = []
    cat_minutes: dict[int, int] = {}
    waste_by_hour = [0.0] * 24
    tracked = untracked = waste = logged = 0
    for i in range(n_days):
        d = start + timedelta(days=i)
        ds = day_stats(d, tz, wake, sleep, entries, waste_ids, now, tracking_from)
        days_out.append({"date": d.isoformat(), "label": d.strftime("%a"),
                         "tracked_minutes": ds.tracked_minutes,
                         "untracked_minutes": ds.untracked_minutes,
                         "waste_minutes": ds.waste_minutes, "logged": ds.logged,
                         "totals": ds.totals})
        for t in ds.totals:
            cat_minutes[t["category_id"]] = cat_minutes.get(t["category_id"], 0) + t["minutes"]
        for h in range(24):
            waste_by_hour[h] += ds.waste_by_hour[h]
        tracked += ds.tracked_minutes
        untracked += ds.untracked_minutes
        waste += ds.waste_minutes
        logged += 1 if ds.logged else 0
    n_active = active_day_count(start, end, today, challenge_start)
    totals = [{"category_id": cid, "minutes": m, "avg_per_day": int(round(m / n_active))}
              for cid, m in cat_minutes.items()]
    totals.sort(key=lambda t: (-t["minutes"], t["category_id"]))

    prev_waste = None
    if challenge_start is None or challenge_start < start:
        prev_waste = 0
        for i in range(1, n_days + 1):
            d = start - timedelta(days=i)
            prev_waste += day_stats(d, tz, wake, sleep, entries, waste_ids, now,
                                    tracking_from).waste_minutes
    return {
        "start": start.isoformat(), "end": end.isoformat(), "days": days_out, "totals": totals,
        "tracked_minutes": tracked, "untracked_minutes": untracked, "waste_minutes": waste,
        "waste_share": round(waste / tracked, 3) if tracked else 0.0,
        "prev_waste_minutes": prev_waste, "days_logged": logged,
        "waste_by_hour": [int(round(x)) for x in waste_by_hour],
        "active_days": n_active,
    }


# --------------------------------------------------------------------------- ping decision

@dataclass
class PingDecision:
    action: str                      # 'timer' | 'outside' | 'short' | 'ping'
    next_ping_at: datetime
    last_checkin_at: datetime | None = None   # new value to store, if the decision changes it
    start: datetime | None = None
    end: datetime | None = None


def windows_around(now: datetime, wake: str, sleep: str, tz: tzinfo) -> list[Span]:
    today = now.astimezone(tz).date()
    return [awake_window(today + timedelta(days=k), wake, sleep, tz) for k in (-1, 0, 1)]


def decide_ping(now: datetime, last_checkin: datetime | None, interval_min: int, wake: str,
                sleep: str, tz: tzinfo, timer_running: bool) -> PingDecision:
    """The scheduler's decision for one due user (SPEC section 6, steps 1 to 3 and 7)."""
    interval = timedelta(minutes=interval_min)
    windows = windows_around(now, wake, sleep, tz)
    current = None
    for ws, we in windows:
        if ws <= now <= we + FINAL_PING_GRACE:
            current = (ws, we)
            break

    def next_after() -> datetime:
        n = now + interval
        # final ping of the day lands exactly on the window end
        if current and now < current[1] < n:
            n = current[1]
        return n

    if timer_running:
        return PingDecision("timer", next_after())
    if current is None:
        upcoming = [ws for ws, _ in windows if ws > now]
        nxt = min(upcoming) if upcoming else now + interval
        return PingDecision("outside", nxt + interval, last_checkin_at=nxt)
    ws, we = current
    start = max(last_checkin, ws) if last_checkin else ws
    end = min(now, we)
    if end - start < MIN_PING_GAP:
        return PingDecision("short", next_after())
    if end - start > 2 * interval:
        start = end - interval
    return PingDecision("ping", next_after(), start=start, end=end)
