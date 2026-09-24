"""Операции, черновики захвата и идемпотентность источника/API.

Выделено из ``queries.py`` при разбиении oversized-модуля; код перенесён без
изменений.
"""

import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from finance_bot.database.connection import get_pool

from ._common import _db_value, _pending_json_default, _row, to_cents

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

# --- operations -----------------------------------------------------------

async def insert_operation_once(
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
    source_chat_id: int | None = None,
    source_message_id: int | None = None,
    source_item_index: int | None = None,
) -> tuple[int, bool]:
    """Идемпотентная вставка по источнику: (id, replayed).

    Повторная доставка того же Telegram-апдейта не создаёт вторую строку —
    возвращается id уже существующей операции и ``replayed=True``.
    """
    row = await get_pool().fetchrow(
        """
        INSERT INTO operations (
          op_date, type, amount, category, comment, account,
          transfer_direction, source, needs_review, subscription_id,
          source_chat_id, source_message_id, source_item_index
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (source_chat_id, source_message_id, source_item_index)
        DO NOTHING
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
        source_chat_id,
        source_message_id,
        source_item_index,
    )
    if row is not None:
        return row["id"], False
    existing = await get_pool().fetchrow(
        """
        SELECT id FROM operations
        WHERE source_chat_id IS ? AND source_message_id IS ?
          AND source_item_index IS ?
        ORDER BY id LIMIT 1
        """,
        source_chat_id,
        source_message_id,
        source_item_index,
    )
    if existing is None:
        raise RuntimeError("SQLite не вернул id добавленной операции")
    return existing["id"], True


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
    source_chat_id: int | None = None,
    source_message_id: int | None = None,
    source_item_index: int | None = None,
) -> int:
    """Совместимая обёртка над ``insert_operation_once`` (только id)."""
    operation_id, _ = await insert_operation_once(
        op_date,
        type_,
        amount,
        category,
        comment,
        account,
        source,
        needs_review,
        transfer_direction,
        subscription_id,
        source_chat_id,
        source_message_id,
        source_item_index,
    )
    return operation_id


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


async def find_possible_duplicates(
    op_date: date, amount: Decimal, type_: str, category: str | None
) -> int | None:
    """Кандидат в дубли: та же сумма и тип, и либо дата ±1 день за последние
    15 минут, либо та же дата и та же категория.

    Возвращает id самого свежего кандидата — UI показывает одну кнопку удаления.
    """
    window_start = (op_date - timedelta(days=1)).isoformat()
    window_end = (op_date + timedelta(days=1)).isoformat()
    recent = (
        datetime.now(timezone.utc) - timedelta(minutes=15)
    ).replace(microsecond=0).isoformat()
    row = await get_pool().fetchrow(
        """
        SELECT id FROM operations
        WHERE amount = ? AND type = ? AND deleted_at IS NULL
          AND (
            (op_date BETWEEN ? AND ? AND created_at >= ?)
            OR (op_date = ? AND ? IS NOT NULL AND category IS ?)
          )
        ORDER BY id DESC LIMIT 1
        """,
        to_cents(amount),
        type_,
        window_start,
        window_end,
        recent,
        op_date.isoformat(),
        category,
        category,
    )
    return row["id"] if row else None

# --- идемпотентность источника и API -------------------------------------

async def get_capture_file(file_unique_id: str) -> dict | None:
    row = await get_pool().fetchrow(
        "SELECT * FROM capture_files WHERE file_unique_id = ?",
        file_unique_id,
    )
    return dict(row) if row else None


async def remember_capture_file(
    file_unique_id: str, operation_ids: list[int] | None = None
) -> None:
    payload = json.dumps(operation_ids or [])
    await get_pool().execute(
        """
        INSERT INTO capture_files (file_unique_id, operation_ids)
        VALUES (?, ?)
        ON CONFLICT (file_unique_id) DO UPDATE SET operation_ids = excluded.operation_ids
        """,
        file_unique_id,
        payload,
    )


async def get_idempotent_response(key: str) -> tuple[int, dict] | None:
    row = await get_pool().fetchrow(
        "SELECT status, response_json FROM api_idempotency WHERE key = ?",
        key,
    )
    if row is None:
        return None
    try:
        payload = json.loads(row["response_json"] or "{}")
    except json.JSONDecodeError:
        return None
    return int(row["status"]), payload


async def save_idempotent_response(
    key: str, status: int, payload: dict
) -> None:
    await purge_expired_idempotency()
    await get_pool().execute(
        """
        INSERT INTO api_idempotency (key, status, response_json)
        VALUES (?, ?, ?)
        ON CONFLICT (key) DO NOTHING
        """,
        key,
        status,
        json.dumps(payload, ensure_ascii=False),
    )


async def purge_expired_idempotency() -> None:
    cutoff = (
        datetime.now(timezone.utc) - timedelta(hours=24)
    ).replace(microsecond=0).isoformat()
    await get_pool().execute(
        "DELETE FROM api_idempotency WHERE created_at < ?", cutoff
    )
