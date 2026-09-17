import os

from dotenv import load_dotenv

load_dotenv()

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

TIMEZONE: str = os.getenv("TIMEZONE", "Europe/Moscow")

# Google/OpenAI недоступны (403 по региону) — берём открытые vision-модели
PRIMARY_MODEL: str = os.getenv("PRIMARY_MODEL", "qwen/qwen2.5-vl-72b-instruct")
FALLBACK_MODEL: str = os.getenv("FALLBACK_MODEL", "mistralai/mistral-small-3.2-24b-instruct")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
LLM_TIMEOUT_SECONDS = 60

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


def plural_ru(n: int, forms: tuple[str, str, str]) -> str:
    value = abs(n)
    if value % 100 in (11, 12, 13, 14):
        return forms[2]
    if value % 10 == 1:
        return forms[0]
    if value % 10 in (2, 3, 4):
        return forms[1]
    return forms[2]
