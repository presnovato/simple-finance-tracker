"""Захват операций: текст / PDF-чек / фото. Ядро frictionless capture."""

import logging
from datetime import datetime, timedelta, timezone

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import (CallbackQuery, InlineKeyboardButton,
                           InlineKeyboardMarkup, Message)
from aiogram.utils.chat_action import ChatActionSender

from finance_bot.core.dashboard import fmt_amount
from finance_bot.core.dates import (effective_today, format_day_month,
                                    resolve_relative_date,
                                    split_explicit_date_prefix)
from finance_bot.core.parsing import parse_quick_amount, validate_operation_date
from finance_bot.core.subscriptions import (
    format_subscription_amount,
    next_charge_after,
)
from finance_bot.database import queries
from finance_bot.handlers import debts
from finance_bot.handlers import manual
from finance_bot.services import budget as budget_service
from finance_bot.services import llm
from finance_bot.webapp import web_app_markup

logger = logging.getLogger(__name__)

router = Router()

MAX_SCREENSHOT_OPERATIONS = 20
# Bot API не отдаёт getFile для файлов больше 20 МБ.
MAX_TELEGRAM_FILE_BYTES = 20 * 1024 * 1024
OPENROUTER_ALERT_SETTING = "openrouter_alert_at"
OPENROUTER_ALERT_INTERVAL = timedelta(hours=6)
LLM_UNAVAILABLE_TEXT = (
    "ИИ сейчас недоступен ({reason}). Сохранил черновик — ответь на это "
    "сообщение суммой/категорией или используй /manual."
)
_awaiting_many_shot = False


def is_many_caption(caption: str | None) -> bool:
    normalized = (caption or "").strip().lower().replace("ё", "е")
    return "список" in normalized or "за день" in normalized


async def _alert_openrouter_once(message: Message, error: llm.LLMUnavailable) -> None:
    """Одно предупреждение о 401/402 за 6 часов, без спама."""
    now = datetime.now(timezone.utc)
    last_raw = await queries.get_setting(OPENROUTER_ALERT_SETTING)
    if last_raw:
        try:
            last_at = datetime.fromisoformat(last_raw)
        except ValueError:
            last_at = None
        if last_at is not None and now - last_at < OPENROUTER_ALERT_INTERVAL:
            return
    await queries.set_setting(
        OPENROUTER_ALERT_SETTING, now.replace(microsecond=0).isoformat()
    )
    await message.answer("OpenRouter: ключ недействителен / закончились кредиты.")


async def handle_llm_unavailable(
    message: Message, error: llm.LLMUnavailable, *, source: str
) -> None:
    """Недоступность ИИ: черновик в pending_captures и понятный ответ."""
    draft = dict(llm.FALLBACK, date=effective_today())
    sent = await message.reply(LLM_UNAVAILABLE_TEXT.format(reason=error.reason))
    await queries.create_pending_capture(
        tg_message_id=sent.message_id,
        source=source,
        draft=draft,
        context=message.text or message.caption,
    )
    if error.status in (401, 402):
        await _alert_openrouter_once(message, error)


def confirmation_text(op: dict, duplicate: bool = False) -> str:
    amount = fmt_amount(op["amount"])
    if op["type"] == "перевод" and op.get("transfer_direction") == "in":
        amount = f"+{amount}"
    parts = [f"✅ Записал: {op['type']} {amount}"]
    if op["type"] != "перевод" and op["category"]:
        parts[0] += f" · {op['category']}"
    if op.get("date") and op["date"] != effective_today():
        parts[0] += f" · за {format_day_month(op['date'])}"
    if op.get("comment"):
        parts.append(op["comment"])
    if op.get("needs_review"):
        parts.append("⚠️ Не уверен в разборе — проверь (reply, если что не так).")
    if duplicate:
        parts.append("❗Похоже на дубль — сегодня уже есть операция "
                     "с такой суммой.")
    return "\n".join(parts)


async def save_and_confirm(
    message: Message,
    parsed: dict,
    source: str,
    *,
    check_duplicate: bool = True,
    context: str | None = None,
    source_item_index: int = 0,
    suspected_duplicate: bool = False,
    source_chat_id: int | None = None,
    source_message_id: int | None = None,
) -> int | None:
    if parsed.get("intent") == "subscription":
        await save_subscription_and_confirm(message, parsed)
        return None
    if parsed["amount"] is None or parsed["amount"] <= 0:
        amount = fmt_amount(parsed["amount"]) if parsed["amount"] else "?"
        sent = await message.reply(
            "⚠️ Не разобрал уверенно — допиши вручную.\n"
            f"Понял так: {amount} / {parsed['type'] or '?'}"
        )
        await queries.create_pending_capture(
            tg_message_id=sent.message_id,
            source=source,
            draft=parsed,
            context=context or message.text or message.caption,
        )
        return None

    # тип вне трёх допустимых → записываем как расход с флагом уточнения
    type_ = parsed["type"] if parsed["type"] in ("расход", "доход", "перевод") \
        else "расход"
    transfer_direction = None
    if type_ == "перевод":
        transfer_direction = parsed.get("transfer_direction") or "out"

    duplicate = suspected_duplicate
    if check_duplicate:
        duplicate = await queries.find_possible_duplicates(
            parsed["date"], parsed["amount"], type_, parsed["category"]
        ) is not None

    chat_id = source_chat_id if source_chat_id is not None else message.chat.id
    message_id = (
        source_message_id
        if source_message_id is not None
        else message.message_id
    )
    op_id, replayed = await queries.insert_operation_once(
        op_date=parsed["date"], type_=type_, amount=parsed["amount"],
        category=parsed["category"], comment=parsed["comment"],
        account=parsed["account"], source=source,
        needs_review=parsed["needs_review"],
        transfer_direction=transfer_direction,
        source_chat_id=chat_id,
        source_message_id=message_id,
        source_item_index=source_item_index,
    )
    if replayed:
        # Апдейт доставлен повторно: операция уже записана. Молчим, чтобы не
        # отправить подтверждение дважды и не задвоить уведомления бюджета.
        logger.info("Повтор апдейта: операция %s уже записана", op_id)
        return op_id

    op = dict(parsed, type=type_, transfer_direction=transfer_direction)
    markup = None
    if duplicate:
        markup = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="❌ Это дубль, удалить",
                                 callback_data=f"del:{op_id}")
        ]])
    sent = await message.reply(
        confirmation_text(op, duplicate=duplicate),
        reply_markup=markup,
    )
    await queries.set_tg_message_id(op_id, sent.message_id)
    if type_ == "расход":
        await budget_service.notify_after_new_expense(
            getattr(message, "bot", None), parsed["date"]
        )
    return op_id


async def save_subscription_and_confirm(message: Message, parsed: dict) -> None:
    amount = parsed.get("amount")
    title = parsed.get("title")
    if amount is None or amount <= 0 or not title:
        await message.reply("⚠️ Не разобрал подписку — укажи сервис и сумму.")
        return

    period = parsed.get("period") if parsed.get("period") in {"monthly", "yearly"} \
        else "monthly"
    next_charge = parsed.get("next_charge")
    if next_charge is None:
        next_charge = next_charge_after(effective_today(), period)
    subscription = await queries.insert_subscription(
        title=title,
        amount=amount,
        period=period,
        next_charge=next_charge,
        category="Подписки",
        comment=parsed.get("comment"),
    )
    period_label = "/год" if period == "yearly" else "/мес"
    text = (
        f"✅ Подписка: {title} — "
        f"{format_subscription_amount(amount)}{period_label}, "
        f"следующее списание {next_charge:%d.%m}"
    )
    if parsed.get("subscription_defaults"):
        text += "\n⚠️ Период и дату уточни во вкладке «Подписки»."
    rows = [[InlineKeyboardButton(
        text="❌ Удалить",
        callback_data=f"subdel:{subscription['id']}",
    )]]
    markup = InlineKeyboardMarkup(inline_keyboard=rows)
    web_markup = web_app_markup("Открыть подписки", tab="subs")
    if web_markup is not None:
        markup = InlineKeyboardMarkup(
            inline_keyboard=list(markup.inline_keyboard)
            + [list(row) for row in web_markup.inline_keyboard]
        )
    await message.reply(text, reply_markup=markup)


_pending_batches: dict[int, tuple[list[dict], int, int]] = {}


def _normalized_type(parsed: dict) -> str:
    return parsed["type"] if parsed["type"] in ("расход", "доход", "перевод") \
        else "расход"


async def _is_suspected(parsed: dict) -> bool:
    if parsed.get("amount") is None or parsed["amount"] <= 0:
        return False
    candidate = await queries.find_possible_duplicates(
        parsed["date"], parsed["amount"], _normalized_type(parsed),
        parsed["category"],
    )
    return candidate is not None


async def save_many_and_confirm(
    message: Message, parsed_items: list[dict], source: str
) -> None:
    if not parsed_items:
        await message.reply("⚠️ Не смог разобрать список операций.")
        return
    if len(parsed_items) > MAX_SCREENSHOT_OPERATIONS:
        await message.reply(
            f"⚠️ На скриншоте больше {MAX_SCREENSHOT_OPERATIONS} операций. "
            "Раздели список на несколько снимков."
        )
        return

    suspected = 0
    for parsed in parsed_items:
        if await _is_suspected(parsed):
            suspected += 1

    if suspected * 2 >= len(parsed_items):
        # Половина и больше похожи на дубли — спрашиваем один раз, не сохраняя.
        # Список держим в памяти до ответа: подтверждение живёт минуты.
        _pending_batches[message.message_id] = (
            parsed_items, message.chat.id, message.message_id
        )
        await message.reply(
            f"⚠️ {suspected} из {len(parsed_items)} операций похожи на уже "
            "записанные. Сохранить всё?",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(
                    text="Сохранить всё",
                    callback_data=f"many:save:{message.message_id}",
                ),
                InlineKeyboardButton(
                    text="Отмена",
                    callback_data=f"many:cancel:{message.message_id}",
                ),
            ]]),
        )
        return

    await message.reply(f"Разобрал {len(parsed_items)} операций.")
    for position, parsed in enumerate(parsed_items):
        await save_and_confirm(
            message, parsed, source, check_duplicate=False,
            source_item_index=position,
            suspected_duplicate=await _is_suspected(parsed),
        )


@router.callback_query(F.data.startswith("many:save:"))
async def on_many_save(callback: CallbackQuery) -> None:
    token = int(callback.data.split(":")[2])
    batch = _pending_batches.pop(token, None)
    if batch is None or callback.message is None:
        await callback.answer("Список уже обработан", show_alert=True)
        return
    parsed_items, chat_id, message_id = batch
    for position, parsed in enumerate(parsed_items):
        await save_and_confirm(
            callback.message, parsed, "бот-список", check_duplicate=False,
            source_item_index=position, suspected_duplicate=True,
            source_chat_id=chat_id, source_message_id=message_id,
        )
    await callback.answer("Сохранил")


@router.callback_query(F.data.startswith("many:cancel:"))
async def on_many_cancel(callback: CallbackQuery) -> None:
    token = int(callback.data.split(":")[2])
    _pending_batches.pop(token, None)
    if callback.message is not None:
        await callback.message.edit_text("Отменил — ничего не записал.")
    await callback.answer()


@router.callback_query(F.data.startswith("del:"))
async def on_delete(callback: CallbackQuery) -> None:
    op_id = int(callback.data.split(":")[1])
    await queries.delete_operation(op_id)
    await callback.message.edit_text("🗑 Удалил.")
    await callback.answer()


@router.message(Command("список"))
async def cmd_many_shot(message: Message) -> None:
    if not llm.is_available():
        await message.answer(
            "ИИ-захват не настроен. Для ручного ввода используй /manual."
        )
        return
    global _awaiting_many_shot
    _awaiting_many_shot = True
    await message.answer(
        "Пришли следующим сообщением скриншот — разберу все траты за день."
    )


def _consume_many_mode(caption: str | None) -> bool:
    global _awaiting_many_shot
    if is_many_caption(caption):
        _awaiting_many_shot = False
        return True
    if _awaiting_many_shot:
        _awaiting_many_shot = False
        return True
    return False


_pending_files: dict[int, dict] = {}


async def _confirm_repeat_file(
    message: Message, file_unique_id: str | None, payload: dict
) -> bool:
    """True, если файл уже присылали и мы ждём подтверждения «Записать»."""
    if not file_unique_id:
        return False
    known = await queries.get_capture_file(file_unique_id)
    if known is None:
        return False
    first_seen = str(known.get("first_seen_at") or "")[:10]
    _pending_files[message.message_id] = payload
    await message.reply(
        f"Этот чек/скриншот уже присылали {first_seen}. Записать ещё раз?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(
                text="Записать",
                callback_data=f"file:save:{message.message_id}",
            ),
            InlineKeyboardButton(
                text="Не нужно",
                callback_data=f"file:skip:{message.message_id}",
            ),
        ]]),
    )
    return True


async def _process_file(
    message: Message,
    bot: Bot,
    data: bytes,
    mime: str,
    filename: str | None,
    many: bool,
    source: str,
    *,
    source_chat_id: int | None = None,
    source_message_id: int | None = None,
) -> None:
    action = (
        ChatActionSender.upload_document
        if mime == "application/pdf"
        else ChatActionSender.upload_photo
    )
    try:
        async with action(bot=bot, chat_id=message.chat.id):
            if mime == "application/pdf":
                if many:
                    parsed_items = await llm.extract_many_from_pdf(
                        data, filename or "operations.pdf", effective_today()
                    )
                else:
                    parsed = await llm.extract_from_pdf(
                        data, filename or "receipt.pdf", effective_today()
                    )
            else:
                if many:
                    parsed_items = await llm.extract_many_from_image(
                        data, mime, effective_today()
                    )
                else:
                    parsed = await llm.extract_from_image(
                        data, mime, effective_today()
                    )
    except llm.LLMUnavailable as error:
        await handle_llm_unavailable(message, error, source=source)
        return
    if many:
        await save_many_and_confirm(message, parsed_items, source)
    else:
        await save_and_confirm(
            message, parsed, source,
            source_chat_id=source_chat_id,
            source_message_id=source_message_id,
        )


@router.message(F.photo)
async def on_photo(message: Message, bot: Bot) -> None:
    if not llm.is_available():
        await message.reply(
            "Для разбора чека нужен OPENROUTER_API_KEY. "
            "Для ручного ввода используй /manual."
        )
        return
    photo = message.photo[-1]
    if photo.file_size and photo.file_size > MAX_TELEGRAM_FILE_BYTES:
        await message.reply(
            "⚠️ Файл больше 20 МБ — Telegram не отдаёт такие файлы боту. "
            "Пришли чек меньшего размера."
        )
        return
    many = _consume_many_mode(message.caption)
    source = "бот-список" if many else "бот-чек"
    repeat = await _confirm_repeat_file(message, photo.file_unique_id, {
        "file_id": photo.file_id,
        "mime": "image/jpeg",
        "filename": None,
        "many": many,
        "source": source,
    })
    if repeat:
        return
    file = await bot.download(photo)
    await _process_file(message, bot, file.read(), "image/jpeg", None, many, source)
    await queries.remember_capture_file(photo.file_unique_id)


@router.message(F.document)
async def on_document(message: Message, bot: Bot) -> None:
    if not llm.is_available():
        await message.reply(
            "Для разбора чека нужен OPENROUTER_API_KEY. "
            "Для ручного ввода используй /manual."
        )
        return
    doc = message.document
    mime = doc.mime_type or ""
    if mime != "application/pdf" and not mime.startswith("image/"):
        await message.reply("⚠️ Принимаю только PDF-чеки и картинки.")
        return
    if doc.file_size and doc.file_size > MAX_TELEGRAM_FILE_BYTES:
        await message.reply(
            "⚠️ Файл больше 20 МБ — Telegram не отдаёт такие файлы боту. "
            "Пришли чек меньшего размера."
        )
        return
    many = _consume_many_mode(message.caption)
    source = "бот-список" if many else "бот-чек"
    repeat = await _confirm_repeat_file(message, doc.file_unique_id, {
        "file_id": doc.file_id,
        "mime": mime,
        "filename": doc.file_name,
        "many": many,
        "source": source,
    })
    if repeat:
        return
    file = await bot.download(doc)
    await _process_file(
        message, bot, file.read(), mime, doc.file_name, many, source
    )
    await queries.remember_capture_file(doc.file_unique_id)


@router.callback_query(F.data.startswith("file:save:"))
async def on_file_save(callback: CallbackQuery) -> None:
    token = int(callback.data.split(":")[2])
    payload = _pending_files.pop(token, None)
    if payload is None or callback.message is None:
        await callback.answer("Уже обработано", show_alert=True)
        return
    bot = callback.bot
    file = await bot.download(payload["file_id"])
    await _process_file(
        callback.message, bot, file.read(), payload["mime"],
        payload.get("filename"), payload["many"], payload["source"],
        source_chat_id=callback.message.chat.id,
        source_message_id=token,
    )
    await callback.answer("Записал")


@router.callback_query(F.data.startswith("file:skip:"))
async def on_file_skip(callback: CallbackQuery) -> None:
    token = int(callback.data.split(":")[2])
    _pending_files.pop(token, None)
    if callback.message is not None:
        await callback.message.edit_text("Хорошо, повторно не записываю.")
    await callback.answer()


@router.message(F.text)
async def on_text(message: Message) -> None:
    if await manual.handle_text(message):
        return
    today = effective_today()
    quick_amount = parse_quick_amount(message.text)
    if quick_amount is not None:
        await save_and_confirm(
            message,
            {
                "intent": "operation",
                "date": today,
                "type": "расход",
                "amount": quick_amount,
                "category": "Прочее",
                "comment": None,
                "account": None,
                "transfer_direction": None,
                "needs_review": True,
            },
            source="бот-быстрый-ввод",
        )
        return
    if not llm.is_available():
        await message.reply(
            "ИИ-захват не настроен. Для пошагового ввода без ИИ используй /manual."
        )
        return
    if await debts.try_handle_debt_message(message, today):
        return
    explicit_date, text_for_llm = split_explicit_date_prefix(message.text, today)
    try:
        parsed = await llm.extract_from_text(text_for_llm or message.text, today)
    except llm.LLMUnavailable as error:
        await handle_llm_unavailable(message, error, source="бот-текст")
        return
    if parsed.get("intent") == "subscription":
        if explicit_date is not None:
            parsed["next_charge"] = explicit_date
        await save_subscription_and_confirm(message, parsed)
        return
    resolved_date = explicit_date or resolve_relative_date(message.text, today)
    if resolved_date is not None:
        parsed["date"], date_needs_review = validate_operation_date(
            resolved_date, today
        )
        parsed["needs_review"] = parsed["needs_review"] or date_needs_review
    await save_and_confirm(message, parsed, source="бот-текст")
