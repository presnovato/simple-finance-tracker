"""Подтверждение операций дня из вечернего пинга (spec 03)."""

from datetime import date

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardMarkup

from finance_bot.core.dates import effective_today
from finance_bot.database import queries

router = Router()


def _without_day_button(
    markup: InlineKeyboardMarkup | None, target: str
) -> InlineKeyboardMarkup | None:
    if markup is None:
        return None
    rows = []
    for row in markup.inline_keyboard:
        kept = [button for button in row if (button.callback_data or "") != target]
        if kept:
            rows.append(kept)
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


@router.callback_query(F.data.startswith("review:day:"))
async def on_confirm_day(callback: CallbackQuery) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) != 3:
        await callback.answer("Некорректная кнопка", show_alert=True)
        return
    try:
        day = date.fromisoformat(parts[2])
    except ValueError:
        await callback.answer("Некорректная дата", show_alert=True)
        return
    if day > effective_today():
        await callback.answer("Это день из будущего", show_alert=True)
        return

    confirmed = await queries.confirm_review_for_date(day)
    await callback.answer(
        f"Отмечено: {confirmed}" if confirmed else "Уже отмечено"
    )
    try:
        # Повторное нажатие безопасно: кнопку убираем без правки текста.
        await callback.message.edit_reply_markup(
            reply_markup=_without_day_button(
                callback.message.reply_markup, callback.data or ""
            )
        )
    except Exception:
        # Устаревшее сообщение без изменений — ответ уже отправлен.
        pass
