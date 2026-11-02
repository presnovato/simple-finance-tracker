"""Криптоактивы.

Выделено из ``queries.py`` при разбиении oversized-модуля; код перенесён без
изменений.
"""

from datetime import date
from decimal import Decimal

from finance_bot.core.crypto import apply_crypto_transaction
from finance_bot.database.connection import get_pool

from ._common import _row, _rows, to_cents

# --- криптоактивы --------------------------------------------------------

def _decimal_text(value: Decimal) -> str:
    text = format(Decimal(value), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


async def list_crypto_holdings() -> list[dict]:
    rows = await get_pool().fetch(
        "SELECT * FROM crypto_holdings ORDER BY asset"
    )
    return _rows(rows)


async def list_crypto_transactions(limit: int = 50) -> list[dict]:
    rows = await get_pool().fetch(
        """
        SELECT * FROM crypto_transactions
        ORDER BY op_date DESC, id DESC
        LIMIT ?
        """,
        limit,
    )
    return _rows(rows)


async def insert_crypto_transaction(
    *,
    asset: str,
    quantity_delta: Decimal,
    rub_amount: Decimal,
    op_date: date,
    comment: str | None,
) -> dict:
    """Атомарно создаёт перевод рублей и движение криптоостатка."""
    asset = asset.strip().upper()
    quantity_delta = Decimal(quantity_delta)
    if quantity_delta == 0:
        raise ValueError("изменение количества криптовалюты не может быть нулевым")

    # Положительный delta — покупка крипты: рубли уходят из фиата.
    # Отрицательный delta — продажа: рубли возвращаются.
    direction = "out" if quantity_delta > 0 else "in"
    operation_comment = comment or (
        f"Покупка {asset}" if direction == "out" else f"Продажа {asset}"
    )
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            holding = await conn.fetchrow(
                "SELECT quantity FROM crypto_holdings WHERE asset = ?", asset
            )
            current_quantity = (
                Decimal(str(holding["quantity"])) if holding else Decimal("0")
            )
            new_quantity = apply_crypto_transaction(
                current_quantity, quantity_delta
            )
            operation = await conn.fetchrow(
                """
                INSERT INTO operations (
                  op_date, type, amount, category, comment, account,
                  transfer_direction, source, needs_review
                ) VALUES (?, 'перевод', ?, NULL, ?, NULL, ?, 'tma-крипта', 0)
                RETURNING id
                """,
                op_date.isoformat(),
                to_cents(rub_amount),
                operation_comment,
                direction,
            )
            if operation is None:
                raise RuntimeError("SQLite не вернул id криптооперации")
            transaction = await conn.fetchrow(
                """
                INSERT INTO crypto_transactions (
                  asset, quantity_delta, rub_amount, op_date, operation_id, comment
                ) VALUES (?, ?, ?, ?, ?, ?)
                RETURNING *
                """,
                asset,
                _decimal_text(quantity_delta),
                to_cents(rub_amount),
                op_date.isoformat(),
                operation["id"],
                comment,
            )
            if transaction is None:
                raise RuntimeError("SQLite не вернул криптотранзакцию")
            if holding:
                await conn.execute(
                    """
                    UPDATE crypto_holdings
                    SET quantity = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%S+00:00','now')
                    WHERE asset = ?
                    """,
                    _decimal_text(new_quantity),
                    asset,
                )
            else:
                await conn.execute(
                    "INSERT INTO crypto_holdings (asset, quantity) VALUES (?, ?)",
                    asset,
                    _decimal_text(new_quantity),
                )
            return _row(transaction)


async def patch_crypto_holding(asset: str, quantity: Decimal) -> dict | None:
    asset = asset.strip().upper()
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            existing = await conn.fetchrow(
                "SELECT id FROM crypto_holdings WHERE asset = ?", asset
            )
            if existing:
                await conn.execute(
                    """
                    UPDATE crypto_holdings
                    SET quantity = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%S+00:00','now')
                    WHERE asset = ?
                    """,
                    _decimal_text(quantity),
                    asset,
                )
            else:
                await conn.execute(
                    "INSERT INTO crypto_holdings (asset, quantity) VALUES (?, ?)",
                    asset,
                    _decimal_text(quantity),
                )
            row = await conn.fetchrow(
                "SELECT * FROM crypto_holdings WHERE asset = ?", asset
            )
            return _row(row) if row else None


async def delete_crypto_transaction(transaction_id: int) -> dict | None:
    """Удаляет движение крипты, откатывает остаток и soft-delete операции."""
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            transaction = await conn.fetchrow(
                "SELECT * FROM crypto_transactions WHERE id = ?",
                transaction_id,
            )
            if transaction is None:
                return None
            holding = await conn.fetchrow(
                "SELECT quantity FROM crypto_holdings WHERE asset = ?",
                transaction["asset"],
            )
            current_quantity = (
                Decimal(str(holding["quantity"])) if holding else Decimal("0")
            )
            new_quantity = apply_crypto_transaction(
                current_quantity, -Decimal(str(transaction["quantity_delta"]))
            )
            if holding:
                await conn.execute(
                    """
                    UPDATE crypto_holdings
                    SET quantity = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%S+00:00','now')
                    WHERE asset = ?
                    """,
                    _decimal_text(new_quantity),
                    transaction["asset"],
                )
            await conn.execute(
                """
                UPDATE operations SET deleted_at = strftime('%Y-%m-%dT%H:%M:%S+00:00','now')
                WHERE id = ? AND deleted_at IS NULL
                """,
                transaction["operation_id"],
            )
            await conn.execute(
                "DELETE FROM crypto_transactions WHERE id = ?", transaction_id
            )
            return _row(transaction)
