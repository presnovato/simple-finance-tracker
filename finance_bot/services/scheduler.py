"""Вечерний пинг: сводка дня + операции, требующие уточнения.

Время хранится в settings (ключ reminder_time), меняется командой /remind
без передеплоя.
"""

import logging
from datetime import date, datetime, time, timedelta, timezone

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

from finance_bot.config import (
    ALLOWED_USER_ID,
    BACKUP_ENABLED,
    BACKUP_HOUR,
    DAY_BOUNDARY_HOUR,
    DEFAULT_REMINDER_TIME,
    plural_ru,
)
from finance_bot.core.dashboard import fmt_amount
from finance_bot.core.dates import TZ, effective_today
from finance_bot.core.subscriptions import (
    due_subscriptions,
    format_subscription_amount,
)
from finance_bot.database import queries
from finance_bot.services import backup as backup_service
from finance_bot.services import budget as budget_service
from finance_bot.webapp import web_app_markup

logger = logging.getLogger(__name__)

JOB_ID = "evening_ping"
RETRY_JOB_ID = "evening_ping_retry"
CATCH_UP_JOB_ID = "evening_ping_catch_up"
BACKUP_JOB_ID = "daily_backup"
BACKUP_CATCH_UP_JOB_ID = "daily_backup_catch_up"
EVENING_MARKER_SETTING = "evening_ping_last_date"
RETRY_DELAY_MINUTES = 10
CATCH_UP_DELAY_SECONDS = 30
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


def scheduled_moment(
    hour: int, minute: int, effective_day: date
) -> datetime:
    """Момент, когда должен уйти пинг за финансовый день ``effective_day``.

    Время до ``DAY_BOUNDARY_HOUR`` относится к следующему календарному дню:
    `/remind 01:30` в ночь на 25-е — это пинг за финансовый день 24-го,
    поэтому для effective_day=24-е момент — 25-е, 01:30.
    """
    calendar_day = effective_day
    if hour < DAY_BOUNDARY_HOUR:
        calendar_day = effective_day + timedelta(days=1)
    return TZ.localize(datetime.combine(calendar_day, time(hour, minute)))


async def _send_evening_ping(bot: Bot, *, is_retry: bool = False) -> None:
    today = effective_today()
    if await queries.get_setting(EVENING_MARKER_SETTING) == today.isoformat():
        logger.info("Вечерний пинг пропущен: за %s уже отправлен", today)
        return
    try:
        text, subscription_markup = await build_evening_message()
        await bot.send_message(
            ALLOWED_USER_ID,
            text,
            reply_markup=_merge_markups(subscription_markup, web_app_markup()),
        )
    except Exception:
        logger.exception("Вечерний пинг не отправился")
        if is_retry:
            logger.error(
                "Повторный вечерний пинг за %s не удался, ждём следующий день",
                today,
            )
        else:
            _schedule_evening_retry(bot)
        return
    await queries.set_setting(EVENING_MARKER_SETTING, today.isoformat())
    logger.info("Вечерний пинг отправлен за %s", today)


def _schedule_evening_retry(bot: Bot) -> None:
    if _scheduler is None:
        return

    async def retry_job() -> None:
        await _send_evening_ping(bot, is_retry=True)

    _scheduler.add_job(
        retry_job,
        DateTrigger(run_date=_utcnow() + timedelta(minutes=RETRY_DELAY_MINUTES)),
        id=RETRY_JOB_ID,
        replace_existing=True,
        misfire_grace_time=3600,
        coalesce=True,
        max_instances=1,
    )
    logger.info(
        "Вечерний пинг: запланирован один повтор через %d минут",
        RETRY_DELAY_MINUTES,
    )


async def schedule_evening_catch_up(bot: Bot) -> bool:
    """Догоняющий запуск, если пинг за текущий финансовый день пропущен.

    Родственник ``schedule_catch_up_if_overdue``, но с семантикой «дата»:
    сравнивается не возраст отметки, а наступил ли уже момент напоминания
    для текущего финансового дня. Возвращает, было ли добавлено задание.
    """
    if _scheduler is None:
        return False
    time_str = await queries.get_setting("reminder_time") or DEFAULT_REMINDER_TIME
    hour, minute = parse_hhmm(time_str) or parse_hhmm(DEFAULT_REMINDER_TIME)
    today = effective_today()
    moment = scheduled_moment(hour, minute, today)
    now = _utcnow().astimezone(TZ)
    if now < moment:
        return False
    if await queries.get_setting(EVENING_MARKER_SETTING) == today.isoformat():
        logger.info("Догоняющий пинг не нужен: за %s уже отправлен", today)
        return False

    async def catch_up_job() -> None:
        await _send_evening_ping(bot)

    _scheduler.add_job(
        catch_up_job,
        DateTrigger(
            run_date=_utcnow() + timedelta(seconds=CATCH_UP_DELAY_SECONDS)
        ),
        id=CATCH_UP_JOB_ID,
        replace_existing=True,
        misfire_grace_time=3600,
        coalesce=True,
        max_instances=1,
    )
    logger.info(
        "Вечерний пинг: запланирован догоняющий запуск за %s", today
    )
    return True


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


async def schedule_catch_up_if_overdue(
    job_id: str,
    func,
    *,
    last_run_key: str,
    max_age: timedelta,
    delay_seconds: int = 60,
) -> bool:
    """Разовый догоняющий запуск, если прошлый прогон пропущен.

    Не блокирует старт: только добавляет задание через ``delay_seconds``.
    Возвращает, было ли задание добавлено.
    """
    if _scheduler is None:
        return False
    last_run = _parse_utc(await queries.get_setting(last_run_key))
    moment = _utcnow()
    if last_run is not None and moment - last_run < max_age:
        return False
    run_at = moment + timedelta(seconds=delay_seconds)
    _scheduler.add_job(
        func,
        DateTrigger(run_date=run_at),
        id=job_id,
        replace_existing=True,
        misfire_grace_time=3600,
        coalesce=True,
        max_instances=1,
    )
    logger.info(
        "Запланирован догоняющий запуск %s на %s", job_id, run_at.isoformat()
    )
    return True


async def setup(bot: Bot) -> AsyncIOScheduler:
    global _scheduler
    _scheduler = AsyncIOScheduler(timezone=TZ)
    time_str = await queries.get_setting("reminder_time") or DEFAULT_REMINDER_TIME
    hour, minute = parse_hhmm(time_str) or parse_hhmm(DEFAULT_REMINDER_TIME)
    _scheduler.add_job(
        _send_evening_ping, CronTrigger(hour=hour, minute=minute, timezone=TZ),
        args=[bot], id=JOB_ID,
        misfire_grace_time=3600, coalesce=True, max_instances=1,
    )

    async def backup_job() -> None:
        await backup_service.send_daily_backup(bot)

    if BACKUP_ENABLED:
        _scheduler.add_job(
            backup_job,
            CronTrigger(hour=BACKUP_HOUR, minute=0, timezone=TZ),
            id=BACKUP_JOB_ID,
            misfire_grace_time=3600,
            coalesce=True,
            max_instances=1,
        )

    _scheduler.start()
    logger.info("Вечерний пинг назначен на %02d:%02d", hour, minute)

    if BACKUP_ENABLED:
        await schedule_catch_up_if_overdue(
            BACKUP_CATCH_UP_JOB_ID,
            backup_job,
            last_run_key=backup_service.LAST_AT_SETTING,
            max_age=timedelta(hours=26),
        )
    await schedule_evening_catch_up(bot)
    return _scheduler


def is_running() -> bool:
    return _scheduler is not None and _scheduler.running


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
