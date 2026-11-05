"""Weekly insight: Claude if available, rule-based fallback otherwise. Never raises."""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import date

from .timeutil import fmt_dur

log = logging.getLogger("ai")

SYSTEM_PROMPT = (
    "You are the cashier at Spent, a 7-day time audit that prints people a receipt for their week. "
    "Voice: dry, a little funny, never preachy. The user marked some categories as 'waste' themselves. "
    "Look at their week and give concrete, specific observations with real numbers. No moralizing, no "
    "guilt, no hype, plain English. Reply with JSON only, no markdown, in exactly this shape: "
    '{"insights": ["...", "...", "..."], "goal": {"category_id": 12, "daily_limit_min": 60, '
    '"reason": "..."}}. '
    "Each insight is at most 25 words. At least one insight names a specific time of day if the data "
    "shows a pattern (see waste_by_hour, index = hour of day). The goal must use a category_id from the "
    "data, preferably the biggest waste category, with a realistic daily limit in minutes."
)


def build_ai_input(week: dict, categories: list[dict], goals: list[dict]) -> dict:
    """Compact JSON-able summary of the week."""
    names = {c["id"]: c["name"] for c in categories}
    n = max(1, week.get("active_days", 7))
    cats = []
    for t in week["totals"]:
        c = next((c for c in categories if c["id"] == t["category_id"]), None)
        if c:
            cats.append({"id": c["id"], "name": c["name"], "is_waste": bool(c["is_waste"]),
                         "total_min": t["minutes"], "avg_per_day": t["avg_per_day"]})
    days = [{"date": d["date"], "weekday": date.fromisoformat(d["date"]).strftime("%A"),
             "tracked_min": d["tracked_minutes"], "waste_min": d["waste_minutes"],
             "by_category": {names.get(t["category_id"], str(t["category_id"])): t["minutes"]
                             for t in d["totals"]}}
            for d in week["days"]]
    return {
        "days": days, "categories": cats, "waste_by_hour": week["waste_by_hour"],
        "avg_waste_per_day": int(round(week["waste_minutes"] / n)),
        "untracked_minutes": week["untracked_minutes"], "tracked_minutes": week["tracked_minutes"],
        "logged_days": week["days_logged"],
        "goals": [{"category_id": g["category_id"], "daily_limit_min": g["daily_limit_min"]} for g in goals],
    }


def _floor15(x: float) -> int:
    return int(x // 15) * 15


def _peak_window(by_hour: list[int]) -> tuple[int, int] | None:
    """Two-hour window with the most waste minutes, as (start_hour, end_hour)."""
    if not by_hour or sum(by_hour) <= 0:
        return None
    best = max(range(24), key=lambda h: by_hour[h] + by_hour[(h + 1) % 24])
    if by_hour[best] + by_hour[(best + 1) % 24] < 0.3 * sum(by_hour):
        return None
    return best, (best + 2) % 24


def fallback_insight(data: dict) -> dict:
    """Rule-based insight, same shape as the AI answer."""
    waste_cats = [c for c in data["categories"] if c["is_waste"] and c["total_min"] > 0]
    insights: list[str] = []
    goal = None
    if waste_cats:
        top = max(waste_cats, key=lambda c: c["total_min"])
        avg = top["avg_per_day"]
        insights.append(f"{top['name']} was your biggest waste category, about {fmt_dur(avg)} a day.")
        peak = _peak_window(data["waste_by_hour"])
        if peak:
            insights.append(f"Most of your waste time lands between {peak[0]:02d}:00 and {peak[1]:02d}:00.")
        worst = max(data["days"], key=lambda d: d["waste_min"])
        if worst["waste_min"] > 0:
            insights.append(f"{worst['weekday']} was the heaviest day, with {fmt_dur(worst['waste_min'])} on waste.")
        total = data["tracked_minutes"] + data["untracked_minutes"]
        if total and data["untracked_minutes"] / total >= 0.15:
            share = round(100 * data["untracked_minutes"] / total)
            insights.append(f"About {share}% of your awake time is not logged, so the real number may be higher.")
        limit = max(15, _floor15(top["avg_per_day"] * 0.7))
        goal = {"category_id": top["id"], "daily_limit_min": limit,
                "reason": f"A cut of about 30% from your {fmt_dur(avg)} average is realistic."}
    else:
        insights.append("There is not much waste time logged yet, so there is no clear pattern.")
        insights.append("Keep answering the check-ins for a few more days to get a clearer picture.")
    return {"insights": insights[:3], "goal": goal}


def parse_ai_response(text: str, valid_category_ids: set[int]) -> dict | None:
    """Pull the JSON out of a model answer. Returns None if it is unusable."""
    if not text:
        return None
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I)
    lo, hi = text.find("{"), text.rfind("}")
    if lo < 0 or hi <= lo:
        return None
    try:
        obj = json.loads(text[lo:hi + 1])
    except (ValueError, TypeError):
        return None
    if not isinstance(obj, dict) or not isinstance(obj.get("insights"), list):
        return None
    insights = [s.strip() for s in obj["insights"] if isinstance(s, str) and s.strip()][:3]
    if not insights:
        return None
    goal = None
    g = obj.get("goal")
    if isinstance(g, dict):
        try:
            cid = int(g.get("category_id"))
            limit = int(g.get("daily_limit_min"))
        except (TypeError, ValueError):
            cid = limit = None
        if cid in valid_category_ids and limit is not None and 5 <= limit <= 1440:
            reason = g.get("reason")
            goal = {"category_id": cid, "daily_limit_min": limit,
                    "reason": reason.strip() if isinstance(reason, str) else ""}
    return {"insights": insights, "goal": goal}


async def get_insight(cfg, data: dict, client=None) -> dict:
    """Ask Claude for the weekly insight; any failure returns the rule-based one."""
    fallback = fallback_insight(data)
    if client is None and not cfg.anthropic_api_key:
        return fallback
    try:
        if client is None:
            from anthropic import AsyncAnthropic
            client = AsyncAnthropic(api_key=cfg.anthropic_api_key, timeout=30.0, max_retries=0)
        resp = await asyncio.wait_for(client.messages.create(
            model=cfg.anthropic_model, max_tokens=600, system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": json.dumps(data, ensure_ascii=False)}]), timeout=30)
        text = "".join(getattr(b, "text", "") for b in resp.content if getattr(b, "type", "") == "text")
        parsed = parse_ai_response(text, {c["id"] for c in data["categories"]})
        if not parsed:
            log.warning("AI answer was not usable, using fallback")
            return fallback
        if parsed["goal"] is None:
            parsed["goal"] = fallback["goal"]
        return parsed
    except Exception as exc:
        log.warning("AI insight failed (%s), using fallback", exc)
        return fallback
