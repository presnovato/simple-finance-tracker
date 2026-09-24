"""Схема SQLite.

Выделено из ``connection.py`` при разбиении oversized-модуля; SQL перенесён
без изменений.
"""

import re

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
