"""Защита mock-инструментов: только локальная явно включённая среда.

Mock-профиль отключает аутентификацию, поэтому запускать его можно лишь тогда,
когда это осознанно: переменная ``FINANCE_TRACKER_MOCK=1``, отсутствие Railway и
mock-токен вместо production.
"""

from __future__ import annotations

import os

from finance_bot.config import RAILWAY_ENV_VARS

MOCK_FLAG = "FINANCE_TRACKER_MOCK"
MOCK_TOKEN = "000000000:mock-token"


class MockGuardError(RuntimeError):
    """Небезопасный запуск mock-инструмента."""


def check_mock_environment(env: dict | None = None) -> list[str]:
    """Список причин отказа; пустой список — запускать можно."""
    values = os.environ if env is None else env
    problems: list[str] = []
    if values.get(MOCK_FLAG) != "1":
        problems.append(f"{MOCK_FLAG}=1 не задан")
    railway = [name for name in RAILWAY_ENV_VARS if values.get(name)]
    if railway:
        problems.append("обнаружены переменные Railway: " + ", ".join(railway))
    token = values.get("BOT_TOKEN", "")
    if token and token != MOCK_TOKEN:
        problems.append("BOT_TOKEN не пустой и не равен mock-токену")
    return problems


def require_mock_environment(env: dict | None = None) -> None:
    problems = check_mock_environment(env)
    if problems:
        raise MockGuardError(
            "Mock-инструменты запускаются только локально с "
            f"{MOCK_FLAG}=1, без Railway и с mock-токеном. Проблемы: "
            + "; ".join(problems)
        )
