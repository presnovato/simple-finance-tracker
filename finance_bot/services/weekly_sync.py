"""Сбор фактического финансового snapshot для Markdown-выгрузки."""

from datetime import date
from decimal import Decimal

from finance_bot.core.dates import effective_today
from finance_bot.core.debts import repaid_principal
from finance_bot.database import queries
from finance_bot.services import balance as balance_service

ZERO = Decimal("0.00")
PERCENT_STEP = Decimal("0.01")


def _decimal(value: object) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(value)  # type: ignore[arg-type]
    except (ArithmeticError, TypeError, ValueError):
        return None


def _progress(principal: Decimal | None, paid: Decimal | None) -> Decimal | None:
    if principal is None or paid is None or principal <= 0:
        return None
    paid = min(principal, max(ZERO, paid))
    return (paid * Decimal("100") / principal).quantize(PERCENT_STEP)


def _debt_fields(
    row: dict,
    _payments: list[dict] | None,
    *,
    kind: str,
) -> dict:
    principal = _decimal(row.get("principal"))
    balance = _decimal(row.get("balance"))
    paid = (
        repaid_principal(principal, balance)
        if principal is not None and balance is not None
        else None
    )

    return {
        "kind": kind,
        "id": row.get("id"),
        "name": row.get("loan_name") or row.get("person") or row.get("creditor"),
        "creditor": row.get("creditor"),
        "person": row.get("person"),
        "contract_ref": row.get("contract_ref"),
        "direction": row.get("direction"),
        "balance": balance,
        "principal": principal,
        "paid_amount": paid,
        "paid_percent": _progress(principal, paid),
        "rate": _decimal(row.get("rate")),
        "min_payment": _decimal(row.get("min_payment")),
        "opened_at": row.get("opened_at"),
        "next_payment_amount": _decimal(row.get("next_payment_amount")),
        "next_payment_date": row.get("next_payment_date"),
        "due_date": row.get("due_date"),
    }


def _sum_balances(items: list[dict]) -> Decimal | None:
    if not items:
        return ZERO
    balances = [item.get("balance") for item in items]
    if any(balance is None for balance in balances):
        return None
    return sum(balances, ZERO)


async def _credit_item(row: dict) -> dict:
    payments = await queries.debt_payment_history(row["id"])
    return _debt_fields(row, payments, kind="credit")


async def _personal_item(row: dict) -> dict:
    payments = await queries.personal_debt_history(row["id"])
    return _debt_fields(row, payments, kind="personal")


async def build_finance_snapshot(as_of: date | None = None) -> dict:
    """Собирает данные, которые не зависят от выбранного периода операций.

    Отсутствующие в модели показатели остаются ``None`` и объясняются
    форматтером, вместо подстановки нулей или расчётов с недоказанными
    предположениями.
    """
    as_of = as_of or effective_today()
    balance_snapshot = await balance_service.get_snapshot()

    credit_rows = await queries.list_debts("active")
    personal_rows = await queries.list_personal_debts("open")
    credits = [await _credit_item(row) for row in credit_rows]
    personal_debts = [await _personal_item(row) for row in personal_rows]
    debts = credits + personal_debts

    personal_liabilities = [
        item for item in personal_debts if item.get("direction") == "i_owe"
    ]
    receivables = [
        item for item in personal_debts if item.get("direction") == "owed_to_me"
    ]
    unknown_personal_direction = [
        item for item in personal_debts
        if item.get("direction") not in {"i_owe", "owed_to_me"}
    ]
    liability_items = credits + personal_liabilities

    liability_balance = _sum_balances(liability_items)
    if unknown_personal_direction:
        liability_balance = None

    credit_next_amounts = [
        item.get("next_payment_amount")
        if item.get("next_payment_amount") is not None
        else item.get("min_payment")
        for item in credits
    ]
    # `min_payment` is a fallback used when a legacy row has no explicit
    # next_payment_amount. Keep it in the snapshot without mutating the row.
    for item, amount in zip(credits, credit_next_amounts):
        item["next_payment_amount"] = amount

    if credits:
        if all(amount is None for amount in credit_next_amounts):
            next_payment_total = None
        else:
            next_payment_total = sum(
                (amount for amount in credit_next_amounts if amount is not None),
                ZERO,
            )
    elif personal_liabilities or unknown_personal_direction:
        next_payment_total = None
    else:
        next_payment_total = ZERO

    return {
        "as_of": as_of,
        "cash": {
            "total": balance_snapshot["amount"] if balance_snapshot else None,
            "anchor_date": balance_snapshot["anchor_date"] if balance_snapshot else None,
            "accounts": None,
            "free": None,
            "reserved": None,
            "total_unavailable_reason": (
                None
                if balance_snapshot
                else "не задан якорь текущего остатка"
            ),
            "accounts_unavailable_reason": (
                "отдельные остатки по счетам/кошелькам не хранятся"
            ),
            "free_unavailable_reason": "резервирование средств не хранится",
            "reserved_unavailable_reason": "резервирование средств не хранится",
        },
        "debts": debts,
        "totals": {
            "credit_balance": _sum_balances(credits),
            "personal_liability_balance": _sum_balances(personal_liabilities),
            "liability_balance": liability_balance,
            "liability_unavailable_reason": (
                "направление одного или нескольких личных долгов неизвестно"
                if unknown_personal_direction
                else "один или несколько остатков неизвестны"
            ),
            "receivable_balance": _sum_balances(receivables),
            "next_payment_amount": next_payment_total,
            "next_payment_unknown_count": sum(
                amount is None for amount in credit_next_amounts
            ),
            "next_payment_date_unknown_count": sum(
                item.get("next_payment_amount") is not None
                and item.get("next_payment_date") is None
                for item in credits
            ),
            "personal_liability_payment_unknown_count": len(personal_liabilities),
            "unknown_personal_direction_count": len(unknown_personal_direction),
        },
        "previous_total_debt": None,
        "history_unavailable_reason": "история snapshot Weekly Sync не хранится",
    }
