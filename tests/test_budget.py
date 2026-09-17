from datetime import date, datetime
from decimal import Decimal

import pytest
from aiohttp.test_utils import TestClient, TestServer

from finance_bot.api.server import create_app
from finance_bot.core.budget import budget_line, budget_status, week_bounds
from finance_bot.core.dates import TZ, effective_today
from finance_bot.database import connection, queries
from finance_bot.services import budget as budget_service


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


def _at(y, m, d, hh, mm=0):
    return TZ.localize(datetime(y, m, d, hh, mm))


async def _expense(
    amount: str,
    *,
    op_date: date = date(2026, 9, 14),
    category: str | None = "Продукты",
    type_: str = "расход",
    needs_review: bool = False,
) -> int:
    return await queries.insert_operation(
        op_date, type_, Decimal(amount), category, None, None,
        "test", needs_review,
    )


def test_budget_week_uses_effective_monday_boundary():
    assert effective_today(_at(2026, 9, 14, 2, 59)) == date(2026, 9, 13)
    assert effective_today(_at(2026, 9, 14, 3, 0)) == date(2026, 9, 14)
    assert week_bounds(date(2026, 9, 16)) == (
        date(2026, 9, 14), date(2026, 9, 20)
    )


@pytest.mark.parametrize(
    ("spent", "expected_percent", "expected_status"),
    [
        ("7999", "79.99", "ok"),
        ("8000", "80.00", "warning"),
        ("9999", "99.99", "warning"),
        ("10000", "100.00", "exceeded"),
        ("10500", "105.00", "exceeded"),
    ],
)
def test_budget_percentages_and_statuses(spent, expected_percent, expected_status):
    row = budget_line("Продукты", Decimal("10000"), Decimal(spent))
    assert row["percent"] == Decimal(expected_percent)
    assert row["status"] == expected_status
    assert budget_status(row["percent"]) == expected_status


def test_saving_threshold_is_strictly_greater_than_one_thousand():
    assert Decimal("1000.01") > Decimal("1000.00")
    assert not Decimal("1000.00") > Decimal("1000.00")


def test_budget_category_without_limit_has_no_category_status():
    row = budget_line("Продукты", None, Decimal("123.45"))

    assert row == {
        "category": "Продукты",
        "limit": None,
        "spent": Decimal("123.45"),
        "remaining": None,
        "percent": None,
        "status": None,
    }


async def test_budget_counts_only_selected_active_expenses(sqlite_database):
    await budget_service.save_settings(
        Decimal("5000"),
        [
            {"category": "Продукты", "limit": Decimal("3000")},
            {"category": "Прочее", "limit": Decimal("1000")},
            {"category": "Жильё", "limit": Decimal("2000")},
        ],
        today=date(2026, 9, 16),
    )
    await _expense("100", category="Продукты", needs_review=True)
    await _expense("50", category=None)
    await _expense("700", category="Жильё")
    await _expense("500", category="Транспорт")
    await _expense("300", category="Продукты", type_="перевод")
    deleted_id = await _expense("900", category="Продукты")
    await queries.soft_delete_operation(deleted_id)

    report = await budget_service.get_budget(today=date(2026, 9, 16))

    assert report["selected_spent"] == Decimal("850.00")
    assert report["overall"]["spent"] == Decimal("850.00")
    assert {
        item["category"]: item["spent"] for item in report["categories"]
    } == {
        "Жильё": Decimal("700.00"),
        "Продукты": Decimal("100.00"),
        "Прочее": Decimal("50.00"),
    }


async def test_budget_snapshot_history_and_no_rollover(sqlite_database):
    first_week = date(2026, 9, 14)
    next_week = date(2026, 9, 21)
    await budget_service.save_settings(
        Decimal("1000"),
        [{"category": "Продукты", "limit": Decimal("700")}],
        today=first_week,
    )
    await _expense("600", op_date=date(2026, 9, 20))

    current = await budget_service.get_budget(today=next_week)
    assert current["week_start"] == next_week
    assert current["categories"][0]["limit"] == Decimal("700.00")
    assert current["selected_spent"] == Decimal("0.00")

    await budget_service.save_settings(
        Decimal("2000"),
        [{"category": "Продукты", "limit": Decimal("1500")}],
        today=next_week,
    )
    historical = await budget_service.get_budget(
        first_week, today=next_week
    )
    changed_current = await budget_service.get_budget(today=next_week)
    assert historical["overall"]["limit"] == Decimal("1000.00")
    assert historical["categories"][0]["limit"] == Decimal("700.00")
    assert historical["selected_spent"] == Decimal("600.00")
    assert changed_current["overall"]["limit"] == Decimal("2000.00")
    assert changed_current["selected_spent"] == Decimal("0.00")


async def test_budget_overall_only_tracks_all_expenses_without_category_limits(
    sqlite_database,
):
    today = date(2026, 9, 16)
    await budget_service.save_settings(
        Decimal("2000"),
        [],
        today=today,
    )
    await _expense("999", op_date=today, category="Продукты")
    await _expense("100", op_date=today, category=None)
    await _expense("50", op_date=today, category="Транспорт", type_="перевод")
    deleted_id = await _expense("700", op_date=today, category="Продукты")
    await queries.soft_delete_operation(deleted_id)

    report = await budget_service.get_budget(today=today)
    lines = await budget_service.evening_budget_lines(today)
    assert report["overall"]["spent"] == Decimal("1099.00")
    assert report["selected_spent"] == Decimal("1099.00")
    assert report["categories"] == []
    assert lines == []
    notifications = await connection.get_pool().fetch(
        "SELECT * FROM weekly_budget_notifications"
    )
    assert notifications == []


async def test_budget_selected_category_can_skip_individual_limit(sqlite_database):
    today = date(2026, 9, 16)
    await budget_service.save_settings(
        Decimal("2000"),
        [
            {"category": "Продукты", "limit": None},
            {"category": "Транспорт", "limit": Decimal("500")},
        ],
        today=today,
    )
    await _expense("125", op_date=today, category="Продукты")
    await _expense("75", op_date=today, category="Транспорт")

    report = await budget_service.get_budget(today=today)
    rows = {item["category"]: item for item in report["categories"]}

    assert report["selected_spent"] == Decimal("200.00")
    assert report["category_limits_total"] == Decimal("500.00")
    assert rows["Продукты"] == {
        "category": "Продукты",
        "limit": None,
        "spent": Decimal("125.00"),
        "remaining": None,
        "percent": None,
        "status": None,
    }
    assert rows["Транспорт"]["remaining"] == Decimal("425.00")


class AllowAuthenticator:
    def authenticate(self, credential: str) -> dict:
        return {"id": 1}


async def test_budget_api_auth_and_validation_are_owner_only(sqlite_database, monkeypatch):
    monkeypatch.setattr(
        "finance_bot.api.routes.effective_today", lambda: date(2026, 9, 16)
    )
    client = TestClient(TestServer(create_app(AllowAuthenticator())))
    await client.start_server()
    try:
        response = await client.get("/api/budget")
        assert response.status == 200
        assert (await response.json())["configured"] is False

        response = await client.put(
            "/api/budget/settings",
            json={
                "overall_limit": "10000.00",
                "categories": [{"category": "Продукты", "limit": "5000.00"}],
            },
        )
        assert response.status == 200
        assert (await response.json())["overall_limit"] == "10000.00"

        response = await client.put(
            "/api/budget/settings",
            json={
                "overall_limit": "8000.00",
                "categories": [{"category": "Продукты"}],
            },
        )
        assert response.status == 200
        assert (await response.json())["categories"] == [
            {"category": "Продукты", "limit": None}
        ]

        response = await client.put(
            "/api/budget/settings",
            json={"overall_limit": "9000.00"},
        )
        assert response.status == 200
        assert (await response.json())["categories"] == []

        for payload in (
            {"overall_limit": 10000, "categories": []},
            {"overall_limit": None, "categories": []},
            {"overall_limit": "10000", "categories": [{"category": "Неизвестно", "limit": "1"}]},
            {"overall_limit": "10000", "categories": [{"category": "Продукты", "limit": 1}]},
            {"overall_limit": "10000", "categories": [{"category": "Продукты", "limit": "0"}]},
        ):
            response = await client.put("/api/budget/settings", json=payload)
            assert response.status == 400

        response = await client.get("/api/budget?week_start=2026-09-15")
        assert response.status == 400
        response = await client.get("/api/budget?week_start=2026-09-21")
        assert response.status == 400

        response = await client.put(
            "/api/budget/settings",
            json={
                "overall_limit": "10000.00",
                "categories": [{"category": "Неизвестно", "limit": "5000.00"}],
            },
        )
        assert response.status == 400
        settings = await client.get("/api/budget/settings")
        assert (await settings.json())["categories"] == []
    finally:
        await client.close()


async def test_budget_api_requires_authentication():
    client = TestClient(TestServer(create_app()))
    await client.start_server()
    try:
        response = await client.get("/api/budget")
        assert response.status == 401
    finally:
        await client.close()


class FakeBot:
    def __init__(self):
        self.messages = []

    async def send_message(self, *args, **kwargs):
        self.messages.append((args, kwargs))


async def test_budget_notifications_claim_once_and_combine_thresholds(sqlite_database, monkeypatch):
    today = date(2026, 9, 16)
    await budget_service.save_settings(
        Decimal("1000"),
        [{"category": "Продукты", "limit": Decimal("2000")}],
        today=today,
    )
    await _expense("1100", op_date=today)
    bot = FakeBot()
    monkeypatch.setattr(budget_service, "effective_today", lambda: today)

    await budget_service.notify_after_new_expense(bot, today)
    await budget_service.notify_after_new_expense(bot, today)

    assert len(bot.messages) == 1
    assert "80%" in bot.messages[0][0][1]
    assert "100%" in bot.messages[0][0][1]
    claimed = await connection.get_pool().fetch(
        "SELECT kind FROM weekly_budget_notifications ORDER BY kind"
    )
    assert claimed == [
        {"kind": "threshold_100"}, {"kind": "threshold_80"}
    ]


async def test_sunday_congratulation_is_strict_and_idempotent(sqlite_database):
    sunday = date(2026, 9, 20)
    await budget_service.save_settings(
        Decimal("2000"),
        [{"category": "Продукты", "limit": Decimal("2000")}],
        today=sunday,
    )
    await _expense("999", op_date=sunday)
    lines = await budget_service.evening_budget_lines(sunday)
    assert any("сэкономить" in line for line in lines)
    assert not await budget_service.evening_budget_lines(sunday)

    await budget_service.save_settings(
        Decimal("2000"),
        [{"category": "Продукты", "limit": Decimal("2000")}],
        today=date(2026, 9, 27),
    )
    await _expense("1000", op_date=date(2026, 9, 27))
    small_saving = await budget_service.evening_budget_lines(date(2026, 9, 27))
    assert not any("сэкономить" in line for line in small_saving)
