from datetime import date
from decimal import Decimal

from finance_bot.services import scheduler


async def test_evening_message_contains_due_subscriptions_and_callbacks(monkeypatch):
    today = date(2026, 8, 10)

    async def day_operations(_today):
        return []

    async def pending_review():
        return []

    async def subscriptions(_status="active", next_charge=None):
        return [
            {
                "id": 1, "title": "Netflix", "amount": Decimal("899"),
                "period": "monthly", "next_charge": date(2026, 8, 10),
                "status": "active",
            },
            {
                "id": 2, "title": "Яндекс Плюс", "amount": Decimal("399"),
                "period": "monthly", "next_charge": date(2026, 8, 8),
                "status": "active",
            },
        ]

    monkeypatch.setattr(scheduler, "effective_today", lambda: today)
    monkeypatch.setattr(scheduler.queries, "day_operations", day_operations)
    monkeypatch.setattr(scheduler.queries, "pending_review", pending_review)
    monkeypatch.setattr(scheduler.queries, "list_subscriptions", subscriptions)

    text, markup = await scheduler.build_evening_message()
    assert "💳 Списались подписки?" in text
    assert "Netflix — 899,00 ₽ (10.08)" in text
    assert "Яндекс Плюс — 399,00 ₽ (08.08, ждёт с 08.08)" in text
    assert markup is not None
    callback_data = [
        button.callback_data
        for row in markup.inline_keyboard
        for button in row
    ]
    assert "subs:yes:1:2026-08-10" in callback_data
    assert "subs:no:2:2026-08-08" in callback_data


async def test_evening_message_shows_signed_income_and_expense(monkeypatch):
    today = date(2026, 8, 10)

    async def day_operations(_today):
        return [
            {"type": "расход", "amount": Decimal("1947")},
            {"type": "доход", "amount": Decimal("5000")},
            {"type": "перевод", "amount": Decimal("300")},
        ]

    async def pending_review():
        return []

    async def subscriptions(_status="active", next_charge=None):
        return []

    monkeypatch.setattr(scheduler, "effective_today", lambda: today)
    monkeypatch.setattr(scheduler.queries, "day_operations", day_operations)
    monkeypatch.setattr(scheduler.queries, "pending_review", pending_review)
    monkeypatch.setattr(scheduler.queries, "list_subscriptions", subscriptions)

    text, _ = await scheduler.build_evening_message()

    assert "Расходы: −1 947₽" in text
    assert "Доходы: +5 000₽" in text
    assert "Всё внёс?" in text
