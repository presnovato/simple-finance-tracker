import gzip
import os
import sqlite3
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from finance_bot.config import ALLOWED_USER_ID
from finance_bot.database import connection, queries
from finance_bot.services import backup, scheduler


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


class FakeBot:
    def __init__(self) -> None:
        self.documents: list[tuple] = []
        self.messages: list[tuple] = []

    async def send_document(self, chat_id, document, **kwargs):
        self.documents.append((chat_id, document, kwargs))

    async def send_message(self, chat_id, text, **kwargs):
        self.messages.append((chat_id, text, kwargs))


async def _insert_expense(amount: str = "100") -> int:
    return await queries.insert_operation(
        date(2026, 9, 24),
        "расход",
        Decimal(amount),
        "Продукты",
        "тест",
        "Карта",
        "text",
        False,
    )


async def test_backup_archive_restores_cleanly(sqlite_database, tmp_path):
    await _insert_expense("42.50")

    archive = await backup.create_backup_archive(tmp_path / "work")

    assert archive.operations_count == 1
    assert len(archive.sha256) == 64
    assert archive.path.suffix == ".gz"

    raw = gzip.decompress(archive.path.read_bytes())
    restored = tmp_path / "restored.db"
    restored.write_bytes(raw)
    with sqlite3.connect(restored) as restored_db:
        assert restored_db.execute(
            "PRAGMA integrity_check"
        ).fetchone()[0] == "ok"
        assert restored_db.execute(
            "SELECT COUNT(*) FROM operations"
        ).fetchone()[0] == 1


async def test_consecutive_backups_of_unchanged_database_are_identical(
    sqlite_database, tmp_path
):
    await _insert_expense()

    first = await backup.create_backup_archive(tmp_path / "a")
    second = await backup.create_backup_archive(tmp_path / "b")

    assert first.sha256 == second.sha256


async def test_send_daily_backup_sends_document_once(sqlite_database, monkeypatch):
    monkeypatch.setattr(backup, "effective_today", lambda: date(2026, 9, 24))
    bot = FakeBot()

    assert await backup.send_daily_backup(bot) is True

    assert len(bot.documents) == 1
    chat_id, document, kwargs = bot.documents[0]
    assert chat_id == ALLOWED_USER_ID
    assert document.filename == "finance_backup_2026-09-24.db.gz"
    assert kwargs["disable_notification"] is True
    assert "24.09.2026" in kwargs["caption"]
    assert "Операций: 0" in kwargs["caption"]
    assert "sha256:" in kwargs["caption"]
    assert await queries.get_setting(backup.SHA_SETTING) is not None
    assert await queries.get_setting(backup.LAST_AT_SETTING) is not None


async def test_unchanged_database_skips_second_send(sqlite_database, monkeypatch):
    monkeypatch.setattr(backup, "effective_today", lambda: date(2026, 9, 24))
    bot = FakeBot()

    assert await backup.send_daily_backup(bot) is True
    assert await backup.send_daily_backup(bot) is False

    assert len(bot.documents) == 1
    assert await queries.get_setting(backup.CHECKED_AT_SETTING) is not None


async def test_changed_database_sends_again(sqlite_database, monkeypatch):
    monkeypatch.setattr(backup, "effective_today", lambda: date(2026, 9, 24))
    bot = FakeBot()

    assert await backup.send_daily_backup(bot) is True
    await _insert_expense("10")
    assert await backup.send_daily_backup(bot) is True

    assert len(bot.documents) == 2


async def test_force_ignores_unchanged_hash(sqlite_database, monkeypatch):
    monkeypatch.setattr(backup, "effective_today", lambda: date(2026, 9, 24))
    bot = FakeBot()

    assert await backup.send_daily_backup(bot) is True
    assert await backup.send_daily_backup(bot, force=True) is True

    assert len(bot.documents) == 2


async def test_oversize_archive_is_not_uploaded(sqlite_database, monkeypatch):
    monkeypatch.setattr(backup, "effective_today", lambda: date(2026, 9, 24))
    monkeypatch.setattr(backup, "MAX_UPLOAD_BYTES", 1)
    bot = FakeBot()

    assert await backup.send_daily_backup(bot) is False

    assert bot.documents == []
    assert len(bot.messages) == 1
    assert "45 МБ" in bot.messages[0][1]


async def test_failure_notifies_owner_and_does_not_mark_success(
    sqlite_database, monkeypatch
):
    async def boom(_tmp_dir):
        raise RuntimeError("boom")

    monkeypatch.setattr(backup, "create_backup_archive", boom)
    bot = FakeBot()

    assert await backup.send_daily_backup(bot) is False

    assert bot.documents == []
    assert len(bot.messages) == 1
    assert "Автобэкап не удался: RuntimeError" in bot.messages[0][1]
    assert await queries.get_setting(backup.LAST_AT_SETTING) is None


async def test_failure_message_error_does_not_propagate(sqlite_database, monkeypatch):
    async def boom(_tmp_dir):
        raise RuntimeError("boom")

    class BrokenBot:
        async def send_message(self, *_args, **_kwargs):
            raise RuntimeError("telegram down")

    monkeypatch.setattr(backup, "create_backup_archive", boom)

    assert await backup.send_daily_backup(BrokenBot()) is False


async def test_catch_up_registers_one_off_job_when_overdue(
    sqlite_database, monkeypatch
):
    scheduler._scheduler = AsyncIOScheduler(timezone=timezone.utc)
    scheduler._scheduler.start()
    try:
        overdue = datetime.now(timezone.utc) - timedelta(hours=48)
        await queries.set_setting(
            "probe_last_at", overdue.replace(microsecond=0).isoformat()
        )

        async def job():
            return None

        added = await scheduler.schedule_catch_up_if_overdue(
            "probe",
            job,
            last_run_key="probe_last_at",
            max_age=timedelta(hours=26),
            delay_seconds=3600,
        )

        assert added is True
        assert scheduler._scheduler.get_job("probe") is not None
    finally:
        scheduler.shutdown()


async def test_catch_up_skips_when_recent(sqlite_database):
    scheduler._scheduler = AsyncIOScheduler(timezone=timezone.utc)
    scheduler._scheduler.start()
    try:
        async def job():
            return None

        await queries.set_setting(
            "probe_last_at", datetime.now(timezone.utc).isoformat()
        )

        added = await scheduler.schedule_catch_up_if_overdue(
            "probe",
            job,
            last_run_key="probe_last_at",
            max_age=timedelta(hours=26),
            delay_seconds=3600,
        )

        assert added is False
        assert scheduler._scheduler.get_job("probe") is None
    finally:
        scheduler.shutdown()


async def test_catch_up_treats_missing_timestamp_as_overdue(sqlite_database):
    scheduler._scheduler = AsyncIOScheduler(timezone=timezone.utc)
    scheduler._scheduler.start()
    try:
        async def job():
            return None

        added = await scheduler.schedule_catch_up_if_overdue(
            "probe",
            job,
            last_run_key="probe_last_at",
            max_age=timedelta(hours=26),
            delay_seconds=3600,
        )

        assert added is True
        assert scheduler._scheduler.get_job("probe") is not None
    finally:
        scheduler.shutdown()


async def test_setup_registers_backup_job_with_options(sqlite_database, monkeypatch):
    monkeypatch.setattr(scheduler, "BACKUP_ENABLED", True)
    bot = FakeBot()

    sched = await scheduler.setup(bot)
    try:
        job = sched.get_job(scheduler.BACKUP_JOB_ID)
        assert job is not None
        assert job.misfire_grace_time == 3600
        assert job.coalesce is True
        assert job.max_instances == 1
    finally:
        scheduler.shutdown()


async def test_setup_skips_backup_when_disabled(sqlite_database, monkeypatch):
    monkeypatch.setattr(scheduler, "BACKUP_ENABLED", False)
    bot = FakeBot()

    sched = await scheduler.setup(bot)
    try:
        assert sched.get_job(scheduler.BACKUP_JOB_ID) is None
        assert sched.get_job(scheduler.BACKUP_CATCH_UP_JOB_ID) is None
    finally:
        scheduler.shutdown()


async def test_pre_migration_snapshot_created_for_existing_data(tmp_path, monkeypatch):
    await connection.close_pool()
    database_path = tmp_path / "legacy.db"
    with sqlite3.connect(database_path) as legacy:
        legacy.executescript(connection.BASE_SCHEMA)
        legacy.execute(
            "INSERT INTO operations (op_date, type, amount, comment) "
            "VALUES (?, ?, ?, ?)",
            ("2026-09-01", "расход", 100, "старое"),
        )
    monkeypatch.setattr(connection, "DB_PATH", str(database_path))
    monkeypatch.setattr(connection, "DB_REQUIRE_PERSISTENT_DIR", False)

    await connection.init_pool()
    try:
        snapshots = list((tmp_path / "backups").glob("pre-migration-*.db"))
        assert len(snapshots) == 1
        assert snapshots[0].name.startswith("pre-migration-v1-")
        with sqlite3.connect(snapshots[0]) as snapshot:
            assert snapshot.execute(
                "SELECT COUNT(*) FROM operations"
            ).fetchone()[0] == 1
    finally:
        await connection.close_pool()


async def test_fresh_database_gets_no_snapshot(tmp_path, monkeypatch):
    await connection.close_pool()
    monkeypatch.setattr(connection, "DB_PATH", str(tmp_path / "fresh.db"))
    monkeypatch.setattr(connection, "DB_REQUIRE_PERSISTENT_DIR", False)

    await connection.init_pool()
    try:
        assert not (tmp_path / "backups").exists()
    finally:
        await connection.close_pool()


def test_pre_migration_snapshots_keep_three_newest(tmp_path):
    backups_dir = tmp_path / "backups"
    backups_dir.mkdir()
    for index in range(4):
        path = backups_dir / f"pre-migration-v{index + 1}-2026092{index}T000000Z.db"
        path.write_bytes(b"snapshot")
        os.utime(path, (1000 + index, 1000 + index))

    connection._prune_pre_migration_snapshots(backups_dir, keep=3)

    remaining = sorted(path.name for path in backups_dir.glob("pre-migration-*.db"))
    assert len(remaining) == 3
    assert "pre-migration-v1-20260920T000000Z.db" not in remaining


async def test_created_fresh_flag_tracks_new_and_existing_file(tmp_path, monkeypatch):
    await connection.close_pool()
    monkeypatch.setattr(connection, "DB_PATH", str(tmp_path / "flag.db"))
    monkeypatch.setattr(connection, "DB_REQUIRE_PERSISTENT_DIR", False)

    await connection.init_pool()
    assert connection.created_fresh is True
    await connection.close_pool()

    await connection.init_pool()
    assert connection.created_fresh is False
    await connection.close_pool()
