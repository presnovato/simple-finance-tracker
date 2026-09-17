from datetime import date
from decimal import Decimal

import pytest

from finance_bot.core.analytics import (average_daily, average_daily_expense,
                                         daily_series, parse_month,
                                         rolling_chart_bounds)


def test_parse_month_leap_year():
    assert parse_month("2024-02") == (date(2024, 2, 1), date(2024, 2, 29))
    with pytest.raises(ValueError):
        parse_month("2024-13")
    with pytest.raises(ValueError):
        parse_month("2024-2")


def test_daily_series_fills_missing_days():
    rows = [{"op_date": date(2026, 7, 2), "total": Decimal("150.25")}]
    assert daily_series(date(2026, 7, 1), date(2026, 7, 3), rows) == [
        {"op_date": date(2026, 7, 1), "expense": Decimal("0")},
        {"op_date": date(2026, 7, 2), "expense": Decimal("150.25")},
        {"op_date": date(2026, 7, 3), "expense": Decimal("0")},
    ]


def test_daily_series_supports_income_values():
    rows = [{"op_date": date(2026, 7, 2), "total": Decimal("450.00")}]

    assert daily_series(
        date(2026, 7, 1), date(2026, 7, 3), rows, value_key="income"
    ) == [
        {"op_date": date(2026, 7, 1), "income": Decimal("0")},
        {"op_date": date(2026, 7, 2), "income": Decimal("450.00")},
        {"op_date": date(2026, 7, 3), "income": Decimal("0")},
    ]


def test_average_daily_uses_only_nonzero_days():
    assert average_daily(Decimal("1500"), 15) == Decimal("100.00")
    assert average_daily_expense(Decimal("1500"), 15) == Decimal("100.00")
    assert average_daily_expense(Decimal("100"), 0) == Decimal("0.00")


def test_rolling_chart_window_starts_at_anchor_until_it_is_full():
    assert rolling_chart_bounds(date(2026, 9, 7), date(2026, 9, 10)) == (
        date(2026, 9, 7), date(2026, 10, 7)
    )
    assert rolling_chart_bounds(date(2026, 7, 1), date(2026, 8, 15)) == (
        date(2026, 7, 16), date(2026, 8, 15)
    )
