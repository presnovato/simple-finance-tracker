"""Typed application keys shared by the API server and routes."""

from aiogram import Bot
from aiohttp import web

BUDGET_BOT_KEY = web.AppKey("budget_bot", Bot | None)
