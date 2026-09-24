"""Запросы Telegram Mini App.

Выделено из ``queries.py`` при разбиении oversized-модуля; код перенесён без
изменений.
"""

from datetime import date, datetime, timezone
from decimal import Decimal

from finance_bot.config import (
    RHYTHM_EXPENSE_EXCLUDED_CATEGORIES,
    RHYTHM_INCOME_EXCLUDED_CATEGORIES,
)
from finance_bot.database.connection import get_pool

from ._common import _db_value, _period_clause, _row, _rows, from_cents

# --- Telegram Mini App ---------------------------------------------------

async def _amounts_by_day(
    start: date,
    end: date,
    *,
    type_: str,
    excluded_categories: tuple[str, ...] = (),
    start_ts: datetime | None = None,
) -> list[dict]:
    period_clause, period_args = _period_clause(start, end, start_ts)
    category_clause = ""
    category_args: tuple[str, ...] = ()
    if excluded_categories:
        placeholders = ", ".join("?" for _ in excluded_categories)
        category_clause = (
            f"AND coalesce(category, '') NOT IN ({placeholders})"
        )
        category_args = excluded_categories
    rows = await get_pool().fetch(
        f"""
        SELECT op_date, sum(amount) AS total
        FROM operations
        WHERE type = ? {category_clause} AND {period_clause}
          AND deleted_at IS NULL
        GROUP BY op_date ORDER BY op_date
        """,
        type_, *category_args, *period_args,
    )
    return _rows(rows)


async def expenses_by_day(
    start: date, end: date, *, start_ts: datetime | None = None
) -> list[dict]:
    """Переменные расходы по дням без жилья и долговых платежей."""
    return await _amounts_by_day(
        start,
        end,
        type_="расход",
        excluded_categories=RHYTHM_EXPENSE_EXCLUDED_CATEGORIES,
        start_ts=start_ts,
    )


async def income_by_day(
    start: date, end: date, *, start_ts: datetime | None = None
) -> list[dict]:
    """Доходы по дням без зарплаты."""
    return await _amounts_by_day(
        start,
        end,
        type_="доход",
        excluded_categories=RHYTHM_INCOME_EXCLUDED_CATEGORIES,
        start_ts=start_ts,
    )


async def operations_for_export(
    start: date | None = None, end: date | None = None
) -> list[dict]:
    """Возвращает только активные операции для пользовательского экспорта."""
    conditions = ["deleted_at IS NULL"]
    args: list[object] = []
    if start is not None:
        conditions.append("op_date >= ?")
        args.append(start.isoformat())
    if end is not None:
        conditions.append("op_date <= ?")
        args.append(end.isoformat())
    rows = await get_pool().fetch(
        f"""
        SELECT * FROM operations
        WHERE {' AND '.join(conditions)}
        ORDER BY op_date, id
        """,
        *args,
    )
    return _rows(rows)


async def get_operation(
    op_id: int, *, include_deleted: bool = False
) -> dict | None:
    deleted_clause = "" if include_deleted else "AND deleted_at IS NULL"
    row = await get_pool().fetchrow(
        f"SELECT * FROM operations WHERE id = ? {deleted_clause}", op_id
    )
    return _row(row) if row else None


async def list_operations(
    *,
    before: tuple[date, int] | None = None,
    category: str | None = None,
    type_: str | None = None,
    query: str | None = None,
    needs_review: bool | None = None,
    op_date: date | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = 40,
) -> list[dict]:
    conditions, args = _operation_filter_parts(
        before=before,
        category=category,
        type_=type_,
        query=query,
        needs_review=needs_review,
        op_date=op_date,
        date_from=date_from,
        date_to=date_to,
    )

    args.append(limit)
    limit_param = "?"
    rows = await get_pool().fetch(
        f"""
        SELECT * FROM operations
        WHERE {' AND '.join(conditions)}
        ORDER BY op_date DESC, id DESC
        LIMIT {limit_param}
        """,
        *args,
    )
    return _rows(rows)


def _operation_filter_parts(
    *,
    before: tuple[date, int] | None = None,
    category: str | None = None,
    type_: str | None = None,
    query: str | None = None,
    needs_review: bool | None = None,
    op_date: date | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> tuple[list[str], list[object]]:
    conditions = ["deleted_at IS NULL"]
    args: list[object] = []

    def bind(value: object) -> str:
        args.append(value)
        return "?"

    if before is not None:
        before_date = before[0].isoformat()
        date_before = bind(before_date)
        date_equal = bind(before_date)
        id_before = bind(before[1])
        conditions.append(
            f"(op_date < {date_before} OR "
            f"(op_date = {date_equal} AND id < {id_before}))"
        )
    if category:
        conditions.append(f"coalesce(category, 'Прочее') = {bind(category)}")
    if type_:
        conditions.append(f"type = {bind(type_)}")
    if query:
        conditions.append(
            f"icontains(coalesce(comment, ''), {bind(query)})"
        )
    if needs_review is not None:
        conditions.append(f"needs_review = {bind(int(needs_review))}")
    if op_date is not None:
        conditions.append(f"op_date = {bind(op_date.isoformat())}")
    if date_from is not None:
        conditions.append(f"op_date >= {bind(date_from.isoformat())}")
    if date_to is not None:
        conditions.append(f"op_date <= {bind(date_to.isoformat())}")
    return conditions, args


async def operations_totals(
    *,
    category: str | None = None,
    type_: str | None = None,
    query: str | None = None,
    needs_review: bool | None = None,
    op_date: date | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict:
    conditions, args = _operation_filter_parts(
        category=category,
        type_=type_,
        query=query,
        needs_review=needs_review,
        op_date=op_date,
        date_from=date_from,
        date_to=date_to,
    )
    row = await get_pool().fetchrow(
        f"""
        SELECT
          count(*) AS total_count,
          coalesce(sum(amount) FILTER (WHERE type = 'расход'), 0) AS expense,
          coalesce(sum(amount) FILTER (WHERE type = 'доход'), 0) AS income,
          coalesce(sum(amount) FILTER (WHERE type = 'перевод'), 0) AS transfer
        FROM operations
        WHERE {' AND '.join(conditions)}
        """,
        *args,
    )
    if row is None:
        raise RuntimeError("SQLite не вернул итоги истории")
    return {
        "total_count": int(row["total_count"]),
        "expense": from_cents(int(row["expense"] or 0)) or Decimal("0.00"),
        "income": from_cents(int(row["income"] or 0)) or Decimal("0.00"),
        "transfer": from_cents(int(row["transfer"] or 0)) or Decimal("0.00"),
    }


async def patch_operation(op_id: int, fields: dict) -> dict | None:
    allowed = (
        "op_date",
        "type",
        "amount",
        "category",
        "comment",
        "account",
        "note",
        "transfer_direction",
    )
    updates = {key: value for key, value in fields.items() if key in allowed}
    if not updates:
        return await get_operation(op_id)
    columns = [f"{key} = ?" for key in updates]
    if any(key != "note" for key in updates):
        columns.append("needs_review = 0")
    values = [_db_value(key, value) for key, value in updates.items()]
    row = await get_pool().fetchrow(
        f"""
        UPDATE operations SET {', '.join(columns)}
        WHERE id = ? AND deleted_at IS NULL
        RETURNING *
        """,
        *values,
        op_id,
    )
    return _row(row) if row else None


async def confirm_operation(op_id: int) -> dict | None:
    row = await get_pool().fetchrow(
        """
        UPDATE operations SET needs_review = 0
        WHERE id = ? AND deleted_at IS NULL
        RETURNING *
        """,
        op_id,
    )
    return _row(row) if row else None


async def soft_delete_operation(op_id: int) -> dict | None:
    deleted_at = datetime.now(timezone.utc).isoformat()
    row = await get_pool().fetchrow(
        """
        UPDATE operations SET deleted_at = ?
        WHERE id = ? AND deleted_at IS NULL
        RETURNING *
        """,
        deleted_at,
        op_id,
    )
    return _row(row) if row else None


async def restore_operation(op_id: int) -> dict | None:
    row = await get_pool().fetchrow(
        """
        UPDATE operations SET deleted_at = NULL
        WHERE id = ? AND deleted_at IS NOT NULL
        RETURNING *
        """,
        op_id,
    )
    return _row(row) if row else None
