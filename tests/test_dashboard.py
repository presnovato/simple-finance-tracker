from decimal import Decimal

from finance_bot.core.dashboard import (fmt_amount, render_bar,
                                        render_categories, render_comparison,
                                        render_balance,
                                        render_subscription_line)


def test_fmt_amount():
    assert fmt_amount(Decimal("1234567.50")) == "1 234 568₽"
    assert fmt_amount(Decimal("450")) == "450₽"
    assert fmt_amount(0) == "0₽"


def test_render_bar():
    assert render_bar(Decimal(100), Decimal(100)) == "▓▓▓▓▓▓▓▓"
    assert render_bar(Decimal(0), Decimal(100)) == "░░░░░░░░"
    # маленькое, но ненулевое значение видно минимум одним сегментом
    assert render_bar(Decimal(1), Decimal(1000)).startswith("▓")
    assert render_bar(Decimal(50), Decimal(0)) == "░░░░░░░░"


def test_render_categories_sorted_input():
    rows = [
        {"category": "Продукты", "total": Decimal(10000)},
        {"category": "Кафе/Досуг", "total": Decimal(2500)},
    ]
    out = render_categories(rows)
    lines = out.splitlines()
    assert lines[0].startswith("Продукты")
    assert "10 000₽" in lines[0]
    assert "2 500₽" in lines[1]


def test_render_categories_empty():
    assert render_categories([]) == "Расходов нет."


def test_render_comparison():
    assert "+11%" in render_comparison(Decimal(42300), Decimal(38100))
    assert render_comparison(Decimal(100), Decimal(0)) == ""


def test_render_subscription_line():
    assert render_subscription_line(Decimal("2398")) == "Подписки: 2 398 ₽/мес"


def test_render_balance_labels_delta_as_period():
    rendered = render_balance(Decimal("100"), Decimal("30"))
    assert "Дельта за период" in rendered
    assert "Дельта за месяц" not in rendered
