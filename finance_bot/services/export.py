"""Генерация файлов экспорта без зависимости от БД и Telegram."""

import csv
import io
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP

MONEY_STEP = Decimal("0.01")
CSV_HEADERS = (
    "Дата",
    "Тип",
    "Сумма",
    "Категория",
    "Комментарий",
    "Заметка",
    "Направление перевода",
    "Нужна проверка",
)


def _date_text(value: object) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value or "")


def _money_text(value: object) -> str:
    if value in (None, ""):
        return ""
    return format(
        Decimal(value).quantize(MONEY_STEP, rounding=ROUND_HALF_UP), "f"
    )


def _text(value: object) -> str:
    return str(value or "")


def generate_csv(operations: list[dict]) -> bytes:
    """Возвращает CSV UTF-8 с BOM и разделителем для русской локали Excel."""
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, delimiter=";", lineterminator="\r\n")
    writer.writerow(CSV_HEADERS)
    for operation in operations:
        writer.writerow([
            _date_text(operation.get("op_date")),
            _text(operation.get("type")),
            _money_text(operation.get("amount")),
            _text(operation.get("category")),
            _text(operation.get("comment")),
            _text(operation.get("note")),
            _text(operation.get("transfer_direction")),
            "Да" if operation.get("needs_review") else "Нет",
        ])
    return stream.getvalue().encode("utf-8-sig")


def _md_text(value: object) -> str:
    return _text(value).replace("\\", "\\\\").replace("\n", "<br>")


def _day_label(value: object) -> str:
    text = _date_text(value)
    try:
        return date.fromisoformat(text[:10]).strftime("%d.%m.%Y")
    except ValueError:
        return text


def _snapshot_money(value: object) -> str:
    if value in (None, ""):
        return "нет данных"
    return f"{_money_text(value)} ₽"


def _snapshot_date(value: object) -> str:
    return _day_label(value) if value not in (None, "") else "нет данных"


def _snapshot_percent(value: object) -> str:
    if value in (None, ""):
        return "нет данных"
    return f"{Decimal(value).quantize(MONEY_STEP)}%"


def _snapshot_identity(item: dict) -> str:
    name = item.get("name") or item.get("person") or item.get("creditor")
    if not name:
        name = f"Долг #{item.get('id', '?')}"
    details = []
    if item.get("kind") == "credit" and item.get("creditor"):
        if item.get("creditor") != name:
            details.append(str(item["creditor"]))
        if item.get("contract_ref"):
            details.append(f"договор {item['contract_ref']}")
    elif item.get("kind") == "personal" and item.get("person"):
        if item.get("person") != name:
            details.append(str(item["person"]))
    if item.get("id") is not None:
        details.append(f"id {item['id']}")
    suffix = f" ({'; '.join(details)})" if details else ""
    return f"{_md_text(name)}{_md_text(suffix)}"


def _payment_line(item: dict, *, personal: bool = False) -> str:
    amount = item.get("next_payment_amount")
    payment_date = item.get("next_payment_date")
    if personal:
        return "ближайший платёж: сумма не хранится"
    if amount is not None and payment_date is not None:
        return f"ближайший платёж {_snapshot_money(amount)} до {_snapshot_date(payment_date)}"
    if amount is not None:
        return f"ближайший платёж {_snapshot_money(amount)} (дата не указана)"
    if payment_date is not None:
        return f"ближайший платёж: сумма не указана до {_snapshot_date(payment_date)}"
    return "ближайший платёж: нет данных"


def _paid_line(item: dict) -> str:
    amount = item.get("paid_amount")
    percent = item.get("paid_percent")
    if amount is None:
        return "погашено: нет данных"
    if percent is None:
        return f"погашено {_snapshot_money(amount)}"
    return f"погашено {_snapshot_money(amount)} ({_snapshot_percent(percent)})"


def _debt_line(item: dict) -> str:
    details = [
        f"остаток {_snapshot_money(item.get('balance'))}",
        f"первоначально {_snapshot_money(item.get('principal'))}",
        _paid_line(item),
        f"начало {_snapshot_date(item.get('opened_at'))}",
    ]
    if item.get("kind") == "credit":
        details.append(_payment_line(item))
        rate = item.get("rate")
        details.append(
            f"ставка {_snapshot_percent(rate)}" if rate is not None
            else "ставка: нет данных"
        )
    else:
        details.append(
            f"срок {_snapshot_date(item.get('due_date'))}"
            if item.get("due_date") is not None else "срок: нет данных"
        )
        details.append(_payment_line(item, personal=True))
    return f"- {_snapshot_identity(item)}: {'; '.join(details)}"


def _signed_snapshot_money(value: object) -> str:
    if value in (None, ""):
        return "нет данных"
    amount = Decimal(value)
    sign = "+" if amount > 0 else ""
    return f"{sign}{_money_text(amount)} ₽"


def render_finance_snapshot(snapshot: dict) -> str:
    """Рендерит только фактические данные текущего финансового состояния."""
    cash = snapshot.get("cash") or {}
    totals = snapshot.get("totals") or {}
    debts = snapshot.get("debts") or []
    credits = [item for item in debts if item.get("kind") == "credit"]
    personal_liabilities = [
        item for item in debts
        if item.get("kind") == "personal" and item.get("direction") == "i_owe"
    ]
    receivables = [
        item for item in debts
        if item.get("kind") == "personal" and item.get("direction") == "owed_to_me"
    ]
    unknown_personal = [
        item for item in debts
        if item.get("kind") == "personal"
        and item.get("direction") not in {"i_owe", "owed_to_me"}
    ]

    as_of = snapshot.get("as_of")
    money_title = "### Текущие деньги"
    if as_of not in (None, ""):
        money_title += f" (на {_snapshot_date(as_of)})"
    lines = [money_title]

    total = cash.get("total")
    if total is None:
        reason = cash.get("total_unavailable_reason") or "источник остатка недоступен"
        lines.append(f"- Всего: нет данных — {reason}")
    else:
        lines.append(f"- Всего: {_snapshot_money(total)}")

    accounts = cash.get("accounts")
    if accounts:
        lines.append("- По счетам/кошелькам:")
        for account in accounts:
            name = _md_text(account.get("name") or account.get("account") or "Без названия")
            lines.append(f"  - {name}: {_snapshot_money(account.get('balance'))}")
    else:
        reason = cash.get("accounts_unavailable_reason") or "нет данных"
        lines.append(f"- По счетам/кошелькам: нет данных — {reason}")

    free = cash.get("free")
    lines.append(
        f"- Свободно: {_snapshot_money(free)}"
        if free is not None else
        f"- Свободно: нет данных — {cash.get('free_unavailable_reason') or 'резервирование не определено'}"
    )
    reserved = cash.get("reserved")
    lines.append(
        f"- Зарезервировано: {_snapshot_money(reserved)}"
        if reserved is not None else
        f"- Зарезервировано: нет данных — {cash.get('reserved_unavailable_reason') or 'резервирование не определено'}"
    )

    lines += ["", "### Долги"]
    if not debts:
        lines.append("- Активных долгов нет")
    else:
        if credits:
            lines.append("#### Кредиты")
            lines.extend(_debt_line(item) for item in credits)
        if personal_liabilities:
            lines.append("#### Личные долги (я должен)")
            lines.extend(_debt_line(item) for item in personal_liabilities)
        if receivables:
            lines.append("#### Личные долги (мне должны)")
            lines.extend(_debt_line(item) for item in receivables)
        if unknown_personal:
            lines.append("#### Личные долги (направление не указано)")
            lines.extend(_debt_line(item) for item in unknown_personal)

    liability_total = totals.get("liability_balance")
    if liability_total is None:
        reason = (
            totals.get("liability_unavailable_reason")
            or "один или несколько остатков неизвестны"
        )
        lines.append(f"- Общая текущая задолженность: нет данных — {reason}")
    else:
        lines.append(f"- Общая текущая задолженность: {_snapshot_money(liability_total)}")

    next_total = totals.get("next_payment_amount")
    if next_total is None:
        next_reason = (
            "сумма обязательного платежа по личным долгам не хранится"
            if totals.get("personal_liability_payment_unknown_count")
            else "сумма обязательного платежа не хранится"
        )
        lines.append(
            "- Общая сумма ближайших обязательных платежей: "
            f"нет данных — {next_reason}"
        )
    else:
        next_suffix = []
        if totals.get("next_payment_unknown_count"):
            next_suffix.append(
                f"сумма не указана по {totals['next_payment_unknown_count']} долгам"
            )
        if totals.get("next_payment_date_unknown_count"):
            next_suffix.append(
                f"дата не указана по {totals['next_payment_date_unknown_count']} долгам"
            )
        if totals.get("personal_liability_payment_unknown_count"):
            next_suffix.append(
                "суммы личных долгов не хранятся"
            )
        suffix = f" ({'; '.join(next_suffix)})" if next_suffix else ""
        lines.append(
            f"- Общая сумма ближайших обязательных платежей: "
            f"{_snapshot_money(next_total)}{suffix}"
        )

    if receivables:
        receivable_total = totals.get("receivable_balance")
        lines.append(f"- Общая сумма мне должны: {_snapshot_money(receivable_total)}")

    previous = snapshot.get("previous_total_debt")
    if previous is None:
        reason = snapshot.get("history_unavailable_reason") or "нет исторических данных"
        lines.append(f"- Изменение с прошлого Weekly Sync: нет данных — {reason}")
    elif liability_total is None:
        lines.append("- Изменение с прошлого Weekly Sync: нет данных — текущий общий долг неизвестен")
    else:
        lines.append(
            f"- Изменение с прошлого Weekly Sync: "
            f"{_signed_snapshot_money(Decimal(liability_total) - Decimal(previous))}"
        )
    return "\n".join(lines)


def generate_md(
    operations: list[dict], finance_snapshot: dict | None = None
) -> bytes:
    """Группирует операции по дням и добавляет фактический финансовый snapshot."""
    expenses = sum(
        (Decimal(operation["amount"]) for operation in operations
         if operation.get("type") == "расход"),
        Decimal("0"),
    )
    income = sum(
        (Decimal(operation["amount"]) for operation in operations
         if operation.get("type") == "доход"),
        Decimal("0"),
    )
    dates = [_date_text(operation.get("op_date")) for operation in operations]
    period = f"{min(dates)} — {max(dates)}" if dates else "нет операций"
    lines = [
        "# Экспорт операций",
        "",
        f"Период: {period}",
        "",
        "## ФИНАНСЫ",
        "",
        f"Доходы за период: {_money_text(income)} ₽",
        f"Расходы за период: {_money_text(expenses)} ₽",
    ]
    if finance_snapshot is not None:
        lines += ["", render_finance_snapshot(finance_snapshot)]
    lines.append("")

    grouped: dict[str, list[dict]] = defaultdict(list)
    for operation in operations:
        grouped[_date_text(operation.get("op_date"))].append(operation)

    for day in sorted(grouped):
        lines.append(f"## {_day_label(day)}")
        day_expense = Decimal("0")
        day_income = Decimal("0")
        for operation in grouped[day]:
            kind = _text(operation.get("type"))
            amount = Decimal(operation["amount"])
            if kind == "расход":
                day_expense += amount
            elif kind == "доход":
                day_income += amount
            details = [
                _md_text(operation.get("category")),
                _md_text(operation.get("comment")),
                _md_text(operation.get("note")),
            ]
            details = [item for item in details if item]
            suffix = f" — {' · '.join(details)}" if details else ""
            lines.append(
                f"- {kind}: {_money_text(amount)} ₽{suffix}"
            )
        lines.append(
            f"Итого за день: расход {_money_text(day_expense)} ₽, "
            f"доход {_money_text(day_income)} ₽"
        )
        lines.append("")

    return "\n".join(lines).encode("utf-8")
