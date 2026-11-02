"""Личные долги.

Выделено из ``queries.py`` при разбиении oversized-модуля; код перенесён без
изменений.
"""

from datetime import date
from decimal import Decimal

from finance_bot.database.connection import get_pool

from ._common import _date_value, _db_value, _row, _rows, to_cents
from .debts import DebtPaymentError

# --- личные долги ---------------------------------------------------------

async def list_personal_debts(
    status: str | None = None, *, archived: bool = False
) -> list[dict]:
    conditions = ["d.archived = ?"]
    args: list[object] = [int(archived)]
    if status:
        conditions.append("d.status = ?")
        args.append(status)
    rows = await get_pool().fetch(
        f"""
        SELECT d.*,
               (SELECT count(*) FROM personal_debt_payments p
                WHERE p.personal_debt_id = d.id) AS payment_count
        FROM personal_debts d
        WHERE {' AND '.join(conditions)}
        ORDER BY (d.status = 'open') DESC, d.due_date NULLS LAST,
                 d.opened_at, d.id
        """,
        *args,
    )
    return _rows(rows)


async def get_personal_debt(personal_debt_id: int) -> dict | None:
    row = await get_pool().fetchrow(
        """
        SELECT d.*,
               (SELECT count(*) FROM personal_debt_payments p
                WHERE p.personal_debt_id = d.id) AS payment_count
        FROM personal_debts d WHERE d.id = ?
        """,
        personal_debt_id,
    )
    return _row(row) if row else None


async def set_personal_debt_archived(
    personal_debt_id: int, archived: bool
) -> dict | None:
    row = await get_pool().fetchrow(
        "UPDATE personal_debts SET archived = ? WHERE id = ? RETURNING *",
        int(archived), personal_debt_id,
    )
    return _row(row) if row else None


async def delete_personal_debt(personal_debt_id: int) -> bool:
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "SELECT COUNT(*) AS count FROM personal_debt_payments "
                "WHERE personal_debt_id = ?",
                personal_debt_id,
            )
            if row is None or row["count"]:
                return False
            deleted = await conn.fetchrow(
                "DELETE FROM personal_debts WHERE id = ? RETURNING id",
                personal_debt_id,
            )
            return deleted is not None


async def insert_personal_debt(
    *,
    person: str,
    direction: str,
    principal: Decimal,
    opened_at: date,
    due_date: date | None,
    comment: str | None,
    operation_id: int | None,
) -> dict:
    principal_cents = to_cents(principal)
    row = await get_pool().fetchrow(
        """
        INSERT INTO personal_debts (
          person, direction, principal, balance, opened_at, due_date,
          comment, operation_id
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        RETURNING *
        """,
        person,
        direction,
        principal_cents,
        principal_cents,
        opened_at.isoformat(),
        _date_value(due_date),
        comment,
        operation_id,
    )
    if row is None:
        raise RuntimeError("SQLite не вернул добавленный личный долг")
    return _row(row)


async def patch_personal_debt(
    personal_debt_id: int, fields: dict
) -> dict | None:
    allowed = {
        "person",
        "direction",
        "principal",
        "balance",
        "opened_at",
        "due_date",
        "comment",
        "status",
    }
    updates = {key: value for key, value in fields.items() if key in allowed}
    if not updates:
        return await get_personal_debt(personal_debt_id)
    if "balance" in updates and "status" not in updates:
        updates["status"] = "closed" if updates["balance"] <= 0 else "open"
    columns = ", ".join(f"{key} = ?" for key in updates)
    values = [_db_value(key, value) for key, value in updates.items()]
    row = await get_pool().fetchrow(
        f"UPDATE personal_debts SET {columns} WHERE id = ? RETURNING *",
        *values,
        personal_debt_id,
    )
    return _row(row) if row else None


async def personal_debt_history(personal_debt_id: int) -> list[dict]:
    rows = await get_pool().fetch(
        """
        SELECT id, personal_debt_id, operation_id, pay_date, amount,
               'payment' AS kind, cash_effect
        FROM personal_debt_payments
        WHERE personal_debt_id = ?
        ORDER BY pay_date DESC, id DESC
        """,
        personal_debt_id,
    )
    return _rows(rows)


async def record_personal_debt_payment(
    personal_debt_id: int,
    operation_id: int,
    pay_date: date,
    amount: Decimal,
) -> dict | None:
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            duplicate = await conn.fetchrow(
                """
                SELECT personal_debt_id FROM personal_debt_payments
                WHERE operation_id = ?
                """,
                operation_id,
            )
            if duplicate:
                row = await conn.fetchrow(
                    "SELECT * FROM personal_debts WHERE id = ?",
                    duplicate["personal_debt_id"],
                )
                return _row(row) if row else None
            debt_raw = await conn.fetchrow(
                "SELECT * FROM personal_debts WHERE id = ?",
                personal_debt_id,
            )
            if debt_raw is None:
                return None
            debt = _row(debt_raw)
            if debt["archived"]:
                raise DebtPaymentError("архивный долг нельзя оплачивать")
            if debt["status"] != "open":
                raise DebtPaymentError("закрытый долг нельзя оплачивать")
            if amount <= 0:
                raise DebtPaymentError("сумма платежа должна быть больше нуля")
            if amount > debt["balance"]:
                raise DebtPaymentError("платёж не может быть больше остатка")
            new_balance = debt["balance"] - amount
            await conn.execute(
                """
                INSERT INTO personal_debt_payments (
                  personal_debt_id, operation_id, pay_date, amount
                ) VALUES (?, ?, ?, ?)
                """,
                personal_debt_id,
                operation_id,
                pay_date.isoformat(),
                to_cents(amount),
            )
            balance_cents = to_cents(new_balance)
            row = await conn.fetchrow(
                """
                UPDATE personal_debts
                SET balance = ?,
                    status = CASE WHEN ? <= 0 THEN 'closed' ELSE 'open' END
                WHERE id = ?
                RETURNING *
                """,
                balance_cents,
                balance_cents,
                personal_debt_id,
            )
            if row is None:
                raise RuntimeError("SQLite не вернул обновлённый личный долг")
            return _row(row)


async def create_personal_debt_payment(
    personal_debt_id: int,
    pay_date: date,
    amount: Decimal,
    idempotency_key: str | None = None,
    cash_effect: str = "movement",
) -> dict | None:
    """Атомарно записывает возврат и при необходимости создаёт перевод."""
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            if idempotency_key:
                duplicate = await conn.fetchrow(
                    """
                    SELECT personal_debt_id FROM personal_debt_payments
                    WHERE idempotency_key = ?
                    """,
                    idempotency_key,
                )
                if duplicate:
                    row = await conn.fetchrow(
                        "SELECT * FROM personal_debts WHERE id = ?",
                        duplicate["personal_debt_id"],
                    )
                    return _row(row) if row else None
            debt_raw = await conn.fetchrow(
                "SELECT * FROM personal_debts WHERE id = ?", personal_debt_id
            )
            if debt_raw is None:
                return None
            debt = _row(debt_raw)
            if debt["archived"]:
                raise DebtPaymentError("архивный долг нельзя оплачивать")
            if debt["status"] != "open":
                raise DebtPaymentError("закрытый долг нельзя оплачивать")
            if amount <= 0:
                raise DebtPaymentError("сумма платежа должна быть больше нуля")
            if amount > debt["balance"]:
                raise DebtPaymentError("платёж не может быть больше остатка")
            if cash_effect not in {"movement", "already_in_balance"}:
                raise DebtPaymentError("неизвестный денежный эффект платежа")
            operation_id = None
            if cash_effect == "movement":
                direction = "in" if debt["direction"] == "owed_to_me" else "out"
                operation = await conn.fetchrow(
                    """
                    INSERT INTO operations (
                      op_date, type, amount, comment, transfer_direction,
                      source, needs_review
                    ) VALUES (?, 'перевод', ?, ?, ?, 'tma-долг', 0)
                    RETURNING id
                    """,
                    pay_date.isoformat(),
                    to_cents(amount),
                    f"Возврат долга: {debt['person']}",
                    direction,
                )
                if operation is None:
                    raise RuntimeError("SQLite не вернул id операции по личному долгу")
                operation_id = operation["id"]
            await conn.execute(
                """
                INSERT INTO personal_debt_payments (
                  personal_debt_id, operation_id, pay_date, amount,
                  cash_effect, idempotency_key
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                personal_debt_id,
                operation_id,
                pay_date.isoformat(),
                to_cents(amount),
                cash_effect,
                idempotency_key,
            )
            new_balance = debt["balance"] - amount
            row = await conn.fetchrow(
                """
                UPDATE personal_debts
                SET balance = ?,
                    status = CASE WHEN ? <= 0 THEN 'closed' ELSE 'open' END
                WHERE id = ?
                RETURNING *
                """,
                to_cents(new_balance),
                to_cents(new_balance),
                personal_debt_id,
            )
            if row is None:
                raise RuntimeError("SQLite не вернул обновлённый личный долг")
            return _row(row)
