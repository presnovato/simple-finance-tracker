import asyncio
import logging
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

import aiosqlite

from finance_bot.config import DB_PATH, DB_REQUIRE_PERSISTENT_DIR
from finance_bot.database.migrations import (
    _prune_pre_migration_snapshots as _prune_pre_migration_snapshots,
)
from finance_bot.database.migrations import _run_migrations
from finance_bot.database.schema import BASE_SCHEMA as BASE_SCHEMA
from finance_bot.database.schema import SCHEMA as SCHEMA

logger = logging.getLogger(__name__)


def _icontains(value: object, query: object) -> int:
    if value is None or query is None:
        return 0
    return int(str(query).casefold() in str(value).casefold())


class SQLiteAdapter:
    def __init__(self, connection: aiosqlite.Connection) -> None:
        self._connection = connection
        self._lock = asyncio.Lock()
        self._transaction_owner: asyncio.Task | None = None

    def _owns_transaction(self) -> bool:
        return self._transaction_owner is asyncio.current_task()

    @asynccontextmanager
    async def _access(self) -> AsyncIterator[None]:
        if self._owns_transaction():
            yield
            return
        async with self._lock:
            yield

    async def fetch(self, sql: str, *args: object) -> list[dict]:
        async with self._access():
            try:
                cursor = await self._connection.execute(sql, args)
                try:
                    rows = await cursor.fetchall()
                finally:
                    await cursor.close()
                if not self._owns_transaction():
                    await self._connection.commit()
            except BaseException:
                if not self._owns_transaction():
                    await self._connection.rollback()
                raise
        return [dict(row) for row in rows]

    async def fetchrow(self, sql: str, *args: object) -> dict | None:
        async with self._access():
            try:
                cursor = await self._connection.execute(sql, args)
                try:
                    row = await cursor.fetchone()
                finally:
                    await cursor.close()
                if not self._owns_transaction():
                    await self._connection.commit()
            except BaseException:
                if not self._owns_transaction():
                    await self._connection.rollback()
                raise
        return dict(row) if row is not None else None

    async def execute(self, sql: str, *args: object) -> None:
        async with self._access():
            try:
                cursor = await self._connection.execute(sql, args)
                await cursor.close()
                if not self._owns_transaction():
                    await self._connection.commit()
            except BaseException:
                if not self._owns_transaction():
                    await self._connection.rollback()
                raise

    async def backup_to(self, destination: Path) -> None:
        """Создаёт согласованную копию SQLite, включая WAL-состояние."""
        async with self._lock:
            target = sqlite3.connect(destination)
            try:
                await self._connection.backup(target)
                integrity = target.execute("PRAGMA integrity_check").fetchone()
                if integrity != ("ok",):
                    detail = integrity[0] if integrity else "пустой результат"
                    raise RuntimeError(
                        f"Проверка резервной копии SQLite не пройдена: {detail}"
                    )
            finally:
                target.close()

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator["SQLiteAdapter"]:
        yield self

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator["SQLiteAdapter"]:
        if self._owns_transaction():
            raise RuntimeError("Вложенные транзакции SQLite не поддерживаются")
        async with self._lock:
            self._transaction_owner = asyncio.current_task()
            try:
                await self._connection.execute("BEGIN IMMEDIATE")
                yield self
            except BaseException:
                await self._connection.rollback()
                raise
            else:
                await self._connection.commit()
            finally:
                self._transaction_owner = None

    async def close(self) -> None:
        async with self._lock:
            await self._connection.close()


_pool: SQLiteAdapter | None = None

# True, если текущий init_pool() создал файл базы с нуля (Volume не найден,
# путь сменился и т.п.). Используется для предупреждения владельцу в main.py.
created_fresh: bool = False

async def init_pool() -> SQLiteAdapter:
    global _pool, created_fresh

    if sqlite3.sqlite_version_info < (3, 35):
        version = sqlite3.sqlite_version
        raise RuntimeError(
            f"Требуется SQLite >= 3.35, установлена версия {version}"
        )

    db_path = Path(DB_PATH).expanduser().resolve()
    parent = db_path.parent
    if DB_REQUIRE_PERSISTENT_DIR and not parent.is_dir():
        raise RuntimeError(
            f"Каталог {parent} не найден — не подключён Railway Volume; "
            "данные были бы потеряны при редеплое"
        )

    existed = db_path.is_file()
    size = db_path.stat().st_size if existed else 0
    created_fresh = not existed
    connection = await aiosqlite.connect(db_path)
    try:
        connection.row_factory = aiosqlite.Row
        await connection.execute("PRAGMA journal_mode = WAL")
        await connection.execute("PRAGMA synchronous = NORMAL")
        await connection.execute("PRAGMA foreign_keys = ON")
        await connection.execute("PRAGMA busy_timeout = 5000")
        await connection.create_function(
            "icontains", 2, _icontains, deterministic=True
        )
        await connection.executescript(BASE_SCHEMA)
        await _run_migrations(
            connection, db_path, had_data=existed and size > 0
        )
        await connection.commit()
    except BaseException:
        await connection.close()
        raise

    _pool = SQLiteAdapter(connection)
    state = "существовал" if existed else "создан заново"
    logger.info(
        "База инициализирована: path=%s, файл %s, размер до старта=%d байт",
        db_path,
        state,
        size,
    )
    return _pool


def get_pool() -> SQLiteAdapter:
    if _pool is None:
        raise RuntimeError("Соединение БД не инициализировано — вызови init_pool()")
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
