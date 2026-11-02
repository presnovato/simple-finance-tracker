from types import SimpleNamespace

import pytest

from finance_bot.database import connection, queries
from finance_bot.handlers import capture
from finance_bot.handlers.capture import is_many_caption
from finance_bot.services import llm


@pytest.fixture
async def sqlite_database(tmp_path, monkeypatch):
    await connection.close_pool()
    monkeypatch.setattr(connection, "DB_PATH", str(tmp_path / "finance.db"))
    monkeypatch.setattr(connection, "DB_REQUIRE_PERSISTENT_DIR", False)
    await connection.init_pool()
    try:
        yield tmp_path / "finance.db"
    finally:
        await connection.close_pool()


class FakeMessage:
    def __init__(self, text: str | None = None, caption: str | None = None):
        self.text = text
        self.caption = caption
        self.chat = SimpleNamespace(id=1)
        self.replies: list[str] = []
        self.answers: list[str] = []

    async def reply(self, text, **_kwargs):
        self.replies.append(text)
        return SimpleNamespace(message_id=777)

    async def answer(self, text, **_kwargs):
        self.answers.append(text)
        return SimpleNamespace(message_id=778)


class FakeBot:
    def __init__(self) -> None:
        self.downloads: list = []
        self.chat_actions: list = []

    async def download(self, file):
        self.downloads.append(file)
        return SimpleNamespace(read=lambda: b"data")

    async def send_chat_action(self, **kwargs):
        self.chat_actions.append(kwargs)
        return True


def test_many_mode_requires_explicit_caption_marker():
    assert is_many_caption("список") is True
    assert is_many_caption("Расходы за день") is True
    assert is_many_caption("обычный чек") is False
    assert is_many_caption(None) is False


def test_many_mode_command_is_one_shot():
    capture._awaiting_many_shot = True
    assert capture._consume_many_mode(None) is True
    assert capture._consume_many_mode(None) is False


async def test_unavailable_llm_stores_draft_and_replies(sqlite_database):
    message = FakeMessage(text="такси 450")
    error = llm.LLMUnavailable("таймаут")

    await capture.handle_llm_unavailable(message, error, source="бот-текст")

    assert message.replies
    assert "ИИ сейчас недоступен (таймаут)" in message.replies[0]
    draft = await queries.get_pending_capture(777)
    assert draft is not None
    assert draft["draft"]["amount"] is None


async def test_unavailable_llm_alerts_openrouter_once_per_window(sqlite_database):
    first = FakeMessage(text="x")
    error = llm.LLMUnavailable("ключ недействителен", status=401)

    await capture.handle_llm_unavailable(first, error, source="бот-текст")
    assert any("OpenRouter" in text for text in first.answers)

    second = FakeMessage(text="y")
    await capture.handle_llm_unavailable(second, error, source="бот-текст")
    assert second.answers == []


async def test_on_text_reports_llm_unavailable(sqlite_database, monkeypatch):
    message = FakeMessage(text="такси 450")

    async def handle_text(_message):
        return False

    async def no_debt(_message, _today):
        return False

    async def boom(_text, _today):
        raise llm.LLMUnavailable("таймаут")

    monkeypatch.setattr(capture.manual, "handle_text", handle_text)
    monkeypatch.setattr(capture.debts, "try_handle_debt_message", no_debt)
    monkeypatch.setattr(capture.llm, "is_available", lambda: True)
    monkeypatch.setattr(capture.llm, "extract_from_text", boom)

    await capture.on_text(message)

    assert message.replies
    assert "ИИ сейчас недоступен" in message.replies[0]
    assert await queries.get_pending_capture(777) is not None


async def test_oversized_photo_is_not_downloaded(sqlite_database, monkeypatch):
    monkeypatch.setattr(capture.llm, "is_available", lambda: True)
    message = FakeMessage(caption="чек")
    message.photo = [
        SimpleNamespace(file_size=capture.MAX_TELEGRAM_FILE_BYTES + 1)
    ]
    bot = FakeBot()

    await capture.on_photo(message, bot)

    assert bot.downloads == []
    assert message.replies
    assert "20 МБ" in message.replies[0]


async def test_oversized_document_is_not_downloaded(sqlite_database, monkeypatch):
    monkeypatch.setattr(capture.llm, "is_available", lambda: True)
    message = FakeMessage()
    message.document = SimpleNamespace(
        mime_type="application/pdf",
        file_size=capture.MAX_TELEGRAM_FILE_BYTES + 1,
        file_name="receipt.pdf",
    )
    bot = FakeBot()

    await capture.on_document(message, bot)

    assert bot.downloads == []
    assert "20 МБ" in message.replies[0]
