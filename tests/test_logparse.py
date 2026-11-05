from app.logparse import match_category, parse_log, resolve_category
from app.timeutil import parse_tz
from conftest import dt

TZ = parse_tz("+01:00")
NOW = dt(2026, 11, 4, 15, 0)   # 16:00 local


def test_simple_range():
    r = parse_log("14:00-14:40 work", NOW, TZ)
    assert r.ok and r.text == "work"
    assert r.start == dt(2026, 11, 4, 13, 0) and r.end == dt(2026, 11, 4, 13, 40)


def test_en_dash_em_dash_dots_and_spaces():
    for text in ("14:00 – 14:40 work", "14.00—14.40 work", "14:00 - 14:40 Work"):
        r = parse_log(text, NOW, TZ)
        assert r and r.ok and r.start == dt(2026, 11, 4, 13), text


def test_yesterday_and_now():
    r = parse_log("yesterday 22:00-23:15 gaming", NOW, TZ)
    assert r.start == dt(2026, 11, 3, 21) and r.end == dt(2026, 11, 3, 22, 15)
    r = parse_log("Yesterday 22:00-23:15 gaming", NOW, TZ)
    assert r.ok
    r = parse_log("15:00-now youtube", NOW, TZ)
    assert r.ok and r.end == NOW and r.start == dt(2026, 11, 4, 14)


def test_errors_and_clipping():
    assert not parse_log("15:00-14:00 work", NOW, TZ).ok                 # end before start
    assert "before" in parse_log("15:00-14:00 work", NOW, TZ).error
    assert not parse_log("17:00-18:00 work", NOW, TZ).ok                 # fully in the future
    r = parse_log("15:00-18:00 work", NOW, TZ)                            # partly future -> clipped
    assert r.ok and r.end == NOW
    assert not parse_log("25:00-26:00 work", NOW, TZ).ok
    assert parse_log("hello there", NOW, TZ) is None
    assert parse_log("14:00-15:00", NOW, TZ) is None                      # no category text


def test_category_matching():
    cats = [{"id": 1, "name": "Work"}, {"id": 2, "name": "Social media"}, {"id": 3, "name": "Study"},
            {"id": 4, "name": "Chores & cooking"}]
    assert [c["id"] for c in match_category(cats, "work")] == [1]
    assert [c["id"] for c in match_category(cats, "soc")] == [2]
    assert [c["id"] for c in match_category(cats, "media")] == [2]           # contains
    assert [c["id"] for c in match_category(cats, "s")] == [2, 3]            # ambiguous prefix
    assert match_category(cats, "nothing") == []
    assert resolve_category(cats, "s") == (None, None)
    assert resolve_category(cats, "work on report") == (cats[0], "on report")
