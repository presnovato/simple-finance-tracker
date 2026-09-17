"""Пользовательские заметки к операции, не зависящие от LLM-правок."""

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from finance_bot.database import queries

router = Router()


@router.message(Command("note"))
async def cmd_note(message: Message, command: CommandObject) -> None:
    reply = message.reply_to_message
    if reply is None or not reply.from_user or not reply.from_user.is_bot:
        await message.answer(
            "Ответь командой /note текст на подтверждение нужной операции."
        )
        return

    op = await queries.get_by_tg_message_id(reply.message_id)
    if op is None:
        await message.reply(
            "Не нашёл операцию по этому сообщению — "
            "оно не про запись или запись уже удалена."
        )
        return

    note = (command.args or "").strip()
    if len(note) > 1000:
        await message.reply("⚠️ Заметка слишком длинная — максимум 1000 символов.")
        return

    await queries.patch_operation(op["id"], {"note": note or None})
    text = "📝 Заметка сохранена." if note else "📝 Заметка очищена."
    sent = await message.reply(text)
    await queries.set_tg_message_id(op["id"], sent.message_id)
