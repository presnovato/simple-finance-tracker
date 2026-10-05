"""Сбор ближайших платежей из БД с изоляцией ошибок источников (spec 04)."""

import logging
from datetime import date

from finance_bot.core.upcoming import upcoming_payments
from finance_bot.database import queries

logger = logging.getLogger(__name__)


async def get_upcoming(today: date) -> tuple[list[dict], list[str]]:
    """Возвращает (платежи, список недоступных источников).

    Сбой одного источника не скрывает данные другого: ошибка логируется, а
    имя источника попадает в список, чтобы UI мог пояснить неполноту.
    """
    errors: list[str] = []

    try:
        subscriptions = await queries.list_subscriptions("active")
    except Exception:
        logger.exception("Не удалось получить подписки для ближайших платежей")
        subscriptions = []
        errors.append("subscriptions")

    try:
        debts = await queries.list_debts("active")
    except Exception:
        logger.exception("Не удалось получить долги для ближайших платежей")
        debts = []
        errors.append("debts")

    return upcoming_payments(today, subscriptions, debts), errors
