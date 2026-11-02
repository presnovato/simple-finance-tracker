"""aiohttp-сервер API и собранной статики TMA."""

import asyncio
import logging
import os
from pathlib import Path

from aiogram import Bot
from aiohttp import web

from finance_bot.api.auth import (AUTHENTICATOR_KEY, Authenticator,
                                  TelegramInitDataAuthenticator, auth_middleware,
                                  default_authenticator)
from finance_bot.api.context import BUDGET_BOT_KEY
from finance_bot.api.routes import setup_routes
from finance_bot.config import RAILWAY_ENV_VARS
from finance_bot.database import connection
from finance_bot.services import bundle, scheduler, watchdog

logger = logging.getLogger(__name__)
TMA_DIST = Path(__file__).resolve().parents[2] / "tma" / "dist"
DB_CHECK_TIMEOUT_SECONDS = 2


def _has_railway_env() -> bool:
    return any(os.getenv(name) for name in RAILWAY_ENV_VARS)


async def _database_ok() -> bool:
    try:
        await asyncio.wait_for(
            connection.get_pool().fetchrow("SELECT 1"),
            timeout=DB_CHECK_TIMEOUT_SECONDS,
        )
    except Exception:
        return False
    return True


async def health(_: web.Request) -> web.Response:
    db_ok = await _database_ok()
    scheduler_ok = scheduler.is_running()
    healthy = db_ok and scheduler_ok
    return web.json_response(
        {
            "status": "ok" if healthy else "degraded",
            "db": db_ok,
            "scheduler": scheduler_ok,
            "polling_last_ok": watchdog.last_ok_iso(),
            "version": os.getenv("RAILWAY_GIT_COMMIT_SHA") or None,
            "tma_bundle_fresh": bundle.is_bundle_fresh(),
        },
        status=200 if healthy else 503,
    )


async def index(request: web.Request) -> web.Response:
    if request.path.startswith("/api/"):
        raise web.HTTPNotFound()
    index_file = TMA_DIST / "index.html"
    if not index_file.exists():
        return web.json_response(
            {"error": "TMA не собрана: выполните npm run build в tma"}, status=503
        )
    # Имена ассетов хешированы и неизменяемы, а index.html — точка входа:
    # если WebView Telegram закеширует его, приложение навсегда останется
    # на старом бандле. Явно запрещаем кеширование.
    return web.FileResponse(index_file, headers={
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache",
        "Expires": "0",
    })


def create_app(
    authenticator: Authenticator | None = None,
    bot: Bot | None = None,
) -> web.Application:
    resolved = authenticator or default_authenticator()
    if _has_railway_env() and not isinstance(
        resolved, TelegramInitDataAuthenticator
    ):
        # Mock-профиль и любой другой аутентификатор недопустимы в production.
        raise RuntimeError(
            "На Railway допустим только TelegramInitDataAuthenticator — "
            "mock-профиль запускать в production нельзя"
        )
    app = web.Application(middlewares=[auth_middleware])
    app[AUTHENTICATOR_KEY] = resolved
    app[BUDGET_BOT_KEY] = bot
    app.router.add_get("/health", health)
    setup_routes(app)
    assets = TMA_DIST / "assets"
    if assets.exists():
        app.router.add_static("/assets", assets, append_version=False)
    app.router.add_get("/{path:.*}", index)
    return app


async def start_server(port: int, bot: Bot | None = None) -> web.AppRunner:
    runner = web.AppRunner(create_app(bot=bot))
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info("TMA API слушает 0.0.0.0:%d", port)
    return runner
