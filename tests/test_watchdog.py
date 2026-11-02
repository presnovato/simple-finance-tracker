import asyncio
import logging
from types import SimpleNamespace

from finance_bot.services import watchdog


class FakeBot:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls = 0

    async def get_me(self):
        self.calls += 1
        if self.fail:
            raise RuntimeError("telegram down")
        return SimpleNamespace(username="bot", id=1)


async def test_check_once_records_success():
    bot = FakeBot()
    instance = watchdog.TelegramWatchdog(bot)

    assert await instance.check_once() is True
    assert instance.last_ok is not None


async def test_critical_logged_once_after_max_failures(caplog):
    bot = FakeBot(fail=True)
    instance = watchdog.TelegramWatchdog(bot, max_failures=6)

    with caplog.at_level(logging.CRITICAL):
        for _ in range(6):
            assert await instance.check_once() is False
        for _ in range(3):
            await instance.check_once()

    criticals = [r for r in caplog.records if r.levelno == logging.CRITICAL]
    assert len(criticals) == 1


async def test_success_resets_failure_counter():
    bot = FakeBot(fail=True)
    instance = watchdog.TelegramWatchdog(bot, max_failures=2)

    await instance.check_once()
    await instance.check_once()
    assert instance._failures == 2

    bot.fail = False
    assert await instance.check_once() is True
    assert instance._failures == 0


async def test_start_runs_check_and_stop_cancels_task():
    bot = FakeBot()
    instance = watchdog.TelegramWatchdog(bot, interval_seconds=3600)

    instance.start()
    for _ in range(10):
        await asyncio.sleep(0)
    await instance.stop()

    assert bot.calls >= 1
    assert instance._task is None


async def test_last_ok_iso_follows_current_watchdog():
    watchdog.set_current(None)
    assert watchdog.last_ok_iso() is None

    instance = watchdog.TelegramWatchdog(FakeBot())
    await instance.check_once()
    watchdog.set_current(instance)
    try:
        assert watchdog.last_ok_iso() == instance.last_ok.isoformat()
    finally:
        watchdog.set_current(None)
    assert watchdog.last_ok_iso() is None
