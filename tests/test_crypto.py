from datetime import date
from decimal import Decimal

import pytest

from finance_bot.api.schemas import (ValidationError, crypto_asset,
                                     crypto_holding_patch,
                                     crypto_transaction_create)
from finance_bot.core.crypto import apply_crypto_transaction


def test_apply_crypto_transaction_and_reversal():
    assert apply_crypto_transaction("0.001", "0.0005") == Decimal("0.0015")
    assert apply_crypto_transaction("0.0015", "-0.0005") == Decimal("0.0010")
    with pytest.raises(ValueError):
        apply_crypto_transaction("0.001", "-0.002")


def test_crypto_schemas_keep_precision_and_normalize_asset():
    created = crypto_transaction_create({
        "asset": "btc",
        "quantity_delta": "0.00000001",
        "rub_amount": "5000",
        "op_date": "2026-08-01",
    }, date(2026, 8, 1))
    assert created["asset"] == "BTC"
    assert created["quantity_delta"] == Decimal("0.00000001")
    assert crypto_holding_patch({"quantity": "1.23456789"})["quantity"] == Decimal("1.23456789")
    assert crypto_asset("usdt") == "USDT"
    with pytest.raises(ValidationError):
        crypto_transaction_create({
            "asset": "BTC", "quantity_delta": "0", "rub_amount": "1"
        }, date(2026, 8, 1))
