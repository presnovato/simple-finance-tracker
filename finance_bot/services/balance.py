"""Сбор якорного баланса из settings и агрегатов операций."""

import logging
from datetime import date, datetime, time, timezone
from decimal import Decimal

from finance_bot.core.balance import (calculate_cash_on_hand,
                                      parse_anchor_amount)
from finance_bot.database import queries

logger = logging.getLogger(__name__)

ANCHOR_AMOUNT_KEY = "balance_anchor_amount"
ANCHOR_DATE_KEY = "balance_anchor_date"
ANCHOR_TS_KEY = "balance_anchor_ts"


async def get_snapshot() -> dict | None:
    amount_text = await queries.get_setting(ANCHOR_AMOUNT_KEY)
    date_text = await queries.get_setting(ANCHOR_DATE_KEY)
    if amount_text is None or date_text is None:
        return None
    ts_text = await queries.get_setting(ANCHOR_TS_KEY)
    try:
        anchor_amount = parse_anchor_amount(amount_text)
        anchor_date = date.fromisoformat(date_text)
        # Якорь, поставленный до появления ANCHOR_TS_KEY, считаем как начало
        # своего дня — это в точности прежнее поведение, без падения.
        anchor_ts = (
            datetime.fromisoformat(ts_text) if ts_text
            else datetime.combine(anchor_date, time.min, tzinfo=timezone.utc)
        )
    except ValueError:
        logger.error("Некорректный якорь баланса в settings")
        return None

    totals = await queries.totals_since(anchor_date, anchor_ts)
    amount = calculate_cash_on_hand(
        anchor_amount,
        totals["income"],
        totals["expense"],
        totals.get("transfer_in", Decimal("0")),
        totals.get("transfer_out", Decimal("0")),
    )
    return {
        "amount": amount,
        "anchor_date": anchor_date,
        "anchor_ts": anchor_ts,
        "anchor_amount": anchor_amount,
        "movement_count": totals["movement_count"],
    }


async def set_anchor(
    amount: Decimal, anchor_date: date, moment: datetime | None = None
) -> None:
    anchor_ts = (moment or datetime.now(timezone.utc)).astimezone(timezone.utc)
    await queries.set_setting(ANCHOR_AMOUNT_KEY, f"{amount:.2f}")
    await queries.set_setting(ANCHOR_DATE_KEY, anchor_date.isoformat())
    await queries.set_setting(
        ANCHOR_TS_KEY, anchor_ts.replace(microsecond=0).isoformat()
    )
