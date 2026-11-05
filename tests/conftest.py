import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import connect  # noqa: E402
from app.repo import DEFAULT_CATEGORIES, Repo  # noqa: E402
from app.timeutil import iso  # noqa: E402

UTC = timezone.utc


def dt(y, mo, d, h=0, mi=0, s=0):
    return datetime(y, mo, d, h, mi, s, tzinfo=UTC)


@pytest.fixture
async def repo(tmp_path):
    conn = await connect(str(tmp_path / "test.db"))
    yield Repo(conn)
    await conn.close()


async def make_user(repo, uid=1, tz="+00:00", wake="08:00", sleep="23:00", interval=60,
                    start="2026-11-01", created="2026-11-01T00:00:00Z", with_cats=True, **extra):
    fields = dict(id=uid, chat_id=uid, first_name="T", tz=tz, wake_time=wake, sleep_time=sleep,
                  ping_interval_min=interval, paused=0, onboarding_step=None, challenge_start=start,
                  created_at=created)
    fields.update(extra)
    cols = ",".join(fields)
    await repo.conn.execute(f"INSERT INTO users({cols}) VALUES({','.join('?' * len(fields))})",
                            tuple(fields.values()))
    await repo.conn.commit()
    cats = {}
    if with_cats:
        for name, emoji, waste in DEFAULT_CATEGORIES:
            cats[name] = await repo.add_category(uid, name, emoji, waste)
    return await repo.get_user(uid), cats


class FakeMessage:
    def __init__(self, message_id):
        self.message_id = message_id


class FakeBot:
    """Records what would have been sent to Telegram."""

    def __init__(self, fail=False):
        self.sent, self.edits, self.photos = [], [], []
        self.fail = fail
        self._id = 100

    async def send_message(self, chat_id, text, **kw):
        if self.fail:
            raise RuntimeError("Forbidden: bot was blocked by the user")
        self._id += 1
        self.sent.append({"chat_id": chat_id, "text": text, **kw})
        return FakeMessage(self._id)

    async def edit_message_text(self, text, chat_id=None, message_id=None, **kw):
        if self.fail:
            raise RuntimeError("message is not modified")
        self.edits.append({"chat_id": chat_id, "message_id": message_id, "text": text, **kw})

    async def send_photo(self, chat_id, photo, **kw):
        if self.fail:
            raise RuntimeError("blocked")
        self.photos.append({"chat_id": chat_id, **kw})
        return FakeMessage(1)
