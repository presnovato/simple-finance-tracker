import asyncio
import logging
import re
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator

import aiosqlite

from finance_bot.config import DB_PATH, DB_REQUIRE_PERSISTENT_DIR

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS operations (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at    TEXT    NOT NULL
                DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00','now')),
  op_date       TEXT    NOT NULL,
  type          TEXT    NOT NULL
                CHECK (type IN ('расход','доход','перевод')),
  amount        INTEGER NOT NULL CHECK (amount >= 0),
  category      TEXT,
  comment       TEXT,
  note          TEXT,
  account       TEXT,
  transfer_direction TEXT CHECK (transfer_direction IN ('in','out','self')),
  source        TEXT,
  needs_review  INTEGER NOT NULL DEFAULT 0,
  tg_message_id INTEGER,
  subscription_id INTEGER REFERENCES subscriptions(id),
  source_chat_id    INTEGER,
  source_message_id INTEGER,
  source_item_index INTEGER,
  deleted_at    TEXT
);
CREATE INDEX IF NOT EXISTS idx_operations_op_date  ON operations (op_date);
CREATE INDEX IF NOT EXISTS idx_operations_category ON operations (category);
CREATE INDEX IF NOT EXISTS idx_operations_tg_msg   ON operations (tg_message_id);
CREATE INDEX IF NOT EXISTS idx_operations_active_date
  ON operations (op_date DESC, id DESC) WHERE deleted_at IS NULL;
-- NULL-значения в SQLite различны, поэтому ручные/TMA/старые записи не
-- конфликтуют между собой; уникальность действует только для источника.
CREATE UNIQUE INDEX IF NOT EXISTS idx_operations_source
  ON operations (source_chat_id, source_message_id, source_item_index);

-- Повторно присланные файлы (file_unique_id стабилен при пересылке).
CREATE TABLE IF NOT EXISTS capture_files (
  file_unique_id TEXT PRIMARY KEY,
  first_seen_at  TEXT NOT NULL
                 DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00','now')),
  operation_ids  TEXT
);

-- Идемпотентность POST /api/operations по заголовку Idempotency-Key.
CREATE TABLE IF NOT EXISTS api_idempotency (
  key           TEXT PRIMARY KEY,
  created_at    TEXT NOT NULL
                DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00','now')),
  status        INTEGER,
  response_json TEXT
);

-- Кредиты и рассрочки
CREATE TABLE IF NOT EXISTS debts (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  creditor    TEXT    NOT NULL,
  loan_name   TEXT,
  contract_ref TEXT,
  principal   INTEGER NOT NULL,
  balance     INTEGER NOT NULL,
  rate        INTEGER,
  min_payment INTEGER,
  next_payment_amount INTEGER,
  opened_at   TEXT,
  next_payment_date TEXT,
  payment_day INTEGER,
  priority    INTEGER,
  due_date    TEXT,
  status      TEXT    NOT NULL DEFAULT 'active',
  archived    INTEGER NOT NULL DEFAULT 0,
  created_at  TEXT    NOT NULL
              DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00','now'))
);

CREATE TABLE IF NOT EXISTS debt_payments (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  debt_id      INTEGER NOT NULL REFERENCES debts(id),
  operation_id INTEGER REFERENCES operations(id),
  pay_date     TEXT    NOT NULL,
  amount       INTEGER NOT NULL,
  principal_amount INTEGER,
  kind         TEXT    NOT NULL DEFAULT 'payment',
  payment_type TEXT    NOT NULL DEFAULT 'regular',
  cash_effect  TEXT    NOT NULL DEFAULT 'movement'
               CHECK (cash_effect IN ('movement','already_in_balance')),
  reason       TEXT,
  idempotency_key TEXT
);
CREATE INDEX IF NOT EXISTS idx_debt_payments_debt_id ON debt_payments (debt_id);

CREATE TABLE IF NOT EXISTS personal_debts (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  person       TEXT    NOT NULL,
  direction    TEXT    NOT NULL CHECK (direction IN ('owed_to_me','i_owe')),
  principal    INTEGER NOT NULL,
  balance      INTEGER NOT NULL,
  opened_at    TEXT    NOT NULL,
  due_date     TEXT,
  comment      TEXT,
  status       TEXT    NOT NULL DEFAULT 'open',
  operation_id INTEGER REFERENCES operations(id),
  archived     INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_personal_debts_status ON personal_debts (status);

CREATE TABLE IF NOT EXISTS personal_debt_payments (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  personal_debt_id INTEGER NOT NULL REFERENCES personal_debts(id),
  operation_id     INTEGER REFERENCES operations(id),
  pay_date         TEXT    NOT NULL,
  amount           INTEGER NOT NULL,
  cash_effect      TEXT    NOT NULL DEFAULT 'movement'
                   CHECK (cash_effect IN ('movement','already_in_balance')),
  idempotency_key  TEXT
);
CREATE INDEX IF NOT EXISTS idx_personal_debt_payments_debt_id
  ON personal_debt_payments (personal_debt_id);

-- Подписки — состояние регулярных списаний, а не поток операций.
CREATE TABLE IF NOT EXISTS subscriptions (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  title        TEXT    NOT NULL,
  amount       INTEGER NOT NULL CHECK (amount >= 0),
  period       TEXT    NOT NULL CHECK (period IN ('monthly','yearly')),
  next_charge  TEXT    NOT NULL,
  category     TEXT,
  comment      TEXT,
  status       TEXT    NOT NULL DEFAULT 'active'
               CHECK (status IN ('active','cancelled')),
  created_at   TEXT    NOT NULL
               DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00','now'))
);
CREATE INDEX IF NOT EXISTS idx_subscriptions_status_next_charge
  ON subscriptions (status, next_charge);

CREATE TABLE IF NOT EXISTS settings (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS schema_migrations (
  version    INTEGER PRIMARY KEY,
  name       TEXT NOT NULL,
  applied_at TEXT NOT NULL
             DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00','now'))
);

CREATE TABLE IF NOT EXISTS pending_captures (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  tg_message_id INTEGER NOT NULL UNIQUE,
  source        TEXT NOT NULL,
  context       TEXT,
  draft_json    TEXT NOT NULL,
  created_at    TEXT NOT NULL
                DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00','now'))
);

-- Устойчивые черновики пошагового ручного ввода операции.
CREATE TABLE IF NOT EXISTS manual_capture_sessions (
  tg_user_id INTEGER PRIMARY KEY,
  step       TEXT NOT NULL,
  draft_json TEXT NOT NULL,
  updated_at TEXT NOT NULL
             DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00','now'))
);

CREATE TABLE IF NOT EXISTS crypto_holdings (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  asset      TEXT NOT NULL UNIQUE,
  quantity   TEXT NOT NULL,
  updated_at TEXT NOT NULL
             DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00','now'))
);

CREATE TABLE IF NOT EXISTS crypto_transactions (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  asset          TEXT NOT NULL,
  quantity_delta TEXT NOT NULL,
  rub_amount     INTEGER NOT NULL CHECK (rub_amount >= 0),
  op_date        TEXT NOT NULL,
  operation_id   INTEGER REFERENCES operations(id),
  comment        TEXT
);
CREATE INDEX IF NOT EXISTS idx_crypto_transactions_date
  ON crypto_transactions (op_date DESC, id DESC);

-- Повторяющийся недельный бюджет и неизменяемые snapshot'ы завершённых недель.
CREATE TABLE IF NOT EXISTS weekly_budget_template (
  id           INTEGER PRIMARY KEY CHECK (id = 1),
  overall_limit INTEGER CHECK (overall_limit IS NULL OR overall_limit > 0),
  updated_at   TEXT NOT NULL
               DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00','now'))
);

CREATE TABLE IF NOT EXISTS weekly_budget_template_categories (
  category     TEXT PRIMARY KEY,
  weekly_limit INTEGER CHECK (weekly_limit IS NULL OR weekly_limit > 0)
);

CREATE TABLE IF NOT EXISTS weekly_budget_weeks (
  week_start   TEXT PRIMARY KEY,
  week_end     TEXT NOT NULL,
  overall_limit INTEGER CHECK (overall_limit IS NULL OR overall_limit > 0),
  created_at   TEXT NOT NULL
               DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00','now'))
);

CREATE TABLE IF NOT EXISTS weekly_budget_week_categories (
  week_start   TEXT NOT NULL REFERENCES weekly_budget_weeks(week_start)
               ON DELETE CASCADE,
  category     TEXT NOT NULL,
  weekly_limit INTEGER CHECK (weekly_limit IS NULL OR weekly_limit > 0),
  PRIMARY KEY (week_start, category)
);

CREATE TABLE IF NOT EXISTS weekly_budget_notifications (
  week_start TEXT NOT NULL REFERENCES weekly_budget_weeks(week_start)
             ON DELETE CASCADE,
  kind       TEXT NOT NULL CHECK (
               kind IN ('threshold_80', 'threshold_100', 'saving_1000')
             ),
  claimed_at TEXT NOT NULL
             DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00','now')),
  PRIMARY KEY (week_start, kind)
);
CREATE INDEX IF NOT EXISTS idx_weekly_budget_week_categories
  ON weekly_budget_week_categories (week_start);
CREATE INDEX IF NOT EXISTS idx_weekly_budget_weeks_start
  ON weekly_budget_weeks (week_start);
"""


def _without_indexes(schema: str) -> str:
    """Убирает индексы из базовой схемы для безопасного старта старых БД."""
    return re.sub(
        r"(?ms)^\s*CREATE\s+(?:UNIQUE\s+)?INDEX\s+IF\s+NOT\s+EXISTS\s+.*?;\s*",
        "\n",
        schema,
    )


# SCHEMA остаётся полной схемой для новых in-memory БД и внешних проверок.
# При старте приложения сначала создаются только таблицы, затем миграции и
# индексы. Так старая БД не падает на индексе, который ссылается на новую
# колонку, пока эта колонка ещё не добавлена.
BASE_SCHEMA = _without_indexes(SCHEMA)


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


async def _ensure_column(
    conn: aiosqlite.Connection, table: str, column: str, ddl: str
) -> None:
    cursor = await conn.execute(f"PRAGMA table_info({table})")
    try:
        names = {row[1] for row in await cursor.fetchall()}
    finally:
        await cursor.close()
    if column not in names:
        await conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


_LEGACY_COLUMNS = (
    ("operations", "transfer_direction", "transfer_direction TEXT"),
    (
        "operations",
        "subscription_id",
        "subscription_id INTEGER REFERENCES subscriptions(id)",
    ),
    ("debts", "archived", "archived INTEGER NOT NULL DEFAULT 0"),
    ("debts", "loan_name", "loan_name TEXT"),
    ("debts", "contract_ref", "contract_ref TEXT"),
    ("debts", "opened_at", "opened_at TEXT"),
    ("debts", "next_payment_amount", "next_payment_amount INTEGER"),
    ("debts", "next_payment_date", "next_payment_date TEXT"),
    ("debts", "payment_day", "payment_day INTEGER"),
    (
        "debt_payments",
        "idempotency_key",
        "idempotency_key TEXT",
    ),
    (
        "debt_payments",
        "payment_type",
        "payment_type TEXT NOT NULL DEFAULT 'regular'",
    ),
    ("debt_payments", "reason", "reason TEXT"),
    ("personal_debts", "archived", "archived INTEGER NOT NULL DEFAULT 0"),
    (
        "personal_debt_payments",
        "idempotency_key",
        "idempotency_key TEXT",
    ),
)

_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_operations_op_date "
    "ON operations (op_date)",
    "CREATE INDEX IF NOT EXISTS idx_operations_category "
    "ON operations (category)",
    "CREATE INDEX IF NOT EXISTS idx_operations_tg_msg "
    "ON operations (tg_message_id)",
    "CREATE INDEX IF NOT EXISTS idx_operations_active_date "
    "ON operations (op_date DESC, id DESC) WHERE deleted_at IS NULL",
    "CREATE INDEX IF NOT EXISTS idx_debt_payments_debt_id "
    "ON debt_payments (debt_id)",
    "CREATE INDEX IF NOT EXISTS idx_personal_debts_status "
    "ON personal_debts (status)",
    "CREATE INDEX IF NOT EXISTS idx_personal_debt_payments_debt_id "
    "ON personal_debt_payments (personal_debt_id)",
    "CREATE INDEX IF NOT EXISTS idx_subscriptions_status_next_charge "
    "ON subscriptions (status, next_charge)",
    "CREATE INDEX IF NOT EXISTS idx_crypto_transactions_date "
    "ON crypto_transactions (op_date DESC, id DESC)",
    "CREATE INDEX IF NOT EXISTS idx_operations_subscription_id "
    "ON operations (subscription_id)",
    "CREATE INDEX IF NOT EXISTS idx_debts_archived ON debts (archived)",
    "CREATE INDEX IF NOT EXISTS idx_personal_debts_archived "
    "ON personal_debts (archived)",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_debt_payments_idempotency "
    "ON debt_payments (idempotency_key) WHERE idempotency_key IS NOT NULL",
    "CREATE UNIQUE INDEX IF NOT EXISTS "
    "idx_personal_debt_payments_idempotency "
    "ON personal_debt_payments (idempotency_key) "
    "WHERE idempotency_key IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS idx_weekly_budget_week_categories "
    "ON weekly_budget_week_categories (week_start)",
    "CREATE INDEX IF NOT EXISTS idx_weekly_budget_weeks_start "
    "ON weekly_budget_weeks (week_start)",
)


async def _migrate_legacy_columns(conn: aiosqlite.Connection) -> None:
    for table, column, ddl in _LEGACY_COLUMNS:
        await _ensure_column(conn, table, column, ddl)


async def _migrate_indexes(conn: aiosqlite.Connection) -> None:
    for statement in _INDEXES:
        await conn.execute(statement)


async def _migrate_pending_captures(conn: aiosqlite.Connection) -> None:
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS pending_captures (
          id            INTEGER PRIMARY KEY AUTOINCREMENT,
          tg_message_id INTEGER NOT NULL UNIQUE,
          source        TEXT NOT NULL,
          context       TEXT,
          draft_json    TEXT NOT NULL,
          created_at    TEXT NOT NULL
                      DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00','now'))
        )
        """
    )


async def _migrate_manual_capture_sessions(conn: aiosqlite.Connection) -> None:
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS manual_capture_sessions (
          tg_user_id INTEGER PRIMARY KEY,
          step       TEXT NOT NULL,
          draft_json TEXT NOT NULL,
          updated_at TEXT NOT NULL
                     DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00','now'))
        )
        """
    )


async def _migrate_payment_cash_effect(conn: aiosqlite.Connection) -> None:
    for table in ("debt_payments", "personal_debt_payments"):
        await _ensure_column(
            conn,
            table,
            "cash_effect",
            "cash_effect TEXT NOT NULL DEFAULT 'movement'",
        )


async def _migrate_debt_payment_principal_amount(
    conn: aiosqlite.Connection,
) -> None:
    await _ensure_column(
        conn,
        "debt_payments",
        "principal_amount",
        "principal_amount INTEGER",
    )


async def _migrate_weekly_budget(conn: aiosqlite.Connection) -> None:
    statements = (
        """
        CREATE TABLE IF NOT EXISTS weekly_budget_template (
          id            INTEGER PRIMARY KEY CHECK (id = 1),
          overall_limit INTEGER CHECK (overall_limit IS NULL OR overall_limit > 0),
          updated_at    TEXT NOT NULL
                        DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00','now'))
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS weekly_budget_template_categories (
          category      TEXT PRIMARY KEY,
          weekly_limit  INTEGER CHECK (weekly_limit IS NULL OR weekly_limit > 0)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS weekly_budget_weeks (
          week_start    TEXT PRIMARY KEY,
          week_end      TEXT NOT NULL,
          overall_limit INTEGER CHECK (overall_limit IS NULL OR overall_limit > 0),
          created_at    TEXT NOT NULL
                        DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00','now'))
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS weekly_budget_week_categories (
          week_start    TEXT NOT NULL REFERENCES weekly_budget_weeks(week_start)
                        ON DELETE CASCADE,
          category      TEXT NOT NULL,
          weekly_limit  INTEGER CHECK (weekly_limit IS NULL OR weekly_limit > 0),
          PRIMARY KEY (week_start, category)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS weekly_budget_notifications (
          week_start TEXT NOT NULL REFERENCES weekly_budget_weeks(week_start)
                     ON DELETE CASCADE,
          kind       TEXT NOT NULL CHECK (
                       kind IN ('threshold_80', 'threshold_100', 'saving_1000')
                     ),
          claimed_at TEXT NOT NULL
                     DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00','now')),
          PRIMARY KEY (week_start, kind)
        )
        """,
    )
    for statement in statements:
        await conn.execute(statement)
    for statement in _INDEXES[-2:]:
        await conn.execute(statement)


async def _migrate_nullable_weekly_budget_limits(
    conn: aiosqlite.Connection,
) -> None:
    """Разрешает выбранным категориям обходиться без отдельного лимита."""
    await conn.execute(
        "ALTER TABLE weekly_budget_template_categories "
        "RENAME TO weekly_budget_template_categories_legacy"
    )
    await conn.execute(
        """
        CREATE TABLE weekly_budget_template_categories (
          category      TEXT PRIMARY KEY,
          weekly_limit  INTEGER CHECK (weekly_limit IS NULL OR weekly_limit > 0)
        )
        """
    )
    await conn.execute(
        """
        INSERT INTO weekly_budget_template_categories (category, weekly_limit)
        SELECT category, weekly_limit
        FROM weekly_budget_template_categories_legacy
        """
    )
    await conn.execute("DROP TABLE weekly_budget_template_categories_legacy")

    await conn.execute(
        "ALTER TABLE weekly_budget_week_categories "
        "RENAME TO weekly_budget_week_categories_legacy"
    )
    await conn.execute(
        """
        CREATE TABLE weekly_budget_week_categories (
          week_start    TEXT NOT NULL REFERENCES weekly_budget_weeks(week_start)
                        ON DELETE CASCADE,
          category      TEXT NOT NULL,
          weekly_limit  INTEGER CHECK (weekly_limit IS NULL OR weekly_limit > 0),
          PRIMARY KEY (week_start, category)
        )
        """
    )
    await conn.execute(
        """
        INSERT INTO weekly_budget_week_categories
          (week_start, category, weekly_limit)
        SELECT week_start, category, weekly_limit
        FROM weekly_budget_week_categories_legacy
        """
    )
    await conn.execute("DROP TABLE weekly_budget_week_categories_legacy")
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_weekly_budget_week_categories "
        "ON weekly_budget_week_categories (week_start)"
    )


async def _migrate_source_idempotency(conn: aiosqlite.Connection) -> None:
    """Идемпотентность источника: колонки, уникальный индекс и новые таблицы."""
    for column, ddl in (
        ("source_chat_id", "source_chat_id INTEGER"),
        ("source_message_id", "source_message_id INTEGER"),
        ("source_item_index", "source_item_index INTEGER"),
    ):
        await _ensure_column(conn, "operations", column, ddl)
    await conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_operations_source "
        "ON operations (source_chat_id, source_message_id, source_item_index)"
    )
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS capture_files (
          file_unique_id TEXT PRIMARY KEY,
          first_seen_at  TEXT NOT NULL
                         DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00','now')),
          operation_ids  TEXT
        )
        """
    )
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS api_idempotency (
          key           TEXT PRIMARY KEY,
          created_at    TEXT NOT NULL
                        DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00','now')),
          status        INTEGER,
          response_json TEXT
        )
        """
    )


_MIGRATIONS = (
    (1, "legacy_columns", _migrate_legacy_columns),
    (2, "indexes_after_columns", _migrate_indexes),
    (3, "pending_captures", _migrate_pending_captures),
    (4, "payment_cash_effect", _migrate_payment_cash_effect),
    (5, "debt_payment_principal_amount", _migrate_debt_payment_principal_amount),
    (6, "weekly_budget", _migrate_weekly_budget),
    (7, "nullable_weekly_budget_limits", _migrate_nullable_weekly_budget_limits),
    (8, "manual_capture_sessions", _migrate_manual_capture_sessions),
    (9, "source_idempotency", _migrate_source_idempotency),
)

# True, если текущий init_pool() создал файл базы с нуля (Volume не найден,
# путь сменился и т.п.). Используется для предупреждения владельцу в main.py.
created_fresh: bool = False


def _prune_pre_migration_snapshots(backups_dir: Path, *, keep: int) -> None:
    snapshots = sorted(
        backups_dir.glob("pre-migration-*.db"),
        key=lambda path: path.stat().st_mtime,
    )
    for stale in snapshots[:-keep]:
        stale.unlink(missing_ok=True)


async def _snapshot_before_migration(
    conn: aiosqlite.Connection, db_path: Path, version: int
) -> None:
    """Локальный снимок БД перед применением первой ожидающей миграции."""
    backups_dir = db_path.parent / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = backups_dir / f"pre-migration-v{version}-{timestamp}.db"
    destination = sqlite3.connect(target)
    try:
        await conn.backup(destination)
    finally:
        destination.close()
    logger.info("Снимок перед миграцией %d: %s", version, target)
    _prune_pre_migration_snapshots(backups_dir, keep=3)


async def _run_migrations(
    conn: aiosqlite.Connection,
    db_path: Path | None = None,
    had_data: bool = False,
) -> None:
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
          version    INTEGER PRIMARY KEY,
          name       TEXT NOT NULL,
          applied_at TEXT NOT NULL
                     DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00','now'))
        )
        """
    )
    await conn.commit()

    cursor = await conn.execute("SELECT version FROM schema_migrations")
    try:
        applied = {row[0] for row in await cursor.fetchall()}
    finally:
        await cursor.close()

    latest_version = _MIGRATIONS[-1][0]
    unknown_versions = sorted(version for version in applied if version > latest_version)
    if unknown_versions:
        raise RuntimeError(
            "База данных требует более новой версии приложения: "
            f"миграции {unknown_versions}"
        )

    pending = [entry for entry in _MIGRATIONS if entry[0] not in applied]
    if pending and had_data and db_path is not None:
        # Снимок до первой ожидающей миграции: сбойную миграцию можно
        # откатить вручную из <db_dir>/backups.
        await _snapshot_before_migration(conn, db_path, pending[0][0])

    for version, name, migration in _MIGRATIONS:
        if version in applied:
            continue
        if any(applied_version > version for applied_version in applied):
            raise RuntimeError(
                "История миграций БД повреждена: пропущена "
                f"миграция {version} перед уже применёнными"
            )

        logger.info("Применяю миграцию БД: version=%d name=%s", version, name)
        await conn.execute("BEGIN IMMEDIATE")
        try:
            await migration(conn)
            await conn.execute(
                "INSERT INTO schema_migrations (version, name) VALUES (?, ?)",
                (version, name),
            )
        except BaseException:
            await conn.rollback()
            raise
        else:
            await conn.commit()
        applied.add(version)


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
