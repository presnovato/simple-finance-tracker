"""Подтверждение регулярных списаний из вечернего пинга."""

from datetime import date

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardMarkup

from finance_bot.core.subscriptions import format_subscription_amount
from finance_bot.database import queries
from finance_bot.services import budget as budget_service

router = Router()


def _replace_subscription_line(text: str, title: str, replacement: str) -> str:
    lines = text.splitlines()
    prefix = f"• {title} —"
    for index, line in enumerate(lines):
        if line.startswith(prefix):
            lines[index] = replacement
            break
    return "\n".join(lines)


def _without_subscription_buttons(
    markup: InlineKeyboardMarkup | None, subscription_id: int
) -> InlineKeyboardMarkup | None:
    if markup is None:
        return None
    rows = []
    for row in markup.inline_keyboard:
        kept = []
        for button in row:
            data = button.callback_data or ""
            parts = data.split(":")
            if len(parts) == 4 and parts[0] == "subs" \
                    and parts[2] == str(subscription_id):
                continue
            kept.append(button)
        if kept:
            rows.append(kept)
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


@router.callback_query(F.data.startswith("subs:"))
async def on_subscription_charge(callback: CallbackQuery) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) != 4 or parts[1] not in {"yes", "no"}:
        await callback.answer("Некорректная кнопка", show_alert=True)
        return
    try:
        subscription_id = int(parts[2])
        charge_date = date.fromisoformat(parts[3])
    except ValueError:
        await callback.answer("Некорректная дата списания", show_alert=True)
        return

    result = await queries.charge_subscription(
        subscription_id,
        confirmed=parts[1] == "yes",
        op_date=charge_date,
        expected_next_charge=charge_date,
    )
    if result is None:
        await callback.answer("Подписка уже отменена или не найдена", show_alert=True)
        return

    subscription = result["subscription"]
    message = callback.message
    if result.get("stale"):
        updated_text = _replace_subscription_line(
            message.text or "",
            subscription["title"],
            f"⏭ {subscription['title']} — уже отмечено",
        )
        await message.edit_text(
            updated_text,
            reply_markup=_without_subscription_buttons(
                message.reply_markup, subscription_id
            ),
        )
        await callback.answer("Уже отмечено", show_alert=True)
        return

    if result.get("operation_created"):
        await budget_service.notify_after_new_expense(
            getattr(callback, "bot", None), result["operation_date"]
        )

    amount = format_subscription_amount(subscription["amount"])
    if parts[1] == "yes":
        replacement = f"✅ {subscription['title']} — {amount} записано"
        answer = "Списание записано"
    else:
        replacement = f"⏭ {subscription['title']} — пропущено"
        answer = "Списание пропущено"
    await message.edit_text(
        _replace_subscription_line(message.text or "", subscription["title"], replacement),
        reply_markup=_without_subscription_buttons(message.reply_markup, subscription_id),
    )
    await callback.answer(answer)


@router.callback_query(F.data.startswith("subdel:"))
async def on_subscription_delete(callback: CallbackQuery) -> None:
    try:
        subscription_id = int((callback.data or "").split(":", 1)[1])
    except (IndexError, ValueError):
        await callback.answer("Некорректная подписка", show_alert=True)
        return
    cancelled = await queries.cancel_subscription(subscription_id)
    if cancelled is None:
        await callback.answer("Подписка уже отменена", show_alert=True)
        return
    await callback.message.edit_text("🗑 Подписку отменил.")
    await callback.answer("Подписка отменена")
