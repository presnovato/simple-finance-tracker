"""Недельный бюджет."""

from aiohttp import web

from finance_bot.api import schemas
from finance_bot.core.dates import effective_today
from finance_bot.services import budget as budget_service

from ._common import _error


def _budget_json(report: dict) -> dict:
    result = {
        "configured": report["configured"],
        "week_start": report["week_start"].isoformat(),
        "week_end": report["week_end"].isoformat(),
        "is_current": report["is_current"],
        "previous_week_start": (
            report["previous_week_start"].isoformat()
            if report.get("previous_week_start") else None
        ),
        "next_week_start": (
            report["next_week_start"].isoformat()
            if report.get("next_week_start") else None
        ),
    }
    if not report["configured"]:
        return result
    result.update({
        "selected_spent": schemas.money_string(report["selected_spent"]),
        "category_limits_total": schemas.money_string(
            report["category_limits_total"]
        ),
        "overall": (
            {
                "limit": schemas.money_string(report["overall"]["limit"]),
                "spent": schemas.money_string(report["overall"]["spent"]),
                "remaining": schemas.money_string(
                    report["overall"]["remaining"]
                ),
                "percent": schemas.money_string(report["overall"]["percent"]),
                "status": report["overall"]["status"],
            }
            if report.get("overall") is not None else None
        ),
        "categories": [
            {
                "category": item["category"],
                "limit": (
                    schemas.money_string(item["limit"])
                    if item["limit"] is not None else None
                ),
                "spent": schemas.money_string(item["spent"]),
                "remaining": (
                    schemas.money_string(item["remaining"])
                    if item["remaining"] is not None else None
                ),
                "percent": (
                    schemas.money_string(item["percent"])
                    if item["percent"] is not None else None
                ),
                "status": item["status"],
            }
            for item in report["categories"]
        ],
    })
    return result


def _budget_settings_json(settings: dict) -> dict:
    return {
        "overall_limit": (
            schemas.money_string(settings["overall_limit"])
            if settings.get("overall_limit") is not None else None
        ),
        "categories": [
            {
                "category": item["category"],
                "limit": (
                    schemas.money_string(item["limit"])
                    if item["limit"] is not None else None
                ),
            }
            for item in settings.get("categories", [])
        ],
    }


async def budget(request: web.Request) -> web.Response:
    try:
        today = effective_today()
        week_start = (
            schemas.budget_week_start(
                request.query["week_start"], today
            )
            if request.query.get("week_start") else None
        )
        report = await budget_service.get_budget(week_start, today=today)
    except (ValueError, schemas.ValidationError) as exc:
        return _error(str(exc))
    return web.json_response(_budget_json(report))


async def budget_settings(request: web.Request) -> web.Response:
    return web.json_response(_budget_settings_json(
        await budget_service.get_settings()
    ))


async def update_budget_settings(request: web.Request) -> web.Response:
    try:
        fields = schemas.budget_settings(await request.json())
    except schemas.ValidationError as exc:
        return _error(str(exc))
    except (web.HTTPBadRequest, TypeError):
        return _error("некорректный JSON")
    settings = await budget_service.save_settings(
        fields["overall_limit"], fields["categories"], today=effective_today()
    )
    return web.json_response(_budget_settings_json(settings))


def register(app: web.Application) -> None:
    app.router.add_get("/api/budget", budget)
    app.router.add_get("/api/budget/settings", budget_settings)
    app.router.add_put("/api/budget/settings", update_budget_settings)
