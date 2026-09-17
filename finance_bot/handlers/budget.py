"""Команда текущего недельного бюджета."""

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from finance_bot.services import budget as budget_service
from finance_bot.webapp import web_app_markup

router = Router()


@router.message(Command("budget"))
async def cmd_budget(message: Message) -> None:
    report = await budget_service.get_budget()
    await message.answer(
        budget_service.render_budget(report),
        reply_markup=web_app_markup("Открыть бюджет"),
    )
