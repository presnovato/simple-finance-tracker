import logging
from datetime import datetime, timezone

from aiogram import Bot, Dispatcher, Router
from aiogram.types import CallbackQuery, Chat, Message, Update, User

from finance_bot.handlers import errors

TOKEN = "123456789:AA" + "x" * 35


class RecordingSession:
    """Заглушка сессии Telegram: запоминает методы, не ходит в сеть."""

    def __init__(self, *, fail: bool = False) -> None:
        self.calls: list = []
        self.fail = fail

    async def __call__(self, bot, method, timeout=None):
        self.calls.append(method)
        if self.fail:
            raise RuntimeError("telegram down")
        return None

    async def close(self) -> None:
        return None


def _bot(**kwargs) -> tuple[Bot, RecordingSession]:
    bot = Bot(token=TOKEN)
    session = RecordingSession(**kwargs)
    bot.session = session
    return bot, session


def _user() -> User:
    return User(id=1, is_bot=False, first_name="Owner")


def _message_update(update_id: int) -> Update:
    return Update(
        update_id=update_id,
        message=Message(
            message_id=update_id,
            date=datetime.now(timezone.utc),
            chat=Chat(id=1, type="private"),
            from_user=_user(),
            text="привет",
        ),
    )


def _callback_update(update_id: int) -> Update:
    return Update(
        update_id=update_id,
        callback_query=CallbackQuery(
            id="cb1",
            from_user=_user(),
            chat_instance="instance",
            data="action",
        ),
    )


def _dispatcher_raising_on(observer: str) -> Dispatcher:
    dispatcher = Dispatcher()
    errors.register(dispatcher)
    failing = Router()

    if observer == "message":

        @failing.message()
        async def boom_message(_message):
            raise RuntimeError("boom")

    else:

        @failing.callback_query()
        async def boom_callback(_callback):
            raise RuntimeError("boom")

    dispatcher.include_router(failing)
    return dispatcher


async def test_message_failure_notifies_owner_once_and_rate_limits():
    errors._last_notified_at = None
    bot, session = _bot()
    dispatcher = _dispatcher_raising_on("message")

    await dispatcher.feed_update(bot, _message_update(1))
    await dispatcher.feed_update(bot, _message_update(2))

    assert len(session.calls) == 1
    assert session.calls[0].text == errors.MESSAGE_FAILURE_TEXT
    assert session.calls[0].chat_id == 1


async def test_callback_failure_answers_with_alert():
    errors._last_notified_at = None
    bot, session = _bot()
    dispatcher = _dispatcher_raising_on("callback")

    await dispatcher.feed_update(bot, _callback_update(3))

    assert len(session.calls) == 1
    assert session.calls[0].text == errors.CALLBACK_FAILURE_TEXT
    assert session.calls[0].show_alert is True


async def test_errors_are_logged_even_when_notifications_are_rate_limited(caplog):
    errors._last_notified_at = None
    bot, _session = _bot()
    dispatcher = _dispatcher_raising_on("message")

    with caplog.at_level(logging.ERROR):
        await dispatcher.feed_update(bot, _message_update(1))
        await dispatcher.feed_update(bot, _message_update(2))

    logged = [
        record
        for record in caplog.records
        if "Ошибка при обработке update" in record.getMessage()
    ]
    assert len(logged) == 2


async def test_error_handler_does_not_raise_when_notification_fails():
    errors._last_notified_at = None
    bot, session = _bot(fail=True)
    dispatcher = _dispatcher_raising_on("message")

    # Ничего не должно всплыть наружу.
    await dispatcher.feed_update(bot, _message_update(1))

    assert session.calls  # попытка была


async def test_rate_limit_resets_after_interval(monkeypatch):
    errors._last_notified_at = None
    bot, session = _bot()
    dispatcher = _dispatcher_raising_on("message")

    await dispatcher.feed_update(bot, _message_update(1))
    assert len(session.calls) == 1

    monkeypatch.setattr(errors, "_last_notified_at", 0.0)
    await dispatcher.feed_update(bot, _message_update(2))
    assert len(session.calls) == 2
