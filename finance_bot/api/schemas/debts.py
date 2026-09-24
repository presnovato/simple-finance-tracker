"""Валидация кредитов.

Выделено из ``schemas.py`` при разбиении oversized-модуля; код перенесён без
изменений.
"""

from datetime import date

from ._common import (
    ValidationError,
    _nullable_date,
    _payload,
    _priority,
    _rate,
    _required_text,
    _text,
    iso_date,
    money,
    nonnegative_money,
)


def debt_create(payload: object) -> dict:
    data = _payload(payload, {
        "creditor", "loan_name", "contract_ref", "principal", "rate",
        "min_payment", "next_payment_amount", "opened_at",
        "next_payment_date", "priority", "due_date",
        "maturity_date",
    }, require_values=False)
    maturity_value = data.get("maturity_date", data.get("due_date"))
    if "maturity_date" in data and "due_date" in data:
        if _nullable_date(data.get("maturity_date"), "maturity_date") != \
                _nullable_date(data.get("due_date"), "due_date"):
            raise ValidationError("maturity_date и due_date должны совпадать")
    min_payment = money(data["min_payment"]) \
        if data.get("min_payment") not in (None, "") else None
    next_payment_amount = money(data["next_payment_amount"]) \
        if data.get("next_payment_amount") not in (None, "") \
        else min_payment
    next_payment_date = _nullable_date(
        data.get("next_payment_date"), "next_payment_date"
    )
    return {
        "creditor": _required_text(data.get("creditor"), "creditor", 120),
        "loan_name": _text(data.get("loan_name"), "loan_name", 160),
        "contract_ref": _text(data.get("contract_ref"), "contract_ref", 80),
        "principal": money(data.get("principal")),
        "rate": _rate(data.get("rate")),
        "min_payment": min_payment,
        "next_payment_amount": next_payment_amount,
        "opened_at": _nullable_date(data.get("opened_at"), "opened_at"),
        "next_payment_date": next_payment_date,
        "priority": _priority(data.get("priority")),
        "due_date": _nullable_date(maturity_value, "maturity_date"),
    }


def debt_patch(payload: object, current: dict) -> dict:
    data = _payload(payload, {
        "creditor", "loan_name", "contract_ref", "principal", "rate",
        "min_payment", "next_payment_amount", "opened_at",
        "next_payment_date", "priority", "due_date",
        "maturity_date", "status",
    })
    result: dict = {}
    if "creditor" in data:
        result["creditor"] = _required_text(data["creditor"], "creditor", 120)
    if "loan_name" in data:
        result["loan_name"] = _text(data["loan_name"], "loan_name", 160)
    if "contract_ref" in data:
        result["contract_ref"] = _text(data["contract_ref"], "contract_ref", 80)
    if "principal" in data:
        result["principal"] = money(data["principal"])
        if result["principal"] < current["balance"]:
            raise ValidationError("principal не может быть меньше текущего остатка")
    if "rate" in data:
        result["rate"] = _rate(data["rate"])
    if "min_payment" in data:
        result["min_payment"] = money(data["min_payment"]) \
            if data["min_payment"] not in (None, "") else None
        if "next_payment_amount" not in data:
            result["next_payment_amount"] = result["min_payment"]
    if "next_payment_amount" in data:
        result["next_payment_amount"] = money(data["next_payment_amount"]) \
            if data["next_payment_amount"] not in (None, "") else None
    if "opened_at" in data:
        result["opened_at"] = _nullable_date(data["opened_at"], "opened_at")
    if "next_payment_date" in data:
        result["next_payment_date"] = _nullable_date(
            data["next_payment_date"], "next_payment_date"
        )
    if "priority" in data:
        result["priority"] = _priority(data["priority"])
    if "maturity_date" in data and "due_date" in data:
        if _nullable_date(data["maturity_date"], "maturity_date") != \
                _nullable_date(data["due_date"], "due_date"):
            raise ValidationError("maturity_date и due_date должны совпадать")
    if "maturity_date" in data:
        result["due_date"] = _nullable_date(data["maturity_date"], "maturity_date")
    elif "due_date" in data:
        result["due_date"] = _nullable_date(data["due_date"], "due_date")
    if "status" in data:
        if data["status"] not in {"active", "closed"}:
            raise ValidationError("неизвестный статус кредита")
        result["status"] = data["status"]
    return result


def debt_adjust(
    payload: object,
    today: date | None = None,
    current: dict | None = None,
) -> dict:
    data = _payload(payload, {"balance", "date", "reason"})
    if "balance" not in data:
        raise ValidationError("balance обязателен")
    balance = nonnegative_money(data["balance"])
    if current is not None and balance > current["principal"]:
        raise ValidationError(
            "остаток не может быть больше первоначальной суммы"
        )
    return {
        "balance": balance,
        "date": iso_date(data["date"]) if data.get("date") else (today or date.today()),
        "reason": _required_text(data.get("reason"), "reason", 300),
    }


def debt_payment(payload: object, today: date | None = None) -> dict:
    data = _payload(
        payload,
        {
            "amount", "principal_amount", "date", "idempotency_key",
            "payment_type", "cash_effect",
        },
        require_values=False,
    )
    amount = nonnegative_money(data.get("amount"))
    principal_amount = None
    if data.get("principal_amount") not in (None, ""):
        principal_amount = nonnegative_money(
            data["principal_amount"], "principal_amount"
        )
        if principal_amount > amount:
            raise ValidationError(
                "principal_amount не может быть больше суммы платежа"
            )
    idempotency_key = _text(data.get("idempotency_key"), "idempotency_key", 120)
    payment_type = data.get("payment_type", "regular")
    if payment_type not in {"regular", "early"}:
        raise ValidationError("неизвестный тип платежа")
    cash_effect = data.get("cash_effect", "movement")
    if cash_effect not in {"movement", "already_in_balance"}:
        raise ValidationError("неизвестный денежный эффект платежа")
    return {
        "amount": amount,
        "principal_amount": principal_amount,
        "date": iso_date(data["date"]) if data.get("date") else (today or date.today()),
        "idempotency_key": idempotency_key,
        "payment_type": payment_type,
        "cash_effect": cash_effect,
    }
