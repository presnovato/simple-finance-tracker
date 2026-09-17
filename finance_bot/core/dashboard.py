"""Рендер текстового дашборда с emoji-барами. Чистые функции без telegram."""

from decimal import Decimal

BAR_WIDTH = 8

MONTHS_RU = (
    "январь", "февраль", "март", "апрель", "май", "июнь",
    "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь",
)


def fmt_amount(value: Decimal | int | float) -> str:
    """1234567.50 → «1 234 568₽» (без копеек — на дашборде они шум)."""
    return f"{round(Decimal(value)):,}".replace(",", " ") + "₽"


def render_bar(value: Decimal, max_value: Decimal, width: int = BAR_WIDTH) -> str:
    if max_value <= 0:
        return "░" * width
    filled = round(width * float(value) / float(max_value))
    filled = min(width, max(1 if value > 0 else 0, filled))
    return "▓" * filled + "░" * (width - filled)


def render_categories(rows: list[dict]) -> str:
    if not rows:
        return "Расходов нет."
    max_total = rows[0]["total"]
    name_width = max(len(r["category"]) for r in rows)
    lines = []
    for r in rows:
        lines.append(
            f"{r['category']:<{name_width}} {render_bar(r['total'], max_total)}"
            f" {fmt_amount(r['total'])}"
        )
    return "\n".join(lines)


def render_comparison(current: Decimal, previous: Decimal) -> str:
    """Сравнение расходов с прошлым месяцем на ту же дату."""
    if previous <= 0:
        return ""
    diff_pct = round((float(current) - float(previous)) / float(previous) * 100)
    arrow = "🔺" if diff_pct > 0 else "🟢" if diff_pct < 0 else "➖"
    return (f"Прошлый месяц на эту дату: {fmt_amount(previous)} "
            f"({arrow} {diff_pct:+d}%)")


def render_subscription_line(monthly_cost: Decimal) -> str:
    return f"Подписки: {fmt_amount(monthly_cost).replace('₽', ' ₽')}/мес"


def render_balance(
    income: Decimal,
    expense: Decimal,
    transfer_in: Decimal = Decimal("0"),
    transfer_out: Decimal = Decimal("0"),
) -> str:
    balance = income - expense + transfer_in - transfer_out
    sign = "＋" if balance >= 0 else "－"
    return (f"Доходы: {fmt_amount(income)}\n"
            f"Дельта за период: {sign}{fmt_amount(abs(balance))}")
