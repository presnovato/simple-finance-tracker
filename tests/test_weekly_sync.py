from datetime import date
from decimal import Decimal

from finance_bot.services import balance as balance_service
from finance_bot.services import weekly_sync


async def test_build_finance_snapshot_reuses_balance_and_debt_history(monkeypatch):
    async def get_snapshot():
        return {
            "amount": Decimal("99500.00"),
            "anchor_date": date(2026, 9, 1),
        }

    async def list_debts(status=None, *, archived=False):
        assert status == "active"
        assert archived is False
        return [{
            "id": 1,
            "creditor": "Банк",
            "loan_name": "Ремонт",
            "contract_ref": "42",
            "principal": Decimal("100000"),
            "balance": Decimal("70000"),
            "rate": Decimal("19.90"),
            "min_payment": Decimal("5000"),
            "next_payment_amount": None,
            "next_payment_date": date(2026, 9, 15),
            "opened_at": date(2025, 3, 12),
        }]

    async def debt_history(debt_id):
        assert debt_id == 1
        return [
            {"amount": Decimal("25000")},
            {"amount": Decimal("10000")},
        ]

    async def list_personal_debts(status=None, *, archived=False):
        assert status == "open"
        assert archived is False
        return [
            {
                "id": 2,
                "person": "Анна",
                "direction": "i_owe",
                "principal": Decimal("1500"),
                "balance": Decimal("1000"),
                "opened_at": date(2026, 8, 1),
                "due_date": date(2026, 9, 20),
            },
            {
                "id": 3,
                "person": "Борис",
                "direction": "owed_to_me",
                "principal": Decimal("2000"),
                "balance": Decimal("1200"),
                "opened_at": date(2026, 8, 1),
                "due_date": None,
            },
        ]

    async def personal_history(debt_id):
        return [{"amount": Decimal("500")}] if debt_id == 2 else []

    monkeypatch.setattr(balance_service, "get_snapshot", get_snapshot)
    monkeypatch.setattr(weekly_sync.queries, "list_debts", list_debts)
    monkeypatch.setattr(weekly_sync.queries, "debt_payment_history", debt_history)
    monkeypatch.setattr(weekly_sync.queries, "list_personal_debts", list_personal_debts)
    monkeypatch.setattr(
        weekly_sync.queries, "personal_debt_history", personal_history
    )

    snapshot = await weekly_sync.build_finance_snapshot(date(2026, 9, 9))

    assert snapshot["cash"]["total"] == Decimal("99500.00")
    assert snapshot["cash"]["accounts"] is None
    assert snapshot["debts"][0]["paid_amount"] == Decimal("30000")
    assert snapshot["debts"][0]["paid_percent"] == Decimal("30.00")
    assert snapshot["debts"][0]["next_payment_amount"] == Decimal("5000")
    assert snapshot["totals"] == {
        "credit_balance": Decimal("70000"),
        "personal_liability_balance": Decimal("1000"),
        "liability_balance": Decimal("71000"),
        "liability_unavailable_reason": "один или несколько остатков неизвестны",
        "receivable_balance": Decimal("1200"),
        "next_payment_amount": Decimal("5000"),
        "next_payment_unknown_count": 0,
        "next_payment_date_unknown_count": 0,
        "personal_liability_payment_unknown_count": 1,
        "unknown_personal_direction_count": 0,
    }


async def test_build_finance_snapshot_has_zero_totals_without_active_debts(monkeypatch):
    async def no_snapshot():
        return None

    async def no_debts(*_args, **_kwargs):
        return []

    monkeypatch.setattr(balance_service, "get_snapshot", no_snapshot)
    monkeypatch.setattr(weekly_sync.queries, "list_debts", no_debts)
    monkeypatch.setattr(weekly_sync.queries, "list_personal_debts", no_debts)

    snapshot = await weekly_sync.build_finance_snapshot(date(2026, 9, 9))

    assert snapshot["cash"]["total"] is None
    assert snapshot["debts"] == []
    assert snapshot["totals"]["liability_balance"] == Decimal("0.00")
    assert snapshot["totals"]["next_payment_amount"] == Decimal("0.00")
    assert snapshot["previous_total_debt"] is None
