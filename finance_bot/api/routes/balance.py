"""Денежный якорь (баланс)."""

from aiohttp import web

from finance_bot.api import schemas
from finance_bot.core.dates import effective_today
from finance_bot.services import balance as balance_service

from ._common import _error


def _cash_balance_payload(snapshot: dict) -> dict:
    return {
        "amount": schemas.money_string(snapshot["amount"]),
        "anchor_date": snapshot["anchor_date"].isoformat(),
        "anchor_amount": schemas.money_string(snapshot["anchor_amount"]),
        "has_anchor": True,
    }


async def cash_balance(_: web.Request) -> web.Response:
    snapshot = await balance_service.get_snapshot()
    if snapshot is None:
        return web.json_response({"has_anchor": False})
    return web.json_response(_cash_balance_payload(snapshot))


async def update_cash_balance(request: web.Request) -> web.Response:
    try:
        fields = schemas.balance_anchor(await request.json(), effective_today())
    except schemas.ValidationError as exc:
        return _error(str(exc))
    except (web.HTTPBadRequest, TypeError):
        return _error("некорректный JSON")

    await balance_service.set_anchor(fields["amount"], fields["anchor_date"])
    snapshot = await balance_service.get_snapshot()
    if snapshot is None:
        return _error("не удалось прочитать сохранённый якорь", 500)
    return web.json_response(_cash_balance_payload(snapshot))


def register(app: web.Application) -> None:
    app.router.add_get("/api/balance", cash_balance)
    app.router.add_patch("/api/balance", update_cash_balance)
