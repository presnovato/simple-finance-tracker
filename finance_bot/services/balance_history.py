"""Сохранение дневного снимка «денег на руках» (spec 06).

Значение берётся из существующего сервиса баланса, формула не дублируется.
История начинается с момента включения функции: прошлые дни не реконструируются.
"""

import logging
from datetime import date, datetime, timezone

from finance_bot.core.dates import effective_today
from finance_bot.database import queries
from finance_bot.services import balance as balance_service

logger = logging.getLogger(__name__)

LAST_AT_SETTING = "balance_snapshot_last_at"


async def store_daily_snapshot(today: date | None = None) -> dict | None:
    """Записывает один снимок за эффективный день; без якоря — ничего."""
    snapshot_date = today or effective_today()
    snapshot = await balance_service.get_snapshot()
    if snapshot is None:
        return None
    stored = await queries.upsert_balance_snapshot(
        snapshot_date, snapshot["amount"]
    )
    await queries.set_setting(
        LAST_AT_SETTING,
        datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    )
    logger.info("Снимок «денег на руках» за %s сохранён", snapshot_date)
    return stored
