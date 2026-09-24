"""Сводка за период."""

from decimal import Decimal

from aiohttp import web

from finance_bot.api import schemas
from finance_bot.core.analytics import (
    average_daily,
    daily_series,
    parse_month,
    rolling_chart_bounds,
)
from finance_bot.core.balance import calculate_period_balance
from finance_bot.core.dates import effective_today
from finance_bot.database import queries
from finance_bot.services import balance as balance_service

from ._common import _error


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


def register(app: web.Application) -> None:
    app.router.add_get("/api/summary", summary)
