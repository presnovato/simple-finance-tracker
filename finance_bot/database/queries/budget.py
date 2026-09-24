"""Недельный бюджет.

Выделено из ``queries.py`` при разбиении oversized-модуля; код перенесён без
изменений.
"""

from datetime import date
from decimal import Decimal

from finance_bot.database.connection import get_pool

from ._common import _row, to_cents

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
