"""Чистая логика кредитов и личных долгов."""

import json
import re
from calendar import monthrange
from datetime import date
from decimal import Decimal, ROUND_CEILING

from finance_bot.core.parsing import parse_amount, validate_operation_date

DEBT_INTENTS = {
    "expense", "debt_payment", "personal_debt_new", "personal_debt_repay"
}
PERSONAL_DIRECTIONS = {"owed_to_me", "i_owe"}
ZERO = Decimal("0")
DEBT_MARKERS = (
    "долг", "долж", "кредит", "рассроч", "займ", "занял", "заняла",
    "одолж", "вернул", "вернула", "погаш", "дал ", "дала ",
)


def may_contain_debt_intent(text: str) -> bool:
    """Не отправляет обычную трату в дополнительный LLM-классификатор."""
    normalized = text.casefold().replace("ё", "е")
    return any(marker in normalized for marker in DEBT_MARKERS)


def normalize_match_text(value: str | None) -> str:
    normalized = (value or "").casefold().replace("ё", "е")
    return re.sub(r"[^a-zа-я0-9]+", "", normalized)


def match_records(query: str | None, records: list[dict], field: str) -> list[dict]:
    """Точный матч имеет приоритет; затем — безопасный матч по подстроке."""
    needle = normalize_match_text(query)
    if not needle:
        return records
    exact = [row for row in records if normalize_match_text(row.get(field)) == needle]
    if exact:
        return exact
    return [
        row for row in records
        if needle in normalize_match_text(row.get(field))
        or normalize_match_text(row.get(field)) in needle
    ]


def _json_object(raw: str) -> dict:
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    candidates = [text]
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match and match.group(0) != text:
        candidates.append(match.group(0))
    for candidate in candidates:
        try:
            value = json.loads(candidate)
            if isinstance(value, dict):
                return value
        except (json.JSONDecodeError, TypeError):
            continue
    raise ValueError("JSON-объект не найден")


def _optional_date(value: object) -> date | None:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def parse_debt_intent_response(raw: str, default_date: date) -> dict:
    """Нормализует ответ отдельного долгового классификатора без исключений."""
    fallback = {
        "intent": "expense", "amount": None, "creditor": None,
        "person": None, "direction": None, "date": default_date,
        "due_date": None, "comment": None, "needs_review": False,
    }
    try:
        data = _json_object(raw)
    except ValueError:
        return fallback

    intent = str(data.get("intent") or "expense").strip().lower()
    if intent not in DEBT_INTENTS:
        return fallback
    if intent == "expense":
        return fallback

    amount = parse_amount(data.get("amount"))
    parsed_date, date_review = validate_operation_date(
        _optional_date(data.get("date")), default_date
    )
    direction = str(data.get("direction") or "").strip().lower() or None
    creditor = str(data.get("creditor") or "").strip() or None
    person = str(data.get("person") or "").strip() or None
    comment = str(data.get("comment") or "").strip() or None
    due_date = _optional_date(data.get("due_date"))

    needs_review = bool(data.get("needs_review")) or date_review
    if amount is None or amount <= 0:
        needs_review = True
    if intent == "debt_payment" and not creditor:
        needs_review = True
    if intent.startswith("personal_debt"):
        if not person or direction not in PERSONAL_DIRECTIONS:
            needs_review = True

    return {
        "intent": intent,
        "amount": amount,
        "creditor": creditor,
        "person": person,
        "direction": direction,
        "date": parsed_date,
        "due_date": due_date,
        "comment": comment,
        "needs_review": needs_review,
    }


def _add_months(value: date, months: int) -> date:
    month_index = value.year * 12 + value.month - 1 + months
    year, month_zero = divmod(month_index, 12)
    month = month_zero + 1
    return date(year, month, min(value.day, monthrange(year, month)[1]))


def forecast_closure_date(
    balance: Decimal,
    payments: list[tuple[date, Decimal]],
    today: date,
    *,
    window: int = 6,
) -> date | None:
    """Прогноз по средней части платежа, ушедшей в тело; двух точек — минимум."""
    positive = sorted(
        ((paid_at, amount) for paid_at, amount in payments if amount > 0),
        key=lambda item: item[0],
    )[-window:]
    if balance <= 0 or len(positive) < 2:
        return None
    average = sum((amount for _, amount in positive), Decimal("0")) / len(positive)
    if average <= 0:
        return None
    months = int((balance / average).to_integral_value(rounding=ROUND_CEILING))
    anchor = max(today, positive[-1][0])
    return _add_months(anchor, months)


def repaid_principal(principal: Decimal, balance: Decimal) -> Decimal:
    """Возвращает погашенное тело из текущего остатка тела кредита."""
    if principal <= 0:
        return ZERO
    return max(ZERO, min(principal, principal - balance))


def progress_percent(principal: Decimal, balance: Decimal) -> Decimal:
    if principal <= 0:
        return Decimal("0.00")
    paid = repaid_principal(principal, balance)
    return (paid * Decimal("100") / principal).quantize(Decimal("0.01"))


def debt_curve(
    total_principal: Decimal,
    payments: list[tuple[date, Decimal]],
) -> list[dict]:
    """Помесечная кривая остатка по фактическим платежам."""
    if total_principal <= 0:
        return []
    monthly: dict[str, Decimal] = {}
    for paid_at, amount in payments:
        key = paid_at.strftime("%Y-%m")
        monthly[key] = monthly.get(key, Decimal("0")) + max(amount, Decimal("0"))
    balance = total_principal
    result: list[dict] = []
    for month in sorted(monthly):
        balance = max(Decimal("0"), balance - monthly[month])
        result.append({"month": month, "balance": balance})
    return result
