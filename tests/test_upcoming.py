"""Ближайшие платежи за 7 дней и воскресный отчёт (spec 04, 05)."""

from datetime import date
from decimal import Decimal

from aiohttp.test_utils import TestClient, TestServer

from finance_bot.api.server import create_app
from finance_bot.core.upcoming import upcoming_payments, upcoming_window
from finance_bot.services import scheduler, upcoming as upcoming_service
from finance_bot.services import weekly_report


def _subscription(**overrides):
    row = {
        "id": 1, "title": "Netflix", "amount": Decimal("899"),
        "period": "monthly", "next_charge": date(2026, 9, 16),
        "status": "active",
    }
    row.update(overrides)
    return row


def _debt(**overrides):
    row = {
        "id": 5, "creditor": "Сбер", "loan_name": "Кредит",
        "next_payment_date": date(2026, 9, 18),
        "next_payment_amount": Decimal("10000"),
        "status": "active", "archived": 0,
    }
    row.update(overrides)
    return row


def test_upcoming_window_is_seven_closed_days():
    assert upcoming_window(date(2026, 9, 14)) == (
        date(2026, 9, 14), date(2026, 9, 20)
    )


def test_upcoming_payments_filters_and_sorts():
    today = date(2026, 9, 14)
    subscriptions = [
        _subscription(id=1, title="Netflix", next_charge=date(2026, 9, 16)),
        _subscription(id=2, title="Прошлое", next_charge=date(2026, 9, 10)),
        _subscription(id=3, title="Далеко", next_charge=date(2026, 9, 25)),
        _subscription(id=4, title="Отменённая", next_charge=date(2026, 9, 15),
                      status="cancelled"),
    ]
    debts = [
        _debt(id=5, loan_name="Кредит", next_payment_date=date(2026, 9, 15)),
        _debt(id=6, loan_name=None, creditor="Банк",
              next_payment_date=date(2026, 9, 16), next_payment_amount=None),
        _debt(id=7, loan_name="Просрочка", next_payment_date=date(2026, 9, 1)),
        _debt(id=8, loan_name="Архив", next_payment_date=date(2026, 9, 17),
              archived=1),
        _debt(id=9, loan_name="Без даты", next_payment_date=None),
    ]

    items = upcoming_payments(today, subscriptions, debts)

    assert [(item["kind"], item["name"], item["date"]) for item in items] == [
        ("debt", "Кредит", date(2026, 9, 15)),
        ("subscription", "Netflix", date(2026, 9, 16)),
        ("debt", "Банк", date(2026, 9, 16)),
    ]
    assert items[2]["amount"] is None


def test_upcoming_payments_keep_duplicate_ids_across_kinds():
    today = date(2026, 9, 14)
    subscriptions = [
        _subscription(id=5, title="Netflix", next_charge=date(2026, 9, 15)),
    ]
    debts = [
        _debt(id=5, loan_name="Кредит", next_payment_date=date(2026, 9, 16)),
    ]

    items = upcoming_payments(today, subscriptions, debts)

    # Одинаковый id у подписки и кредита различим только парой kind + id.
    assert [(item["kind"], item["id"]) for item in items] == [
        ("subscription", 5),
        ("debt", 5),
    ]


def test_upcoming_payments_exclude_closed_debts_and_inactive_subscriptions():
    today = date(2026, 9, 14)
    subscriptions = [
        _subscription(status="cancelled", next_charge=date(2026, 9, 15)),
    ]
    debts = [
        _debt(status="closed", next_payment_date=date(2026, 9, 15)),
    ]

    assert upcoming_payments(today, subscriptions, debts) == []


async def test_upcoming_service_isolates_source_errors(monkeypatch):
    today = date(2026, 9, 14)

    async def broken(_status="active"):
        raise RuntimeError("подписки недоступны")

    async def debts(_status="active"):
        return [_debt()]

    monkeypatch.setattr(upcoming_service.queries, "list_subscriptions", broken)
    monkeypatch.setattr(upcoming_service.queries, "list_debts", debts)

    items, errors = await upcoming_service.get_upcoming(today)

    assert errors == ["subscriptions"]
    assert [item["kind"] for item in items] == ["debt"]


class AllowAuthenticator:
    def authenticate(self, _credential: str) -> dict:
        return {"id": 1}


async def test_upcoming_endpoint_serializes(monkeypatch):
    today = date(2026, 9, 14)

    async def fake(today_arg):
        assert today_arg == today
        return ([{
            "kind": "debt", "id": 5, "name": "Кредит",
            "amount": Decimal("10000"), "date": date(2026, 9, 18),
        }], [])

    monkeypatch.setattr("finance_bot.api.routes.upcoming.effective_today", lambda: today)
    monkeypatch.setattr("finance_bot.api.routes.upcoming.upcoming_service.get_upcoming", fake)
    client = TestClient(TestServer(create_app(AllowAuthenticator())))
    await client.start_server()
    try:
        response = await client.get("/api/upcoming")
        assert response.status == 200
        payload = await response.json()
        assert payload["date_from"] == "2026-09-14"
        assert payload["date_to"] == "2026-09-20"
        assert payload["items"] == [{
            "kind": "debt", "id": 5, "name": "Кредит",
            "amount": "10000.00", "date": "2026-09-18",
        }]
        assert payload["errors"] == []
    finally:
        await client.close()


async def test_sunday_lines_show_period_budget_categories_and_payments(monkeypatch):
    today = date(2026, 9, 20)  # воскресенье

    async def categories(_start, _end):
        return [
            {"category": "Еда дома", "total": Decimal("5000")},
            {"category": "Транспорт", "total": Decimal("3000")},
            {"category": "Досуг", "total": Decimal("1000")},
            {"category": "Прочее", "total": Decimal("500")},
        ]

    async def budget(today=None):
        return {
            "configured": True,
            "overall": {
                "limit": Decimal("15000"), "spent": Decimal("9500"),
                "remaining": Decimal("5500"), "percent": Decimal("63.33"),
                "status": "ok",
            },
        }

    async def payments(_today):
        return ([{
            "kind": "subscription", "id": 1, "name": "Netflix",
            "amount": Decimal("899"), "date": date(2026, 9, 22),
        }], [])

    monkeypatch.setattr(weekly_report.queries, "expenses_by_category", categories)
    monkeypatch.setattr(weekly_report.budget_service, "get_budget", budget)
    monkeypatch.setattr(weekly_report.upcoming_service, "get_upcoming", payments)

    lines = await weekly_report.sunday_lines(today)
    text = "\n".join(lines)

    assert "Неделя 14.09–20.09" in text
    assert "Расходы: 9 500₽ из 15 000₽" in text
    assert "Остаток: 5 500₽" in text
    assert "Еда дома 5 000₽" in text
    assert "Транспорт 3 000₽" in text
    assert "Досуг 1 000₽" in text
    # Показываем только три крупнейшие категории.
    assert "Прочее" not in text
    assert "Netflix — 899₽" in text


async def test_sunday_lines_without_budget_show_actual_expenses(monkeypatch):
    today = date(2026, 9, 20)

    async def categories(_start, _end):
        return [{"category": "Еда дома", "total": Decimal("2000")}]

    async def budget(today=None):
        return {"configured": False, "overall": None}

    async def payments(_today):
        return ([], [])

    monkeypatch.setattr(weekly_report.queries, "expenses_by_category", categories)
    monkeypatch.setattr(weekly_report.budget_service, "get_budget", budget)
    monkeypatch.setattr(weekly_report.upcoming_service, "get_upcoming", payments)

    text = "\n".join(await weekly_report.sunday_lines(today))

    assert "Расходы за неделю: 2 000₽" in text
    assert "лимит не задан" in text


async def test_evening_message_adds_sunday_block_only_on_sunday(monkeypatch):
    async def day_operations(_today):
        return []

    async def pending_review():
        return []

    async def subscriptions(_status="active", next_charge=None):
        return []

    async def sunday(_today):
        return ["SUN-BLOCK"]

    async def empty(_today):
        return []

    monkeypatch.setattr(scheduler.queries, "day_operations", day_operations)
    monkeypatch.setattr(scheduler.queries, "pending_review", pending_review)
    monkeypatch.setattr(scheduler.queries, "list_subscriptions", subscriptions)
    monkeypatch.setattr(scheduler.budget_service, "evening_budget_lines", empty)
    monkeypatch.setattr(scheduler.weekly_report, "sunday_lines", sunday)

    monkeypatch.setattr(scheduler, "effective_today", lambda: date(2026, 9, 20))
    sunday_text, _ = await scheduler.build_evening_message()
    assert "SUN-BLOCK" in sunday_text

    monkeypatch.setattr(scheduler, "effective_today", lambda: date(2026, 9, 21))
    monday_text, _ = await scheduler.build_evening_message()
    assert "SUN-BLOCK" not in monday_text
