"""Ежедневный бэкап базы: тихое хранение на сервере и выдача по запросу.

Копия создаётся через SQLite backup API (``connection.SQLiteAdapter.backup_to``),
сжимается gzip и сохраняется в ``BACKUP_DIR`` под именем
``finance_backup_ГГГГ-ММ-ДД.db.gz``. Рядом лежит JSON-метаданные, чтобы команда
``/backup`` строила подпись, не распаковывая архив. На успех в чат ничего не
уходит; владелец получает файл только по запросу ``/backup``.

Архивы содержат всю финансовую историю, поэтому хранятся только 7 дней
(``BACKUP_RETENTION_DAYS``) и никогда не покидают каталог бэкапов сами по себе.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import logging
import os
import re
import shutil
import sqlite3
import tempfile
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from aiogram import Bot

from finance_bot.config import (
    ALLOWED_USER_ID,
    BACKUP_DIR,
    BACKUP_RETENTION_DAYS,
)
from finance_bot.core.dates import effective_today
from finance_bot.database import connection, queries

logger = logging.getLogger(__name__)

# Лимит Bot API на загрузку файла — 50 МБ; оставляем запас.
MAX_UPLOAD_BYTES = 45 * 1024 * 1024
# Запас свободного места поверх двух копий архива.
DISK_HEADROOM_BYTES = 50 * 1024 * 1024
# Осиротевшие .tmp-файлы старше этого возраста можно удалять.
TMP_MAX_AGE_SECONDS = 3600

LAST_AT_SETTING = "backup_last_at"

_ARCHIVE_RE = re.compile(r"finance_backup_(\d{4}-\d{2}-\d{2})\.db\.gz")
_METADATA_RE = re.compile(r"finance_backup_(\d{4}-\d{2}-\d{2})\.json")


class InsufficientDiskSpace(RuntimeError):
    """Свободного места меньше, чем нужно для ещё одной копии."""


@dataclass
class BackupArchive:
    """Готовая к отправке сжатая копия базы."""

    path: Path
    size_bytes: int
    sha256: str
    operations_count: int
    created_at: datetime


@dataclass
class StoredBackup:
    """Архив, сохранённый в ``BACKUP_DIR``."""

    date: date
    archive_path: Path
    size_bytes: int
    sha256: str
    operations_count: int
    created_at: datetime


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_iso(moment: datetime | None = None) -> str:
    return (moment or _utc_now()).replace(microsecond=0).isoformat()


def format_size(size: int) -> str:
    if size >= 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} МБ"
    if size >= 1024:
        return f"{size / 1024:.1f} КБ"
    return f"{size} Б"


def _normalise_copy(db_path: Path) -> None:
    """Убирает служебные ключи автобэкапа из копии и уплотняет её.

    Значения ``backup_*`` в settings меняются при каждом запуске; без очистки
    они попадали бы в архив и мешали сравнивать копии между собой.
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


def backup_path(day: date) -> Path:
    return Path(BACKUP_DIR) / f"finance_backup_{day.isoformat()}.db.gz"


def metadata_path(day: date) -> Path:
    return Path(BACKUP_DIR) / f"finance_backup_{day.isoformat()}.json"


def _free_disk_bytes() -> int:
    return shutil.disk_usage(BACKUP_DIR).free


def _ensure_disk_space(archive: BackupArchive) -> None:
    required = 2 * archive.size_bytes + DISK_HEADROOM_BYTES
    free = _free_disk_bytes()
    if free < required:
        raise InsufficientDiskSpace(
            f"свободно {format_size(free)}, нужно минимум {format_size(required)}"
        )


def store_archive(archive: BackupArchive, day: date) -> StoredBackup:
    """Атомарно кладёт архив и метаданные в ``BACKUP_DIR``."""
    directory = Path(BACKUP_DIR)
    directory.mkdir(parents=True, exist_ok=True)
    _ensure_disk_space(archive)

    final = backup_path(day)
    tmp = final.with_name(final.name + ".tmp")
    tmp.write_bytes(archive.path.read_bytes())
    os.replace(tmp, final)

    metadata = metadata_path(day)
    metadata_tmp = metadata.with_name(metadata.name + ".tmp")
    metadata_tmp.write_text(
        json.dumps(
            {
                "created_at": _utc_iso(archive.created_at),
                "size_bytes": archive.size_bytes,
                "sha256": archive.sha256,
                "operations_count": archive.operations_count,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    os.replace(metadata_tmp, metadata)

    return StoredBackup(
        date=day,
        archive_path=final,
        size_bytes=archive.size_bytes,
        sha256=archive.sha256,
        operations_count=archive.operations_count,
        created_at=archive.created_at,
    )


def _parse_created_at(value: object) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _load_metadata(day: date) -> dict | None:
    metadata = metadata_path(day)
    if not metadata.is_file():
        return None
    try:
        return json.loads(metadata.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def list_backups() -> list[StoredBackup]:
    """Возвращает сохранённые архивы, новые сверху."""
    directory = Path(BACKUP_DIR)
    if not directory.is_dir():
        return []

    backups: list[StoredBackup] = []
    for path in directory.iterdir():
        match = _ARCHIVE_RE.fullmatch(path.name)
        if not match:
            continue
        day = date.fromisoformat(match.group(1))
        metadata = _load_metadata(day) or {}
        created_at = _parse_created_at(metadata.get("created_at"))
        if created_at is None:
            created_at = datetime.fromtimestamp(
                path.stat().st_mtime, tz=timezone.utc
            )
        backups.append(
            StoredBackup(
                date=day,
                archive_path=path,
                size_bytes=int(metadata.get("size_bytes", path.stat().st_size)),
                sha256=str(metadata.get("sha256", "")),
                operations_count=int(metadata.get("operations_count", 0)),
                created_at=created_at,
            )
        )
    backups.sort(key=lambda backup: backup.date, reverse=True)
    return backups


def prune_old_backups() -> list[str]:
    """Удаляет архивы вне периода хранения и осиротевшие .tmp-файлы.

    Трогает только файлы строго нашего формата, поэтому снимки
    ``pre-migration-*`` и посторонние файлы остаются нетронутыми.
    """
    directory = Path(BACKUP_DIR)
    if not directory.is_dir():
        return []

    retention = max(1, BACKUP_RETENTION_DAYS)
    cutoff = effective_today() - timedelta(days=retention - 1)
    now = time.time()
    removed: list[str] = []

    for path in directory.iterdir():
        match = _ARCHIVE_RE.fullmatch(path.name) or _METADATA_RE.fullmatch(
            path.name
        )
        if match:
            if date.fromisoformat(match.group(1)) < cutoff:
                path.unlink(missing_ok=True)
                removed.append(path.name)
            continue
        if path.name.startswith("finance_backup_") and path.suffix == ".tmp":
            try:
                stale = now - path.stat().st_mtime > TMP_MAX_AGE_SECONDS
            except OSError:
                continue
            if stale:
                path.unlink(missing_ok=True)
                removed.append(path.name)

    if removed:
        logger.info("Удалены старые бэкапы: %s", ", ".join(sorted(removed)))
    return removed


async def _notify_failure(bot: Bot, error: Exception) -> None:
    """Сообщает об ошибке; сбой самого сообщения не должен ломать планировщик."""
    try:
        await bot.send_message(
            ALLOWED_USER_ID,
            f"⚠️ Автобэкап не удался: {type(error).__name__}",
        )
    except Exception:
        logger.exception("Не удалось сообщить об ошибке автобэкапа")


async def _notify_disk_space(bot: Bot) -> None:
    try:
        await bot.send_message(
            ALLOWED_USER_ID,
            "⚠️ Автобэкап не сохранён: на диске мало свободного места.",
        )
    except Exception:
        logger.exception("Не удалось сообщить о нехватке места для бэкапа")


async def store_daily_backup(bot: Bot) -> StoredBackup | None:
    """Создаёт и молча сохраняет бэкап за текущий финансовый день.

    Возвращает сохранённую копию или ``None`` при сбое или нехватке места.
    На успех никаких сообщений в чат не отправляет.
    """
    tmp_dir = Path(tempfile.mkdtemp(prefix="finance_backup_"))
    try:
        today = effective_today()
        try:
            archive = await create_backup_archive(tmp_dir)
        except Exception as error:
            logger.exception("Автобэкап не удался")
            await _notify_failure(bot, error)
            return None

        try:
            stored = store_archive(archive, today)
        except InsufficientDiskSpace as error:
            logger.error("Бэкап не сохранён: %s", error)
            await _notify_disk_space(bot)
            return None
        except Exception as error:
            logger.exception("Автобэкап не удался")
            await _notify_failure(bot, error)
            return None

        await queries.set_setting(LAST_AT_SETTING, _utc_iso())
        try:
            prune_old_backups()
        except Exception:
            logger.exception("Не удалось удалить старые бэкапы")

        logger.info(
            "Бэкап сохранён: %s, %d байт, операций %d",
            stored.archive_path.name,
            stored.size_bytes,
            stored.operations_count,
        )
        return stored
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
