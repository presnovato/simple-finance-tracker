"""Роуты TMA API по доменам."""

from aiohttp import web

from . import (
    analytics,
    balance,
    budget,
    categories,
    crypto,
    debts,
    integrations,
    operations,
    personal_debts,
    subscriptions,
    summary,
    upcoming,
)


def setup_routes(app: web.Application) -> None:
    integrations.register(app)
    summary.register(app)
    upcoming.register(app)
    analytics.register(app)
    budget.register(app)
    operations.register(app)
    crypto.register(app)
    categories.register(app)
    balance.register(app)
    debts.register(app)
    personal_debts.register(app)
    subscriptions.register(app)
