from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from finance_bot.core.dates import TZ
from finance_bot.database import connection, queries
from finance_bot.services import scheduler


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
        self.messages: list[tuple] = []

    async def send_message(self, chat_id, text, **kwargs):
        self.messages.append((chat_id, text, kwargs))


def _moscow_utc(day: int, hour: int, minute: int) -> datetime:
    moment = TZ.localize(datetime(2026, 9, day, hour, minute))
    return moment.astimezone(timezone.utc)


async def _ok_evening_message():
    return "🌙 текст", None


def _use_scheduler():
    scheduler._scheduler = AsyncIOScheduler(timezone=TZ)
    scheduler._scheduler.start()
    return scheduler._scheduler


async def test_evening_message_contains_due_subscriptions_and_callbacks(monkeypatch):
    today = date(2026, 8, 10)

    async def day_operations(_today):
        return []

    async def pending_review():
        return []

    async def subscriptions(_status="active", next_charge=None):
        return [
            {
                "id": 1, "title": "Netflix", "amount": Decimal("899"),
                "period": "monthly", "next_charge": date(2026, 8, 10),
                "status": "active",
            },
            {
                "id": 2, "title": "Яндекс Плюс", "amount": Decimal("399"),
                "period": "monthly", "next_charge": date(2026, 8, 8),
                "status": "active",
            },
        ]

    monkeypatch.setattr(scheduler, "effective_today", lambda: today)
    monkeypatch.setattr(scheduler.queries, "day_operations", day_operations)
    monkeypatch.setattr(scheduler.queries, "pending_review", pending_review)
    monkeypatch.setattr(scheduler.queries, "list_subscriptions", subscriptions)

    text, markup = await scheduler.build_evening_message()
    assert "💳 Списались подписки?" in text
    assert "Netflix — 899,00 ₽ (10.08)" in text
    assert "Яндекс Плюс — 399,00 ₽ (08.08, ждёт с 08.08)" in text
    assert markup is not None
    callback_data = [
        button.callback_data
        for row in markup.inline_keyboard
        for button in row
    ]
    assert "subs:yes:1:2026-08-10" in callback_data
    assert "subs:no:2:2026-08-08" in callback_data


async def test_evening_message_shows_signed_income_and_expense(monkeypatch):
    today = date(2026, 8, 10)

    async def day_operations(_today):
        return [
            {"type": "расход", "amount": Decimal("1947")},
            {"type": "доход", "amount": Decimal("5000")},
            {"type": "перевод", "amount": Decimal("300")},
        ]

    async def pending_review():
        return []

    async def subscriptions(_status="active", next_charge=None):
        return []

    monkeypatch.setattr(scheduler, "effective_today", lambda: today)
    monkeypatch.setattr(scheduler.queries, "day_operations", day_operations)
    monkeypatch.setattr(scheduler.queries, "pending_review", pending_review)
    monkeypatch.setattr(scheduler.queries, "list_subscriptions", subscriptions)

    text, _ = await scheduler.build_evening_message()

    assert "Расходы: −1 947₽" in text
    assert "Доходы: +5 000₽" in text
    assert "Всё внёс?" in text


def test_scheduled_moment_rules():
    assert scheduler.scheduled_moment(21, 0, date(2026, 9, 24)) == TZ.localize(
        datetime(2026, 9, 24, 21, 0)
    )
    # Время после полуночи относится к следующему календарному дню.
    assert scheduler.scheduled_moment(1, 30, date(2026, 9, 24)) == TZ.localize(
        datetime(2026, 9, 25, 1, 30)
    )


async def test_evening_ping_sets_marker_and_skips_second_call(
    sqlite_database, monkeypatch
):
    monkeypatch.setattr(scheduler, "effective_today", lambda: date(2026, 9, 24))
    monkeypatch.setattr(scheduler, "build_evening_message", _ok_evening_message)
    bot = FakeBot()

    await scheduler._send_evening_ping(bot)
    await scheduler._send_evening_ping(bot)

    assert len(bot.messages) == 1
    assert (
        await queries.get_setting(scheduler.EVENING_MARKER_SETTING)
        == "2026-09-24"
    )


async def test_evening_ping_skips_when_marker_already_set(
    sqlite_database, monkeypatch
):
    monkeypatch.setattr(scheduler, "effective_today", lambda: date(2026, 9, 24))
    monkeypatch.setattr(scheduler, "build_evening_message", _ok_evening_message)
    await queries.set_setting(scheduler.EVENING_MARKER_SETTING, "2026-09-24")
    bot = FakeBot()

    await scheduler._send_evening_ping(bot)

    assert bot.messages == []


async def test_catch_up_scheduled_after_reminder(sqlite_database, monkeypatch):
    _use_scheduler()
    try:
        monkeypatch.setattr(scheduler, "effective_today", lambda: date(2026, 9, 24))
        monkeypatch.setattr(scheduler, "_utcnow", lambda: _moscow_utc(24, 21, 30))
        await queries.set_setting("reminder_time", "21:00")

        assert await scheduler.schedule_evening_catch_up(FakeBot()) is True
        assert scheduler._scheduler.get_job(scheduler.CATCH_UP_JOB_ID) is not None
    finally:
        scheduler.shutdown()


async def test_catch_up_not_scheduled_before_reminder(sqlite_database, monkeypatch):
    _use_scheduler()
    try:
        monkeypatch.setattr(scheduler, "effective_today", lambda: date(2026, 9, 24))
        monkeypatch.setattr(scheduler, "_utcnow", lambda: _moscow_utc(24, 20, 0))
        await queries.set_setting("reminder_time", "21:00")

        assert await scheduler.schedule_evening_catch_up(FakeBot()) is False
        assert scheduler._scheduler.get_job(scheduler.CATCH_UP_JOB_ID) is None
    finally:
        scheduler.shutdown()


async def test_catch_up_not_scheduled_when_marker_set(sqlite_database, monkeypatch):
    _use_scheduler()
    try:
        monkeypatch.setattr(scheduler, "effective_today", lambda: date(2026, 9, 24))
        monkeypatch.setattr(scheduler, "_utcnow", lambda: _moscow_utc(24, 21, 30))
        await queries.set_setting("reminder_time", "21:00")
        await queries.set_setting(scheduler.EVENING_MARKER_SETTING, "2026-09-24")

        assert await scheduler.schedule_evening_catch_up(FakeBot()) is False
        assert scheduler._scheduler.get_job(scheduler.CATCH_UP_JOB_ID) is None
    finally:
        scheduler.shutdown()


async def test_restart_after_midnight_catches_up_previous_effective_day(
    sqlite_database, monkeypatch
):
    _use_scheduler()
    try:
        # 01:00 — ещё финансовый день 24-го; пинг за него был в 21:00.
        monkeypatch.setattr(scheduler, "effective_today", lambda: date(2026, 9, 24))
        monkeypatch.setattr(scheduler, "_utcnow", lambda: _moscow_utc(25, 1, 0))
        await queries.set_setting("reminder_time", "21:00")

        assert await scheduler.schedule_evening_catch_up(FakeBot()) is True
        assert scheduler._scheduler.get_job(scheduler.CATCH_UP_JOB_ID) is not None
    finally:
        scheduler.shutdown()


async def test_after_midnight_reminder_catch_up_rule(sqlite_database, monkeypatch):
    _use_scheduler()
    try:
        monkeypatch.setattr(scheduler, "effective_today", lambda: date(2026, 9, 24))
        await queries.set_setting("reminder_time", "01:30")

        # 01:00 — момент 01:30 ещё не наступил.
        monkeypatch.setattr(scheduler, "_utcnow", lambda: _moscow_utc(25, 1, 0))
        assert await scheduler.schedule_evening_catch_up(FakeBot()) is False

        # 02:00 — момент 01:30 уже прошёл.
        monkeypatch.setattr(scheduler, "_utcnow", lambda: _moscow_utc(25, 2, 0))
        assert await scheduler.schedule_evening_catch_up(FakeBot()) is True
    finally:
        scheduler.shutdown()


async def test_failed_ping_schedules_single_retry(sqlite_database, monkeypatch):
    _use_scheduler()
    try:
        monkeypatch.setattr(scheduler, "effective_today", lambda: date(2026, 9, 24))
        monkeypatch.setattr(scheduler, "_utcnow", lambda: _moscow_utc(24, 21, 0))

        async def boom():
            raise RuntimeError("сеть упала")

        monkeypatch.setattr(scheduler, "build_evening_message", boom)

        await scheduler._send_evening_ping(FakeBot())

        job = scheduler._scheduler.get_job(scheduler.RETRY_JOB_ID)
        assert job is not None
        assert await queries.get_setting(scheduler.EVENING_MARKER_SETTING) is None
    finally:
        scheduler.shutdown()


async def test_retry_success_sets_marker(sqlite_database, monkeypatch):
    _use_scheduler()
    try:
        monkeypatch.setattr(scheduler, "effective_today", lambda: date(2026, 9, 24))
        monkeypatch.setattr(scheduler, "_utcnow", lambda: _moscow_utc(24, 21, 0))
        monkeypatch.setattr(scheduler, "build_evening_message", _ok_evening_message)
        bot = FakeBot()

        await scheduler._send_evening_ping(bot, is_retry=True)

        assert len(bot.messages) == 1
        assert (
            await queries.get_setting(scheduler.EVENING_MARKER_SETTING)
            == "2026-09-24"
        )
    finally:
        scheduler.shutdown()


async def test_retry_failure_gives_up_without_rescheduling(
    sqlite_database, monkeypatch
):
    _use_scheduler()
    try:
        monkeypatch.setattr(scheduler, "effective_today", lambda: date(2026, 9, 24))
        monkeypatch.setattr(scheduler, "_utcnow", lambda: _moscow_utc(24, 21, 0))

        async def boom():
            raise RuntimeError("сеть упала")

        monkeypatch.setattr(scheduler, "build_evening_message", boom)

        await scheduler._send_evening_ping(FakeBot(), is_retry=True)

        assert scheduler._scheduler.get_job(scheduler.RETRY_JOB_ID) is None
        assert await queries.get_setting(scheduler.EVENING_MARKER_SETTING) is None
    finally:
        scheduler.shutdown()


async def test_reschedule_keeps_job_options(sqlite_database, monkeypatch):
    monkeypatch.setattr(scheduler, "effective_today", lambda: date(2026, 9, 24))
    monkeypatch.setattr(scheduler, "_utcnow", lambda: _moscow_utc(24, 10, 0))
    bot = FakeBot()

    sched = await scheduler.setup(bot)
    try:
        job = sched.get_job(scheduler.JOB_ID)
        assert job is not None
        assert job.misfire_grace_time == 3600
        assert job.coalesce is True
        assert job.max_instances == 1

        scheduler.reschedule(22, 30)

        job = sched.get_job(scheduler.JOB_ID)
        assert job is not None
        assert job.misfire_grace_time == 3600
        assert job.coalesce is True
        assert job.max_instances == 1
        assert "hour='22'" in str(job.trigger)
        assert "minute='30'" in str(job.trigger)
    finally:
        scheduler.shutdown()
