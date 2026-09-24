"""Настройки приложения.

Выделено из ``queries.py`` при разбиении oversized-модуля; код перенесён без
изменений.
"""

from finance_bot.database.connection import get_pool

# --- settings -------------------------------------------------------------

async def get_setting(key: str) -> str | None:
    row = await get_pool().fetchrow(
        "SELECT value FROM settings WHERE key = ?", key
    )
    return row["value"] if row else None


async def set_setting(key: str, value: str) -> None:
    await get_pool().execute(
        """
        INSERT INTO settings (key, value) VALUES (?, ?)
        ON CONFLICT (key) DO UPDATE SET value = excluded.value
        """,
        key,
        value,
    )
