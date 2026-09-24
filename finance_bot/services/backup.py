"""Ежедневный автобэкап базы в чат владельца.

Копия создаётся через SQLite backup API (``connection.SQLiteAdapter.backup_to``),
сжимается gzip и отправляется документом. Повторная отправка неизменной базы
пропускается по хешу содержимого.

Файлы бэкапа содержат всю финансовую историю, поэтому живут только во
временном каталоге вне репозитория и удаляются в ``finally``.
"""

from __future__ import annotations

import gzip
import hashlib
import logging
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from aiogram import Bot
from aiogram.types import FSInputFile

from finance_bot.config import ALLOWED_USER_ID
from finance_bot.core.dates import effective_today
from finance_bot.database import connection, queries

logger = logging.getLogger(__name__)

# Лимит Bot API на загрузку файла — 50 МБ; оставляем запас.
MAX_UPLOAD_BYTES = 45 * 1024 * 1024

SHA_SETTING = "backup_last_sha256"
LAST_AT_SETTING = "backup_last_at"
CHECKED_AT_SETTING = "backup_last_checked_at"


@dataclass
class BackupArchive:
    """Готовая к отправке сжатая копия базы."""

    path: Path
    size_bytes: int
    sha256: str
    operations_count: int
    created_at: datetime


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_iso(moment: datetime | None = None) -> str:
    return (moment or _utc_now()).replace(microsecond=0).isoformat()


def _format_size(size: int) -> str:
    if size >= 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} МБ"
    if size >= 1024:
        return f"{size / 1024:.1f} КБ"
    return f"{size} Б"


def _normalise_copy(db_path: Path) -> None:
    """Убирает служебные ключи автобэкапа из копии и уплотняет её.

    Иначе значения ``backup_*`` в settings менялись бы при каждом запуске,
    и хеш «неизменной» базы отличался бы, ломая пропуск повторной отправки.
    """
    copy = sqlite3.connect(db_path)
    try:
        copy.execute("DELETE FROM settings WHERE key GLOB 'backup_*'")
        copy.commit()
        copy.execute("VACUUM")
    finally:
        copy.close()


async def _count_active_operations() -> int:
    row = await connection.get_pool().fetchrow(
        "SELECT COUNT(*) AS total FROM operations WHERE deleted_at IS NULL"
    )
    return int(row["total"]) if row else 0


async def create_backup_archive(tmp_dir: Path) -> BackupArchive:
    """Создаёт проверенную сжатую копию базы во временном каталоге."""
    tmp_dir.mkdir(parents=True, exist_ok=True)
    db_copy = tmp_dir / "finance_backup.db"
    await connection.get_pool().backup_to(db_copy)
    _normalise_copy(db_copy)

    raw = db_copy.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()

    gz_path = db_copy.with_name(db_copy.name + ".gz")
    with gzip.open(gz_path, "wb") as handle:
        handle.write(raw)

    return BackupArchive(
        path=gz_path,
        size_bytes=gz_path.stat().st_size,
        sha256=digest,
        operations_count=await _count_active_operations(),
        created_at=_utc_now(),
    )


async def _notify_failure(bot: Bot, error: Exception) -> None:
    """Сообщает об ошибке; сбой самого сообщения не должен ломать планировщик."""
    try:
        await bot.send_message(
            ALLOWED_USER_ID,
            f"⚠️ Автобэкап не удался: {type(error).__name__}",
        )
    except Exception:
        logger.exception("Не удалось сообщить об ошибке автобэкапа")


async def _deliver(bot: Bot, tmp_dir: Path, *, force: bool) -> bool:
    archive = await create_backup_archive(tmp_dir)

    previous_sha = await queries.get_setting(SHA_SETTING)
    if not force and previous_sha == archive.sha256:
        await queries.set_setting(CHECKED_AT_SETTING, _utc_iso())
        await queries.set_setting(LAST_AT_SETTING, _utc_iso())
        logger.info("Автобэкап пропущен: база не изменилась с прошлого раза")
        return False

    if archive.size_bytes > MAX_UPLOAD_BYTES:
        logger.warning(
            "Автобэкап превышает лимит Telegram: %d байт", archive.size_bytes
        )
        await bot.send_message(
            ALLOWED_USER_ID,
            "⚠️ Автобэкап не отправлен: архив "
            f"{_format_size(archive.size_bytes)} больше лимита 45 МБ.",
        )
        await queries.set_setting(CHECKED_AT_SETTING, _utc_iso())
        return False

    today = effective_today()
    filename = f"finance_backup_{today.isoformat()}.db.gz"
    caption = (
        f"💾 Автобэкап за {today:%d.%m.%Y}\n"
        f"Размер: {_format_size(archive.size_bytes)}\n"
        f"Операций: {archive.operations_count}\n"
        f"sha256: {archive.sha256[:12]}…"
    )
    await bot.send_document(
        ALLOWED_USER_ID,
        FSInputFile(archive.path, filename=filename),
        caption=caption,
        disable_notification=True,
    )
    await queries.set_setting(SHA_SETTING, archive.sha256)
    await queries.set_setting(LAST_AT_SETTING, _utc_iso())
    await queries.set_setting(CHECKED_AT_SETTING, _utc_iso())
    logger.info(
        "Автобэкап отправлен: %s, %d байт, операций %d",
        filename,
        archive.size_bytes,
        archive.operations_count,
    )
    return True


async def send_daily_backup(bot: Bot, *, force: bool = False) -> bool:
    """Готовит и отправляет бэкап; возвращает, был ли отправлен файл."""
    tmp_dir = Path(tempfile.mkdtemp(prefix="finance_backup_"))
    try:
        try:
            return await _deliver(bot, tmp_dir, force=force)
        except Exception as error:
            logger.exception("Автобэкап не удался")
            await _notify_failure(bot, error)
            return False
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
