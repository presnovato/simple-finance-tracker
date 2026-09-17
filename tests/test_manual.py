from datetime import date

import pytest

from finance_bot.database import connection, queries
from finance_bot.handlers.manual import parse_manual_brief, parse_manual_date


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


def test_manual_date_parser_is_deterministic():
    today = date(2026, 9, 17)
    assert parse_manual_date("сегодня", today) == today
    assert parse_manual_date("вчера", today) == date(2026, 9, 16)
    assert parse_manual_date("2026-09-01", today) == date(2026, 9, 1)
    assert parse_manual_date("01.09.2026", today) == date(2026, 9, 1)
    assert parse_manual_date("завтра", today) is None
    assert parse_manual_date("не дата", today) is None


def test_manual_brief_extracts_known_fields_without_llm():
    draft = parse_manual_brief(
        "расход 850 Продукты вчера карта, комментарий: ужин",
        date(2026, 9, 17),
    )

    assert draft == {
        "type": "расход",
        "amount": "850",
        "category": "Продукты",
        "op_date": "2026-09-16",
        "account": "карта",
        "comment": "ужин",
    }


def test_manual_brief_keeps_transfer_without_category():
    draft = parse_manual_brief("перевод 5000 себе вчера", date(2026, 9, 17))

    assert draft["type"] == "перевод"
    assert draft["amount"] == "5000"
    assert draft["transfer_direction"] == "self"
    assert draft["category"] is None


async def test_manual_capture_session_round_trip(sqlite_database):
    await queries.save_manual_capture_session(
        1,
        "amount",
        {"type": "расход", "category": "Продукты"},
    )
    session = await queries.get_manual_capture_session(1)
    assert session is not None
    assert session["step"] == "amount"
    assert session["draft"] == {"type": "расход", "category": "Продукты"}

    await queries.save_manual_capture_session(
        1,
        "date",
        {"amount": "1250.50"},
    )
    assert (await queries.get_manual_capture_session(1))["step"] == "date"
    await queries.delete_manual_capture_session(1)
    assert await queries.get_manual_capture_session(1) is None
