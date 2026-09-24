"""Валидация личных долгов.

Выделено из ``schemas.py`` при разбиении oversized-модуля; код перенесён без
изменений.
"""

from datetime import date

from ._common import (
    ValidationError,
    _nullable_date,
    _payload,
    _required_text,
    _text,
    iso_date,
    money,
    nonnegative_money,
)


def personal_debt_create(payload: object, today: date) -> dict:
    data = _payload(payload, {
        "person", "direction", "principal", "opened_at", "due_date", "comment"
    }, require_values=False)
    direction = data.get("direction")
    if direction not in {"owed_to_me", "i_owe"}:
        raise ValidationError("неизвестное направление долга")
    return {
        "person": _required_text(data.get("person"), "person", 120),
        "direction": direction,
        "principal": money(data.get("principal")),
        "opened_at": iso_date(data["opened_at"]) if data.get("opened_at") else today,
        "due_date": _nullable_date(data.get("due_date"), "due_date"),
        "comment": _text(data.get("comment"), "comment", 500),
        "operation_id": None,
    }


def personal_debt_patch(payload: object, current: dict) -> dict:
    data = _payload(payload, {
        "person", "direction", "principal", "balance", "opened_at",
        "due_date", "comment", "status",
    })
    result: dict = {}
    if "person" in data:
        result["person"] = _required_text(data["person"], "person", 120)
    if "direction" in data:
        if data["direction"] not in {"owed_to_me", "i_owe"}:
            raise ValidationError("неизвестное направление долга")
        result["direction"] = data["direction"]
    if "principal" in data:
        result["principal"] = money(data["principal"])
    if "balance" in data:
        result["balance"] = nonnegative_money(data["balance"])
    if "opened_at" in data:
        result["opened_at"] = iso_date(data["opened_at"])
    if "due_date" in data:
        result["due_date"] = _nullable_date(data["due_date"], "due_date")
    if "comment" in data:
        result["comment"] = _text(data["comment"], "comment", 500)
    if "status" in data:
        if data["status"] not in {"open", "closed"}:
            raise ValidationError("неизвестный статус личного долга")
        result["status"] = data["status"]
    final_principal = result.get("principal", current["principal"])
    final_balance = result.get("balance", current["balance"])
    if final_principal < final_balance:
        raise ValidationError("principal не может быть меньше текущего остатка")
    return result
