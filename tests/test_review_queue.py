"""Очередь проверки и подтверждение дня из вечернего пинга (spec 03)."""

from datetime import date
from decimal import Decimal

import pytest
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from finance_bot import webapp
from finance_bot.database import connection, queries
from finance_bot.handlers import review
from finance_bot.services import scheduler


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


async def _expense(day: date, amount: str, *, review: bool) -> int:
    return await queries.insert_operation(
        day, "расход", Decimal(amount), "Еда дома", None, None,
        "test", review,
    )


async def test_needs_review_count_and_confirm_day(sqlite_database):
    day = date(2026, 9, 14)
    await _expense(day, "100", review=True)
    await _expense(day, "200", review=True)
    await _expense(day, "300", review=False)
    other = date(2026, 9, 15)
    await _expense(other, "400", review=True)
    deleted_id = await _expense(day, "500", review=True)
    await queries.soft_delete_operation(deleted_id)

    assert await queries.needs_review_count() == 3

    assert await queries.confirm_review_for_date(day) == 2
    assert await queries.needs_review_count() == 1
    # Повторное нажатие безопасно.
    assert await queries.confirm_review_for_date(day) == 0

    # Удалённая операция не подтверждается и не воскрешается.
    deleted = await queries.get_operation(deleted_id, include_deleted=True)
    assert deleted is not None
    assert deleted["needs_review"] is True
    assert deleted["deleted_at"] is not None


class _FakeMessage:
    def __init__(self, markup: InlineKeyboardMarkup | None) -> None:
        self.reply_markup = markup
        self.edited: InlineKeyboardMarkup | None = None

    async def edit_reply_markup(self, reply_markup=None):
        self.edited = reply_markup


class _FakeCallback:
    def __init__(self, data: str, markup: InlineKeyboardMarkup | None) -> None:
        self.data = data
        self.message = _FakeMessage(markup)
        self.answers: list[str | None] = []

    async def answer(self, text: str | None = None, **_kwargs):
        self.answers.append(text)


async def test_review_callback_confirms_day_and_removes_button(sqlite_database):
    day = date(2026, 9, 14)
    await _expense(day, "100", review=True)
    day_iso = day.isoformat()
    target = f"review:day:{day_iso}"
    markup = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Всё за сегодня верно", callback_data=target),
        InlineKeyboardButton(text="другое", callback_data="subs:yes:1:2026-09-14"),
    ]])
    callback = _FakeCallback(target, markup)

    await review.on_confirm_day(callback)  # type: ignore[arg-type]

    assert callback.answers == ["Отмечено: 1"]
    assert await queries.needs_review_count() == 0
    remaining = [
        button.callback_data
        for row in (callback.message.edited or InlineKeyboardMarkup(inline_keyboard=[])).inline_keyboard
        for button in row
    ]
    assert target not in remaining
    assert "subs:yes:1:2026-09-14" in remaining


async def test_review_callback_second_press_is_safe(sqlite_database):
    day = date(2026, 9, 14)
    await _expense(day, "100", review=True)
    target = f"review:day:{day.isoformat()}"

    await review.on_confirm_day(_FakeCallback(target, None))  # type: ignore[arg-type]
    callback = _FakeCallback(target, None)
    await review.on_confirm_day(callback)  # type: ignore[arg-type]

    assert callback.answers == ["Уже отмечено"]


async def test_evening_message_uses_short_queue_when_tma_configured(monkeypatch):
    today = date(2026, 9, 14)
    long_review = [{
        "op_date": date(2026, 9, 1), "amount": Decimal("100"),
        "comment": "старая операция", "category": "Прочее",
    }]

    async def day_operations(_today):
        return [{"type": "расход", "amount": Decimal("100")}]

    async def pending_review():
        return long_review

    async def subscriptions(_status="active", next_charge=None):
        return []

    monkeypatch.setattr(scheduler, "effective_today", lambda: today)
    monkeypatch.setattr(scheduler, "TMA_URL", "https://tma.example/app")
    monkeypatch.setattr(webapp, "TMA_URL", "https://tma.example/app")
    monkeypatch.setattr(scheduler.queries, "day_operations", day_operations)
    monkeypatch.setattr(scheduler.queries, "pending_review", pending_review)
    monkeypatch.setattr(scheduler.queries, "list_subscriptions", subscriptions)
    monkeypatch.setattr(
        scheduler.budget_service, "evening_budget_lines", _empty_lines
    )

    text, markup = await scheduler.build_evening_message()

    assert "Требуют уточнения: 1" in text
    assert "старая операция" not in text
    assert markup is not None
    buttons = [button for row in markup.inline_keyboard for button in row]
    assert any(button.callback_data == f"review:day:{today.isoformat()}" for button in buttons)
    assert any(
        button.web_app and "review=1" in button.web_app.url and "tab=history" in button.web_app.url
        for button in buttons
    )


async def test_evening_message_keeps_reply_list_without_tma(monkeypatch):
    today = date(2026, 9, 14)

    async def day_operations(_today):
        return []

    async def pending_review():
        return [{
            "op_date": date(2026, 9, 1), "amount": Decimal("100"),
            "comment": "старая операция", "category": "Прочее",
        }]

    async def subscriptions(_status="active", next_charge=None):
        return []

    monkeypatch.setattr(scheduler, "effective_today", lambda: today)
    monkeypatch.setattr(scheduler, "TMA_URL", "")
    monkeypatch.setattr(webapp, "TMA_URL", "")
    monkeypatch.setattr(scheduler.queries, "day_operations", day_operations)
    monkeypatch.setattr(scheduler.queries, "pending_review", pending_review)
    monkeypatch.setattr(scheduler.queries, "list_subscriptions", subscriptions)
    monkeypatch.setattr(
        scheduler.budget_service, "evening_budget_lines", _empty_lines
    )

    text, markup = await scheduler.build_evening_message()

    assert "старая операция" in text
    assert "Ответь (reply)" in text
    assert markup is None


async def _empty_lines(_today):
    return []


async def test_budget_error_does_not_break_evening_message(monkeypatch):
    today = date(2026, 9, 14)  # понедельник: воскресного блока нет

    async def day_operations(_today):
        return [{"type": "расход", "amount": Decimal("100")}]

    async def pending_review():
        return []

    async def subscriptions(_status="active", next_charge=None):
        return []

    async def broken(_today):
        raise RuntimeError("бюджет сломался")

    monkeypatch.setattr(scheduler, "effective_today", lambda: today)
    monkeypatch.setattr(scheduler.queries, "day_operations", day_operations)
    monkeypatch.setattr(scheduler.queries, "pending_review", pending_review)
    monkeypatch.setattr(scheduler.queries, "list_subscriptions", subscriptions)
    monkeypatch.setattr(scheduler.budget_service, "evening_budget_lines", broken)

    text, _ = await scheduler.build_evening_message()

    # Сбой необязательной бюджетной строки не ломает существующий пинг.
    assert "Сегодня записано" in text
