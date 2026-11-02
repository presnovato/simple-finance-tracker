"""Общие помощники API-роутов."""

from aiohttp import web


def _error(message: str, status: int = 400) -> web.Response:
    return web.json_response({"error": message}, status=status)
