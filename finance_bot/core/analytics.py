"""Чистые функции для агрегатов Telegram Mini App."""

from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
import re


def parse_month(value: str) -> tuple[date, date]:
    """Преобразует YYYY-MM в границы календарного месяца."""
    if not isinstance(value, str) or re.fullmatch(r"\d{4}-\d{2}", value) is None:
        raise ValueError("month должен быть в формате YYYY-MM")
    try:
        year_text, month_text = value.split("-", 1)
        year, month = int(year_text), int(month_text)
        start = date(year, month, 1)
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("month должен быть в формате YYYY-MM") from exc
    return start, date(year, month, monthrange(year, month)[1])


def daily_series(
    start: date,
    end: date,
    rows: list[dict],
    *,
    value_key: str = "expense",
) -> list[dict[str, date | Decimal]]:
    """Заполняет отсутствующие календарные дни нулевыми суммами."""
    totals = {row["op_date"]: Decimal(row["total"]) for row in rows}
    result = []
    current = start
    while current <= end:
        result.append({"op_date": current, value_key: totals.get(current, Decimal("0"))})
        current += timedelta(days=1)
    return result


def rolling_chart_bounds(
    period_start: date, period_end: date, window_days: int = 31
) -> tuple[date, date]:
    """Возвращает месячное окно для графика внутри текущего периода.

    Пока период короче окна, график начинается с якоря и дополняется будущими
    нулевыми днями. После этого окно сдвигается вместе с текущей датой.
    """
    if window_days <= 0:
        raise ValueError("window_days должен быть положительным")
    last_start = period_end - timedelta(days=window_days - 1)
    start = max(period_start, last_start)
    return start, start + timedelta(days=window_days - 1)


def average_daily(total: Decimal, nonzero_days: int) -> Decimal:
    """Среднее по дням, в которые реально была сумма (нули не учитываются)."""
    if nonzero_days <= 0:
        return Decimal("0.00")
    return (Decimal(total) / nonzero_days).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def average_daily_expense(total: Decimal, nonzero_days: int) -> Decimal:
    """Среднее по дням, в которые реально были траты."""
    return average_daily(total, nonzero_days)
