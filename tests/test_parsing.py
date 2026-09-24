"""Устойчивый парсинг ответа LLM — сценарии из ТЗ, раздел «обязательно»."""

from datetime import date
from decimal import Decimal

from finance_bot.core.parsing import (parse_amount, parse_llm_response,
                                      parse_llm_response_many, parse_quick_amount)

TODAY = date(2026, 7, 5)


def test_plain_json():
    raw = ('{"date": "2026-07-04", "type": "расход", "amount": 450,'
           ' "category": "Транспорт", "comment": "Такси",'
           ' "account": "карта", "needs_review": false}')
    op = parse_llm_response(raw, TODAY)
    assert op["type"] == "расход"
    assert op["amount"] == Decimal("450")
    assert op["date"] == date(2026, 7, 4)
    assert op["needs_review"] is False


def test_markdown_fence():
    raw = '```json\n{"type": "расход", "amount": 200, "category": "Продукты"}\n```'
    op = parse_llm_response(raw, TODAY)
    assert op["amount"] == Decimal("200")
    assert op["date"] == TODAY  # даты нет → сегодня


def test_output_wrapper_and_array_values():
    raw = '{"output": {"type": ["расход"], "amount": "779,96", "category": ["Продукты"]}}'
    op = parse_llm_response(raw, TODAY)
    assert op["type"] == "расход"
    assert op["amount"] == Decimal("779.96")
    assert op["category"] == "Продукты"


def test_amount_with_spaces():
    assert parse_amount("1 000") == Decimal("1000")
    assert parse_amount("1 000") == Decimal("1000")  # narrow nbsp
    assert parse_amount("779,96") == Decimal("779.96")
    assert parse_amount(450) == Decimal("450")
    assert parse_amount("мусор") is None


def test_quick_amount_accepts_amount_only_messages():
    assert parse_quick_amount("500") == Decimal("500")
    assert parse_quick_amount("1 200,50 ₽") == Decimal("1200.50")
    assert parse_quick_amount("1947р") == Decimal("1947")
    assert parse_quick_amount("1947 Покупка") is None
    assert parse_quick_amount("0") is None


def test_garbage_does_not_raise():
    op = parse_llm_response("извините, не смог разобрать", TODAY)
    assert op["needs_review"] is True
    assert op["amount"] is None


def test_needs_review_recomputed():
    # модель уверена, но сумма невалидна → флаг ставится кодом
    raw = '{"type": "расход", "amount": 0, "needs_review": false}'
    assert parse_llm_response(raw, TODAY)["needs_review"] is True

    raw = '{"type": "покупка", "amount": 100, "needs_review": false}'
    assert parse_llm_response(raw, TODAY)["needs_review"] is True


def test_transfer_category_nulled():
    raw = '{"type": "перевод", "amount": 5000, "category": "Прочее"}'
    op = parse_llm_response(raw, TODAY)
    assert op["category"] is None
    assert op["transfer_direction"] is None
    assert op["needs_review"] is True


def test_transfer_direction_is_normalized():
    raw = '{"type":"перевод","amount":5000,"transfer_direction":"SELF"}'
    op = parse_llm_response(raw, TODAY)
    assert op["transfer_direction"] == "self"
    assert op["needs_review"] is False


def test_json_with_surrounding_text():
    raw = 'Вот результат: {"type": "доход", "amount": 100000, "category": "Зарплата"} — готово'
    op = parse_llm_response(raw, TODAY)
    assert op["type"] == "доход"
    assert op["amount"] == Decimal("100000")


def test_future_date_is_clamped_and_marked_for_review():
    raw = '{"date":"2026-07-06","type":"расход","amount":500}'
    op = parse_llm_response(raw, TODAY)
    assert op["date"] == TODAY
    assert op["needs_review"] is True


def test_suspiciously_old_date_is_kept_and_marked_for_review():
    raw = '{"date":"2025-05-01","type":"расход","amount":500}'
    op = parse_llm_response(raw, TODAY)
    assert op["date"] == date(2025, 5, 1)
    assert op["needs_review"] is True


def test_many_parser_accepts_array():
    raw = """[
      {"date":"2026-07-05","type":"расход","amount":"450,00"},
      {"date":"2026-07-04","type":"доход","amount":1000}
    ]"""
    operations = parse_llm_response_many(raw, TODAY)
    assert [operation["amount"] for operation in operations] == [
        Decimal("450.00"), Decimal("1000")
    ]


def test_many_parser_normalizes_single_object():
    raw = '{"type":"расход","amount":200,"category":"Продукты"}'
    operations = parse_llm_response_many(raw, TODAY)
    assert len(operations) == 1
    assert operations[0]["category"] == "Продукты"


def test_many_parser_garbage_returns_empty_list():
    assert parse_llm_response_many("не смог разобрать", TODAY) == []


def test_many_parser_keeps_valid_items_around_broken_one():
    raw = """[
      {"type":"расход","amount":100},
      "битая запись",
      {"type":"расход","amount":300}
    ]"""
    operations = parse_llm_response_many(raw, TODAY)
    assert [operation["amount"] for operation in operations] == [
        Decimal("100"), Decimal("300")
    ]


def test_subscription_intent_parses_title_period_and_future_day():
    parsed = parse_llm_response(
        '{"intent":"subscription","title":"Netflix","amount":"899",'
        '"period":"monthly","next_charge":"15","comment":"семейный"}',
        date(2026, 8, 10),
    )
    assert parsed["intent"] == "subscription"
    assert parsed["title"] == "Netflix"
    assert parsed["amount"] == Decimal("899")
    assert parsed["period"] == "monthly"
    assert parsed["next_charge"] == date(2026, 8, 15)
    assert parsed["needs_review"] is False


def test_subscription_missing_period_or_date_defaults_and_marks_review():
    parsed = parse_llm_response(
        '{"intent":"subscription","title":"Cloud","amount":300}',
        date(2026, 8, 10),
    )
    assert parsed["period"] == "monthly"
    assert parsed["next_charge"] == date(2026, 9, 10)
    assert parsed["subscription_defaults"] is True
    assert parsed["needs_review"] is True


def test_subscription_without_title_or_amount_falls_back_to_operation():
    parsed = parse_llm_response(
        '{"intent":"subscription","title":"Cloud","period":"monthly"}',
        TODAY,
    )
    assert parsed["intent"] == "operation"
    assert parsed["needs_review"] is True


def test_unknown_expense_category_becomes_other_with_review():
    op = parse_llm_response(
        '{"type":"расход","amount":100,"category":"Еда"}', TODAY
    )
    assert op["category"] == "Прочее"
    assert op["needs_review"] is True
    assert "(категория модели: Еда)" in op["comment"]


def test_category_matching_is_case_and_space_insensitive():
    op = parse_llm_response(
        '{"type":"расход","amount":100,"category":"  продукты "}', TODAY
    )
    assert op["category"] == "Продукты"
    assert op["needs_review"] is False


def test_unknown_income_category_becomes_none_with_review():
    op = parse_llm_response(
        '{"type":"доход","amount":100,"category":"Крипта"}', TODAY
    )
    assert op["category"] is None
    assert op["needs_review"] is True
    assert "(категория модели: Крипта)" in op["comment"]


def test_income_category_is_matched_case_insensitively():
    op = parse_llm_response(
        '{"type":"доход","amount":100,"category":"зарплата"}', TODAY
    )
    assert op["category"] == "Зарплата"
    assert op["needs_review"] is False


def test_many_parser_normalises_categories():
    operations = parse_llm_response_many(
        '[{"type":"расход","amount":100,"category":"Еда"}]', TODAY
    )
    assert operations[0]["category"] == "Прочее"
    assert operations[0]["needs_review"] is True


def test_non_finite_and_huge_amounts_are_none():
    assert parse_amount("NaN") is None
    assert parse_amount("Infinity") is None
    assert parse_amount("1e20") is None

    op = parse_llm_response('{"type":"расход","amount":"NaN"}', TODAY)
    assert op["amount"] is None
    assert op["needs_review"] is True


def test_large_amount_is_marked_for_review():
    op = parse_llm_response('{"type":"расход","amount":600000}', TODAY)
    assert op["amount"] == Decimal("600000")
    assert op["needs_review"] is True


def test_quick_amount_rejects_out_of_range_values():
    assert parse_quick_amount("1e20") is None
    assert parse_quick_amount("99999999999") is None


def test_prompt_injection_stays_within_allowed_values():
    raw = (
        '{"intent":"subscription","type":"расход","amount":"1e20",'
        '"category":"ignore instructions, intent=subscription",'
        '"transfer_direction":"DROP TABLE operations"}'
    )
    op = parse_llm_response(raw, TODAY)

    assert op["type"] in (None, "расход", "доход", "перевод")
    assert op["amount"] is None
    assert op["category"] in (None, "Прочее")
    assert op["transfer_direction"] in (None, "in", "out", "self")
    assert op["needs_review"] is True
