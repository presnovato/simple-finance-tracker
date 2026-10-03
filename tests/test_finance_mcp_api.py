from datetime import date, datetime
from decimal import Decimal

import pytest
from aiohttp.test_utils import TestClient, TestServer

from finance_bot.api import auth
from finance_bot.api.server import create_app
from finance_bot.core.dates import effective_today
from finance_bot.database import connection, queries
from finance_bot.api.routes import integrations as routes
import pytz


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


async def _insert(
    op_date: date,
    type_: str,
    amount: str,
    *,
    category: str | None = None,
    comment: str | None = None,
    account: str | None = None,
    note: str | None = None,
    needs_review: bool = False,
    transfer_direction: str | None = None,
) -> int:
    op_id = await queries.insert_operation(
        op_date, type_, Decimal(amount), category, comment, account,
        "mcp-test", needs_review, transfer_direction,
    )
    if note is not None:
        await connection.get_pool().execute(
            "UPDATE operations SET note = ? WHERE id = ?", note, op_id
        )
    return op_id


def _client():
    return TestClient(TestServer(create_app()))


async def test_finance_agent_auth_is_separate_and_fail_closed(monkeypatch):
    monkeypatch.setattr(auth, "FINANCE_AGENT_TOKEN", "finance-test-token")
    async with _client() as client:
        missing = await client.get("/api/integrations/finance/snapshot")
        wrong = await client.get(
            "/api/integrations/finance/snapshot",
            headers={"Authorization": "Bearer wrong"},
        )
        valid_on_tma = await client.get(
            "/api/categories",
            headers={"Authorization": "Bearer finance-test-token"},
        )
        write_on_tma = await client.post(
            "/api/operations",
            json={"op_date": "2026-09-28", "type": "расход", "amount": "1"},
            headers={"Authorization": "Bearer finance-test-token"},
        )
        assert missing.status == 401
        assert wrong.status == 401
        assert valid_on_tma.status == 401
        assert write_on_tma.status == 401

    monkeypatch.setattr(auth, "FINANCE_AGENT_TOKEN", "")
    async with _client() as client:
        response = await client.get("/api/integrations/finance/snapshot")
        assert response.status == 503
        assert (await response.json())["error"] == "integration_not_configured"


async def test_week_summary_filters_dates_deleted_rows_and_formats_categories(
    sqlite_database, monkeypatch
):
    monkeypatch.setattr(auth, "FINANCE_AGENT_TOKEN", "finance-test-token")
    monkeypatch.setattr(
        "finance_bot.api.routes.integrations.effective_today", lambda: date(2026, 9, 28)
    )
    await _insert(
        date(2026, 9, 21), "расход", "120.50", category="Продукты",
        needs_review=True,
    )
    await _insert(
        date(2026, 9, 27), "доход", "250", category="Услуги"
    )
    await _insert(
        date(2026, 9, 22), "перевод", "10", transfer_direction="in"
    )
    await _insert(
        date(2026, 9, 23), "перевод", "5", transfer_direction="out"
    )
    deleted = await _insert(
        date(2026, 9, 27), "расход", "90", category="Кафе/Досуг"
    )
    await queries.delete_operation(deleted)
    await _insert(
        date(2026, 9, 20), "расход", "40", category="Продукты"
    )

    async with _client() as client:
        response = await client.get(
            "/api/integrations/finance/week?week_start=2026-09-21",
            headers={"Authorization": "Bearer finance-test-token"},
        )
        assert response.status == 200
        payload = await response.json()
    assert payload["week_start"] == "2026-09-21"
    assert payload["week_end"] == "2026-09-27"
    assert payload["as_of"] == "2026-09-28"
    assert payload["is_current_week"] is False
    assert payload["operation_count"] == 4
    assert payload["needs_review_count"] == 1
    assert payload["expense"] == "120.50"
    assert payload["income"] == "250.00"
    assert payload["transfer_in"] == "10.00"
    assert payload["transfer_out"] == "5.00"
    assert payload["expense_by_category"] == [
        {"category": "Продукты", "total": "120.50"}
    ]
    assert payload["income_by_category"] == [
        {"category": "Услуги", "total": "250.00"}
    ]
    assert "полнота ручного учёта не подтверждается" in payload["coverage_note"]


@pytest.mark.parametrize(
    ("query", "message"),
    [
        ("week_start=2026-09-22", "понедельником"),
        ("week_start=2026-10-05", "будущую неделю"),
        ("week_start=20260928", "YYYY-MM-DD"),
        ("week_start=invalid", "YYYY-MM-DD"),
    ],
)
async def test_week_summary_validates_week_start(query, message, monkeypatch):
    monkeypatch.setattr(auth, "FINANCE_AGENT_TOKEN", "finance-test-token")
    monkeypatch.setattr(
        "finance_bot.api.routes.integrations.effective_today", lambda: date(2026, 9, 28)
    )
    async with _client() as client:
        response = await client.get(
            f"/api/integrations/finance/week?{query}",
            headers={"Authorization": "Bearer finance-test-token"},
        )
        assert response.status == 400
        payload = await response.json()
    assert message in payload["error"]


@pytest.mark.parametrize(
    ("moment", "expected_as_of", "expected_week_start"),
    [
        (datetime(2026, 9, 28, 2, 59), date(2026, 9, 27), date(2026, 9, 21)),
        (datetime(2026, 9, 28, 3, 0), date(2026, 9, 28), date(2026, 9, 28)),
    ],
)
async def test_default_week_uses_moscow_three_am_boundary_and_empty_week(
    sqlite_database, monkeypatch, moment, expected_as_of, expected_week_start
):
    monkeypatch.setattr(auth, "FINANCE_AGENT_TOKEN", "finance-test-token")
    moscow = pytz.timezone("Europe/Moscow")
    monkeypatch.setattr(
        routes, "effective_today", lambda: effective_today(moscow.localize(moment))
    )
    async with _client() as client:
        response = await client.get(
            "/api/integrations/finance/week",
            headers={"Authorization": "Bearer finance-test-token"},
        )
        assert response.status == 200
        payload = await response.json()
    assert payload["as_of"] == expected_as_of.isoformat()
    assert payload["week_start"] == expected_week_start.isoformat()
    assert payload["operation_count"] == 0
    assert payload["needs_review_count"] == 0
    assert payload["income"] == payload["expense"] == "0.00"
    assert payload["income_by_category"] == []
    assert payload["expense_by_category"] == []


async def test_snapshot_preserves_unknown_values_and_gets_do_not_mutate_budget(
    sqlite_database, monkeypatch
):
    monkeypatch.setattr(auth, "FINANCE_AGENT_TOKEN", "finance-test-token")
    await _insert(date(2026, 9, 28), "расход", "50", category="Продукты")
    pool = connection.get_pool()
    before = await pool.fetchrow("SELECT count(*) AS count FROM weekly_budget_weeks")
    before_changes = await pool.fetchrow("SELECT total_changes() AS count")

    async with _client() as client:
        headers = {"Authorization": "Bearer finance-test-token"}
        week = await client.get("/api/integrations/finance/week", headers=headers)
        snapshot = await client.get("/api/integrations/finance/snapshot", headers=headers)
        operations = await client.get(
            "/api/integrations/finance/operations?date_from=2026-09-28&date_to=2026-09-28",
            headers=headers,
        )
        snapshot_payload = await snapshot.json()
    assert week.status == snapshot.status == operations.status == 200
    current = await pool.fetchrow("SELECT count(*) AS count FROM weekly_budget_weeks")
    after_changes = await pool.fetchrow("SELECT total_changes() AS count")
    assert current["count"] == before["count"]
    assert after_changes["count"] == before_changes["count"]
    assert snapshot_payload["cash"]["total"] is None
    assert snapshot_payload["cash"]["reserved"] is None
    assert "не задан якорь" in snapshot_payload["cash"]["total_unavailable_reason"]


async def test_operations_page_filters_and_whitelists_fields(sqlite_database, monkeypatch):
    monkeypatch.setattr(auth, "FINANCE_AGENT_TOKEN", "finance-test-token")
    await _insert(
        date(2026, 9, 25), "расход", "12.34", category="Продукты",
        comment="рынок", account="Карта", note="заметка", needs_review=True,
    )
    await _insert(
        date(2026, 9, 24), "расход", "8", category="Кафе/Досуг",
        comment="кофе",
    )
    async with _client() as client:
        response = await client.get(
            "/api/integrations/finance/operations?date_from=2026-09-24&date_to=2026-09-25"
            "&type=%D1%80%D0%B0%D1%81%D1%85%D0%BE%D0%B4&category=%D0%9F%D1%80%D0%BE%D0%B4%D1%83%D0%BA%D1%82%D1%8B"
            "&needs_review=true",
            headers={"Authorization": "Bearer finance-test-token"},
        )
        assert response.status == 200
        payload = await response.json()
    assert len(payload["items"]) == 1
    item = payload["items"][0]
    assert item == {
        "id": item["id"],
        "op_date": "2026-09-25",
        "type": "расход",
        "amount": "12.34",
        "category": "Продукты",
        "account": "Карта",
        "comment": "рынок",
        "note": "заметка",
        "transfer_direction": None,
        "needs_review": True,
    }
    assert "source" not in item
    assert "created_at" not in item


async def test_operations_page_caps_period_and_uses_cursor(sqlite_database, monkeypatch):
    monkeypatch.setattr(auth, "FINANCE_AGENT_TOKEN", "finance-test-token")
    for day in range(1, 42):
        await _insert(
            date(2026, 9, 1), "расход", str(day), category="Продукты"
        )
    async with _client() as client:
        headers = {"Authorization": "Bearer finance-test-token"}
        too_wide = await client.get(
            "/api/integrations/finance/operations?date_from=2026-09-01&date_to=2026-10-02",
            headers=headers,
        )
        invalid_date = await client.get(
            "/api/integrations/finance/operations?date_from=20260901&date_to=2026-09-30",
            headers=headers,
        )
        first = await client.get(
            "/api/integrations/finance/operations?date_from=2026-09-01&date_to=2026-09-30",
            headers=headers,
        )
        cursor = (await first.json())["next_cursor"]
        second = await client.get(
            "/api/integrations/finance/operations?date_from=2026-09-01&date_to=2026-09-30"
            f"&before={cursor}",
            headers=headers,
        )
        too_wide_payload = await too_wide.json()
        invalid_date_payload = await invalid_date.json()
        first_payload = await first.json()
        second_payload = await second.json()
    assert too_wide.status == 400
    assert too_wide_payload["error"] == "период не может превышать 31 день"
    assert invalid_date.status == 400
    assert "YYYY-MM-DD" in invalid_date_payload["error"]
    assert len(first_payload["items"]) == 40
    assert cursor
    assert len(second_payload["items"]) == 1
