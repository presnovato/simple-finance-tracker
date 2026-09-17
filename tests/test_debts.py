from datetime import date
from decimal import Decimal

from finance_bot.core.debts import (
    debt_curve,
    forecast_closure_date,
    match_records,
    may_contain_debt_intent,
    parse_debt_intent_response,
    progress_percent,
    repaid_principal,
)
from finance_bot.services import llm

TODAY = date(2026, 7, 21)


def test_classifier_gate_leaves_regular_capture_alone():
    assert may_contain_debt_intent("кофе 350") is False
    assert may_contain_debt_intent("платёж по кредиту Сбер 15000") is True
    assert may_contain_debt_intent("дал Васе 5000") is True
    assert may_contain_debt_intent("Вася вернул долг") is True


def test_parse_credit_payment_intent():
    parsed = parse_debt_intent_response(
        """```json
        {"intent":"debt_payment","amount":"15000,00","creditor":"Сбер",
         "date":"2026-07-20","comment":"Платёж по кредиту"}
        ```""",
        TODAY,
    )
    assert parsed["intent"] == "debt_payment"
    assert parsed["amount"] == Decimal("15000.00")
    assert parsed["creditor"] == "Сбер"
    assert parsed["date"] == date(2026, 7, 20)
    assert parsed["needs_review"] is False


def test_parse_personal_debt_and_invalid_response():
    parsed = parse_debt_intent_response(
        '{"intent":"personal_debt_new","amount":5000,"person":"Вася",'
        '"direction":"owed_to_me"}',
        TODAY,
    )
    assert parsed["person"] == "Вася"
    assert parsed["direction"] == "owed_to_me"
    assert parse_debt_intent_response("мусор", TODAY)["intent"] == "expense"


def test_name_matching_prefers_exact_then_substring():
    rows = [{"id": 1, "creditor": "Сбер"}, {"id": 2, "creditor": "Сбер Карта"}]
    assert [row["id"] for row in match_records("сбер", rows, "creditor")] == [1]
    assert [row["id"] for row in match_records("карта", rows, "creditor")] == [2]
    assert match_records("ВТБ", rows, "creditor") == []


def test_forecast_needs_two_payments_and_uses_decimal_average():
    assert forecast_closure_date(
        Decimal("30000"), [(date(2026, 6, 1), Decimal("10000"))], TODAY
    ) is None
    result = forecast_closure_date(
        Decimal("30000"),
        [
            (date(2026, 5, 1), Decimal("10000")),
            (date(2026, 6, 1), Decimal("10000")),
        ],
        TODAY,
    )
    assert result == date(2026, 10, 21)


def test_progress_and_monthly_curve():
    assert repaid_principal(Decimal("100000"), Decimal("75000")) == Decimal("25000")
    assert progress_percent(Decimal("100000"), Decimal("75000")) == Decimal("25.00")
    assert debt_curve(
        Decimal("100000"),
        [
            (date(2026, 5, 5), Decimal("10000")),
            (date(2026, 5, 25), Decimal("5000")),
            (date(2026, 6, 5), Decimal("10000")),
        ],
    ) == [
        {"month": "2026-05", "balance": Decimal("85000")},
        {"month": "2026-06", "balance": Decimal("75000")},
    ]


def test_prompts_fix_credit_payment_as_expense():
    extract_prompt = llm.build_extract_prompt(TODAY)
    intent_prompt = llm.build_debt_intent_prompt(TODAY)
    assert "платёж по банковскому кредиту/рассрочке = расход" in extract_prompt
    assert "категория «Долги»" in extract_prompt
    assert "personal_debt_repay" in intent_prompt
    assert "direction owed_to_me" in intent_prompt


async def test_regular_expense_does_not_call_debt_classifier(monkeypatch):
    async def fail(*_args, **_kwargs):
        raise AssertionError("обычная трата не должна вызывать классификатор")

    monkeypatch.setattr(llm, "_call", fail)
    result = await llm.extract_debt_intent("кофе 350", TODAY)
    assert result["intent"] == "expense"
