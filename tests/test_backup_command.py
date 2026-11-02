import json
from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest
from aiogram.filters import CommandObject

from finance_bot.database import connection
from finance_bot.handlers import backup as backup_handler
from finance_bot.services import backup


def _today() -> date:
    return date(2026, 9, 24)


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


@pytest.fixture
def backup_dir(tmp_path, monkeypatch):
    directory = tmp_path / "backups" / "daily"
    monkeypatch.setattr(backup, "BACKUP_DIR", str(directory))
    monkeypatch.setattr(backup, "effective_today", _today)
    monkeypatch.setattr(backup_handler, "effective_today", _today)
    return directory


class FakeBot:
    def __init__(self) -> None:
        self.messages: list[tuple] = []

    async def send_message(self, chat_id, text, **kwargs):
        self.messages.append((chat_id, text, kwargs))


class FakeMessage:
    def __init__(self) -> None:
        self.bot = FakeBot()
        self.chat = SimpleNamespace(id=1)
        self.answers: list[str] = []
        self.documents: list[tuple] = []

    async def answer(self, text, **_kwargs):
        self.answers.append(text)
        return SimpleNamespace(message_id=1)

    async def answer_document(self, document, **kwargs):
        self.documents.append((document, kwargs))
        return SimpleNamespace(message_id=2)


def _command(args: str) -> CommandObject:
    return CommandObject(prefix="/", command="backup", args=args)


def _write_stored(
    directory,
    day: date,
    *,
    size_bytes: int = 100,
    operations_count: int = 0,
) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    archive = directory / f"finance_backup_{day.isoformat()}.db.gz"
    archive.write_bytes(b"backup")
    metadata = directory / f"finance_backup_{day.isoformat()}.json"
    metadata.write_text(
        json.dumps(
            {
                "created_at": datetime(
                    2026, 9, day.day, 4, 0, tzinfo=timezone.utc
                ).isoformat(),
                "size_bytes": size_bytes,
                "sha256": "abcdef123456" + "0" * 52,
                "operations_count": operations_count,
            }
        ),
        encoding="utf-8",
    )


async def test_no_argument_sends_today(backup_dir):
    _write_stored(backup_dir, date(2026, 9, 24), operations_count=3)
    message = FakeMessage()

    await backup_handler.cmd_backup(message, _command(""))

    assert len(message.documents) == 1
    document, kwargs = message.documents[0]
    assert document.filename == "finance_backup_2026-09-24.db.gz"
    assert "24.09.2026" in kwargs["caption"]
    assert "Операций: 3" in kwargs["caption"]
    assert "sha256: abcdef123456" in kwargs["caption"]


async def test_requested_date_without_file_falls_back_to_earlier(backup_dir):
    _write_stored(backup_dir, date(2026, 9, 23))
    message = FakeMessage()

    await backup_handler.cmd_backup(message, _command("24.09"))

    document, kwargs = message.documents[0]
    assert document.filename == "finance_backup_2026-09-23.db.gz"
    assert "ближайший: 23.09" in kwargs["caption"]


async def test_requested_date_falls_back_to_later(backup_dir):
    _write_stored(backup_dir, date(2026, 9, 22))
    _write_stored(backup_dir, date(2026, 9, 23))
    message = FakeMessage()

    await backup_handler.cmd_backup(message, _command("20.09"))

    document, _ = message.documents[0]
    assert document.filename == "finance_backup_2026-09-22.db.gz"


async def test_yesterday_and_explicit_iso_date(backup_dir):
    _write_stored(backup_dir, date(2026, 9, 23))
    _write_stored(backup_dir, date(2026, 9, 22))

    yesterday = FakeMessage()
    await backup_handler.cmd_backup(yesterday, _command("вчера"))
    assert yesterday.documents[0][0].filename == "finance_backup_2026-09-23.db.gz"

    explicit = FakeMessage()
    await backup_handler.cmd_backup(explicit, _command("2026-09-22"))
    assert explicit.documents[0][0].filename == "finance_backup_2026-09-22.db.gz"


async def test_unparseable_argument_shows_help(backup_dir):
    message = FakeMessage()

    await backup_handler.cmd_backup(message, _command("непонятно"))

    assert message.documents == []
    assert message.answers == [backup_handler.HELP_TEXT]
    assert "/backup" in message.answers[0]


async def test_list_shows_dates_newest_first(backup_dir):
    for day in (20, 22, 23, 24):
        _write_stored(backup_dir, date(2026, 9, day), operations_count=day)
    message = FakeMessage()

    await backup_handler.cmd_backup(message, _command("список"))

    text = message.answers[0]
    positions = [
        text.index(f"{day:02d}.09.2026") for day in (24, 23, 22, 20)
    ]
    assert positions == sorted(positions)
    assert "операций 24" in text


async def test_empty_directory_replies_no_backups(backup_dir):
    message = FakeMessage()

    await backup_handler.cmd_backup(message, _command(""))

    assert message.documents == []
    assert message.answers == [backup_handler.NO_BACKUPS_TEXT]


async def test_empty_directory_list_replies_no_backups(backup_dir):
    message = FakeMessage()

    await backup_handler.cmd_backup(message, _command("список"))

    assert message.documents == []
    assert message.answers == [backup_handler.NO_BACKUPS_TEXT]


async def test_now_creates_and_sends_fresh_archive(
    sqlite_database, backup_dir
):
    message = FakeMessage()

    await backup_handler.cmd_backup(message, _command("сейчас"))

    assert (
        backup_dir / "finance_backup_2026-09-24.db.gz"
    ).is_file()
    assert len(message.documents) == 1
    document, kwargs = message.documents[0]
    assert document.filename == "finance_backup_2026-09-24.db.gz"
    assert "24.09.2026" in kwargs["caption"]


async def test_oversize_archive_replies_with_text(backup_dir, monkeypatch):
    _write_stored(backup_dir, date(2026, 9, 24), size_bytes=50 * 1024 * 1024)
    monkeypatch.setattr(backup, "MAX_UPLOAD_BYTES", 1)
    message = FakeMessage()

    await backup_handler.cmd_backup(message, _command(""))

    assert message.documents == []
    assert "45 МБ" in message.answers[0]
