"""Чистые операции с остатком криптоактива."""

from decimal import Decimal


def apply_crypto_transaction(
    quantity: Decimal | str,
    quantity_delta: Decimal | str,
) -> Decimal:
    """Возвращает новый остаток и не допускает продажи сверх остатка."""
    result = Decimal(str(quantity)) + Decimal(str(quantity_delta))
    if result < 0:
        raise ValueError("нельзя продать больше криптовалюты, чем есть в остатке")
    return result
