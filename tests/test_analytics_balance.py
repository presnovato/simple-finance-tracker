"""История «денег на руках» и сравнение категорий (spec 06)."""

from datetime import date
from decimal import Decimal

import pytest
from aiohttp.test_utils import TestClient, TestServer

from finance_bot.api.server import create_app
from finance_bot.core.analytics import comparison_periods
from finance_bot.database import connection, queries
from finance_bot.services import balance_history


@pytest.fixture
async def sqlite_database(tmp_path, monkeypatch):
    await connection.close_pool()
    monkeypatch.setattr(connection, "DB_PATH", str(tmp_path / "finance.db"))
    monkeypatch.setattr(connection, "DB_REQUIRE_PERSISTENT_DIR", False)
    await connection.init_pool()
    try:
        yield tmp_path / "finance.db"
    finally:
        await connection.close_pool()


def test_comparison_periods_for_open_month_uses_same_day():
    start, end = date(2026, 9, 1), date(2026, 9, 30)
    current = comparison_periods(start, end, date(2026, 9, 12))
    assert current == (
        date(2026, 9, 1), date(2026, 9, 12),
        date(2026, 8, 1), date(2026, 8, 12),
    )


def test_comparison_periods_clamps_short_previous_month():
    # 31 марта → сравниваем с 28 февраля (последний день месяца).
    current = comparison_periods(
        date(2026, 3, 1), date(2026, 3, 31), date(2026, 3, 31)
    )
    assert current == (
        date(2026, 3, 1), date(2026, 3, 31),
        date(2026, 2, 1), date(2026, 2, 28),
    )


def test_comparison_periods_for_closed_month_uses_full_previous():
    current = comparison_periods(
        date(2026, 5, 1), date(2026, 5, 31), date(2026, 9, 12)
    )
    assert current == (
        date(2026, 5, 1), date(2026, 5, 31),
        date(2026, 4, 1), date(2026, 4, 30),
    )


async def test_upsert_balance_snapshot_is_idempotent(sqlite_database):
    day = date(2026, 9, 14)
    await queries.upsert_balance_snapshot(day, Decimal("1000.00"))
    await queries.upsert_balance_snapshot(day, Decimal("2500.50"))

    rows = await queries.list_balance_snapshots(day, day)
    assert len(rows) == 1
    assert rows[0]["snapshot_date"] == day
    assert rows[0]["amount"] == Decimal("2500.50")


async def test_store_daily_snapshot_uses_balance_service(sqlite_database, monkeypatch):
    day = date(2026, 9, 14)

    async def snapshot():
        return {"amount": Decimal("777.00")}

    monkeypatch.setattr(balance_history.balance_service, "get_snapshot", snapshot)
    stored = await balance_history.store_daily_snapshot(day)
    assert stored is not None
    assert stored["amount"] == Decimal("777.00")

    rows = await queries.list_balance_snapshots(day, day)
    assert rows[0]["amount"] == Decimal("777.00")


async def test_store_daily_snapshot_without_anchor_writes_nothing(
    sqlite_database, monkeypatch
):
    day = date(2026, 9, 14)

    async def no_snapshot():
        return None

    monkeypatch.setattr(balance_history.balance_service, "get_snapshot", no_snapshot)
    assert await balance_history.store_daily_snapshot(day) is None
    assert await queries.list_balance_snapshots(day, day) == []


class AllowAuthenticator:
    def authenticate(self, _credential: str) -> dict:
        return {"id": 1}


async def test_balance_history_endpoint(monkeypatch):
    async def rows(_start, _end):
        return [
            {"snapshot_date": date(2026, 9, 14), "amount": Decimal("1000")},
            {"snapshot_date": date(2026, 9, 16), "amount": Decimal("1200")},
        ]

    monkeypatch.setattr("finance_bot.database.queries.list_balance_snapshots", rows)
    client = TestClient(TestServer(create_app(AllowAuthenticator())))
    await client.start_server()
    try:
        response = await client.get(
            "/api/balance/history?date_from=2026-09-01&date_to=2026-09-30"
        )
        assert response.status == 200
        payload = await response.json()
        # Пропуск 15.09 сохраняем как разрыв: отдаём только реальные снимки.
        assert payload["items"] == [
            {"date": "2026-09-14", "amount": "1000.00"},
            {"date": "2026-09-16", "amount": "1200.00"},
        ]
    finally:
        await client.close()


async def test_balance_history_endpoint_rejects_long_period():
    client = TestClient(TestServer(create_app(AllowAuthenticator())))
    await client.start_server()
    try:
        response = await client.get(
            "/api/balance/history?date_from=2020-01-01&date_to=2026-01-01"
        )
        assert response.status == 400
    finally:
        await client.close()


async def test_category_comparison_endpoint(monkeypatch):
    async def categories(start, end):
        if start == date(2026, 9, 1):
            return [
                {"category": "Еда дома", "total": Decimal("1000")},
                {"category": "Досуг", "total": Decimal("500")},
            ]
        return [{"category": "Еда дома", "total": Decimal("400")}]

    monkeypatch.setattr("finance_bot.api.routes.analytics.effective_today",
                        lambda: date(2026, 9, 12))
    monkeypatch.setattr("finance_bot.database.queries.expenses_by_category", categories)
    client = TestClient(TestServer(create_app(AllowAuthenticator())))
    await client.start_server()
    try:
        response = await client.get("/api/analytics/categories?month=2026-09")
        assert response.status == 200
        payload = await response.json()
        assert payload["period_end"] == "2026-09-12"
        assert payload["previous_end"] == "2026-08-12"
        by_name = {item["category"]: item for item in payload["categories"]}
        assert by_name["Еда дома"]["previous"] == "400.00"
        assert by_name["Еда дома"]["change"] == "600.00"
        assert by_name["Еда дома"]["percent"] == "150.0"
        assert by_name["Досуг"]["previous"] == "0.00"
        assert by_name["Досуг"]["percent"] is None
        assert by_name["Досуг"]["appeared"] is True
    finally:
        await client.close()
