"""Архивные категории, NULL и сохранность данных (spec 01)."""

from datetime import date
from decimal import Decimal

import pytest
from aiohttp.test_utils import TestClient, TestServer

from finance_bot.api import schemas
from finance_bot.api.server import create_app
from finance_bot.config import EXPENSE_CATEGORIES
from finance_bot.database import connection, queries
from finance_bot.database import migrations as migrations_module


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


async def _expense(amount: str, category, *, type_: str = "расход") -> int:
    return await queries.insert_operation(
        date(2026, 9, 14), type_, Decimal(amount), category, None, None,
        "test", False,
    )


async def test_migrations_preserve_history_and_limits(tmp_path, monkeypatch):
    await connection.close_pool()
    database_path = tmp_path / "finance.db"
    monkeypatch.setattr(connection, "DB_PATH", str(database_path))
    monkeypatch.setattr(connection, "DB_REQUIRE_PERSISTENT_DIR", False)

    # База на версии 9 — до миграции balance_snapshots.
    full = migrations_module._MIGRATIONS
    migrations_module._MIGRATIONS = full[:9]
    try:
        await connection.init_pool()
    finally:
        migrations_module._MIGRATIONS = full

    pool = connection.get_pool()
    for op_date, type_, amount, category in (
        ("2026-09-14", "расход", 100, "Продукты"),
        ("2026-09-14", "расход", 200, "Долги"),
        ("2026-09-14", "расход", 300, "Кафе/Досуг"),
        ("2026-09-14", "расход", 400, None),
        ("2026-09-14", "доход", 500, "Подарки"),
    ):
        await pool.execute(
            "INSERT INTO operations (op_date, type, amount, category) "
            "VALUES (?, ?, ?, ?)",
            op_date, type_, amount, category,
        )
    await pool.execute(
        "INSERT INTO weekly_budget_template_categories (category, weekly_limit) "
        "VALUES ('Продукты', 4500), ('Жильё', 3000), ('Быт', 1200)"
    )
    await pool.execute(
        "INSERT INTO weekly_budget_weeks (week_start, week_end) "
        "VALUES ('2026-09-14', '2026-09-20')"
    )
    await pool.execute(
        "INSERT INTO weekly_budget_week_categories "
        "(week_start, category, weekly_limit) VALUES ('2026-09-14', 'Продукты', 4500)"
    )
    await pool.execute(
        "INSERT INTO subscriptions (title, amount, period, next_charge, category) "
        "VALUES ('Кинопоиск', 399, 'monthly', '2026-10-01', 'Продукты')"
    )
    await connection.close_pool()

    # Повторный запуск применяет balance_snapshots, но не трогает категории.
    await connection.init_pool()
    try:
        pool = connection.get_pool()
        categories = {
            row["category"]
            for row in await pool.fetch("SELECT category FROM operations")
        }
        assert categories == {"Продукты", "Долги", "Кафе/Досуг", None, "Подарки"}
        template = {
            row["category"]: row["weekly_limit"]
            for row in await pool.fetch(
                "SELECT category, weekly_limit FROM weekly_budget_template_categories"
            )
        }
        assert template == {"Продукты": 4500, "Жильё": 3000, "Быт": 1200}
        snapshot = await pool.fetch(
            "SELECT category, weekly_limit FROM weekly_budget_week_categories"
        )
        assert [(row["category"], row["weekly_limit"]) for row in snapshot] == [
            ("Продукты", 4500)
        ]
        subscription = await pool.fetchrow(
            "SELECT category FROM subscriptions WHERE title = 'Кинопоиск'"
        )
        assert subscription == {"category": "Продукты"}
        versions = {
            row["version"]
            for row in await pool.fetch("SELECT version FROM schema_migrations")
        }
        assert versions == {1, 2, 3, 4, 5, 6, 7, 8, 9, 10}
    finally:
        await connection.close_pool()


async def test_archived_expense_categories_from_operations_and_limits(sqlite_database):
    await _expense("100", "Продукты")
    await _expense("200", "Еда дома")
    await _expense("300", None)
    await _expense("400", "Продукты", type_="перевод")
    await queries.save_weekly_budget_settings(
        Decimal("5000"),
        [{"category": "Старый лимит", "limit": Decimal("1000")}],
        date(2026, 9, 14),
        date(2026, 9, 20),
    )
    # Архивная категория могла остаться только в историческом снимке недели.
    pool = connection.get_pool()
    await pool.execute(
        "INSERT INTO weekly_budget_weeks (week_start, week_end) "
        "VALUES ('2026-08-31', '2026-09-06')"
    )
    await pool.execute(
        "INSERT INTO weekly_budget_week_categories "
        "(week_start, category, weekly_limit) "
        "VALUES ('2026-08-31', 'Старый снимок', 700)"
    )

    archived = await queries.archived_expense_categories(EXPENSE_CATEGORIES)

    assert archived == ["Продукты", "Старый лимит", "Старый снимок"]


async def test_new_operation_with_archived_category_is_rejected():
    with pytest.raises(schemas.ValidationError):
        schemas.operation_create({
            "type": "расход", "amount": "100", "category": "Продукты",
            "op_date": "2026-09-14",
        }, date(2026, 9, 14))


async def test_living_and_household_limits_are_independent(sqlite_database):
    await queries.save_weekly_budget_settings(
        Decimal("10000"),
        [
            {"category": "Жильё", "limit": Decimal("3000")},
            {"category": "Быт", "limit": Decimal("1200")},
        ],
        date(2026, 9, 14),
        date(2026, 9, 20),
    )
    settings = await queries.get_weekly_budget_template()
    assert {
        item["category"]: item["limit"] for item in settings["categories"]
    } == {"Жильё": Decimal("3000.00"), "Быт": Decimal("1200.00")}


async def test_null_category_is_filtered_separately(sqlite_database):
    await _expense("100", None)
    await _expense("200", "Прочее")

    null_rows = await queries.list_operations(category_null=True)
    assert [row["amount"] for row in null_rows] == [Decimal("100.00")]

    other_rows = await queries.list_operations(category="Прочее")
    assert [row["amount"] for row in other_rows] == [Decimal("200.00")]


class AllowAuthenticator:
    def authenticate(self, _credential: str) -> dict:
        return {"id": 1}


async def test_budget_rejects_new_archived_limit_but_allows_existing(
    sqlite_database, monkeypatch
):
    await queries.save_weekly_budget_settings(
        Decimal("10000"),
        [{"category": "Продукты", "limit": Decimal("2000")}],
        date(2026, 9, 14),
        date(2026, 9, 20),
    )
    monkeypatch.setattr(
        "finance_bot.api.routes.budget.effective_today",
        lambda: date(2026, 9, 16),
    )
    client = TestClient(TestServer(create_app(AllowAuthenticator())))
    await client.start_server()
    try:
        # Существующий архивный лимит сохраняется.
        response = await client.put(
            "/api/budget/settings",
            json={
                "overall_limit": "10000.00",
                "categories": [{"category": "Продукты", "limit": "2000.00"}],
            },
        )
        assert response.status == 200

        # Новый архивный лимит отклоняется.
        response = await client.put(
            "/api/budget/settings",
            json={
                "overall_limit": "10000.00",
                "categories": [{"category": "Долги", "limit": "1000.00"}],
            },
        )
        assert response.status == 400

        # Активная категория принимается.
        response = await client.put(
            "/api/budget/settings",
            json={
                "overall_limit": "10000.00",
                "categories": [{"category": "Жильё", "limit": "3000.00"}],
            },
        )
        assert response.status == 200
    finally:
        await client.close()
