"""Общие валидаторы и сериализаторы API.

Выделено из ``schemas.py`` при разбиении oversized-модуля; код перенесён без
изменений.
"""

import base64
import binascii
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from finance_bot.config import MAX_ABS_AMOUNT


class ValidationError(ValueError):
    pass


def money(value: object) -> Decimal:
    if isinstance(value, (float, bool)) or value is None:
        raise ValidationError("amount должен быть строкой с числом")
    try:
        amount = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError) as exc:
        raise ValidationError("некорректная сумма") from exc
    if amount <= 0 or amount >= MAX_ABS_AMOUNT:
        raise ValidationError("сумма вне допустимого диапазона")
    return amount


def nonnegative_money(value: object, field: str = "balance") -> Decimal:
    if isinstance(value, (float, bool)) or value is None:
        raise ValidationError(f"{field} должен быть строкой с числом")
    try:
        amount = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError) as exc:
        raise ValidationError(f"некорректное поле {field}") from exc
    if amount < 0 or amount >= MAX_ABS_AMOUNT:
        raise ValidationError(f"{field} вне допустимого диапазона")
    return amount


def signed_money(value: object, field: str = "amount") -> Decimal:
    if isinstance(value, (float, bool)) or value is None:
        raise ValidationError(f"{field} должен быть строкой с числом")
    try:
        amount = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError) as exc:
        raise ValidationError(f"некорректное поле {field}") from exc
    if not amount.is_finite() or abs(amount) >= MAX_ABS_AMOUNT:
        raise ValidationError(f"{field} вне допустимого диапазона")
    return amount


def iso_date(value: object) -> date:
    if not isinstance(value, str):
        raise ValidationError("дата должна быть в формате YYYY-MM-DD")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValidationError("дата должна быть в формате YYYY-MM-DD") from exc


def _text(value: object, field: str, max_length: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValidationError(f"{field} должен быть строкой")
    value = value.strip()
    if len(value) > max_length:
        raise ValidationError(f"{field} слишком длинный")
    return value or None


def _required_text(value: object, field: str, max_length: int) -> str:
    result = _text(value, field, max_length)
    if result is None:
        raise ValidationError(f"{field} обязателен")
    return result


def _nullable_date(value: object, field: str) -> date | None:
    if value in (None, ""):
        return None
    try:
        return iso_date(value)
    except ValidationError as exc:
        raise ValidationError(f"{field}: {exc}") from exc


def _rate(value: object) -> Decimal | None:
    if value in (None, ""):
        return None
    if isinstance(value, (float, bool)):
        raise ValidationError("rate должен быть строкой с числом")
    try:
        result = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError) as exc:
        raise ValidationError("некорректная ставка") from exc
    if result < 0 or result >= Decimal("1000"):
        raise ValidationError("ставка вне допустимого диапазона")
    return result


def _priority(value: object) -> int | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        raise ValidationError("priority должен быть целым числом")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError("priority должен быть целым числом") from exc
    if str(result) != str(value).strip() or not 1 <= result <= 999:
        raise ValidationError("priority должен быть целым числом от 1 до 999")
    return result


def _payload(payload: object, allowed: set[str], *, require_values: bool = True) -> dict:
    if not isinstance(payload, dict):
        raise ValidationError("ожидается JSON-объект")
    unknown = set(payload) - allowed
    if unknown:
        raise ValidationError(f"неизвестные поля: {', '.join(sorted(unknown))}")
    if require_values and not payload:
        raise ValidationError("нет полей для изменения")
    return payload


def money_string(value: Decimal | int) -> str:
    return f"{Decimal(value):.2f}"


def decimal_string(value: Decimal | int) -> str:
    text = format(Decimal(value), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def operation_json(operation: dict) -> dict:
    result = {}
    for key, value in operation.items():
        if isinstance(value, Decimal):
            result[key] = money_string(value)
        elif isinstance(value, (date, datetime)):
            result[key] = value.isoformat()
        else:
            result[key] = value
    return result


def encode_cursor(op_date: date, op_id: int) -> str:
    raw = f"{op_date.isoformat()}:{op_id}".encode("ascii")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(value: str) -> tuple[date, int]:
    try:
        padding = "=" * (-len(value) % 4)
        decoded = base64.urlsafe_b64decode(value + padding).decode("ascii")
        date_text, id_text = decoded.rsplit(":", 1)
        return date.fromisoformat(date_text), int(id_text)
    except (binascii.Error, ValueError, UnicodeDecodeError) as exc:
        raise ValidationError("некорректный cursor") from exc


def query_bool(value: str | None) -> bool | None:
    if value is None or value == "":
        return None
    normalized = value.lower()
    if normalized in {"1", "true", "yes"}:
        return True
    if normalized in {"0", "false", "no"}:
        return False
    raise ValidationError("ожидается true или false")
