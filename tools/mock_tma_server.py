"""Standalone local TMA server with auth bypass for mock previews."""

import asyncio
import logging
import os
import sys
from pathlib import Path

# При запуске файлом (`python tools/...`) корень репозитория не попадает в
# sys.path — добавляем его, чтобы импортировать finance_bot и tools.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from aiohttp import web  # noqa: E402

from finance_bot.api.server import create_app  # noqa: E402
from finance_bot.database import connection, queries  # noqa: E402
from tools._mock_guard import (  # noqa: E402
    MockGuardError,
    require_mock_environment,
)

logger = logging.getLogger(__name__)

DEFAULT_BIND_HOST = "127.0.0.1"


class MockAuthenticator:
    """Development-only authenticator; never use this server in production."""

    def authenticate(self, _: str) -> dict:
        return {
            "id": int(os.getenv("ALLOWED_USER_ID", "123456789")),
            "first_name": "Mock",
            "username": "mock",
        }


async def main() -> None:
    require_mock_environment()
    await connection.init_pool()
    runner = None
    try:
        marker = await queries.get_setting("mock_database")
        if marker != "1":
            raise MockGuardError(
                "База не помечена как mock (settings.mock_database != 1) — "
                "отказываюсь её раздавать."
            )
        runner = web.AppRunner(create_app(authenticator=MockAuthenticator()))
        await runner.setup()
        host = os.getenv("MOCK_BIND_HOST", DEFAULT_BIND_HOST)
        port = int(os.getenv("PORT", "8080"))
        site = web.TCPSite(runner, host, port)
        await site.start()
        logger.info("Mock TMA слушает на %s:%s", host, port)
        await asyncio.Event().wait()
    finally:
        if runner is not None:
            await runner.cleanup()
        await connection.close_pool()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        asyncio.run(main())
    except MockGuardError as error:
        print(f"Отказ: {error}", file=sys.stderr)
        raise SystemExit(2)
