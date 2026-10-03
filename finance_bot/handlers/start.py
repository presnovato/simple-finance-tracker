import logging

from aiogram import Bot, Router
from aiogram.filters import CommandStart
from aiogram.types import BotCommand, BotCommandScopeChat, Message

from finance_bot.config import ALLOWED_USER_ID

logger = logging.getLogger(__name__)

router = Router()

# Меню «/» в Telegram. Имена команд — только латиница, цифры и «_».
BOT_COMMANDS = (
    ("manual", "Ручной ввод операции без ИИ"),
    ("dashboard", "Сводка расходов"),
    ("budget", "Недельный бюджет"),
    ("balance", "Текущий баланс или новое значение"),
    ("list", "Разобрать скриншот списка трат за день"),
    ("note", "Заметка к операции (ответом на подтверждение)"),
    ("export", "Выгрузить операции или копию базы"),
    ("backup", "Копия базы за нужный день"),
    ("remind", "Время вечернего пинга, например 21:30"),
    ("cancel", "Отменить ручной ввод"),
    ("start", "Справка"),
)

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
/balance — текущий баланс; /balance 15000 — задать новый
/list — разобрать следующим сообщением список трат за день
/note текст — заметка к операции (ответом на подтверждение)
/export — выгрузить операции или копию базы
/backup — копия базы за нужный день
/remind 21:30 — время вечернего пинга
/cancel — отменить ручной ввод
"""


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    await message.answer(HELP_TEXT)


async def configure_commands(bot: Bot) -> None:
    """Регистрирует меню команд только в чате владельца."""
    try:
        await bot.set_my_commands(
            [BotCommand(command=name, description=text) for name, text in BOT_COMMANDS],
            scope=BotCommandScopeChat(chat_id=ALLOWED_USER_ID),
        )
    except Exception:
        logger.exception("Не удалось установить меню команд")
