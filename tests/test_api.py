import json

import pytest
from aiohttp.test_utils import TestClient, TestServer

from app.config import Config
from app.seed import seed_user
from app.web.server import create_app
from conftest import FakeBot, dt
from test_auth import TOKEN, make_fields, sign

NOW = dt(2026, 11, 4, 18, 0)      # 19:00 local for the seeded +01:00 user
H = {"X-Dev-User": "111"}


@pytest.fixture
async def client(repo, tmp_path):
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<html>hello</html>")
    (static / "app.js").write_text("console.log(1)")
    await seed_user(repo, 111, 7, "+01:00", NOW)
    cfg = Config(bot_token=TOKEN, dev_mode=True)
    app = create_app(cfg, repo, bot=FakeBot(), static_dir=static, clock=lambda: NOW)
    async with TestClient(TestServer(app)) as c:
        c.repo, c.app_ = repo, app
        yield c


async def get(client, path, headers=H):
    r = await client.get(path, headers=headers)
    return r.status, await r.json()


async def test_health_and_static(client):
    r = await client.get("/health")
    assert r.status == 200 and await r.text() == "ok"
    r = await client.get("/app/")
    assert r.status == 200 and "hello" in await r.text()
    r = await client.get("/app/app.js")
    assert r.status == 200
    r = await client.get("/app", allow_redirects=False)
    assert r.status == 302 and r.headers["Location"] == "/app/"


async def test_me(client):
    status, me = await get(client, "/api/me")
    assert status == 200
    u = me["user"]
    assert u == {"first_name": "Demo", "tz": "+01:00", "wake_time": "08:00", "sleep_time": "23:00",
                 "ping_interval_min": 60, "paused": False, "challenge_day": 7, "challenge_days": 7,
                 "today": "2026-11-04"}
    assert len(me["categories"]) == 12
    assert set(me["categories"][0]) == {"id", "name", "emoji", "is_waste", "color", "active"}
    assert me["categories"][0]["color"] == "#4C7DF0" and me["categories"][9]["is_waste"] is True


async def test_day_shape_and_numbers(client):
    status, day = await get(client, "/api/day")
    assert status == 200
    assert set(day) == {"date", "awake_start_min", "awake_end_min", "awake_minutes", "tracked_minutes",
                        "untracked_minutes", "waste_minutes", "waste_share", "totals", "entries", "running",
                        "limits"}
    assert day["date"] == "2026-11-04" and (day["awake_start_min"], day["awake_end_min"]) == (480, 1380)
    assert day["awake_minutes"] == 660                           # 08:00 to 19:00 local
    assert day["tracked_minutes"] == sum(t["minutes"] for t in day["totals"])
    assert day["untracked_minutes"] <= day["awake_minutes"] - 0
    assert day["totals"] == sorted(day["totals"], key=lambda t: -t["minutes"])
    e = day["entries"][0]
    assert set(e) == {"id", "category_id", "start", "end", "start_min", "end_min", "source", "note"}
    assert e["start"] == f"{e['start_min'] // 60:02d}:{e['start_min'] % 60:02d}" and isinstance(e["end_min"], int)
    assert day["running"] is None
    assert day["limits"] == [{"goal_id": 1, "category_id": 10, "limit_min": 60,
                              "used_min": next((t["minutes"] for t in day["totals"] if t["category_id"] == 10), 0)}]
    waste_ids = {c["id"] for c in (await get(client, "/api/me"))[1]["categories"] if c["is_waste"]}
    assert day["waste_minutes"] == sum(t["minutes"] for t in day["totals"] if t["category_id"] in waste_ids)
    status, other = await get(client, "/api/day?date=2026-11-01")
    assert other["date"] == "2026-11-01" and other["awake_minutes"] == 900
    assert (await get(client, "/api/day?date=garbage"))[0] == 400


async def test_week_shape_and_numbers(client):
    status, week = await get(client, "/api/week")
    assert status == 200
    assert set(week) == {"start", "end", "days", "totals", "tracked_minutes", "untracked_minutes",
                         "waste_minutes", "waste_share", "prev_waste_minutes", "days_logged",
                         "waste_by_hour", "insight"}
    assert (week["start"], week["end"]) == ("2026-10-29", "2026-11-04") and len(week["days"]) == 7
    assert set(week["days"][0]) == {"date", "label", "tracked_minutes", "untracked_minutes", "waste_minutes",
                                    "logged", "totals"}
    assert week["days"][0]["label"] == "Thu"
    assert week["tracked_minutes"] == sum(d["tracked_minutes"] for d in week["days"])
    assert week["waste_minutes"] == sum(d["waste_minutes"] for d in week["days"])
    assert week["totals"][0].keys() == {"category_id", "minutes", "avg_per_day"}
    assert sum(t["minutes"] for t in week["totals"]) == week["tracked_minutes"]
    # the seeded user's first day is 2026-10-29, so the week before has no data
    assert week["prev_waste_minutes"] is None
    assert len(week["waste_by_hour"]) == 24 and sum(week["waste_by_hour"]) in range(week["waste_minutes"] - 24, week["waste_minutes"] + 25)
    assert week["insight"].keys() == {"text", "created_at"} and week["insight"]["text"].startswith("•")
    assert week["days_logged"] == sum(1 for d in week["days"] if d["logged"])
    # the evening waste peak of the seed shows up in the hour buckets
    assert sum(week["waste_by_hour"][19:23]) > 0.5 * sum(week["waste_by_hour"])
    status, earlier = await get(client, "/api/week?end=2026-11-02")
    assert earlier["end"] == "2026-11-02" and earlier["days"][-1]["date"] == "2026-11-02"


async def test_goals_shape(client):
    status, g = await get(client, "/api/goals")
    assert status == 200 and len(g["goals"]) == 1
    goal = g["goals"][0]
    assert set(goal) == {"id", "category_id", "daily_limit_min", "today_used_min", "week_avg_min",
                         "baseline_avg_min"}
    assert goal["daily_limit_min"] == 60 and goal["category_id"] == 10


async def test_entries_post_and_delete(client):
    cats = (await get(client, "/api/me"))[1]["categories"]
    study = next(c["id"] for c in cats if c["name"] == "Study")
    r = await client.post("/api/entries", headers=H, json={
        "category_id": study, "date": "2026-11-04", "start": "14:00", "end": "15:30", "note": None})
    body = await r.json()
    assert r.status == 200 and body["ok"] is True
    e = body["entry"]
    assert e == {"id": e["id"], "category_id": study, "start": "14:00", "end": "15:30", "start_min": 840,
                 "end_min": 930, "source": "manual", "note": None}
    day = (await get(client, "/api/day"))[1]
    inside = [x for x in day["entries"] if x["start_min"] < 930 and x["end_min"] > 840]
    assert [x["id"] for x in inside] == [e["id"]]                 # everything else was trimmed away
    assert next(t for t in day["totals"] if t["category_id"] == study)["minutes"] == 90
    r = await client.delete(f"/api/entries/{e['id']}", headers=H)
    assert r.status == 200 and await r.json() == {"ok": True}
    day = (await get(client, "/api/day"))[1]
    assert all(x["id"] != e["id"] for x in day["entries"])
    assert (await client.delete(f"/api/entries/{e['id']}", headers=H)).status == 404


async def test_entries_validation(client):
    async def post(**kw):
        body = {"category_id": 1, "date": "2026-11-04", "start": "14:00", "end": "15:00", **kw}
        r = await client.post("/api/entries", headers=H, json=body)
        return r.status, await r.json()
    s, b = await post(start="15:00", end="14:00")
    assert s == 400 and b["error"] == "bad_range" and "message" in b
    assert (await post(start="15:00", end="15:00"))[0] == 400
    s, b = await post(start="20:00", end="21:00")
    assert s == 400 and b["error"] == "future"
    s, b = await post(start="18:00", end="21:00")                  # clipped to now (19:00 local)
    assert s == 200 and b["entry"]["end"] == "19:00"
    assert (await post(start="xx", end="15:00"))[1]["error"] == "bad_time"
    assert (await post(category_id=9999))[1]["error"] == "bad_category"


async def test_entries_cannot_touch_other_users(client, repo):
    from conftest import make_user
    await make_user(repo, uid=222)
    eid = (await get(client, "/api/day"))[1]["entries"][0]["id"]
    r = await client.delete(f"/api/entries/{eid}", headers={"X-Dev-User": "222"})
    assert r.status == 404
    r = await client.post("/api/entries", headers={"X-Dev-User": "222"},
                          json={"category_id": 1, "date": "2026-11-04", "start": "10:00", "end": "11:00"})
    assert r.status == 400                                       # category 1 belongs to user 111


async def test_goals_post_and_delete(client):
    r = await client.post("/api/goals", headers=H, json={"category_id": 11, "daily_limit_min": 45})
    body = await r.json()
    assert r.status == 200 and body["ok"] is True
    g = body["goal"]
    assert set(g) == {"id", "category_id", "daily_limit_min", "today_used_min", "week_avg_min", "baseline_avg_min"}
    assert g["category_id"] == 11 and g["daily_limit_min"] == 45 and g["baseline_avg_min"] > 0
    # replaces an existing goal for the same category
    r = await client.post("/api/goals", headers=H, json={"category_id": 11, "daily_limit_min": 30})
    g2 = (await r.json())["goal"]
    goals = (await get(client, "/api/goals"))[1]["goals"]
    assert [x["daily_limit_min"] for x in goals if x["category_id"] == 11] == [30]
    assert (await client.post("/api/goals", headers=H, json={"category_id": 11, "daily_limit_min": 1})).status == 400
    r = await client.delete(f"/api/goals/{g2['id']}", headers=H)
    assert r.status == 200 and await r.json() == {"ok": True}
    assert all(x["category_id"] != 11 for x in (await get(client, "/api/goals"))[1]["goals"])
    assert (await client.delete("/api/goals/9999", headers=H)).status == 404


async def test_auth_rules(client, repo):
    assert (await get(client, "/api/me", headers={}))[0] == 401
    s, b = await get(client, "/api/me", headers={"X-Dev-User": "4242"})
    assert s == 404 and b["error"] == "not_registered"
    # real initData works
    init = sign(make_fields(auth_date=int(NOW.timestamp()), uid=111))
    s, me = await get(client, "/api/me", headers={"X-Telegram-Init-Data": init})
    assert s == 200 and me["user"]["first_name"] == "Demo"
    bad = init.replace("Nik", "Eve")
    assert (await get(client, "/api/me", headers={"X-Telegram-Init-Data": bad}))[0] == 401


async def test_dev_header_ignored_without_dev_mode(repo, tmp_path):
    await seed_user(repo, 111, 3, "+01:00", NOW)
    app = create_app(Config(bot_token=TOKEN, dev_mode=False), repo, static_dir=tmp_path, clock=lambda: NOW)
    async with TestClient(TestServer(app)) as c:
        r = await c.get("/api/me", headers=H)
        assert r.status == 401
