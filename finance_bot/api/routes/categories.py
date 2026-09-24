"""Категории операций."""

from aiohttp import web

from finance_bot.config import EXPENSE_CATEGORIES, INCOME_CATEGORIES


async def categories(_: web.Request) -> web.Response:
    return web.json_response({
        "expense": list(EXPENSE_CATEGORIES),
        "income": list(INCOME_CATEGORIES),
    })


def register(app: web.Application) -> None:
    app.router.add_get("/api/categories", categories)
