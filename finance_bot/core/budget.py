"""Чистые расчёты недельного бюджета."""

from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

MONEY_QUANTUM = Decimal("0.01")


def week_bounds(anchor: date) -> tuple[date, date]:
    """Понедельник и воскресенье календарной недели anchor."""
    start = anchor - timedelta(days=anchor.weekday())
    return start, start + timedelta(days=6)


def budget_percent(spent: Decimal, limit: Decimal) -> Decimal:
    """Процент освоения лимита с точностью до сотых."""
    if limit <= 0:
        raise ValueError("лимит должен быть больше нуля")
    return (spent * Decimal("100") / limit).quantize(
        MONEY_QUANTUM, rounding=ROUND_HALF_UP
    )


def budget_status(percent: Decimal) -> str:
    if percent >= Decimal("100"):
        return "exceeded"
    if percent >= Decimal("80"):
        return "warning"
    return "ok"


def budget_status_for_values(spent: Decimal, limit: Decimal) -> str:
    """Статус по точной сумме, без округления отображаемого процента."""
    if spent >= limit:
        return "exceeded"
    if spent * Decimal("100") >= limit * Decimal("80"):
        return "warning"
    return "ok"


def threshold_reached(
    spent: Decimal, limit: Decimal, threshold_percent: Decimal
) -> bool:
    return spent * Decimal("100") >= limit * threshold_percent


def budget_remaining(limit: Decimal, spent: Decimal) -> Decimal:
    return (limit - spent).quantize(MONEY_QUANTUM)


def budget_line(
    category: str,
    limit: Decimal | None,
    spent: Decimal,
) -> dict:
    if limit is None:
        return {
            "category": category,
            "limit": None,
            "spent": spent,
            "remaining": None,
            "percent": None,
            "status": None,
        }

    percent = budget_percent(spent, limit)
    return {
        "category": category,
        "limit": limit,
        "spent": spent,
        "remaining": budget_remaining(limit, spent),
        "percent": percent,
        "status": budget_status_for_values(spent, limit),
    }


def overall_line(limit: Decimal | None, spent: Decimal) -> dict | None:
    if limit is None:
        return None
    percent = budget_percent(spent, limit)
    return {
        "limit": limit,
        "spent": spent,
        "remaining": budget_remaining(limit, spent),
        "percent": percent,
        "status": budget_status_for_values(spent, limit),
    }
