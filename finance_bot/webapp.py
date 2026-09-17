"""Telegram-кнопки и Menu Button для открытия TMA."""

import logging
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from aiogram import Bot
from aiogram.types import (InlineKeyboardButton, InlineKeyboardMarkup,
                           MenuButtonWebApp, WebAppInfo)

from finance_bot.config import ALLOWED_USER_ID, TMA_URL

logger = logging.getLogger(__name__)


def _web_app_url(tab: str | None = None) -> str:
    if not tab:
        return TMA_URL
    parts = urlsplit(TMA_URL)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["tab"] = tab
    return urlunsplit((parts.scheme, parts.netloc, parts.path,
                       urlencode(query), parts.fragment))


def web_app_markup(
    text: str = "Открыть дашборд", *, tab: str | None = None
) -> InlineKeyboardMarkup | None:
    if not TMA_URL:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text=f"📊 {text}", web_app=WebAppInfo(url=_web_app_url(tab))
        )
    ]])


async def configure_menu_button(bot: Bot) -> None:
    if not TMA_URL:
        logger.warning("TMA_URL не задан — Menu Button и web_app-кнопки отключены")
        return
    try:
        await bot.set_chat_menu_button(
            chat_id=ALLOWED_USER_ID,
            menu_button=MenuButtonWebApp(
                text="Дашборд",
                web_app=WebAppInfo(url=TMA_URL),
            ),
        )
    except Exception:
        logger.exception("Не удалось установить Telegram Menu Button")
