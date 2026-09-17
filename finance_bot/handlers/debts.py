"""Кредитные и личные долги поверх обычного текстового захвата."""

from aiogram import F, Router
from aiogram.types import (CallbackQuery, InlineKeyboardButton,
                           InlineKeyboardMarkup, Message)

from finance_bot.core.dashboard import fmt_amount
from finance_bot.core.dates import (resolve_relative_date,
                                    split_explicit_date_prefix)
from finance_bot.core.debts import match_records, may_contain_debt_intent
from finance_bot.core.parsing import validate_operation_date
from finance_bot.database import queries
from finance_bot.services import budget as budget_service
from finance_bot.services import llm

router = Router()


def _credit_keyboard(operation_id: int, debts: list[dict]) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(
        text=_credit_label(row)[:48], callback_data=f"crd:{operation_id}:{row['id']}"
    )] for row in debts[:8]]
    rows.append([InlineKeyboardButton(
        text="Не долг", callback_data=f"crn:{operation_id}"
    )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _credit_label(row: dict) -> str:
    title = row.get("loan_name") or row["creditor"]
    if row.get("loan_name") and row.get("creditor"):
        title = f"{title} · {row['creditor']}"
    if row.get("contract_ref"):
        title = f"{title} · {row['contract_ref']}"
    return title


def _match_credits(query: str | None, records: list[dict]) -> list[dict]:
    if not query:
        return records
    matches = match_records(query, records, "creditor")
    for row in match_records(query, records, "loan_name"):
        if row not in matches:
            matches.append(row)
    return matches


def _personal_keyboard(operation_id: int, debts: list[dict]) -> InlineKeyboardMarkup:
    direction = {"owed_to_me": "мне должны", "i_owe": "я должен"}
    rows = [[InlineKeyboardButton(
        text=f"{row['person']} · {direction[row['direction']]}"[:48],
        callback_data=f"prd:{operation_id}:{row['id']}",
    )] for row in debts[:8]]
    rows.append([InlineKeyboardButton(
        text="Не долг", callback_data=f"prn:{operation_id}"
    )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _insert_operation(intent: dict, *, type_: str, category: str | None,
                            comment: str, needs_review: bool,
                            transfer_direction: str | None = None) -> int:
    return await queries.insert_operation(
        op_date=intent["date"], type_=type_, amount=intent["amount"],
        category=category, comment=comment, account=None, source="бот-долг",
        needs_review=needs_review,
        transfer_direction=transfer_direction,
    )


async def _reply_and_link(message: Message, operation_id: int, text: str,
                          markup: InlineKeyboardMarkup | None = None) -> None:
    sent = await message.reply(text, reply_markup=markup)
    await queries.set_tg_message_id(operation_id, sent.message_id)


def _resolve_intent_date(intent: dict, text: str, today) -> None:
    explicit_date, _ = split_explicit_date_prefix(text, today)
    resolved = explicit_date or resolve_relative_date(text, today)
    if resolved is not None:
        intent["date"], date_review = validate_operation_date(resolved, today)
        intent["needs_review"] = intent["needs_review"] or date_review


async def _credit_payment(message: Message, intent: dict) -> None:
    if intent["amount"] is None or intent["amount"] <= 0:
        await message.reply("⚠️ Не нашёл сумму платежа по кредиту. Уточни её текстом.")
        return
    creditor = intent["creditor"] or "кредит"
    comment = intent["comment"] or f"Платёж по кредиту {creditor}"
    active = await queries.list_debts("active")
    matches = _match_credits(intent["creditor"], active)
    exact = len(matches) == 1
    operation_id = await _insert_operation(
        intent, type_="расход", category="Долги", comment=comment,
        needs_review=intent["needs_review"] or not exact,
    )
    await budget_service.notify_after_new_expense(
        getattr(message, "bot", None), intent["date"]
    )

    if exact:
        debt = await queries.record_debt_payment(
            matches[0]["id"], operation_id, intent["date"], intent["amount"]
        )
        if debt is None:
            await _reply_and_link(
                message, operation_id,
                "⚠️ Расход записан, но кредит не удалось обновить. Проверь TMA.",
            )
            return
        text = (
            f"✅ Записал: расход {fmt_amount(intent['amount'])} · Долги\n"
            f"{_credit_label(debt)}: остаток тела не изменён — "
            "разбивка платежа неизвестна. Уточни остаток в TMA."
        )
        await _reply_and_link(message, operation_id, text)
        return

    candidates = matches or active
    prompt = "Не нашёл активный кредит." if not candidates else "Выбери кредит для платежа:"
    await _reply_and_link(
        message,
        operation_id,
        f"✅ Расход {fmt_amount(intent['amount'])} записан в «Долги».\n{prompt}",
        _credit_keyboard(operation_id, candidates),
    )


async def _personal_new(message: Message, intent: dict) -> None:
    if intent["amount"] is None or intent["amount"] <= 0 \
            or not intent["person"] \
            or intent["direction"] not in {"owed_to_me", "i_owe"}:
        await message.reply(
            "⚠️ Не разобрал личный долг. Укажи имя, сумму и кто кому должен."
        )
        return
    direction_text = "мне должны" if intent["direction"] == "owed_to_me" \
        else "я должен"
    comment = intent["comment"] or f"Личный долг: {intent['person']}"
    operation_id = await _insert_operation(
        intent, type_="перевод", category=None, comment=comment,
        needs_review=intent["needs_review"],
        transfer_direction="out" if intent["direction"] == "owed_to_me" else "in",
    )
    await queries.insert_personal_debt(
        person=intent["person"], direction=intent["direction"],
        principal=intent["amount"], opened_at=intent["date"],
        due_date=intent["due_date"], comment=comment, operation_id=operation_id,
    )
    await _reply_and_link(
        message,
        operation_id,
        f"✅ Записал личный долг: {intent['person']} · {direction_text} · "
        f"{fmt_amount(intent['amount'])}",
    )


async def _personal_repay(message: Message, intent: dict) -> None:
    if intent["amount"] is None or intent["amount"] <= 0:
        await message.reply("⚠️ Не нашёл сумму возврата долга. Уточни её текстом.")
        return
    active = await queries.list_personal_debts("open")
    if intent["direction"] in {"owed_to_me", "i_owe"}:
        active = [row for row in active if row["direction"] == intent["direction"]]
    matches = match_records(intent["person"], active, "person")
    exact = len(matches) == 1
    comment = intent["comment"] or f"Возврат долга: {intent['person'] or 'без имени'}"
    operation_id = await _insert_operation(
        intent, type_="перевод", category=None, comment=comment,
        needs_review=intent["needs_review"] or not exact,
        transfer_direction=(
            "in" if intent.get("direction") == "owed_to_me" else "out"
        ),
    )
    if exact:
        debt = await queries.record_personal_debt_payment(
            matches[0]["id"], operation_id, intent["date"], intent["amount"]
        )
        if debt is None:
            await _reply_and_link(
                message, operation_id,
                "⚠️ Перевод записан, но личный долг не удалось обновить.",
            )
            return
        text = (
            f"✅ Записал возврат: {fmt_amount(intent['amount'])}\n"
            f"{debt['person']}: осталось {fmt_amount(debt['balance'])}"
        )
        if debt["status"] == "closed":
            text += "\n🎉 Личный долг закрыт."
        await _reply_and_link(message, operation_id, text)
        return

    candidates = matches or active
    prompt = "Не нашёл открытый личный долг." if not candidates \
        else "Выбери личный долг:"
    await _reply_and_link(
        message,
        operation_id,
        f"✅ Перевод {fmt_amount(intent['amount'])} записан.\n{prompt}",
        _personal_keyboard(operation_id, candidates),
    )


async def try_handle_debt_message(message: Message, today) -> bool:
    """Возвращает True, только если сообщение распознано как долговое."""
    text = message.text or ""
    if not may_contain_debt_intent(text):
        return False
    intent = await llm.extract_debt_intent(text, today)
    if intent["intent"] == "expense":
        return False
    _resolve_intent_date(intent, text, today)
    if intent["intent"] == "debt_payment":
        await _credit_payment(message, intent)
    elif intent["intent"] == "personal_debt_new":
        await _personal_new(message, intent)
    else:
        await _personal_repay(message, intent)
    return True


@router.callback_query(F.data.startswith("crd:"))
async def choose_credit(callback: CallbackQuery) -> None:
    _, operation_text, debt_text = callback.data.split(":")
    operation = await queries.get_operation(int(operation_text))
    if operation is None:
        await callback.answer("Операция не найдена", show_alert=True)
        return
    debt = await queries.record_debt_payment(
        int(debt_text), operation["id"], operation["op_date"], operation["amount"]
    )
    if debt is None:
        await callback.answer("Кредит не найден", show_alert=True)
        return
    await queries.confirm_operation(operation["id"])
    await callback.message.edit_text(
        f"✅ Платёж привязан к «{_credit_label(debt)}».\n"
        "Остаток тела не изменён: часть платежа, ушедшая в тело, "
        "не указана. Уточни его в TMA."
    )
    await callback.answer()


@router.callback_query(F.data.startswith("crn:"))
async def credit_is_not_debt(callback: CallbackQuery) -> None:
    operation_id = int(callback.data.split(":")[1])
    operation = await queries.patch_operation(operation_id, {"category": "Прочее"})
    if operation is None:
        await callback.answer("Операция не найдена", show_alert=True)
        return
    await callback.message.edit_text("✅ Оставил обычным расходом · Прочее.")
    await callback.answer()


@router.callback_query(F.data.startswith("prd:"))
async def choose_personal_debt(callback: CallbackQuery) -> None:
    _, operation_text, debt_text = callback.data.split(":")
    operation = await queries.get_operation(int(operation_text))
    if operation is None:
        await callback.answer("Операция не найдена", show_alert=True)
        return
    debt = await queries.record_personal_debt_payment(
        int(debt_text), operation["id"], operation["op_date"], operation["amount"]
    )
    if debt is None:
        await callback.answer("Личный долг не найден", show_alert=True)
        return
    await queries.confirm_operation(operation["id"])
    suffix = "\n🎉 Долг закрыт." if debt["status"] == "closed" else ""
    await callback.message.edit_text(
        f"✅ Возврат привязан к долгу «{debt['person']}».\n"
        f"Осталось {fmt_amount(debt['balance'])}{suffix}"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("prn:"))
async def personal_is_not_debt(callback: CallbackQuery) -> None:
    operation_id = int(callback.data.split(":")[1])
    operation = await queries.confirm_operation(operation_id)
    if operation is None:
        await callback.answer("Операция не найдена", show_alert=True)
        return
    await callback.message.edit_text("✅ Оставил обычным переводом.")
    await callback.answer()
