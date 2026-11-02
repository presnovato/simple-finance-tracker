"""Устойчивый разбор ответа LLM (раздел ТЗ «Устойчивый парсинг ответа»).

Flash-модели капризны: markdown-обёртки, внешний ключ output, массивы вместо
строк, суммы «1 000» / «779,96». Полный провал не роняет бот — возвращается
запись с needs_review=True.
"""

import json
import re
from calendar import monthrange
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from finance_bot.config import (
    EXPENSE_CATEGORIES,
    INCOME_CATEGORIES,
    LARGE_AMOUNT_REVIEW_THRESHOLD,
    MAX_ABS_AMOUNT,
    OPERATION_TYPES,
)
from finance_bot.core.subscriptions import next_charge_after

FALLBACK = {
    "intent": "operation",
    "date": None, "type": None, "amount": None, "category": None,
    "comment": None, "account": None, "transfer_direction": None,
    "needs_review": True,
}


def parse_amount(value) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, (int, float, Decimal)):
        amount = Decimal(str(value))
    else:
        text = str(value)
        text = re.sub(r"[₽рp\.руб\s\u00a0\u202f]+$", "", text.strip(), flags=re.IGNORECASE)
        text = (
            text.replace("\u00a0", "")
            .replace("\u202f", "")
            .replace(" ", "")
            .replace(",", ".")
        )
        try:
            amount = Decimal(text)
        except InvalidOperation:
            return None
    if not amount.is_finite() or abs(amount) >= MAX_ABS_AMOUNT:
        return None
    return amount


def parse_quick_amount(text: str) -> Decimal | None:
    """Распознаёт сообщение только с суммой для frictionless capture."""
    normalized = text.strip()
    if re.fullmatch(
        r"\+?(?:\d[\d \u00a0]*(?:[.,]\d{1,2})?)\s*"
        r"(?:₽|р|руб(?:\.|лей|ля)?)?",
        normalized,
        flags=re.IGNORECASE,
    ) is None:
        return None
    amount = parse_amount(normalized)
    return amount if amount is not None and amount > 0 else None


def _unwrap(obj):
    """Разворачивает {"output": {...}} и одноэлементные массивы-значения."""
    if isinstance(obj, dict) and set(obj.keys()) == {"output"}:
        obj = obj["output"]
    if isinstance(obj, list) and len(obj) == 1:
        obj = obj[0]
    return obj


def _decode_json(raw: str, *, prefer_array: bool = False):
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()

    candidates = [text]
    patterns = (r"\[.*\]", r"\{.*\}") if prefer_array \
        else (r"\{.*\}", r"\[.*\]")
    for pattern in patterns:
        match = re.search(pattern, text, re.DOTALL)
        if match and match.group(0) not in candidates:
            candidates.append(match.group(0))

    for candidate in candidates:
        try:
            return json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            continue
    raise ValueError("JSON не найден")


def _scalar(value):
    if isinstance(value, list) and value:
        return value[0]
    return value


def _text_value(value) -> str | None:
    value = _scalar(value)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_date(value) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(str(_scalar(value)).strip()[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def validate_operation_date(value: date | None, default_date: date) -> tuple[date, bool]:
    """Возвращает безопасную дату и признак необходимости ручной проверки."""
    resolved = value or default_date
    if resolved > default_date:
        return default_date, True
    return resolved, resolved < default_date - timedelta(days=400)


def _subscription_day_date(day: int, today: date) -> date | None:
    if not 1 <= day <= 31:
        return None
    year, month = today.year, today.month
    candidate = date(year, month, min(day, monthrange(year, month)[1]))
    if candidate <= today:
        month += 1
        if month == 13:
            year, month = year + 1, 1
        candidate = date(year, month, min(day, monthrange(year, month)[1]))
    return candidate


def _parse_subscription_date(value, today: date) -> date | None:
    raw = _text_value(value)
    if raw is None:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        pass

    day_only = re.fullmatch(r"(\d{1,2})(?:\s*числа?)?", raw.lower())
    if day_only:
        return _subscription_day_date(int(day_only.group(1)), today)

    day_month = re.fullmatch(r"(\d{1,2})[./-](\d{1,2})", raw)
    if day_month:
        day, month = int(day_month.group(1)), int(day_month.group(2))
        try:
            candidate = date(today.year, month, day)
        except ValueError:
            return None
        if candidate <= today:
            try:
                candidate = date(today.year + 1, month, day)
            except ValueError:
                return None
        return candidate
    return None


def _parse_subscription(data: dict, default_date: date) -> dict | None:
    title = _text_value(data.get("title"))
    amount = parse_amount(_scalar(data.get("amount")))
    if not title or amount is None or amount <= 0:
        return None

    raw_period = _text_value(data.get("period"))
    period = raw_period.lower() if raw_period else "monthly"
    needs_review = bool(data.get("needs_review"))
    if amount > LARGE_AMOUNT_REVIEW_THRESHOLD:
        needs_review = True
    used_default = raw_period is None
    if period not in {"monthly", "yearly"}:
        period = "monthly"
        needs_review = True
        used_default = True

    charge_date = _parse_subscription_date(data.get("next_charge"), default_date)
    if charge_date is None:
        charge_date = next_charge_after(default_date, period)
        needs_review = True
        used_default = True
    comment = _text_value(data.get("comment"))
    return {
        "intent": "subscription",
        "title": title[:160],
        "amount": amount,
        "period": period,
        "next_charge": charge_date,
        "category": "Подписки",
        "comment": comment[:500] if comment else None,
        "needs_review": needs_review,
        "subscription_defaults": used_default,
    }


def _normalise_category(
    value: str | None, type_: str | None
) -> tuple[str | None, bool, str | None]:
    """Приводит категорию модели к допустимой, не теряя неизвестную.

    Возвращает (категория, needs_review, исходное_значение_модели).
    """
    if value is None:
        return None, False, None
    if type_ == "перевод":
        return None, False, None
    allowed = INCOME_CATEGORIES if type_ == "доход" else EXPENSE_CATEGORIES
    normalized = " ".join(value.casefold().split())
    lookup = {name.casefold(): name for name in allowed}
    canonical = lookup.get(normalized)
    if canonical is not None:
        return canonical, False, None
    fallback = None if type_ == "доход" else "Прочее"
    return fallback, True, value


def _parse_one(
    data: dict, default_date: date, *, allow_subscription: bool = True
) -> dict:
    intent = _text_value(data.get("intent"))
    if allow_subscription and intent and intent.lower() == "subscription":
        subscription = _parse_subscription(data, default_date)
        if subscription is not None:
            return subscription

    parsed_date, date_needs_review = validate_operation_date(
        _parse_date(data.get("date")), default_date
    )

    type_ = _scalar(data.get("type"))
    type_ = str(type_).strip().lower() if type_ else None
    amount = parse_amount(_scalar(data.get("amount")))
    raw_category = _scalar(data.get("category"))
    raw_category = str(raw_category).strip() if raw_category else None
    category, category_review, model_category = _normalise_category(
        raw_category, type_
    )
    direction = _scalar(data.get("transfer_direction"))
    direction = str(direction).strip().lower() if direction else None
    if direction not in {"in", "out", "self"}:
        direction = None

    comment = (str(_scalar(data.get("comment"))).strip()
               if data.get("comment") else None)
    if model_category:
        # Категория модели неизвестна — сохраняем её в комментарии.
        suffix = f"(категория модели: {model_category})"
        comment = f"{comment} {suffix}" if comment else suffix

    result = {
        "intent": "operation",
        "date": parsed_date,
        "type": type_,
        "amount": amount,
        "category": category,
        "comment": comment,
        "account": (str(_scalar(data.get("account"))).strip().lower()
                    if data.get("account") else None),
        "transfer_direction": direction,
        "needs_review": (
            bool(data.get("needs_review"))
            or date_needs_review
            or category_review
        ),
    }

    # needs_review пересчитывается в коде, модели не доверяем
    if result["amount"] is None or result["amount"] <= 0 \
            or result["type"] not in OPERATION_TYPES:
        result["needs_review"] = True
    if (
        result["amount"] is not None
        and result["amount"] > LARGE_AMOUNT_REVIEW_THRESHOLD
    ):
        result["needs_review"] = True
    if result["type"] == "перевод":
        result["category"] = None
        # Без направления безопасный дефолт будет применён при записи как
        # исходящий перевод, но запись должна попасть на ручную проверку.
        if result["transfer_direction"] is None:
            result["needs_review"] = True
    else:
        result["transfer_direction"] = None
    return result


def parse_llm_response(raw: str, default_date: date) -> dict:
    """Строка от модели → нормализованный dict операции. Никогда не бросает."""
    try:
        data = _unwrap(_decode_json(raw))
        if not isinstance(data, dict):
            raise ValueError("не объект")
    except Exception:
        return dict(FALLBACK)
    return _parse_one(data, default_date)


def parse_llm_response_many(raw: str, default_date: date) -> list[dict]:
    """Ответ модели → список операций; битая позиция не губит остальные."""
    try:
        data = _decode_json(raw, prefer_array=True)
        if isinstance(data, dict) and set(data) == {"output"}:
            data = data["output"]
        if isinstance(data, dict):
            data = [data]
        if not isinstance(data, list):
            return []
        return [
            _parse_one(item, default_date, allow_subscription=False)
            for item in data
            if isinstance(item, dict)
        ]
    except Exception:
        return []
