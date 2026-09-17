"""Пошаговый ручной ввод операции без обращения к LLM."""

import re
from datetime import date, timedelta
from decimal import Decimal

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from finance_bot.api import schemas
from finance_bot.config import EXPENSE_CATEGORIES, INCOME_CATEGORIES, OPERATION_TYPES
from finance_bot.core.dashboard import fmt_amount
from finance_bot.core.dates import effective_today, format_day_month, resolve_relative_date
from finance_bot.core.parsing import parse_amount
from finance_bot.database import queries
from finance_bot.services import budget as budget_service
from finance_bot.services import operations as operation_service

router = Router()

TYPE_STEP = "type"
AMOUNT_STEP = "amount"
CATEGORY_STEP = "category"
DIRECTION_STEP = "direction"
DATE_STEP = "date"
COMMENT_STEP = "comment"
CONFIRM_STEP = "confirm"
BRIEF_STEP = "brief"


def _button(text: str, callback_data: str, style: str | None = None) -> InlineKeyboardButton:
    data = {"text": text, "callback_data": callback_data}
    if style is not None:
        data["style"] = style
    return InlineKeyboardButton(**data)


def _cancel_button() -> list[InlineKeyboardButton]:
    return [_button("❌ Отмена", "manual:cancel", "danger")]


def _keyboard(
    rows: list[list[InlineKeyboardButton]],
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=rows + [_cancel_button()])


def _type_keyboard() -> InlineKeyboardMarkup:
    return _keyboard([
        [
            _button("💸 Расход", "manual:type:расход", "primary"),
            _button("💰 Доход", "manual:type:доход", "primary"),
        ],
        [_button("↔️ Перевод", "manual:type:перевод", "primary")],
    ])


def _category_keyboard(categories: tuple[str, ...]) -> InlineKeyboardMarkup:
    rows = [
        [_button(f"🧾 {category}", f"manual:category:{category}", "primary")]
        for category in categories
    ]
    return _keyboard(rows)


def _direction_keyboard() -> InlineKeyboardMarkup:
    return _keyboard([
        [
            _button("⬅️ Входящий", "manual:direction:in", "primary"),
            _button("➡️ Исходящий", "manual:direction:out", "primary"),
        ],
        [_button("🔁 Между своими", "manual:direction:self", "primary")],
    ])


def _date_keyboard() -> InlineKeyboardMarkup:
    return _keyboard([
        [
            _button("📅 Сегодня", "manual:date:today", "primary"),
            _button("◀️ Вчера", "manual:date:yesterday", "primary"),
        ],
        [_button("🗓 Другая дата", "manual:date:custom", "primary")],
    ])


def _optional_keyboard(field: str) -> InlineKeyboardMarkup:
    return _keyboard([
        [_button("⏭ Пропустить", f"manual:skip:{field}", "primary")],
    ])


def _confirm_keyboard() -> InlineKeyboardMarkup:
    return _keyboard([
        [_button("✅ Записать", "manual:confirm", "success")],
    ])


def parse_manual_brief(text: str, today: date) -> dict:
    """Извлекает только однозначные поля из текстового ручного брифа.

    Это намеренно не LLM-парсер: распознаются известные типы, категории,
    суммы и даты. Всё нераспознанное остаётся для кнопочного шага или
    комментария.
    """
    normalized = text.strip().lower().replace("ё", "е")
    draft: dict = {}

    type_aliases = {
        "расход": "расход", "трата": "расход", "доход": "доход",
        "перевод": "перевод",
    }
    for alias, type_ in type_aliases.items():
        if re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", normalized):
            draft["type"] = type_
            break

    date_match = re.search(
        r"(?<!\d)(?:20\d{2}-\d{1,2}-\d{1,2}|\d{1,2}[./]\d{1,2}(?:[./]\d{2,4})?)(?!\d)",
        normalized,
    )
    if date_match:
        candidate = parse_manual_date(date_match.group(), today)
        if candidate is not None:
            draft["op_date"] = candidate.isoformat()
    elif re.search(r"(?<!\w)сегодня(?!\w)", normalized):
        draft["op_date"] = today.isoformat()
    elif re.search(r"(?<!\w)вчера(?!\w)", normalized):
        draft["op_date"] = (today - timedelta(days=1)).isoformat()

    amount_source = normalized if date_match is None else (
        normalized[:date_match.start()] + normalized[date_match.end():]
    )
    amount_match = re.search(
        r"(?<![\d./-])\d[\d\s\u00a0]*(?:[.,]\d{1,2})?\s*(?:₽|р|руб(?:\.|лей|ля)?)?",
        amount_source,
        flags=re.IGNORECASE,
    )
    if amount_match:
        amount = parse_amount(amount_match.group())
        if amount is not None and amount > 0:
            draft["amount"] = str(amount)

    categories = EXPENSE_CATEGORIES + INCOME_CATEGORIES
    for category in sorted(categories, key=len, reverse=True):
        if category.lower().replace("ё", "е") in normalized:
            draft["category"] = category
            break

    direction_aliases = {
        "входящий": "in", "пришел": "in", "вернули": "in",
        "исходящий": "out", "отправил": "out",
        "между своими": "self", "себе": "self",
    }
    for alias, direction in direction_aliases.items():
        if alias in normalized:
            draft["transfer_direction"] = direction
            break

    if "карта" in normalized:
        draft["account"] = "карта"
    elif "наличные" in normalized or re.search(r"(?<!\w)нал(?!\w)", normalized):
        draft["account"] = "нал"

    comment_match = re.search(r"(?:комментарий|коммент|описание)\s*[:=-]\s*(.+)$", text, re.I)
    if comment_match:
        draft["comment"] = comment_match.group(1).strip()[:500] or None

    if draft.get("type") == "перевод":
        draft["category"] = None

    return draft


def _next_required_step(draft: dict) -> str | None:
    if not draft.get("type"):
        return TYPE_STEP
    if not draft.get("amount"):
        return AMOUNT_STEP
    if draft["type"] == "перевод":
        return DIRECTION_STEP if not draft.get("transfer_direction") else None
    if not draft.get("category"):
        return CATEGORY_STEP
    return DATE_STEP if not draft.get("op_date") else None


async def _prompt_missing(event: Message | CallbackQuery, user_id: int, draft: dict) -> None:
    draft = dict(draft)
    if draft.get("type") == "перевод":
        draft["category"] = None
    elif draft.get("type") == "расход" and draft.get("category") not in EXPENSE_CATEGORIES:
        draft.pop("category", None)
    elif draft.get("type") == "доход" and draft.get("category") not in INCOME_CATEGORIES:
        draft.pop("category", None)
    step = _next_required_step(draft)
    if step is None:
        await _show_confirmation(user_id, event, draft)
        return
    await _save(user_id, step, draft)
    prompts = {
        TYPE_STEP: ("1/4 · Выбери тип операции", _type_keyboard()),
        CATEGORY_STEP: ("2/4 · Выбери категорию", _category_keyboard(
            EXPENSE_CATEGORIES if draft.get("type") == "расход" else INCOME_CATEGORIES
        )),
        AMOUNT_STEP: ("2/4 · Введи сумму, например 1250,50", _keyboard([])),
        DIRECTION_STEP: ("2/4 · Выбери направление перевода", _direction_keyboard()),
        DATE_STEP: ("3/4 · Выбери дату операции", _date_keyboard()),
    }
    text, markup = prompts[step]
    if isinstance(event, CallbackQuery):
        await _edit_callback(event, text, markup)
    else:
        await event.answer(text, reply_markup=markup)


def parse_manual_date(value: str, today: date) -> date | None:
    """Разбирает только явные даты и относительные слова, без LLM."""
    normalized = value.strip().lower().replace("ё", "е")
    if normalized in {"сегодня", "today"}:
        return today
    if normalized in {"вчера", "yesterday"}:
        return today - timedelta(days=1)

    resolved = resolve_relative_date(normalized, today)
    if resolved is None or resolved > today:
        return None
    return resolved


def _user_id(message: Message | CallbackQuery) -> int | None:
    user = message.from_user
    return user.id if user is not None else None


async def _edit_callback(
    callback: CallbackQuery,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    message = callback.message
    if message is not None and hasattr(message, "edit_text"):
        await message.edit_text(text, reply_markup=reply_markup)


async def _session_for(
    event: Message | CallbackQuery,
) -> dict | None:
    user_id = _user_id(event)
    return await queries.get_manual_capture_session(user_id) if user_id else None


async def _save(user_id: int, step: str, draft: dict) -> None:
    await queries.save_manual_capture_session(user_id, step, draft)


async def _prompt_comment(message: Message) -> None:
    await message.answer(
        "Шаг 6/6. Добавь комментарий или нажми «Пропустить».",
        reply_markup=_optional_keyboard("comment"),
    )


def _confirmation_text(draft: dict) -> str:
    type_ = draft["type"]
    text = f"Проверь: {type_} {fmt_amount(Decimal(draft['amount']))}"
    if type_ != "перевод":
        text += f" · {draft['category']}"
    else:
        direction = {
            "in": "входящий",
            "out": "исходящий",
            "self": "между своими",
        }[draft["transfer_direction"]]
        text += f" · {direction}"
    text += f" · за {format_day_month(date.fromisoformat(draft['op_date']))}"
    if draft.get("comment"):
        text += f"\n{draft['comment']}"
    return text


async def _show_confirmation(user_id: int, event: Message | CallbackQuery, draft: dict) -> None:
    await _save(user_id, CONFIRM_STEP, draft)
    text = _confirmation_text(draft)
    if isinstance(event, CallbackQuery):
        await _edit_callback(event, text, _confirm_keyboard())
    else:
        await event.answer(text, reply_markup=_confirm_keyboard())


@router.message(Command("manual"))
async def cmd_manual(message: Message) -> None:
    user_id = _user_id(message)
    if user_id is None:
        return
    await _save(user_id, BRIEF_STEP, {})
    await message.answer(
        "🧾 Ручная запись без ИИ\n\n"
        "Напиши одной фразой всё, что знаешь. Например:\n"
        "«расход 850 Продукты сегодня, комментарий: ужин»\n"
        "или «перевод 5000 себе вчера»\n\n"
        "Понятные поля возьму из текста, для пропущенного покажу кнопки.",
        reply_markup=_keyboard([]),
    )


@router.message(Command("cancel"))
@router.message(Command("отмена"))
async def cmd_cancel(message: Message) -> None:
    user_id = _user_id(message)
    if user_id is None:
        return
    existed = await queries.get_manual_capture_session(user_id)
    await queries.delete_manual_capture_session(user_id)
    await message.answer(
        "Ручной ввод отменён." if existed else "Активного ручного ввода нет."
    )


@router.callback_query(F.data == "manual:cancel")
async def on_cancel(callback: CallbackQuery) -> None:
    user_id = _user_id(callback)
    if user_id is not None:
        await queries.delete_manual_capture_session(user_id)
    await _edit_callback(callback, "Ручной ввод отменён.")
    await callback.answer("Отменено")


@router.callback_query(F.data.startswith("manual:type:"))
async def on_type(callback: CallbackQuery) -> None:
    session = await _session_for(callback)
    user_id = _user_id(callback)
    type_ = (callback.data or "").split(":", 2)[-1]
    if not session or user_id is None or session["step"] != TYPE_STEP:
        await callback.answer("Сценарий устарел", show_alert=True)
        return
    if type_ not in OPERATION_TYPES:
        await callback.answer("Неизвестный тип", show_alert=True)
        return

    draft = {**session["draft"], "type": type_}
    await _prompt_missing(callback, user_id, draft)
    await callback.answer()


@router.callback_query(F.data.startswith("manual:category:"))
async def on_category(callback: CallbackQuery) -> None:
    session = await _session_for(callback)
    user_id = _user_id(callback)
    category = (callback.data or "").split(":", 2)[-1]
    if not session or user_id is None or session["step"] != CATEGORY_STEP:
        await callback.answer("Сценарий устарел", show_alert=True)
        return
    categories = (
        EXPENSE_CATEGORIES
        if session["draft"].get("type") == "расход"
        else INCOME_CATEGORIES
    )
    if category not in categories:
        await callback.answer("Неизвестная категория", show_alert=True)
        return
    draft = {**session["draft"], "category": category}
    await _prompt_missing(callback, user_id, draft)
    await callback.answer()


@router.callback_query(F.data.startswith("manual:direction:"))
async def on_direction(callback: CallbackQuery) -> None:
    session = await _session_for(callback)
    user_id = _user_id(callback)
    direction = (callback.data or "").split(":", 2)[-1]
    if not session or user_id is None or session["step"] != DIRECTION_STEP:
        await callback.answer("Сценарий устарел", show_alert=True)
        return
    if direction not in {"in", "out", "self"}:
        await callback.answer("Неизвестное направление", show_alert=True)
        return
    draft = {**session["draft"], "transfer_direction": direction}
    await _prompt_missing(callback, user_id, draft)
    await callback.answer()


@router.callback_query(F.data.startswith("manual:date:"))
async def on_date(callback: CallbackQuery) -> None:
    session = await _session_for(callback)
    user_id = _user_id(callback)
    choice = (callback.data or "").split(":", 2)[-1]
    if not session or user_id is None or session["step"] != DATE_STEP:
        await callback.answer("Сценарий устарел", show_alert=True)
        return
    if choice == "custom":
        await _edit_callback(callback, "Шаг 5/6. Введи дату в формате YYYY-MM-DD или DD.MM.YYYY.", _keyboard([]))
        await callback.answer()
        return

    today = effective_today()
    op_date = today if choice == "today" else today - timedelta(days=1)
    if choice not in {"today", "yesterday"}:
        await callback.answer("Неизвестная дата", show_alert=True)
        return
    draft = {**session["draft"], "op_date": op_date.isoformat()}
    await _show_confirmation(user_id, callback, draft)
    await callback.answer()


async def _prompt_comment_for_event(
    event: Message | CallbackQuery,
    user_id: int,
    draft: dict,
) -> None:
    await _save(user_id, COMMENT_STEP, draft)
    text = "Шаг 6/6. Добавь комментарий или нажми «Пропустить»."
    if isinstance(event, CallbackQuery):
        await _edit_callback(event, text, _optional_keyboard("comment"))
    else:
        await event.answer(text, reply_markup=_optional_keyboard("comment"))


@router.callback_query(F.data.startswith("manual:skip:"))
async def on_skip(callback: CallbackQuery) -> None:
    session = await _session_for(callback)
    user_id = _user_id(callback)
    field = (callback.data or "").split(":", 2)[-1]
    if not session or user_id is None or session["step"] != field:
        await callback.answer("Сценарий устарел", show_alert=True)
        return
    draft = {**session["draft"], field: None}
    if field == COMMENT_STEP:
        await _show_confirmation(user_id, callback, draft)
    else:
        await _show_confirmation(user_id, callback, draft)
    await callback.answer()


@router.callback_query(F.data == "manual:confirm")
async def on_confirm(callback: CallbackQuery) -> None:
    session = await _session_for(callback)
    user_id = _user_id(callback)
    if not session or user_id is None or session["step"] != CONFIRM_STEP:
        await callback.answer("Сценарий устарел", show_alert=True)
        return

    draft = session["draft"]
    try:
        operation, duplicate_id = await operation_service.create_operation(
            op_date=date.fromisoformat(draft["op_date"]),
            type_=draft["type"],
            amount=Decimal(draft["amount"]),
            category=draft.get("category"),
            comment=draft.get("comment"),
            account=None,
            transfer_direction=draft.get("transfer_direction"),
            source="бот-ручной",
            check_duplicate=True,
        )
    except (ValueError, TypeError) as exc:
        await callback.answer("Не удалось записать операцию", show_alert=True)
        if callback.message is not None and hasattr(callback.message, "answer"):
            await callback.message.answer(f"Ошибка ручного ввода: {exc}")
        return

    await queries.delete_manual_capture_session(user_id)
    if operation["type"] == "расход":
        await budget_service.notify_after_new_expense(
            getattr(callback, "bot", None), operation["op_date"]
        )
    text = f"✅ Записал: {operation['type']} {fmt_amount(operation['amount'])}"
    if operation.get("category"):
        text += f" · {operation['category']}"
    if duplicate_id is not None:
        text += "\n❗Похоже на дубль — проверь историю."
    await _edit_callback(callback, text)
    await callback.answer("Записано")


async def handle_text(message: Message) -> bool:
    """Обрабатывает текст только при активной ручной сессии."""
    user_id = _user_id(message)
    if user_id is None or not message.text:
        return False
    session = await queries.get_manual_capture_session(user_id)
    if session is None:
        return False

    step = session["step"]
    draft = dict(session["draft"])
    text = message.text.strip()
    if step == BRIEF_STEP:
        parsed = parse_manual_brief(text, effective_today())
        await _prompt_missing(message, user_id, {**draft, **parsed})
        return True
    if step == AMOUNT_STEP:
        parsed = parse_amount(text)
        try:
            amount = schemas.money(str(parsed)) if parsed is not None and parsed.is_finite() else None
        except schemas.ValidationError:
            amount = None
        if amount is None:
            await message.answer("Не понял сумму. Введи положительное число, например 1250,50.")
            return True
        draft["amount"] = str(amount)
        await _prompt_missing(message, user_id, draft)
        return True

    if step == DATE_STEP:
        op_date = parse_manual_date(text, effective_today())
        if op_date is None:
            await message.answer("Не понял дату. Используй сегодня, вчера или YYYY-MM-DD.")
            return True
        draft["op_date"] = op_date.isoformat()
        await _show_confirmation(user_id, message, draft)
        return True

    if step == COMMENT_STEP:
        max_length = 500
        if len(text) > max_length:
            await message.answer(f"Текст слишком длинный: максимум {max_length} символов.")
            return True
        draft[step] = text or None
        await _show_confirmation(user_id, message, draft)
        return True

    await message.answer("Продолжи ручной ввод кнопкой из последнего сообщения или используй /cancel.")
    return True
