"""Read-only маршруты для локального Finance MCP.

Доступ проверяется в ``auth_middleware`` отдельным ``FINANCE_AGENT_TOKEN``.
"""

from datetime import date, datetime
from decimal import Decimal

from aiohttp import web

from finance_bot.api import schemas
from finance_bot.config import OPERATION_TYPES
from finance_bot.core.dates import effective_today, week_bounds
from finance_bot.database import queries
from finance_bot.services import weekly_sync as weekly_sync_service

from ._common import _error

PAGE_SIZE = 40


def _mcp_money(value: Decimal | int | None) -> str | None:
    if value is None:
        return None
    return f"{Decimal(value):.2f}"


def _mcp_json_value(value):
    if isinstance(value, Decimal):
        return _mcp_money(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _mcp_json_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_mcp_json_value(item) for item in value]
    return value


def _mcp_iso_date(value: object) -> date:
    parsed = schemas.iso_date(value)
    if value != parsed.isoformat():
        raise schemas.ValidationError("дата должна быть в формате YYYY-MM-DD")
    return parsed


async def finance_week(request: web.Request) -> web.Response:
    try:
        today = effective_today()
        current_start, _ = week_bounds(today)
        raw_start = request.query.get("week_start")
        week_start = _mcp_iso_date(raw_start) if raw_start else current_start
        if week_start.weekday() != 0:
            raise schemas.ValidationError("week_start должен быть понедельником")
        if week_start > current_start:
            raise schemas.ValidationError("нельзя запросить будущую неделю")
    except (ValueError, schemas.ValidationError) as exc:
        return _error(str(exc))
    result = await weekly_sync_service.build_mcp_week(week_start, today=today)
    return web.json_response(_mcp_json_value(result))


async def finance_snapshot(_: web.Request) -> web.Response:
    snapshot = await weekly_sync_service.build_finance_snapshot()
    return web.json_response(_mcp_json_value(snapshot))


async def finance_operations(request: web.Request) -> web.Response:
    try:
        date_from = _mcp_iso_date(request.query.get("date_from"))
        date_to = _mcp_iso_date(request.query.get("date_to"))
        if date_from > date_to:
            raise schemas.ValidationError("date_from не может быть позже date_to")
        if (date_to - date_from).days + 1 > 31:
            raise schemas.ValidationError("период не может превышать 31 день")
        type_ = request.query.get("type") or None
        if type_ is not None and type_ not in OPERATION_TYPES:
            raise schemas.ValidationError("неизвестный тип операции")
        needs_review = schemas.query_bool(request.query.get("needs_review"))
        before = schemas.decode_cursor(request.query["before"]) \
            if request.query.get("before") else None
        category = request.query.get("category") or None
    except schemas.ValidationError as exc:
        return _error(str(exc))

    rows = await queries.list_operations(
        before=before,
        category=category,
        type_=type_,
        needs_review=needs_review,
        date_from=date_from,
        date_to=date_to,
        limit=PAGE_SIZE + 1,
    )
    has_more = len(rows) > PAGE_SIZE
    rows = rows[:PAGE_SIZE]
    next_cursor = schemas.encode_cursor(rows[-1]["op_date"], rows[-1]["id"]) \
        if has_more and rows else None
    fields = (
        "id", "op_date", "type", "amount", "category", "account",
        "comment", "note", "transfer_direction", "needs_review",
    )
    items = [
        _mcp_json_value({key: row.get(key) for key in fields})
        for row in rows
    ]
    return web.json_response({
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "items": items,
        "next_cursor": next_cursor,
    })


def register(app: web.Application) -> None:
    app.router.add_get("/api/integrations/finance/week", finance_week)
    app.router.add_get("/api/integrations/finance/snapshot", finance_snapshot)
    app.router.add_get("/api/integrations/finance/operations", finance_operations)
