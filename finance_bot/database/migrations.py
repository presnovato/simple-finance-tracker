"""Миграции схемы SQLite.

Выделено из ``connection.py`` при разбиении oversized-модуля; код перенесён
без изменений.
"""

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite

logger = logging.getLogger(__name__)


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
