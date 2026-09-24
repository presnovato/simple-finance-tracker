"""Валидация криптоактивов.

Выделено из ``schemas.py`` при разбиении oversized-модуля; код перенесён без
изменений.
"""

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from ._common import (
    ValidationError,
    _payload,
    _required_text,
    _text,
    decimal_string,
    iso_date,
    money,
    money_string,
)


def crypto_asset(value: object) -> str:
    asset = _required_text(value, "asset", 15).upper()
    if re.fullmatch(r"[A-Z0-9][A-Z0-9._-]{0,14}", asset) is None:
        raise ValidationError("asset должен быть тикером из латинских букв и цифр")
    return asset


def crypto_quantity(value: object, field: str = "quantity", *, allow_zero: bool = False) -> Decimal:
    if isinstance(value, (float, bool)) or value is None:
        raise ValidationError(f"{field} должен быть строкой с числом")
    try:
        quantity = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValidationError(f"некорректное поле {field}") from exc
    if not quantity.is_finite() or abs(quantity) >= Decimal("1000000000000000"):
        raise ValidationError(f"{field} вне допустимого диапазона")
    if not allow_zero and quantity == 0:
        raise ValidationError(f"{field} не может быть нулевым")
    if allow_zero and quantity < 0:
        raise ValidationError(f"{field} не может быть отрицательным")
    return quantity


def crypto_transaction_create(payload: object, today: date) -> dict:
    data = _payload(payload, {
        "asset", "quantity_delta", "rub_amount", "op_date", "comment",
    }, require_values=False)
    return {
        "asset": crypto_asset(data.get("asset")),
        "quantity_delta": crypto_quantity(data.get("quantity_delta"), "quantity_delta"),
        "rub_amount": money(data.get("rub_amount")),
        "op_date": iso_date(data["op_date"]) if data.get("op_date") else today,
        "comment": _text(data.get("comment"), "comment", 500),
    }


def crypto_holding_patch(payload: object) -> dict:
    data = _payload(payload, {"quantity"})
    return {"quantity": crypto_quantity(data.get("quantity"), allow_zero=True)}


def crypto_overview_patch(payload: object) -> bool:
    data = _payload(payload, {"visible"})
    if not isinstance(data.get("visible"), bool):
        raise ValidationError("visible должен быть boolean")
    return data["visible"]


def crypto_holding_json(holding: dict) -> dict:
    return {
        "asset": holding["asset"],
        "quantity": decimal_string(holding["quantity"]),
        "updated_at": holding["updated_at"].isoformat()
        if isinstance(holding.get("updated_at"), datetime)
        else holding.get("updated_at"),
    }


def crypto_transaction_json(transaction: dict) -> dict:
    return {
        "id": transaction["id"],
        "asset": transaction["asset"],
        "quantity_delta": decimal_string(transaction["quantity_delta"]),
        "rub_amount": money_string(transaction["rub_amount"]),
        "op_date": transaction["op_date"].isoformat()
        if isinstance(transaction.get("op_date"), date)
        else transaction.get("op_date"),
        "operation_id": transaction.get("operation_id"),
        "comment": transaction.get("comment"),
    }
