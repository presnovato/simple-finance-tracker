"""Категории операций."""

from aiohttp import web

from finance_bot.config import EXPENSE_CATEGORIES, INCOME_CATEGORIES
from finance_bot.database import queries


async def categories(_: web.Request) -> web.Response:
    archived = await queries.archived_expense_categories(EXPENSE_CATEGORIES)
    return web.json_response({
        "expense": list(EXPENSE_CATEGORIES),
        "income": list(INCOME_CATEGORIES),
        "archived_expense": archived,
    })


def register(app: web.Application) -> None:
    app.router.add_get("/api/categories", categories)
