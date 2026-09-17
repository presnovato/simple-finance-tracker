"""Настройки отображения криптоактивов в обзоре."""

from finance_bot.database import queries

OVERVIEW_VISIBLE_KEY = "crypto_overview_visible"


async def is_overview_visible() -> bool:
    """Возвращает настройку с безопасным default-on для старых баз."""
    return await queries.get_setting(OVERVIEW_VISIBLE_KEY) != "0"


async def set_overview_visible(visible: bool) -> None:
    await queries.set_setting(OVERVIEW_VISIBLE_KEY, "1" if visible else "0")
