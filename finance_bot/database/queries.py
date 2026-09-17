import json
from calendar import monthrange
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Mapping

from finance_bot.config import (
    RHYTHM_EXPENSE_EXCLUDED_CATEGORIES,
    RHYTHM_INCOME_EXCLUDED_CATEGORIES,
)
from finance_bot.core.crypto import apply_crypto_transaction
from finance_bot.core.subscriptions import next_charge_after
from finance_bot.database.connection import get_pool

CENTS = Decimal("100")
TWO_PLACES = Decimal("0.01")

MONEY_COLUMNS = {
    "amount",
    "principal_amount",
    "interest_amount",
    "principal",
    "balance",
    "min_payment",
    "next_payment_amount",
    "total",
    "expense",
    "income",
    "transfer_in",
    "transfer_out",
    "rub_amount",
    "overall_limit",
    "weekly_limit",
    "spent",
}
RATE_COLUMNS = {"rate"}
DATE_COLUMNS = {
    "op_date", "pay_date", "due_date", "opened_at", "next_payment_date",
    "anchor_date", "next_charge", "week_start", "week_end",
}
TS_COLUMNS = {"created_at", "deleted_at", "updated_at"}
BOOL_COLUMNS = {"needs_review", "archived"}
DECIMAL_TEXT_COLUMNS = {"quantity", "quantity_delta"}


def to_cents(value: Decimal | int) -> int:
    return int(
        (Decimal(value) * CENTS).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    )


def from_cents(value: int | None) -> Decimal | None:
    if value is None:
        return None
    return (Decimal(value) / CENTS).quantize(TWO_PLACES)


def _row(row: Mapping[str, object]) -> dict:
    result = dict(row)
    for column, value in result.items():
        if value is None:
            continue
        if column in MONEY_COLUMNS or column in RATE_COLUMNS:
            if not isinstance(value, Decimal):
                result[column] = from_cents(int(value))
        elif column in DATE_COLUMNS:
            if not isinstance(value, date):
                result[column] = date.fromisoformat(str(value))
        elif column in TS_COLUMNS:
            if not isinstance(value, datetime):
                result[column] = datetime.fromisoformat(str(value))
        elif column in BOOL_COLUMNS:
            result[column] = bool(value)
        elif column in DECIMAL_TEXT_COLUMNS:
            result[column] = Decimal(str(value))
    return result


def _rows(rows: list[dict]) -> list[dict]:
    return [_row(row) for row in rows]


def _date_value(value: date | None) -> str | None:
    return value.isoformat() if value is not None else None


def _ts_value(value: datetime) -> str:
    """Строка того же формата, что и `created_at` в схеме — иначе сравнение
    строк в SQLite поедет: UTC, секундная точность, оффсет `+00:00`."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _period_clause(
    start: date, end: date, start_ts: datetime | None = None
) -> tuple[str, tuple[str, ...]]:
    """Граница периода по дате или по точному моменту якоря.

    Для даты якоря учитываем только операции, созданные после обновления
    баланса. На остальных датах достаточно обычного верхнего ограничения.
    """
    if start_ts is None:
        return "op_date BETWEEN ? AND ?", (start.isoformat(), end.isoformat())
    anchor = start.isoformat()
    return (
        "(op_date > ? OR (op_date = ? AND created_at > ?)) AND op_date <= ?",
        (anchor, anchor, _ts_value(start_ts), end.isoformat()),
    )


def _db_value(column: str, value: object) -> object:
    if value is None:
        return None
    if column in MONEY_COLUMNS or column in RATE_COLUMNS:
        return to_cents(value)  # type: ignore[arg-type]
    if column in DATE_COLUMNS:
        return value.isoformat()  # type: ignore[union-attr]
    if column in TS_COLUMNS:
        return value.isoformat()  # type: ignore[union-attr]
    if column in BOOL_COLUMNS:
        return int(bool(value))
    return value


def _pending_json_default(value: object) -> str:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError(f"Значение {type(value).__name__} нельзя сохранить в JSON")


async def create_pending_capture(
    tg_message_id: int,
    source: str,
    draft: dict,
    context: str | None = None,
) -> None:
    draft_json = json.dumps(
        draft,
        ensure_ascii=False,
        default=_pending_json_default,
    )
    await get_pool().execute(
        """
        INSERT INTO pending_captures (tg_message_id, source, context, draft_json)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(tg_message_id) DO UPDATE SET
          source = excluded.source,
          context = excluded.context,
          draft_json = excluded.draft_json,
          created_at = strftime('%Y-%m-%dT%H:%M:%S+00:00','now')
        """,
        tg_message_id,
        source,
        context,
        draft_json,
    )


async def get_pending_capture(tg_message_id: int) -> dict | None:
    row = await get_pool().fetchrow(
        "SELECT * FROM pending_captures WHERE tg_message_id = ?",
        tg_message_id,
    )
    if row is None:
        return None
    try:
        draft = json.loads(row["draft_json"])
    except (TypeError, ValueError):
        await delete_pending_capture(tg_message_id)
        return None
    return {
        "tg_message_id": row["tg_message_id"],
        "source": row["source"],
        "context": row["context"],
        "draft": draft,
    }


async def delete_pending_capture(tg_message_id: int) -> None:
    await get_pool().execute(
        "DELETE FROM pending_captures WHERE tg_message_id = ?",
        tg_message_id,
    )


async def save_manual_capture_session(
    tg_user_id: int,
    step: str,
    draft: dict,
) -> None:
    draft_json = json.dumps(
        draft,
        ensure_ascii=False,
        default=_pending_json_default,
    )
    await get_pool().execute(
        """
        INSERT INTO manual_capture_sessions (tg_user_id, step, draft_json)
        VALUES (?, ?, ?)
        ON CONFLICT(tg_user_id) DO UPDATE SET
          step = excluded.step,
          draft_json = excluded.draft_json,
          updated_at = strftime('%Y-%m-%dT%H:%M:%S+00:00','now')
        """,
        tg_user_id,
        step,
        draft_json,
    )


async def get_manual_capture_session(tg_user_id: int) -> dict | None:
    row = await get_pool().fetchrow(
        "SELECT * FROM manual_capture_sessions WHERE tg_user_id = ?",
        tg_user_id,
    )
    if row is None:
        return None
    try:
        draft = json.loads(row["draft_json"])
    except (TypeError, ValueError):
        await delete_manual_capture_session(tg_user_id)
        return None
    return {
        "tg_user_id": row["tg_user_id"],
        "step": row["step"],
        "draft": draft,
        "updated_at": row["updated_at"],
    }


async def delete_manual_capture_session(tg_user_id: int) -> None:
    await get_pool().execute(
        "DELETE FROM manual_capture_sessions WHERE tg_user_id = ?",
        tg_user_id,
    )


def _advance_month(value: date, payment_day: int | None = None) -> date:
    """Сдвигает ежемесячную дату, не ломаясь на коротких месяцах."""
    month_index = value.year * 12 + value.month
    year, month_zero = divmod(month_index, 12)
    month = month_zero + 1
    day = payment_day or value.day
    return date(year, month, min(day, monthrange(year, month)[1]))


def _next_payment_after(
    debt: dict, payment_type: str,
) -> date | None:
    scheduled = debt.get("next_payment_date")
    if payment_type != "regular" or scheduled is None:
        return scheduled
    return _advance_month(scheduled, debt.get("payment_day"))


class DebtPaymentError(ValueError):
    """Ошибка бизнес-правил при внесении платежа по долгу."""


# --- operations -----------------------------------------------------------

async def insert_operation(
    op_date: date,
    type_: str,
    amount: Decimal,
    category: str | None,
    comment: str | None,
    account: str | None,
    source: str,
    needs_review: bool,
    transfer_direction: str | None = None,
    subscription_id: int | None = None,
) -> int:
    row = await get_pool().fetchrow(
        """
        INSERT INTO operations (
          op_date, type, amount, category, comment, account,
          transfer_direction, source, needs_review, subscription_id
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        RETURNING id
        """,
        op_date.isoformat(),
        type_,
        to_cents(amount),
        category,
        comment,
        account,
        transfer_direction,
        source,
        int(needs_review),
        subscription_id,
    )
    if row is None:
        raise RuntimeError("SQLite не вернул id добавленной операции")
    return row["id"]


async def set_tg_message_id(op_id: int, tg_message_id: int) -> None:
    await get_pool().execute(
        "UPDATE operations SET tg_message_id = ? WHERE id = ?",
        tg_message_id,
        op_id,
    )


async def get_by_tg_message_id(tg_message_id: int) -> dict | None:
    row = await get_pool().fetchrow(
        """SELECT * FROM operations
           WHERE tg_message_id = ? AND deleted_at IS NULL""",
        tg_message_id,
    )
    return _row(row) if row else None


async def update_operation(op_id: int, fields: dict) -> None:
    allowed = (
        "op_date",
        "type",
        "amount",
        "category",
        "comment",
        "account",
        "needs_review",
        "transfer_direction",
    )
    updates = {key: value for key, value in fields.items() if key in allowed}
    if not updates:
        return
    columns = ", ".join(f"{key} = ?" for key in updates)
    values = [_db_value(key, value) for key, value in updates.items()]
    await get_pool().execute(
        f"""UPDATE operations SET {columns}
            WHERE id = ? AND deleted_at IS NULL""",
        *values,
        op_id,
    )


async def delete_operation(op_id: int) -> None:
    await get_pool().execute("DELETE FROM operations WHERE id = ?", op_id)


async def find_duplicate(
    op_date: date, amount: Decimal, type_: str
) -> int | None:
    row = await get_pool().fetchrow(
        """
        SELECT id FROM operations
        WHERE op_date = ? AND amount = ? AND type = ?
          AND deleted_at IS NULL
        ORDER BY id DESC LIMIT 1
        """,
        op_date.isoformat(),
        to_cents(amount),
        type_,
    )
    return row["id"] if row else None


# --- сводки ---------------------------------------------------------------

async def day_operations(op_date: date) -> list[dict]:
    rows = await get_pool().fetch(
        """SELECT * FROM operations
           WHERE op_date = ? AND deleted_at IS NULL ORDER BY id""",
        op_date.isoformat(),
    )
    return _rows(rows)


async def pending_review() -> list[dict]:
    rows = await get_pool().fetch(
        """SELECT * FROM operations
           WHERE needs_review AND deleted_at IS NULL ORDER BY id"""
    )
    return _rows(rows)


async def expenses_by_category(
    start: date, end: date, *, start_ts: datetime | None = None
) -> list[dict]:
    """Расходы [start, end] по категориям, по убыванию. Переводы исключены."""
    period_clause, period_args = _period_clause(start, end, start_ts)
    rows = await get_pool().fetch(
        f"""
        SELECT coalesce(category, 'Прочее') AS category, sum(amount) AS total
        FROM operations
        WHERE type = 'расход' AND {period_clause}
          AND deleted_at IS NULL
        GROUP BY 1 ORDER BY total DESC
        """,
        *period_args,
    )
    return _rows(rows)


# --- недельный бюджет ----------------------------------------------------

async def get_weekly_budget_template() -> dict | None:
    row = await get_pool().fetchrow(
        "SELECT id, overall_limit FROM weekly_budget_template WHERE id = 1"
    )
    if row is None:
        return None
    category_rows = await get_pool().fetch(
        """
        SELECT category, weekly_limit
        FROM weekly_budget_template_categories
        ORDER BY rowid
        """
    )
    return {
        "overall_limit": _row(row)["overall_limit"],
        "categories": [
            {
                "category": category_row["category"],
                "limit": _row(category_row)["weekly_limit"],
            }
            for category_row in category_rows
        ],
    }


async def save_weekly_budget_settings(
    overall_limit: Decimal | None,
    categories: list[dict],
    week_start: date,
    week_end: date,
) -> None:
    """Атомарно обновляет шаблон и snapshot текущей недели."""
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                """
                INSERT INTO weekly_budget_template (id, overall_limit)
                VALUES (1, ?)
                ON CONFLICT (id) DO UPDATE SET
                  overall_limit = excluded.overall_limit,
                  updated_at = strftime('%Y-%m-%dT%H:%M:%S+00:00','now')
                """,
                to_cents(overall_limit) if overall_limit is not None else None,
            )
            await conn.execute(
                "DELETE FROM weekly_budget_template_categories"
            )
            for item in categories:
                await conn.execute(
                    """
                    INSERT INTO weekly_budget_template_categories
                      (category, weekly_limit)
                    VALUES (?, ?)
                    """,
                    item["category"],
                    to_cents(item["limit"]) if item["limit"] is not None else None,
                )

            await conn.execute(
                """
                INSERT INTO weekly_budget_weeks
                  (week_start, week_end, overall_limit)
                VALUES (?, ?, ?)
                ON CONFLICT (week_start) DO UPDATE SET
                  week_end = excluded.week_end,
                  overall_limit = excluded.overall_limit
                """,
                week_start.isoformat(),
                week_end.isoformat(),
                to_cents(overall_limit) if overall_limit is not None else None,
            )
            await conn.execute(
                "DELETE FROM weekly_budget_week_categories WHERE week_start = ?",
                week_start.isoformat(),
            )
            for item in categories:
                await conn.execute(
                    """
                    INSERT INTO weekly_budget_week_categories
                      (week_start, category, weekly_limit)
                    VALUES (?, ?, ?)
                    """,
                    week_start.isoformat(),
                    item["category"],
                    to_cents(item["limit"]) if item["limit"] is not None else None,
                )


async def ensure_weekly_budget_snapshot(
    week_start: date, week_end: date
) -> bool:
    """Создаёт snapshot недели из шаблона, если бюджет уже настроен."""
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            existing = await conn.fetchrow(
                "SELECT week_start FROM weekly_budget_weeks WHERE week_start = ?",
                week_start.isoformat(),
            )
            if existing is not None:
                return True
            template = await conn.fetchrow(
                "SELECT overall_limit FROM weekly_budget_template WHERE id = 1"
            )
            if template is None:
                return False
            await conn.execute(
                """
                INSERT INTO weekly_budget_weeks
                  (week_start, week_end, overall_limit)
                VALUES (?, ?, ?)
                """,
                week_start.isoformat(),
                week_end.isoformat(),
                template["overall_limit"],
            )
            await conn.execute(
                """
                INSERT INTO weekly_budget_week_categories
                  (week_start, category, weekly_limit)
                SELECT ?, category, weekly_limit
                FROM weekly_budget_template_categories
                """,
                week_start.isoformat(),
            )
            return True


async def get_weekly_budget_snapshot(week_start: date) -> dict | None:
    row = await get_pool().fetchrow(
        """
        SELECT week_start, week_end, overall_limit
        FROM weekly_budget_weeks
        WHERE week_start = ?
        """,
        week_start.isoformat(),
    )
    if row is None:
        return None
    category_rows = await get_pool().fetch(
        """
        SELECT category, weekly_limit
        FROM weekly_budget_week_categories
        WHERE week_start = ?
        ORDER BY rowid
        """,
        week_start.isoformat(),
    )
    snapshot = _row(row)
    snapshot["categories"] = [
        {
            "category": category_row["category"],
            "limit": _row(category_row)["weekly_limit"],
        }
        for category_row in category_rows
    ]
    return snapshot


async def weekly_budget_spent(
    start: date, end: date, categories: list[str]
) -> dict[str, Decimal]:
    category_clause = ""
    category_args: list[object] = []
    if categories:
        placeholders = ", ".join("?" for _ in categories)
        category_clause = (
            f"AND coalesce(category, 'Прочее') IN ({placeholders})"
        )
        category_args.extend(categories)
    rows = await get_pool().fetch(
        f"""
        SELECT coalesce(category, 'Прочее') AS category,
               coalesce(sum(amount), 0) AS spent
        FROM operations
        WHERE type = 'расход'
          AND deleted_at IS NULL
          AND op_date BETWEEN ? AND ?
          {category_clause}
        GROUP BY 1
        """,
        start.isoformat(),
        end.isoformat(),
        *category_args,
    )
    return {
        row["category"]: _row(row)["spent"]
        for row in rows
    }


async def weekly_budget_neighbor_starts(
    week_start: date, current_week_start: date
) -> tuple[date | None, date | None]:
    row = await get_pool().fetchrow(
        """
        SELECT
          (SELECT week_start FROM weekly_budget_weeks
           WHERE week_start < ? ORDER BY week_start DESC LIMIT 1)
            AS previous_week_start,
          (SELECT week_start FROM weekly_budget_weeks
           WHERE week_start > ? AND week_start <= ?
           ORDER BY week_start LIMIT 1)
            AS next_week_start
        """,
        week_start.isoformat(),
        week_start.isoformat(),
        current_week_start.isoformat(),
    )
    if row is None:
        return None, None
    previous = (
        date.fromisoformat(row["previous_week_start"])
        if row["previous_week_start"] else None
    )
    following = (
        date.fromisoformat(row["next_week_start"])
        if row["next_week_start"] else None
    )
    return previous, following


async def claim_weekly_budget_notification(week_start: date, kind: str) -> bool:
    row = await get_pool().fetchrow(
        """
        INSERT OR IGNORE INTO weekly_budget_notifications (week_start, kind)
        VALUES (?, ?)
        RETURNING kind
        """,
        week_start.isoformat(),
        kind,
    )
    return row is not None


async def claim_weekly_budget_notifications(
    week_start: date, kinds: list[str]
) -> list[str]:
    """Атомарно резервирует несколько событий одной бюджетной проверки."""
    if not kinds:
        return []
    pool = get_pool()
    claimed = []
    async with pool.acquire() as conn:
        async with conn.transaction():
            for kind in kinds:
                row = await conn.fetchrow(
                    """
                    INSERT OR IGNORE INTO weekly_budget_notifications
                      (week_start, kind)
                    VALUES (?, ?)
                    RETURNING kind
                    """,
                    week_start.isoformat(),
                    kind,
                )
                if row is not None:
                    claimed.append(row["kind"])
    return claimed


async def totals(
    start: date, end: date, *, start_ts: datetime | None = None
) -> dict:
    period_clause, period_args = _period_clause(start, end, start_ts)
    row = await get_pool().fetchrow(
        f"""
        SELECT
          coalesce(sum(amount) FILTER (WHERE type = 'расход'), 0) AS expense,
          coalesce(sum(amount) FILTER (WHERE type = 'доход'), 0)  AS income,
          coalesce(sum(amount) FILTER (
            WHERE type = 'перевод' AND transfer_direction = 'in'
          ), 0) AS transfer_in,
          coalesce(sum(amount) FILTER (
            WHERE type = 'перевод'
              AND coalesce(transfer_direction, 'out') = 'out'
          ), 0) AS transfer_out
        FROM operations
        WHERE {period_clause} AND deleted_at IS NULL
          AND NOT (
            type = 'перевод' AND (
              EXISTS (
                SELECT 1 FROM personal_debts d
                WHERE d.operation_id = operations.id
              )
              OR EXISTS (
                SELECT 1 FROM personal_debt_payments p
                WHERE p.operation_id = operations.id
              )
              OR EXISTS (
                SELECT 1 FROM debt_payments k
                WHERE k.operation_id = operations.id
              )
            )
        )
        """,
        *period_args,
    )
    if row is None:
        raise RuntimeError("SQLite не вернул строку итогов")
    return _row(row)


async def totals_since(anchor_date: date, anchor_ts: datetime) -> dict:
    """Движения денег после момента якоря.

    Якорь — момент, а не дата: операции дня якоря, записанные до пересчёта,
    уже входят в названную сумму и повторно вычитаться не должны.
    """
    row = await get_pool().fetchrow(
        """
        SELECT
          coalesce(sum(amount) FILTER (WHERE type = 'расход'), 0) AS expense,
          coalesce(sum(amount) FILTER (WHERE type = 'доход'), 0)  AS income,
          coalesce(sum(amount) FILTER (
            WHERE type = 'перевод' AND transfer_direction = 'in'
          ), 0) AS transfer_in,
          coalesce(sum(amount) FILTER (
            WHERE type = 'перевод'
              AND coalesce(transfer_direction, 'out') = 'out'
          ), 0) AS transfer_out,
          count(*) FILTER (
            WHERE type IN ('расход', 'доход')
               OR (type = 'перевод'
                   AND coalesce(transfer_direction, 'out') IN ('in', 'out'))
          ) AS movement_count
        FROM operations
        WHERE deleted_at IS NULL
          AND (op_date > ? OR (op_date = ? AND created_at > ?))
        """,
        anchor_date.isoformat(),
        anchor_date.isoformat(),
        _ts_value(anchor_ts),
    )
    if row is None:
        raise RuntimeError("SQLite не вернул строку итогов")
    return _row(row)


# --- Telegram Mini App ---------------------------------------------------

async def _amounts_by_day(
    start: date,
    end: date,
    *,
    type_: str,
    excluded_categories: tuple[str, ...] = (),
    start_ts: datetime | None = None,
) -> list[dict]:
    period_clause, period_args = _period_clause(start, end, start_ts)
    category_clause = ""
    category_args: tuple[str, ...] = ()
    if excluded_categories:
        placeholders = ", ".join("?" for _ in excluded_categories)
        category_clause = (
            f"AND coalesce(category, '') NOT IN ({placeholders})"
        )
        category_args = excluded_categories
    rows = await get_pool().fetch(
        f"""
        SELECT op_date, sum(amount) AS total
        FROM operations
        WHERE type = ? {category_clause} AND {period_clause}
          AND deleted_at IS NULL
        GROUP BY op_date ORDER BY op_date
        """,
        type_, *category_args, *period_args,
    )
    return _rows(rows)


async def expenses_by_day(
    start: date, end: date, *, start_ts: datetime | None = None
) -> list[dict]:
    """Переменные расходы по дням без жилья и долговых платежей."""
    return await _amounts_by_day(
        start,
        end,
        type_="расход",
        excluded_categories=RHYTHM_EXPENSE_EXCLUDED_CATEGORIES,
        start_ts=start_ts,
    )


async def income_by_day(
    start: date, end: date, *, start_ts: datetime | None = None
) -> list[dict]:
    """Доходы по дням без зарплаты."""
    return await _amounts_by_day(
        start,
        end,
        type_="доход",
        excluded_categories=RHYTHM_INCOME_EXCLUDED_CATEGORIES,
        start_ts=start_ts,
    )


async def operations_for_export(
    start: date | None = None, end: date | None = None
) -> list[dict]:
    """Возвращает только активные операции для пользовательского экспорта."""
    conditions = ["deleted_at IS NULL"]
    args: list[object] = []
    if start is not None:
        conditions.append("op_date >= ?")
        args.append(start.isoformat())
    if end is not None:
        conditions.append("op_date <= ?")
        args.append(end.isoformat())
    rows = await get_pool().fetch(
        f"""
        SELECT * FROM operations
        WHERE {' AND '.join(conditions)}
        ORDER BY op_date, id
        """,
        *args,
    )
    return _rows(rows)


async def get_operation(
    op_id: int, *, include_deleted: bool = False
) -> dict | None:
    deleted_clause = "" if include_deleted else "AND deleted_at IS NULL"
    row = await get_pool().fetchrow(
        f"SELECT * FROM operations WHERE id = ? {deleted_clause}", op_id
    )
    return _row(row) if row else None


async def list_operations(
    *,
    before: tuple[date, int] | None = None,
    category: str | None = None,
    type_: str | None = None,
    query: str | None = None,
    needs_review: bool | None = None,
    op_date: date | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = 40,
) -> list[dict]:
    conditions, args = _operation_filter_parts(
        before=before,
        category=category,
        type_=type_,
        query=query,
        needs_review=needs_review,
        op_date=op_date,
        date_from=date_from,
        date_to=date_to,
    )

    args.append(limit)
    limit_param = "?"
    rows = await get_pool().fetch(
        f"""
        SELECT * FROM operations
        WHERE {' AND '.join(conditions)}
        ORDER BY op_date DESC, id DESC
        LIMIT {limit_param}
        """,
        *args,
    )
    return _rows(rows)


def _operation_filter_parts(
    *,
    before: tuple[date, int] | None = None,
    category: str | None = None,
    type_: str | None = None,
    query: str | None = None,
    needs_review: bool | None = None,
    op_date: date | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> tuple[list[str], list[object]]:
    conditions = ["deleted_at IS NULL"]
    args: list[object] = []

    def bind(value: object) -> str:
        args.append(value)
        return "?"

    if before is not None:
        before_date = before[0].isoformat()
        date_before = bind(before_date)
        date_equal = bind(before_date)
        id_before = bind(before[1])
        conditions.append(
            f"(op_date < {date_before} OR "
            f"(op_date = {date_equal} AND id < {id_before}))"
        )
    if category:
        conditions.append(f"coalesce(category, 'Прочее') = {bind(category)}")
    if type_:
        conditions.append(f"type = {bind(type_)}")
    if query:
        conditions.append(
            f"icontains(coalesce(comment, ''), {bind(query)})"
        )
    if needs_review is not None:
        conditions.append(f"needs_review = {bind(int(needs_review))}")
    if op_date is not None:
        conditions.append(f"op_date = {bind(op_date.isoformat())}")
    if date_from is not None:
        conditions.append(f"op_date >= {bind(date_from.isoformat())}")
    if date_to is not None:
        conditions.append(f"op_date <= {bind(date_to.isoformat())}")
    return conditions, args


async def operations_totals(
    *,
    category: str | None = None,
    type_: str | None = None,
    query: str | None = None,
    needs_review: bool | None = None,
    op_date: date | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict:
    conditions, args = _operation_filter_parts(
        category=category,
        type_=type_,
        query=query,
        needs_review=needs_review,
        op_date=op_date,
        date_from=date_from,
        date_to=date_to,
    )
    row = await get_pool().fetchrow(
        f"""
        SELECT
          count(*) AS total_count,
          coalesce(sum(amount) FILTER (WHERE type = 'расход'), 0) AS expense,
          coalesce(sum(amount) FILTER (WHERE type = 'доход'), 0) AS income,
          coalesce(sum(amount) FILTER (WHERE type = 'перевод'), 0) AS transfer
        FROM operations
        WHERE {' AND '.join(conditions)}
        """,
        *args,
    )
    if row is None:
        raise RuntimeError("SQLite не вернул итоги истории")
    return {
        "total_count": int(row["total_count"]),
        "expense": from_cents(int(row["expense"] or 0)) or Decimal("0.00"),
        "income": from_cents(int(row["income"] or 0)) or Decimal("0.00"),
        "transfer": from_cents(int(row["transfer"] or 0)) or Decimal("0.00"),
    }


async def patch_operation(op_id: int, fields: dict) -> dict | None:
    allowed = (
        "op_date",
        "type",
        "amount",
        "category",
        "comment",
        "account",
        "note",
        "transfer_direction",
    )
    updates = {key: value for key, value in fields.items() if key in allowed}
    if not updates:
        return await get_operation(op_id)
    columns = [f"{key} = ?" for key in updates]
    if any(key != "note" for key in updates):
        columns.append("needs_review = 0")
    values = [_db_value(key, value) for key, value in updates.items()]
    row = await get_pool().fetchrow(
        f"""
        UPDATE operations SET {', '.join(columns)}
        WHERE id = ? AND deleted_at IS NULL
        RETURNING *
        """,
        *values,
        op_id,
    )
    return _row(row) if row else None


async def confirm_operation(op_id: int) -> dict | None:
    row = await get_pool().fetchrow(
        """
        UPDATE operations SET needs_review = 0
        WHERE id = ? AND deleted_at IS NULL
        RETURNING *
        """,
        op_id,
    )
    return _row(row) if row else None


async def soft_delete_operation(op_id: int) -> dict | None:
    deleted_at = datetime.now(timezone.utc).isoformat()
    row = await get_pool().fetchrow(
        """
        UPDATE operations SET deleted_at = ?
        WHERE id = ? AND deleted_at IS NULL
        RETURNING *
        """,
        deleted_at,
        op_id,
    )
    return _row(row) if row else None


async def restore_operation(op_id: int) -> dict | None:
    row = await get_pool().fetchrow(
        """
        UPDATE operations SET deleted_at = NULL
        WHERE id = ? AND deleted_at IS NOT NULL
        RETURNING *
        """,
        op_id,
    )
    return _row(row) if row else None


# --- криптоактивы --------------------------------------------------------

def _decimal_text(value: Decimal) -> str:
    text = format(Decimal(value), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


async def list_crypto_holdings() -> list[dict]:
    rows = await get_pool().fetch(
        "SELECT * FROM crypto_holdings ORDER BY asset"
    )
    return _rows(rows)


async def list_crypto_transactions(limit: int = 50) -> list[dict]:
    rows = await get_pool().fetch(
        """
        SELECT * FROM crypto_transactions
        ORDER BY op_date DESC, id DESC
        LIMIT ?
        """,
        limit,
    )
    return _rows(rows)


async def insert_crypto_transaction(
    *,
    asset: str,
    quantity_delta: Decimal,
    rub_amount: Decimal,
    op_date: date,
    comment: str | None,
) -> dict:
    """Атомарно создаёт перевод рублей и движение криптоостатка."""
    asset = asset.strip().upper()
    quantity_delta = Decimal(quantity_delta)
    if quantity_delta == 0:
        raise ValueError("изменение количества криптовалюты не может быть нулевым")

    # Положительный delta — покупка крипты: рубли уходят из фиата.
    # Отрицательный delta — продажа: рубли возвращаются.
    direction = "out" if quantity_delta > 0 else "in"
    operation_comment = comment or (
        f"Покупка {asset}" if direction == "out" else f"Продажа {asset}"
    )
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            holding = await conn.fetchrow(
                "SELECT quantity FROM crypto_holdings WHERE asset = ?", asset
            )
            current_quantity = (
                Decimal(str(holding["quantity"])) if holding else Decimal("0")
            )
            new_quantity = apply_crypto_transaction(
                current_quantity, quantity_delta
            )
            operation = await conn.fetchrow(
                """
                INSERT INTO operations (
                  op_date, type, amount, category, comment, account,
                  transfer_direction, source, needs_review
                ) VALUES (?, 'перевод', ?, NULL, ?, NULL, ?, 'tma-крипта', 0)
                RETURNING id
                """,
                op_date.isoformat(),
                to_cents(rub_amount),
                operation_comment,
                direction,
            )
            if operation is None:
                raise RuntimeError("SQLite не вернул id криптооперации")
            transaction = await conn.fetchrow(
                """
                INSERT INTO crypto_transactions (
                  asset, quantity_delta, rub_amount, op_date, operation_id, comment
                ) VALUES (?, ?, ?, ?, ?, ?)
                RETURNING *
                """,
                asset,
                _decimal_text(quantity_delta),
                to_cents(rub_amount),
                op_date.isoformat(),
                operation["id"],
                comment,
            )
            if transaction is None:
                raise RuntimeError("SQLite не вернул криптотранзакцию")
            if holding:
                await conn.execute(
                    """
                    UPDATE crypto_holdings
                    SET quantity = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%S+00:00','now')
                    WHERE asset = ?
                    """,
                    _decimal_text(new_quantity),
                    asset,
                )
            else:
                await conn.execute(
                    "INSERT INTO crypto_holdings (asset, quantity) VALUES (?, ?)",
                    asset,
                    _decimal_text(new_quantity),
                )
            return _row(transaction)


async def patch_crypto_holding(asset: str, quantity: Decimal) -> dict | None:
    asset = asset.strip().upper()
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            existing = await conn.fetchrow(
                "SELECT id FROM crypto_holdings WHERE asset = ?", asset
            )
            if existing:
                await conn.execute(
                    """
                    UPDATE crypto_holdings
                    SET quantity = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%S+00:00','now')
                    WHERE asset = ?
                    """,
                    _decimal_text(quantity),
                    asset,
                )
            else:
                await conn.execute(
                    "INSERT INTO crypto_holdings (asset, quantity) VALUES (?, ?)",
                    asset,
                    _decimal_text(quantity),
                )
            row = await conn.fetchrow(
                "SELECT * FROM crypto_holdings WHERE asset = ?", asset
            )
            return _row(row) if row else None


async def delete_crypto_transaction(transaction_id: int) -> dict | None:
    """Удаляет движение крипты, откатывает остаток и soft-delete операции."""
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            transaction = await conn.fetchrow(
                "SELECT * FROM crypto_transactions WHERE id = ?",
                transaction_id,
            )
            if transaction is None:
                return None
            holding = await conn.fetchrow(
                "SELECT quantity FROM crypto_holdings WHERE asset = ?",
                transaction["asset"],
            )
            current_quantity = (
                Decimal(str(holding["quantity"])) if holding else Decimal("0")
            )
            new_quantity = apply_crypto_transaction(
                current_quantity, -Decimal(str(transaction["quantity_delta"]))
            )
            if holding:
                await conn.execute(
                    """
                    UPDATE crypto_holdings
                    SET quantity = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%S+00:00','now')
                    WHERE asset = ?
                    """,
                    _decimal_text(new_quantity),
                    transaction["asset"],
                )
            await conn.execute(
                """
                UPDATE operations SET deleted_at = strftime('%Y-%m-%dT%H:%M:%S+00:00','now')
                WHERE id = ? AND deleted_at IS NULL
                """,
                transaction["operation_id"],
            )
            await conn.execute(
                "DELETE FROM crypto_transactions WHERE id = ?", transaction_id
            )
            return _row(transaction)


# --- кредиты --------------------------------------------------------------

async def list_debts(
    status: str | None = None, *, archived: bool = False
) -> list[dict]:
    conditions = ["d.archived = ?"]
    args: list[object] = [int(archived)]
    if status:
        conditions.append("d.status = ?")
        args.append(status)
    rows = await get_pool().fetch(
        f"""
        SELECT d.*,
               (SELECT count(*) FROM debt_payments p
                WHERE p.debt_id = d.id AND p.kind = 'payment') AS payment_count
        FROM debts d
        WHERE {' AND '.join(conditions)}
        ORDER BY (d.status = 'active') DESC, d.priority NULLS LAST, d.id
        """,
        *args,
    )
    return _rows(rows)


async def get_debt(debt_id: int) -> dict | None:
    row = await get_pool().fetchrow(
        """
        SELECT d.*,
               (SELECT count(*) FROM debt_payments p
                WHERE p.debt_id = d.id AND p.kind = 'payment') AS payment_count
        FROM debts d WHERE d.id = ?
        """,
        debt_id,
    )
    return _row(row) if row else None


async def set_debt_archived(debt_id: int, archived: bool) -> dict | None:
    row = await get_pool().fetchrow(
        "UPDATE debts SET archived = ? WHERE id = ? RETURNING *",
        int(archived), debt_id,
    )
    return _row(row) if row else None


async def delete_debt(debt_id: int) -> bool:
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "SELECT COUNT(*) AS count FROM debt_payments WHERE debt_id = ?",
                debt_id,
            )
            if row is None or row["count"]:
                return False
            deleted = await conn.fetchrow(
                "DELETE FROM debts WHERE id = ? RETURNING id", debt_id
            )
            return deleted is not None


async def insert_debt(
    *,
    creditor: str,
    principal: Decimal,
    rate: Decimal | None,
    min_payment: Decimal | None,
    priority: int | None,
    due_date: date | None,
    loan_name: str | None = None,
    contract_ref: str | None = None,
    opened_at: date | None = None,
    next_payment_amount: Decimal | None = None,
    next_payment_date: date | None = None,
) -> dict:
    principal_cents = to_cents(principal)
    planned_payment = (
        next_payment_amount if next_payment_amount is not None else min_payment
    )
    row = await get_pool().fetchrow(
        """
        INSERT INTO debts (
          creditor, loan_name, contract_ref, principal, balance, rate,
          min_payment, next_payment_amount, opened_at, next_payment_date,
          payment_day, priority, due_date
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        RETURNING *
        """,
        creditor,
        loan_name,
        contract_ref,
        principal_cents,
        principal_cents,
        to_cents(rate) if rate is not None else None,
        to_cents(min_payment) if min_payment is not None else None,
        to_cents(planned_payment) if planned_payment is not None else None,
        _date_value(opened_at),
        _date_value(next_payment_date),
        next_payment_date.day if next_payment_date is not None else None,
        priority,
        _date_value(due_date),
    )
    if row is None:
        raise RuntimeError("SQLite не вернул добавленный кредит")
    return _row(row)


async def patch_debt(debt_id: int, fields: dict) -> dict | None:
    allowed = {
        "creditor",
        "loan_name",
        "contract_ref",
        "principal",
        "rate",
        "min_payment",
        "next_payment_amount",
        "opened_at",
        "next_payment_date",
        "priority",
        "due_date",
        "status",
    }
    updates = {key: value for key, value in fields.items() if key in allowed}
    if not updates:
        return await get_debt(debt_id)
    if "next_payment_date" in updates:
        next_date = updates["next_payment_date"]
        updates["payment_day"] = next_date.day if next_date is not None else None
    columns = ", ".join(f"{key} = ?" for key in updates)
    values = [_db_value(key, value) for key, value in updates.items()]
    row = await get_pool().fetchrow(
        f"UPDATE debts SET {columns} WHERE id = ? RETURNING *",
        *values,
        debt_id,
    )
    return _row(row) if row else None


async def debt_payment_history(
    debt_id: int, *, limit: int | None = None
) -> list[dict]:
    limit_clause = "LIMIT ?" if limit is not None else ""
    args = (debt_id, limit) if limit is not None else (debt_id,)
    rows = await get_pool().fetch(
        f"""
        SELECT * FROM debt_payments
        WHERE debt_id = ? AND kind = 'payment'
        ORDER BY pay_date DESC, id DESC {limit_clause}
        """,
        *args,
    )
    return _rows(rows)


async def debt_history(debt_id: int) -> list[dict]:
    rows = await get_pool().fetch(
        """
        SELECT id, debt_id, operation_id, pay_date, amount, principal_amount,
               CASE WHEN kind = 'payment' AND principal_amount IS NOT NULL
                    THEN amount - principal_amount END AS interest_amount,
               kind,
               payment_type, cash_effect, reason
        FROM debt_payments
        WHERE debt_id = ?
        ORDER BY pay_date DESC, id DESC
        """,
        debt_id,
    )
    return _rows(rows)


async def list_debt_payments() -> list[dict]:
    rows = await get_pool().fetch(
        """
        SELECT p.* FROM debt_payments p
        JOIN debts d ON d.id = p.debt_id
        WHERE p.kind = 'payment' AND d.archived = 0
        ORDER BY p.pay_date, p.id
        """
    )
    return _rows(rows)


async def record_debt_payment(
    debt_id: int,
    operation_id: int,
    pay_date: date,
    amount: Decimal,
    payment_type: str = "regular",
    principal_amount: Decimal | None = None,
) -> dict | None:
    """Идемпотентно привязывает операцию и применяет известную часть к телу."""
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            duplicate = await conn.fetchrow(
                "SELECT debt_id FROM debt_payments WHERE operation_id = ?",
                operation_id,
            )
            if duplicate:
                row = await conn.fetchrow(
                    "SELECT * FROM debts WHERE id = ?", duplicate["debt_id"]
                )
                return _row(row) if row else None
            debt_raw = await conn.fetchrow(
                "SELECT * FROM debts WHERE id = ?", debt_id
            )
            if debt_raw is None:
                return None
            debt = _row(debt_raw)
            if debt["archived"]:
                raise DebtPaymentError("архивный долг нельзя оплачивать")
            if debt["status"] != "active":
                raise DebtPaymentError("закрытый долг нельзя оплачивать")
            if amount <= 0:
                raise DebtPaymentError("сумма платежа должна быть больше нуля")
            if payment_type not in {"regular", "early"}:
                raise DebtPaymentError("неизвестный тип платежа")
            if principal_amount is not None:
                if principal_amount < 0 or principal_amount > amount:
                    raise DebtPaymentError(
                        "часть платежа в тело должна быть от 0 до суммы платежа"
                    )
                if principal_amount > debt["balance"]:
                    raise DebtPaymentError(
                        "часть платежа в тело не может быть больше остатка"
                    )
            applied_principal = (
                principal_amount if principal_amount is not None else Decimal("0")
            )
            new_balance = debt["balance"] - applied_principal
            next_payment_date = _next_payment_after(debt, payment_type)
            await conn.execute(
                """
                INSERT INTO debt_payments (
                  debt_id, operation_id, pay_date, amount, principal_amount,
                  kind, payment_type
                ) VALUES (?, ?, ?, ?, ?, 'payment', ?)
                """,
                debt_id,
                operation_id,
                pay_date.isoformat(),
                to_cents(amount),
                to_cents(principal_amount) if principal_amount is not None else None,
                payment_type,
            )
            balance_cents = to_cents(new_balance)
            row = await conn.fetchrow(
                """
                UPDATE debts
                SET balance = ?,
                    next_payment_date = ?,
                    status = CASE WHEN ? <= 0 THEN 'closed' ELSE 'active' END
                WHERE id = ?
                RETURNING *
                """,
                balance_cents,
                _date_value(next_payment_date),
                balance_cents,
                debt_id,
            )
            if row is None:
                raise RuntimeError("SQLite не вернул обновлённый кредит")
            return _row(row)


async def create_debt_payment(
    debt_id: int,
    pay_date: date,
    amount: Decimal,
    idempotency_key: str | None = None,
    payment_type: str = "regular",
    cash_effect: str = "movement",
    principal_amount: Decimal | None = None,
    return_operation_details: bool = False,
) -> dict | None:
    """Атомарно записывает платёж и известную часть, ушедшую в тело."""
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            if idempotency_key:
                duplicate = await conn.fetchrow(
                    """
                    SELECT debt_id, operation_id
                    FROM debt_payments
                    WHERE idempotency_key = ?
                    """,
                    idempotency_key,
                )
                if duplicate:
                    row = await conn.fetchrow(
                        "SELECT * FROM debts WHERE id = ?", duplicate["debt_id"]
                    )
                    if row is None:
                        return None
                    result = _row(row)
                    if return_operation_details:
                        return {
                            "debt": result,
                            "operation_id": duplicate["operation_id"],
                            "operation_created": False,
                        }
                    return result
            debt_raw = await conn.fetchrow(
                "SELECT * FROM debts WHERE id = ?", debt_id
            )
            if debt_raw is None:
                return None
            debt = _row(debt_raw)
            if debt["archived"]:
                raise DebtPaymentError("архивный долг нельзя оплачивать")
            if debt["status"] != "active":
                raise DebtPaymentError("закрытый долг нельзя оплачивать")
            if amount <= 0:
                raise DebtPaymentError("сумма платежа должна быть больше нуля")
            if payment_type not in {"regular", "early"}:
                raise DebtPaymentError("неизвестный тип платежа")
            if cash_effect not in {"movement", "already_in_balance"}:
                raise DebtPaymentError("неизвестный денежный эффект платежа")
            if principal_amount is not None:
                if principal_amount < 0 or principal_amount > amount:
                    raise DebtPaymentError(
                        "часть платежа в тело должна быть от 0 до суммы платежа"
                    )
                if principal_amount > debt["balance"]:
                    raise DebtPaymentError(
                        "часть платежа в тело не может быть больше остатка"
                    )
            next_payment_date = _next_payment_after(debt, payment_type)
            payment_label = (
                "Досрочное погашение" if payment_type == "early" else "Платёж"
            )
            operation_id = None
            if cash_effect == "movement":
                operation = await conn.fetchrow(
                    """
                    INSERT INTO operations (
                      op_date, type, amount, category, comment, source, needs_review
                    ) VALUES (?, 'расход', ?, 'Долги', ?, 'tma-долг', 0)
                    RETURNING id
                    """,
                    pay_date.isoformat(),
                    to_cents(amount),
                    f"{payment_label} по кредиту "
                    f"{debt.get('loan_name') or debt['creditor']}",
                )
                if operation is None:
                    raise RuntimeError("SQLite не вернул id операции по кредиту")
                operation_id = operation["id"]
            await conn.execute(
                """
                INSERT INTO debt_payments (
                  debt_id, operation_id, pay_date, amount, principal_amount,
                  kind, payment_type, cash_effect, idempotency_key
                ) VALUES (?, ?, ?, ?, ?, 'payment', ?, ?, ?)
                """,
                debt_id,
                operation_id,
                pay_date.isoformat(),
                to_cents(amount),
                to_cents(principal_amount) if principal_amount is not None else None,
                payment_type,
                cash_effect,
                idempotency_key,
            )
            applied_principal = (
                principal_amount if principal_amount is not None else Decimal("0")
            )
            new_balance = debt["balance"] - applied_principal
            row = await conn.fetchrow(
                """
                UPDATE debts
                SET balance = ?,
                    next_payment_date = ?,
                    status = CASE WHEN ? <= 0 THEN 'closed' ELSE 'active' END
                WHERE id = ?
                RETURNING *
                """,
                to_cents(new_balance),
                _date_value(next_payment_date),
                to_cents(new_balance),
                debt_id,
            )
            if row is None:
                raise RuntimeError("SQLite не вернул обновлённый кредит")
            result = _row(row)
            if return_operation_details:
                return {
                    "debt": result,
                    "operation_id": operation_id,
                    "operation_created": operation_id is not None,
                }
            return result


async def adjust_debt_balance(
    debt_id: int,
    new_balance: Decimal,
    adjusted_at: date,
    reason: str | None = None,
) -> dict | None:
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            debt = await conn.fetchrow(
                "SELECT id, principal, archived FROM debts WHERE id = ?", debt_id
            )
            if debt is None:
                return None
            if debt["archived"]:
                raise DebtPaymentError("архивный долг нельзя корректировать")
            balance_cents = to_cents(new_balance)
            if new_balance > from_cents(debt["principal"]):
                raise DebtPaymentError(
                    "остаток не может быть больше первоначальной суммы"
                )
            await conn.execute(
                """
                INSERT INTO debt_payments (debt_id, pay_date, amount, kind, reason)
                VALUES (?, ?, ?, 'adjustment', ?)
                """,
                debt_id,
                adjusted_at.isoformat(),
                balance_cents,
                reason,
            )
            row = await conn.fetchrow(
                """
                UPDATE debts
                SET balance = ?,
                    status = CASE WHEN ? <= 0 THEN 'closed' ELSE 'active' END
                WHERE id = ?
                RETURNING *
                """,
                balance_cents,
                balance_cents,
                debt_id,
            )
            if row is None:
                raise RuntimeError("SQLite не вернул обновлённый кредит")
            return _row(row)


# --- личные долги ---------------------------------------------------------

async def list_personal_debts(
    status: str | None = None, *, archived: bool = False
) -> list[dict]:
    conditions = ["d.archived = ?"]
    args: list[object] = [int(archived)]
    if status:
        conditions.append("d.status = ?")
        args.append(status)
    rows = await get_pool().fetch(
        f"""
        SELECT d.*,
               (SELECT count(*) FROM personal_debt_payments p
                WHERE p.personal_debt_id = d.id) AS payment_count
        FROM personal_debts d
        WHERE {' AND '.join(conditions)}
        ORDER BY (d.status = 'open') DESC, d.due_date NULLS LAST,
                 d.opened_at, d.id
        """,
        *args,
    )
    return _rows(rows)


async def get_personal_debt(personal_debt_id: int) -> dict | None:
    row = await get_pool().fetchrow(
        """
        SELECT d.*,
               (SELECT count(*) FROM personal_debt_payments p
                WHERE p.personal_debt_id = d.id) AS payment_count
        FROM personal_debts d WHERE d.id = ?
        """,
        personal_debt_id,
    )
    return _row(row) if row else None


async def set_personal_debt_archived(
    personal_debt_id: int, archived: bool
) -> dict | None:
    row = await get_pool().fetchrow(
        "UPDATE personal_debts SET archived = ? WHERE id = ? RETURNING *",
        int(archived), personal_debt_id,
    )
    return _row(row) if row else None


async def delete_personal_debt(personal_debt_id: int) -> bool:
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "SELECT COUNT(*) AS count FROM personal_debt_payments "
                "WHERE personal_debt_id = ?",
                personal_debt_id,
            )
            if row is None or row["count"]:
                return False
            deleted = await conn.fetchrow(
                "DELETE FROM personal_debts WHERE id = ? RETURNING id",
                personal_debt_id,
            )
            return deleted is not None


async def insert_personal_debt(
    *,
    person: str,
    direction: str,
    principal: Decimal,
    opened_at: date,
    due_date: date | None,
    comment: str | None,
    operation_id: int | None,
) -> dict:
    principal_cents = to_cents(principal)
    row = await get_pool().fetchrow(
        """
        INSERT INTO personal_debts (
          person, direction, principal, balance, opened_at, due_date,
          comment, operation_id
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        RETURNING *
        """,
        person,
        direction,
        principal_cents,
        principal_cents,
        opened_at.isoformat(),
        _date_value(due_date),
        comment,
        operation_id,
    )
    if row is None:
        raise RuntimeError("SQLite не вернул добавленный личный долг")
    return _row(row)


async def patch_personal_debt(
    personal_debt_id: int, fields: dict
) -> dict | None:
    allowed = {
        "person",
        "direction",
        "principal",
        "balance",
        "opened_at",
        "due_date",
        "comment",
        "status",
    }
    updates = {key: value for key, value in fields.items() if key in allowed}
    if not updates:
        return await get_personal_debt(personal_debt_id)
    if "balance" in updates and "status" not in updates:
        updates["status"] = "closed" if updates["balance"] <= 0 else "open"
    columns = ", ".join(f"{key} = ?" for key in updates)
    values = [_db_value(key, value) for key, value in updates.items()]
    row = await get_pool().fetchrow(
        f"UPDATE personal_debts SET {columns} WHERE id = ? RETURNING *",
        *values,
        personal_debt_id,
    )
    return _row(row) if row else None


async def personal_debt_history(personal_debt_id: int) -> list[dict]:
    rows = await get_pool().fetch(
        """
        SELECT id, personal_debt_id, operation_id, pay_date, amount,
               'payment' AS kind, cash_effect
        FROM personal_debt_payments
        WHERE personal_debt_id = ?
        ORDER BY pay_date DESC, id DESC
        """,
        personal_debt_id,
    )
    return _rows(rows)


async def record_personal_debt_payment(
    personal_debt_id: int,
    operation_id: int,
    pay_date: date,
    amount: Decimal,
) -> dict | None:
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            duplicate = await conn.fetchrow(
                """
                SELECT personal_debt_id FROM personal_debt_payments
                WHERE operation_id = ?
                """,
                operation_id,
            )
            if duplicate:
                row = await conn.fetchrow(
                    "SELECT * FROM personal_debts WHERE id = ?",
                    duplicate["personal_debt_id"],
                )
                return _row(row) if row else None
            debt_raw = await conn.fetchrow(
                "SELECT * FROM personal_debts WHERE id = ?",
                personal_debt_id,
            )
            if debt_raw is None:
                return None
            debt = _row(debt_raw)
            if debt["archived"]:
                raise DebtPaymentError("архивный долг нельзя оплачивать")
            if debt["status"] != "open":
                raise DebtPaymentError("закрытый долг нельзя оплачивать")
            if amount <= 0:
                raise DebtPaymentError("сумма платежа должна быть больше нуля")
            if amount > debt["balance"]:
                raise DebtPaymentError("платёж не может быть больше остатка")
            new_balance = debt["balance"] - amount
            await conn.execute(
                """
                INSERT INTO personal_debt_payments (
                  personal_debt_id, operation_id, pay_date, amount
                ) VALUES (?, ?, ?, ?)
                """,
                personal_debt_id,
                operation_id,
                pay_date.isoformat(),
                to_cents(amount),
            )
            balance_cents = to_cents(new_balance)
            row = await conn.fetchrow(
                """
                UPDATE personal_debts
                SET balance = ?,
                    status = CASE WHEN ? <= 0 THEN 'closed' ELSE 'open' END
                WHERE id = ?
                RETURNING *
                """,
                balance_cents,
                balance_cents,
                personal_debt_id,
            )
            if row is None:
                raise RuntimeError("SQLite не вернул обновлённый личный долг")
            return _row(row)


async def create_personal_debt_payment(
    personal_debt_id: int,
    pay_date: date,
    amount: Decimal,
    idempotency_key: str | None = None,
    cash_effect: str = "movement",
) -> dict | None:
    """Атомарно записывает возврат и при необходимости создаёт перевод."""
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            if idempotency_key:
                duplicate = await conn.fetchrow(
                    """
                    SELECT personal_debt_id FROM personal_debt_payments
                    WHERE idempotency_key = ?
                    """,
                    idempotency_key,
                )
                if duplicate:
                    row = await conn.fetchrow(
                        "SELECT * FROM personal_debts WHERE id = ?",
                        duplicate["personal_debt_id"],
                    )
                    return _row(row) if row else None
            debt_raw = await conn.fetchrow(
                "SELECT * FROM personal_debts WHERE id = ?", personal_debt_id
            )
            if debt_raw is None:
                return None
            debt = _row(debt_raw)
            if debt["archived"]:
                raise DebtPaymentError("архивный долг нельзя оплачивать")
            if debt["status"] != "open":
                raise DebtPaymentError("закрытый долг нельзя оплачивать")
            if amount <= 0:
                raise DebtPaymentError("сумма платежа должна быть больше нуля")
            if amount > debt["balance"]:
                raise DebtPaymentError("платёж не может быть больше остатка")
            if cash_effect not in {"movement", "already_in_balance"}:
                raise DebtPaymentError("неизвестный денежный эффект платежа")
            operation_id = None
            if cash_effect == "movement":
                direction = "in" if debt["direction"] == "owed_to_me" else "out"
                operation = await conn.fetchrow(
                    """
                    INSERT INTO operations (
                      op_date, type, amount, comment, transfer_direction,
                      source, needs_review
                    ) VALUES (?, 'перевод', ?, ?, ?, 'tma-долг', 0)
                    RETURNING id
                    """,
                    pay_date.isoformat(),
                    to_cents(amount),
                    f"Возврат долга: {debt['person']}",
                    direction,
                )
                if operation is None:
                    raise RuntimeError("SQLite не вернул id операции по личному долгу")
                operation_id = operation["id"]
            await conn.execute(
                """
                INSERT INTO personal_debt_payments (
                  personal_debt_id, operation_id, pay_date, amount,
                  cash_effect, idempotency_key
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                personal_debt_id,
                operation_id,
                pay_date.isoformat(),
                to_cents(amount),
                cash_effect,
                idempotency_key,
            )
            new_balance = debt["balance"] - amount
            row = await conn.fetchrow(
                """
                UPDATE personal_debts
                SET balance = ?,
                    status = CASE WHEN ? <= 0 THEN 'closed' ELSE 'open' END
                WHERE id = ?
                RETURNING *
                """,
                to_cents(new_balance),
                to_cents(new_balance),
                personal_debt_id,
            )
            if row is None:
                raise RuntimeError("SQLite не вернул обновлённый личный долг")
            return _row(row)


# --- подписки -------------------------------------------------------------

async def list_subscriptions(
    status: str | None = "active", next_charge: date | None = None
) -> list[dict]:
    conditions: list[str] = []
    args: list[object] = []
    if status is not None:
        conditions.append("status = ?")
        args.append(status)
    if next_charge is not None:
        conditions.append("next_charge = ?")
        args.append(next_charge.isoformat())
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    rows = await get_pool().fetch(
        f"""
        SELECT * FROM subscriptions
        {where}
        ORDER BY next_charge, id
        """,
        *args,
    )
    return _rows(rows)


async def get_subscription(subscription_id: int) -> dict | None:
    row = await get_pool().fetchrow(
        "SELECT * FROM subscriptions WHERE id = ?", subscription_id
    )
    return _row(row) if row else None


async def insert_subscription(
    *,
    title: str,
    amount: Decimal,
    period: str,
    next_charge: date,
    category: str | None,
    comment: str | None,
) -> dict:
    row = await get_pool().fetchrow(
        """
        INSERT INTO subscriptions (
          title, amount, period, next_charge, category, comment
        )
        VALUES (?, ?, ?, ?, ?, ?)
        RETURNING *
        """,
        title,
        to_cents(amount),
        period,
        next_charge.isoformat(),
        category,
        comment,
    )
    if row is None:
        raise RuntimeError("SQLite не вернул добавленную подписку")
    return _row(row)


async def patch_subscription(
    subscription_id: int, fields: dict
) -> dict | None:
    allowed = {
        "title", "amount", "period", "next_charge", "category", "comment", "status",
    }
    updates = {key: value for key, value in fields.items() if key in allowed}
    if not updates:
        return await get_subscription(subscription_id)
    columns = ", ".join(f"{key} = ?" for key in updates)
    values = [_db_value(key, value) for key, value in updates.items()]
    row = await get_pool().fetchrow(
        f"UPDATE subscriptions SET {columns} WHERE id = ? RETURNING *",
        *values,
        subscription_id,
    )
    return _row(row) if row else None


async def cancel_subscription(subscription_id: int) -> dict | None:
    row = await get_pool().fetchrow(
        """
        UPDATE subscriptions SET status = 'cancelled'
        WHERE id = ? AND status != 'cancelled'
        RETURNING *
        """,
        subscription_id,
    )
    return _row(row) if row else None


async def charge_subscription(
    subscription_id: int,
    *,
    confirmed: bool,
    op_date: date | None = None,
    expected_next_charge: date | None = None,
) -> dict | None:
    """Подтверждает или пропускает списание атомарно вместе со сдвигом даты.

    При переданном `expected_next_charge` результат с `stale=True` означает,
    что callback пришёл из старого вечернего сообщения и ничего не меняет.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            raw = await conn.fetchrow(
                "SELECT * FROM subscriptions WHERE id = ? AND status = 'active'",
                subscription_id,
            )
            if raw is None:
                return None

            subscription = _row(raw)
            current_next_charge = subscription["next_charge"]
            if (
                expected_next_charge is not None
                and current_next_charge != expected_next_charge
            ):
                return {
                    "subscription": subscription,
                    "operation_id": None,
                    "operation_date": None,
                    "operation_created": False,
                    "stale": True,
                }

            charge_date = op_date or current_next_charge
            operation_id: int | None = None
            operation_created = False
            if confirmed:
                duplicate = await conn.fetchrow(
                    """
                    SELECT id FROM operations
                    WHERE subscription_id = ? AND op_date = ?
                      AND deleted_at IS NULL
                    ORDER BY id DESC LIMIT 1
                    """,
                    subscription_id,
                    charge_date.isoformat(),
                )
                if duplicate is not None:
                    operation_id = duplicate["id"]
                else:
                    operation = await conn.fetchrow(
                        """
                        INSERT INTO operations (
                          op_date, type, amount, category, comment, account,
                          transfer_direction, source, needs_review, subscription_id
                        )
                        VALUES (?, 'расход', ?, 'Подписки', ?, NULL, NULL,
                                'бот-подписка', 0, ?)
                        RETURNING id
                        """,
                        charge_date.isoformat(),
                        to_cents(subscription["amount"]),
                        subscription["title"],
                        subscription_id,
                    )
                    if operation is None:
                        raise RuntimeError("SQLite не вернул id операции подписки")
                    operation_id = operation["id"]
                    operation_created = True

            new_next_charge = current_next_charge
            if current_next_charge <= charge_date:
                new_next_charge = next_charge_after(
                    current_next_charge, subscription["period"]
                )

            if new_next_charge != current_next_charge:
                updated = await conn.fetchrow(
                    """
                    UPDATE subscriptions
                    SET next_charge = ?
                    WHERE id = ? AND next_charge = ? AND status = 'active'
                    RETURNING *
                    """,
                    new_next_charge.isoformat(),
                    subscription_id,
                    current_next_charge.isoformat(),
                )
                if updated is None:
                    raise RuntimeError("SQLite не вернул обновлённую подписку")
                subscription = _row(updated)

            return {
                "subscription": subscription,
                "operation_id": operation_id,
                "operation_date": charge_date if operation_created else None,
                "operation_created": operation_created,
                "stale": False,
            }


# --- settings -------------------------------------------------------------

async def get_setting(key: str) -> str | None:
    row = await get_pool().fetchrow(
        "SELECT value FROM settings WHERE key = ?", key
    )
    return row["value"] if row else None


async def set_setting(key: str, value: str) -> None:
    await get_pool().execute(
        """
        INSERT INTO settings (key, value) VALUES (?, ?)
        ON CONFLICT (key) DO UPDATE SET value = excluded.value
        """,
        key,
        value,
    )
