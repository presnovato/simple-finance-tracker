import asyncio
import logging

from aiogram import Bot, Dispatcher

from finance_bot.api import server
from finance_bot.config import BOT_TOKEN, PORT
from finance_bot.database import connection
from finance_bot.handlers import (
    budget, capture, dashboard, debts, edit, export, manual, notes, settings,
    start, subscriptions,
)
from finance_bot.handlers.access import OwnerOnlyMiddleware
from finance_bot.services import scheduler
from finance_bot.webapp import configure_menu_button

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    await connection.init_pool()
    bot = None
    api_runner = None
    try:
        bot = Bot(token=BOT_TOKEN)
        dp = Dispatcher()
        dp.message.middleware(OwnerOnlyMiddleware())
        dp.callback_query.middleware(OwnerOnlyMiddleware())

        # Порядок важен: команды → правки reply-ем → catch-all захват
        dp.include_router(start.router)
        dp.include_router(manual.router)
        dp.include_router(dashboard.router)
        dp.include_router(settings.router)
        dp.include_router(notes.router)
        dp.include_router(debts.router)
        dp.include_router(export.router)
        dp.include_router(subscriptions.router)
        dp.include_router(edit.router)
        dp.include_router(budget.router)
        dp.include_router(capture.router)

        api_runner = await server.start_server(PORT, bot=bot)
        await configure_menu_button(bot)
        await scheduler.setup(bot)

        logger.info("Запускаю polling")
        await dp.start_polling(bot, close_bot_session=False)
    finally:
        scheduler.shutdown()
        if api_runner is not None:
            await api_runner.cleanup()
        if bot is not None:
            await bot.session.close()
        await connection.close_pool()


if __name__ == "__main__":
    asyncio.run(main())
