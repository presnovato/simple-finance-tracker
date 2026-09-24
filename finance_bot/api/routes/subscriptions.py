"""Подписки."""

from aiohttp import web

from finance_bot.api import schemas
from finance_bot.api.context import BUDGET_BOT_KEY
from finance_bot.core.dates import effective_today, month_bounds
from finance_bot.core.subscriptions import (
    due_subscriptions,
    monthly_cost,
    next_charge_after,
    share_of_expenses,
    upcoming_charges,
    yearly_cost,
)
from finance_bot.database import queries
from finance_bot.services import budget as budget_service

from ._common import _error


async def subscriptions(request: web.Request) -> web.Response:
    status = request.query.get("status") or "active"
    if status not in {"active", "cancelled"}:
        return _error("неизвестный статус подписки")
    rows = await queries.list_subscriptions(status)
    if status == "cancelled":
        return web.json_response({
            "items": [
                schemas.subscription_json(row, due=False) for row in rows
            ],
            "monthly_cost": None,
            "yearly_cost": None,
            "month_expenses": None,
            "share_percent": None,
            "upcoming": [],
        })

    today = effective_today()
    due_ids = {row["id"] for row in due_subscriptions(rows, today)}
    month_start, month_end = month_bounds(today)
    month_total = await queries.totals(month_start, min(month_end, today))
    monthly = monthly_cost(rows)
    share = share_of_expenses(monthly, month_total["expense"])
    return web.json_response({
        "items": [
            schemas.subscription_json(row, due=row["id"] in due_ids)
            for row in rows
        ],
        "monthly_cost": schemas.money_string(monthly),
        "yearly_cost": schemas.money_string(yearly_cost(rows)),
        "month_expenses": schemas.money_string(month_total["expense"]),
        "share_percent": f"{share:.1f}" if share is not None else None,
        "upcoming": [
            {
                "subscription_id": charge["subscription_id"],
                "title": charge["title"],
                "amount": schemas.money_string(charge["amount"]),
                "charge_date": charge["charge_date"].isoformat(),
            }
            for charge in upcoming_charges(rows, today)
        ],
    })


async def create_subscription(request: web.Request) -> web.Response:
    try:
        fields = schemas.subscription_create(
            await request.json(), effective_today()
        )
    except schemas.ValidationError as exc:
        return _error(str(exc))
    except (web.HTTPBadRequest, TypeError):
        return _error("некорректный JSON")
    subscription = await queries.insert_subscription(**fields)
    return web.json_response(schemas.subscription_json(subscription), status=201)


async def patch_subscription(request: web.Request) -> web.Response:
    try:
        subscription_id = int(request.match_info["id"])
        current = await queries.get_subscription(subscription_id)
        if current is None:
            return _error("подписка не найдена", 404)
        fields = schemas.subscription_patch(await request.json(), current)
    except (ValueError, schemas.ValidationError) as exc:
        return _error(str(exc))
    except (web.HTTPBadRequest, TypeError):
        return _error("некорректный JSON")
    if (
        fields.get("status") == "active"
        and current.get("status") == "cancelled"
    ):
        next_charge = fields.get("next_charge", current["next_charge"])
        while next_charge <= effective_today():
            next_charge = next_charge_after(next_charge, current["period"])
        fields["next_charge"] = next_charge
    updated = await queries.patch_subscription(subscription_id, fields)
    if updated is None:
        return _error("подписка не найдена", 404)
    return web.json_response(schemas.subscription_json(updated))


async def delete_subscription(request: web.Request) -> web.Response:
    try:
        subscription_id = int(request.match_info["id"])
    except ValueError:
        return _error("некорректный id")
    cancelled = await queries.cancel_subscription(subscription_id)
    if cancelled is None:
        return _error("подписка не найдена", 404)
    return web.json_response(schemas.subscription_json(cancelled))


async def charge_subscription(request: web.Request) -> web.Response:
    try:
        subscription_id = int(request.match_info["id"])
        fields = schemas.charge_request(await request.json())
    except (ValueError, schemas.ValidationError) as exc:
        return _error(str(exc))
    except (web.HTTPBadRequest, TypeError):
        return _error("некорректный JSON")

    result = await queries.charge_subscription(
        subscription_id,
        confirmed=fields["confirmed"],
        op_date=fields["op_date"],
    )
    if result is None:
        return _error("подписка не найдена", 404)
    if result.get("operation_created"):
        await budget_service.notify_after_new_expense(
            request.app.get(BUDGET_BOT_KEY), result["operation_date"]
        )
    return web.json_response({
        "subscription": schemas.subscription_json(
            result["subscription"], due=False
        ),
        "operation_id": result["operation_id"],
    })


def register(app: web.Application) -> None:
    app.router.add_get("/api/subscriptions", subscriptions)
    app.router.add_post("/api/subscriptions", create_subscription)
    app.router.add_patch("/api/subscriptions/{id}", patch_subscription)
    app.router.add_delete("/api/subscriptions/{id}", delete_subscription)
    app.router.add_post("/api/subscriptions/{id}/charge", charge_subscription)
