"""Аудит категорий: активные, архивные и пустые (spec 01).

Скрипт только читает SQLite и ничего не меняет. Показывает, какие значения
категорий встречаются в операциях и лимитах и являются ли они активными или
архивными. Запускается на локальной копии базы или mock-базе; production-база
не трогается.

Примеры:

    python tools/category_migration_report.py --db path/to/finance.db
    python tools/category_migration_report.py --db path/to/finance.db --json
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

# Позволяем запуск файлом (`python tools/...`) без установки пакета.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from finance_bot.config import DB_PATH, EXPENSE_CATEGORIES, INCOME_CATEGORIES  # noqa: E402


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
    ).fetchone()
    return row is not None


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def collect(conn: sqlite3.Connection) -> dict:
    report: dict = {
        "known": {
            "expense": list(EXPENSE_CATEGORIES),
            "income": list(INCOME_CATEGORIES),
        },
        "operations": [],
        "unknown_expense": [],
        "unknown_income": [],
        "unknown_other": [],
        "budget_template": [],
        "budget_snapshots": [],
        "subscriptions": [],
    }
    if not _table_exists(conn, "operations"):
        return report

    op_columns = _columns(conn, "operations")
    has_deleted = "deleted_at" in op_columns

    active_sum = "SUM(CASE WHEN deleted_at IS NULL THEN amount ELSE 0 END)"
    rows_sum = "SUM(amount)"
    if not has_deleted:
        active_sum = rows_sum = "SUM(amount)"

    query = f"""
        SELECT COALESCE(category, '<NULL>') AS category,
               type,
               COUNT(*) AS rows,
               {rows_sum} AS total,
               {active_sum} AS active_total,
               SUM(CASE WHEN deleted_at IS NULL THEN 1 ELSE 0 END) AS active_rows
        FROM operations
        GROUP BY category, type
        ORDER BY type, rows DESC, category
    """ if has_deleted else f"""
        SELECT COALESCE(category, '<NULL>') AS category,
               type,
               COUNT(*) AS rows,
               {rows_sum} AS total,
               {rows_sum} AS active_total,
               COUNT(*) AS active_rows
        FROM operations
        GROUP BY category, type
        ORDER BY type, rows DESC, category
    """
    for category, type_, rows, total, active_total, active_rows in conn.execute(query):
        report["operations"].append({
            "category": category,
            "type": type_,
            "rows": rows,
            "active_rows": active_rows,
            "total": _rub(total),
            "active_total": _rub(active_total),
        })

    for item in report["operations"]:
        name = item["category"]
        if name == "<NULL>":
            continue
        if item["type"] == "расход":
            if name not in EXPENSE_CATEGORIES:
                report["unknown_expense"].append(name)
        elif item["type"] == "доход":
            if name not in INCOME_CATEGORIES:
                report["unknown_income"].append(name)
        else:
            report["unknown_other"].append(name)

    if _table_exists(conn, "weekly_budget_template_categories"):
        for category, limit in conn.execute(
            "SELECT category, weekly_limit FROM weekly_budget_template_categories "
            "ORDER BY category"
        ):
            report["budget_template"].append({
                "category": category,
                "weekly_limit": _rub(limit) if limit is not None else None,
            })

    if _table_exists(conn, "weekly_budget_week_categories"):
        for category, weeks, lo, hi in conn.execute(
            "SELECT category, COUNT(*), MIN(weekly_limit), MAX(weekly_limit) "
            "FROM weekly_budget_week_categories GROUP BY category ORDER BY category"
        ):
            report["budget_snapshots"].append({
                "category": category,
                "weeks": weeks,
                "min_limit": _rub(lo) if lo is not None else None,
                "max_limit": _rub(hi) if hi is not None else None,
            })

    if _table_exists(conn, "subscriptions") and _table_exists(conn, "operations"):
        has_status = "status" in _columns(conn, "subscriptions")
        where = "WHERE status = 'active'" if has_status else ""
        for category, count, total in conn.execute(
            f"SELECT COALESCE(category, '<NULL>'), COUNT(*), SUM(amount) "
            f"FROM subscriptions {where} GROUP BY category ORDER BY COUNT(*) DESC"
        ):
            report["subscriptions"].append({
                "category": category,
                "count": count,
                "total": _rub(total),
            })

    report["unknown_expense"] = sorted(set(report["unknown_expense"]))
    report["unknown_income"] = sorted(set(report["unknown_income"]))
    report["unknown_other"] = sorted(set(report["unknown_other"]))
    return report


def _rub(kopecks) -> str:
    """SQLite хранит суммы в копейках."""
    if kopecks is None:
        return "0.00"
    return f"{int(kopecks) / 100:.2f}"


def _op_counts(report: dict) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = defaultdict(lambda: {"rows": 0, "active": 0})
    for item in report["operations"]:
        if item["type"] != "расход":
            continue
        counts[item["category"]]["rows"] += item["rows"]
        counts[item["category"]]["active"] += item["active_rows"]
    return counts


def render_text(report: dict, db_path: str) -> str:
    lines = ["Категории: аудит активных/архивных (spec 01)", f"База: {db_path}", ""]

    lines.append("ОПЕРАЦИИ (все строки, включая soft-deleted)")
    lines.append(f"{'категория':<26}{'тип':<10}{'строк':>8}{'активн.':>9}{'сумма':>14}")
    for item in report["operations"]:
        lines.append(
            f"{item['category']:<26}{item['type']:<10}{item['rows']:>8}"
            f"{item['active_rows']:>9}{item['total']:>14}"
        )
    lines.append("")

    lines.append("ЛИМИТЫ (текущий шаблон недельного бюджета)")
    if report["budget_template"]:
        for item in report["budget_template"]:
            lines.append(
                f"  {item['category']:<26}{item['weekly_limit'] or 'без лимита'}"
            )
    else:
        lines.append("  (нет)")
    lines.append("")

    lines.append("ИСТОРИЧЕСКИЕ СНИМКИ БЮДЖЕТА (не мигрируются без отдельного решения)")
    if report["budget_snapshots"]:
        for item in report["budget_snapshots"]:
            lines.append(
                f"  {item['category']:<26}недель={item['weeks']:<4}"
                f" мин={item['min_limit']} макс={item['max_limit']}"
            )
    else:
        lines.append("  (нет)")
    lines.append("")

    lines.append("ПОДПИСКИ (активные)")
    if report["subscriptions"]:
        for item in report["subscriptions"]:
            lines.append(
                f"  {item['category']:<26}шт={item['count']:<4}сумма={item['total']}"
            )
    else:
        lines.append("  (нет)")
    lines.append("")

    counts = _op_counts(report)
    lines.append("КЛАССИФИКАЦИЯ ЗНАЧЕНИЙ (расходные категории)")
    lines.append(f"{'значение':<26}{'оп.':>5}{'лимит':>10}  статус")
    template = {i["category"] for i in report["budget_template"]}
    seen = set(counts) | template | set(EXPENSE_CATEGORIES)
    if counts.get("<NULL>", {}).get("rows"):
        seen.add("<NULL>")
    for value in sorted(seen):
        if value == "<NULL>":
            status = "NULL: показывается как «Без категории»"
        elif value in EXPENSE_CATEGORIES:
            status = "активная"
        else:
            status = "АРХИВНАЯ (не предлагать для новых операций)"
        lines.append(
            f"{value:<26}{counts.get(value, {}).get('rows', 0):>5}"
            f"{'да' if value in template else '—':>10}  {status}"
        )
    lines.append("")

    if report["unknown_expense"] or report["unknown_income"] or report["unknown_other"]:
        lines.append("НЕАКТИВНЫЕ/НЕИЗВЕСТНЫЕ ЗНАЧЕНИЯ В ДАННЫХ")
        for label, values in (
            ("расход", report["unknown_expense"]),
            ("доход", report["unknown_income"]),
            ("перевод/другой тип", report["unknown_other"]),
        ):
            if values:
                lines.append(f"  {label}: {', '.join(values)}")
        lines.append("")

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=DB_PATH, help="путь к файлу SQLite")
    parser.add_argument("--json", action="store_true", help="вывести JSON")
    args = parser.parse_args(argv)

    db_path = Path(args.db).expanduser()
    if not db_path.is_file():
        print(f"База не найдена: {db_path}", file=sys.stderr)
        return 2

    uri = f"file:{db_path.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        report = collect(conn)
    finally:
        conn.close()

    if args.json:
        report["db"] = str(db_path)
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render_text(report, str(db_path)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
