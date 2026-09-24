"""Сводки по операциям.

Выделено из ``queries.py`` при разбиении oversized-модуля; код перенесён без
изменений.
"""

from datetime import date, datetime

from finance_bot.database.connection import get_pool

from ._common import _period_clause, _row, _rows, _ts_value

# --- сводки ---------------------------------------------------------------

async def day_operations(op_date: date) -> list[dict]:
    rows = await get_pool().fetch(
        """SELECT * FROM operations
           WHERE op_date = ? AND deleted_at IS NULL ORDER BY id""",
        op_date.isoformat(),
    )
    return _rows(rows)


async def pending_review() -> list[dict]:
    rows = await get_pool().fetch(
        """SELECT * FROM operations
           WHERE needs_review AND deleted_at IS NULL ORDER BY id"""
    )
    return _rows(rows)


async def expenses_by_category(
    start: date, end: date, *, start_ts: datetime | None = None
) -> list[dict]:
    """Расходы [start, end] по категориям, по убыванию. Переводы исключены."""
    period_clause, period_args = _period_clause(start, end, start_ts)
    rows = await get_pool().fetch(
        f"""
        SELECT coalesce(category, 'Прочее') AS category, sum(amount) AS total
        FROM operations
        WHERE type = 'расход' AND {period_clause}
          AND deleted_at IS NULL
        GROUP BY 1 ORDER BY total DESC
        """,
        *period_args,
    )
    return _rows(rows)

async def totals(
    start: date, end: date, *, start_ts: datetime | None = None
) -> dict:
    period_clause, period_args = _period_clause(start, end, start_ts)
    row = await get_pool().fetchrow(
        f"""
        SELECT
          coalesce(sum(amount) FILTER (WHERE type = 'расход'), 0) AS expense,
          coalesce(sum(amount) FILTER (WHERE type = 'доход'), 0)  AS income,
          coalesce(sum(amount) FILTER (
            WHERE type = 'перевод' AND transfer_direction = 'in'
          ), 0) AS transfer_in,
          coalesce(sum(amount) FILTER (
            WHERE type = 'перевод'
              AND coalesce(transfer_direction, 'out') = 'out'
          ), 0) AS transfer_out
        FROM operations
        WHERE {period_clause} AND deleted_at IS NULL
          AND NOT (
            type = 'перевод' AND (
              EXISTS (
                SELECT 1 FROM personal_debts d
                WHERE d.operation_id = operations.id
              )
              OR EXISTS (
                SELECT 1 FROM personal_debt_payments p
                WHERE p.operation_id = operations.id
              )
              OR EXISTS (
                SELECT 1 FROM debt_payments k
                WHERE k.operation_id = operations.id
              )
            )
        )
        """,
        *period_args,
    )
    if row is None:
        raise RuntimeError("SQLite не вернул строку итогов")
    return _row(row)


async def totals_since(anchor_date: date, anchor_ts: datetime) -> dict:
    """Движения денег после момента якоря.

    Якорь — момент, а не дата: операции дня якоря, записанные до пересчёта,
    уже входят в названную сумму и повторно вычитаться не должны.
    """
    row = await get_pool().fetchrow(
        """
        SELECT
          coalesce(sum(amount) FILTER (WHERE type = 'расход'), 0) AS expense,
          coalesce(sum(amount) FILTER (WHERE type = 'доход'), 0)  AS income,
          coalesce(sum(amount) FILTER (
            WHERE type = 'перевод' AND transfer_direction = 'in'
          ), 0) AS transfer_in,
          coalesce(sum(amount) FILTER (
            WHERE type = 'перевод'
              AND coalesce(transfer_direction, 'out') = 'out'
          ), 0) AS transfer_out,
          count(*) FILTER (
            WHERE type IN ('расход', 'доход')
               OR (type = 'перевод'
                   AND coalesce(transfer_direction, 'out') IN ('in', 'out'))
          ) AS movement_count
        FROM operations
        WHERE deleted_at IS NULL
          AND (op_date > ? OR (op_date = ? AND created_at > ?))
        """,
        anchor_date.isoformat(),
        anchor_date.isoformat(),
        _ts_value(anchor_ts),
    )
    if row is None:
        raise RuntimeError("SQLite не вернул строку итогов")
    return _row(row)
