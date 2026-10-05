"""Ближайшие платежи по подпискам и долгам за 7 дней (spec 04).

Чистая логика без БД: общий источник для TMA-карточки и воскресного отчёта.
"""

from datetime import date, timedelta

UPCOMING_WINDOW_DAYS = 7


def upcoming_window(today: date) -> tuple[date, date]:
    """Закрытое окно [сегодня, сегодня + 6]."""
    return today, today + timedelta(days=UPCOMING_WINDOW_DAYS - 1)


def upcoming_payments(
    today: date,
    subscriptions: list[dict],
    debts: list[dict],
) -> list[dict]:
    """Единый список известных платежей в окне семи дней.

    Просроченные и завершённые сущности не включаются как будущие. Запись без
    даты пропускается, известная дата без суммы включается с ``amount=None``
    («сумма не указана»). Суммы между собой не складываются.
    """
    _, end = upcoming_window(today)
    items: list[dict] = []

    for subscription in subscriptions:
        if subscription.get("status") != "active":
            continue
        charge_date = subscription.get("next_charge")
        if charge_date is None or not today <= charge_date <= end:
            continue
        items.append({
            "kind": "subscription",
            "id": subscription["id"],
            "name": subscription["title"],
            "amount": subscription.get("amount"),
            "date": charge_date,
        })

    for debt in debts:
        if debt.get("archived") or debt.get("status") not in (None, "active"):
            continue
        payment_date = debt.get("next_payment_date")
        if payment_date is None or not today <= payment_date <= end:
            continue
        name = debt.get("loan_name") or debt.get("creditor") or f"Долг #{debt['id']}"
        items.append({
            "kind": "debt",
            "id": debt["id"],
            "name": name,
            "amount": debt.get("next_payment_amount"),
            "date": payment_date,
        })

    items.sort(key=lambda item: (item["date"], item["name"].casefold()))
    return items
