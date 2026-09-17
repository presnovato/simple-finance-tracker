"""Standalone local TMA server with auth bypass for mock previews."""

import asyncio
import logging
import os

from aiohttp import web

from finance_bot.api.server import create_app
from finance_bot.database import connection

logger = logging.getLogger(__name__)


class MockAuthenticator:
    """Development-only authenticator; never use this server in production."""

    def authenticate(self, _: str) -> dict:
        return {
            "id": int(os.getenv("ALLOWED_USER_ID", "123456789")),
            "first_name": "Mock",
            "username": "mock",
        }


async def main() -> None:
    await connection.init_pool()
    runner = web.AppRunner(create_app(authenticator=MockAuthenticator()))
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", int(os.getenv("PORT", "8080")))
    await site.start()
    logger.info("Mock TMA слушает на порту %s", os.getenv("PORT", "8080"))
    try:
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()
        await connection.close_pool()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    asyncio.run(main())
