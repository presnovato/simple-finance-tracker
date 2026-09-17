import sqlite3

from finance_bot.database.connection import SCHEMA


def test_sqlite_schema_is_idempotent_and_complete():
    connection = sqlite3.connect(":memory:")
    connection.executescript(SCHEMA)
    connection.executescript(SCHEMA)

    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    assert {
        "operations",
        "debts",
        "debt_payments",
        "personal_debts",
        "personal_debt_payments",
        "subscriptions",
        "settings",
        "crypto_holdings",
        "crypto_transactions",
        "manual_capture_sessions",
        "weekly_budget_template",
        "weekly_budget_template_categories",
        "weekly_budget_weeks",
        "weekly_budget_week_categories",
        "weekly_budget_notifications",
    } <= tables

    operation_columns = {
        row[1]: row[2]
        for row in connection.execute("PRAGMA table_info(operations)")
    }
    assert operation_columns["amount"] == "INTEGER"
    assert operation_columns["op_date"] == "TEXT"
    assert operation_columns["needs_review"] == "INTEGER"
    assert {"deleted_at", "note", "transfer_direction", "subscription_id"} <= operation_columns.keys()

    debt_columns = {
        row[1]: row[2]
        for row in connection.execute("PRAGMA table_info(debts)")
    }
    assert debt_columns["rate"] == "INTEGER"
    assert {
        "status", "created_at", "loan_name", "contract_ref", "opened_at",
        "next_payment_amount", "next_payment_date", "payment_day",
    } <= debt_columns.keys()

    debt_payment_columns = {
        row[1]: row[2]
        for row in connection.execute("PRAGMA table_info(debt_payments)")
    }
    assert {
        "payment_type", "reason", "cash_effect", "principal_amount",
    } <= debt_payment_columns.keys()

    personal_debt_payment_columns = {
        row[1]: row[2]
        for row in connection.execute(
            "PRAGMA table_info(personal_debt_payments)"
        )
    }
    assert "cash_effect" in personal_debt_payment_columns

    indexes = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index'"
        )
    }
    assert {
        "idx_operations_active_date",
        "idx_debt_payments_debt_id",
        "idx_personal_debts_status",
        "idx_personal_debt_payments_debt_id",
        "idx_subscriptions_status_next_charge",
        "idx_crypto_transactions_date",
        "idx_weekly_budget_week_categories",
        "idx_weekly_budget_weeks_start",
    } <= indexes

    weekly_category_columns = {
        row[1]: row[3]
        for row in connection.execute(
            "PRAGMA table_info(weekly_budget_template_categories)"
        )
    }
    assert weekly_category_columns["weekly_limit"] == 0
    assert "ALTER TABLE" not in SCHEMA
