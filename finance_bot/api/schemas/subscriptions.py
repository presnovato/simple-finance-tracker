"""Валидация подписок.

Выделено из ``schemas.py`` при разбиении oversized-модуля; код перенесён без
изменений.
"""

from datetime import date, datetime

from ._common import (
    ValidationError,
    _payload,
    _required_text,
    _text,
    iso_date,
    money_string,
    nonnegative_money,
)


def subscription_create(payload: object, today: date) -> dict:
    data = _payload(payload, {
        "title", "amount", "period", "next_charge", "category", "comment",
    }, require_values=False)
    period = data.get("period")
    if period not in {"monthly", "yearly"}:
        raise ValidationError("period должен быть monthly или yearly")
    if not data.get("next_charge"):
        raise ValidationError("next_charge обязателен")
    return {
        "title": _required_text(data.get("title"), "title", 160),
        "amount": nonnegative_money(data.get("amount"), "amount"),
        "period": period,
        "next_charge": iso_date(data["next_charge"]),
        "category": _text(data.get("category"), "category", 120),
        "comment": _text(data.get("comment"), "comment", 500),
    }


def subscription_patch(payload: object, current: dict) -> dict:
    data = _payload(payload, {
        "title", "amount", "period", "next_charge", "category", "comment", "status",
    })
    result: dict = {}
    if "title" in data:
        result["title"] = _required_text(data["title"], "title", 160)
    if "amount" in data:
        result["amount"] = nonnegative_money(data["amount"], "amount")
    if "period" in data:
        if data["period"] not in {"monthly", "yearly"}:
            raise ValidationError("period должен быть monthly или yearly")
        result["period"] = data["period"]
    if "next_charge" in data:
        result["next_charge"] = iso_date(data["next_charge"])
    if "category" in data:
        result["category"] = _text(data["category"], "category", 120)
    if "comment" in data:
        result["comment"] = _text(data["comment"], "comment", 500)
    if "status" in data:
        if data["status"] not in {"active", "cancelled"}:
            raise ValidationError("неизвестный статус подписки")
        result["status"] = data["status"]
    return result


def charge_request(payload: object) -> dict:
    data = _payload(payload, {"confirmed", "op_date"}, require_values=False)
    if "confirmed" not in data or not isinstance(data["confirmed"], bool):
        raise ValidationError("confirmed должен быть логическим значением")
    return {
        "confirmed": data["confirmed"],
        "op_date": iso_date(data["op_date"])
        if data.get("op_date") is not None else None,
    }


def subscription_json(subscription: dict, *, due: bool | None = None) -> dict:
    result = {
        "id": subscription["id"],
        "title": subscription["title"],
        "amount": money_string(subscription["amount"]),
        "period": subscription["period"],
        "next_charge": subscription["next_charge"].isoformat()
        if isinstance(subscription.get("next_charge"), date)
        else subscription.get("next_charge"),
        "category": subscription.get("category"),
        "comment": subscription.get("comment"),
        "status": subscription["status"],
        "created_at": subscription["created_at"].isoformat()
        if isinstance(subscription.get("created_at"), (date, datetime))
        else subscription.get("created_at"),
    }
    if due is not None:
        result["due"] = due
    return result
