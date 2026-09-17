from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message

router = Router()

HELP_TEXT = """💰 Финансовый бот

Просто кидай операции — я разберу и запишу:
• текстом: «такси 450», «кофе 200р»
• PDF-чеком (Сбер, Т-Банк, Альфа)
• фото/скрином чека (ВТБ)

Ошибся я — ответь (reply) на моё подтверждение
и напиши, что поправить: «это продукты, 540»
или просто «удали».

Команды:
/manual — ручной ввод операции без ИИ
/dashboard — сводка расходов
/budget — статус недельного бюджета
/export — выгрузить операции или копию базы
/список — разобрать следующим сообщением список трат за день
/remind 21:30 — время вечернего пинга
"""


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    await message.answer(HELP_TEXT)
