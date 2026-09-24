"""Правка операции reply-ем на подтверждение бота: «это продукты, 540».

Роутер подключается ДО capture — фильтр ловит только reply на сообщения бота.
"""

import logging

from aiogram import F, Router
from aiogram.types import Message

from finance_bot.core.dashboard import fmt_amount
from finance_bot.core.dates import effective_today
from finance_bot.database import queries
from finance_bot.handlers import capture
from finance_bot.services import llm

logger = logging.getLogger(__name__)

router = Router()

DELETE_WORDS = {"удали", "удалить", "убери", "delete", "del"}


async def _correct(message: Message, record: dict, context: str | None):
    """Правка через LLM; недоступность ИИ не роняет хендлер."""
    try:
        return await llm.correct_operation(
            record, message.text, effective_today(), context=context
        )
    except llm.LLMUnavailable as error:
        await message.reply(
            capture.LLM_UNAVAILABLE_TEXT.format(reason=error.reason)
        )
        return None


@router.message(F.text, F.reply_to_message, F.reply_to_message.from_user.is_bot)
async def on_correction(message: Message) -> None:
    reply = message.reply_to_message
    op = await queries.get_by_tg_message_id(reply.message_id)
    if op is None:
        pending = await queries.get_pending_capture(reply.message_id)
        if pending is None:
            await message.reply("Не нашёл операцию по этому сообщению — "
                                "оно не про запись или запись уже удалена.")
            return
        if message.text.strip().lower() in DELETE_WORDS:
            await queries.delete_pending_capture(reply.message_id)
            await message.reply("🗑 Черновик удалил, операция не записана.")
            return

        corrected = await _correct(
            message,
            pending["draft"],
            pending.get("context") or reply.text or reply.caption,
        )
        if corrected is None:
            return
        if corrected["amount"] is None or corrected["amount"] <= 0 \
                or corrected["type"] not in ("расход", "доход", "перевод"):
            await message.reply(
                "⚠️ Не понял правку — укажи сумму и тип операции ещё раз."
            )
            return

        await capture.save_and_confirm(
            message,
            corrected,
            pending["source"],
        )
        await queries.delete_pending_capture(reply.message_id)
        return

    if message.text.strip().lower() in DELETE_WORDS:
        await queries.delete_operation(op["id"])
        await message.reply(f"🗑 Удалил: {op['type']} {fmt_amount(op['amount'])}.")
        return

    corrected = await _correct(
        message, op, reply.text or reply.caption
    )
    if corrected is None:
        return
    if corrected["amount"] is None or corrected["amount"] <= 0 \
            or corrected["type"] not in ("расход", "доход", "перевод"):
        sent = await message.reply(
            "⚠️ Не понял правку — попробуй сформулировать иначе."
        )
        await queries.set_tg_message_id(op["id"], sent.message_id)
        return

    transfer_direction = (
        corrected.get("transfer_direction") or "out"
        if corrected["type"] == "перевод"
        else None
    )
    await queries.update_operation(op["id"], {
        "op_date": corrected["date"],
        "type": corrected["type"],
        "amount": corrected["amount"],
        "category": corrected["category"],
        "comment": corrected["comment"],
        "account": corrected["account"],
        "transfer_direction": transfer_direction,
        "needs_review": False,  # раз пользователь поправил — запись выверена
    })

    text = f"✏️ Исправил: {corrected['type']} {fmt_amount(corrected['amount'])}"
    if corrected["type"] != "перевод" and corrected["category"]:
        text += f" · {corrected['category']}"
    if corrected["comment"]:
        text += f"\n{corrected['comment']}"
    sent = await message.reply(text)
    # правки можно продолжать reply-ем уже на новое подтверждение
    await queries.set_tg_message_id(op["id"], sent.message_id)
