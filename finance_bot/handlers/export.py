"""Экспорт операций и согласованной копии SQLite через inline-меню."""

from datetime import timedelta
from pathlib import Path
from tempfile import NamedTemporaryFile

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from finance_bot.core.dates import effective_today
from finance_bot.database import connection, queries
from finance_bot.services.export import generate_csv, generate_md
from finance_bot.services.weekly_sync import build_finance_snapshot

router = Router()

PERIODS = {
    "1": ("1д", 1),
    "7": ("7 дн", 7),
    "30": ("30 дн", 30),
    "all": ("♾️", None),
}
FORMATS = {"csv": ".csv", "md": ".md"}


def _menu(period: str = "30", fmt: str = "csv") -> InlineKeyboardMarkup:
    period_row = [
        InlineKeyboardButton(
            text=f"{'✅ ' if key == period else ''}{label}",
            callback_data=f"export:pick:{key}:{fmt}",
        )
        for key, (label, _) in PERIODS.items()
    ]
    format_row = [
        InlineKeyboardButton(
            text=f"{'✅ ' if key == fmt else ''}{extension}",
            callback_data=f"export:format:{period}:{key}",
        )
        for key, extension in FORMATS.items()
    ]
    return InlineKeyboardMarkup(inline_keyboard=[
        period_row,
        format_row,
        [InlineKeyboardButton(
            text="📥 Скачать",
            callback_data=f"export:run:{period}:{fmt}",
        )],
        [InlineKeyboardButton(
            text="💾 Выгрузить все данные (.db)",
            callback_data="export:db",
        )],
    ])


async def _show_menu(callback: CallbackQuery, period: str, fmt: str) -> None:
    if callback.message is not None:
        await callback.message.edit_text(
            "Выбери период и формат выгрузки:", reply_markup=_menu(period, fmt)
        )
    await callback.answer()


@router.message(Command("export"))
async def cmd_export(message: Message) -> None:
    await message.answer(
        "Выбери период и формат выгрузки:", reply_markup=_menu()
    )


@router.callback_query(F.data.startswith("export:pick:"))
async def pick_period(callback: CallbackQuery) -> None:
    try:
        _, _, period, fmt = callback.data.split(":")
        if period not in PERIODS or fmt not in FORMATS:
            raise ValueError
    except ValueError:
        await callback.answer("Некорректный период", show_alert=True)
        return
    await _show_menu(callback, period, fmt)


@router.callback_query(F.data.startswith("export:format:"))
async def pick_format(callback: CallbackQuery) -> None:
    try:
        _, _, period, fmt = callback.data.split(":")
        if period not in PERIODS or fmt not in FORMATS:
            raise ValueError
    except ValueError:
        await callback.answer("Некорректный формат", show_alert=True)
        return
    await _show_menu(callback, period, fmt)


def _period_bounds(period: str):
    label, days = PERIODS[period]
    today = effective_today()
    if days is None:
        return label, None, None
    return label, today - timedelta(days=days - 1), today


@router.callback_query(F.data.startswith("export:run:"))
async def run_export(callback: CallbackQuery) -> None:
    try:
        _, _, period, fmt = callback.data.split(":")
        label, start, end = _period_bounds(period)
        extension = FORMATS[fmt]
    except (KeyError, ValueError):
        await callback.answer("Некорректные параметры выгрузки", show_alert=True)
        return

    operations = await queries.operations_for_export(start, end)
    if fmt == "csv":
        content = generate_csv(operations)
    else:
        content = generate_md(operations, await build_finance_snapshot())
    suffix = f"{period}d" if period != "all" else "all"
    filename = f"finance_export_{suffix}{extension}"
    if callback.message is not None:
        await callback.message.answer_document(
            BufferedInputFile(content, filename=filename),
            caption=f"Экспорт операций: {label}, {len(operations)} шт.",
        )
    await callback.answer("Файл готов")


@router.callback_query(F.data == "export:db")
async def export_database(callback: CallbackQuery) -> None:
    if callback.message is None:
        await callback.answer("Сообщение недоступно", show_alert=True)
        return

    temp_path: Path | None = None
    try:
        with NamedTemporaryFile(
            prefix="finance_export_", suffix=".db", delete=False
        ) as handle:
            temp_path = Path(handle.name)
        await connection.get_pool().backup_to(temp_path)
        await callback.message.answer_document(
            FSInputFile(temp_path, filename="finance_backup.db"),
            caption="Согласованная копия базы Finance Tracker.",
        )
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
    await callback.answer("База выгружена")
