"""Криптоактивы."""

from aiohttp import web

from finance_bot.api import schemas
from finance_bot.core.dates import effective_today
from finance_bot.database import queries
from finance_bot.services import crypto as crypto_service

from ._common import _error


async def crypto(request: web.Request) -> web.Response:
    holdings = await queries.list_crypto_holdings()
    transactions = await queries.list_crypto_transactions()
    return web.json_response({
        "items": [schemas.crypto_holding_json(row) for row in holdings],
        "transactions": [schemas.crypto_transaction_json(row) for row in transactions],
        "overview_visible": await crypto_service.is_overview_visible(),
    })


async def crypto_overview_visibility(request: web.Request) -> web.Response:
    return web.json_response({
        "overview_visible": await crypto_service.is_overview_visible(),
    })


async def update_crypto_overview_visibility(request: web.Request) -> web.Response:
    try:
        visible = schemas.crypto_overview_patch(await request.json())
    except schemas.ValidationError as exc:
        return _error(str(exc))
    except (web.HTTPBadRequest, TypeError):
        return _error("некорректный JSON")
    await crypto_service.set_overview_visible(visible)
    return web.json_response({"overview_visible": visible})


async def create_crypto_transaction(request: web.Request) -> web.Response:
    try:
        fields = schemas.crypto_transaction_create(
            await request.json(), effective_today()
        )
        transaction = await queries.insert_crypto_transaction(**fields)
    except (schemas.ValidationError, ValueError) as exc:
        return _error(str(exc))
    except (web.HTTPBadRequest, TypeError):
        return _error("некорректный JSON")
    return web.json_response(schemas.crypto_transaction_json(transaction), status=201)


async def patch_crypto_holding(request: web.Request) -> web.Response:
    try:
        asset = schemas.crypto_asset(request.match_info["asset"])
        fields = schemas.crypto_holding_patch(await request.json())
        holding = await queries.patch_crypto_holding(asset, fields["quantity"])
    except (schemas.ValidationError, ValueError) as exc:
        return _error(str(exc))
    except (web.HTTPBadRequest, TypeError):
        return _error("некорректный JSON")
    if holding is None:
        return _error("актив не найден", 404)
    return web.json_response(schemas.crypto_holding_json(holding))


async def delete_crypto_transaction(request: web.Request) -> web.Response:
    try:
        transaction_id = int(request.match_info["id"])
        deleted = await queries.delete_crypto_transaction(transaction_id)
    except (ValueError, schemas.ValidationError) as exc:
        return _error(str(exc))
    if deleted is None:
        return _error("криптооперация не найдена", 404)
    return web.json_response({
        "deleted": True,
        "transaction": schemas.crypto_transaction_json(deleted),
    })


def register(app: web.Application) -> None:
    app.router.add_get("/api/crypto", crypto)
    app.router.add_post("/api/crypto/transactions", create_crypto_transaction)
    app.router.add_get("/api/crypto/overview", crypto_overview_visibility)
    app.router.add_patch("/api/crypto/overview", update_crypto_overview_visibility)
    app.router.add_patch("/api/crypto/holdings/{asset}", patch_crypto_holding)
    app.router.add_delete("/api/crypto/transactions/{id}", delete_crypto_transaction)
