"""Общие константы и помощники запросов к БД.

Выделено из ``queries.py`` при разбиении oversized-модуля; код перенесён без
изменений.
"""

from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Mapping

CENTS = Decimal("100")
TWO_PLACES = Decimal("0.01")

MONEY_COLUMNS = {
    "amount",
    "principal_amount",
    "interest_amount",
    "principal",
    "balance",
    "min_payment",
    "next_payment_amount",
    "total",
    "expense",
    "income",
    "transfer_in",
    "transfer_out",
    "rub_amount",
    "overall_limit",
    "weekly_limit",
    "spent",
}
RATE_COLUMNS = {"rate"}
DATE_COLUMNS = {
    "op_date", "pay_date", "due_date", "opened_at", "next_payment_date",
    "anchor_date", "next_charge", "week_start", "week_end",
}
TS_COLUMNS = {"created_at", "deleted_at", "updated_at"}
BOOL_COLUMNS = {"needs_review", "archived"}
DECIMAL_TEXT_COLUMNS = {"quantity", "quantity_delta"}


def to_cents(value: Decimal | int) -> int:
    return int(
        (Decimal(value) * CENTS).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    )


def from_cents(value: int | None) -> Decimal | None:
    if value is None:
        return None
    return (Decimal(value) / CENTS).quantize(TWO_PLACES)


def _row(row: Mapping[str, object]) -> dict:
    result = dict(row)
    for column, value in result.items():
        if value is None:
            continue
        if column in MONEY_COLUMNS or column in RATE_COLUMNS:
            if not isinstance(value, Decimal):
                result[column] = from_cents(int(value))
        elif column in DATE_COLUMNS:
            if not isinstance(value, date):
                result[column] = date.fromisoformat(str(value))
        elif column in TS_COLUMNS:
            if not isinstance(value, datetime):
                result[column] = datetime.fromisoformat(str(value))
        elif column in BOOL_COLUMNS:
            result[column] = bool(value)
        elif column in DECIMAL_TEXT_COLUMNS:
            result[column] = Decimal(str(value))
    return result


def _rows(rows: list[dict]) -> list[dict]:
    return [_row(row) for row in rows]


def _date_value(value: date | None) -> str | None:
    return value.isoformat() if value is not None else None


def _ts_value(value: datetime) -> str:
    """Строка того же формата, что и `created_at` в схеме — иначе сравнение
    строк в SQLite поедет: UTC, секундная точность, оффсет `+00:00`."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _period_clause(
    start: date, end: date, start_ts: datetime | None = None
) -> tuple[str, tuple[str, ...]]:
    """Граница периода по дате или по точному моменту якоря.

    Для даты якоря учитываем только операции, созданные после обновления
    баланса. На остальных датах достаточно обычного верхнего ограничения.
    """
    if start_ts is None:
        return "op_date BETWEEN ? AND ?", (start.isoformat(), end.isoformat())
    anchor = start.isoformat()
    return (
        "(op_date > ? OR (op_date = ? AND created_at > ?)) AND op_date <= ?",
        (anchor, anchor, _ts_value(start_ts), end.isoformat()),
    )


def _db_value(column: str, value: object) -> object:
    if value is None:
        return None
    if column in MONEY_COLUMNS or column in RATE_COLUMNS:
        return to_cents(value)  # type: ignore[arg-type]
    if column in DATE_COLUMNS:
        return value.isoformat()  # type: ignore[union-attr]
    if column in TS_COLUMNS:
        return value.isoformat()  # type: ignore[union-attr]
    if column in BOOL_COLUMNS:
        return int(bool(value))
    return value


def _pending_json_default(value: object) -> str:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError(f"Значение {type(value).__name__} нельзя сохранить в JSON")
