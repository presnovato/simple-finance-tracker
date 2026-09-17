"""Захват операций: текст / PDF-чек / фото. Ядро frictionless capture."""

import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import (CallbackQuery, InlineKeyboardButton,
                           InlineKeyboardMarkup, Message)

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
_awaiting_many_shot = False


def is_many_caption(caption: str | None) -> bool:
    normalized = (caption or "").strip().lower().replace("ё", "е")
    return "список" in normalized or "за день" in normalized


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
) -> None:
    if parsed.get("intent") == "subscription":
        await save_subscription_and_confirm(message, parsed)
        return
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
        return

    # тип вне трёх допустимых → записываем как расход с флагом уточнения
    type_ = parsed["type"] if parsed["type"] in ("расход", "доход", "перевод") \
        else "расход"
    transfer_direction = None
    if type_ == "перевод":
        transfer_direction = parsed.get("transfer_direction") or "out"

    duplicate_id = None
    if check_duplicate:
        duplicate_id = await queries.find_duplicate(
            parsed["date"], parsed["amount"], type_)

    op_id = await queries.insert_operation(
        op_date=parsed["date"], type_=type_, amount=parsed["amount"],
        category=parsed["category"], comment=parsed["comment"],
        account=parsed["account"], source=source,
        needs_review=parsed["needs_review"],
        transfer_direction=transfer_direction,
    )

    op = dict(parsed, type=type_, transfer_direction=transfer_direction)
    markup = None
    if duplicate_id is not None:
        markup = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="❌ Это дубль, удалить",
                                 callback_data=f"del:{op_id}")
        ]])
    sent = await message.reply(
        confirmation_text(op, duplicate=duplicate_id is not None),
        reply_markup=markup,
    )
    await queries.set_tg_message_id(op_id, sent.message_id)
    if type_ == "расход":
        await budget_service.notify_after_new_expense(
            getattr(message, "bot", None), parsed["date"]
        )


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

    await message.reply(f"Разобрал {len(parsed_items)} операций.")
    for parsed in parsed_items:
        await save_and_confirm(
            message, parsed, source, check_duplicate=False
        )


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


@router.message(F.photo)
async def on_photo(message: Message, bot: Bot) -> None:
    if not llm.is_available():
        await message.reply(
            "Для разбора чека нужен OPENROUTER_API_KEY. "
            "Для ручного ввода используй /manual."
        )
        return
    file = await bot.download(message.photo[-1])
    if _consume_many_mode(message.caption):
        parsed_items = await llm.extract_many_from_image(
            file.read(), "image/jpeg", effective_today()
        )
        await save_many_and_confirm(message, parsed_items, source="бот-список")
        return
    parsed = await llm.extract_from_image(
        file.read(), "image/jpeg", effective_today())
    await save_and_confirm(message, parsed, source="бот-чек")


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
    file = await bot.download(doc)
    data = file.read()
    if mime == "application/pdf":
        if _consume_many_mode(message.caption):
            parsed_items = await llm.extract_many_from_pdf(
                data, doc.file_name or "operations.pdf", effective_today()
            )
            await save_many_and_confirm(
                message, parsed_items, source="бот-список"
            )
            return
        parsed = await llm.extract_from_pdf(
            data, doc.file_name or "receipt.pdf", effective_today())
    else:
        if _consume_many_mode(message.caption):
            parsed_items = await llm.extract_many_from_image(
                data, mime, effective_today()
            )
            await save_many_and_confirm(
                message, parsed_items, source="бот-список"
            )
            return
        parsed = await llm.extract_from_image(data, mime, effective_today())
    await save_and_confirm(message, parsed, source="бот-чек")


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
    parsed = await llm.extract_from_text(text_for_llm or message.text, today)
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
