"""Глобальный обработчик ошибок: владелец видит сбой, а не тишину.

Логи не ограничиваются, а сообщения владельцу — не чаще одного раза в
``NOTIFY_INTERVAL_SECONDS``. Текст нейтральный: после частичного сохранения
нельзя утверждать, что «ничего не сохранено».
"""

from __future__ import annotations

import logging
import time

from aiogram import Dispatcher
from aiogram.types import ErrorEvent

logger = logging.getLogger(__name__)

NOTIFY_INTERVAL_SECONDS = 60
MESSAGE_FAILURE_TEXT = (
    "⚠️ Ошибка при обработке — проверь последние операции в «Истории»."
)
CALLBACK_FAILURE_TEXT = "Ошибка, попробуй ещё раз"

_last_notified_at: float | None = None


def _should_notify(now: float) -> bool:
    global _last_notified_at
    if (
        _last_notified_at is not None
        and now - _last_notified_at < NOTIFY_INTERVAL_SECONDS
    ):
        return False
    _last_notified_at = now
    return True


async def handle_error(event: ErrorEvent) -> None:
    try:
        logger.error(
            "Ошибка при обработке update: type=%s id=%s",
            event.update.event_type,
            event.update.update_id,
            exc_info=event.exception,
        )
    except Exception:
        logger.exception("Не удалось залогировать ошибку обработки")

    try:
        if not _should_notify(time.monotonic()):
            return
        message = event.update.message
        if message is not None:
            await message.answer(MESSAGE_FAILURE_TEXT)
            return
        callback = event.update.callback_query
        if callback is not None:
            await callback.answer(CALLBACK_FAILURE_TEXT, show_alert=True)
    except Exception:
        # Обработчик ошибок не должен падать сам.
        logger.exception("Не удалось сообщить владельцу об ошибке")


def register(dispatcher: Dispatcher) -> None:
    """Подключает обработчик к диспетчеру (вызывается первым в main.py)."""
    dispatcher.errors.register(handle_error)
