"""Чистый расчёт якорного остатка денег."""

from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

MONEY_STEP = Decimal("0.01")
MAX_ABS_AMOUNT = Decimal("10000000000")


def parse_anchor_amount(value: str) -> Decimal:
    normalized = value.strip().replace(" ", "").replace(" ", "").replace(",", ".")
    try:
        amount = Decimal(normalized).quantize(MONEY_STEP, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("некорректная сумма") from exc
    if not amount.is_finite() or abs(amount) >= MAX_ABS_AMOUNT:
        raise ValueError("сумма вне допустимого диапазона")
    return amount


def calculate_cash_on_hand(
    anchor_amount: Decimal | None,
    income: Decimal = Decimal("0"),
    expense: Decimal = Decimal("0"),
    transfer_in: Decimal = Decimal("0"),
    transfer_out: Decimal = Decimal("0"),
) -> Decimal | None:
    if anchor_amount is None:
        return None
    return calculate_period_balance(
        Decimal(income), Decimal(expense), Decimal(transfer_in), Decimal(transfer_out),
        base=Decimal(anchor_amount),
    )


def calculate_period_balance(
    income: Decimal,
    expense: Decimal,
    transfer_in: Decimal = Decimal("0"),
    transfer_out: Decimal = Decimal("0"),
    *,
    base: Decimal = Decimal("0"),
) -> Decimal:
    """Баланс с учётом входящих/исходящих переводов; self-переводы не входят."""
    return (
        Decimal(base) + Decimal(income) - Decimal(expense)
        + Decimal(transfer_in) - Decimal(transfer_out)
    ).quantize(MONEY_STEP, rounding=ROUND_HALF_UP)


def counts_after_anchor(
    operation: dict, anchor_date: date, anchor_ts: datetime
) -> bool:
    """Двигала ли операция деньги уже после того, как остаток был пересчитан.

    Якорь — это момент времени, а не дата: сумма из `/balance` уже включает
    всё, что произошло раньше. Дни до якоря отбрасываются целиком, дни после
    берутся целиком, а внутри самого дня якоря операции различаются по
    `created_at` — при frictionless capture это близко к моменту траты.
    """
    op_date = operation["op_date"]
    if op_date > anchor_date:
        return True
    if op_date < anchor_date:
        return False
    created_at = operation.get("created_at")
    if created_at is None:
        return False
    if isinstance(created_at, str):
        created_at = datetime.fromisoformat(created_at)
    return created_at > anchor_ts


def movement_totals(
    operations: list[dict],
    anchor_date: date,
    anchor_ts: datetime,
    *,
    exclude_debt_transfers: bool = False,
) -> dict:
    """Эталонный расчёт для тестов и небольших наборов без зависимости от БД.

    ``debt_related`` — вычисляемый слой данных, а не колонка ``operations``.
    Для наличных такие переводы остаются движением денег, а для месячной
    дельты их можно исключить тем же правилом, что и в SQL-агрегате.
    """
    income = Decimal("0")
    expense = Decimal("0")
    transfer_in = Decimal("0")
    transfer_out = Decimal("0")
    count = 0
    for operation in operations:
        if operation.get("deleted_at"):
            continue
        if not counts_after_anchor(operation, anchor_date, anchor_ts):
            continue
        if (
            exclude_debt_transfers
            and operation.get("type") == "перевод"
            and operation.get("debt_related")
        ):
            continue
        amount = Decimal(operation["amount"])
        if operation["type"] == "доход":
            income += amount
            count += 1
        elif operation["type"] == "расход":
            expense += amount
            count += 1
        elif operation["type"] == "перевод":
            direction = operation.get("transfer_direction") or "out"
            if direction == "in":
                transfer_in += amount
                count += 1
            elif direction == "out":
                transfer_out += amount
                count += 1
    return {
        "income": income,
        "expense": expense,
        "transfer_in": transfer_in,
        "transfer_out": transfer_out,
        "movement_count": count,
    }


def format_cash_amount(value: Decimal, *, show_plus: bool = False) -> str:
    amount = Decimal(value).quantize(MONEY_STEP, rounding=ROUND_HALF_UP)
    sign = "−" if amount < 0 else "+" if show_plus and amount > 0 else ""
    formatted = f"{abs(amount):,.2f}".replace(",", " ").replace(".", ",")
    if formatted.endswith(",00"):
        formatted = formatted[:-3]
    return f"{sign}{formatted} ₽"
