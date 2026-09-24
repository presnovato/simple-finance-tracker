"""Валидация и JSON-схемы API без зависимости от aiohttp."""

import base64
import binascii
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from finance_bot.config import (EXPENSE_CATEGORIES, INCOME_CATEGORIES,
                                MAX_ABS_AMOUNT, OPERATION_TYPES)
from finance_bot.core.budget import week_bounds


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


TRANSFER_DIRECTIONS = {"in", "out", "self"}


def transfer_direction(value: object) -> str | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str) or value not in TRANSFER_DIRECTIONS:
        raise ValidationError("неизвестное направление перевода")
    return value


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


def iso_date(value: object) -> date:
    if not isinstance(value, str):
        raise ValidationError("дата должна быть в формате YYYY-MM-DD")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValidationError("дата должна быть в формате YYYY-MM-DD") from exc


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


def _budget_money(value: object, field: str) -> Decimal:
    if not isinstance(value, str):
        raise ValidationError(f"{field} должен быть строкой с числом")
    try:
        return money(value)
    except ValidationError as exc:
        raise ValidationError(f"{field}: {exc}") from exc


def _optional_budget_money(value: object, field: str) -> Decimal | None:
    if value in (None, ""):
        return None
    return _budget_money(value, field)


def budget_settings(payload: object) -> dict:
    data = _payload(payload, {"overall_limit", "categories"})
    if "overall_limit" not in data:
        raise ValidationError("overall_limit обязателен")

    overall_limit = _budget_money(data["overall_limit"], "overall_limit")

    category_items = data.get("categories", [])
    if not isinstance(category_items, list):
        raise ValidationError("categories должен быть списком")

    categories = []
    seen = set()
    for item in category_items:
        item_data = _payload(item, {"category", "limit"})
        category = item_data.get("category")
        if not isinstance(category, str) or category not in EXPENSE_CATEGORIES:
            raise ValidationError("неизвестная расходная категория")
        if category in seen:
            raise ValidationError("категории должны быть уникальными")
        seen.add(category)
        categories.append({
            "category": category,
            "limit": _optional_budget_money(
                item_data.get("limit"), f"лимит {category}"
            ),
        })
    return {"overall_limit": overall_limit, "categories": categories}


def budget_week_start(value: object, today: date) -> date:
    start = iso_date(value)
    if start.weekday() != 0:
        raise ValidationError("week_start должен быть понедельником")
    current_start, _ = week_bounds(today)
    if start > current_start:
        raise ValidationError("нельзя запросить будущую неделю")
    return start


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
