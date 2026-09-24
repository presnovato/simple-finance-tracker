import gzip
import json
import os
import sqlite3
import time
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler

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


@pytest.fixture
def backup_dir(tmp_path, monkeypatch):
    directory = tmp_path / "backups" / "daily"
    monkeypatch.setattr(backup, "BACKUP_DIR", str(directory))
    monkeypatch.setattr(backup, "effective_today", lambda: date(2026, 9, 24))
    return directory


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
                "sha256": "a" * 64,
                "operations_count": operations_count,
            }
        ),
        encoding="utf-8",
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


async def test_daily_job_stores_archive_without_notifying(
    sqlite_database, backup_dir
):
    await _insert_expense("42.50")
    bot = FakeBot()

    stored = await backup.store_daily_backup(bot)

    assert stored is not None
    assert stored.archive_path.name == "finance_backup_2026-09-24.db.gz"
    assert stored.operations_count == 1
    assert len(stored.sha256) == 64
    assert bot.documents == []
    assert bot.messages == []

    archive = backup_dir / "finance_backup_2026-09-24.db.gz"
    metadata = json.loads(
        (backup_dir / "finance_backup_2026-09-24.json").read_text(
            encoding="utf-8"
        )
    )
    assert metadata["operations_count"] == 1
    assert metadata["size_bytes"] == stored.size_bytes
    assert metadata["sha256"] == stored.sha256
    assert await queries.get_setting(backup.LAST_AT_SETTING) is not None
    assert await queries.get_setting("backup_last_sha256") is None

    raw = gzip.decompress(archive.read_bytes())
    restored = backup_dir / "restored.db"
    restored.write_bytes(raw)
    with sqlite3.connect(restored) as restored_db:
        assert restored_db.execute(
            "PRAGMA integrity_check"
        ).fetchone()[0] == "ok"


async def test_second_run_same_day_overwrites(sqlite_database, backup_dir):
    bot = FakeBot()
    await _insert_expense("10")
    await backup.store_daily_backup(bot)
    await _insert_expense("20")

    stored = await backup.store_daily_backup(bot)

    archives = list(backup_dir.glob("finance_backup_*.db.gz"))
    assert len(archives) == 1
    assert stored is not None
    assert stored.operations_count == 2


async def test_failure_notifies_owner_and_leaves_no_archive(
    sqlite_database, backup_dir, monkeypatch
):
    async def boom(_tmp_dir):
        raise RuntimeError("boom")

    monkeypatch.setattr(backup, "create_backup_archive", boom)
    bot = FakeBot()

    assert await backup.store_daily_backup(bot) is None

    assert bot.documents == []
    assert len(bot.messages) == 1
    assert "Автобэкап не удался: RuntimeError" in bot.messages[0][1]
    assert await queries.get_setting(backup.LAST_AT_SETTING) is None
    assert list(backup_dir.glob("finance_backup_*.db.gz")) == []
    assert list(backup_dir.glob("finance_backup_*.json")) == []


async def test_failure_message_error_does_not_propagate(
    sqlite_database, backup_dir, monkeypatch
):
    async def boom(_tmp_dir):
        raise RuntimeError("boom")

    class BrokenBot:
        async def send_message(self, *_args, **_kwargs):
            raise RuntimeError("telegram down")

    monkeypatch.setattr(backup, "create_backup_archive", boom)

    assert await backup.store_daily_backup(BrokenBot()) is None


async def test_disk_guard_skips_write_and_notifies(
    sqlite_database, backup_dir, monkeypatch
):
    monkeypatch.setattr(backup, "_free_disk_bytes", lambda: 0)
    bot = FakeBot()

    assert await backup.store_daily_backup(bot) is None

    assert list(backup_dir.glob("finance_backup_*.db.gz")) == []
    assert bot.documents == []
    assert len(bot.messages) == 1
    assert "места" in bot.messages[0][1]
    assert await queries.get_setting(backup.LAST_AT_SETTING) is None


async def test_retention_keeps_latest_seven_and_ignores_others(backup_dir):
    for offset in range(10):
        _write_stored(backup_dir, date(2026, 9, 15 + offset))
    (backup_dir / "pre-migration-v1-20260101T000000Z.db").write_bytes(b"snap")
    (backup_dir / "notes.txt").write_text("keep", encoding="utf-8")

    removed = backup.prune_old_backups()

    remaining = sorted(
        path.name for path in backup_dir.glob("finance_backup_*.db.gz")
    )
    assert remaining == [
        f"finance_backup_2026-09-{day:02d}.db.gz" for day in range(18, 25)
    ]
    assert len(removed) == 6
    assert (backup_dir / "pre-migration-v1-20260101T000000Z.db").is_file()
    assert (backup_dir / "notes.txt").is_file()


async def test_prune_removes_only_stale_tmp_files(backup_dir):
    backup_dir.mkdir(parents=True, exist_ok=True)
    stale = backup_dir / "finance_backup_2026-09-24.db.gz.tmp"
    stale.write_bytes(b"partial")
    old = time.time() - 7200
    os.utime(stale, (old, old))
    fresh = backup_dir / "finance_backup_2026-09-24.json.tmp"
    fresh.write_bytes(b"partial")

    backup.prune_old_backups()

    assert not stale.exists()
    assert fresh.is_file()


async def test_list_backups_newest_first(backup_dir):
    for day in (20, 24, 22):
        _write_stored(backup_dir, date(2026, 9, day))

    listed = backup.list_backups()

    assert [stored.date for stored in listed] == [
        date(2026, 9, 24),
        date(2026, 9, 22),
        date(2026, 9, 20),
    ]


async def test_setup_prunes_old_backups_on_startup(
    sqlite_database, monkeypatch
):
    monkeypatch.setattr(scheduler, "BACKUP_ENABLED", True)
    calls: list[bool] = []
    monkeypatch.setattr(
        scheduler.backup_service,
        "prune_old_backups",
        lambda: calls.append(True),
    )

    await scheduler.setup(FakeBot())
    try:
        assert calls == [True]
    finally:
        scheduler.shutdown()


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
