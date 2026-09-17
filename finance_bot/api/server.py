"""aiohttp-сервер API и собранной статики TMA."""

import logging
from pathlib import Path

from aiogram import Bot
from aiohttp import web

from finance_bot.api.auth import (AUTHENTICATOR_KEY, Authenticator,
                                  auth_middleware, default_authenticator)
from finance_bot.api.context import BUDGET_BOT_KEY
from finance_bot.api.routes import setup_routes

logger = logging.getLogger(__name__)
TMA_DIST = Path(__file__).resolve().parents[2] / "tma" / "dist"


async def health(_: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


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
    app = web.Application(middlewares=[auth_middleware])
    app[AUTHENTICATOR_KEY] = authenticator or default_authenticator()
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
