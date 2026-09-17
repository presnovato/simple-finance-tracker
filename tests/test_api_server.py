from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from aiohttp.test_utils import TestClient, TestServer

from finance_bot.api.server import create_app


class AllowAuthenticator:
    def authenticate(self, credential: str) -> dict:
        return {"id": 1}


async def test_health_is_public_and_api_requires_init_data():
    client = TestClient(TestServer(create_app()))
    await client.start_server()
    try:
        health = await client.get("/health")
        assert health.status == 200
        assert await health.json() == {"status": "ok"}

        protected = await client.get("/api/categories")
        assert protected.status == 401
    finally:
        await client.close()


async def test_authenticator_is_replaceable():
    client = TestClient(TestServer(create_app(AllowAuthenticator())))
    await client.start_server()
    try:
        response = await client.get("/api/categories")
        assert response.status == 200
        payload = await response.json()
        assert "Продукты" in payload["expense"]
        assert "Долги" in payload["expense"]
    finally:
        await client.close()


async def test_manual_operation_create_route_validates_and_serializes(monkeypatch):
    calls = {}

    async def create_operation(**fields):
        calls["fields"] = fields
        return ({
            "id": 42,
            "created_at": datetime(2026, 9, 17, tzinfo=timezone.utc),
            "op_date": date(2026, 9, 16),
            "type": "расход",
            "amount": Decimal("1250.50"),
            "category": "Продукты",
            "comment": "рынок",
            "note": None,
            "account": None,
            "transfer_direction": None,
            "source": "tma-ручной",
            "needs_review": False,
            "tg_message_id": None,
            "deleted_at": None,
            "subscription_id": None,
        }, None)

    monkeypatch.setattr("finance_bot.api.routes.operation_service.create_operation", create_operation)
    monkeypatch.setattr("finance_bot.api.routes.effective_today", lambda: date(2026, 9, 17))
    client = TestClient(TestServer(create_app(AllowAuthenticator())))
    await client.start_server()
    try:
        response = await client.post(
            "/api/operations",
            json={
                "type": "расход",
                "amount": "1250.50",
                "category": "Продукты",
                "op_date": "2026-09-16",
                "comment": "рынок",
            },
        )
        assert response.status == 201
        assert (await response.json())["amount"] == "1250.50"
        assert calls["fields"] == {
            "type_": "расход",
            "amount": Decimal("1250.50"),
            "category": "Продукты",
            "op_date": date(2026, 9, 16),
            "comment": "рынок",
            "account": None,
            "transfer_direction": None,
            "source": "tma-ручной",
        }
    finally:
        await client.close()


async def test_debts_summary_serializes_decimal_values(monkeypatch):
    async def debt_rows(_status=None):
        return [
            {
                "id": 1, "creditor": "Сбер", "principal": Decimal("100000"),
                "balance": Decimal("70000"), "status": "active",
            }
        ]

    async def payments():
        return [
            {
                "pay_date": date(2026, 6, 1),
                "amount": Decimal("15000"),
                "principal_amount": Decimal("10000"),
            },
            {
                "pay_date": date(2026, 7, 1),
                "amount": Decimal("25000"),
                "principal_amount": Decimal("20000"),
            },
        ]

    monkeypatch.setattr("finance_bot.api.routes.queries.list_debts", debt_rows)
    monkeypatch.setattr("finance_bot.api.routes.queries.list_debt_payments", payments)
    client = TestClient(TestServer(create_app(AllowAuthenticator())))
    await client.start_server()
    try:
        response = await client.get("/api/debts/summary")
        assert response.status == 200
        payload = await response.json()
        assert payload["total_principal"] == "100000.00"
        assert payload["total_balance"] == "70000.00"
        assert payload["total_paid"] == "30000.00"
        assert payload["progress"] == "30.00"
        assert payload["curve"][-1] == {
            "month": "2026-07", "balance": "70000.00"
        }
    finally:
        await client.close()


async def test_debts_summary_uses_current_body_balance_for_progress(monkeypatch):
    async def debt_rows(_status=None):
        return [{
            "id": 1, "creditor": "Сбер", "principal": Decimal("100000"),
            "balance": Decimal("80000"), "status": "active",
        }]

    async def payments():
        return [{"pay_date": date(2026, 9, 1), "amount": Decimal("5000")}]

    monkeypatch.setattr("finance_bot.api.routes.queries.list_debts", debt_rows)
    monkeypatch.setattr("finance_bot.api.routes.queries.list_debt_payments", payments)
    client = TestClient(TestServer(create_app(AllowAuthenticator())))
    await client.start_server()
    try:
        response = await client.get("/api/debts/summary")
        assert response.status == 200
        payload = await response.json()
        assert payload["total_balance"] == "80000.00"
        assert payload["total_paid"] == "20000.00"
        assert payload["progress"] == "20.00"
    finally:
        await client.close()


async def test_balance_endpoint_serializes_snapshot(monkeypatch):
    async def snapshot():
        return {
            "amount": Decimal("99500.00"),
            "anchor_date": date(2026, 7, 21),
            "anchor_amount": Decimal("100000.00"),
            "movement_count": 1,
        }

    monkeypatch.setattr("finance_bot.api.routes.balance_service.get_snapshot", snapshot)
    client = TestClient(TestServer(create_app(AllowAuthenticator())))
    await client.start_server()
    try:
        response = await client.get("/api/balance")
        assert response.status == 200
        assert await response.json() == {
            "amount": "99500.00",
            "anchor_date": "2026-07-21",
            "anchor_amount": "100000.00",
            "has_anchor": True,
        }
    finally:
        await client.close()


async def test_balance_endpoint_updates_anchor(monkeypatch):
    calls = {}

    async def set_anchor(amount, anchor_date):
        calls["anchor"] = (amount, anchor_date)

    async def snapshot():
        return {
            "amount": Decimal("99500.00"),
            "anchor_date": date(2026, 9, 1),
            "anchor_amount": Decimal("100000.00"),
            "movement_count": 2,
        }

    monkeypatch.setattr("finance_bot.api.routes.effective_today", lambda: date(2026, 9, 8))
    monkeypatch.setattr("finance_bot.api.routes.balance_service.set_anchor", set_anchor)
    monkeypatch.setattr("finance_bot.api.routes.balance_service.get_snapshot", snapshot)
    client = TestClient(TestServer(create_app(AllowAuthenticator())))
    await client.start_server()
    try:
        response = await client.patch(
            "/api/balance",
            json={"amount": "100000", "anchor_date": "2026-09-01"},
        )
        assert response.status == 200
        assert calls["anchor"] == (Decimal("100000.00"), date(2026, 9, 1))
        assert (await response.json())["anchor_amount"] == "100000.00"
    finally:
        await client.close()


async def test_crypto_overview_visibility_is_persisted_server_side(monkeypatch):
    state = {"visible": True}

    async def holdings():
        return []

    async def transactions():
        return []

    async def is_visible():
        return state["visible"]

    async def set_visible(visible):
        state["visible"] = visible

    monkeypatch.setattr("finance_bot.api.routes.queries.list_crypto_holdings", holdings)
    monkeypatch.setattr("finance_bot.api.routes.queries.list_crypto_transactions", transactions)
    monkeypatch.setattr("finance_bot.api.routes.crypto_service.is_overview_visible", is_visible)
    monkeypatch.setattr("finance_bot.api.routes.crypto_service.set_overview_visible", set_visible)
    client = TestClient(TestServer(create_app(AllowAuthenticator())))
    await client.start_server()
    try:
        response = await client.get("/api/crypto/overview")
        assert response.status == 200
        assert await response.json() == {"overview_visible": True}

        response = await client.get("/api/crypto")
        assert response.status == 200
        assert (await response.json())["overview_visible"] is True

        response = await client.patch("/api/crypto/overview", json={"visible": False})
        assert response.status == 200
        assert await response.json() == {"overview_visible": False}
        assert state["visible"] is False

        response = await client.get("/api/crypto")
        assert response.status == 200
        assert (await response.json())["overview_visible"] is False

        response = await client.get("/api/crypto/overview")
        assert response.status == 200
        assert await response.json() == {"overview_visible": False}
    finally:
        await client.close()


async def test_subscriptions_endpoint_serializes_monthly_cost(monkeypatch):
    charge_date = date.today() + timedelta(days=7)

    async def rows(_status="active", _next_charge=None):
        return [{
            "id": 1,
            "title": "Музыка",
            "amount": Decimal("1200.00"),
            "period": "yearly",
            "next_charge": charge_date,
            "category": None,
            "comment": "семейный план",
            "status": "active",
            "created_at": date(2026, 8, 8),
        }]

    monkeypatch.setattr("finance_bot.api.routes.queries.list_subscriptions", rows)
    async def totals(_start, _end):
        return {
            "expense": Decimal("19340.00"),
            "income": Decimal("0.00"),
            "transfer_in": Decimal("0.00"),
            "transfer_out": Decimal("0.00"),
        }

    monkeypatch.setattr("finance_bot.api.routes.queries.totals", totals)
    client = TestClient(TestServer(create_app(AllowAuthenticator())))
    await client.start_server()
    try:
        response = await client.get("/api/subscriptions")
        assert response.status == 200
        assert await response.json() == {
            "items": [{
                "id": 1,
                "title": "Музыка",
                "amount": "1200.00",
                "period": "yearly",
                "next_charge": charge_date.isoformat(),
                "category": None,
                "comment": "семейный план",
                "status": "active",
                "due": False,
                "created_at": "2026-08-08",
            }],
            "monthly_cost": "100.00",
            "yearly_cost": "1200.00",
            "month_expenses": "19340.00",
            "share_percent": "0.5",
            "upcoming": [{
                "subscription_id": 1,
                "title": "Музыка",
                "amount": "1200.00",
                "charge_date": charge_date.isoformat(),
            }],
        }
    finally:
        await client.close()


async def test_subscription_charge_route_delegates_and_serializes(monkeypatch):
    subscription = {
        "id": 5,
        "title": "Музыка",
        "amount": Decimal("1200.00"),
        "period": "yearly",
        "next_charge": date(2027, 8, 10),
        "category": "Подписки",
        "comment": None,
        "status": "active",
        "created_at": date(2026, 8, 8),
    }

    async def charge(subscription_id, *, confirmed, op_date=None, expected_next_charge=None):
        assert subscription_id == 5
        assert confirmed is True
        assert op_date == date(2026, 8, 10)
        assert expected_next_charge is None
        return {"subscription": subscription, "operation_id": 123, "stale": False}

    monkeypatch.setattr("finance_bot.api.routes.queries.charge_subscription", charge)
    client = TestClient(TestServer(create_app(AllowAuthenticator())))
    await client.start_server()
    try:
        response = await client.post(
            "/api/subscriptions/5/charge",
            json={"confirmed": True, "op_date": "2026-08-10"},
        )
        assert response.status == 200
        payload = await response.json()
        assert payload["operation_id"] == 123
        assert payload["subscription"]["due"] is False
    finally:
        await client.close()


async def test_summary_includes_transfer_balance_without_smoothing(monkeypatch):
    async def no_snapshot():
        return None

    async def totals(_start, _end):
        return {
            "expense": Decimal("30"), "income": Decimal("100"),
            "transfer_in": Decimal("25"), "transfer_out": Decimal("40"),
        }

    async def expenses_by_day(_start, _end):
        return [
            {"op_date": date(2026, 7, 1), "total": Decimal("10")},
            {"op_date": date(2026, 7, 2), "total": Decimal("20")},
        ]

    async def income_by_day(_start, _end):
        return [
            {"op_date": date(2026, 7, 1), "total": Decimal("40")},
            {"op_date": date(2026, 7, 3), "total": Decimal("60")},
        ]

    async def expenses_by_category(_start, _end):
        return [{"category": "Продукты", "total": Decimal("30")}]

    monkeypatch.setattr("finance_bot.api.routes.queries.totals", totals)
    monkeypatch.setattr("finance_bot.api.routes.queries.expenses_by_day", expenses_by_day)
    monkeypatch.setattr("finance_bot.api.routes.queries.income_by_day", income_by_day)
    monkeypatch.setattr("finance_bot.api.routes.queries.expenses_by_category", expenses_by_category)
    monkeypatch.setattr("finance_bot.api.routes.balance_service.get_snapshot", no_snapshot)
    client = TestClient(TestServer(create_app(AllowAuthenticator())))
    await client.start_server()
    try:
        response = await client.get("/api/summary?month=2026-07")
        assert response.status == 200
        payload = await response.json()
        assert payload["balance"] == "55.00"
        assert payload["average_daily"] == "15.00"
        assert payload["average_daily_income"] == "50.00"
        assert payload["period_mode"] == "month"
        assert payload["period_start"] == "2026-07-01"
        assert payload["period_end"] == "2026-07-31"
        assert payload["chart_start"] == "2026-07-01"
        assert payload["chart_end"] == "2026-07-31"
        # daily_series заполняет весь месяц: графику нужна ось 1–31, а не только
        # дни с тратами.
        assert len(payload["days"]) == 31
        assert payload["days"][0] == {
            "op_date": "2026-07-01", "expense": "10.00", "income": "40.00"
        }
        assert payload["days"][1] == {
            "op_date": "2026-07-02", "expense": "20.00", "income": "0.00"
        }
        assert payload["days"][2] == {
            "op_date": "2026-07-03", "expense": "0.00", "income": "60.00"
        }
    finally:
        await client.close()


async def test_summary_uses_balance_anchor_period_and_exact_same_day_boundary(monkeypatch):
    anchor_date = date(2026, 9, 7)
    anchor_ts = datetime(2026, 9, 7, 18, tzinfo=timezone.utc)
    calls = {}

    async def snapshot():
        return {"anchor_date": anchor_date, "anchor_ts": anchor_ts}

    async def totals(start, end, *, start_ts):
        calls["totals"] = (start, end, start_ts)
        return {
            "expense": Decimal("30"), "income": Decimal("100"),
            "transfer_in": Decimal("0"), "transfer_out": Decimal("0"),
        }

    async def expenses_by_day(start, end, *, start_ts):
        calls["days"] = (start, end, start_ts)
        return [{"op_date": date(2026, 9, 8), "total": Decimal("30")}]

    async def income_by_day(start, end, *, start_ts):
        calls["income_days"] = (start, end, start_ts)
        return [{"op_date": date(2026, 9, 9), "total": Decimal("100")}]

    async def expenses_by_category(start, end, *, start_ts):
        calls["categories"] = (start, end, start_ts)
        return [{"category": "Продукты", "total": Decimal("30")}]

    monkeypatch.setattr("finance_bot.api.routes.effective_today", lambda: date(2026, 9, 10))
    monkeypatch.setattr("finance_bot.api.routes.balance_service.get_snapshot", snapshot)
    monkeypatch.setattr("finance_bot.api.routes.queries.totals", totals)
    monkeypatch.setattr("finance_bot.api.routes.queries.expenses_by_day", expenses_by_day)
    monkeypatch.setattr("finance_bot.api.routes.queries.income_by_day", income_by_day)
    monkeypatch.setattr("finance_bot.api.routes.queries.expenses_by_category", expenses_by_category)
    client = TestClient(TestServer(create_app(AllowAuthenticator())))
    await client.start_server()
    try:
        response = await client.get("/api/summary?month=2020-01")
        assert response.status == 200
        payload = await response.json()
        assert payload["period_mode"] == "anchor"
        assert payload["period_start"] == "2026-09-07"
        assert payload["period_end"] == "2026-09-10"
        assert payload["chart_start"] == "2026-09-07"
        assert payload["chart_end"] == "2026-10-07"
        assert len(payload["days"]) == 31
        assert payload["average_daily_income"] == "100.00"
        assert payload["days"][0] == {
            "op_date": "2026-09-07", "expense": "0.00", "income": "0.00"
        }
        assert calls == {
            "totals": (anchor_date, date(2026, 9, 10), anchor_ts),
            "days": (anchor_date, date(2026, 9, 10), anchor_ts),
            "income_days": (anchor_date, date(2026, 9, 10), anchor_ts),
            "categories": (anchor_date, date(2026, 9, 10), anchor_ts),
        }
    finally:
        await client.close()


async def test_index_is_not_cached_by_webview():
    from finance_bot.api.server import TMA_DIST, create_app

    if not (TMA_DIST / "index.html").exists():
        pytest.skip("бандл TMA не собран")
    app = create_app(authenticator=lambda _: True)
    async with TestClient(TestServer(app)) as client:
        response = await client.get("/")
        assert response.status == 200
        assert "no-store" in response.headers["Cache-Control"]
