"""Аналитика: сравнение категорий по месяцам (spec 06)."""

from decimal import Decimal

from aiohttp import web

from finance_bot.api import schemas
from finance_bot.core.analytics import comparison_periods, parse_month
from finance_bot.core.dates import effective_today
from finance_bot.database import queries

from ._common import _error


async def category_comparison(request: web.Request) -> web.Response:
    month = request.query.get("month") or effective_today().strftime("%Y-%m")
    try:
        start, end = parse_month(month)
    except ValueError as exc:
        return _error(str(exc))

    today = effective_today()
    cur_start, cur_end, prev_start, prev_end = comparison_periods(
        start, end, today
    )
    current_rows = await queries.expenses_by_category(cur_start, cur_end)
    previous_rows = await queries.expenses_by_category(prev_start, prev_end)
    current = {row["category"]: row["total"] for row in current_rows}
    previous = {row["category"]: row["total"] for row in previous_rows}

    categories = []
    for name in set(current) | set(previous):
        current_total = current.get(name, Decimal("0.00"))
        previous_total = previous.get(name, Decimal("0.00"))
        change = current_total - previous_total
        percent = (
            (change / previous_total * Decimal("100")).quantize(Decimal("0.1"))
            if previous_total > 0 else None
        )
        categories.append({
            "category": name,
            "current": schemas.money_string(current_total),
            "previous": schemas.money_string(previous_total),
            "change": schemas.money_string(change),
            "percent": f"{percent:.1f}" if percent is not None else None,
            "appeared": previous_total == 0 and current_total > 0,
        })
    categories.sort(key=lambda item: Decimal(item["current"]), reverse=True)

    return web.json_response({
        "month": month,
        "period_start": cur_start.isoformat(),
        "period_end": cur_end.isoformat(),
        "previous_start": prev_start.isoformat(),
        "previous_end": prev_end.isoformat(),
        "categories": categories,
    })


def register(app: web.Application) -> None:
    app.router.add_get("/api/analytics/categories", category_comparison)
