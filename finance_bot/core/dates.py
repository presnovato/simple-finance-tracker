import re
from datetime import date, datetime, timedelta

import pytz

from finance_bot.config import DAY_BOUNDARY_HOUR, TIMEZONE

TZ = pytz.timezone(TIMEZONE)

WEEKDAYS_RU = {
    "понедельник": 0,
    "понедельника": 0,
    "вторник": 1,
    "вторника": 1,
    "среду": 2,
    "среда": 2,
    "четверг": 3,
    "четверга": 3,
    "пятницу": 4,
    "пятница": 4,
    "субботу": 5,
    "суббота": 5,
    "воскресенье": 6,
}

MONTHS_RU = {
    "января": 1,
    "февраля": 2,
    "марта": 3,
    "апреля": 4,
    "мая": 5,
    "июня": 6,
    "июля": 7,
    "августа": 8,
    "сентября": 9,
    "октября": 10,
    "ноября": 11,
    "декабря": 12,
}

MONTH_NAMES_GENITIVE = tuple(MONTHS_RU)

_ISO_DATE_RE = re.compile(r"(?<!\d)(\d{4}-\d{2}-\d{2})(?!\d)")
_DOT_DATE_RE = re.compile(
    r"(?<!\d)(\d{1,2})\.(\d{1,2})(?:\.(\d{4}))?(?!\d)"
)
_DATE_PREFIX_RE = re.compile(
    r"^\s*((?:\d{4}-\d{2}-\d{2})|(?:\d{1,2}\.\d{1,2}(?:\.\d{4})?))"
    r"(?:\s+|$)"
)


def now_local() -> datetime:
    return datetime.now(TZ)


def effective_today(moment: datetime | None = None) -> date:
    """Финансовый «сегодня»: до DAY_BOUNDARY_HOUR ночи идёт вчерашний день."""
    moment = moment or now_local()
    return (moment - timedelta(hours=DAY_BOUNDARY_HOUR)).date()


def week_bounds(anchor: date) -> tuple[date, date]:
    """Возвращает понедельник и воскресенье финансовой недели anchor."""
    start = anchor - timedelta(days=anchor.weekday())
    return start, start + timedelta(days=6)


def _date_without_year(day: int, month: int, today: date) -> date | None:
    try:
        resolved = date(today.year, month, day)
    except ValueError:
        return None
    if resolved > today:
        try:
            resolved = date(today.year - 1, month, day)
        except ValueError:
            return None
    return resolved


def _parse_explicit_date(value: str, today: date) -> date | None:
    iso = _ISO_DATE_RE.fullmatch(value)
    if iso:
        try:
            return date.fromisoformat(iso.group(1))
        except ValueError:
            return None

    dotted = _DOT_DATE_RE.fullmatch(value)
    if not dotted:
        return None
    day, month = int(dotted.group(1)), int(dotted.group(2))
    if dotted.group(3):
        try:
            return date(int(dotted.group(3)), month, day)
        except ValueError:
            return None
    return _date_without_year(day, month, today)


def split_explicit_date_prefix(text: str, today: date) -> tuple[date | None, str]:
    """Снимает явный префикс даты, чтобы LLM не приняла его за сумму."""
    match = _DATE_PREFIX_RE.match(text)
    if not match:
        return None, text
    resolved = _parse_explicit_date(match.group(1), today)
    if resolved is None:
        return None, text
    return resolved, text[match.end():].strip()


def resolve_relative_date(text: str, today: date) -> date | None:
    """Находит дату в пользовательском тексте без участия LLM."""
    normalized = text.lower().replace("ё", "е")

    iso = _ISO_DATE_RE.search(normalized)
    if iso:
        resolved = _parse_explicit_date(iso.group(1), today)
        if resolved is not None:
            return resolved

    explicit_prefix = _DATE_PREFIX_RE.match(normalized)
    if explicit_prefix:
        resolved = _parse_explicit_date(explicit_prefix.group(1), today)
        if resolved is not None:
            return resolved

    named_month = re.search(
        rf"(?<!\d)(\d{{1,2}})\s+({'|'.join(MONTHS_RU)})(?!\w)",
        normalized,
    )
    if named_month:
        return _date_without_year(
            int(named_month.group(1)), MONTHS_RU[named_month.group(2)], today
        )

    if re.search(r"\bпослезавтра\b", normalized):
        return today + timedelta(days=2)
    if re.search(r"\bзавтра\b", normalized):
        return today + timedelta(days=1)
    if re.search(r"\bпозавчера\b", normalized):
        return today - timedelta(days=2)
    if re.search(r"\bвчера\b", normalized):
        return today - timedelta(days=1)
    if re.search(r"\bсегодня\b", normalized):
        return today

    days_ago = re.search(
        r"\b(\d+)\s+(?:день|дня|дней)\s+назад\b", normalized
    )
    if days_ago:
        return today - timedelta(days=int(days_ago.group(1)))

    weekday = re.search(
        rf"\b(?:в|во)\s+({'|'.join(WEEKDAYS_RU)})\b", normalized
    )
    if weekday:
        target = WEEKDAYS_RU[weekday.group(1)]
        days_back = (today.weekday() - target) % 7 or 7
        return today - timedelta(days=days_back)
    return None


def format_day_month(value: date) -> str:
    return f"{value.day} {MONTH_NAMES_GENITIVE[value.month - 1]}"


def month_bounds(anchor: date, offset: int = 0) -> tuple[date, date]:
    """Первый и последний день месяца anchor со сдвигом offset месяцев."""
    year, month = anchor.year, anchor.month + offset
    year += (month - 1) // 12
    month = (month - 1) % 12 + 1
    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        end = date(year, month + 1, 1) - timedelta(days=1)
    return start, end


def same_day_prev_month(anchor: date) -> date:
    """То же число прошлого месяца (с обрезкой по длине месяца)."""
    start, end = month_bounds(anchor, offset=-1)
    return min(date(start.year, start.month, anchor.day), end) \
        if anchor.day <= end.day else end
