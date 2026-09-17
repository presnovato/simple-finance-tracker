"""Дашборд /dashboard: текст + emoji-бары, навигация инлайн-кнопками.

Текущий дашборд считает период от последнего обновления баланса. Месяцы
остаются отдельным режимом просмотра истории, если якорь задан.
Callback data: dash:p | dash:m:<offset> | dash:w | dash:d
"""

from datetime import timedelta

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import (CallbackQuery, InlineKeyboardButton,
                           InlineKeyboardMarkup, Message, WebAppInfo)

from finance_bot.config import TMA_URL
from finance_bot.core import dashboard as views
from finance_bot.core.dashboard import MONTHS_RU, fmt_amount
from finance_bot.core.dates import (effective_today, format_day_month,
                                     month_bounds, same_day_prev_month)
from finance_bot.core.subscriptions import monthly_cost
from finance_bot.database import queries
from finance_bot.services import balance as balance_service

router = Router()


def _keyboard(month_offset: int | None) -> InlineKeyboardMarkup:
    if month_offset is None:
        row = [
            InlineKeyboardButton(text="Период", callback_data="dash:p"),
            InlineKeyboardButton(text="Неделя", callback_data="dash:w"),
            InlineKeyboardButton(text="Сегодня", callback_data="dash:d"),
        ]
        rows = [row]
        if TMA_URL:
            rows.append([InlineKeyboardButton(
                text="📊 Открыть дашборд", web_app=WebAppInfo(url=TMA_URL)
            )])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    prev_start, _ = month_bounds(effective_today(), month_offset - 1)
    row = [
        InlineKeyboardButton(
            text=f"◀ {MONTHS_RU[prev_start.month - 1].capitalize()}",
            callback_data=f"dash:m:{month_offset - 1}",
        ),
        InlineKeyboardButton(text="Неделя", callback_data="dash:w"),
        InlineKeyboardButton(text="Сегодня", callback_data="dash:d"),
    ]
    if month_offset < 0:
        row.append(InlineKeyboardButton(
            text="▶", callback_data=f"dash:m:{month_offset + 1}"))
    rows = [row]
    if TMA_URL:
        rows.append([InlineKeyboardButton(
            text="📊 Открыть дашборд", web_app=WebAppInfo(url=TMA_URL)
        )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def render_month(offset: int) -> str:
    today = effective_today()
    start, end = month_bounds(today, offset)
    period_end = min(end, today) if offset == 0 else end
    title = f"📊 {MONTHS_RU[start.month - 1].capitalize()} {start.year}"

    cats = await queries.expenses_by_category(start, period_end)
    total = await queries.totals(start, period_end)
    parts = [title, "",
             f"Расходы: {fmt_amount(total['expense'])}",
             views.render_categories(cats)]
    active_subscriptions = await queries.list_subscriptions("active")
    if active_subscriptions:
        parts += ["", views.render_subscription_line(
            monthly_cost(active_subscriptions)
        )]

    if offset == 0:
        prev_start, _ = month_bounds(today, -1)
        prev = await queries.totals(prev_start, same_day_prev_month(today))
        comparison = views.render_comparison(total["expense"], prev["expense"])
        if comparison:
            parts += ["", comparison]

    parts += ["", views.render_balance(
        total["income"],
        total["expense"],
        total.get("transfer_in", 0),
        total.get("transfer_out", 0),
    )]
    return "\n".join(parts)


async def render_period(snapshot: dict) -> str:
    """Текущий цикл финансовых метрик от момента обновления баланса."""
    start = snapshot["anchor_date"]
    end = effective_today()
    start_ts = snapshot.get("anchor_ts")
    cats = await queries.expenses_by_category(start, end, start_ts=start_ts)
    total = await queries.totals(start, end, start_ts=start_ts)
    parts = [
        f"📊 Период: {format_day_month(start)} — {format_day_month(end)}",
        "",
        f"Расходы: {fmt_amount(total['expense'])}",
        views.render_categories(cats),
    ]
    active_subscriptions = await queries.list_subscriptions("active")
    if active_subscriptions:
        parts += ["", views.render_subscription_line(
            monthly_cost(active_subscriptions)
        )]
    parts += ["", views.render_balance(
        total["income"],
        total["expense"],
        total.get("transfer_in", 0),
        total.get("transfer_out", 0),
    )]
    return "\n".join(parts)


async def render_range(start, end, title: str) -> str:
    cats = await queries.expenses_by_category(start, end)
    total = await queries.totals(start, end)
    return "\n".join([title, "",
                      f"Расходы: {fmt_amount(total['expense'])}",
                      views.render_categories(cats)])


@router.message(Command("dashboard"))
async def cmd_dashboard(message: Message) -> None:
    snapshot = await balance_service.get_snapshot()
    if snapshot is None:
        text, markup = await render_month(0), _keyboard(0)
    else:
        text, markup = await render_period(snapshot), _keyboard(None)
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data.startswith("dash:"))
async def on_dash_nav(callback: CallbackQuery) -> None:
    parts = callback.data.split(":")
    today = effective_today()
    if parts[1] == "m":
        offset = int(parts[2])
        text, markup = await render_month(offset), _keyboard(offset)
    elif parts[1] == "p":
        snapshot = await balance_service.get_snapshot()
        if snapshot is None:
            text, markup = await render_month(0), _keyboard(0)
        else:
            text, markup = await render_period(snapshot), _keyboard(None)
    elif parts[1] == "w":
        text = await render_range(today - timedelta(days=6), today,
                                  "📊 Последние 7 дней")
        snapshot = await balance_service.get_snapshot()
        markup = _keyboard(None if snapshot is not None else 0)
    else:
        text = await render_range(today, today, "📊 Сегодня")
        snapshot = await balance_service.get_snapshot()
        markup = _keyboard(None if snapshot is not None else 0)
    if callback.message.text != text:
        await callback.message.edit_text(text, reply_markup=markup)
    await callback.answer()
