"""Вечерний пинг: сводка дня + операции, требующие уточнения.

Время хранится в settings (ключ reminder_time), меняется командой /remind
без передеплоя.
"""

import logging
from datetime import timedelta

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from finance_bot.config import ALLOWED_USER_ID, DEFAULT_REMINDER_TIME, plural_ru
from finance_bot.core.dashboard import fmt_amount
from finance_bot.core.dates import TZ, effective_today
from finance_bot.core.subscriptions import (
    due_subscriptions,
    format_subscription_amount,
)
from finance_bot.database import queries
from finance_bot.services import budget as budget_service
from finance_bot.webapp import web_app_markup

logger = logging.getLogger(__name__)

JOB_ID = "evening_ping"
_scheduler: AsyncIOScheduler | None = None


def parse_hhmm(value: str) -> tuple[int, int] | None:
    try:
        hour, minute = value.strip().split(":")
        hour, minute = int(hour), int(minute)
    except ValueError:
        return None
    if 0 <= hour <= 23 and 0 <= minute <= 59:
        return hour, minute
    return None


def _merge_markups(
    *markups: InlineKeyboardMarkup | None,
) -> InlineKeyboardMarkup | None:
    rows = []
    for markup in markups:
        if markup is not None:
            rows.extend(list(row) for row in markup.inline_keyboard)
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


def _due_keyboard(due: list[dict]) -> InlineKeyboardMarkup | None:
    if not due:
        return None
    if len(due) > 3:
        return web_app_markup("Отметить списания", tab="subs")

    rows = []
    for subscription in due:
        charge_date = subscription["next_charge"].isoformat()
        title = subscription["title"][:30]
        rows.append([
            InlineKeyboardButton(
                text=f"✅ {title}",
                callback_data=f"subs:yes:{subscription['id']}:{charge_date}",
            ),
            InlineKeyboardButton(
                text=f"⏭ {title}",
                callback_data=f"subs:no:{subscription['id']}:{charge_date}",
            ),
        ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def build_evening_message() -> tuple[str, InlineKeyboardMarkup | None]:
    today = effective_today()
    ops = await queries.day_operations(today)
    counted = [o for o in ops if o["type"] != "перевод"]
    expense_total = sum(
        (o["amount"] for o in counted if o["type"] == "расход"),
        start=0,
    )
    income_total = sum(
        (o["amount"] for o in counted if o["type"] == "доход"),
        start=0,
    )

    if not ops:
        lines = ["🌙 За сегодня не записано ни одной операции.",
                 "Пробеги по дню: были траты? Кидай текстом или чеком."]
    else:
        n = len(counted)
        lines = [
            f"🌙 Сегодня записано: {n} "
            f"{plural_ru(n, ('операция', 'операции', 'операций'))}.",
        ]
        if expense_total:
            lines.append(f"Расходы: −{fmt_amount(expense_total)}")
        if income_total:
            lines.append(f"Доходы: +{fmt_amount(income_total)}")
        if not expense_total and not income_total:
            lines.append("Только переводы — они не входят в расходы и доходы.")
        lines.append(
            "Всё внёс? Если что-то забылось — кидай сейчас.",
        )

    review = await queries.pending_review()
    if review:
        lines.append("")
        lines.append(f"⚠️ Требуют уточнения ({len(review)}):")
        for op in review:
            desc = op["comment"] or op["category"] or "без описания"
            lines.append(f"• {op['op_date']:%d.%m} {fmt_amount(op['amount'])} — {desc}")
        lines.append("Ответь (reply) на сообщение бота о нужной операции "
                     "и напиши, что поправить.")

    active_subscriptions = await queries.list_subscriptions("active")
    due_tomorrow = [
        subscription for subscription in active_subscriptions
        if subscription["next_charge"] == today + timedelta(days=1)
    ]
    if due_tomorrow:
        lines.append("")
        lines.append("🔔 Завтра списываются подписки:")
        for subscription in due_tomorrow:
            period = "/год" if subscription["period"] == "yearly" else "/мес"
            lines.append(
                f"• {subscription['title']} — "
                f"{format_subscription_amount(subscription['amount'])}{period}"
            )

    due = due_subscriptions(active_subscriptions, today)
    if due:
        lines.append("")
        lines.append("💳 Списались подписки?")
        for subscription in due:
            charge_date = subscription["next_charge"]
            waiting = (
                f", ждёт с {charge_date:%d.%m}"
                if charge_date < today else ""
            )
            lines.append(
                f"• {subscription['title']} — "
                f"{format_subscription_amount(subscription['amount'])} "
                f"({charge_date:%d.%m}{waiting})"
            )
    try:
        budget_lines = await budget_service.evening_budget_lines(today)
    except Exception:
        # Бюджет не должен ломать существующий вечерний пинг.
        logger.exception("Не удалось проверить недельный бюджет")
        budget_lines = []
    if budget_lines:
        lines.append("")
        lines.extend(budget_lines)
    return "\n".join(lines), _due_keyboard(due)


async def _send_evening_ping(bot: Bot) -> None:
    try:
        text, subscription_markup = await build_evening_message()
        await bot.send_message(
            ALLOWED_USER_ID,
            text,
            reply_markup=_merge_markups(subscription_markup, web_app_markup()),
        )
    except Exception:
        logger.exception("Вечерний пинг не отправился")


async def setup(bot: Bot) -> AsyncIOScheduler:
    global _scheduler
    _scheduler = AsyncIOScheduler(timezone=TZ)
    time_str = await queries.get_setting("reminder_time") or DEFAULT_REMINDER_TIME
    hour, minute = parse_hhmm(time_str) or parse_hhmm(DEFAULT_REMINDER_TIME)
    _scheduler.add_job(
        _send_evening_ping, CronTrigger(hour=hour, minute=minute, timezone=TZ),
        args=[bot], id=JOB_ID,
    )
    _scheduler.start()
    logger.info("Вечерний пинг назначен на %02d:%02d", hour, minute)
    return _scheduler


def reschedule(hour: int, minute: int) -> None:
    if _scheduler is not None:
        _scheduler.reschedule_job(
            JOB_ID, trigger=CronTrigger(hour=hour, minute=minute, timezone=TZ)
        )


def shutdown() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
