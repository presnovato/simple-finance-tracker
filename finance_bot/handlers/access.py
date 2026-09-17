"""Бот личный: всё, что не от владельца, молча игнорируется."""

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from finance_bot.config import ALLOWED_USER_ID


class OwnerOnlyMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: TelegramObject, data: dict):
        user = data.get("event_from_user")
        if user is None or user.id != ALLOWED_USER_ID:
            return None
        return await handler(event, data)
