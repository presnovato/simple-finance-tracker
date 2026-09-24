"""Общий сервис детерминированного создания финансовой операции."""

from datetime import date
from decimal import Decimal

from finance_bot.database import queries


async def create_operation(
    *,
    op_date: date,
    type_: str,
    amount: Decimal,
    category: str | None,
    comment: str | None,
    account: str | None,
    transfer_direction: str | None,
    source: str,
    check_duplicate: bool = False,
) -> tuple[dict, int | None]:
    """Создаёт операцию и возвращает её публичную строку и дубль, если он есть."""
    duplicate_id = None
    if check_duplicate:
        duplicate_id = await queries.find_possible_duplicates(
            op_date, amount, type_, category
        )

    operation_id = await queries.insert_operation(
        op_date=op_date,
        type_=type_,
        amount=amount,
        category=category,
        comment=comment,
        account=account,
        source=source,
        needs_review=False,
        transfer_direction=transfer_direction,
    )
    operation = await queries.get_operation(operation_id)
    if operation is None:
        raise RuntimeError("Не удалось прочитать созданную операцию")
    return operation, duplicate_id
