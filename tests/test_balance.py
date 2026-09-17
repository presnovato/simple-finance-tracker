from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from finance_bot.core.balance import (calculate_cash_on_hand,
                                      calculate_period_balance,
                                      format_cash_amount, movement_totals,
                                      parse_anchor_amount)


def _ts(day: date, hour: int) -> datetime:
    return datetime(day.year, day.month, day.day, hour, tzinfo=timezone.utc)


def test_no_anchor_hides_cash_balance():
    assert calculate_cash_on_hand(None, Decimal("100"), Decimal("50")) is None


def test_anchor_today_applies_movements():
    assert calculate_cash_on_hand(
        Decimal("100000"), Decimal("500"), Decimal("1000")
    ) == Decimal("99500.00")


def test_movements_before_anchor_deleted_and_transfers_are_ignored():
    anchor_date = date(2026, 7, 20)
    anchor_ts = _ts(anchor_date, 12)
    totals = movement_totals([
        {"op_date": date(2026, 7, 19), "type": "расход", "amount": "900",
         "created_at": _ts(date(2026, 7, 19), 10)},
        {"op_date": date(2026, 7, 20), "type": "расход", "amount": "500",
         "created_at": _ts(anchor_date, 18)},
        {"op_date": date(2026, 7, 21), "type": "доход", "amount": "200",
         "created_at": _ts(date(2026, 7, 21), 9)},
        {"op_date": date(2026, 7, 21), "type": "перевод", "amount": "1000",
         "created_at": _ts(date(2026, 7, 21), 9)},
        {"op_date": date(2026, 7, 21), "type": "расход", "amount": "50",
         "created_at": _ts(date(2026, 7, 21), 10),
         "deleted_at": "2026-07-21T10:00:00Z"},
    ], anchor_date, anchor_ts)
    assert totals == {
        "income": Decimal("200"),
        "expense": Decimal("500"),
        "transfer_in": Decimal("0"),
        "transfer_out": Decimal("1000"),
        "movement_count": 3,
    }
    assert calculate_cash_on_hand(
        Decimal("100000"), totals["income"], totals["expense"]
    ) == Decimal("99700.00")


def test_same_day_movements_before_anchor_are_not_reapplied():
    """Регресс: трата, записанная утром, не должна вычитаться из суммы,
    которую я назвал вечером — я её уже посчитал, когда пересчитывал наличные."""
    anchor_date = date(2026, 7, 20)
    anchor_ts = _ts(anchor_date, 21)
    totals = movement_totals([
        {"op_date": anchor_date, "type": "расход", "amount": "500",
         "created_at": _ts(anchor_date, 9)},
        {"op_date": anchor_date, "type": "расход", "amount": "300",
         "created_at": _ts(anchor_date, 14)},
    ], anchor_date, anchor_ts)
    assert totals == {
        "income": Decimal("0"),
        "expense": Decimal("0"),
        "transfer_in": Decimal("0"),
        "transfer_out": Decimal("0"),
        "movement_count": 0,
    }
    assert calculate_cash_on_hand(
        Decimal("10000"), totals["income"], totals["expense"]
    ) == Decimal("10000.00")


def test_backdated_receipt_does_not_touch_anchor():
    """Чек позавчерашней датой, занесённый после якоря: деньги ушли ещё
    до пересчёта, значит в названной сумме их уже нет."""
    anchor_date = date(2026, 7, 20)
    anchor_ts = _ts(anchor_date, 12)
    totals = movement_totals([
        {"op_date": date(2026, 7, 18), "type": "расход", "amount": "700",
         "created_at": _ts(date(2026, 7, 21), 11)},
    ], anchor_date, anchor_ts)
    assert totals["expense"] == Decimal("0")
    assert totals["movement_count"] == 0


def test_anchor_amount_parser_and_formatter():
    assert parse_anchor_amount("123 456,78") == Decimal("123456.78")
    assert parse_anchor_amount("0") == Decimal("0.00")
    assert format_cash_amount(Decimal("123456.78")) == "123 456,78 ₽"
    assert format_cash_amount(Decimal("5256.78"), show_plus=True) == "+5 256,78 ₽"
    with pytest.raises(ValueError):
        parse_anchor_amount("не число")


def test_transfer_directions_change_balance_except_self():
    assert calculate_period_balance(
        Decimal("100"), Decimal("30"), Decimal("25"), Decimal("40")
    ) == Decimal("55.00")
    assert calculate_period_balance(
        Decimal("100"), Decimal("30"), Decimal("0"), Decimal("0")
    ) == Decimal("70.00")


def test_debt_transfers_stay_in_cash_but_can_be_excluded_from_delta():
    operations = [{
        "op_date": date(2026, 7, 21),
        "type": "перевод",
        "amount": "10000",
        "transfer_direction": "out",
        "debt_related": True,
        "created_at": _ts(date(2026, 7, 21), 9),
    }]
    cash = movement_totals(
        operations, date(2026, 7, 20), _ts(date(2026, 7, 20), 12)
    )
    delta = movement_totals(
        operations, date(2026, 7, 20), _ts(date(2026, 7, 20), 12),
        exclude_debt_transfers=True,
    )
    assert cash["transfer_out"] == Decimal("10000")
    assert cash["movement_count"] == 1
    assert delta["transfer_out"] == Decimal("0")
    assert delta["movement_count"] == 0
