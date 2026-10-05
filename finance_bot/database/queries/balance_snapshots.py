"""Дневные снимки «денег на руках» (spec 06)."""

from datetime import date

from finance_bot.database.connection import get_pool

from ._common import _row, _rows, to_cents


async def upsert_balance_snapshot(snapshot_date: date, amount) -> dict | None:
    """Сохраняет снимок дня; повторный запуск обновляет запись, не дублирует."""
    row = await get_pool().fetchrow(
        """
        INSERT INTO balance_snapshots (snapshot_date, amount)
        VALUES (?, ?)
        ON CONFLICT (snapshot_date) DO UPDATE SET
          amount = excluded.amount,
          created_at = strftime('%Y-%m-%dT%H:%M:%S+00:00','now')
        RETURNING snapshot_date, amount, created_at
        """,
        snapshot_date.isoformat(),
        to_cents(amount),
    )
    return _row(row) if row else None


async def list_balance_snapshots(start: date, end: date) -> list[dict]:
    rows = await get_pool().fetch(
        """
        SELECT snapshot_date, amount FROM balance_snapshots
        WHERE snapshot_date BETWEEN ? AND ?
        ORDER BY snapshot_date
        """,
        start.isoformat(),
        end.isoformat(),
    )
    return _rows(rows)


async def latest_balance_snapshot() -> dict | None:
    row = await get_pool().fetchrow(
        "SELECT snapshot_date, amount FROM balance_snapshots "
        "ORDER BY snapshot_date DESC LIMIT 1"
    )
    return _row(row) if row else None
