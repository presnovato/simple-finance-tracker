"""In-memory API fixture for viewing every TMA section without SQLite or Telegram.

This server is deliberately local-only. It mirrors the response shapes used by
the production API closely enough to exercise the Overview, History, Debts,
Crypto, and Subscriptions screens, including their common mutations.
"""

import asyncio
import calendar
import logging
from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from aiohttp import web

logger = logging.getLogger(__name__)

EXPENSE_CATEGORIES = (
    "Жильё", "Продукты", "Готовая еда", "Кафе/Досуг", "Быт", "Техника",
    "Транспорт", "Лекарства", "Подписки", "Подарки", "Долги", "Прочее",
)
INCOME_CATEGORIES = ("Зарплата", "Реклама", "Услуги", "Подарки")
RHYTHM_EXPENSE_EXCLUDED_CATEGORIES = {"Жильё", "Долги"}
RHYTHM_INCOME_EXCLUDED_CATEGORIES = {"Зарплата"}

TODAY = date.today()
CURRENT_WEEK_START = TODAY - timedelta(days=TODAY.weekday())
PREVIOUS_WEEK_START = CURRENT_WEEK_START - timedelta(days=7)


def day(offset: int = 0) -> str:
    return (TODAY + timedelta(days=offset)).isoformat()


def timestamp(offset: int = 0, hour: int = 18) -> str:
    return f"{day(offset)}T{hour:02d}:00:00+03:00"


def money(value: Decimal | str | int) -> str:
    return f"{Decimal(str(value)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):.2f}"


def decimal_text(value: Decimal | str | int) -> str:
    text = format(Decimal(str(value)), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def decimal_value(value: object, default: str = "0") -> Decimal:
    try:
        return Decimal(str(default if value in (None, "") else value))
    except Exception as exc:
        raise web.HTTPBadRequest(text="некорректное число") from exc


def week_end(week_start: date) -> date:
    return week_start + timedelta(days=6)


def percentage(spent: Decimal, limit: Decimal) -> Decimal:
    return (spent * Decimal("100") / limit).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )


def status(spent: Decimal, limit: Decimal | None) -> str | None:
    if limit is None:
        return None
    if spent >= limit:
        return "exceeded"
    if spent * Decimal("100") >= limit * Decimal("80"):
        return "warning"
    return "ok"


def line(category: str, limit: Decimal | None, spent: Decimal) -> dict:
    if limit is None:
        return {
            "category": category,
            "limit": None,
            "spent": money(spent),
            "remaining": None,
            "percent": None,
            "status": None,
        }
    return {
        "category": category,
        "limit": money(limit),
        "spent": money(spent),
        "remaining": money(limit - spent),
        "percent": money(percentage(spent, limit)),
        "status": status(spent, limit),
    }


LIMITS = {
    "Продукты": Decimal("4500.00"),
    "Транспорт": Decimal("1800.00"),
    "Кафе/Досуг": Decimal("1500.00"),
    "Жильё": Decimal("3000.00"),
    "Долги": Decimal("1000.00"),
    "Прочее": Decimal("800.00"),
}

CURRENT_SPENT = {
    "Продукты": Decimal("3200.00"),
    "Транспорт": Decimal("1600.00"),
    "Кафе/Досуг": Decimal("950.00"),
    "Жильё": Decimal("2500.00"),
    "Долги": Decimal("650.00"),
    "Прочее": Decimal("300.00"),
    "Быт": Decimal("480.00"),
    "Лекарства": Decimal("720.00"),
    "Подарки": Decimal("1600.00"),
    "Подписки": Decimal("399.00"),
}

PREVIOUS_SPENT = {
    "Продукты": Decimal("2800.00"),
    "Транспорт": Decimal("600.00"),
    "Кафе/Досуг": Decimal("400.00"),
    "Жильё": Decimal("2300.00"),
    "Долги": Decimal("500.00"),
    "Прочее": Decimal("150.00"),
}

settings = {
    "overall_limit": Decimal("10000.00"),
    "categories": dict(LIMITS),
}

cash_balance = {
    "has_anchor": True,
    "amount": "186400.00",
    "anchor_date": day(),
    "anchor_amount": "190000.00",
}


def make_operation(
    op_id: int,
    offset: int,
    type_: str,
    amount: str,
    category: str | None,
    comment: str,
    *,
    account: str = "Тинькофф Black",
    note: str | None = None,
    transfer_direction: str | None = None,
    needs_review: bool = False,
    source: str = "mock",
    deleted_at: str | None = None,
    subscription_id: int | None = None,
) -> dict:
    return {
        "id": op_id,
        "created_at": timestamp(offset, 19),
        "op_date": day(offset),
        "type": type_,
        "amount": amount,
        "category": category,
        "comment": comment,
        "note": note,
        "account": account,
        "transfer_direction": transfer_direction,
        "source": source,
        "needs_review": needs_review,
        "tg_message_id": None,
        "deleted_at": deleted_at,
        "subscription_id": subscription_id,
    }


operations = [
    make_operation(
        120, 0, "расход", "3200.00", "Продукты",
        "Закупка продуктов на неделю",
        note="Проверить чек и разнести покупки",
        needs_review=True,
    ),
    make_operation(119, -1, "расход", "1200.00", "Транспорт", "Такси и метро"),
    make_operation(
        118, -2, "расход", "950.00", "Кафе/Досуг",
        "Ужин с друзьями", account="Сбербанк",
    ),
    make_operation(
        117, -3, "расход", "2500.00", "Жильё",
        "Коммунальные услуги", account="Сбербанк",
    ),
    make_operation(116, -4, "расход", "650.00", "Долги", "Платёж по кредитке"),
    make_operation(
        115, -5, "расход", "300.00", None,
        "Мелкие бытовые расходы", note="Категория не указана",
    ),
    make_operation(114, -6, "расход", "480.00", "Быт", "Средства для дома"),
    make_operation(113, -8, "расход", "720.00", "Лекарства", "Аптека"),
    make_operation(112, -10, "расход", "1600.00", "Подарки", "Подарок коллеге"),
    make_operation(111, -12, "расход", "400.00", "Транспорт", "Автобус между городами"),
    make_operation(
        110, 0, "расход", "399.00", "Подписки",
        "Яндекс Плюс", account="Тинькофф Black", subscription_id=501,
    ),
    make_operation(
        109, 0, "доход", "120000.00", "Зарплата",
        "Зарплата за сентябрь", account="Сбербанк",
    ),
    make_operation(
        108, 0, "перевод", "15000.00", None,
        "Перевод в накопления", account="Сбербанк",
        transfer_direction="self",
    ),
    make_operation(
        104, -7, "доход", "18000.00", "Услуги",
        "Аванс за консультацию", account="Сбербанк",
    ),
    make_operation(
        107, -9, "расход", "2100.00", "Продукты",
        "Продукты на прошлой неделе",
    ),
    make_operation(
        106, -8, "доход", "118000.00", "Зарплата",
        "Зарплата за август", account="Сбербанк",
    ),
    make_operation(
        105, -2, "расход", "500.00", "Продукты",
        "Удалённая тестовая операция",
        deleted_at=timestamp(-2, 20),
    ),
]


def visible_operations() -> list[dict]:
    return [
        item for item in operations
        if item.get("deleted_at") is None
    ]


def summary_payload(month: str) -> dict:
    try:
        start = date.fromisoformat(f"{month}-01")
    except ValueError as exc:
        raise web.HTTPBadRequest(text="некорректный месяц") from exc
    next_month = (
        date(start.year + 1, 1, 1)
        if start.month == 12
        else date(start.year, start.month + 1, 1)
    )
    month_end = next_month - timedelta(days=1)
    chart_end = min(month_end, TODAY) if start <= TODAY else month_end
    day_totals: dict[str, dict[str, Decimal]] = {}
    category_totals: dict[str, Decimal] = {}
    expense = Decimal("0")
    income = Decimal("0")
    transfer_in = Decimal("0")
    transfer_out = Decimal("0")
    for operation in visible_operations():
        op_date = date.fromisoformat(operation["op_date"])
        if not start <= op_date <= month_end:
            continue
        amount = decimal_value(operation["amount"])
        bucket = day_totals.setdefault(
            operation["op_date"],
            {"expense": Decimal("0"), "income": Decimal("0")},
        )
        if operation["type"] == "расход":
            expense += amount
            if operation["category"] not in RHYTHM_EXPENSE_EXCLUDED_CATEGORIES:
                bucket["expense"] += amount
            category = operation["category"] or "Прочее"
            category_totals[category] = category_totals.get(category, Decimal("0")) + amount
        elif operation["type"] == "доход":
            income += amount
            if operation["category"] not in RHYTHM_INCOME_EXCLUDED_CATEGORIES:
                bucket["income"] += amount
        elif operation["type"] == "перевод":
            if operation.get("transfer_direction") == "in":
                transfer_in += amount
            elif operation.get("transfer_direction") in (None, "out"):
                transfer_out += amount

    days = []
    cursor = start
    while cursor <= chart_end:
        key = cursor.isoformat()
        totals = day_totals.get(
            key, {"expense": Decimal("0"), "income": Decimal("0")}
        )
        days.append({
            "op_date": key,
            "expense": money(totals["expense"]),
            "income": money(totals["income"]),
        })
        cursor += timedelta(days=1)

    chart_expense_total = sum((item["expense"] for item in day_totals.values()), Decimal("0"))
    chart_income_total = sum((item["income"] for item in day_totals.values()), Decimal("0"))
    expense_days = sum(1 for item in day_totals.values() if item["expense"] != 0)
    income_days = sum(1 for item in day_totals.values() if item["income"] != 0)

    return {
        "month": month,
        "period_mode": "month",
        "period_start": start.isoformat(),
        "period_end": chart_end.isoformat(),
        "chart_start": start.isoformat(),
        "chart_end": chart_end.isoformat(),
        "expense": money(expense),
        "income": money(income),
        "transfer_in": money(transfer_in),
        "transfer_out": money(transfer_out),
        "balance": money(income - expense + transfer_in - transfer_out),
        "average_daily": money(
            chart_expense_total / expense_days if expense_days else Decimal("0")
        ),
        "average_daily_income": money(
            chart_income_total / income_days if income_days else Decimal("0")
        ),
        "days": days,
        "categories": [
            {"category": category, "total": money(amount)}
            for category, amount in sorted(
                category_totals.items(), key=lambda item: item[1], reverse=True
            )
        ],
    }


def budget_for(week_start: date) -> dict:
    is_current = week_start == CURRENT_WEEK_START
    spent_by_category = CURRENT_SPENT if is_current else PREVIOUS_SPENT
    categories = [
        line(category, limit, spent_by_category.get(category, Decimal("0")))
        for category, limit in settings["categories"].items()
    ]
    selected_spent = sum(
        (spent_by_category.get(category, Decimal("0"))
         for category in settings["categories"]),
        Decimal("0"),
    )
    overall_limit = settings["overall_limit"]
    previous = None if week_start == PREVIOUS_WEEK_START else PREVIOUS_WEEK_START
    following = CURRENT_WEEK_START if week_start == PREVIOUS_WEEK_START else None
    overall = None
    if overall_limit is not None:
        overall = {
            "limit": money(overall_limit),
            "spent": money(selected_spent),
            "remaining": money(overall_limit - selected_spent),
            "percent": money(percentage(selected_spent, overall_limit)),
            "status": status(selected_spent, overall_limit),
        }
    return {
        "configured": True,
        "week_start": week_start.isoformat(),
        "week_end": week_end(week_start).isoformat(),
        "is_current": is_current,
        "selected_spent": money(selected_spent),
        "category_limits_total": money(sum(
            (limit for limit in settings["categories"].values() if limit is not None),
            Decimal("0"),
        )),
        "overall": overall,
        "categories": categories,
        "previous_week_start": previous.isoformat() if previous else None,
        "next_week_start": following.isoformat() if following else None,
    }


crypto_holdings = [
    {"asset": "BTC", "quantity": "0.0842", "updated_at": timestamp(-1, 21)},
    {"asset": "ETH", "quantity": "1.735", "updated_at": timestamp(-4, 18)},
    {"asset": "USDT", "quantity": "420.00", "updated_at": timestamp(-7, 12)},
]

crypto_transactions = [
    {
        "id": 401, "asset": "BTC", "quantity_delta": "0.025",
        "rub_amount": "180000.00", "op_date": day(-40),
        "operation_id": None, "comment": "Покупка на просадке",
    },
    {
        "id": 402, "asset": "ETH", "quantity_delta": "1.735",
        "rub_amount": "420000.00", "op_date": day(-28),
        "operation_id": None, "comment": "Пополнение кошелька",
    },
    {
        "id": 403, "asset": "BTC", "quantity_delta": "-0.006",
        "rub_amount": "47000.00", "op_date": day(-12),
        "operation_id": None, "comment": "Частичная фиксация",
    },
    {
        "id": 404, "asset": "USDT", "quantity_delta": "420",
        "rub_amount": "38500.00", "op_date": day(-7),
        "operation_id": None, "comment": "Резерв для поездки",
    },
]
crypto_overview_visible = True


def make_debt(
    debt_id: int,
    creditor: str,
    loan_name: str,
    principal: str,
    balance: str,
    *,
    rate: str | None,
    min_payment: str | None,
    next_payment_amount: str | None,
    opened_offset: int,
    next_payment_offset: int | None,
    priority: int | None,
    due_offset: int | None,
    status_: str = "active",
    archived: bool = False,
    contract_ref: str | None = None,
) -> dict:
    return {
        "id": debt_id,
        "creditor": creditor,
        "loan_name": loan_name,
        "contract_ref": contract_ref,
        "principal": principal,
        "balance": balance,
        "rate": rate,
        "min_payment": min_payment,
        "next_payment_amount": next_payment_amount,
        "opened_at": day(opened_offset),
        "next_payment_date": day(next_payment_offset) if next_payment_offset is not None else None,
        "payment_day": None,
        "priority": priority,
        "due_date": day(due_offset) if due_offset is not None else None,
        "status": status_,
        "archived": archived,
        "created_at": timestamp(opened_offset, 10),
    }


debts = [
    make_debt(
        1, "Альфа-Банк", "Кредитная карта", "180000.00", "124500.00",
        rate="29.90", min_payment="8500.00", next_payment_amount="8500.00",
        opened_offset=-220, next_payment_offset=5, priority=1, due_offset=510,
        contract_ref="•••• 7788",
    ),
    make_debt(
        2, "Тинькофф", "Рассрочка на технику", "65000.00", "38700.00",
        rate="0.00", min_payment="5400.00", next_payment_amount="5400.00",
        opened_offset=-150, next_payment_offset=12, priority=2, due_offset=210,
        contract_ref="рассрочка",
    ),
    make_debt(
        3, "М.Видео", "Ноутбук", "42000.00", "0.00",
        rate="0.00", min_payment=None, next_payment_amount=None,
        opened_offset=-420, next_payment_offset=None, priority=3, due_offset=-30,
        status_="closed",
    ),
    make_debt(
        4, "Сбербанк", "Старая карта", "30000.00", "0.00",
        rate="24.90", min_payment=None, next_payment_amount=None,
        opened_offset=-700, next_payment_offset=None, priority=None, due_offset=-300,
        status_="closed", archived=True,
    ),
]

debt_history = {
    1: [
        {
            "id": 201, "debt_id": 1, "operation_id": None, "pay_date": day(-110),
            "amount": "15000.00", "principal_amount": "12000.00",
            "interest_amount": "3000.00", "kind": "payment",
            "payment_type": "regular", "cash_effect": "movement", "reason": None,
        },
        {
            "id": 202, "debt_id": 1, "operation_id": None, "pay_date": day(-82),
            "amount": "16500.00", "principal_amount": "13000.00",
            "interest_amount": "3500.00", "kind": "payment",
            "payment_type": "regular", "cash_effect": "movement", "reason": None,
        },
        {
            "id": 203, "debt_id": 1, "operation_id": None, "pay_date": day(-54),
            "amount": "18000.00", "principal_amount": "14500.00",
            "interest_amount": "3500.00", "kind": "payment",
            "payment_type": "early", "cash_effect": "movement", "reason": None,
        },
        {
            "id": 204, "debt_id": 1, "operation_id": None, "pay_date": day(-26),
            "amount": "19500.00", "principal_amount": "16000.00",
            "interest_amount": "3500.00", "kind": "payment",
            "payment_type": "regular", "cash_effect": "movement", "reason": None,
        },
    ],
    2: [
        {
            "id": 205, "debt_id": 2, "operation_id": None, "pay_date": day(-80),
            "amount": "9500.00", "principal_amount": "9000.00",
            "interest_amount": "500.00", "kind": "payment",
            "payment_type": "regular", "cash_effect": "movement", "reason": None,
        },
        {
            "id": 206, "debt_id": 2, "operation_id": None, "pay_date": day(-52),
            "amount": "9000.00", "principal_amount": "8500.00",
            "interest_amount": "500.00", "kind": "payment",
            "payment_type": "regular", "cash_effect": "movement", "reason": None,
        },
        {
            "id": 207, "debt_id": 2, "operation_id": None, "pay_date": day(-24),
            "amount": "10000.00", "principal_amount": "8800.00",
            "interest_amount": "1200.00", "kind": "payment",
            "payment_type": "regular", "cash_effect": "movement", "reason": None,
        },
    ],
    3: [
        {
            "id": 208, "debt_id": 3, "operation_id": None, "pay_date": day(-180),
            "amount": "7300.00", "principal_amount": "7000.00",
            "interest_amount": "300.00", "kind": "payment",
            "payment_type": "regular", "cash_effect": "movement", "reason": None,
        },
        {
            "id": 209, "debt_id": 3, "operation_id": None, "pay_date": day(-150),
            "amount": "7300.00", "principal_amount": "7000.00",
            "interest_amount": "300.00", "kind": "payment",
            "payment_type": "regular", "cash_effect": "movement", "reason": None,
        },
        {
            "id": 210, "debt_id": 3, "operation_id": None, "pay_date": day(-120),
            "amount": "7300.00", "principal_amount": "7000.00",
            "interest_amount": "300.00", "kind": "payment",
            "payment_type": "regular", "cash_effect": "movement", "reason": None,
        },
        {
            "id": 211, "debt_id": 3, "operation_id": None,
            "pay_date": day(-90), "amount": "7300.00",
            "principal_amount": "7000.00", "interest_amount": "300.00",
            "kind": "payment", "payment_type": "regular",
            "cash_effect": "movement", "reason": None,
        },
        {
            "id": 212, "debt_id": 3, "operation_id": None, "pay_date": day(-60),
            "amount": "7300.00", "principal_amount": "7000.00",
            "interest_amount": "300.00", "kind": "payment",
            "payment_type": "regular", "cash_effect": "movement", "reason": None,
        },
        {
            "id": 213, "debt_id": 3, "operation_id": None, "pay_date": day(-30),
            "amount": "7300.00", "principal_amount": "7000.00",
            "interest_amount": "300.00", "kind": "payment",
            "payment_type": "regular", "cash_effect": "movement", "reason": None,
        },
    ],
}

personal_debts = [
    {
        "id": 11, "person": "Анна", "direction": "owed_to_me",
        "principal": "28000.00", "balance": "18000.00",
        "opened_at": day(-45), "due_date": day(10), "comment": "За билеты и отель",
        "status": "open", "archived": False, "operation_id": None,
        "payment_count": 1,
    },
    {
        "id": 12, "person": "Илья", "direction": "i_owe",
        "principal": "15000.00", "balance": "9000.00",
        "opened_at": day(-30), "due_date": day(20), "comment": "Вернуть за ремонт",
        "status": "open", "archived": False, "operation_id": None,
        "payment_count": 1,
    },
    {
        "id": 13, "person": "Мария", "direction": "owed_to_me",
        "principal": "12000.00", "balance": "0.00",
        "opened_at": day(-180), "due_date": day(-20), "comment": "Закрыт полностью",
        "status": "closed", "archived": False, "operation_id": None,
        "payment_count": 2,
    },
    {
        "id": 14, "person": "Олег", "direction": "i_owe",
        "principal": "8000.00", "balance": "3500.00",
        "opened_at": day(-260), "due_date": day(-90), "comment": "Старая запись",
        "status": "open", "archived": True, "operation_id": None,
        "payment_count": 0,
    },
]

personal_debt_history = {
    11: [{
        "id": 301, "personal_debt_id": 11, "operation_id": None,
        "pay_date": day(-18), "amount": "10000.00",
        "principal_amount": "10000.00", "interest_amount": None,
        "kind": "payment", "payment_type": "regular",
        "cash_effect": "movement", "reason": None,
    }],
    12: [{
        "id": 302, "personal_debt_id": 12, "operation_id": None,
        "pay_date": day(-10), "amount": "6000.00",
        "principal_amount": "6000.00", "interest_amount": None,
        "kind": "payment", "payment_type": "regular",
        "cash_effect": "movement", "reason": None,
    }],
    13: [
        {
            "id": 303, "personal_debt_id": 13, "operation_id": None,
            "pay_date": day(-120), "amount": "7000.00",
            "principal_amount": "7000.00", "interest_amount": None,
            "kind": "payment", "payment_type": "regular",
            "cash_effect": "movement", "reason": None,
        },
        {
            "id": 304, "personal_debt_id": 13, "operation_id": None,
            "pay_date": day(-80), "amount": "5000.00",
            "principal_amount": "5000.00", "interest_amount": None,
            "kind": "payment", "payment_type": "regular",
            "cash_effect": "movement", "reason": None,
        },
    ],
    14: [],
}


def debt_progress(principal: str, balance: str) -> Decimal:
    principal_value = decimal_value(principal)
    if principal_value <= 0:
        return Decimal("0")
    result = (principal_value - decimal_value(balance)) * Decimal("100") / principal_value
    return max(Decimal("0"), min(Decimal("100"), result))


def debt_payload(debt: dict) -> dict:
    result = deepcopy(debt)
    history = debt_history.get(debt["id"], [])
    result["maturity_date"] = result.get("due_date")
    result["forecast_date"] = (
        day(180) if debt["status"] == "active" and not debt["archived"] else None
    )
    result["payment_count"] = sum(item["kind"] == "payment" for item in history)
    result["history_count"] = len(history)
    result["progress"] = money(debt_progress(debt["principal"], debt["balance"]))
    return result


def debts_summary_payload() -> dict:
    rows = [item for item in debts if not item["archived"]]
    total_principal = sum(
        (decimal_value(item["principal"]) for item in rows), Decimal("0")
    )
    total_balance = sum(
        (decimal_value(item["balance"]) for item in rows), Decimal("0")
    )
    curve = [
        {"month": (TODAY - timedelta(days=150)).strftime("%Y-%m"), "balance": "236000.00"},
        {"month": (TODAY - timedelta(days=120)).strftime("%Y-%m"), "balance": "219000.00"},
        {"month": (TODAY - timedelta(days=90)).strftime("%Y-%m"), "balance": "202000.00"},
        {"month": (TODAY - timedelta(days=60)).strftime("%Y-%m"), "balance": "181000.00"},
        {"month": (TODAY - timedelta(days=30)).strftime("%Y-%m"), "balance": "170000.00"},
        {"month": TODAY.strftime("%Y-%m"), "balance": money(total_balance)},
    ]
    return {
        "total_principal": money(total_principal),
        "total_balance": money(total_balance),
        "total_paid": money(total_principal - total_balance),
        "progress": money(
            (total_principal - total_balance) * Decimal("100") / total_principal
            if total_principal else Decimal("0")
        ),
        "active_count": sum(item["status"] == "active" for item in rows),
        "closed_count": sum(item["status"] == "closed" for item in rows),
        "curve": curve,
    }


subscriptions = [
    {
        "id": 501, "title": "Яндекс Плюс", "amount": "399.00",
        "period": "monthly", "next_charge": day(-1), "category": "Подписки",
        "comment": "Музыка и фильмы", "status": "active",
        "created_at": timestamp(-140, 10),
    },
    {
        "id": 502, "title": "Облако", "amount": "299.00",
        "period": "monthly", "next_charge": day(8), "category": "Подписки",
        "comment": "Диск 200 ГБ", "status": "active",
        "created_at": timestamp(-100, 10),
    },
    {
        "id": 503, "title": "Figma Professional", "amount": "12000.00",
        "period": "yearly", "next_charge": day(20), "category": "Подписки",
        "comment": "Годовая лицензия", "status": "active",
        "created_at": timestamp(-360, 10),
    },
    {
        "id": 504, "title": "Онлайн-кинотеатр", "amount": "699.00",
        "period": "monthly", "next_charge": day(24), "category": "Подписки",
        "comment": "Семейный тариф", "status": "active",
        "created_at": timestamp(-60, 10),
    },
    {
        "id": 505, "title": "VPN", "amount": "249.00",
        "period": "monthly", "next_charge": day(-40), "category": "Подписки",
        "comment": "Отменённая подписка", "status": "cancelled",
        "created_at": timestamp(-240, 10),
    },
]


def add_period(value: date, period: str) -> date:
    if period == "yearly":
        return value.replace(year=value.year + 1)
    next_month = value.month + 1
    year = value.year + (1 if next_month == 13 else 0)
    month = 1 if next_month == 13 else next_month
    return date(year, month, min(value.day, calendar.monthrange(year, month)[1]))


def subscription_payload(subscription: dict, *, due: bool | None = None) -> dict:
    result = deepcopy(subscription)
    result["amount"] = money(result["amount"])
    if due is not None:
        result["due"] = due
    return result


def subscriptions_payload(status_: str) -> dict:
    rows = [item for item in subscriptions if item["status"] == status_]
    if status_ == "cancelled":
        return {
            "items": [subscription_payload(item, due=False) for item in rows],
            "monthly_cost": None,
            "yearly_cost": None,
            "month_expenses": None,
            "share_percent": None,
            "upcoming": [],
        }

    monthly = sum(
        (decimal_value(item["amount"]) / Decimal("12")
         if item["period"] == "yearly"
         else decimal_value(item["amount"]) for item in rows),
        Decimal("0"),
    )
    yearly = sum(
        (decimal_value(item["amount"]) * Decimal("12")
         if item["period"] == "monthly"
         else decimal_value(item["amount"]) for item in rows),
        Decimal("0"),
    )
    month_expenses = decimal_value(
        summary_payload(TODAY.strftime("%Y-%m"))["expense"]
    )
    share = (
        monthly * Decimal("100") / month_expenses
        if month_expenses else None
    )
    upcoming = []
    for item in rows:
        charge_date = date.fromisoformat(item["next_charge"])
        if TODAY < charge_date <= TODAY + timedelta(days=30):
            upcoming.append({
                "subscription_id": item["id"],
                "title": item["title"],
                "amount": money(item["amount"]),
                "charge_date": item["next_charge"],
            })
    upcoming.sort(key=lambda item: item["charge_date"])
    return {
        "items": [
            subscription_payload(
                item,
                due=date.fromisoformat(item["next_charge"]) <= TODAY,
            )
            for item in rows
        ],
        "monthly_cost": money(monthly),
        "yearly_cost": money(yearly),
        "month_expenses": money(month_expenses),
        "share_percent": f"{share:.1f}" if share is not None else None,
        "upcoming": upcoming,
    }


async def read_json(request: web.Request) -> dict:
    try:
        payload = await request.json()
    except (web.HTTPBadRequest, ValueError):
        raise web.HTTPBadRequest(text="invalid JSON")
    if not isinstance(payload, dict):
        raise web.HTTPBadRequest(text="JSON object expected")
    return payload


def error(message: str, status_code: int = 400) -> web.Response:
    return web.json_response({"error": message}, status=status_code)


async def summary(request: web.Request) -> web.Response:
    try:
        payload = summary_payload(
            request.query.get("month", TODAY.strftime("%Y-%m"))
        )
    except web.HTTPBadRequest as exc:
        return error(exc.text)
    return web.json_response(payload)


async def operations_endpoint(request: web.Request) -> web.Response:
    rows = visible_operations()
    category = request.query.get("category")
    type_ = request.query.get("type")
    op_date = request.query.get("date")
    try:
        date_from = (
            date.fromisoformat(request.query["date_from"])
            if request.query.get("date_from") else None
        )
        date_to = (
            date.fromisoformat(request.query["date_to"])
            if request.query.get("date_to") else None
        )
    except ValueError:
        return error("дата должна быть в формате YYYY-MM-DD")
    if date_from is not None and date_to is not None and date_from > date_to:
        return error("начало периода не может быть позже конца")
    query = (request.query.get("q") or "").strip().lower()
    needs_review = request.query.get("needs_review") in {"1", "true"}
    if category:
        rows = [
            item for item in rows
            if (item["category"] or "Прочее") == category
        ]
    if type_:
        rows = [item for item in rows if item["type"] == type_]
    if op_date:
        rows = [item for item in rows if item["op_date"] == op_date]
    if date_from is not None:
        rows = [
            item for item in rows
            if date.fromisoformat(item["op_date"]) >= date_from
        ]
    if date_to is not None:
        rows = [
            item for item in rows
            if date.fromisoformat(item["op_date"]) <= date_to
        ]
    if needs_review:
        rows = [item for item in rows if item["needs_review"]]
    if query:
        rows = [
            item for item in rows
            if query in " ".join(
                str(item.get(field) or "")
                for field in ("comment", "note", "category", "account")
            ).lower()
        ]
    rows.sort(key=lambda item: (item["op_date"], item["id"]), reverse=True)
    totals = {
        "total_count": len(rows),
        "expense": sum(
            (decimal_value(item["amount"]) for item in rows if item["type"] == "расход"),
            Decimal("0"),
        ),
        "income": sum(
            (decimal_value(item["amount"]) for item in rows if item["type"] == "доход"),
            Decimal("0"),
        ),
        "transfer": sum(
            (decimal_value(item["amount"]) for item in rows if item["type"] == "перевод"),
            Decimal("0"),
        ),
    }
    return web.json_response({
        "items": deepcopy(rows[:40]),
        "next_cursor": None,
        "totals": {
            "total_count": totals["total_count"],
            "expense": money(totals["expense"]),
            "income": money(totals["income"]),
            "transfer": money(totals["transfer"]),
        },
    })


async def create_operation(request: web.Request) -> web.Response:
    payload = await read_json(request)
    type_ = payload.get("type")
    if type_ not in {"расход", "доход", "перевод"}:
        return error("неизвестный тип операции")
    try:
        amount = decimal_value(payload.get("amount"))
        op_date = date.fromisoformat(str(payload.get("op_date") or day()))
    except (ValueError, web.HTTPBadRequest) as exc:
        if isinstance(exc, web.HTTPBadRequest) and exc.text == "некорректное число":
            return error(exc.text)
        return error("некорректная дата операции")
    if amount <= 0:
        return error("сумма должна быть положительной")
    if op_date > TODAY:
        return error("дата операции не может быть в будущем")

    if type_ == "перевод":
        category = None
        direction = payload.get("transfer_direction")
        if direction not in {"in", "out", "self"}:
            return error("у перевода должно быть направление")
    else:
        direction = None
        category = payload.get("category")
        allowed = EXPENSE_CATEGORIES if type_ == "расход" else INCOME_CATEGORIES
        if category not in allowed:
            return error("неизвестная категория операции")

    operation_id = max((item["id"] for item in operations), default=0) + 1
    operation = make_operation(
        operation_id,
        0,
        type_,
        money(amount),
        category,
        str(payload.get("comment") or "Без описания").strip(),
        account=str(payload.get("account") or "Тинькофф Black").strip(),
        transfer_direction=direction,
        source="tma-ручной",
    )
    operation["op_date"] = op_date.isoformat()
    operations.insert(0, operation)
    return web.json_response(deepcopy(operation), status=201)


async def patch_operation(request: web.Request) -> web.Response:
    try:
        op_id = int(request.match_info["id"])
    except ValueError:
        return error("некорректный id")
    operation = next((item for item in operations if item["id"] == op_id), None)
    if operation is None or operation.get("deleted_at") is not None:
        return error("операция не найдена", 404)
    payload = await read_json(request)
    for field in (
        "category", "op_date", "type", "comment", "note", "account",
        "transfer_direction",
    ):
        if field in payload:
            operation[field] = payload[field]
    if "amount" in payload:
        operation["amount"] = money(decimal_value(payload["amount"]))
    return web.json_response(deepcopy(operation))


async def confirm_operation(request: web.Request) -> web.Response:
    try:
        op_id = int(request.match_info["id"])
    except ValueError:
        return error("некорректный id")
    operation = next((item for item in operations if item["id"] == op_id), None)
    if operation is None or operation.get("deleted_at") is not None:
        return error("операция не найдена", 404)
    operation["needs_review"] = False
    return web.json_response(deepcopy(operation))


async def delete_operation(request: web.Request) -> web.Response:
    try:
        op_id = int(request.match_info["id"])
    except ValueError:
        return error("некорректный id")
    operation = next((item for item in operations if item["id"] == op_id), None)
    if operation is None or operation.get("deleted_at") is not None:
        return error("операция не найдена", 404)
    operation["deleted_at"] = timestamp()
    return web.json_response({"deleted": True, "id": op_id})


async def restore_operation(request: web.Request) -> web.Response:
    try:
        op_id = int(request.match_info["id"])
    except ValueError:
        return error("некорректный id")
    operation = next((item for item in operations if item["id"] == op_id), None)
    if operation is None:
        return error("операция не найдена", 404)
    operation["deleted_at"] = None
    return web.json_response(deepcopy(operation))


async def balance(request: web.Request) -> web.Response:
    if request.method == "PATCH":
        payload = await read_json(request)
        if "amount" in payload:
            cash_balance["anchor_amount"] = money(decimal_value(payload["amount"]))
            cash_balance["amount"] = cash_balance["anchor_amount"]
        if payload.get("anchor_date"):
            cash_balance["anchor_date"] = str(payload["anchor_date"])
        cash_balance["has_anchor"] = True
    return web.json_response(deepcopy(cash_balance))


async def crypto_endpoint(_: web.Request) -> web.Response:
    return web.json_response({
        "items": deepcopy(crypto_holdings),
        "transactions": deepcopy(crypto_transactions),
        "overview_visible": crypto_overview_visible,
    })


async def crypto_overview(request: web.Request) -> web.Response:
    global crypto_overview_visible
    if request.method == "PATCH":
        payload = await read_json(request)
        if not isinstance(payload.get("visible"), bool):
            return error("visible должен быть boolean")
        crypto_overview_visible = payload["visible"]
    return web.json_response({"overview_visible": crypto_overview_visible})


async def create_crypto_transaction(request: web.Request) -> web.Response:
    payload = await read_json(request)
    transaction = {
        "id": max((item["id"] for item in crypto_transactions), default=400) + 1,
        "asset": str(payload.get("asset") or "").upper(),
        "quantity_delta": decimal_text(payload.get("quantity_delta")),
        "rub_amount": money(decimal_value(payload.get("rub_amount"))),
        "op_date": str(payload.get("op_date") or day()),
        "operation_id": None,
        "comment": payload.get("comment"),
    }
    if not transaction["asset"]:
        return error("asset обязателен")
    crypto_transactions.insert(0, transaction)
    holding = next(
        (item for item in crypto_holdings
         if item["asset"] == transaction["asset"]),
        None,
    )
    if holding is None:
        holding = {
            "asset": transaction["asset"], "quantity": "0",
            "updated_at": timestamp(),
        }
        crypto_holdings.append(holding)
    holding["quantity"] = decimal_text(
        decimal_value(holding["quantity"])
        + decimal_value(transaction["quantity_delta"])
    )
    holding["updated_at"] = timestamp()
    return web.json_response(deepcopy(transaction), status=201)


async def patch_crypto_holding(request: web.Request) -> web.Response:
    asset = request.match_info["asset"]
    payload = await read_json(request)
    quantity = decimal_text(payload.get("quantity"))
    holding = next((item for item in crypto_holdings if item["asset"] == asset), None)
    if holding is None:
        holding = {"asset": asset, "quantity": quantity, "updated_at": timestamp()}
        crypto_holdings.append(holding)
    else:
        holding["quantity"] = quantity
        holding["updated_at"] = timestamp()
    return web.json_response(deepcopy(holding))


async def delete_crypto_transaction(request: web.Request) -> web.Response:
    try:
        transaction_id = int(request.match_info["id"])
    except ValueError:
        return error("некорректный id")
    index = next(
        (index for index, item in enumerate(crypto_transactions)
         if item["id"] == transaction_id),
        None,
    )
    if index is None:
        return error("криптооперация не найдена", 404)
    transaction = crypto_transactions.pop(index)
    holding = next(
        (item for item in crypto_holdings
         if item["asset"] == transaction["asset"]),
        None,
    )
    if holding is not None:
        holding["quantity"] = decimal_text(
            decimal_value(holding["quantity"])
            - decimal_value(transaction["quantity_delta"])
        )
        holding["updated_at"] = timestamp()
    return web.json_response({"deleted": True, "transaction": transaction})


async def categories(_: web.Request) -> web.Response:
    return web.json_response({
        "expense": list(EXPENSE_CATEGORIES),
        "income": list(INCOME_CATEGORIES),
    })


async def budget_settings(_: web.Request) -> web.Response:
    return web.json_response({
        "overall_limit": (
            money(settings["overall_limit"])
            if settings["overall_limit"] is not None else None
        ),
        "categories": [
            {
                "category": category,
                "limit": money(limit) if limit is not None else None,
            }
            for category, limit in settings["categories"].items()
        ],
    })


async def update_budget_settings(request: web.Request) -> web.Response:
    payload = await read_json(request)
    if payload.get("overall_limit") in (None, ""):
        return error("overall_limit обязателен")
    try:
        settings["overall_limit"] = decimal_value(payload["overall_limit"])
        settings["categories"] = {
            str(item["category"]): (
                decimal_value(item["limit"])
                if item.get("limit") not in (None, "") else None
            )
            for item in payload.get("categories", [])
        }
    except (KeyError, TypeError, web.HTTPBadRequest):
        return error("некорректные настройки бюджета")
    return web.json_response({
        "overall_limit": money(settings["overall_limit"]),
        "categories": [
            {
                "category": category,
                "limit": money(limit) if limit is not None else None,
            }
            for category, limit in settings["categories"].items()
        ],
    })


def find_debt(debt_id: int) -> dict | None:
    return next((item for item in debts if item["id"] == debt_id), None)


def find_personal_debt(debt_id: int) -> dict | None:
    return next((item for item in personal_debts if item["id"] == debt_id), None)


async def debts_endpoint(request: web.Request) -> web.Response:
    status_filter = request.query.get("status")
    archived = request.query.get("archived", "0") == "1"
    rows = [
        item for item in debts
        if item["archived"] == archived
        and (status_filter is None or item["status"] == status_filter)
    ]
    return web.json_response({"items": [debt_payload(item) for item in rows]})


async def create_debt(request: web.Request) -> web.Response:
    payload = await read_json(request)
    debt_id = max((item["id"] for item in debts), default=0) + 1
    principal = money(decimal_value(payload.get("principal")))
    debt = make_debt(
        debt_id,
        str(payload.get("creditor") or "Новый кредит"),
        str(payload.get("loan_name") or ""),
        principal,
        principal,
        rate=payload.get("rate"),
        min_payment=payload.get("min_payment"),
        next_payment_amount=payload.get("next_payment_amount"),
        opened_offset=0,
        next_payment_offset=None,
        priority=payload.get("priority"),
        due_offset=None,
    )
    debts.append(debt)
    debt_history[debt_id] = []
    return web.json_response(debt_payload(debt), status=201)


async def patch_debt(request: web.Request) -> web.Response:
    try:
        debt_id = int(request.match_info["id"])
    except ValueError:
        return error("некорректный id")
    debt = find_debt(debt_id)
    if debt is None:
        return error("кредит не найден", 404)
    payload = await read_json(request)
    for field in (
        "creditor", "loan_name", "contract_ref", "principal", "balance",
        "rate", "min_payment", "next_payment_amount", "opened_at",
        "next_payment_date", "priority", "due_date", "maturity_date", "status",
    ):
        if field not in payload:
            continue
        target = "due_date" if field == "maturity_date" else field
        debt[target] = payload[field]
    return web.json_response(debt_payload(debt))


async def adjust_debt(request: web.Request) -> web.Response:
    try:
        debt_id = int(request.match_info["id"])
    except ValueError:
        return error("некорректный id")
    debt = find_debt(debt_id)
    if debt is None:
        return error("кредит не найден", 404)
    payload = await read_json(request)
    debt["balance"] = money(decimal_value(payload.get("balance")))
    if decimal_value(debt["balance"]) == 0:
        debt["status"] = "closed"
    debt_history.setdefault(debt_id, []).append({
        "id": max(
            (item["id"] for history in debt_history.values() for item in history),
            default=200,
        ) + 1,
        "debt_id": debt_id,
        "operation_id": None,
        "pay_date": str(payload.get("date") or day()),
        "amount": "0.00",
        "principal_amount": None,
        "interest_amount": None,
        "kind": "adjustment",
        "payment_type": None,
        "cash_effect": "already_in_balance",
        "reason": payload.get("reason"),
    })
    return web.json_response(debt_payload(debt))


async def pay_debt(request: web.Request) -> web.Response:
    try:
        debt_id = int(request.match_info["id"])
    except ValueError:
        return error("некорректный id")
    debt = find_debt(debt_id)
    if debt is None:
        return error("кредит не найден", 404)
    payload = await read_json(request)
    amount = decimal_value(payload.get("amount"))
    principal_amount = decimal_value(
        payload.get("principal_amount"), default=str(amount)
    )
    new_balance = max(
        Decimal("0"),
        decimal_value(debt["balance"]) - principal_amount,
    )
    debt["balance"] = money(new_balance)
    if new_balance == 0:
        debt["status"] = "closed"
    debt_history.setdefault(debt_id, []).append({
        "id": max(
            (item["id"] for history in debt_history.values() for item in history),
            default=200,
        ) + 1,
        "debt_id": debt_id,
        "operation_id": None,
        "pay_date": str(payload.get("date") or day()),
        "amount": money(amount),
        "principal_amount": money(principal_amount),
        "interest_amount": money(max(Decimal("0"), amount - principal_amount)),
        "kind": "payment",
        "payment_type": payload.get("payment_type", "regular"),
        "cash_effect": payload.get("cash_effect", "movement"),
        "reason": None,
    })
    return web.json_response(debt_payload(debt))


async def debt_history_endpoint(request: web.Request) -> web.Response:
    try:
        debt_id = int(request.match_info["id"])
    except ValueError:
        return error("некорректный id")
    if find_debt(debt_id) is None:
        return error("кредит не найден", 404)
    return web.json_response({"items": deepcopy(debt_history.get(debt_id, []))})


async def archive_debt(request: web.Request) -> web.Response:
    try:
        debt_id = int(request.match_info["id"])
    except ValueError:
        return error("некорректный id")
    debt = find_debt(debt_id)
    if debt is None:
        return error("кредит не найден", 404)
    debt["archived"] = request.match_info["action"] == "archive"
    return web.json_response(debt_payload(debt))


async def delete_debt(request: web.Request) -> web.Response:
    try:
        debt_id = int(request.match_info["id"])
    except ValueError:
        return error("некорректный id")
    debt = find_debt(debt_id)
    if debt is None:
        return error("кредит не найден", 404)
    debts.remove(debt)
    debt_history.pop(debt_id, None)
    return web.json_response({"deleted": True})


async def debts_summary(_: web.Request) -> web.Response:
    return web.json_response(debts_summary_payload())


async def personal_debts_endpoint(request: web.Request) -> web.Response:
    status_filter = request.query.get("status")
    archived = request.query.get("archived", "0") == "1"
    rows = [
        item for item in personal_debts
        if item["archived"] == archived
        and (status_filter is None or item["status"] == status_filter)
    ]
    return web.json_response({"items": deepcopy(rows)})


async def create_personal_debt(request: web.Request) -> web.Response:
    payload = await read_json(request)
    debt_id = max((item["id"] for item in personal_debts), default=10) + 1
    principal = money(decimal_value(payload.get("principal")))
    debt = {
        "id": debt_id,
        "person": str(payload.get("person") or "Новый человек"),
        "direction": payload.get("direction", "owed_to_me"),
        "principal": principal,
        "balance": principal,
        "opened_at": str(payload.get("opened_at") or day()),
        "due_date": payload.get("due_date"),
        "comment": payload.get("comment"),
        "status": "open",
        "archived": False,
        "operation_id": None,
        "payment_count": 0,
    }
    personal_debts.append(debt)
    personal_debt_history[debt_id] = []
    return web.json_response(deepcopy(debt), status=201)


async def patch_personal_debt(request: web.Request) -> web.Response:
    try:
        debt_id = int(request.match_info["id"])
    except ValueError:
        return error("некорректный id")
    debt = find_personal_debt(debt_id)
    if debt is None:
        return error("личный долг не найден", 404)
    payload = await read_json(request)
    for field in (
        "person", "direction", "principal", "balance", "opened_at",
        "due_date", "comment", "status",
    ):
        if field in payload:
            debt[field] = payload[field]
    return web.json_response(deepcopy(debt))


async def pay_personal_debt(request: web.Request) -> web.Response:
    try:
        debt_id = int(request.match_info["id"])
    except ValueError:
        return error("некорректный id")
    debt = find_personal_debt(debt_id)
    if debt is None:
        return error("личный долг не найден", 404)
    payload = await read_json(request)
    amount = decimal_value(payload.get("amount"))
    new_balance = max(
        Decimal("0"),
        decimal_value(debt["balance"]) - amount,
    )
    debt["balance"] = money(new_balance)
    debt["status"] = "closed" if new_balance == 0 else "open"
    history = personal_debt_history.setdefault(debt_id, [])
    history.append({
        "id": max(
            (item["id"] for values in personal_debt_history.values() for item in values),
            default=300,
        ) + 1,
        "personal_debt_id": debt_id,
        "operation_id": None,
        "pay_date": str(payload.get("date") or day()),
        "amount": money(amount),
        "principal_amount": money(amount),
        "interest_amount": None,
        "kind": "payment",
        "payment_type": "regular",
        "cash_effect": payload.get("cash_effect", "movement"),
        "reason": None,
    })
    debt["payment_count"] = len(history)
    return web.json_response(deepcopy(debt))


async def personal_debt_history_endpoint(request: web.Request) -> web.Response:
    try:
        debt_id = int(request.match_info["id"])
    except ValueError:
        return error("некорректный id")
    if find_personal_debt(debt_id) is None:
        return error("личный долг не найден", 404)
    return web.json_response({
        "items": deepcopy(personal_debt_history.get(debt_id, []))
    })


async def archive_personal_debt(request: web.Request) -> web.Response:
    try:
        debt_id = int(request.match_info["id"])
    except ValueError:
        return error("некорректный id")
    debt = find_personal_debt(debt_id)
    if debt is None:
        return error("личный долг не найден", 404)
    debt["archived"] = request.match_info["action"] == "archive"
    return web.json_response(deepcopy(debt))


async def delete_personal_debt(request: web.Request) -> web.Response:
    try:
        debt_id = int(request.match_info["id"])
    except ValueError:
        return error("некорректный id")
    debt = find_personal_debt(debt_id)
    if debt is None:
        return error("личный долг не найден", 404)
    personal_debts.remove(debt)
    personal_debt_history.pop(debt_id, None)
    return web.json_response({"deleted": True})


async def subscriptions_endpoint(request: web.Request) -> web.Response:
    status_filter = request.query.get("status", "active")
    if status_filter not in {"active", "cancelled"}:
        return error("неизвестный статус подписки")
    return web.json_response(subscriptions_payload(status_filter))


async def create_subscription(request: web.Request) -> web.Response:
    payload = await read_json(request)
    if not str(payload.get("title") or "").strip():
        return error("title обязателен")
    if payload.get("amount") in (None, ""):
        return error("amount обязателен")
    amount = decimal_value(payload.get("amount"))
    if amount <= 0:
        return error("amount должен быть положительным")
    if payload.get("period") not in {"monthly", "yearly"}:
        return error("period должен быть monthly или yearly")
    if not payload.get("next_charge"):
        return error("next_charge обязателен")
    subscription_id = max((item["id"] for item in subscriptions), default=500) + 1
    subscription = {
        "id": subscription_id,
        "title": str(payload["title"]).strip(),
        "amount": money(amount),
        "period": payload.get("period", "monthly"),
        "next_charge": str(payload.get("next_charge") or day(30)),
        "category": payload.get("category"),
        "comment": payload.get("comment"),
        "status": "active",
        "created_at": timestamp(),
    }
    subscriptions.append(subscription)
    return web.json_response(subscription_payload(subscription, due=False), status=201)


async def patch_subscription(request: web.Request) -> web.Response:
    try:
        subscription_id = int(request.match_info["id"])
    except ValueError:
        return error("некорректный id")
    subscription = next(
        (item for item in subscriptions if item["id"] == subscription_id),
        None,
    )
    if subscription is None:
        return error("подписка не найдена", 404)
    payload = await read_json(request)
    for field in (
        "title", "amount", "period", "next_charge", "category", "comment", "status",
    ):
        if field not in payload:
            continue
        subscription[field] = (
            money(decimal_value(payload[field]))
            if field == "amount" else payload[field]
        )
    return web.json_response(subscription_payload(
        subscription,
        due=subscription["status"] == "active"
        and date.fromisoformat(subscription["next_charge"]) <= TODAY,
    ))


async def delete_subscription(request: web.Request) -> web.Response:
    try:
        subscription_id = int(request.match_info["id"])
    except ValueError:
        return error("некорректный id")
    subscription = next(
        (item for item in subscriptions if item["id"] == subscription_id),
        None,
    )
    if subscription is None:
        return error("подписка не найдена", 404)
    subscription["status"] = "cancelled"
    return web.json_response(subscription_payload(subscription, due=False))


async def charge_subscription(request: web.Request) -> web.Response:
    try:
        subscription_id = int(request.match_info["id"])
    except ValueError:
        return error("некорректный id")
    subscription = next(
        (item for item in subscriptions if item["id"] == subscription_id),
        None,
    )
    if subscription is None:
        return error("подписка не найдена", 404)
    payload = await read_json(request)
    confirmed = bool(payload.get("confirmed"))
    charge_date = str(payload.get("op_date") or day())
    subscription["next_charge"] = add_period(
        date.fromisoformat(charge_date),
        subscription["period"],
    ).isoformat()
    operation_id = None
    if confirmed:
        operation_id = max((item["id"] for item in operations), default=100) + 1
        operations.insert(0, make_operation(
            operation_id, 0, "расход", subscription["amount"],
            subscription["category"], f"Подписка: {subscription['title']}",
            subscription_id=subscription["id"],
        ))
    return web.json_response({
        "subscription": subscription_payload(subscription, due=False),
        "operation_id": operation_id,
    })


async def budget_endpoint(request: web.Request) -> web.Response:
    raw = request.query.get("week_start")
    try:
        requested = date.fromisoformat(raw) if raw else CURRENT_WEEK_START
    except ValueError:
        return error("некорректная дата недели")
    if requested.weekday() != 0:
        return error("week_start должен быть понедельником")
    if requested > CURRENT_WEEK_START:
        return error("будущая неделя недоступна")
    if requested not in {CURRENT_WEEK_START, PREVIOUS_WEEK_START}:
        return error("mock поддерживает только две недели")
    return web.json_response(budget_for(requested))


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/api/summary", summary)
    app.router.add_get("/api/operations", operations_endpoint)
    app.router.add_post("/api/operations", create_operation)
    app.router.add_patch("/api/operations/{id}", patch_operation)
    app.router.add_post("/api/operations/{id}/confirm", confirm_operation)
    app.router.add_delete("/api/operations/{id}", delete_operation)
    app.router.add_post("/api/operations/{id}/restore", restore_operation)
    app.router.add_get("/api/crypto", crypto_endpoint)
    app.router.add_post("/api/crypto/transactions", create_crypto_transaction)
    app.router.add_get("/api/crypto/overview", crypto_overview)
    app.router.add_patch("/api/crypto/overview", crypto_overview)
    app.router.add_patch("/api/crypto/holdings/{asset}", patch_crypto_holding)
    app.router.add_delete("/api/crypto/transactions/{id}", delete_crypto_transaction)
    app.router.add_get("/api/categories", categories)
    app.router.add_get("/api/balance", balance)
    app.router.add_patch("/api/balance", balance)
    app.router.add_get("/api/budget", budget_endpoint)
    app.router.add_get("/api/budget/settings", budget_settings)
    app.router.add_put("/api/budget/settings", update_budget_settings)
    app.router.add_get("/api/debts/summary", debts_summary)
    app.router.add_get("/api/debts", debts_endpoint)
    app.router.add_post("/api/debts", create_debt)
    app.router.add_patch("/api/debts/{id}", patch_debt)
    app.router.add_post("/api/debts/{id}/adjust", adjust_debt)
    app.router.add_post("/api/debts/{id}/pay", pay_debt)
    app.router.add_get("/api/debts/{id}/payments", debt_history_endpoint)
    app.router.add_post("/api/debts/{id}/{action}", archive_debt)
    app.router.add_delete("/api/debts/{id}", delete_debt)
    app.router.add_get("/api/personal-debts", personal_debts_endpoint)
    app.router.add_post("/api/personal-debts", create_personal_debt)
    app.router.add_patch("/api/personal-debts/{id}", patch_personal_debt)
    app.router.add_post("/api/personal-debts/{id}/pay", pay_personal_debt)
    app.router.add_get(
        "/api/personal-debts/{id}/payments", personal_debt_history_endpoint
    )
    app.router.add_post(
        "/api/personal-debts/{id}/{action}", archive_personal_debt
    )
    app.router.add_delete("/api/personal-debts/{id}", delete_personal_debt)
    app.router.add_get("/api/subscriptions", subscriptions_endpoint)
    app.router.add_post("/api/subscriptions", create_subscription)
    app.router.add_patch("/api/subscriptions/{id}", patch_subscription)
    app.router.add_delete("/api/subscriptions/{id}", delete_subscription)
    app.router.add_post("/api/subscriptions/{id}/charge", charge_subscription)
    return app


async def main() -> None:
    runner = web.AppRunner(create_app())
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 8080)
    await site.start()
    logger.info("In-memory mock API слушает 127.0.0.1:8080")
    try:
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    asyncio.run(main())
