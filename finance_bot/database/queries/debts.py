"""Кредиты и рассрочки.

Выделено из ``queries.py`` при разбиении oversized-модуля; код перенесён без
изменений.
"""

from calendar import monthrange
from datetime import date
from decimal import Decimal

from finance_bot.database.connection import get_pool

from ._common import _date_value, _db_value, _row, _rows, from_cents, to_cents

def _advance_month(value: date, payment_day: int | None = None) -> date:
    """Сдвигает ежемесячную дату, не ломаясь на коротких месяцах."""
    month_index = value.year * 12 + value.month
    year, month_zero = divmod(month_index, 12)
    month = month_zero + 1
    day = payment_day or value.day
    return date(year, month, min(day, monthrange(year, month)[1]))


def _next_payment_after(
    debt: dict, payment_type: str,
) -> date | None:
    scheduled = debt.get("next_payment_date")
    if payment_type != "regular" or scheduled is None:
        return scheduled
    return _advance_month(scheduled, debt.get("payment_day"))


class DebtPaymentError(ValueError):
    """Ошибка бизнес-правил при внесении платежа по долгу."""

# --- кредиты --------------------------------------------------------------

async def list_debts(
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
               (SELECT count(*) FROM debt_payments p
                WHERE p.debt_id = d.id AND p.kind = 'payment') AS payment_count
        FROM debts d
        WHERE {' AND '.join(conditions)}
        ORDER BY (d.status = 'active') DESC, d.priority NULLS LAST, d.id
        """,
        *args,
    )
    return _rows(rows)


async def get_debt(debt_id: int) -> dict | None:
    row = await get_pool().fetchrow(
        """
        SELECT d.*,
               (SELECT count(*) FROM debt_payments p
                WHERE p.debt_id = d.id AND p.kind = 'payment') AS payment_count
        FROM debts d WHERE d.id = ?
        """,
        debt_id,
    )
    return _row(row) if row else None


async def set_debt_archived(debt_id: int, archived: bool) -> dict | None:
    row = await get_pool().fetchrow(
        "UPDATE debts SET archived = ? WHERE id = ? RETURNING *",
        int(archived), debt_id,
    )
    return _row(row) if row else None


async def delete_debt(debt_id: int) -> bool:
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "SELECT COUNT(*) AS count FROM debt_payments WHERE debt_id = ?",
                debt_id,
            )
            if row is None or row["count"]:
                return False
            deleted = await conn.fetchrow(
                "DELETE FROM debts WHERE id = ? RETURNING id", debt_id
            )
            return deleted is not None


async def insert_debt(
    *,
    creditor: str,
    principal: Decimal,
    rate: Decimal | None,
    min_payment: Decimal | None,
    priority: int | None,
    due_date: date | None,
    loan_name: str | None = None,
    contract_ref: str | None = None,
    opened_at: date | None = None,
    next_payment_amount: Decimal | None = None,
    next_payment_date: date | None = None,
) -> dict:
    principal_cents = to_cents(principal)
    planned_payment = (
        next_payment_amount if next_payment_amount is not None else min_payment
    )
    row = await get_pool().fetchrow(
        """
        INSERT INTO debts (
          creditor, loan_name, contract_ref, principal, balance, rate,
          min_payment, next_payment_amount, opened_at, next_payment_date,
          payment_day, priority, due_date
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        RETURNING *
        """,
        creditor,
        loan_name,
        contract_ref,
        principal_cents,
        principal_cents,
        to_cents(rate) if rate is not None else None,
        to_cents(min_payment) if min_payment is not None else None,
        to_cents(planned_payment) if planned_payment is not None else None,
        _date_value(opened_at),
        _date_value(next_payment_date),
        next_payment_date.day if next_payment_date is not None else None,
        priority,
        _date_value(due_date),
    )
    if row is None:
        raise RuntimeError("SQLite не вернул добавленный кредит")
    return _row(row)


async def patch_debt(debt_id: int, fields: dict) -> dict | None:
    allowed = {
        "creditor",
        "loan_name",
        "contract_ref",
        "principal",
        "rate",
        "min_payment",
        "next_payment_amount",
        "opened_at",
        "next_payment_date",
        "priority",
        "due_date",
        "status",
    }
    updates = {key: value for key, value in fields.items() if key in allowed}
    if not updates:
        return await get_debt(debt_id)
    if "next_payment_date" in updates:
        next_date = updates["next_payment_date"]
        updates["payment_day"] = next_date.day if next_date is not None else None
    columns = ", ".join(f"{key} = ?" for key in updates)
    values = [_db_value(key, value) for key, value in updates.items()]
    row = await get_pool().fetchrow(
        f"UPDATE debts SET {columns} WHERE id = ? RETURNING *",
        *values,
        debt_id,
    )
    return _row(row) if row else None


async def debt_payment_history(
    debt_id: int, *, limit: int | None = None
) -> list[dict]:
    limit_clause = "LIMIT ?" if limit is not None else ""
    args = (debt_id, limit) if limit is not None else (debt_id,)
    rows = await get_pool().fetch(
        f"""
        SELECT * FROM debt_payments
        WHERE debt_id = ? AND kind = 'payment'
        ORDER BY pay_date DESC, id DESC {limit_clause}
        """,
        *args,
    )
    return _rows(rows)


async def debt_history(debt_id: int) -> list[dict]:
    rows = await get_pool().fetch(
        """
        SELECT id, debt_id, operation_id, pay_date, amount, principal_amount,
               CASE WHEN kind = 'payment' AND principal_amount IS NOT NULL
                    THEN amount - principal_amount END AS interest_amount,
               kind,
               payment_type, cash_effect, reason
        FROM debt_payments
        WHERE debt_id = ?
        ORDER BY pay_date DESC, id DESC
        """,
        debt_id,
    )
    return _rows(rows)


async def list_debt_payments() -> list[dict]:
    rows = await get_pool().fetch(
        """
        SELECT p.* FROM debt_payments p
        JOIN debts d ON d.id = p.debt_id
        WHERE p.kind = 'payment' AND d.archived = 0
        ORDER BY p.pay_date, p.id
        """
    )
    return _rows(rows)


async def record_debt_payment(
    debt_id: int,
    operation_id: int,
    pay_date: date,
    amount: Decimal,
    payment_type: str = "regular",
    principal_amount: Decimal | None = None,
) -> dict | None:
    """Идемпотентно привязывает операцию и применяет известную часть к телу."""
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            duplicate = await conn.fetchrow(
                "SELECT debt_id FROM debt_payments WHERE operation_id = ?",
                operation_id,
            )
            if duplicate:
                row = await conn.fetchrow(
                    "SELECT * FROM debts WHERE id = ?", duplicate["debt_id"]
                )
                return _row(row) if row else None
            debt_raw = await conn.fetchrow(
                "SELECT * FROM debts WHERE id = ?", debt_id
            )
            if debt_raw is None:
                return None
            debt = _row(debt_raw)
            if debt["archived"]:
                raise DebtPaymentError("архивный долг нельзя оплачивать")
            if debt["status"] != "active":
                raise DebtPaymentError("закрытый долг нельзя оплачивать")
            if amount <= 0:
                raise DebtPaymentError("сумма платежа должна быть больше нуля")
            if payment_type not in {"regular", "early"}:
                raise DebtPaymentError("неизвестный тип платежа")
            if principal_amount is not None:
                if principal_amount < 0 or principal_amount > amount:
                    raise DebtPaymentError(
                        "часть платежа в тело должна быть от 0 до суммы платежа"
                    )
                if principal_amount > debt["balance"]:
                    raise DebtPaymentError(
                        "часть платежа в тело не может быть больше остатка"
                    )
            applied_principal = (
                principal_amount if principal_amount is not None else Decimal("0")
            )
            new_balance = debt["balance"] - applied_principal
            next_payment_date = _next_payment_after(debt, payment_type)
            await conn.execute(
                """
                INSERT INTO debt_payments (
                  debt_id, operation_id, pay_date, amount, principal_amount,
                  kind, payment_type
                ) VALUES (?, ?, ?, ?, ?, 'payment', ?)
                """,
                debt_id,
                operation_id,
                pay_date.isoformat(),
                to_cents(amount),
                to_cents(principal_amount) if principal_amount is not None else None,
                payment_type,
            )
            balance_cents = to_cents(new_balance)
            row = await conn.fetchrow(
                """
                UPDATE debts
                SET balance = ?,
                    next_payment_date = ?,
                    status = CASE WHEN ? <= 0 THEN 'closed' ELSE 'active' END
                WHERE id = ?
                RETURNING *
                """,
                balance_cents,
                _date_value(next_payment_date),
                balance_cents,
                debt_id,
            )
            if row is None:
                raise RuntimeError("SQLite не вернул обновлённый кредит")
            return _row(row)


async def create_debt_payment(
    debt_id: int,
    pay_date: date,
    amount: Decimal,
    idempotency_key: str | None = None,
    payment_type: str = "regular",
    cash_effect: str = "movement",
    principal_amount: Decimal | None = None,
    return_operation_details: bool = False,
) -> dict | None:
    """Атомарно записывает платёж и известную часть, ушедшую в тело."""
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            if idempotency_key:
                duplicate = await conn.fetchrow(
                    """
                    SELECT debt_id, operation_id
                    FROM debt_payments
                    WHERE idempotency_key = ?
                    """,
                    idempotency_key,
                )
                if duplicate:
                    row = await conn.fetchrow(
                        "SELECT * FROM debts WHERE id = ?", duplicate["debt_id"]
                    )
                    if row is None:
                        return None
                    result = _row(row)
                    if return_operation_details:
                        return {
                            "debt": result,
                            "operation_id": duplicate["operation_id"],
                            "operation_created": False,
                        }
                    return result
            debt_raw = await conn.fetchrow(
                "SELECT * FROM debts WHERE id = ?", debt_id
            )
            if debt_raw is None:
                return None
            debt = _row(debt_raw)
            if debt["archived"]:
                raise DebtPaymentError("архивный долг нельзя оплачивать")
            if debt["status"] != "active":
                raise DebtPaymentError("закрытый долг нельзя оплачивать")
            if amount <= 0:
                raise DebtPaymentError("сумма платежа должна быть больше нуля")
            if payment_type not in {"regular", "early"}:
                raise DebtPaymentError("неизвестный тип платежа")
            if cash_effect not in {"movement", "already_in_balance"}:
                raise DebtPaymentError("неизвестный денежный эффект платежа")
            if principal_amount is not None:
                if principal_amount < 0 or principal_amount > amount:
                    raise DebtPaymentError(
                        "часть платежа в тело должна быть от 0 до суммы платежа"
                    )
                if principal_amount > debt["balance"]:
                    raise DebtPaymentError(
                        "часть платежа в тело не может быть больше остатка"
                    )
            next_payment_date = _next_payment_after(debt, payment_type)
            payment_label = (
                "Досрочное погашение" if payment_type == "early" else "Платёж"
            )
            operation_id = None
            if cash_effect == "movement":
                operation = await conn.fetchrow(
                    """
                    INSERT INTO operations (
                      op_date, type, amount, category, comment, source, needs_review
                    ) VALUES (?, 'расход', ?, 'Долги', ?, 'tma-долг', 0)
                    RETURNING id
                    """,
                    pay_date.isoformat(),
                    to_cents(amount),
                    f"{payment_label} по кредиту "
                    f"{debt.get('loan_name') or debt['creditor']}",
                )
                if operation is None:
                    raise RuntimeError("SQLite не вернул id операции по кредиту")
                operation_id = operation["id"]
            await conn.execute(
                """
                INSERT INTO debt_payments (
                  debt_id, operation_id, pay_date, amount, principal_amount,
                  kind, payment_type, cash_effect, idempotency_key
                ) VALUES (?, ?, ?, ?, ?, 'payment', ?, ?, ?)
                """,
                debt_id,
                operation_id,
                pay_date.isoformat(),
                to_cents(amount),
                to_cents(principal_amount) if principal_amount is not None else None,
                payment_type,
                cash_effect,
                idempotency_key,
            )
            applied_principal = (
                principal_amount if principal_amount is not None else Decimal("0")
            )
            new_balance = debt["balance"] - applied_principal
            row = await conn.fetchrow(
                """
                UPDATE debts
                SET balance = ?,
                    next_payment_date = ?,
                    status = CASE WHEN ? <= 0 THEN 'closed' ELSE 'active' END
                WHERE id = ?
                RETURNING *
                """,
                to_cents(new_balance),
                _date_value(next_payment_date),
                to_cents(new_balance),
                debt_id,
            )
            if row is None:
                raise RuntimeError("SQLite не вернул обновлённый кредит")
            result = _row(row)
            if return_operation_details:
                return {
                    "debt": result,
                    "operation_id": operation_id,
                    "operation_created": operation_id is not None,
                }
            return result


async def adjust_debt_balance(
    debt_id: int,
    new_balance: Decimal,
    adjusted_at: date,
    reason: str | None = None,
) -> dict | None:
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            debt = await conn.fetchrow(
                "SELECT id, principal, archived FROM debts WHERE id = ?", debt_id
            )
            if debt is None:
                return None
            if debt["archived"]:
                raise DebtPaymentError("архивный долг нельзя корректировать")
            balance_cents = to_cents(new_balance)
            if new_balance > from_cents(debt["principal"]):
                raise DebtPaymentError(
                    "остаток не может быть больше первоначальной суммы"
                )
            await conn.execute(
                """
                INSERT INTO debt_payments (debt_id, pay_date, amount, kind, reason)
                VALUES (?, ?, ?, 'adjustment', ?)
                """,
                debt_id,
                adjusted_at.isoformat(),
                balance_cents,
                reason,
            )
            row = await conn.fetchrow(
                """
                UPDATE debts
                SET balance = ?,
                    status = CASE WHEN ? <= 0 THEN 'closed' ELSE 'active' END
                WHERE id = ?
                RETURNING *
                """,
                balance_cents,
                balance_cents,
                debt_id,
            )
            if row is None:
                raise RuntimeError("SQLite не вернул обновлённый кредит")
            return _row(row)
