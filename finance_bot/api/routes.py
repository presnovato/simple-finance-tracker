"""Owner-only API Telegram Mini App."""

from decimal import Decimal

from aiohttp import web

from finance_bot.api import schemas
from finance_bot.api.context import BUDGET_BOT_KEY
from finance_bot.config import EXPENSE_CATEGORIES, INCOME_CATEGORIES, OPERATION_TYPES
from finance_bot.core.analytics import (average_daily, daily_series, parse_month,
                                         rolling_chart_bounds)
from finance_bot.core.balance import calculate_period_balance
from finance_bot.core.dates import effective_today, month_bounds
from finance_bot.core.debts import (
    debt_curve,
    forecast_closure_date,
    progress_percent,
    repaid_principal,
)
from finance_bot.core.subscriptions import (
    due_subscriptions,
    monthly_cost,
    next_charge_after,
    share_of_expenses,
    upcoming_charges,
    yearly_cost,
)
from finance_bot.database import queries
from finance_bot.services import balance as balance_service
from finance_bot.services import budget as budget_service
from finance_bot.services import crypto as crypto_service
from finance_bot.services import operations as operation_service

PAGE_SIZE = 40


def _error(message: str, status: int = 400) -> web.Response:
    return web.json_response({"error": message}, status=status)


async def summary(request: web.Request) -> web.Response:
    balance_snapshot = await balance_service.get_snapshot()
    start_ts = None
    if balance_snapshot is not None:
        start = balance_snapshot["anchor_date"]
        end = effective_today()
        start_ts = balance_snapshot.get("anchor_ts")
        month = start.strftime("%Y-%m")
        period_mode = "anchor"
    else:
        try:
            month = request.query.get("month") or effective_today().strftime("%Y-%m")
            start, end = parse_month(month)
        except ValueError as exc:
            return _error(str(exc))
        period_mode = "month"

    if period_mode == "anchor":
        chart_start, chart_end = rolling_chart_bounds(start, end)
    else:
        chart_start, chart_end = start, end

    if start_ts is None:
        totals = await queries.totals(start, end)
        day_rows = await queries.expenses_by_day(start, end)
        income_day_rows = await queries.income_by_day(start, end)
        category_rows = await queries.expenses_by_category(start, end)
    else:
        totals = await queries.totals(start, end, start_ts=start_ts)
        day_rows = await queries.expenses_by_day(start, end, start_ts=start_ts)
        income_day_rows = await queries.income_by_day(start, end, start_ts=start_ts)
        category_rows = await queries.expenses_by_category(start, end, start_ts=start_ts)
    days = daily_series(chart_start, chart_end, day_rows)
    income_days = daily_series(
        chart_start, chart_end, income_day_rows, value_key="income"
    )
    chart_expense_total = sum(
        (Decimal(row["total"]) for row in day_rows), Decimal("0")
    )
    chart_income_total = sum(
        (Decimal(row["total"]) for row in income_day_rows), Decimal("0")
    )
    average = average_daily(chart_expense_total, len(day_rows))
    average_income = average_daily(chart_income_total, len(income_day_rows))
    balance = calculate_period_balance(
        totals["income"],
        totals["expense"],
        totals.get("transfer_in", Decimal("0")),
        totals.get("transfer_out", Decimal("0")),
    )
    return web.json_response({
        "month": month,
        "period_mode": period_mode,
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "chart_start": chart_start.isoformat(),
        "chart_end": chart_end.isoformat(),
        "expense": schemas.money_string(totals["expense"]),
        "income": schemas.money_string(totals["income"]),
        "transfer_in": schemas.money_string(
            totals.get("transfer_in", Decimal("0"))
        ),
        "transfer_out": schemas.money_string(
            totals.get("transfer_out", Decimal("0"))
        ),
        "balance": schemas.money_string(balance),
        "average_daily": schemas.money_string(average),
        "average_daily_income": schemas.money_string(average_income),
        "days": [
            {
                "op_date": expense_row["op_date"].isoformat(),
                "expense": schemas.money_string(expense_row["expense"]),
                "income": schemas.money_string(income_row["income"]),
            }
            for expense_row, income_row in zip(days, income_days)
        ],
        "categories": [
            {"category": row["category"], "total": schemas.money_string(row["total"])}
            for row in category_rows
        ],
    })


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
    return web.json_response(schemas.operation_json(operation), status=201)


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


async def categories(_: web.Request) -> web.Response:
    return web.json_response({
        "expense": list(EXPENSE_CATEGORIES),
        "income": list(INCOME_CATEGORIES),
    })


def _budget_json(report: dict) -> dict:
    result = {
        "configured": report["configured"],
        "week_start": report["week_start"].isoformat(),
        "week_end": report["week_end"].isoformat(),
        "is_current": report["is_current"],
        "previous_week_start": (
            report["previous_week_start"].isoformat()
            if report.get("previous_week_start") else None
        ),
        "next_week_start": (
            report["next_week_start"].isoformat()
            if report.get("next_week_start") else None
        ),
    }
    if not report["configured"]:
        return result
    result.update({
        "selected_spent": schemas.money_string(report["selected_spent"]),
        "category_limits_total": schemas.money_string(
            report["category_limits_total"]
        ),
        "overall": (
            {
                "limit": schemas.money_string(report["overall"]["limit"]),
                "spent": schemas.money_string(report["overall"]["spent"]),
                "remaining": schemas.money_string(
                    report["overall"]["remaining"]
                ),
                "percent": schemas.money_string(report["overall"]["percent"]),
                "status": report["overall"]["status"],
            }
            if report.get("overall") is not None else None
        ),
        "categories": [
            {
                "category": item["category"],
                "limit": (
                    schemas.money_string(item["limit"])
                    if item["limit"] is not None else None
                ),
                "spent": schemas.money_string(item["spent"]),
                "remaining": (
                    schemas.money_string(item["remaining"])
                    if item["remaining"] is not None else None
                ),
                "percent": (
                    schemas.money_string(item["percent"])
                    if item["percent"] is not None else None
                ),
                "status": item["status"],
            }
            for item in report["categories"]
        ],
    })
    return result


def _budget_settings_json(settings: dict) -> dict:
    return {
        "overall_limit": (
            schemas.money_string(settings["overall_limit"])
            if settings.get("overall_limit") is not None else None
        ),
        "categories": [
            {
                "category": item["category"],
                "limit": (
                    schemas.money_string(item["limit"])
                    if item["limit"] is not None else None
                ),
            }
            for item in settings.get("categories", [])
        ],
    }


async def budget(request: web.Request) -> web.Response:
    try:
        today = effective_today()
        week_start = (
            schemas.budget_week_start(
                request.query["week_start"], today
            )
            if request.query.get("week_start") else None
        )
        report = await budget_service.get_budget(week_start, today=today)
    except (ValueError, schemas.ValidationError) as exc:
        return _error(str(exc))
    return web.json_response(_budget_json(report))


async def budget_settings(request: web.Request) -> web.Response:
    return web.json_response(_budget_settings_json(
        await budget_service.get_settings()
    ))


async def update_budget_settings(request: web.Request) -> web.Response:
    try:
        fields = schemas.budget_settings(await request.json())
    except schemas.ValidationError as exc:
        return _error(str(exc))
    except (web.HTTPBadRequest, TypeError):
        return _error("некорректный JSON")
    settings = await budget_service.save_settings(
        fields["overall_limit"], fields["categories"], today=effective_today()
    )
    return web.json_response(_budget_settings_json(settings))


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


async def subscriptions(request: web.Request) -> web.Response:
    status = request.query.get("status") or "active"
    if status not in {"active", "cancelled"}:
        return _error("неизвестный статус подписки")
    rows = await queries.list_subscriptions(status)
    if status == "cancelled":
        return web.json_response({
            "items": [
                schemas.subscription_json(row, due=False) for row in rows
            ],
            "monthly_cost": None,
            "yearly_cost": None,
            "month_expenses": None,
            "share_percent": None,
            "upcoming": [],
        })

    today = effective_today()
    due_ids = {row["id"] for row in due_subscriptions(rows, today)}
    month_start, month_end = month_bounds(today)
    month_total = await queries.totals(month_start, min(month_end, today))
    monthly = monthly_cost(rows)
    share = share_of_expenses(monthly, month_total["expense"])
    return web.json_response({
        "items": [
            schemas.subscription_json(row, due=row["id"] in due_ids)
            for row in rows
        ],
        "monthly_cost": schemas.money_string(monthly),
        "yearly_cost": schemas.money_string(yearly_cost(rows)),
        "month_expenses": schemas.money_string(month_total["expense"]),
        "share_percent": f"{share:.1f}" if share is not None else None,
        "upcoming": [
            {
                "subscription_id": charge["subscription_id"],
                "title": charge["title"],
                "amount": schemas.money_string(charge["amount"]),
                "charge_date": charge["charge_date"].isoformat(),
            }
            for charge in upcoming_charges(rows, today)
        ],
    })


async def create_subscription(request: web.Request) -> web.Response:
    try:
        fields = schemas.subscription_create(
            await request.json(), effective_today()
        )
    except schemas.ValidationError as exc:
        return _error(str(exc))
    except (web.HTTPBadRequest, TypeError):
        return _error("некорректный JSON")
    subscription = await queries.insert_subscription(**fields)
    return web.json_response(schemas.subscription_json(subscription), status=201)


async def patch_subscription(request: web.Request) -> web.Response:
    try:
        subscription_id = int(request.match_info["id"])
        current = await queries.get_subscription(subscription_id)
        if current is None:
            return _error("подписка не найдена", 404)
        fields = schemas.subscription_patch(await request.json(), current)
    except (ValueError, schemas.ValidationError) as exc:
        return _error(str(exc))
    except (web.HTTPBadRequest, TypeError):
        return _error("некорректный JSON")
    if (
        fields.get("status") == "active"
        and current.get("status") == "cancelled"
    ):
        next_charge = fields.get("next_charge", current["next_charge"])
        while next_charge <= effective_today():
            next_charge = next_charge_after(next_charge, current["period"])
        fields["next_charge"] = next_charge
    updated = await queries.patch_subscription(subscription_id, fields)
    if updated is None:
        return _error("подписка не найдена", 404)
    return web.json_response(schemas.subscription_json(updated))


async def delete_subscription(request: web.Request) -> web.Response:
    try:
        subscription_id = int(request.match_info["id"])
    except ValueError:
        return _error("некорректный id")
    cancelled = await queries.cancel_subscription(subscription_id)
    if cancelled is None:
        return _error("подписка не найдена", 404)
    return web.json_response(schemas.subscription_json(cancelled))


async def charge_subscription(request: web.Request) -> web.Response:
    try:
        subscription_id = int(request.match_info["id"])
        fields = schemas.charge_request(await request.json())
    except (ValueError, schemas.ValidationError) as exc:
        return _error(str(exc))
    except (web.HTTPBadRequest, TypeError):
        return _error("некорректный JSON")

    result = await queries.charge_subscription(
        subscription_id,
        confirmed=fields["confirmed"],
        op_date=fields["op_date"],
    )
    if result is None:
        return _error("подписка не найдена", 404)
    if result.get("operation_created"):
        await budget_service.notify_after_new_expense(
            request.app.get(BUDGET_BOT_KEY), result["operation_date"]
        )
    return web.json_response({
        "subscription": schemas.subscription_json(
            result["subscription"], due=False
        ),
        "operation_id": result["operation_id"],
    })


def setup_routes(app: web.Application) -> None:
    app.router.add_get("/api/summary", summary)
    app.router.add_get("/api/budget", budget)
    app.router.add_get("/api/budget/settings", budget_settings)
    app.router.add_put("/api/budget/settings", update_budget_settings)
    app.router.add_get("/api/operations", operations)
    app.router.add_post("/api/operations", create_operation)
    app.router.add_patch("/api/operations/{id}", patch_operation)
    app.router.add_post("/api/operations/{id}/confirm", confirm_operation)
    app.router.add_delete("/api/operations/{id}", delete_operation)
    app.router.add_post("/api/operations/{id}/restore", restore_operation)
    app.router.add_get("/api/crypto", crypto)
    app.router.add_post("/api/crypto/transactions", create_crypto_transaction)
    app.router.add_get("/api/crypto/overview", crypto_overview_visibility)
    app.router.add_patch("/api/crypto/overview", update_crypto_overview_visibility)
    app.router.add_patch("/api/crypto/holdings/{asset}", patch_crypto_holding)
    app.router.add_delete("/api/crypto/transactions/{id}", delete_crypto_transaction)
    app.router.add_get("/api/categories", categories)
    app.router.add_get("/api/balance", cash_balance)
    app.router.add_patch("/api/balance", update_cash_balance)
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
    app.router.add_get("/api/subscriptions", subscriptions)
    app.router.add_post("/api/subscriptions", create_subscription)
    app.router.add_patch("/api/subscriptions/{id}", patch_subscription)
    app.router.add_delete("/api/subscriptions/{id}", delete_subscription)
    app.router.add_post("/api/subscriptions/{id}/charge", charge_subscription)
