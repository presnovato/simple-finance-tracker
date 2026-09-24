"""Подписки.

Выделено из ``queries.py`` при разбиении oversized-модуля; код перенесён без
изменений.
"""

from datetime import date
from decimal import Decimal

from finance_bot.core.subscriptions import next_charge_after
from finance_bot.database.connection import get_pool

from ._common import _db_value, _row, _rows, to_cents

# --- подписки -------------------------------------------------------------

async def list_subscriptions(
    status: str | None = "active", next_charge: date | None = None
) -> list[dict]:
    conditions: list[str] = []
    args: list[object] = []
    if status is not None:
        conditions.append("status = ?")
        args.append(status)
    if next_charge is not None:
        conditions.append("next_charge = ?")
        args.append(next_charge.isoformat())
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    rows = await get_pool().fetch(
        f"""
        SELECT * FROM subscriptions
        {where}
        ORDER BY next_charge, id
        """,
        *args,
    )
    return _rows(rows)


async def get_subscription(subscription_id: int) -> dict | None:
    row = await get_pool().fetchrow(
        "SELECT * FROM subscriptions WHERE id = ?", subscription_id
    )
    return _row(row) if row else None


async def insert_subscription(
    *,
    title: str,
    amount: Decimal,
    period: str,
    next_charge: date,
    category: str | None,
    comment: str | None,
) -> dict:
    row = await get_pool().fetchrow(
        """
        INSERT INTO subscriptions (
          title, amount, period, next_charge, category, comment
        )
        VALUES (?, ?, ?, ?, ?, ?)
        RETURNING *
        """,
        title,
        to_cents(amount),
        period,
        next_charge.isoformat(),
        category,
        comment,
    )
    if row is None:
        raise RuntimeError("SQLite не вернул добавленную подписку")
    return _row(row)


async def patch_subscription(
    subscription_id: int, fields: dict
) -> dict | None:
    allowed = {
        "title", "amount", "period", "next_charge", "category", "comment", "status",
    }
    updates = {key: value for key, value in fields.items() if key in allowed}
    if not updates:
        return await get_subscription(subscription_id)
    columns = ", ".join(f"{key} = ?" for key in updates)
    values = [_db_value(key, value) for key, value in updates.items()]
    row = await get_pool().fetchrow(
        f"UPDATE subscriptions SET {columns} WHERE id = ? RETURNING *",
        *values,
        subscription_id,
    )
    return _row(row) if row else None


async def cancel_subscription(subscription_id: int) -> dict | None:
    row = await get_pool().fetchrow(
        """
        UPDATE subscriptions SET status = 'cancelled'
        WHERE id = ? AND status != 'cancelled'
        RETURNING *
        """,
        subscription_id,
    )
    return _row(row) if row else None


async def charge_subscription(
    subscription_id: int,
    *,
    confirmed: bool,
    op_date: date | None = None,
    expected_next_charge: date | None = None,
) -> dict | None:
    """Подтверждает или пропускает списание атомарно вместе со сдвигом даты.

    При переданном `expected_next_charge` результат с `stale=True` означает,
    что callback пришёл из старого вечернего сообщения и ничего не меняет.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            raw = await conn.fetchrow(
                "SELECT * FROM subscriptions WHERE id = ? AND status = 'active'",
                subscription_id,
            )
            if raw is None:
                return None

            subscription = _row(raw)
            current_next_charge = subscription["next_charge"]
            if (
                expected_next_charge is not None
                and current_next_charge != expected_next_charge
            ):
                return {
                    "subscription": subscription,
                    "operation_id": None,
                    "operation_date": None,
                    "operation_created": False,
                    "stale": True,
                }

            charge_date = op_date or current_next_charge
            operation_id: int | None = None
            operation_created = False
            if confirmed:
                duplicate = await conn.fetchrow(
                    """
                    SELECT id FROM operations
                    WHERE subscription_id = ? AND op_date = ?
                      AND deleted_at IS NULL
                    ORDER BY id DESC LIMIT 1
                    """,
                    subscription_id,
                    charge_date.isoformat(),
                )
                if duplicate is not None:
                    operation_id = duplicate["id"]
                else:
                    operation = await conn.fetchrow(
                        """
                        INSERT INTO operations (
                          op_date, type, amount, category, comment, account,
                          transfer_direction, source, needs_review, subscription_id
                        )
                        VALUES (?, 'расход', ?, 'Подписки', ?, NULL, NULL,
                                'бот-подписка', 0, ?)
                        RETURNING id
                        """,
                        charge_date.isoformat(),
                        to_cents(subscription["amount"]),
                        subscription["title"],
                        subscription_id,
                    )
                    if operation is None:
                        raise RuntimeError("SQLite не вернул id операции подписки")
                    operation_id = operation["id"]
                    operation_created = True

            new_next_charge = current_next_charge
            if current_next_charge <= charge_date:
                new_next_charge = next_charge_after(
                    current_next_charge, subscription["period"]
                )

            if new_next_charge != current_next_charge:
                updated = await conn.fetchrow(
                    """
                    UPDATE subscriptions
                    SET next_charge = ?
                    WHERE id = ? AND next_charge = ? AND status = 'active'
                    RETURNING *
                    """,
                    new_next_charge.isoformat(),
                    subscription_id,
                    current_next_charge.isoformat(),
                )
                if updated is None:
                    raise RuntimeError("SQLite не вернул обновлённую подписку")
                subscription = _row(updated)

            return {
                "subscription": subscription,
                "operation_id": operation_id,
                "operation_date": charge_date if operation_created else None,
                "operation_created": operation_created,
                "stale": False,
            }
