"""Воскресный недельный блок для вечернего пинга (spec 05).

Отчёт добавляется к существующему вечернему сообщению один раз за день и
делится теми же правилами, что карточка ближайших платежей (spec 04).
Сбой необязательного блока не теряет весь пинг: ошибки логируются.
"""

import logging
from datetime import date
from decimal import Decimal

from finance_bot.core.budget import week_bounds
from finance_bot.core.dashboard import fmt_amount
from finance_bot.database import queries
from finance_bot.services import budget as budget_service
from finance_bot.services import upcoming as upcoming_service

logger = logging.getLogger(__name__)


async def sunday_lines(today: date) -> list[str]:
    """Строки недельной сводки; пустой список, если данных нет."""
    week_start, week_end = week_bounds(today)
    lines = [f"🗓 Неделя {week_start:%d.%m}–{week_end:%d.%m}"]

    categories: list[dict] = []
    try:
        categories = await queries.expenses_by_category(week_start, week_end)
    except Exception:
        logger.exception("Не удалось собрать категории недели")

    report: dict | None = None
    try:
        report = await budget_service.get_budget(today=today)
    except Exception:
        logger.exception("Не удалось собрать бюджет недели")

    overall = (report or {}).get("overall")
    if overall is not None:
        lines.append(
            f"Расходы: {fmt_amount(overall['spent'])} из "
            f"{fmt_amount(overall['limit'])}"
        )
        remaining = overall["remaining"]
        if remaining < 0:
            lines.append(f"Перерасход: {fmt_amount(abs(remaining))}")
        else:
            lines.append(f"Остаток: {fmt_amount(remaining)}")
    else:
        total = sum((row["total"] for row in categories), Decimal("0"))
        lines.append(f"Расходы за неделю: {fmt_amount(total)}")
        lines.append("Общий недельный лимит не задан.")

    top = categories[:3]
    if top:
        parts = " · ".join(
            f"{row['category']} {fmt_amount(row['total'])}" for row in top
        )
        lines.append(f"Крупнейшие категории: {parts}")

    payments, errors = await upcoming_service.get_upcoming(today)
    if payments:
        lines.append("")
        lines.append("Ближайшие 7 дней:")
        for item in payments:
            amount = (
                "сумма не указана"
                if item["amount"] is None else fmt_amount(item["amount"])
            )
            lines.append(f"• {item['date']:%d.%m} {item['name']} — {amount}")
    if errors:
        lines.append("Часть данных о ближайших платежах недоступна.")

    return lines
