import json
from types import SimpleNamespace

from app.ai import (build_ai_input, fallback_insight, get_insight, parse_ai_response)
from app.config import Config
from app.entries import week_stats_for
from app.seed import seed_user
from conftest import dt

NOW = dt(2026, 11, 4, 20)
GOOD = {"insights": ["Evenings are your weak spot.", "Tuesday was the heaviest day."],
        "goal": {"category_id": 10, "daily_limit_min": 60, "reason": "Small cut."}}


def test_parse_plain_fenced_and_chatty():
    assert parse_ai_response(json.dumps(GOOD), {10, 11})["goal"]["category_id"] == 10
    fenced = "```json\n" + json.dumps(GOOD) + "\n```"
    assert parse_ai_response(fenced, {10})["insights"][0].startswith("Evenings")
    chatty = "Sure! Here you go: " + json.dumps(GOOD) + " Hope that helps."
    assert parse_ai_response(chatty, {10}) is not None


def test_parse_rejects_junk_and_cleans_goal():
    assert parse_ai_response("not json", {10}) is None
    assert parse_ai_response("", {10}) is None
    assert parse_ai_response('{"insights": []}', {10}) is None
    assert parse_ai_response('{"insights": "text"}', {10}) is None
    bad_goal = dict(GOOD, goal={"category_id": 999, "daily_limit_min": 60})
    assert parse_ai_response(json.dumps(bad_goal), {10})["goal"] is None
    bad_goal = dict(GOOD, goal={"category_id": 10, "daily_limit_min": "abc"})
    assert parse_ai_response(json.dumps(bad_goal), {10})["goal"] is None
    many = {"insights": ["a", "b", "c", "d", 5, ""], "goal": None}
    assert parse_ai_response(json.dumps(many), {10})["insights"] == ["a", "b", "c"]


async def _data(repo):
    await seed_user(repo, 111, 7, "+01:00", NOW)
    user = await repo.get_user(111)
    cats = await repo.list_categories(111)
    week = await week_stats_for(repo, user, dt(2026, 11, 4, 12).date(), NOW, cats)
    return build_ai_input(week, cats, await repo.list_goals(111)), cats


async def test_fallback_rules(repo):
    data, cats = await _data(repo)
    fb = fallback_insight(data)
    assert 2 <= len(fb["insights"]) <= 3
    waste = {c["id"] for c in cats if c["is_waste"]}
    assert fb["goal"]["category_id"] in waste
    top = max((c for c in data["categories"] if c["is_waste"]), key=lambda c: c["total_min"])
    assert fb["goal"]["category_id"] == top["id"]
    expected = max(15, int(top["avg_per_day"] * 0.7) // 15 * 15)
    assert fb["goal"]["daily_limit_min"] == expected and expected % 15 == 0


def test_fallback_without_waste():
    data = {"categories": [], "days": [], "waste_by_hour": [0] * 24, "tracked_minutes": 0,
            "untracked_minutes": 0}
    fb = fallback_insight(data)
    assert fb["goal"] is None and fb["insights"]


class FakeClient:
    def __init__(self, text=None, exc=None):
        self.messages = SimpleNamespace(create=self.create)
        self.text, self.exc, self.calls = text, exc, []

    async def create(self, **kw):
        self.calls.append(kw)
        if self.exc:
            raise self.exc
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=self.text)])


async def test_get_insight_uses_model_answer(repo):
    data, cats = await _data(repo)
    cid = next(c["id"] for c in cats if c["is_waste"])
    good = {"insights": ["One.", "Two."], "goal": {"category_id": cid, "daily_limit_min": 45, "reason": "r"}}
    client = FakeClient(json.dumps(good))
    cfg = Config(anthropic_api_key="x", anthropic_model="test-model")
    res = await get_insight(cfg, data, client=client)
    assert res["insights"] == ["One.", "Two."] and res["goal"]["daily_limit_min"] == 45
    assert client.calls[0]["model"] == "test-model" and client.calls[0]["max_tokens"] == 600


async def test_get_insight_falls_back_on_any_failure(repo):
    data, _ = await _data(repo)
    cfg = Config(anthropic_api_key="x")
    fb = fallback_insight(data)
    assert await get_insight(cfg, data, client=FakeClient(exc=RuntimeError("boom"))) == fb
    assert await get_insight(cfg, data, client=FakeClient(text="sorry, no json")) == fb
    assert await get_insight(Config(), data) == fb            # no API key, no client
    # model answer without a usable goal keeps its insights but takes the fallback goal
    res = await get_insight(cfg, data, client=FakeClient(json.dumps({"insights": ["Only."], "goal": None})))
    assert res["insights"] == ["Only."] and res["goal"] == fb["goal"]
