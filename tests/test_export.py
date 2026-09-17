from datetime import date
from decimal import Decimal

from finance_bot.services.export import generate_csv, generate_md, render_finance_snapshot


def _operations():
    return [{
        "op_date": date(2026, 8, 8),
        "type": "расход",
        "amount": Decimal("1234.50"),
        "category": "Кафе;досуг",
        "comment": "строка 1\nстрока 2",
        "note": "вернуть",
        "transfer_direction": None,
        "needs_review": True,
    }]


def test_generate_csv_is_excel_friendly_and_keeps_decimal_text():
    content = generate_csv(_operations())

    assert content.startswith(b"\xef\xbb\xbf")
    text = content.decode("utf-8-sig")
    assert "Дата;Тип;Сумма;Категория" in text
    assert "1234.50" in text
    assert '"Кафе;досуг"' in text
    assert '"строка 1\nстрока 2"' in text
    assert "Да" in text


def test_generate_empty_csv_and_grouped_markdown():
    assert len(generate_csv([])) > 0
    markdown = generate_md(_operations()).decode("utf-8")

    assert "# Экспорт операций" in markdown
    assert "## ФИНАНСЫ" in markdown
    assert "Доходы за период: 0.00 ₽" in markdown
    assert "Расходы за период: 1234.50 ₽" in markdown
    assert "## 08.08.2026" in markdown
    assert "Итого за день" in markdown
    assert "1234.50 ₽" in markdown


def test_markdown_contains_current_money_and_debt_snapshot():
    snapshot = {
        "as_of": date(2026, 9, 9),
        "cash": {
            "total": Decimal("99500"),
            "accounts": None,
            "free": None,
            "reserved": None,
            "accounts_unavailable_reason": "отдельные остатки не хранятся",
            "free_unavailable_reason": "резервирование не хранится",
            "reserved_unavailable_reason": "резервирование не хранится",
        },
        "debts": [{
            "kind": "credit",
            "id": 1,
            "name": "Ремонт",
            "creditor": "Банк",
            "contract_ref": "42",
            "balance": Decimal("70000"),
            "principal": Decimal("100000"),
            "paid_amount": Decimal("30000"),
            "paid_percent": Decimal("30"),
            "opened_at": date(2025, 3, 12),
            "next_payment_amount": Decimal("5000"),
            "next_payment_date": date(2026, 9, 15),
            "rate": Decimal("19.9"),
        }],
        "totals": {
            "liability_balance": Decimal("70000"),
            "next_payment_amount": Decimal("5000"),
            "next_payment_unknown_count": 0,
            "next_payment_date_unknown_count": 0,
        },
        "previous_total_debt": None,
        "history_unavailable_reason": "история snapshot Weekly Sync не хранится",
    }

    markdown = generate_md(_operations(), snapshot).decode("utf-8")

    assert "### Текущие деньги (на 09.09.2026)" in markdown
    assert "- Всего: 99500.00 ₽" in markdown
    assert "По счетам/кошелькам: нет данных" in markdown
    assert "Свободно: нет данных" in markdown
    assert "Ремонт (Банк; договор 42; id 1)" in markdown
    assert "остаток 70000.00 ₽" in markdown
    assert "погашено 30000.00 ₽ (30.00%)" in markdown
    assert "ближайший платёж 5000.00 ₽ до 15.09.2026" in markdown
    assert "ставка 19.90%" in markdown
    assert "Общая текущая задолженность: 70000.00 ₽" in markdown
    assert "Общая сумма ближайших обязательных платежей: 5000.00 ₽" in markdown
    assert "Изменение с прошлого Weekly Sync: нет данных" in markdown


def test_snapshot_marks_unknown_values_without_inventing_zeros():
    rendered = render_finance_snapshot({
        "cash": {
            "total": None,
            "accounts": None,
            "free": None,
            "reserved": None,
            "total_unavailable_reason": "не задан якорь",
            "accounts_unavailable_reason": "остатки по счетам не хранятся",
            "free_unavailable_reason": "резервы не хранятся",
            "reserved_unavailable_reason": "резервы не хранятся",
        },
        "debts": [{
            "kind": "credit",
            "id": 2,
            "name": "Кредит",
            "balance": None,
            "principal": None,
            "paid_amount": None,
            "paid_percent": None,
            "opened_at": None,
            "next_payment_amount": None,
            "next_payment_date": None,
            "rate": None,
        }],
        "totals": {
            "liability_balance": None,
            "next_payment_amount": None,
            "next_payment_unknown_count": 1,
            "next_payment_date_unknown_count": 0,
        },
        "previous_total_debt": None,
        "history_unavailable_reason": "нет истории",
    })

    assert "Всего: нет данных — не задан якорь" in rendered
    assert "остаток нет данных" in rendered
    assert "первоначально нет данных" in rendered
    assert "ставка: нет данных" in rendered
    assert "Общая текущая задолженность: нет данных" in rendered
    assert "Общая сумма ближайших обязательных платежей: нет данных" in rendered


def test_snapshot_handles_no_active_debts_and_can_render_change():
    rendered = render_finance_snapshot({
        "cash": {"total": Decimal("10")},
        "debts": [],
        "totals": {
            "liability_balance": Decimal("100"),
            "next_payment_amount": Decimal("0"),
        },
        "previous_total_debt": Decimal("125"),
    })

    assert "Активных долгов нет" in rendered
    assert "Общая текущая задолженность: 100.00 ₽" in rendered
    assert "Общая сумма ближайших обязательных платежей: 0.00 ₽" in rendered
    assert "Изменение с прошлого Weekly Sync: -25.00 ₽" in rendered
