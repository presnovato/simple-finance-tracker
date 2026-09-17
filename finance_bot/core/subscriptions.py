"""Чистые расчёты для регулярных подписок."""

from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

PERIODS = {"monthly", "yearly"}
MONEY_STEP = Decimal("0.01")


def next_charge_after(current: date, period: str) -> date:
    """Сдвигает дату списания на один период, не выходя за конец месяца."""
    if period not in PERIODS:
        raise ValueError("period должен быть monthly или yearly")

    if period == "monthly":
        year = current.year + (current.month == 12)
        month = 1 if current.month == 12 else current.month + 1
    else:
        year = current.year + 1
        month = current.month

    day = min(current.day, monthrange(year, month)[1])
    return date(year, month, day)


def monthly_cost(subscriptions: list[dict]) -> Decimal:
    """Стоимость активных подписок в пересчёте на месяц."""
    total = Decimal("0")
    for subscription in subscriptions:
        if subscription.get("status") == "cancelled":
            continue
        amount = Decimal(subscription["amount"])
        total += amount if subscription["period"] == "monthly" else amount / Decimal("12")
    return total.quantize(MONEY_STEP, rounding=ROUND_HALF_UP)


def due_subscriptions(subscriptions: list[dict], today: date) -> list[dict]:
    """Возвращает активные подписки, которые уже пора подтвердить."""
    return sorted(
        (
            subscription
            for subscription in subscriptions
            if subscription.get("status") == "active"
            and subscription["next_charge"] <= today
        ),
        key=lambda subscription: (
            subscription["next_charge"], subscription.get("id", 0)
        ),
    )


def upcoming_charges(
    subscriptions: list[dict], today: date, days: int = 30
) -> list[dict]:
    """Строит ленту будущих списаний в полуоткрытом окне от today."""
    if days < 0:
        return []

    end = today + timedelta(days=days)
    result: list[dict] = []
    for subscription in subscriptions:
        if subscription.get("status") != "active":
            continue
        charge_date = subscription["next_charge"]
        while charge_date <= today:
            charge_date = next_charge_after(charge_date, subscription["period"])
        while charge_date <= end:
            result.append({
                "subscription_id": subscription["id"],
                "title": subscription["title"],
                "amount": Decimal(subscription["amount"]),
                "charge_date": charge_date,
            })
            charge_date = next_charge_after(charge_date, subscription["period"])

    return sorted(
        result, key=lambda charge: (charge["charge_date"], charge["subscription_id"])
    )


def yearly_cost(subscriptions: list[dict]) -> Decimal:
    """Стоимость активных подписок в пересчёте на год."""
    return (monthly_cost(subscriptions) * Decimal("12")).quantize(
        MONEY_STEP, rounding=ROUND_HALF_UP
    )


def share_of_expenses(monthly: Decimal, expenses: Decimal) -> Decimal | None:
    """Доля ежемесячной стоимости подписок в расходах, в процентах."""
    expenses = Decimal(expenses)
    if expenses <= 0:
        return None
    return (
        Decimal(monthly) * Decimal("100") / expenses
    ).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def format_subscription_amount(value: Decimal | int) -> str:
    """Человеческое отображение суммы подписки с копейками."""
    return f"{Decimal(value):.2f}".replace(".", ",") + " ₽"
