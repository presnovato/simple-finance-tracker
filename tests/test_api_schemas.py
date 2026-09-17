from datetime import date
from decimal import Decimal

import pytest

from finance_bot.api.schemas import (
    ValidationError,
    balance_anchor,
    crypto_overview_patch,
    debt_adjust,
    debt_create,
    debt_payment,
    debt_patch,
    decode_cursor,
    encode_cursor,
    money,
    operation_create,
    operation_patch,
    personal_debt_create,
    personal_debt_patch,
    charge_request,
    subscription_create,
    subscription_patch,
)


def test_money_requires_json_string_not_float():
    assert money("779,96".replace(",", ".")) == Decimal("779.96")
    with pytest.raises(ValidationError):
        money(12.5)
    with pytest.raises(ValidationError):
        money("0")


def test_balance_anchor_accepts_signed_amount_and_rejects_future_date():
    assert balance_anchor(
        {"amount": "-1500.50", "anchor_date": "2026-09-01"},
        date(2026, 9, 8),
    ) == {
        "amount": Decimal("-1500.50"),
        "anchor_date": date(2026, 9, 1),
    }
    with pytest.raises(ValidationError):
        balance_anchor({"amount": "100", "anchor_date": "2026-09-09"}, date(2026, 9, 8))
    with pytest.raises(ValidationError):
        balance_anchor({"amount": 100.5}, date(2026, 9, 8))


def test_crypto_overview_patch_accepts_only_boolean_visibility():
    assert crypto_overview_patch({"visible": False}) is False
    with pytest.raises(ValidationError):
        crypto_overview_patch({"visible": "false"})


def test_transfer_patch_clears_category_and_any_patch_is_validated():
    current = {"type": "расход"}
    assert operation_patch({"type": "перевод", "category": "Продукты"}, current) == {
        "type": "перевод", "category": None, "transfer_direction": "out",
    }
    assert operation_patch({"transfer_direction": "in"}, {"type": "перевод"}) == {
        "category": None, "transfer_direction": "in"
    }
    assert operation_patch({"transfer_direction": None}, {"type": "перевод"}) == {
        "category": None, "transfer_direction": None
    }
    with pytest.raises(ValidationError):
        operation_patch({"transfer_direction": "sideways"}, {"type": "перевод"})
    with pytest.raises(ValidationError):
        operation_patch({"needs_review": True}, current)


def test_operation_create_requires_manual_fields_and_normalizes_transfers():
    today = date(2026, 9, 17)
    assert operation_create({
        "type": "расход",
        "amount": "1250,50".replace(",", "."),
        "category": "Продукты",
        "op_date": "2026-09-16",
        "comment": "рынок",
    }, today) == {
        "type_": "расход",
        "amount": Decimal("1250.50"),
        "category": "Продукты",
        "op_date": date(2026, 9, 16),
        "comment": "рынок",
        "account": None,
        "transfer_direction": None,
    }
    assert operation_create({
        "type": "перевод",
        "amount": "500",
        "transfer_direction": "self",
    }, today)["category"] is None
    with pytest.raises(ValidationError):
        operation_create({"type": "расход", "amount": "500"}, today)
    with pytest.raises(ValidationError):
        operation_create({
            "type": "доход", "amount": "500", "category": "Продукты",
        }, today)
    with pytest.raises(ValidationError):
        operation_create({
            "type": "перевод", "amount": "500", "category": "Продукты",
        }, today)
    with pytest.raises(ValidationError):
        operation_create({
            "type": "расход", "amount": "500", "category": "Продукты",
            "op_date": "2026-09-18",
        }, today)


def test_note_patch_is_independent_and_limited():
    current = {"type": "расход"}
    assert operation_patch({"note": "вернуть с коллеги"}, current) == {
        "note": "вернуть с коллеги"
    }
    assert operation_patch({"note": ""}, current) == {"note": None}
    with pytest.raises(ValidationError):
        operation_patch({"note": "x" * 1001}, current)


def test_cursor_round_trip():
    cursor = encode_cursor(date(2026, 7, 15), 42)
    assert decode_cursor(cursor) == (date(2026, 7, 15), 42)
    with pytest.raises(ValidationError):
        decode_cursor("not-a-cursor")


def test_debt_schemas_keep_money_as_decimal_strings():
    created = debt_create({
        "creditor": "Сбер",
        "principal": "100000.00",
        "rate": "19.90",
        "min_payment": "10000",
        "next_payment_amount": "10000",
        "opened_at": "2025-03-12",
        "next_payment_date": "2026-08-15",
        "loan_name": "Ремонт",
        "contract_ref": "1234",
        "priority": 1,
        "maturity_date": "2027-01-15",
    })
    assert created["principal"] == Decimal("100000.00")
    assert created["rate"] == Decimal("19.90")
    assert created["due_date"] == date(2027, 1, 15)
    assert created["opened_at"] == date(2025, 3, 12)
    assert created["next_payment_date"] == date(2026, 8, 15)
    assert created["next_payment_amount"] == Decimal("10000.00")
    with pytest.raises(ValidationError):
        debt_create({"creditor": "Сбер", "principal": 100.5})


def test_debt_patch_and_zero_balance_adjustment():
    current = {"balance": Decimal("50000")}
    assert debt_patch({"status": "closed"}, current) == {"status": "closed"}
    assert debt_adjust({
        "balance": "0", "date": "2026-07-21", "reason": "Сверил в банке",
    }) == {
        "balance": Decimal("0.00"),
        "date": date(2026, 7, 21),
        "reason": "Сверил в банке",
    }
    with pytest.raises(ValidationError):
        debt_adjust({"balance": "0", "date": "2026-07-21"})
    with pytest.raises(ValidationError):
        debt_patch({"principal": "1000"}, current)


def test_debt_payment_schema_distinguishes_early_repayment():
    assert debt_payment({
        "amount": "5000",
        "date": "2026-08-01",
        "payment_type": "early",
    }) == {
        "amount": Decimal("5000.00"),
        "principal_amount": None,
        "date": date(2026, 8, 1),
        "idempotency_key": None,
        "payment_type": "early",
        "cash_effect": "movement",
    }
    already_in_balance = debt_payment({
        "amount": "5000",
        "cash_effect": "already_in_balance",
    })
    assert already_in_balance["cash_effect"] == "already_in_balance"
    with_body = debt_payment({"amount": "5000", "principal_amount": "3200"})
    assert with_body["principal_amount"] == Decimal("3200.00")
    with pytest.raises(ValidationError):
        debt_payment({"amount": "5000", "principal_amount": "5000.01"})
    with pytest.raises(ValidationError):
        debt_payment({"amount": "5000", "payment_type": "unknown"})
    with pytest.raises(ValidationError):
        debt_payment({"amount": "5000", "cash_effect": "unknown"})


def test_personal_debt_schemas_validate_direction_and_balance():
    created = personal_debt_create({
        "person": "Вася", "direction": "owed_to_me", "principal": "5000"
    }, date(2026, 7, 21))
    assert created["opened_at"] == date(2026, 7, 21)
    assert created["operation_id"] is None
    current = {"principal": Decimal("5000"), "balance": Decimal("5000")}
    assert personal_debt_patch({"balance": "2000"}, current) == {
        "balance": Decimal("2000.00")
    }
    with pytest.raises(ValidationError):
        personal_debt_create({
            "person": "Вася", "direction": "unknown", "principal": "5000"
        }, date(2026, 7, 21))


def test_subscription_schemas_keep_period_and_date_contract():
    created = subscription_create({
        "title": "Музыка",
        "amount": "1200",
        "period": "yearly",
        "next_charge": "2026-08-31",
        "comment": "семейный план",
    }, date(2026, 8, 8))
    assert created == {
        "title": "Музыка",
        "amount": Decimal("1200.00"),
        "period": "yearly",
        "next_charge": date(2026, 8, 31),
        "category": None,
        "comment": "семейный план",
    }
    assert subscription_patch({"amount": "0", "status": "cancelled"}, created) == {
        "amount": Decimal("0.00"), "status": "cancelled"
    }
    with pytest.raises(ValidationError):
        subscription_create({
            "title": "Музыка", "amount": "10", "period": "weekly",
            "next_charge": "2026-08-31",
        }, date(2026, 8, 8))


def test_charge_request_requires_boolean_and_rejects_unknown_fields():
    assert charge_request({"confirmed": True, "op_date": "2026-08-10"}) == {
        "confirmed": True, "op_date": date(2026, 8, 10),
    }
    assert charge_request({"confirmed": False}) == {
        "confirmed": False, "op_date": None,
    }
    with pytest.raises(ValidationError):
        charge_request({"confirmed": "yes"})
    with pytest.raises(ValidationError):
        charge_request({"confirmed": True, "op_date": "10.08.2026"})
    with pytest.raises(ValidationError):
        charge_request({"confirmed": True, "extra": 1})
