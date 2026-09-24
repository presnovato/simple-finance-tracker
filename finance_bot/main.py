import asyncio
import logging

from aiogram import Bot, Dispatcher

from finance_bot.api import server
from finance_bot.config import (
    ALLOWED_USER_ID,
    BOT_TOKEN,
    DB_REQUIRE_PERSISTENT_DIR,
    PORT,
    validate_config,
)
from finance_bot.database import connection
from finance_bot.handlers import (
    budget, capture, dashboard, debts, edit, errors, export, manual, notes,
    settings, start, subscriptions,
)
from finance_bot.handlers.access import OwnerOnlyMiddleware
from finance_bot.services import bundle, llm, scheduler
from finance_bot.services import watchdog as watchdog_service
from finance_bot.webapp import configure_menu_button

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    problems = validate_config()
    if problems:
        raise RuntimeError(
            "Некорректная конфигурация:\n- " + "\n- ".join(problems)
        )

    await connection.init_pool()
    bot = None
    api_runner = None
    watchdog = None
    model_check = None
    try:
        bot = Bot(token=BOT_TOKEN)
        if connection.created_fresh and DB_REQUIRE_PERSISTENT_DIR:
            # Потерянный или неподключённый Volume создаёт пустую базу молча.
            try:
                await bot.send_message(
                    ALLOWED_USER_ID,
                    "⚠️ База данных создана заново. Если это не первый "
                    "запуск — восстанови её из последнего бэкапа.",
                )
            except Exception:
                logger.exception("Не удалось предупредить о пересоздании базы")
        dp = Dispatcher()
        dp.message.middleware(OwnerOnlyMiddleware())
        dp.callback_query.middleware(OwnerOnlyMiddleware())

        # Обработчик ошибок идёт первым, чтобы ловить сбои любых хендлеров.
        errors.register(dp)

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
        bundle.log_bundle_freshness()

        try:
            me = await bot.get_me()
            logger.info("Бот @%s (id=%s) запущен", me.username, me.id)
        except Exception:
            logger.warning("get_me() не удался на старте")

        watchdog = watchdog_service.TelegramWatchdog(bot)
        watchdog_service.set_current(watchdog)
        watchdog.start()

        # Проверка моделей не блокирует старт и не роняет бота при сбое сети.
        model_check = asyncio.create_task(llm.check_models_available(bot))

        logger.info("Запускаю polling")
        await dp.start_polling(bot, close_bot_session=False)
    finally:
        if model_check is not None:
            model_check.cancel()
            try:
                await model_check
            except (asyncio.CancelledError, Exception):
                pass
        if watchdog is not None:
            await watchdog.stop()
        watchdog_service.set_current(None)
        scheduler.shutdown()
        if api_runner is not None:
            await api_runner.cleanup()
        await llm.close_client()
        if bot is not None:
            await bot.session.close()
        await connection.close_pool()


if __name__ == "__main__":
    asyncio.run(main())
