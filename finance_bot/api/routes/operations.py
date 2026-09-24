"""Операции."""

from aiohttp import web

from finance_bot.api import schemas
from finance_bot.api.context import BUDGET_BOT_KEY
from finance_bot.config import OPERATION_TYPES
from finance_bot.core.dates import effective_today
from finance_bot.database import queries
from finance_bot.services import budget as budget_service
from finance_bot.services import operations as operation_service

from ._common import _error

PAGE_SIZE = 40


async def operations(request: web.Request) -> web.Response:
    try:
        before = schemas.decode_cursor(request.query["before"]) \
            if request.query.get("before") else None
        type_ = request.query.get("type") or None
        if type_ is not None and type_ not in OPERATION_TYPES:
            raise schemas.ValidationError("неизвестный тип операции")
        needs_review = schemas.query_bool(request.query.get("needs_review"))
        date_filter = schemas.iso_date(request.query["date"]) \
            if request.query.get("date") else None
        date_from = schemas.iso_date(request.query["date_from"]) \
            if request.query.get("date_from") else None
        date_to = schemas.iso_date(request.query["date_to"]) \
            if request.query.get("date_to") else None
        if date_from is not None and date_to is not None and date_from > date_to:
            raise schemas.ValidationError("начало периода не может быть позже конца")
    except schemas.ValidationError as exc:
        return _error(str(exc))

    category = request.query.get("category") or None
    query = (request.query.get("q") or "").strip()[:100] or None
    rows = await queries.list_operations(
        before=before,
        category=category,
        type_=type_,
        query=query,
        needs_review=needs_review,
        op_date=date_filter,
        date_from=date_from,
        date_to=date_to,
        limit=PAGE_SIZE + 1,
    )
    has_more = len(rows) > PAGE_SIZE
    rows = rows[:PAGE_SIZE]
    next_cursor = schemas.encode_cursor(rows[-1]["op_date"], rows[-1]["id"]) \
        if has_more and rows else None
    totals = await queries.operations_totals(
        category=category,
        type_=type_,
        query=query,
        needs_review=needs_review,
        op_date=date_filter,
        date_from=date_from,
        date_to=date_to,
    )
    return web.json_response({
        "items": [schemas.operation_json(row) for row in rows],
        "next_cursor": next_cursor,
        "totals": {
            "total_count": totals["total_count"],
            "expense": schemas.money_string(totals["expense"]),
            "income": schemas.money_string(totals["income"]),
            "transfer": schemas.money_string(totals["transfer"]),
        },
    })


async def create_operation(request: web.Request) -> web.Response:
    idempotency_key = request.headers.get("Idempotency-Key")
    if idempotency_key:
        stored = await queries.get_idempotent_response(idempotency_key)
        if stored is not None:
            status, payload = stored
            return web.json_response(payload, status=status)

    try:
        fields = schemas.operation_create(
            await request.json(), effective_today()
        )
        operation, _ = await operation_service.create_operation(
            **fields,
            source="tma-ручной",
        )
    except (schemas.ValidationError, ValueError) as exc:
        return _error(str(exc))
    except (web.HTTPBadRequest, TypeError):
        return _error("некорректный JSON")

    if operation["type"] == "расход":
        await budget_service.notify_after_new_expense(
            request.app.get(BUDGET_BOT_KEY), operation["op_date"]
        )
    payload = schemas.operation_json(operation)
    if idempotency_key:
        # Повторный запрос с тем же ключом в течение 24 часов вернёт этот ответ.
        await queries.save_idempotent_response(idempotency_key, 201, payload)
    return web.json_response(payload, status=201)


async def patch_operation(request: web.Request) -> web.Response:
    try:
        op_id = int(request.match_info["id"])
        current = await queries.get_operation(op_id)
        if current is None:
            return _error("операция не найдена", 404)
        payload = await request.json()
        fields = schemas.operation_patch(payload, current)
    except (ValueError, schemas.ValidationError) as exc:
        return _error(str(exc))
    except (web.HTTPBadRequest, TypeError):
        return _error("некорректный JSON")

    updated = await queries.patch_operation(op_id, fields)
    if updated is None:
        return _error("операция не найдена", 404)
    return web.json_response(schemas.operation_json(updated))


async def confirm_operation(request: web.Request) -> web.Response:
    try:
        op_id = int(request.match_info["id"])
    except ValueError:
        return _error("некорректный id")
    operation = await queries.confirm_operation(op_id)
    if operation is None:
        return _error("операция не найдена", 404)
    return web.json_response(schemas.operation_json(operation))


async def delete_operation(request: web.Request) -> web.Response:
    try:
        op_id = int(request.match_info["id"])
    except ValueError:
        return _error("некорректный id")
    operation = await queries.soft_delete_operation(op_id)
    if operation is None:
        return _error("операция не найдена", 404)
    return web.json_response({"deleted": True, "id": op_id})


async def restore_operation(request: web.Request) -> web.Response:
    try:
        op_id = int(request.match_info["id"])
    except ValueError:
        return _error("некорректный id")
    operation = await queries.restore_operation(op_id)
    if operation is None:
        return _error("операция не найдена", 404)
    return web.json_response(schemas.operation_json(operation))


def register(app: web.Application) -> None:
    app.router.add_get("/api/operations", operations)
    app.router.add_post("/api/operations", create_operation)
    app.router.add_patch("/api/operations/{id}", patch_operation)
    app.router.add_post("/api/operations/{id}/confirm", confirm_operation)
    app.router.add_delete("/api/operations/{id}", delete_operation)
    app.router.add_post("/api/operations/{id}/restore", restore_operation)
