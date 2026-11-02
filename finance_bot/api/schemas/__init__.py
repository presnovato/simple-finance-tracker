"""Валидация и JSON-схемы API: пакет вместо одного модуля.

Публичный путь ``finance_bot.api.schemas.<name>`` сохранён: имена
реэкспортируются из подмодулей.
"""

from ._common import (
    ValidationError,
    decode_cursor,
    decimal_string,
    encode_cursor,
    iso_date,
    money,
    money_string,
    nonnegative_money,
    operation_json,
    query_bool,
    signed_money,
)
from .balance import (
    balance_anchor,
)
from .budget import (
    budget_settings,
    budget_week_start,
)
from .crypto import (
    crypto_asset,
    crypto_holding_json,
    crypto_holding_patch,
    crypto_overview_patch,
    crypto_quantity,
    crypto_transaction_create,
    crypto_transaction_json,
)
from .debts import (
    debt_adjust,
    debt_create,
    debt_patch,
    debt_payment,
)
from .operations import (
    operation_create,
    operation_patch,
    transfer_direction,
)
from .personal_debts import (
    personal_debt_create,
    personal_debt_patch,
)
from .subscriptions import (
    charge_request,
    subscription_create,
    subscription_json,
    subscription_patch,
)

__all__ = [
    "balance_anchor",
    "budget_settings",
    "budget_week_start",
    "charge_request",
    "crypto_asset",
    "crypto_holding_json",
    "crypto_holding_patch",
    "crypto_overview_patch",
    "crypto_quantity",
    "crypto_transaction_create",
    "crypto_transaction_json",
    "debt_adjust",
    "debt_create",
    "debt_patch",
    "debt_payment",
    "decimal_string",
    "decode_cursor",
    "encode_cursor",
    "iso_date",
    "money",
    "money_string",
    "nonnegative_money",
    "operation_create",
    "operation_json",
    "operation_patch",
    "personal_debt_create",
    "personal_debt_patch",
    "query_bool",
    "signed_money",
    "subscription_create",
    "subscription_json",
    "subscription_patch",
    "transfer_direction",
    "ValidationError",
]
