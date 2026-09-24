import sqlite3
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from aiohttp.test_utils import TestClient, TestServer

from finance_bot.api.server import create_app
from finance_bot.database import connection, queries
from finance_bot.handlers import capture


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


class AllowAuthenticator:
    def authenticate(self, credential: str) -> dict:
        return {"id": 1}


class FakeMessage:
    def __init__(self, message_id: int = 10, text: str | None = None):
        self.message_id = message_id
        self.chat = SimpleNamespace(id=1)
        self.text = text
        self.caption = None
        self.replies: list[str] = []
        self._next = 900

    async def reply(self, text, **_kwargs):
        self._next += 1
        self.replies.append(text)
        return SimpleNamespace(message_id=self._next)

    async def answer(self, text, **_kwargs):
        return SimpleNamespace(message_id=self._next)


async def _noop(*_args, **_kwargs):
    return None


def _parsed(
    amount: str = "100",
    category: str = "Продукты",
    op_date: date = date(2026, 9, 24),
) -> dict:
    return {
        "intent": "operation",
        "date": op_date,
        "type": "расход",
        "amount": Decimal(amount),
        "category": category,
        "comment": "тест",
        "account": None,
        "transfer_direction": None,
        "needs_review": False,
    }


async def test_redelivered_update_inserts_once(sqlite_database, monkeypatch):
    monkeypatch.setattr(capture.budget_service, "notify_after_new_expense", _noop)
    message = FakeMessage(message_id=42)

    await capture.save_and_confirm(message, _parsed(), "бот-текст")
    await capture.save_and_confirm(message, _parsed(), "бот-текст")

    rows = await queries.list_operations(op_date=date(2026, 9, 24))
    assert len(rows) == 1
    # На повтор апдейта молчим, чтобы не отправить подтверждение дважды.
    assert len(message.replies) == 1


async def test_soft_deleted_operation_still_blocks_reinsertion(
    sqlite_database, monkeypatch
):
    monkeypatch.setattr(capture.budget_service, "notify_after_new_expense", _noop)
    message = FakeMessage(message_id=43)

    op_id = await capture.save_and_confirm(message, _parsed(), "бот-текст")
    await queries.soft_delete_operation(op_id)
    again = await capture.save_and_confirm(message, _parsed(), "бот-текст")

    assert again == op_id
    assert await queries.list_operations(op_date=date(2026, 9, 24)) == []


async def test_duplicate_heuristic_matrix(sqlite_database):
    today = date(2026, 9, 24)
    op_id = await queries.insert_operation(
        today, "расход", Decimal("250"), "Продукты", "кофе", "Карта",
        "text", False,
    )

    # (a) дата ±1 день и свежий created_at
    assert await queries.find_possible_duplicates(
        today + timedelta(days=1), Decimal("250"), "расход", "Другое"
    ) == op_id

    # (b) та же дата и категория, даже если запись старая
    await connection.get_pool().execute(
        "UPDATE operations SET created_at = ? WHERE id = ?",
        "2020-01-01T00:00:00+00:00",
        op_id,
    )
    assert await queries.find_possible_duplicates(
        today, Decimal("250"), "расход", "Продукты"
    ) == op_id

    # негативы
    assert await queries.find_possible_duplicates(
        today, Decimal("999"), "расход", "Продукты"
    ) is None
    assert await queries.find_possible_duplicates(
        today, Decimal("250"), "доход", "Продукты"
    ) is None
    assert await queries.find_possible_duplicates(
        today, Decimal("250"), "расход", "Другое"
    ) is None


async def test_batch_with_half_suspected_asks_before_saving(
    sqlite_database, monkeypatch
):
    monkeypatch.setattr(capture.budget_service, "notify_after_new_expense", _noop)
    today = date(2026, 9, 24)
    await queries.insert_operation(
        today, "расход", Decimal("100"), "Продукты", "x", "Карта", "text", False
    )
    items = [_parsed("100"), _parsed("100")]
    message = FakeMessage(message_id=50)

    await capture.save_many_and_confirm(message, items, "бот-список")

    assert any("похожи" in reply for reply in message.replies)
    assert len(await queries.list_operations(op_date=today)) == 1


async def test_batch_below_half_saves_and_marks_suspected(
    sqlite_database, monkeypatch
):
    monkeypatch.setattr(capture.budget_service, "notify_after_new_expense", _noop)
    today = date(2026, 9, 24)
    await queries.insert_operation(
        today, "расход", Decimal("100"), "Продукты", "x", "Карта", "text", False
    )
    items = [
        _parsed("100"),
        _parsed("777", op_date=date(2026, 8, 1)),
        _parsed("888", op_date=date(2026, 8, 1)),
    ]
    message = FakeMessage(message_id=51)

    await capture.save_many_and_confirm(message, items, "бот-список")

    assert len(await queries.list_operations(op_date=today)) == 2
    assert any("дубль" in reply.lower() for reply in message.replies)


async def test_api_idempotency_key_returns_stored_response(sqlite_database):
    client = TestClient(TestServer(create_app(AllowAuthenticator())))
    await client.start_server()
    body = {
        "type": "расход",
        "amount": "100",
        "category": "Продукты",
        "op_date": "2026-09-24",
    }
    try:
        first = await client.post(
            "/api/operations", json=body, headers={"Idempotency-Key": "k1"}
        )
        repeated = await client.post(
            "/api/operations", json=body, headers={"Idempotency-Key": "k1"}
        )
        assert first.status == 201
        assert repeated.status == 201
        assert await first.json() == await repeated.json()

        plain_a = await client.post("/api/operations", json=body)
        plain_b = await client.post("/api/operations", json=body)
        assert (await plain_a.json())["id"] != (await plain_b.json())["id"]

        rows = await queries.list_operations(op_date=date(2026, 9, 24))
        assert len(rows) == 3
    finally:
        await client.close()


async def test_legacy_database_gets_source_columns_and_unique_index(
    tmp_path, monkeypatch
):
    await connection.close_pool()
    database_path = tmp_path / "legacy9.db"
    legacy_schema = connection.SCHEMA
    for fragment in (
        "  source_chat_id    INTEGER,\n",
        "  source_message_id INTEGER,\n",
        "  source_item_index INTEGER,\n",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_operations_source\n"
        "  ON operations (source_chat_id, source_message_id, source_item_index);\n",
    ):
        legacy_schema = legacy_schema.replace(fragment, "")
    with sqlite3.connect(database_path) as legacy:
        legacy.executescript(legacy_schema)
        legacy.execute(
            "INSERT INTO operations (op_date, type, amount, comment) "
            "VALUES ('2026-01-01', 'расход', 500, 'старое')"
        )
    monkeypatch.setattr(connection, "DB_PATH", str(database_path))
    monkeypatch.setattr(connection, "DB_REQUIRE_PERSISTENT_DIR", False)

    await connection.init_pool()
    try:
        columns = {
            row["name"]
            for row in await connection.get_pool().fetch(
                "PRAGMA table_info(operations)"
            )
        }
        assert {
            "source_chat_id", "source_message_id", "source_item_index",
        } <= columns
        indexes = {
            row["name"]
            for row in await connection.get_pool().fetch(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            )
        }
        assert "idx_operations_source" in indexes
        rows = await queries.list_operations()
        assert len(rows) == 1
        assert rows[0]["comment"] == "старое"
    finally:
        await connection.close_pool()
