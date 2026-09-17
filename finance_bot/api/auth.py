"""Аутентификация Telegram Mini App с заменяемым backend-ом."""

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import parse_qsl

from aiohttp import web

from finance_bot.config import ALLOWED_USER_ID, BOT_TOKEN


class AuthError(ValueError):
    pass


class Authenticator(Protocol):
    def authenticate(self, credential: str) -> dict: ...


AUTHENTICATOR_KEY = web.AppKey("authenticator", Authenticator)


@dataclass(frozen=True)
class TelegramInitDataAuthenticator:
    bot_token: str
    allowed_user_id: int
    max_age_seconds: int = 86_400

    def authenticate(self, credential: str) -> dict:
        if not credential:
            raise AuthError("initData отсутствует")
        values = dict(parse_qsl(credential, keep_blank_values=True))
        received_hash = values.pop("hash", "")
        if not received_hash:
            raise AuthError("hash отсутствует")

        check_string = "\n".join(f"{key}={values[key]}" for key in sorted(values))
        secret = hmac.new(
            b"WebAppData", self.bot_token.encode("utf-8"), hashlib.sha256
        ).digest()
        expected_hash = hmac.new(
            secret, check_string.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(received_hash, expected_hash):
            raise AuthError("неверная подпись initData")

        try:
            auth_date = int(values["auth_date"])
            user = json.loads(values["user"])
            user_id = int(user["id"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise AuthError("initData не содержит корректного пользователя") from exc

        age = int(time.time()) - auth_date
        if age < -60 or age > self.max_age_seconds:
            raise AuthError("initData устарел")
        if user_id != self.allowed_user_id:
            raise AuthError("доступ запрещён")
        return user


def default_authenticator() -> TelegramInitDataAuthenticator:
    return TelegramInitDataAuthenticator(BOT_TOKEN, ALLOWED_USER_ID)


def _credential(request: web.Request) -> str:
    raw = request.headers.get("X-Telegram-Init-Data", "")
    if raw:
        return raw
    authorization = request.headers.get("Authorization", "")
    scheme, _, value = authorization.partition(" ")
    return value if scheme.lower() == "tma" else ""


@web.middleware
async def auth_middleware(request: web.Request, handler):
    if not request.path.startswith("/api/"):
        return await handler(request)
    authenticator = request.app[AUTHENTICATOR_KEY]
    try:
        request["auth_user"] = authenticator.authenticate(_credential(request))
    except AuthError as exc:
        return web.json_response({"error": str(exc)}, status=401)
    return await handler(request)
