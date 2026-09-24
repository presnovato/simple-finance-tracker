import logging
import os
import re
from decimal import Decimal
from pathlib import Path

import pytz
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
ALLOWED_USER_ID: int = int(os.getenv("ALLOWED_USER_ID", "0"))


def _sqlite_path(value: str) -> str:
    if value.startswith("sqlite:///"):
        return value.removeprefix("sqlite:///")
    if value.startswith("sqlite://"):
        return value.removeprefix("sqlite://")
    return value


DB_PATH: str = _sqlite_path(os.getenv("DB_PATH", "/data/finance.db"))
DB_REQUIRE_PERSISTENT_DIR: bool = (
    os.getenv("DB_REQUIRE_PERSISTENT_DIR", "1") == "1"
)
OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "")
TMA_URL: str = os.getenv("TMA_URL", "").rstrip("/")
PORT: int = int(os.getenv("PORT", "8080"))

# Ежедневный автобэкап: час по местному времени и общий выключатель.
BACKUP_ENABLED: bool = os.getenv("BACKUP_ENABLED", "1") == "1"


def _backup_hour(value: str) -> int:
    try:
        hour = int(value)
    except ValueError:
        hour = -1
    if 0 <= hour <= 23:
        return hour
    logger.warning(
        "BACKUP_HOUR=%r некорректен (ожидается 0–23), использую 4", value
    )
    return 4


BACKUP_HOUR: int = _backup_hour(os.getenv("BACKUP_HOUR", "4"))

# Каталог ежедневных архивов; на Railway лежит внутри Volume рядом с базой.
DEFAULT_BACKUP_DIR = str(Path(DB_PATH).expanduser().parent / "backups" / "daily")


def _backup_dir(value: str) -> str:
    resolved = value.strip()
    if resolved:
        return resolved
    logger.warning("BACKUP_DIR пуст, использую %s", DEFAULT_BACKUP_DIR)
    return DEFAULT_BACKUP_DIR


BACKUP_DIR: str = _backup_dir(os.getenv("BACKUP_DIR", DEFAULT_BACKUP_DIR))


def _backup_retention_days(value: str) -> int:
    try:
        days = int(value)
    except ValueError:
        days = 0
    if days >= 1:
        return days
    logger.warning(
        "BACKUP_RETENTION_DAYS=%r некорректен (минимум 1), использую 7", value
    )
    return 7


BACKUP_RETENTION_DAYS: int = _backup_retention_days(
    os.getenv("BACKUP_RETENTION_DAYS", "7")
)

TIMEZONE: str = os.getenv("TIMEZONE", "Europe/Moscow")

# Google/OpenAI недоступны (403 по региону) — берём открытые vision-модели
PRIMARY_MODEL: str = os.getenv("PRIMARY_MODEL", "qwen/qwen2.5-vl-72b-instruct")
FALLBACK_MODEL: str = os.getenv("FALLBACK_MODEL", "mistralai/mistral-small-3.2-24b-instruct")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
LLM_MODELS_URL = "https://openrouter.ai/api/v1/models"
LLM_TIMEOUT_SECONDS = 45
LLM_CONNECT_TIMEOUT_SECONDS = 10

# Провайдеры, которые логируют или обучаются на запросах, исключаются.
LLM_DENY_DATA_COLLECTION: bool = (
    os.getenv("LLM_DENY_DATA_COLLECTION", "1") == "1"
)

# Верхняя граница суммы: общая для бота, LLM-парсинга и API.
MAX_ABS_AMOUNT = Decimal("10000000000")
# Суммы выше этого порога уходят на ручную проверку.
LARGE_AMOUNT_REVIEW_THRESHOLD = Decimal("500000")

# Признаки запуска на Railway: защита mock-инструментов и production-guard API.
RAILWAY_ENV_VARS = (
    "RAILWAY_ENVIRONMENT",
    "RAILWAY_ENVIRONMENT_ID",
    "RAILWAY_PROJECT_ID",
    "RAILWAY_SERVICE_ID",
)

# Траты до этого часа ночи относятся к предыдущему дню
DAY_BOUNDARY_HOUR = 3

# Вечернее напоминание по умолчанию (меняется командой /remind, хранится в БД)
DEFAULT_REMINDER_TIME = "21:00"

OPERATION_TYPES = ("расход", "доход", "перевод")

EXPENSE_CATEGORIES = (
    "Жильё", "Продукты", "Готовая еда", "Кафе/Досуг", "Быт", "Техника",
    "Транспорт", "Лекарства", "Подписки", "Подарки", "Долги", "Прочее",
)
INCOME_CATEGORIES = ("Зарплата", "Реклама", "Услуги", "Подарки")

# Для графиков ритма не показываем фиксированные расходы и зарплату:
# они полезны в общих итогах, но искажают картину переменных операций.
RHYTHM_EXPENSE_EXCLUDED_CATEGORIES = ("Жильё", "Долги")
RHYTHM_INCOME_EXCLUDED_CATEGORIES = ("Зарплата",)


_BOT_TOKEN_RE = re.compile(r"^\d{6,12}:[A-Za-z0-9_-]{30,}$")


def _valid_tma_url(url: str) -> bool:
    if url.startswith("https://"):
        return True
    return url.startswith("http://localhost") or url.startswith("http://127.0.0.1")


def validate_config() -> list[str]:
    """Проверяет конфигурацию и возвращает список всех проблем сразу.

    Вызывается только из main.py: инструменты и тесты работают с мок-токенами.
    """
    problems: list[str] = []
    if not _BOT_TOKEN_RE.match(BOT_TOKEN):
        problems.append(
            "BOT_TOKEN не задан или имеет неверный формат "
            "(ожидается <id>:<ключ>)"
        )
    if ALLOWED_USER_ID <= 0:
        problems.append("ALLOWED_USER_ID должен быть положительным числом")
    if TMA_URL and not _valid_tma_url(TMA_URL):
        problems.append(
            "TMA_URL должен начинаться с https:// "
            "(локально допустим http://localhost)"
        )
    try:
        pytz.timezone(TIMEZONE)
    except pytz.UnknownTimeZoneError:
        problems.append(f"TIMEZONE={TIMEZONE} — неизвестная часовая зона")
    if not PRIMARY_MODEL.strip():
        problems.append("PRIMARY_MODEL не задан")
    if not FALLBACK_MODEL.strip():
        problems.append("FALLBACK_MODEL не задан")
    return problems


def plural_ru(n: int, forms: tuple[str, str, str]) -> str:
    value = abs(n)
    if value % 100 in (11, 12, 13, 14):
        return forms[2]
    if value % 10 == 1:
        return forms[0]
    if value % 10 in (2, 3, 4):
        return forms[1]
    return forms[2]
