"""Сторож Telegram: периодический ``get_me()`` и отметка последнего успеха.

Процесс не завершается при сбое Telegram — перезапуск не лечит недоступность
сервиса. Состояние нужно только для ``/health`` и для одной CRITICAL-записи.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from aiogram import Bot

logger = logging.getLogger(__name__)

DEFAULT_INTERVAL_SECONDS = 300
DEFAULT_MAX_FAILURES = 6


class TelegramWatchdog:
    def __init__(
        self,
        bot: Bot,
        *,
        interval_seconds: int = DEFAULT_INTERVAL_SECONDS,
        max_failures: int = DEFAULT_MAX_FAILURES,
    ) -> None:
        self._bot = bot
        self._interval = interval_seconds
        self._max_failures = max_failures
        self._failures = 0
        self._warned = False
        self._task: asyncio.Task | None = None
        self.last_ok: datetime | None = None

    async def check_once(self) -> bool:
        """Одна проверка; возвращает, ответил ли Telegram."""
        try:
            await self._bot.get_me()
        except Exception:
            self._failures += 1
            if self._failures >= self._max_failures and not self._warned:
                logger.critical(
                    "Telegram недоступен: %d проверок подряд не удались",
                    self._failures,
                )
                self._warned = True
            return False
        self.last_ok = datetime.now(timezone.utc)
        self._failures = 0
        self._warned = False
        return True

    async def _run(self) -> None:
        while True:
            await self.check_once()
            await asyncio.sleep(self._interval)

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None


_current: TelegramWatchdog | None = None


def set_current(watchdog: TelegramWatchdog | None) -> None:
    global _current
    _current = watchdog


def current() -> TelegramWatchdog | None:
    return _current


def last_ok_iso() -> str | None:
    watchdog = _current
    if watchdog is None or watchdog.last_ok is None:
        return None
    return watchdog.last_ok.isoformat()
