from datetime import date, timedelta, timezone

from app.intervals import (awake_window, clip_to_day, day_stats, decide_ping, plan_override,
                           subtract_intervals, week_stats)
from app.timeutil import fmt_dur, parse_tz, tz_from_local_time
from conftest import dt

UTC = timezone.utc


def test_subtract_free_time_fragments():
    span = (dt(2026, 11, 4, 14), dt(2026, 11, 4, 15))
    busy = [(dt(2026, 11, 4, 14, 10), dt(2026, 11, 4, 14, 20)), (dt(2026, 11, 4, 14, 40), dt(2026, 11, 4, 16))]
    assert subtract_intervals(span, busy) == [
        (dt(2026, 11, 4, 14), dt(2026, 11, 4, 14, 10)),
        (dt(2026, 11, 4, 14, 20), dt(2026, 11, 4, 14, 40))]


def test_subtract_nothing_free_and_tiny_fragments():
    span = (dt(2026, 11, 4, 14), dt(2026, 11, 4, 15))
    assert subtract_intervals(span, [(dt(2026, 11, 4, 13), dt(2026, 11, 4, 16))]) == []
    # 30 s leftover is dropped
    busy = [(dt(2026, 11, 4, 14, 0, 30), dt(2026, 11, 4, 15))]
    assert subtract_intervals(span, busy) == []
    assert subtract_intervals(span, []) == [span]


def test_override_split_trim_delete():
    now = dt(2026, 11, 4, 20)
    existing = [
        (1, dt(2026, 11, 4, 9), dt(2026, 11, 4, 12)),       # contains new -> split
        (2, dt(2026, 11, 4, 13), dt(2026, 11, 4, 14)),      # overlaps start -> trimmed to the left
        (3, dt(2026, 11, 4, 14, 30), dt(2026, 11, 4, 16)),  # overlaps end -> trimmed to the right
        (4, dt(2026, 11, 4, 14, 10), dt(2026, 11, 4, 14, 20)),  # inside -> deleted
        (5, dt(2026, 11, 4, 8), dt(2026, 11, 4, 8, 30)),    # untouched
    ]
    p = plan_override(existing, dt(2026, 11, 4, 10), dt(2026, 11, 4, 11), now)
    assert p.delete == [] and p.insert == [(1, dt(2026, 11, 4, 11), dt(2026, 11, 4, 12))]
    assert p.update == [(1, dt(2026, 11, 4, 9), dt(2026, 11, 4, 10))]

    p = plan_override(existing, dt(2026, 11, 4, 13, 30), dt(2026, 11, 4, 15), now)
    assert (2, dt(2026, 11, 4, 13), dt(2026, 11, 4, 13, 30)) in p.update
    assert (3, dt(2026, 11, 4, 15), dt(2026, 11, 4, 16)) in p.update
    assert p.delete == [4]


def test_override_running_timer_keeps_running():
    now = dt(2026, 11, 4, 18)
    existing = [(7, dt(2026, 11, 4, 17), None)]
    p = plan_override(existing, dt(2026, 11, 4, 16, 30), dt(2026, 11, 4, 17, 30), now)
    assert p.update == [(7, dt(2026, 11, 4, 17, 30), None)] and not p.delete and not p.insert
    p = plan_override(existing, dt(2026, 11, 4, 17, 20), dt(2026, 11, 4, 17, 40), now)
    assert p.update == [(7, dt(2026, 11, 4, 17, 40), None)]
    assert p.insert == [(7, dt(2026, 11, 4, 17), dt(2026, 11, 4, 17, 20))]


def test_clip_across_midnight_and_offsets():
    # 23:00-01:00 local, offset +01:00 -> UTC 22:00-00:00
    tz = parse_tz("+01:00")
    s, e = dt(2026, 11, 4, 22), dt(2026, 11, 5, 0)
    d1 = clip_to_day(s, e, date(2026, 11, 4), tz)
    assert d1 == (dt(2026, 11, 4, 22), dt(2026, 11, 4, 23))      # 23:00-24:00 local
    d2 = clip_to_day(s, e, date(2026, 11, 5), tz)
    assert d2 == (dt(2026, 11, 4, 23), dt(2026, 11, 5, 0))        # 00:00-01:00 local
    assert clip_to_day(s, e, date(2026, 11, 3), tz) is None


def test_clip_negative_offset():
    tz = parse_tz("-05:00")
    # local Nov 4 22:00 -> Nov 5 02:00 is UTC Nov 5 03:00 -> 07:00
    s, e = dt(2026, 11, 5, 3), dt(2026, 11, 5, 7)
    assert clip_to_day(s, e, date(2026, 11, 4), tz) == (dt(2026, 11, 5, 3), dt(2026, 11, 5, 5))
    assert clip_to_day(s, e, date(2026, 11, 5), tz) == (dt(2026, 11, 5, 5), dt(2026, 11, 5, 7))
    # the same UTC instants are on a different local day for a +05:30 user
    assert clip_to_day(s, e, date(2026, 11, 4), parse_tz("+05:30")) is None


def _entry(i, cat, s, e, source="checkin"):
    return {"id": i, "category_id": cat, "start": s, "end": e, "source": source, "note": None}


def test_day_stats_negative_offset_split_entry():
    tz = parse_tz("-05:00")
    e = [_entry(1, 1, dt(2026, 11, 5, 3), dt(2026, 11, 5, 7))]
    now = dt(2026, 11, 6, 12)
    a = day_stats(date(2026, 11, 4), tz, "08:00", "23:00", e, set(), now)
    b = day_stats(date(2026, 11, 5), tz, "08:00", "23:00", e, set(), now)
    assert (a.entries[0]["start"], a.entries[0]["end"], a.entries[0]["end_min"]) == ("22:00", "00:00", 1440)
    assert (b.entries[0]["start"], b.entries[0]["end"], b.entries[0]["start_min"]) == ("00:00", "02:00", 0)
    assert a.tracked_minutes == 120 and b.tracked_minutes == 120


def test_awake_window_crosses_midnight():
    tz = parse_tz("+00:00")
    s, e = awake_window(date(2026, 11, 4), "08:00", "01:00", tz)
    assert s == dt(2026, 11, 4, 8) and e == dt(2026, 11, 5, 1)
    s, e = awake_window(date(2026, 11, 4), "08:00", "23:00", tz)
    assert e == dt(2026, 11, 4, 23)
    now = dt(2026, 11, 6, 12)
    # every day shows 08:00-24:00 plus the 00:00-01:00 tail of the previous night's window
    d4 = day_stats(date(2026, 11, 4), tz, "08:00", "01:00", [], set(), now)
    d5 = day_stats(date(2026, 11, 5), tz, "08:00", "01:00", [], set(), now)
    assert (d4.awake_start_min, d4.awake_end_min, d4.awake_minutes) == (480, 1440, 960 + 60)
    assert d5.awake_minutes == 960 + 60
    # entry after midnight belongs to the next day and covers the tail
    ent = [_entry(1, 1, dt(2026, 11, 5, 0), dt(2026, 11, 5, 1))]
    d5 = day_stats(date(2026, 11, 5), tz, "08:00", "01:00", ent, set(), now)
    assert d5.untracked_minutes == 960 and d5.tracked_minutes == 60


def test_awake_minutes_today_only_elapsed_and_running_timer():
    tz = parse_tz("+00:00")
    now = dt(2026, 11, 4, 12, 0)
    ent = [_entry(1, 1, dt(2026, 11, 4, 9), dt(2026, 11, 4, 10)),
           _entry(2, 10, dt(2026, 11, 4, 11, 30), None, "timer")]
    ds = day_stats(date(2026, 11, 4), tz, "08:00", "23:00", ent, {10}, now)
    assert ds.awake_minutes == 240
    assert ds.tracked_minutes == 60 + 30 and ds.waste_minutes == 30
    assert ds.untracked_minutes == 240 - 90
    assert ds.running == {"entry_id": 2, "category_id": 10, "start": "11:30", "start_min": 690, "minutes": 30}
    assert ds.totals[0] == {"category_id": 1, "minutes": 60}
    assert ds.waste_share == round(30 / 90, 3)
    assert not ds.logged                      # 90 of 240 min
    assert ds.waste_by_hour[11] == 30


def test_tracking_from_ignores_time_before_onboarding():
    tz = parse_tz("+00:00")
    now = dt(2026, 11, 4, 20)
    ds = day_stats(date(2026, 11, 4), tz, "08:00", "23:00", [], set(), now, tracking_from=dt(2026, 11, 4, 18))
    assert ds.awake_minutes == 120


def test_week_stats_shape_and_prev():
    tz = parse_tz("+00:00")
    now = dt(2026, 11, 8, 23, 30)
    ent = []
    for i in range(14):
        d = dt(2026, 10, 26) + timedelta(days=i)
        ent.append(_entry(i * 2 + 1, 1, d.replace(hour=9), d.replace(hour=17)))
        ent.append(_entry(i * 2 + 2, 10, d.replace(hour=20), d.replace(hour=21)))
    w = week_stats(date(2026, 11, 8), tz, "08:00", "23:00", ent, {10}, now, challenge_start=date(2026, 10, 26))
    assert w["start"] == "2026-11-02" and len(w["days"]) == 7
    assert w["waste_minutes"] == 7 * 60 and w["prev_waste_minutes"] == 7 * 60
    assert w["totals"][0] == {"category_id": 1, "minutes": 7 * 480, "avg_per_day": 480}
    assert sum(w["waste_by_hour"]) == 420 and w["waste_by_hour"][20] == 420
    assert w["days"][0]["label"] == "Mon" and w["days_logged"] == 7
    w2 = week_stats(date(2026, 11, 8), tz, "08:00", "23:00", ent, {10}, now, challenge_start=date(2026, 11, 2))
    assert w2["prev_waste_minutes"] is None


# ----------------------------------------------------------------------- ping decision

TZ = parse_tz("+01:00")   # window 08:00-23:00 local = 07:00-22:00 UTC


def D(*a, **k):
    return decide_ping(*a, **k)


def test_ping_normal_interval():
    d = D(dt(2026, 11, 4, 10), dt(2026, 11, 4, 9), 60, "08:00", "23:00", TZ, False)
    assert d.action == "ping" and (d.start, d.end) == (dt(2026, 11, 4, 9), dt(2026, 11, 4, 10))
    assert d.next_ping_at == dt(2026, 11, 4, 11)


def test_ping_cap_keeps_only_last_interval():
    d = D(dt(2026, 11, 4, 12), dt(2026, 11, 4, 6), 60, "08:00", "23:00", TZ, False)
    assert (d.start, d.end) == (dt(2026, 11, 4, 11), dt(2026, 11, 4, 12))
    # exactly 2x interval is not capped
    d = D(dt(2026, 11, 4, 12), dt(2026, 11, 4, 10), 60, "08:00", "23:00", TZ, False)
    assert d.start == dt(2026, 11, 4, 10)


def test_ping_uses_window_start_not_old_checkin():
    d = D(dt(2026, 11, 4, 8, 10), dt(2026, 11, 3, 21), 60, "08:00", "23:00", TZ, False)
    assert d.action == "ping" and d.start == dt(2026, 11, 4, 7)   # window start 08:00 local


def test_ping_too_short_interval():
    d = D(dt(2026, 11, 4, 10), dt(2026, 11, 4, 9, 55), 60, "08:00", "23:00", TZ, False)
    assert d.action == "short" and d.next_ping_at == dt(2026, 11, 4, 11)


def test_no_ping_while_timer_runs():
    d = D(dt(2026, 11, 4, 10), dt(2026, 11, 4, 9), 60, "08:00", "23:00", TZ, True)
    assert d.action == "timer" and d.next_ping_at == dt(2026, 11, 4, 11)


def test_ping_outside_window_moves_to_next_start():
    d = D(dt(2026, 11, 4, 23, 30), dt(2026, 11, 4, 21), 60, "08:00", "23:00", TZ, False)
    assert d.action == "outside"
    assert d.last_checkin_at == dt(2026, 11, 5, 7) and d.next_ping_at == dt(2026, 11, 5, 8)
    # before the window opens on the same day
    d = D(dt(2026, 11, 4, 5), None, 60, "08:00", "23:00", TZ, False)
    assert d.action == "outside" and d.last_checkin_at == dt(2026, 11, 4, 7)


def test_final_ping_exactly_at_window_end():
    d = D(dt(2026, 11, 4, 21, 10), dt(2026, 11, 4, 20, 10), 60, "08:00", "23:00", TZ, False)
    assert d.action == "ping" and d.next_ping_at == dt(2026, 11, 4, 22)       # not 22:10
    # the scheduler tick lands a few seconds late: still the final ping, ends at window end
    d = D(dt(2026, 11, 4, 22, 0, 20), dt(2026, 11, 4, 21, 10), 60, "08:00", "23:00", TZ, False)
    assert d.action == "ping" and d.end == dt(2026, 11, 4, 22) and d.start == dt(2026, 11, 4, 21, 10)
    assert d.next_ping_at == dt(2026, 11, 4, 23, 0, 20)
    # exactly at the end
    d = D(dt(2026, 11, 4, 22), dt(2026, 11, 4, 21, 10), 60, "08:00", "23:00", TZ, False)
    assert d.action == "ping" and d.end == dt(2026, 11, 4, 22)
    # well after the window: nothing is asked
    assert D(dt(2026, 11, 4, 22, 30), dt(2026, 11, 4, 21, 10), 60, "08:00", "23:00", TZ, False).action == "outside"


def test_ping_window_crossing_midnight():
    utc = parse_tz("+00:00")
    d = D(dt(2026, 11, 5, 0, 30), dt(2026, 11, 4, 23, 30), 30, "08:00", "01:00", utc, False)
    assert d.action == "ping" and d.end == dt(2026, 11, 5, 0, 30)
    d = D(dt(2026, 11, 5, 2), dt(2026, 11, 5, 1), 30, "08:00", "01:00", utc, False)
    assert d.action == "outside" and d.last_checkin_at == dt(2026, 11, 5, 8)


def test_tz_from_local_time_and_fmt():
    assert tz_from_local_time("14:05", dt(2026, 11, 4, 13, 2)) == "+01:00"
    assert tz_from_local_time("08:07", dt(2026, 11, 4, 13, 2)) == "-05:00"
    assert tz_from_local_time("18:30", dt(2026, 11, 4, 13, 0)) == "+05:30"
    assert tz_from_local_time("00:30", dt(2026, 11, 4, 23, 0)) == "+01:30"
    assert tz_from_local_time("nonsense", dt(2026, 11, 4, 13)) is None
    assert [fmt_dur(m) for m in (0, 45, 60, 65, 90, 1120)] == ["0m", "45m", "1h", "1h 05m", "1h 30m", "18h 40m"]
