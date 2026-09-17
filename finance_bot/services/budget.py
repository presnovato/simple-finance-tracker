"""Сервис недельного бюджета для API, TMA, бота и планировщика."""

import logging
from datetime import date, timedelta
from decimal import Decimal

from aiogram import Bot

from finance_bot.config import ALLOWED_USER_ID, EXPENSE_CATEGORIES
from finance_bot.core.budget import (
    budget_line,
    overall_line,
    threshold_reached,
    week_bounds,
)
from finance_bot.core.dashboard import fmt_amount
from finance_bot.core.dates import effective_today
from finance_bot.database import queries
from finance_bot.webapp import web_app_markup

logger = logging.getLogger(__name__)

THRESHOLDS = (
    ("threshold_80", Decimal("80")),
    ("threshold_100", Decimal("100")),
)


def _ordered_categories(categories: list[dict]) -> list[dict]:
    order = {category: index for index, category in enumerate(EXPENSE_CATEGORIES)}
    return sorted(categories, key=lambda item: order.get(item["category"], 999))


async def get_budget(
    week_start: date | None = None,
    *,
    today: date | None = None,
) -> dict:
    current_day = today or effective_today()
    current_start, _ = week_bounds(current_day)
    requested_start = week_start or current_start
    if requested_start.weekday() != 0:
        raise ValueError("week_start должен быть понедельником")
    if requested_start > current_start:
        raise ValueError("нельзя запросить будущую неделю")

    requested_end = requested_start + timedelta(days=6)
    if requested_start == current_start:
        await queries.ensure_weekly_budget_snapshot(
            requested_start, requested_end
        )
    snapshot = await queries.get_weekly_budget_snapshot(requested_start)
    previous, following = await queries.weekly_budget_neighbor_starts(
        requested_start, current_start
    )
    result = {
        "configured": snapshot is not None,
        "week_start": requested_start,
        "week_end": requested_end,
        "is_current": requested_start == current_start,
        "previous_week_start": previous,
        "next_week_start": following,
    }
    if snapshot is None:
        return result

    categories = _ordered_categories(snapshot["categories"])
    spent_by_category = await queries.weekly_budget_spent(
        snapshot["week_start"], snapshot["week_end"],
        [item["category"] for item in categories],
    )
    category_rows = [
        budget_line(
            item["category"],
            item.get("limit"),
            spent_by_category.get(item["category"], Decimal("0.00")),
        )
        for item in categories
    ]
    selected_spent = (
        sum((item["spent"] for item in category_rows), Decimal("0.00"))
        if categories
        else sum(spent_by_category.values(), Decimal("0.00"))
    )
    result.update({
        "selected_spent": selected_spent,
        "category_limits_total": sum(
            (
                item["limit"] for item in category_rows
                if item["limit"] is not None
            ),
            Decimal("0.00"),
        ),
        "overall": overall_line(snapshot["overall_limit"], selected_spent),
        "categories": category_rows,
    })
    return result


async def get_settings() -> dict:
    template = await queries.get_weekly_budget_template()
    if template is None:
        return {"overall_limit": None, "categories": []}
    return {
        "overall_limit": template["overall_limit"],
        "categories": _ordered_categories(template["categories"]),
    }


async def save_settings(
    overall_limit: Decimal | None,
    categories: list[dict],
    *,
    today: date | None = None,
) -> dict:
    if overall_limit is None:
        raise ValueError("общий недельный лимит обязателен")
    current_start, current_end = week_bounds(today or effective_today())
    await queries.save_weekly_budget_settings(
        overall_limit,
        _ordered_categories(categories),
        current_start,
        current_end,
    )
    return await get_settings()


async def _claim_thresholds(report: dict) -> list[str]:
    overall = report.get("overall")
    if overall is None:
        return []
    due = []
    for kind, threshold in THRESHOLDS:
        if not threshold_reached(overall["spent"], overall["limit"], threshold):
            continue
        due.append(kind)
    return await queries.claim_weekly_budget_notifications(
        report["week_start"], due
    )


def _remaining_text(value: Decimal) -> str:
    if value < 0:
        return f"перерасход {fmt_amount(abs(value))}"
    return f"остаток {fmt_amount(value)}"


def render_budget(report: dict) -> str:
    if not report.get("configured"):
        return (
            "💰 Недельный бюджет ещё не настроен.\n"
            "Открой TMA и задай общий недельный лимит."
        )

    lines = [
        f"💰 Бюджет недели {report['week_start']:%d.%m}–"
        f"{report['week_end']:%d.%m}",
    ]
    overall = report.get("overall")
    if overall is not None:
        status = {
            "ok": "в норме",
            "warning": "внимание",
            "exceeded": "лимит превышен",
        }[overall["status"]]
        lines.append(
            f"Общий: {fmt_amount(overall['spent'])} из "
            f"{fmt_amount(overall['limit'])} ({overall['percent']}%) · "
            f"{_remaining_text(overall['remaining'])} · {status}"
        )
    lines.append(
        f"{'Расходы выбранных категорий' if report['categories'] else 'Расходы за неделю'}: "
        f"{fmt_amount(report['selected_spent'])}"
    )
    for category in report["categories"]:
        lines.append(
            f"• {category['category']}: {fmt_amount(category['spent'])} из "
            f"{fmt_amount(category['limit'])} · "
            f"{_remaining_text(category['remaining'])}"
        )
    return "\n".join(lines)


def _threshold_text(report: dict, events: list[str]) -> str:
    labels = ["80%" if kind == "threshold_80" else "100%" for kind in events]
    if len(labels) == 1:
        event_text = f"порог {labels[0]}"
    else:
        event_text = "пороги " + " и ".join(labels)
    overall = report["overall"]
    return (
        f"⚠️ Недельный бюджет: достигнут {event_text}. "
        f"Потрачено {fmt_amount(overall['spent'])} из "
        f"{fmt_amount(overall['limit'])} ({overall['percent']}%)."
    )


async def evening_budget_lines(today: date) -> list[str]:
    report = await get_budget(today=today)
    if not report.get("configured"):
        return []
    lines = []
    events = await _claim_thresholds(report)
    if events:
        lines.append(_threshold_text(report, events))

    overall = report.get("overall")
    if (
        today.weekday() == 6
        and overall is not None
        and overall["remaining"] > Decimal("1000.00")
        and await queries.claim_weekly_budget_notification(
            report["week_start"], "saving_1000"
        )
    ):
        lines.append(
            f"🎉 На этой неделе удалось сэкономить: "
            f"{fmt_amount(overall['remaining'])} остатка общего бюджета."
        )
    return lines


async def notify_after_new_expense(bot: Bot | None, op_date: date) -> None:
    """Проверяет пороги после новой записи, не влияя на сохранение операции."""
    if bot is None:
        return
    today = effective_today()
    current_start, current_end = week_bounds(today)
    if not current_start <= op_date <= current_end:
        return
    try:
        report = await get_budget(today=today)
        events = await _claim_thresholds(report)
        if not events:
            return
        await bot.send_message(
            ALLOWED_USER_ID,
            _threshold_text(report, events),
            reply_markup=web_app_markup("Открыть бюджет"),
        )
    except Exception:
        # Claim остаётся в БД: неопределённая ошибка Telegram не должна
        # запускать автоматическую повторную отправку того же события.
        logger.exception("Не удалось отправить уведомление недельного бюджета")
