from datetime import date, datetime, timezone
from decimal import Decimal
import sqlite3

import pytest

from finance_bot.core.balance import movement_totals
from finance_bot.database import connection, queries


@pytest.fixture
async def sqlite_database(tmp_path, monkeypatch):
    await connection.close_pool()
    monkeypatch.setattr(connection, "DB_PATH", str(tmp_path / "finance.db"))
    monkeypatch.setattr(connection, "DB_REQUIRE_PERSISTENT_DIR", False)
    await connection.init_pool()
    try:
        yield tmp_path / "finance.db"
    finally:
        await connection.close_pool()


async def _insert_expense(
    amount: str,
    *,
    op_date: date = date(2026, 7, 26),
    category: str = "Продукты",
    comment: str = "продукты",
    needs_review: bool = False,
) -> int:
    return await queries.insert_operation(
        op_date,
        "расход",
        Decimal(amount),
        category,
        comment,
        "Карта",
        "text",
        needs_review,
    )


async def test_operation_round_trip_preserves_public_types(sqlite_database):
    op_id = await _insert_expense("540", needs_review=True)

    operation = await queries.get_operation(op_id)

    assert operation is not None
    assert operation["amount"] == Decimal("540.00")
    assert isinstance(operation["amount"], Decimal)
    assert operation["op_date"] == date(2026, 7, 26)
    assert type(operation["op_date"]) is date
    assert operation["needs_review"] is True
    assert type(operation["needs_review"]) is bool
    assert isinstance(operation["created_at"], datetime)


async def test_aggregates_and_daily_dates_keep_contract(sqlite_database):
    await _insert_expense("540.10", category="Продукты")
    await _insert_expense("59.90", category="Транспорт")
    await queries.insert_operation(
        date(2026, 7, 26),
        "доход",
        Decimal("1000"),
        "Зарплата",
        "аванс",
        "Карта",
        "text",
        False,
    )

    totals = await queries.totals(date(2026, 7, 1), date(2026, 7, 31))
    categories = await queries.expenses_by_category(
        date(2026, 7, 1), date(2026, 7, 31)
    )
    days = await queries.expenses_by_day(
        date(2026, 7, 1), date(2026, 7, 31)
    )

    assert totals == {
        "expense": Decimal("600.00"),
        "income": Decimal("1000.00"),
        "transfer_in": Decimal("0.00"),
        "transfer_out": Decimal("0.00"),
    }
    assert all(isinstance(row["total"], Decimal) for row in categories)
    assert all(row["total"].as_tuple().exponent == -2 for row in categories)
    assert days == [
        {"op_date": date(2026, 7, 26), "total": Decimal("600.00")}
    ]
    assert type(days[0]["op_date"]) is date


async def test_rhythm_day_queries_exclude_fixed_categories_and_salary(sqlite_database):
    op_date = date(2026, 7, 26)
    await _insert_expense("100", op_date=op_date, category="Продукты")
    await _insert_expense("200", op_date=op_date, category="Жильё")
    await _insert_expense("300", op_date=op_date, category="Долги")
    await queries.insert_operation(
        op_date,
        "доход",
        Decimal("1000"),
        "Зарплата",
        "аванс",
        "Карта",
        "text",
        False,
    )
    await queries.insert_operation(
        op_date,
        "доход",
        Decimal("400"),
        "Услуги",
        "проект",
        "Карта",
        "text",
        False,
    )
    await queries.insert_operation(
        op_date,
        "доход",
        Decimal("50"),
        None,
        "прочее",
        "Карта",
        "text",
        False,
    )

    expenses = await queries.expenses_by_day(
        date(2026, 7, 1), date(2026, 7, 31)
    )
    incomes = await queries.income_by_day(
        date(2026, 7, 1), date(2026, 7, 31)
    )
    totals = await queries.totals(date(2026, 7, 1), date(2026, 7, 31))

    assert expenses == [{"op_date": op_date, "total": Decimal("100.00")}]
    assert incomes == [{"op_date": op_date, "total": Decimal("450.00")}]
    assert totals["expense"] == Decimal("600.00")
    assert totals["income"] == Decimal("1450.00")


async def test_period_aggregates_start_after_balance_anchor_timestamp(sqlite_database):
    anchor_date = date(2026, 7, 26)
    anchor_ts = datetime(2026, 7, 26, 18, 0, tzinfo=timezone.utc)

    before_anchor = await _insert_expense("500", op_date=anchor_date)
    await _set_created_at(
        before_anchor, datetime(2026, 7, 26, 9, 0, tzinfo=timezone.utc)
    )
    after_anchor = await _insert_expense("300", op_date=anchor_date)
    await _set_created_at(
        after_anchor, datetime(2026, 7, 26, 21, 0, tzinfo=timezone.utc)
    )
    next_day = await _insert_expense("100", op_date=date(2026, 7, 27))
    await _set_created_at(
        next_day, datetime(2026, 7, 27, 8, 0, tzinfo=timezone.utc)
    )

    totals = await queries.totals(
        anchor_date, date(2026, 7, 27), start_ts=anchor_ts
    )
    categories = await queries.expenses_by_category(
        anchor_date, date(2026, 7, 27), start_ts=anchor_ts
    )
    days = await queries.expenses_by_day(
        anchor_date, date(2026, 7, 27), start_ts=anchor_ts
    )

    assert totals["expense"] == Decimal("400.00")
    assert categories == [{"category": "Продукты", "total": Decimal("400.00")}]
    assert days == [
        {"op_date": anchor_date, "total": Decimal("300.00")},
        {"op_date": date(2026, 7, 27), "total": Decimal("100.00")},
    ]


async def test_monthly_delta_excludes_personal_debt_transfer_but_cash_keeps_it(
    sqlite_database,
):
    operation_id = await queries.insert_operation(
        date(2026, 7, 26),
        "перевод",
        Decimal("10000"),
        None,
        "выдал долг",
        "Карта",
        "text",
        False,
        "out",
    )
    await queries.insert_personal_debt(
        person="Вася",
        direction="owed_to_me",
        principal=Decimal("10000"),
        opened_at=date(2026, 7, 26),
        due_date=None,
        comment=None,
        operation_id=operation_id,
    )

    delta = await queries.totals(date(2026, 7, 1), date(2026, 7, 31))
    cash = await queries.totals_since(
        date(2026, 7, 1), datetime(2026, 7, 1, tzinfo=timezone.utc)
    )

    assert delta["transfer_out"] == Decimal("0.00")
    assert cash["transfer_out"] == Decimal("10000.00")


async def test_cursor_pagination_and_casefold_search(sqlite_database):
    first_id = await _insert_expense(
        "10", op_date=date(2026, 7, 24), comment="другое"
    )
    second_id = await _insert_expense(
        "20", op_date=date(2026, 7, 25), comment="Свежие продукты"
    )
    third_id = await _insert_expense(
        "30", op_date=date(2026, 7, 26), comment="транспорт"
    )

    first_page = await queries.list_operations(limit=2)
    cursor = (first_page[-1]["op_date"], first_page[-1]["id"])
    second_page = await queries.list_operations(before=cursor, limit=2)
    found = await queries.list_operations(query="ПРОДУКТЫ")

    assert [row["id"] for row in first_page] == [third_id, second_id]
    assert [row["id"] for row in second_page] == [first_id]
    assert {row["id"] for row in first_page}.isdisjoint(
        row["id"] for row in second_page
    )
    assert [row["id"] for row in found] == [second_id]


async def test_operations_date_range_and_totals_share_the_same_filters(
    sqlite_database,
):
    await _insert_expense("10", op_date=date(2026, 7, 24))
    income_id = await queries.insert_operation(
        date(2026, 7, 25), "доход", Decimal("20"), "Услуги", "аванс",
        "Карта", "text", False,
    )
    transfer_id = await queries.insert_operation(
        date(2026, 7, 26), "перевод", Decimal("30"), None, "накопления",
        "Карта", "text", False, "out",
    )
    deleted_id = await _insert_expense("40", op_date=date(2026, 7, 25))
    await queries.soft_delete_operation(deleted_id)

    rows = await queries.list_operations(
        date_from=date(2026, 7, 25), date_to=date(2026, 7, 26),
    )
    totals = await queries.operations_totals(
        date_from=date(2026, 7, 25), date_to=date(2026, 7, 26),
    )

    assert [row["id"] for row in rows] == [transfer_id, income_id]
    assert totals == {
        "total_count": 2,
        "expense": Decimal("0.00"),
        "income": Decimal("20.00"),
        "transfer": Decimal("30.00"),
    }


async def test_soft_delete_excludes_and_restore_returns_operation(
    sqlite_database,
):
    op_id = await _insert_expense("540")

    deleted = await queries.soft_delete_operation(op_id)

    assert deleted is not None
    assert isinstance(deleted["deleted_at"], datetime)
    assert await queries.list_operations() == []
    assert await queries.totals(
        date(2026, 7, 1), date(2026, 7, 31)
    ) == {
        "expense": Decimal("0.00"),
        "income": Decimal("0.00"),
        "transfer_in": Decimal("0.00"),
        "transfer_out": Decimal("0.00"),
    }
    assert await queries.find_possible_duplicates(
        date(2026, 7, 26), Decimal("540"), "расход", "Продукты"
    ) is None

    restored = await queries.restore_operation(op_id)

    assert restored is not None
    assert restored["deleted_at"] is None
    assert [row["id"] for row in await queries.list_operations()] == [op_id]


async def test_patch_review_semantics(sqlite_database):
    op_id = await _insert_expense("540", needs_review=True)

    note_only = await queries.patch_operation(op_id, {"note": "личное"})
    regular = await queries.patch_operation(op_id, {"comment": "уточнено"})

    assert note_only is not None
    assert note_only["needs_review"] is True
    assert regular is not None
    assert regular["needs_review"] is False


async def test_debt_payment_is_idempotent_and_closes_debt(sqlite_database):
    debt = await queries.insert_debt(
        creditor="Банк",
        principal=Decimal("100"),
        rate=Decimal("12.50"),
        min_payment=Decimal("10"),
        priority=1,
        due_date=None,
    )
    operation_id = await _insert_expense("100", category="Долги")

    first = await queries.record_debt_payment(
        debt["id"], operation_id, date(2026, 7, 26), Decimal("100"),
        principal_amount=Decimal("100"),
    )
    second = await queries.record_debt_payment(
        debt["id"], operation_id, date(2026, 7, 26), Decimal("100")
    )
    payments = await queries.debt_payment_history(debt["id"])

    assert first is not None
    assert first["balance"] == Decimal("0.00")
    assert first["status"] == "closed"
    assert second == first
    assert len(payments) == 1
    assert payments[0]["amount"] == Decimal("100.00")
    assert payments[0]["principal_amount"] == Decimal("100.00")


async def test_tma_debt_payment_is_atomic_idempotent_and_rejects_overpay(
    sqlite_database,
):
    debt = await queries.insert_debt(
        creditor="Тестовый банк",
        principal=Decimal("100"),
        rate=None,
        min_payment=Decimal("10"),
        priority=None,
        due_date=None,
    )

    first = await queries.create_debt_payment(
        debt["id"], date(2026, 7, 26), Decimal("40"), "payment-key-1",
        principal_amount=Decimal("40"),
    )
    repeated = await queries.create_debt_payment(
        debt["id"], date(2026, 7, 26), Decimal("40"), "payment-key-1"
    )

    assert first is not None
    assert repeated == first
    assert first["balance"] == Decimal("60.00")
    assert len(await queries.debt_payment_history(debt["id"])) == 1
    operations = await queries.list_operations(op_date=date(2026, 7, 26))
    assert len(operations) == 1
    assert operations[0]["category"] == "Долги"

    with pytest.raises(queries.DebtPaymentError, match="больше остатка"):
        await queries.create_debt_payment(
            debt["id"], date(2026, 7, 27), Decimal("61"), "payment-key-2",
            principal_amount=Decimal("61"),
        )
    assert await queries.list_operations(op_date=date(2026, 7, 27)) == []


async def test_tma_debt_payment_can_skip_cash_operation(sqlite_database):
    debt = await queries.insert_debt(
        creditor="Банк без повторного списания",
        principal=Decimal("100"),
        rate=None,
        min_payment=Decimal("10"),
        priority=None,
        due_date=None,
    )

    result = await queries.create_debt_payment(
        debt["id"],
        date(2026, 7, 26),
        Decimal("40"),
        "already-in-balance-key",
        cash_effect="already_in_balance",
        principal_amount=Decimal("40"),
    )

    assert result is not None
    assert result["balance"] == Decimal("60.00")
    assert await queries.list_operations(op_date=date(2026, 7, 26)) == []
    history = await queries.debt_history(debt["id"])
    assert len(history) == 1
    assert history[0]["operation_id"] is None
    assert history[0]["cash_effect"] == "already_in_balance"
    assert (await queries.list_debt_payments())[0]["cash_effect"] == "already_in_balance"


async def test_credit_payment_without_body_breakdown_does_not_change_balance(
    sqlite_database,
):
    debt = await queries.insert_debt(
        creditor="Банк с неизвестной разбивкой",
        principal=Decimal("100"),
        rate=Decimal("20"),
        min_payment=Decimal("10"),
        priority=None,
        due_date=None,
    )

    result = await queries.create_debt_payment(
        debt["id"], date(2026, 7, 26), Decimal("10"), "unknown-body-key"
    )

    assert result is not None
    assert result["balance"] == Decimal("100.00")
    history = await queries.debt_history(debt["id"])
    assert history[0]["principal_amount"] is None
    assert history[0]["interest_amount"] is None


async def test_credit_metadata_and_early_payment_keep_monthly_schedule(
    sqlite_database,
):
    debt = await queries.insert_debt(
        creditor="Тестовый банк",
        loan_name="Ремонт",
        contract_ref="1234",
        principal=Decimal("100"),
        rate=Decimal("19.9"),
        min_payment=Decimal("40"),
        next_payment_amount=Decimal("40"),
        opened_at=date(2025, 3, 12),
        next_payment_date=date(2026, 8, 15),
        priority=1,
        due_date=date(2027, 3, 15),
    )

    assert debt["loan_name"] == "Ремонт"
    assert debt["contract_ref"] == "1234"
    assert debt["opened_at"] == date(2025, 3, 12)
    assert debt["next_payment_amount"] == Decimal("40.00")
    assert debt["payment_day"] == 15

    early = await queries.create_debt_payment(
        debt["id"], date(2026, 8, 1), Decimal("20"), "early-key", "early",
        principal_amount=Decimal("20"),
    )
    assert early is not None
    assert early["next_payment_date"] == date(2026, 8, 15)
    early_operation = await queries.get_operation(
        (await queries.debt_history(debt["id"]))[0]["operation_id"]
    )
    assert early_operation is not None
    assert early_operation["comment"] == "Досрочное погашение по кредиту Ремонт"
    assert (await queries.debt_history(debt["id"]))[0]["payment_type"] == "early"
    assert (await queries.debt_history(debt["id"]))[0]["interest_amount"] == Decimal("0.00")

    regular = await queries.create_debt_payment(
        debt["id"], date(2026, 8, 15), Decimal("40"), "regular-key",
        principal_amount=Decimal("40"),
    )
    assert regular is not None
    assert regular["next_payment_date"] == date(2026, 9, 15)


async def test_debt_adjustment_is_history_not_payment_and_archive_is_reversible(
    sqlite_database,
):
    debt = await queries.insert_debt(
        creditor="Корректируемый банк",
        principal=Decimal("100"),
        rate=None,
        min_payment=None,
        priority=None,
        due_date=None,
    )

    adjusted = await queries.adjust_debt_balance(
        debt["id"], Decimal("80"), date(2026, 7, 26), "Сверил в банке"
    )
    assert adjusted is not None
    assert [row["kind"] for row in await queries.debt_history(debt["id"])] == [
        "adjustment"
    ]
    assert (await queries.debt_history(debt["id"]))[0]["reason"] == "Сверил в банке"
    assert await queries.list_debt_payments() == []

    archived = await queries.set_debt_archived(debt["id"], True)
    assert archived is not None and archived["archived"] is True
    assert await queries.list_debts() == []
    assert [row["id"] for row in await queries.list_debts(archived=True)] == [
        debt["id"]
    ]
    restored = await queries.set_debt_archived(debt["id"], False)
    assert restored is not None and restored["archived"] is False


async def test_tma_personal_debt_payment_is_atomic_and_keeps_direction(
    sqlite_database,
):
    debt = await queries.insert_personal_debt(
        person="Анна",
        direction="owed_to_me",
        principal=Decimal("75"),
        opened_at=date(2026, 7, 20),
        due_date=None,
        comment=None,
        operation_id=None,
    )

    paid = await queries.create_personal_debt_payment(
        debt["id"], date(2026, 7, 26), Decimal("25"), "personal-key-1"
    )
    repeated = await queries.create_personal_debt_payment(
        debt["id"], date(2026, 7, 26), Decimal("25"), "personal-key-1"
    )

    assert paid is not None
    assert repeated == paid
    assert paid["balance"] == Decimal("50.00")
    assert (await queries.get_personal_debt(debt["id"]))["payment_count"] == 1
    operation = await queries.get_operation(
        (await queries.personal_debt_history(debt["id"]))[0]["operation_id"]
    )
    assert operation is not None
    assert operation["type"] == "перевод"
    assert operation["transfer_direction"] == "in"


async def test_tma_personal_debt_payment_can_skip_cash_operation(sqlite_database):
    debt = await queries.insert_personal_debt(
        person="Анна",
        direction="owed_to_me",
        principal=Decimal("100"),
        opened_at=date(2026, 7, 20),
        due_date=None,
        comment=None,
        operation_id=None,
    )

    result = await queries.create_personal_debt_payment(
        debt["id"],
        date(2026, 7, 26),
        Decimal("40"),
        "personal-already-in-balance-key",
        cash_effect="already_in_balance",
    )

    assert result is not None
    assert result["balance"] == Decimal("60.00")
    assert await queries.list_operations(op_date=date(2026, 7, 26)) == []
    history = await queries.personal_debt_history(debt["id"])
    assert len(history) == 1
    assert history[0]["operation_id"] is None
    assert history[0]["cash_effect"] == "already_in_balance"


async def test_debt_delete_is_allowed_without_history_and_blocked_after_history(
    sqlite_database,
):
    empty_debt = await queries.insert_debt(
        creditor="Удаляемый банк",
        principal=Decimal("100"),
        rate=None,
        min_payment=None,
        priority=None,
        due_date=None,
    )
    assert await queries.delete_debt(empty_debt["id"]) is True
    assert await queries.get_debt(empty_debt["id"]) is None

    debt_with_history = await queries.insert_debt(
        creditor="Банк с историей",
        principal=Decimal("100"),
        rate=None,
        min_payment=None,
        priority=None,
        due_date=None,
    )
    await queries.create_debt_payment(
        debt_with_history["id"], date(2026, 7, 26), Decimal("10")
    )
    assert await queries.delete_debt(debt_with_history["id"]) is False
    assert await queries.get_debt(debt_with_history["id"]) is not None

    empty_personal = await queries.insert_personal_debt(
        person="Удаляемый человек",
        direction="owed_to_me",
        principal=Decimal("50"),
        opened_at=date(2026, 7, 20),
        due_date=None,
        comment=None,
        operation_id=None,
    )
    assert await queries.delete_personal_debt(empty_personal["id"]) is True


async def test_integer_kopecks_sum_exactly(sqlite_database):
    await _insert_expense("0.1")
    await _insert_expense("0.1")
    await _insert_expense("0.1")

    result = await queries.totals(date(2026, 7, 1), date(2026, 7, 31))

    assert result["expense"] == Decimal("0.30")
    assert result["expense"].as_tuple().exponent == -2


async def test_missing_persistent_directory_fails_fast(tmp_path, monkeypatch):
    await connection.close_pool()
    missing_db = tmp_path / "missing-volume" / "finance.db"
    monkeypatch.setattr(connection, "DB_PATH", str(missing_db))
    monkeypatch.setattr(connection, "DB_REQUIRE_PERSISTENT_DIR", True)

    with pytest.raises(RuntimeError, match="не подключён Railway Volume"):
        await connection.init_pool()

    assert not missing_db.parent.exists()


async def test_remaining_query_surface_and_pragmas(sqlite_database):
    pool = connection.get_pool()
    assert (await pool.fetchrow("PRAGMA journal_mode"))["journal_mode"] == "wal"
    assert (await pool.fetchrow("PRAGMA foreign_keys"))["foreign_keys"] == 1
    assert (await pool.fetchrow("PRAGMA busy_timeout"))["timeout"] == 5000

    await queries.set_setting("reminder_time", "20:00")
    await queries.set_setting("reminder_time", "21:30")
    assert await queries.get_setting("reminder_time") == "21:30"

    op_id = await _insert_expense("40", needs_review=True)
    await queries.update_operation(
        op_id, {"amount": Decimal("45.50"), "op_date": date(2026, 7, 25)}
    )
    confirmed = await queries.confirm_operation(op_id)
    assert confirmed is not None
    assert confirmed["amount"] == Decimal("45.50")
    assert confirmed["op_date"] == date(2026, 7, 25)
    assert confirmed["needs_review"] is False

    debt = await queries.insert_debt(
        creditor="Банк",
        principal=Decimal("200"),
        rate=None,
        min_payment=None,
        priority=None,
        due_date=None,
    )
    patched_debt = await queries.patch_debt(
        debt["id"],
        {
            "rate": Decimal("9.75"),
            "min_payment": Decimal("25"),
            "due_date": date(2026, 8, 1),
        },
    )
    adjusted_debt = await queries.adjust_debt_balance(
        debt["id"], Decimal("150.25"), date(2026, 7, 26)
    )
    assert patched_debt is not None
    assert patched_debt["rate"] == Decimal("9.75")
    assert patched_debt["min_payment"] == Decimal("25.00")
    assert patched_debt["due_date"] == date(2026, 8, 1)
    assert adjusted_debt is not None
    assert adjusted_debt["balance"] == Decimal("150.25")
    assert [row["id"] for row in await queries.list_debts("active")] == [
        debt["id"]
    ]

    personal = await queries.insert_personal_debt(
        person="Анна",
        direction="i_owe",
        principal=Decimal("75"),
        opened_at=date(2026, 7, 20),
        due_date=None,
        comment="до зарплаты",
        operation_id=None,
    )
    payment_operation_id = await _insert_expense("25", category="Долги")
    paid = await queries.record_personal_debt_payment(
        personal["id"],
        payment_operation_id,
        date(2026, 7, 26),
        Decimal("25"),
    )
    patched_personal = await queries.patch_personal_debt(
        personal["id"], {"balance": Decimal("0")}
    )
    assert paid is not None
    assert paid["balance"] == Decimal("50.00")
    assert patched_personal is not None
    assert patched_personal["balance"] == Decimal("0.00")
    assert patched_personal["status"] == "closed"
    assert [row["id"] for row in await queries.list_personal_debts("closed")] == [
        personal["id"]
    ]


async def _set_created_at(op_id: int, moment: datetime) -> None:
    await connection.get_pool().execute(
        "UPDATE operations SET created_at = ? WHERE id = ?",
        moment.replace(microsecond=0).isoformat(),
        op_id,
    )


async def test_totals_since_ignores_same_day_movements_before_anchor(
    sqlite_database,
):
    """Регресс на /balance: якорь — момент, а не дата. Утренняя трата уже
    учтена в сумме, названной вечером, и не должна вычитаться повторно."""
    anchor_date = date(2026, 7, 26)
    anchor_ts = datetime(2026, 7, 26, 18, 0, tzinfo=timezone.utc)

    before = await _insert_expense("500", op_date=anchor_date)
    await _set_created_at(before, datetime(2026, 7, 26, 9, 0, tzinfo=timezone.utc))
    after = await _insert_expense("300", op_date=anchor_date)
    await _set_created_at(after, datetime(2026, 7, 26, 21, 0, tzinfo=timezone.utc))
    backdated = await _insert_expense("700", op_date=date(2026, 7, 24))
    await _set_created_at(
        backdated, datetime(2026, 7, 26, 22, 0, tzinfo=timezone.utc)
    )
    next_day = await _insert_expense("100", op_date=date(2026, 7, 27))
    await _set_created_at(next_day, datetime(2026, 7, 27, 8, 0, tzinfo=timezone.utc))

    totals = await queries.totals_since(anchor_date, anchor_ts)

    assert totals["expense"] == Decimal("400.00")
    assert totals["income"] == Decimal("0.00")
    assert totals["movement_count"] == 2


async def test_totals_since_matches_pure_reference(sqlite_database):
    """SQL и эталон из core/balance.py — две реализации одного правила."""
    anchor_date = date(2026, 7, 26)
    anchor_ts = datetime(2026, 7, 26, 18, 0, tzinfo=timezone.utc)
    moments = {
        date(2026, 7, 25): datetime(2026, 7, 25, 10, tzinfo=timezone.utc),
        date(2026, 7, 26): datetime(2026, 7, 26, 20, tzinfo=timezone.utc),
        date(2026, 7, 27): datetime(2026, 7, 27, 10, tzinfo=timezone.utc),
    }
    for op_date, moment in moments.items():
        op_id = await _insert_expense("150", op_date=op_date)
        await _set_created_at(op_id, moment)

    totals = await queries.totals_since(anchor_date, anchor_ts)
    reference = movement_totals(
        [
            {"op_date": op_date, "type": "расход",
             "amount": Decimal("150"), "created_at": moment}
            for op_date, moment in moments.items()
        ],
        anchor_date,
        anchor_ts,
    )

    assert totals["expense"] == reference["expense"]
    assert totals["movement_count"] == reference["movement_count"]


async def test_crypto_transaction_updates_balance_and_rolls_back(sqlite_database):
    purchase = await queries.insert_crypto_transaction(
        asset="BTC",
        quantity_delta=Decimal("0.001"),
        rub_amount=Decimal("5000"),
        op_date=date(2026, 7, 26),
        comment="покупка BTC",
    )
    sale = await queries.insert_crypto_transaction(
        asset="BTC",
        quantity_delta=Decimal("-0.0004"),
        rub_amount=Decimal("2500"),
        op_date=date(2026, 7, 27),
        comment="продажа BTC",
    )

    holdings = await queries.list_crypto_holdings()
    assert holdings[0]["asset"] == "BTC"
    assert holdings[0]["quantity"] == Decimal("0.0006")
    totals = await queries.totals(date(2026, 7, 1), date(2026, 7, 31))
    assert totals["transfer_out"] == Decimal("5000.00")
    assert totals["transfer_in"] == Decimal("2500.00")
    operation = await queries.get_operation(purchase["operation_id"])
    assert operation is not None
    assert operation["transfer_direction"] == "out"
    deleted = await queries.delete_crypto_transaction(sale["id"])
    assert deleted is not None
    assert (await queries.list_crypto_holdings())[0]["quantity"] == Decimal("0.001")
    assert await queries.get_operation(sale["operation_id"]) is None


async def test_backup_to_creates_readable_consistent_sqlite_copy(sqlite_database):
    await _insert_expense("42.50")
    backup_path = sqlite_database.parent / "backup.db"

    await connection.get_pool().backup_to(backup_path)

    with sqlite3.connect(backup_path) as backup:
        assert backup.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert backup.execute("SELECT count(*) FROM operations").fetchone()[0] == 1
        assert backup.execute(
            "SELECT amount FROM operations"
        ).fetchone()[0] == 4250


async def test_subscription_queries_round_trip_and_cancel(sqlite_database):
    created = await queries.insert_subscription(
        title="Музыка",
        amount=Decimal("1200"),
        period="yearly",
        next_charge=date(2026, 8, 31),
        category="Подписки",
        comment="семейный план",
    )
    assert created["amount"] == Decimal("1200.00")
    assert created["next_charge"] == date(2026, 8, 31)
    assert [row["id"] for row in await queries.list_subscriptions()] == [created["id"]]
    assert [row["id"] for row in await queries.list_subscriptions(
        "active", next_charge=date(2026, 8, 31)
    )] == [created["id"]]

    patched = await queries.patch_subscription(
        created["id"], {"next_charge": date(2026, 9, 30)}
    )
    cancelled = await queries.cancel_subscription(created["id"])

    assert patched is not None
    assert patched["next_charge"] == date(2026, 9, 30)
    assert cancelled is not None
    assert cancelled["status"] == "cancelled"
    assert await queries.list_subscriptions() == []


async def test_subscription_operation_link_migration_is_present(sqlite_database):
    columns = {
        row["name"]
        for row in await connection.get_pool().fetch("PRAGMA table_info(operations)")
    }
    indexes = {
        row["name"]
        for row in await connection.get_pool().fetch(
            "SELECT name FROM sqlite_master WHERE type = 'index'"
        )
    }
    assert "subscription_id" in columns
    assert "idx_operations_subscription_id" in indexes


async def test_legacy_operations_table_receives_subscription_link(tmp_path, monkeypatch):
    await connection.close_pool()
    database_path = tmp_path / "legacy.db"
    legacy_schema = connection.SCHEMA.replace(
        "  subscription_id INTEGER REFERENCES subscriptions(id),\n", ""
    )
    with sqlite3.connect(database_path) as legacy:
        legacy.executescript(legacy_schema)

    monkeypatch.setattr(connection, "DB_PATH", str(database_path))
    monkeypatch.setattr(connection, "DB_REQUIRE_PERSISTENT_DIR", False)
    await connection.init_pool()
    try:
        columns = {
            row["name"]
            for row in await connection.get_pool().fetch(
                "PRAGMA table_info(operations)"
            )
        }
        indexes = {
            row["name"]
            for row in await connection.get_pool().fetch(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            )
        }
        assert "subscription_id" in columns
        assert "idx_operations_subscription_id" in indexes
    finally:
        await connection.close_pool()


async def test_legacy_payment_tables_receive_idempotency_columns_before_indexes(
    tmp_path, monkeypatch
):
    await connection.close_pool()
    database_path = tmp_path / "legacy-payments.db"
    legacy_schema = connection.SCHEMA.replace(
        "  principal_amount INTEGER,\n",
        "",
    ).replace(
        "  cash_effect  TEXT    NOT NULL DEFAULT 'movement'\n"
        "               CHECK (cash_effect IN ('movement','already_in_balance')),\n",
        "",
    ).replace(
        "  reason       TEXT,\n  idempotency_key TEXT\n",
        "  reason       TEXT\n",
    ).replace(
        "  amount           INTEGER NOT NULL,\n"
        "  cash_effect      TEXT    NOT NULL DEFAULT 'movement'\n"
        "                   CHECK (cash_effect IN ('movement','already_in_balance')),\n"
        "  idempotency_key  TEXT\n",
        "  amount           INTEGER NOT NULL\n",
    ).replace(
        "  operation_id INTEGER REFERENCES operations(id),\n"
        "  archived     INTEGER NOT NULL DEFAULT 0\n",
        "  operation_id INTEGER REFERENCES operations(id)\n",
    )
    with sqlite3.connect(database_path) as legacy:
        legacy.executescript(legacy_schema)

    monkeypatch.setattr(connection, "DB_PATH", str(database_path))
    monkeypatch.setattr(connection, "DB_REQUIRE_PERSISTENT_DIR", False)
    await connection.init_pool()
    try:
        debt_payment_columns = {
            row["name"]
            for row in await connection.get_pool().fetch(
                "PRAGMA table_info(debt_payments)"
            )
        }
        personal_payment_columns = {
            row["name"]
            for row in await connection.get_pool().fetch(
                "PRAGMA table_info(personal_debt_payments)"
            )
        }
        personal_debt_columns = {
            row["name"]
            for row in await connection.get_pool().fetch(
                "PRAGMA table_info(personal_debts)"
            )
        }
        indexes = {
            row["name"]
            for row in await connection.get_pool().fetch(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            )
        }
        assert "idempotency_key" in debt_payment_columns
        assert "idempotency_key" in personal_payment_columns
        assert "cash_effect" in debt_payment_columns
        assert "cash_effect" in personal_payment_columns
        assert "principal_amount" in debt_payment_columns
        assert "archived" in personal_debt_columns
        assert {
            "idx_debt_payments_idempotency",
            "idx_personal_debt_payments_idempotency",
            "idx_personal_debts_archived",
        } <= indexes
    finally:
        await connection.close_pool()


async def test_subscription_charge_is_idempotent_and_links_operation(sqlite_database):
    created = await queries.insert_subscription(
        title="Музыка",
        amount=Decimal("899"),
        period="monthly",
        next_charge=date(2026, 8, 10),
        category="Подписки",
        comment=None,
    )

    first = await queries.charge_subscription(
        created["id"], confirmed=True, op_date=date(2026, 8, 10)
    )
    assert first is not None
    assert first["operation_id"] is not None
    assert first["subscription"]["next_charge"] == date(2026, 9, 10)
    operation = await queries.get_operation(first["operation_id"])
    assert operation is not None
    assert operation["category"] == "Подписки"
    assert operation["comment"] == "Музыка"
    assert operation["subscription_id"] == created["id"]

    repeated = await queries.charge_subscription(
        created["id"], confirmed=True, op_date=date(2026, 8, 10)
    )
    assert repeated is not None
    assert repeated["operation_id"] == first["operation_id"]
    assert repeated["subscription"]["next_charge"] == date(2026, 9, 10)
    assert len(await queries.list_operations(op_date=date(2026, 8, 10))) == 1


async def test_subscription_skip_moves_without_operation(sqlite_database):
    created = await queries.insert_subscription(
        title="Видео",
        amount=Decimal("500"),
        period="monthly",
        next_charge=date(2026, 8, 10),
        category="Подписки",
        comment=None,
    )
    result = await queries.charge_subscription(created["id"], confirmed=False)
    assert result is not None
    assert result["operation_id"] is None
    assert result["subscription"]["next_charge"] == date(2026, 9, 10)
    assert await queries.list_operations(op_date=date(2026, 8, 10)) == []


async def test_subscription_charge_rolls_back_on_date_shift_failure(
    sqlite_database, monkeypatch
):
    created = await queries.insert_subscription(
        title="Облако",
        amount=Decimal("300"),
        period="monthly",
        next_charge=date(2026, 8, 10),
        category="Подписки",
        comment=None,
    )

    def fail(*_args, **_kwargs):
        raise RuntimeError("сбой сдвига")

    monkeypatch.setattr(
        "finance_bot.database.queries.subscriptions.next_charge_after", fail
    )
    with pytest.raises(RuntimeError, match="сбой сдвига"):
        await queries.charge_subscription(created["id"], confirmed=True)

    current = await queries.get_subscription(created["id"])
    assert current is not None
    assert current["next_charge"] == date(2026, 8, 10)
    assert await queries.list_operations(op_date=date(2026, 8, 10)) == []


async def test_schema_migration_history_is_recorded(sqlite_database):
    migrations = await connection.get_pool().fetch(
        "SELECT version, name FROM schema_migrations ORDER BY version"
    )

    assert migrations == [
        {"version": 1, "name": "legacy_columns"},
        {"version": 2, "name": "indexes_after_columns"},
        {"version": 3, "name": "pending_captures"},
        {"version": 4, "name": "payment_cash_effect"},
        {"version": 5, "name": "debt_payment_principal_amount"},
        {"version": 6, "name": "weekly_budget"},
        {"version": 7, "name": "nullable_weekly_budget_limits"},
        {"version": 8, "name": "manual_capture_sessions"},
        {"version": 9, "name": "source_idempotency"},
    ]


async def test_pending_capture_round_trip_preserves_reply_context(sqlite_database):
    await queries.create_pending_capture(
        tg_message_id=123,
        source="бот-текст",
        draft={"amount": None, "date": date(2026, 9, 8)},
        context="⚠️ Не разобрал уверенно",
    )

    pending = await queries.get_pending_capture(123)

    assert pending == {
        "tg_message_id": 123,
        "source": "бот-текст",
        "context": "⚠️ Не разобрал уверенно",
        "draft": {"amount": None, "date": "2026-09-08"},
    }
    await queries.delete_pending_capture(123)
    assert await queries.get_pending_capture(123) is None


async def test_legacy_schema_is_migrated_before_indexes(tmp_path, monkeypatch):
    await connection.close_pool()
    database_path = tmp_path / "legacy-without-index-columns.db"
    legacy_schema = connection.BASE_SCHEMA
    for fragment in (
        "  transfer_direction TEXT CHECK (transfer_direction IN ('in','out','self')),\n",
        "  subscription_id INTEGER REFERENCES subscriptions(id),\n",
        "  loan_name TEXT,\n",
        "  contract_ref TEXT,\n",
        "  opened_at TEXT,\n",
        "  next_payment_amount INTEGER,\n",
        "  next_payment_date TEXT,\n",
        "  payment_day INTEGER,\n",
        "  principal_amount INTEGER,\n",
        "  archived    INTEGER NOT NULL DEFAULT 0,\n",
        "  cash_effect  TEXT    NOT NULL DEFAULT 'movement'\n"
        "               CHECK (cash_effect IN ('movement','already_in_balance')),\n",
        "  cash_effect      TEXT    NOT NULL DEFAULT 'movement'\n"
        "                   CHECK (cash_effect IN ('movement','already_in_balance')),\n",
        "  idempotency_key TEXT\n",
        "  payment_type TEXT NOT NULL DEFAULT 'regular',\n",
        "  reason       TEXT,\n",
        "  idempotency_key  TEXT\n",
    ):
        legacy_schema = legacy_schema.replace(fragment, "")
    legacy_schema = legacy_schema.replace(",\n);", "\n);")

    with sqlite3.connect(database_path) as legacy:
        legacy.executescript(legacy_schema)

    monkeypatch.setattr(connection, "DB_PATH", str(database_path))
    monkeypatch.setattr(connection, "DB_REQUIRE_PERSISTENT_DIR", False)
    await connection.init_pool()
    try:
        columns = {
            row["name"]
            for row in await connection.get_pool().fetch(
                "PRAGMA table_info(debt_payments)"
            )
        }
        indexes = {
            row["name"]
            for row in await connection.get_pool().fetch(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            )
        }
        assert {
            "payment_type", "reason", "idempotency_key", "cash_effect",
            "principal_amount",
        } <= columns
        assert {
            "idx_debt_payments_idempotency",
            "idx_personal_debt_payments_idempotency",
            "idx_operations_subscription_id",
        } <= indexes
    finally:
        await connection.close_pool()
