from datetime import date
from decimal import Decimal

import pytest

from finance_bot.core.subscriptions import (
    due_subscriptions,
    monthly_cost,
    next_charge_after,
    share_of_expenses,
    upcoming_charges,
    yearly_cost,
)


def test_next_charge_clamps_end_of_month():
    assert next_charge_after(date(2026, 1, 31), "monthly") == date(2026, 2, 28)
    assert next_charge_after(date(2024, 1, 31), "monthly") == date(2024, 2, 29)
    assert next_charge_after(date(2024, 2, 29), "yearly") == date(2025, 2, 28)
    assert next_charge_after(date(2026, 8, 8), "monthly") == date(2026, 9, 8)
    with pytest.raises(ValueError):
        next_charge_after(date(2026, 8, 8), "weekly")


def test_monthly_cost_converts_yearly_and_ignores_cancelled():
    assert monthly_cost([
        {"amount": Decimal("500"), "period": "monthly", "status": "active"},
        {"amount": Decimal("1200"), "period": "yearly", "status": "active"},
        {"amount": Decimal("999"), "period": "monthly", "status": "cancelled"},
    ]) == Decimal("600.00")
    assert monthly_cost([]) == Decimal("0.00")


def test_due_subscriptions_are_sorted_and_ignore_cancelled():
    subscriptions = [
        {"id": 2, "status": "active", "next_charge": date(2026, 8, 10)},
        {"id": 1, "status": "active", "next_charge": date(2026, 8, 8)},
        {"id": 3, "status": "active", "next_charge": date(2026, 8, 11)},
        {"id": 4, "status": "cancelled", "next_charge": date(2026, 8, 1)},
    ]
    assert [row["id"] for row in due_subscriptions(
        subscriptions, date(2026, 8, 10)
    )] == [1, 2]


def test_upcoming_charges_use_exclusive_today_and_inclusive_end():
    subscriptions = [
        {
            "id": 1, "title": "Месяц", "amount": Decimal("500"),
            "period": "monthly", "status": "active",
            "next_charge": date(2026, 8, 15),
        },
        {
            "id": 2, "title": "Год", "amount": Decimal("1200"),
            "period": "yearly", "status": "active",
            "next_charge": date(2026, 9, 9),
        },
        {
            "id": 3, "title": "Сегодня", "amount": Decimal("1"),
            "period": "monthly", "status": "active",
            "next_charge": date(2026, 8, 10),
        },
    ]
    charges = upcoming_charges(subscriptions, date(2026, 8, 10), days=30)
    assert [(charge["subscription_id"], charge["charge_date"]) for charge in charges] == [
        (1, date(2026, 8, 15)),
        (2, date(2026, 9, 9)),
    ]


def test_yearly_cost_and_share_are_decimal_safe():
    subscriptions = [{
        "amount": Decimal("1200"), "period": "yearly", "status": "active",
    }]
    assert yearly_cost(subscriptions) == Decimal("1200.00")
    assert share_of_expenses(Decimal("2398"), Decimal("19340")) == Decimal("12.4")
    assert share_of_expenses(Decimal("10"), Decimal("0")) is None
