import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest

from finance_bot.api.auth import AuthError, TelegramInitDataAuthenticator


def signed_init_data(token: str, user_id: int, auth_date: int | None = None) -> str:
    values = {
        "auth_date": str(auth_date or int(time.time())),
        "query_id": "test-query",
        "user": json.dumps({"id": user_id, "first_name": "Sunset"}, separators=(",", ":")),
    }
    check_string = "\n".join(f"{key}={values[key]}" for key in sorted(values))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    values["hash"] = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(values)


def test_auth_accepts_signed_allowed_user():
    auth = TelegramInitDataAuthenticator("secret", 123)
    assert auth.authenticate(signed_init_data("secret", 123))["id"] == 123


def test_auth_rejects_wrong_user_and_stale_data():
    auth = TelegramInitDataAuthenticator("secret", 123, max_age_seconds=60)
    with pytest.raises(AuthError):
        auth.authenticate(signed_init_data("secret", 456))
    with pytest.raises(AuthError):
        auth.authenticate(signed_init_data("secret", 123, int(time.time()) - 120))


def test_auth_rejects_tampering():
    auth = TelegramInitDataAuthenticator("secret", 123)
    tampered = signed_init_data("secret", 123).replace("Sunset", "Attacker")
    with pytest.raises(AuthError):
        auth.authenticate(tampered)
