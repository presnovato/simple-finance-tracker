"""Валидация недельного бюджета.

Выделено из ``schemas.py`` при разбиении oversized-модуля; код перенесён без
изменений.
"""

from datetime import date
from decimal import Decimal

from finance_bot.config import EXPENSE_CATEGORIES
from finance_bot.core.budget import week_bounds

from ._common import ValidationError, _payload, iso_date, money


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
