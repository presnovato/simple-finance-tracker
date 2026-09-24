"""Валидация денежного якоря.

Выделено из ``schemas.py`` при разбиении oversized-модуля; код перенесён без
изменений.
"""

from datetime import date

from ._common import ValidationError, _payload, iso_date, signed_money


def balance_anchor(payload: object, today: date) -> dict:
    data = _payload(payload, {"amount", "anchor_date"})
    if "amount" not in data:
        raise ValidationError("amount обязателен")
    anchor_date = iso_date(data.get("anchor_date", today.isoformat()))
    if anchor_date > today:
        raise ValidationError("дата якоря не может быть в будущем")
    return {
        "amount": signed_money(data["amount"]),
        "anchor_date": anchor_date,
    }
