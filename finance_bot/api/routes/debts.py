"""Кредиты и рассрочки."""

from decimal import Decimal

from aiohttp import web

from finance_bot.api import schemas
from finance_bot.api.context import BUDGET_BOT_KEY
from finance_bot.core.dates import effective_today
from finance_bot.core.debts import (
    debt_curve,
    forecast_closure_date,
    progress_percent,
    repaid_principal,
)
from finance_bot.database import queries
from finance_bot.services import budget as budget_service

from ._common import _error


async def _debt_with_forecast(row: dict) -> dict:
    history = await queries.debt_history(row["id"])
    payments = [item for item in history if item["kind"] == "payment"]
    principal_payments = [
        (item["pay_date"], item["principal_amount"])
        for item in payments
        if item.get("principal_amount") is not None
        and item["principal_amount"] > 0
    ]
    forecast = forecast_closure_date(
        row["balance"],
        principal_payments,
        effective_today(),
    )
    result = schemas.operation_json(row)
    # `due_date` is the legacy DB/API name; expose the unambiguous UI name too.
    result["maturity_date"] = result.get("due_date")
    result["forecast_date"] = forecast.isoformat() if forecast else None
    result["payment_count"] = len(payments)
    result["history_count"] = len(history)
    result["progress"] = schemas.money_string(
        progress_percent(row["principal"], row["balance"])
    )
    return result


async def debts(request: web.Request) -> web.Response:
    status = request.query.get("status") or None
    if status is not None and status not in {"active", "closed"}:
        return _error("неизвестный статус кредита")
    archived_value = request.query.get("archived", "0")
    if archived_value not in {"0", "1"}:
        return _error("archived должен быть 0 или 1")
    rows = await queries.list_debts(status, archived=archived_value == "1")
    return web.json_response({
        "items": [await _debt_with_forecast(row) for row in rows]
    })


async def create_debt(request: web.Request) -> web.Response:
    try:
        fields = schemas.debt_create(await request.json())
    except schemas.ValidationError as exc:
        return _error(str(exc))
    except (web.HTTPBadRequest, TypeError):
        return _error("некорректный JSON")
    debt = await queries.insert_debt(**fields)
    return web.json_response(await _debt_with_forecast(debt), status=201)


async def patch_debt(request: web.Request) -> web.Response:
    try:
        debt_id = int(request.match_info["id"])
        current = await queries.get_debt(debt_id)
        if current is None:
            return _error("кредит не найден", 404)
        fields = schemas.debt_patch(await request.json(), current)
    except (ValueError, schemas.ValidationError) as exc:
        return _error(str(exc))
    except (web.HTTPBadRequest, TypeError):
        return _error("некорректный JSON")
    updated = await queries.patch_debt(debt_id, fields)
    if updated is None:
        return _error("кредит не найден", 404)
    return web.json_response(await _debt_with_forecast(updated))


async def adjust_debt(request: web.Request) -> web.Response:
    try:
        debt_id = int(request.match_info["id"])
        current = await queries.get_debt(debt_id)
        if current is None:
            return _error("кредит не найден", 404)
        fields = schemas.debt_adjust(
            await request.json(), effective_today(), current
        )
    except (ValueError, schemas.ValidationError) as exc:
        return _error(str(exc))
    except (web.HTTPBadRequest, TypeError):
        return _error("некорректный JSON")
    try:
        updated = await queries.adjust_debt_balance(
            debt_id, fields["balance"], fields["date"], fields["reason"]
        )
    except queries.DebtPaymentError as exc:
        return _error(str(exc), 409)
    if updated is None:
        return _error("кредит не найден", 404)
    return web.json_response(await _debt_with_forecast(updated))


async def pay_debt(request: web.Request) -> web.Response:
    try:
        debt_id = int(request.match_info["id"])
        fields = schemas.debt_payment(await request.json(), effective_today())
    except (ValueError, schemas.ValidationError) as exc:
        return _error(str(exc))
    try:
        payment = await queries.create_debt_payment(
            debt_id,
            fields["date"],
            fields["amount"],
            fields["idempotency_key"],
            fields["payment_type"],
            cash_effect=fields["cash_effect"],
            principal_amount=fields["principal_amount"],
            return_operation_details=True,
        )
    except queries.DebtPaymentError as exc:
        return _error(str(exc), 409)
    updated = payment["debt"] if payment is not None else None
    if updated is None:
        return _error("кредит не найден", 404)
    if payment.get("operation_created"):
        await budget_service.notify_after_new_expense(
            request.app.get(BUDGET_BOT_KEY), fields["date"]
        )
    return web.json_response(await _debt_with_forecast(updated))


async def debt_payments(request: web.Request) -> web.Response:
    try:
        debt_id = int(request.match_info["id"])
    except ValueError:
        return _error("некорректный id")
    if await queries.get_debt(debt_id) is None:
        return _error("кредит не найден", 404)
    return web.json_response({
        "items": [schemas.operation_json(row)
                  for row in await queries.debt_history(debt_id)]
    })


async def archive_debt(request: web.Request) -> web.Response:
    try:
        debt_id = int(request.match_info["id"])
    except ValueError:
        return _error("некорректный id")
    updated = await queries.set_debt_archived(debt_id, True)
    if updated is None:
        return _error("кредит не найден", 404)
    return web.json_response(await _debt_with_forecast(updated))


async def restore_debt(request: web.Request) -> web.Response:
    try:
        debt_id = int(request.match_info["id"])
    except ValueError:
        return _error("некорректный id")
    updated = await queries.set_debt_archived(debt_id, False)
    if updated is None:
        return _error("кредит не найден", 404)
    return web.json_response(await _debt_with_forecast(updated))


async def delete_debt(request: web.Request) -> web.Response:
    try:
        debt_id = int(request.match_info["id"])
    except ValueError:
        return _error("некорректный id")
    if not await queries.delete_debt(debt_id):
        return _error("кредит не найден или у него уже есть история", 409)
    return web.json_response({"deleted": True})


async def debts_summary(_: web.Request) -> web.Response:
    debt_rows = await queries.list_debts()
    payment_rows = await queries.list_debt_payments()
    total_principal = sum(
        (row["principal"] for row in debt_rows), Decimal("0")
    )
    total_balance = sum((row["balance"] for row in debt_rows), Decimal("0"))
    total_paid = sum(
        (
            repaid_principal(row["principal"], row["balance"])
            for row in debt_rows
        ),
        Decimal("0"),
    )
    curve = debt_curve(
        total_principal,
        [
            (row["pay_date"], row["principal_amount"])
            for row in payment_rows
            if row.get("principal_amount") is not None
            and row["principal_amount"] > 0
        ],
    )
    return web.json_response({
        "total_principal": schemas.money_string(total_principal),
        "total_balance": schemas.money_string(total_balance),
        "total_paid": schemas.money_string(total_paid),
        "progress": schemas.money_string(
            progress_percent(total_principal, total_balance)
        ),
        "active_count": sum(row["status"] == "active" for row in debt_rows),
        "closed_count": sum(row["status"] == "closed" for row in debt_rows),
        "curve": [
            {"month": point["month"],
             "balance": schemas.money_string(point["balance"])}
            for point in curve
        ],
    })


def register(app: web.Application) -> None:
    app.router.add_get("/api/debts/summary", debts_summary)
    app.router.add_get("/api/debts", debts)
    app.router.add_post("/api/debts", create_debt)
    app.router.add_patch("/api/debts/{id}", patch_debt)
    app.router.add_post("/api/debts/{id}/adjust", adjust_debt)
    app.router.add_post("/api/debts/{id}/pay", pay_debt)
    app.router.add_get("/api/debts/{id}/payments", debt_payments)
    app.router.add_post("/api/debts/{id}/archive", archive_debt)
    app.router.add_post("/api/debts/{id}/restore", restore_debt)
    app.router.add_delete("/api/debts/{id}", delete_debt)
