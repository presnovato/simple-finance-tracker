from datetime import date, datetime

from finance_bot.core.dates import (TZ, effective_today, month_bounds,
                                    resolve_relative_date,
                                    same_day_prev_month,
                                    split_explicit_date_prefix)


def _at(y, m, d, hh, mm=0):
    return TZ.localize(datetime(y, m, d, hh, mm))


def test_night_belongs_to_yesterday():
    assert effective_today(_at(2026, 7, 5, 0, 30)) == date(2026, 7, 4)
    assert effective_today(_at(2026, 7, 5, 2, 59)) == date(2026, 7, 4)


def test_morning_is_today():
    assert effective_today(_at(2026, 7, 5, 3, 0)) == date(2026, 7, 5)
    assert effective_today(_at(2026, 7, 5, 12, 0)) == date(2026, 7, 5)


def test_month_bounds():
    assert month_bounds(date(2026, 7, 15)) == (date(2026, 7, 1), date(2026, 7, 31))
    assert month_bounds(date(2026, 7, 15), -1) == (date(2026, 6, 1), date(2026, 6, 30))
    # переход через год
    assert month_bounds(date(2026, 1, 10), -1) == (date(2025, 12, 1), date(2025, 12, 31))
    assert month_bounds(date(2025, 12, 10), 1) == (date(2026, 1, 1), date(2026, 1, 31))


def test_same_day_prev_month_clamps():
    assert same_day_prev_month(date(2026, 7, 15)) == date(2026, 6, 15)
    # 31 июля → 30 июня (у июня нет 31-го)
    assert same_day_prev_month(date(2026, 7, 31)) == date(2026, 6, 30)
    assert same_day_prev_month(date(2026, 3, 30)) == date(2026, 2, 28)


def test_resolve_relative_date_variants():
    today = date(2026, 7, 21)  # вторник
    assert resolve_relative_date("сегодня кофе 200", today) == today
    assert resolve_relative_date("вчера такси 500", today) == date(2026, 7, 20)
    assert resolve_relative_date("позавчера продукты", today) == date(2026, 7, 19)
    assert resolve_relative_date("3 дня назад обед", today) == date(2026, 7, 18)
    assert resolve_relative_date("в субботу кино", today) == date(2026, 7, 18)
    assert resolve_relative_date("5 июля такси", today) == date(2026, 7, 5)
    assert resolve_relative_date("31 декабря подарок", today) == date(2025, 12, 31)
    assert resolve_relative_date("завтра такси", today) == date(2026, 7, 22)
    assert resolve_relative_date("просто кофе 200", today) is None
    assert resolve_relative_date("кофе 12.07", today) is None


def test_explicit_date_prefix_is_removed_before_llm():
    today = date(2026, 7, 21)
    assert split_explicit_date_prefix("05.07 такси 500", today) == (
        date(2026, 7, 5), "такси 500"
    )
    assert split_explicit_date_prefix("2026-07-05 такси 500", today) == (
        date(2026, 7, 5), "такси 500"
    )
    assert split_explicit_date_prefix("такси 500", today) == (None, "такси 500")


def test_relative_date_uses_financial_today_before_boundary():
    today = effective_today(_at(2026, 7, 5, 2, 59))
    assert resolve_relative_date("вчера такси", today) == date(2026, 7, 3)
