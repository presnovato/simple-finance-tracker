"""Личные долги."""

from aiohttp import web

from finance_bot.api import schemas
from finance_bot.core.dates import effective_today
from finance_bot.database import queries

from ._common import _error


async def personal_debts(request: web.Request) -> web.Response:
    status = request.query.get("status") or None
    if status is not None and status not in {"open", "closed"}:
        return _error("неизвестный статус личного долга")
    archived_value = request.query.get("archived", "0")
    if archived_value not in {"0", "1"}:
        return _error("archived должен быть 0 или 1")
    rows = await queries.list_personal_debts(
        status, archived=archived_value == "1"
    )
    return web.json_response({
        "items": [schemas.operation_json(row) for row in rows]
    })


async def create_personal_debt(request: web.Request) -> web.Response:
    try:
        fields = schemas.personal_debt_create(await request.json(), effective_today())
    except schemas.ValidationError as exc:
        return _error(str(exc))
    except (web.HTTPBadRequest, TypeError):
        return _error("некорректный JSON")
    debt = await queries.insert_personal_debt(**fields)
    return web.json_response(schemas.operation_json(debt), status=201)


async def patch_personal_debt(request: web.Request) -> web.Response:
    try:
        debt_id = int(request.match_info["id"])
        current = await queries.get_personal_debt(debt_id)
        if current is None:
            return _error("личный долг не найден", 404)
        fields = schemas.personal_debt_patch(await request.json(), current)
    except (ValueError, schemas.ValidationError) as exc:
        return _error(str(exc))
    except (web.HTTPBadRequest, TypeError):
        return _error("некорректный JSON")
    updated = await queries.patch_personal_debt(debt_id, fields)
    if updated is None:
        return _error("личный долг не найден", 404)
    return web.json_response(schemas.operation_json(updated))


async def pay_personal_debt(request: web.Request) -> web.Response:
    try:
        debt_id = int(request.match_info["id"])
        fields = schemas.debt_payment(await request.json(), effective_today())
        if fields["payment_type"] != "regular":
            return _error("досрочный платёж доступен только для кредитов")
    except (ValueError, schemas.ValidationError) as exc:
        return _error(str(exc))
    try:
        updated = await queries.create_personal_debt_payment(
            debt_id,
            fields["date"],
            fields["amount"],
            fields["idempotency_key"],
            cash_effect=fields["cash_effect"],
        )
    except queries.DebtPaymentError as exc:
        return _error(str(exc), 409)
    if updated is None:
        return _error("личный долг не найден", 404)
    return web.json_response(schemas.operation_json(updated))


async def personal_debt_payments(request: web.Request) -> web.Response:
    try:
        debt_id = int(request.match_info["id"])
    except ValueError:
        return _error("некорректный id")
    if await queries.get_personal_debt(debt_id) is None:
        return _error("личный долг не найден", 404)
    return web.json_response({
        "items": [schemas.operation_json(row)
                  for row in await queries.personal_debt_history(debt_id)]
    })


async def archive_personal_debt(request: web.Request) -> web.Response:
    try:
        debt_id = int(request.match_info["id"])
    except ValueError:
        return _error("некорректный id")
    updated = await queries.set_personal_debt_archived(debt_id, True)
    if updated is None:
        return _error("личный долг не найден", 404)
    return web.json_response(schemas.operation_json(updated))


async def restore_personal_debt(request: web.Request) -> web.Response:
    try:
        debt_id = int(request.match_info["id"])
    except ValueError:
        return _error("некорректный id")
    updated = await queries.set_personal_debt_archived(debt_id, False)
    if updated is None:
        return _error("личный долг не найден", 404)
    return web.json_response(schemas.operation_json(updated))


async def delete_personal_debt(request: web.Request) -> web.Response:
    try:
        debt_id = int(request.match_info["id"])
    except ValueError:
        return _error("некорректный id")
    if not await queries.delete_personal_debt(debt_id):
        return _error("личный долг не найден или у него уже есть история", 409)
    return web.json_response({"deleted": True})


def register(app: web.Application) -> None:
    app.router.add_get("/api/personal-debts", personal_debts)
    app.router.add_post("/api/personal-debts", create_personal_debt)
    app.router.add_patch("/api/personal-debts/{id}", patch_personal_debt)
    app.router.add_post("/api/personal-debts/{id}/pay", pay_personal_debt)
    app.router.add_get(
        "/api/personal-debts/{id}/payments", personal_debt_payments
    )
    app.router.add_post(
        "/api/personal-debts/{id}/archive", archive_personal_debt
    )
    app.router.add_post(
        "/api/personal-debts/{id}/restore", restore_personal_debt
    )
    app.router.add_delete("/api/personal-debts/{id}", delete_personal_debt)
