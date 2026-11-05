"""Settings read from environment variables (see SPEC section 2)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _flag(value: str | None) -> bool:
    return (value or "").strip().lower() in ("1", "true", "yes", "on")


@dataclass
class Config:
    bot_token: str = ""
    public_url: str = ""
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-haiku-5-5"
    db_path: str = "./data/timetracker.db"
    admin_ids: set[int] = field(default_factory=set)
    port: int = 8080
    dev_mode: bool = False
    web_only: bool = False
    challenge_days: int = 7

    @classmethod
    def from_env(cls, env=None) -> "Config":
        env = os.environ if env is None else env
        admin_ids: set[int] = set()
        for part in (env.get("ADMIN_IDS") or "").split(","):
            part = part.strip()
            if part.lstrip("-").isdigit():
                admin_ids.add(int(part))
        try:
            port = int(env.get("PORT") or 8080)
        except ValueError:
            port = 8080
        try:
            days = int(env.get("CHALLENGE_DAYS") or 7)
        except ValueError:
            days = 7
        return cls(
            bot_token=(env.get("BOT_TOKEN") or "").strip(),
            public_url=(env.get("PUBLIC_URL") or "").strip().rstrip("/"),
            anthropic_api_key=(env.get("ANTHROPIC_API_KEY") or "").strip(),
            anthropic_model=(env.get("ANTHROPIC_MODEL") or "claude-haiku-5-5").strip(),
            db_path=(env.get("DB_PATH") or "./data/timetracker.db").strip(),
            admin_ids=admin_ids,
            port=port,
            dev_mode=_flag(env.get("DEV_MODE")),
            web_only=_flag(env.get("WEB_ONLY")),
            challenge_days=max(1, days),
        )

    @property
    def webapp_url(self) -> str:
        return self.public_url + "/app/" if self.public_url else ""


ASSETS_DIR = Path(__file__).parent / "assets"
