"""Seed an isolated SQLite fixture for a local TMA preview."""

import asyncio
import logging
import os
import sqlite3
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

# При запуске файлом (`python tools/...`) корень репозитория не попадает в
# sys.path — добавляем его, чтобы импортировать finance_bot и tools.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from finance_bot.config import DB_PATH  # noqa: E402
from finance_bot.core.budget import week_bounds  # noqa: E402
from finance_bot.core.dates import effective_today  # noqa: E402
from finance_bot.database import connection, queries  # noqa: E402
from finance_bot.services import budget as budget_service  # noqa: E402
from tools._mock_guard import (  # noqa: E402
    MockGuardError,
    require_mock_environment,
)

logger = logging.getLogger(__name__)
MARKER = Path(os.getenv("MOCK_DB_MARKER", "/data/.mock-ready"))
MOCK_DB_SETTING = "mock_database"


def _anchor_date() -> date:
    value = os.getenv("MOCK_ANCHOR_DATE")
    return date.fromisoformat(value) if value else effective_today()


def _database_is_mock(database_path: Path) -> bool:
    """True, если файл помечен как mock-база (или файла нет)."""
    if not database_path.is_file():
        return True
    try:
        connection = sqlite3.connect(database_path)
    except sqlite3.Error:
        return False
    try:
        row = connection.execute(
            f"SELECT value FROM settings WHERE key = '{MOCK_DB_SETTING}'"
        ).fetchone()
    except sqlite3.Error:
        # Нечитаемый или повреждённый файл считаем не-mock: пусть удалит человек.
        return False
    finally:
        connection.close()
    return bool(row and row[0] == "1")


def _reset_database_file() -> None:
    database_path = Path(DB_PATH)
    if not _database_is_mock(database_path):
        raise MockGuardError(
            f"{database_path} не помечена как mock-база "
            f"(нет settings.{MOCK_DB_SETTING}=1). Удали файл вручную, если уверен."
        )
    for suffix in ("", "-wal", "-shm"):
        candidate = Path(f"{database_path}{suffix}")
        candidate.unlink(missing_ok=True)


async def _insert_expense(
    op_date: date,
    amount: str,
    category: str | None,
    *,
    needs_review: bool = False,
) -> None:
    await queries.insert_operation(
        op_date=op_date,
        type_="расход",
        amount=Decimal(amount),
        category=category,
        comment="mock fixture",
        account="Mock-карта",
        source="mock-db",
        needs_review=needs_review,
    )


async def _seed(today: date) -> None:
    current_start, current_end = week_bounds(today)
    previous_start = current_start - timedelta(days=7)
    previous_end = previous_start + timedelta(days=6)

    await budget_service.save_settings(
        Decimal("10000.00"),
        [
            {"category": "Продукты", "limit": Decimal("4500.00")},
            {"category": "Транспорт", "limit": Decimal("1800.00")},
            {"category": "Кафе/Досуг", "limit": Decimal("1500.00")},
            {"category": "Жильё", "limit": Decimal("3000.00")},
            {"category": "Долги", "limit": Decimal("1000.00")},
            {"category": "Прочее", "limit": Decimal("800.00")},
        ],
        today=today,
    )
    await queries.ensure_weekly_budget_snapshot(previous_start, previous_end)

    available_days = max(0, (today - current_start).days)

    def current_day(days_back: int) -> date:
        return today - timedelta(days=min(days_back, available_days))

    await _insert_expense(current_day(0), "3200.00", "Продукты", needs_review=True)
    await _insert_expense(current_day(1), "1200.00", "Транспорт")
    await _insert_expense(current_day(2), "950.00", "Кафе/Досуг")
    await _insert_expense(current_day(3), "2500.00", "Жильё")
    await _insert_expense(current_day(4), "650.00", "Долги")
    await _insert_expense(current_day(5), "300.00", None)
    await queries.insert_operation(
        current_day(0), "перевод", Decimal("999.00"), "Продукты",
        "mock transfer, excluded", "Mock-карта", "mock-db", False,
        transfer_direction="out",
    )
    deleted_id = await queries.insert_operation(
        current_day(0), "расход", Decimal("500.00"), "Продукты",
        "mock soft-deleted expense", "Mock-карта", "mock-db", False,
    )
    await queries.soft_delete_operation(deleted_id)
    await queries.insert_operation(
        current_day(0), "доход", Decimal("120000.00"), "Зарплата",
        "mock income", "Mock-карта", "mock-db", False,
    )

    await _insert_expense(previous_start + timedelta(days=1), "2800.00", "Продукты")
    await _insert_expense(previous_start + timedelta(days=2), "600.00", "Транспорт")
    await _insert_expense(previous_start + timedelta(days=3), "400.00", "Кафе/Досуг")
    await _insert_expense(previous_start + timedelta(days=4), "2300.00", "Жильё")
    await _insert_expense(previous_start + timedelta(days=5), "500.00", "Долги")
    await _insert_expense(previous_start + timedelta(days=6), "150.00", None)

    # Внутренняя метка: mock_tma_server откажется раздавать базу без неё.
    await queries.set_setting(MOCK_DB_SETTING, "1")

    logger.info(
        "Mock DB seeded: current=%s..%s previous=%s..%s",
        current_start,
        current_end,
        previous_start,
        previous_end,
    )


async def main() -> None:
    require_mock_environment()
    reset = os.getenv("MOCK_RESET", "0") == "1"
    if reset:
        _reset_database_file()

    await connection.init_pool()
    try:
        if MARKER.exists() and not reset:
            logger.info("Mock DB уже заполнена: %s", MARKER)
            return
        await _seed(_anchor_date())
    finally:
        await connection.close_pool()

    MARKER.parent.mkdir(parents=True, exist_ok=True)
    MARKER.write_text("seeded\n", encoding="utf-8")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        asyncio.run(main())
    except MockGuardError as error:
        print(f"Отказ: {error}", file=sys.stderr)
        raise SystemExit(2)
