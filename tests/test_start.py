import re

import pytest
from aiogram.types import BotCommandScopeChat

from finance_bot.handlers import start


def test_bot_commands_are_valid_and_documented():
    for name, description in start.BOT_COMMANDS:
        assert re.fullmatch(r"[a-z0-9_]{1,32}", name)
        assert 3 <= len(description) <= 256
        if name != "start":
            assert f"/{name}" in start.HELP_TEXT


@pytest.mark.asyncio
async def test_configure_commands_scopes_menu_to_owner(monkeypatch):
    monkeypatch.setattr(start, "ALLOWED_USER_ID", 42)
    calls = []

    class FakeBot:
        async def set_my_commands(self, commands, scope):
            calls.append((commands, scope))

    await start.configure_commands(FakeBot())

    commands, scope = calls[0]
    assert [item.command for item in commands] == [name for name, _ in start.BOT_COMMANDS]
    assert isinstance(scope, BotCommandScopeChat)
    assert scope.chat_id == 42


@pytest.mark.asyncio
async def test_configure_commands_failure_does_not_crash_startup():
    class BrokenBot:
        async def set_my_commands(self, commands, scope):
            raise RuntimeError("network")

    await start.configure_commands(BrokenBot())
