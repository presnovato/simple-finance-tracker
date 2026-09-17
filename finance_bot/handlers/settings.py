from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from finance_bot.core.balance import format_cash_amount, parse_anchor_amount
from finance_bot.core.dates import effective_today, format_day_month
from finance_bot.database import queries
from finance_bot.services import balance as balance_service
from finance_bot.services import scheduler

router = Router()

BALANCE_LIMITATION = (
    "Переводы между своими счетами не меняют баланс; направление обычных "
    "переводов при неуверенности отмечается для проверки."
)


@router.message(Command("remind"))
async def cmd_remind(message: Message, command: CommandObject) -> None:
    parsed = scheduler.parse_hhmm(command.args or "")
    if parsed is None:
        current = await queries.get_setting("reminder_time") or "21:00"
        await message.answer(
            f"Вечерний пинг сейчас в {current}.\n"
            "Поменять: /remind 22:30"
        )
        return
    hour, minute = parsed
    await queries.set_setting("reminder_time", f"{hour:02d}:{minute:02d}")
    scheduler.reschedule(hour, minute)
    await message.answer(f"⏰ Вечерний пинг теперь в {hour:02d}:{minute:02d}.")


@router.message(Command("balance"))
async def cmd_balance(message: Message, command: CommandObject) -> None:
    value = (command.args or "").strip()
    if not value:
        snapshot = await balance_service.get_snapshot()
        if snapshot is None:
            await message.answer(
                "Якорь для «денег на руках» ещё не задан.\n"
                "Установить: /balance 123456.78\n\n"
                f"ℹ️ {BALANCE_LIMITATION}"
            )
            return
        await message.answer(
            f"💰 Деньги на руках: {format_cash_amount(snapshot['amount'])}\n"
            f"Якорь: {format_cash_amount(snapshot['anchor_amount'])} "
            f"на {format_day_month(snapshot['anchor_date'])}\n"
            f"Движений с даты якоря: {snapshot['movement_count']}\n\n"
            f"ℹ️ {BALANCE_LIMITATION}"
        )
        return

    try:
        new_amount = parse_anchor_amount(value)
    except ValueError as exc:
        await message.answer(
            f"⚠️ {exc}. Пример: /balance 123456.78"
        )
        return

    previous = await balance_service.get_snapshot()
    anchor_date = effective_today()
    await balance_service.set_anchor(new_amount, anchor_date)

    if previous is None:
        change_text = (
            "Расчётного значения раньше не было. "
            f"Стало {format_cash_amount(new_amount)}."
        )
    else:
        difference = new_amount - previous["amount"]
        change_text = (
            f"Было по расчёту {format_cash_amount(previous['amount'])}, "
            f"стало {format_cash_amount(new_amount)}, расхождение "
            f"{format_cash_amount(difference, show_plus=True)}."
        )
    await message.answer(
        f"💰 {change_text}\n"
        f"Новый якорь: {format_day_month(anchor_date)}.\n\n"
        f"ℹ️ {BALANCE_LIMITATION}"
    )
