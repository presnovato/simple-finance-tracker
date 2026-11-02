"""Команда /backup: выдача сохранённых ежедневных копий по запросу."""

from __future__ import annotations

from datetime import date

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import FSInputFile, Message

from finance_bot.core.dates import TZ, effective_today, resolve_relative_date
from finance_bot.services import backup as backup_service

router = Router()

HELP_TEXT = (
    "Что умеет /backup:\n"
    "• /backup — копия за сегодня;\n"
    "• /backup вчера — за вчера; можно /backup 22.09 "
    "или /backup 2026-09-22;\n"
    "• /backup список — все сохранённые копии;\n"
    "• /backup сейчас — создать свежую копию прямо сейчас."
)

NO_BACKUPS_TEXT = "Бэкапов пока нет. Создать сейчас: /backup сейчас"


def _format_date(value: date) -> str:
    return f"{value:%d.%m.%Y}"


def _format_short(value: date) -> str:
    return f"{value:%d.%m}"


def _select_backup(
    backups: list[backup_service.StoredBackup], requested: date
) -> tuple[backup_service.StoredBackup | None, bool]:
    """Выбирает копию за дату или ближайшую к ней (сначала более раннюю)."""
    for stored in backups:
        if stored.date == requested:
            return stored, False
    earlier = [stored for stored in backups if stored.date < requested]
    if earlier:
        return max(earlier, key=lambda stored: stored.date), True
    later = [stored for stored in backups if stored.date > requested]
    if later:
        return min(later, key=lambda stored: stored.date), True
    return None, False


def _caption(
    stored: backup_service.StoredBackup, requested: date, *, nearest: bool
) -> str:
    created_local = stored.created_at.astimezone(TZ)
    lines = []
    if nearest:
        lines.append(
            f"За {_format_short(requested)} бэкапа нет — отправляю ближайший: "
            f"{_format_short(stored.date)}."
        )
    lines.append(f"💾 Бэкап за {_format_date(stored.date)}")
    lines.append(f"Создан: {created_local:%d.%m.%Y %H:%M} ({TZ.zone})")
    lines.append(f"Размер: {backup_service.format_size(stored.size_bytes)}")
    lines.append(f"Операций: {stored.operations_count}")
    lines.append(f"sha256: {stored.sha256[:12]}…")
    return "\n".join(lines)


async def _send_backup(
    message: Message,
    stored: backup_service.StoredBackup,
    requested: date,
    *,
    nearest: bool,
) -> None:
    if stored.size_bytes > backup_service.MAX_UPLOAD_BYTES:
        await message.answer(
            f"⚠️ Бэкап за {_format_date(stored.date)} весит "
            f"{backup_service.format_size(stored.size_bytes)} — это больше лимита "
            "Telegram 45 МБ, файлом не отправить. Забери его с Volume вручную."
        )
        return
    await message.answer_document(
        FSInputFile(stored.archive_path, filename=stored.archive_path.name),
        caption=_caption(stored, requested, nearest=nearest),
    )


async def _send_for_date(message: Message, requested: date) -> None:
    stored, nearest = _select_backup(backup_service.list_backups(), requested)
    if stored is None:
        await message.answer(NO_BACKUPS_TEXT)
        return
    await _send_backup(message, stored, requested, nearest=nearest)


async def _send_list(message: Message) -> None:
    backups = backup_service.list_backups()
    if not backups:
        await message.answer(NO_BACKUPS_TEXT)
        return
    lines = ["📦 Сохранённые бэкапы (новые сверху):"]
    for stored in backups:
        lines.append(
            f"• {_format_date(stored.date)} — "
            f"{backup_service.format_size(stored.size_bytes)}, "
            f"операций {stored.operations_count}"
        )
    await message.answer("\n".join(lines))


@router.message(Command("backup"))
async def cmd_backup(message: Message, command: CommandObject) -> None:
    argument = (command.args or "").strip()
    normalized = argument.lower().replace("ё", "е")

    if not argument:
        await _send_for_date(message, effective_today())
        return
    if normalized == "список":
        await _send_list(message)
        return
    if normalized == "сейчас":
        stored = await backup_service.store_daily_backup(message.bot)
        if stored is not None:
            await _send_backup(
                message, stored, stored.date, nearest=False
            )
        return

    requested = resolve_relative_date(argument, effective_today())
    if requested is None:
        await message.answer(HELP_TEXT)
        return
    await _send_for_date(message, requested)
