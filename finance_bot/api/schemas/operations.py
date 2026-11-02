"""Валидация операций.

Выделено из ``schemas.py`` при разбиении oversized-модуля; код перенесён без
изменений.
"""

from datetime import date

from finance_bot.config import EXPENSE_CATEGORIES, INCOME_CATEGORIES, OPERATION_TYPES

from ._common import ValidationError, _payload, _required_text, _text, iso_date, money


TRANSFER_DIRECTIONS = {"in", "out", "self"}


def transfer_direction(value: object) -> str | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str) or value not in TRANSFER_DIRECTIONS:
        raise ValidationError("неизвестное направление перевода")
    return value


def operation_patch(payload: object, current: dict) -> dict:
    if not isinstance(payload, dict):
        raise ValidationError("ожидается JSON-объект")
    allowed = {
        "amount", "category", "op_date", "type", "comment", "account", "note",
        "transfer_direction",
    }
    unknown = set(payload) - allowed
    if unknown:
        raise ValidationError(f"неизвестные поля: {', '.join(sorted(unknown))}")
    if not payload:
        raise ValidationError("нет полей для изменения")

    result: dict = {}
    if "amount" in payload:
        result["amount"] = money(payload["amount"])
    if "op_date" in payload:
        result["op_date"] = iso_date(payload["op_date"])
    if "type" in payload:
        if payload["type"] not in OPERATION_TYPES:
            raise ValidationError("неизвестный тип операции")
        result["type"] = payload["type"]
    if "category" in payload:
        result["category"] = _text(payload["category"], "category", 100)
    if "comment" in payload:
        result["comment"] = _text(payload["comment"], "comment", 500)
    if "account" in payload:
        result["account"] = _text(payload["account"], "account", 100)
    if "note" in payload:
        result["note"] = _text(payload["note"], "note", 1000)
    if "transfer_direction" in payload:
        result["transfer_direction"] = transfer_direction(
            payload["transfer_direction"]
        )

    final_type = result.get("type", current["type"])
    if final_type == "перевод":
        result["category"] = None
        if "transfer_direction" not in result and current.get("type") != "перевод":
            result["transfer_direction"] = "out"
    elif "type" in payload or "transfer_direction" in payload:
        result["transfer_direction"] = None
    return result


def operation_create(payload: object, today: date) -> dict:
    """Валидирует полностью заданную операцию из ручного интерфейса."""
    data = _payload(payload, {
        "amount", "category", "op_date", "type", "comment", "account",
        "transfer_direction",
    }, require_values=False)
    if "amount" not in data:
        raise ValidationError("amount обязателен")
    if data.get("type") not in OPERATION_TYPES:
        raise ValidationError("неизвестный тип операции")

    op_date = iso_date(data.get("op_date", today.isoformat()))
    if op_date > today:
        raise ValidationError("дата операции не может быть в будущем")

    type_ = data["type"]
    comment = _text(data.get("comment"), "comment", 500)
    account = _text(data.get("account"), "account", 100)
    if type_ == "перевод":
        if data.get("category") not in (None, ""):
            raise ValidationError("у перевода не может быть категории")
        direction = transfer_direction(data.get("transfer_direction"))
        if direction is None:
            raise ValidationError("у перевода должно быть направление")
        category = None
    else:
        if data.get("transfer_direction") not in (None, ""):
            raise ValidationError("у расхода или дохода не может быть направления")
        category = _required_text(data.get("category"), "category", 100)
        allowed = EXPENSE_CATEGORIES if type_ == "расход" else INCOME_CATEGORIES
        if category not in allowed:
            raise ValidationError("неизвестная категория операции")
        direction = None

    return {
        "op_date": op_date,
        "type_": type_,
        "amount": money(data["amount"]),
        "category": category,
        "comment": comment,
        "account": account,
        "transfer_direction": direction,
    }
