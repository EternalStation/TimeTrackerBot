import hashlib
import hmac
import json
from urllib.parse import quote, urlencode

from app.web.server import validate_init_data

TOKEN = "123456:TEST-TOKEN"


def sign(fields: dict, token=TOKEN) -> str:
    check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    h = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode({**fields, "hash": h})


def make_fields(auth_date=1_800_000_000, uid=111):
    return {"auth_date": str(auth_date), "query_id": "AAH", "signature": "xyz",
            "user": json.dumps({"id": uid, "first_name": "Nik"}, separators=(",", ":"))}


def test_valid_init_data():
    data = sign(make_fields())
    user = validate_init_data(data, TOKEN, now_ts=1_800_000_100)
    assert user and user["id"] == 111


def test_tampered_or_wrong_token_rejected():
    data = sign(make_fields())
    tampered = data.replace(quote('"id":111', safe=""), quote('"id":999', safe=""))
    assert tampered != data
    assert validate_init_data(tampered, TOKEN, now_ts=1_800_000_100) is None
    assert validate_init_data(data, "999:OTHER", now_ts=1_800_000_100) is None
    assert validate_init_data(data.rsplit("&hash=", 1)[0], TOKEN, now_ts=1_800_000_100) is None
    assert validate_init_data("", TOKEN) is None
    assert validate_init_data(data, "") is None


def test_old_auth_date_rejected():
    data = sign(make_fields(auth_date=1_800_000_000))
    assert validate_init_data(data, TOKEN, now_ts=1_800_000_000 + 6 * 86400) is not None
    assert validate_init_data(data, TOKEN, now_ts=1_800_000_000 + 8 * 86400) is None
