"""Ближайшие платежи за 7 дней (spec 04)."""

from aiohttp import web

from finance_bot.api import schemas
from finance_bot.core.dates import effective_today
from finance_bot.core.upcoming import upcoming_window
from finance_bot.services import upcoming as upcoming_service


async def upcoming(_: web.Request) -> web.Response:
    today = effective_today()
    items, errors = await upcoming_service.get_upcoming(today)
    _, end = upcoming_window(today)
    return web.json_response({
        "date_from": today.isoformat(),
        "date_to": end.isoformat(),
        "items": [
            {
                "kind": item["kind"],
                "id": item["id"],
                "name": item["name"],
                "amount": (
                    schemas.money_string(item["amount"])
                    if item["amount"] is not None else None
                ),
                "date": item["date"].isoformat(),
            }
            for item in items
        ],
        "errors": errors,
    })


def register(app: web.Application) -> None:
    app.router.add_get("/api/upcoming", upcoming)
