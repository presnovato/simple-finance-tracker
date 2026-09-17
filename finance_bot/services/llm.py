"""Извлечение операции через OpenRouter: primary-модель с фолбэком.

Текст и файлы идут в одну vision-модель (единый промпт, единый парсер).
PDF — через plugin file-parser (native → mistral-ocr при сбое),
PNG/фото — data-URI base64 без плагина.
"""

import base64
import json
import logging
from datetime import date

import httpx

from finance_bot.config import (
    EXPENSE_CATEGORIES, FALLBACK_MODEL, INCOME_CATEGORIES, LLM_TIMEOUT_SECONDS,
    OPENROUTER_API_KEY, OPENROUTER_URL, PRIMARY_MODEL,
)
from finance_bot.core.debts import (may_contain_debt_intent,
                                    parse_debt_intent_response)
from finance_bot.core.parsing import (FALLBACK, parse_llm_response,
                                      parse_llm_response_many)

logger = logging.getLogger(__name__)

MCC_MAP = """Жильё: 4900, 6513
Продукты: 5411, 5499
Готовая еда: 5814 (доставка/навынос), 5462
Кафе/Досуг: 5812, 5813, 5814 (на месте)
Быт: 5200, 5719, 5211, 5251, 5712, 5977, 7230
Техника: 5732, 5722, 5045
Транспорт: 4121, 4111, 7512, 7523, 5541, 5542
Лекарства: 5912, 8011, 8021, 8062
Подписки: 5815, 5816, 5817, 4899
Подарки: 5944, 5992, 5947"""


def is_available() -> bool:
    """Возвращает, настроен ли внешний AI-провайдер для этого процесса."""
    return bool(OPENROUTER_API_KEY.strip())


def build_extract_prompt(today: date) -> str:
    return f"""Ты парсер финансовых операций. Пользователь присылает трату/доход \
  текстом или чеком (документ). Верни СТРОГО один JSON-объект без пояснений:
{{"intent":"operation|subscription", "date": "YYYY-MM-DD", "type": "расход|доход|перевод", "amount": число,
 "category": строка или null, "comment": строка, "account": "карта|нал|null",
 "transfer_direction": "in|out|self|null", "title": строка или null,
 "period": "monthly|yearly|null", "next_charge": "YYYY-MM-DD|null",
 "needs_review": true|false}}

Правила:
- intent по умолчанию operation. Если сообщение явно заводит регулярную подписку
  («подписка Netflix 899 в месяц с 15 числа», «оформил Яндекс Плюс 399/мес»),
  ставь intent=subscription, заполняй title, amount, period, next_charge и comment.
  Для subscription категория всегда «Подписки». Если указано только число месяца,
  верни ближайшую такую дату в будущем относительно финансового сегодня.
  Не называй обычную покупку подпиской только из-за слова «месяц».
- date: из чека, если есть; иначе {today.isoformat()} (сегодня). Для текста
  распознавай сегодня/вчера/позавчера, «N дней назад», день недели
  («в субботу» = ближайшая прошедшая суббота) и «5 июля» без года.
  Для даты без года используй текущий год, но если она оказалась в будущем —
  прошлый. Дата в будущем недопустима.
- платёж по банковскому кредиту/рассрочке = расход, категория «Долги».
- выдача и возврат личного долга = перевод; также переводом считаются обмен
  валюты и движение между своими счетами. Это не трата и не доход.
- Для перевода укажи transfer_direction: in — получил/вернули/пришло от кого-то;
  self — перевёл между своими счетами, на наличные или между своими кошельками;
  out — отправил наружу. Если направление неясно, выбери out и needs_review=true.
- amount: число с точкой (779,96 → 779.96; 1 000 → 1000).
  В фискальном чеке бери ИТОГО, не отдельные позиции.
- category для расхода — одно из: {", ".join(EXPENSE_CATEGORIES)}.
  Для дохода: {", ".join(INCOME_CATEGORIES)}. Для перевода: null.
- Маркетплейсы (Ozon/WB) → Прочее + needs_review=true.
  Платежи в бюджет (налоги/штрафы, КБК/УИН) → Прочее + needs_review=true.
  Фастфуд: навынос/доставка → Готовая еда, на месте → Кафе/Досуг.
- comment: продавец или суть операции, коротко.
- needs_review=true, если не уверен.

Карта MCC → категория:
{MCC_MAP}"""


def build_extract_many_prompt(today: date) -> str:
    return f"""Ты парсер списка финансовых операций со скриншота банковского
приложения или трекера. Верни СТРОГО JSON-массив без пояснений, не более
20 объектов. Каждый объект имеет структуру:
{{"date": "YYYY-MM-DD", "type": "расход|доход|перевод", "amount": число,
"category": строка или null, "comment": строка, "account": "карта|нал|null",
"transfer_direction": "in|out|self|null",
"needs_review": true|false}}

Правила:
- Одна видимая операция в списке = один объект. Не объединяй разные строки.
- date: дата строки, иначе {today.isoformat()}. Дата в будущем недопустима.
- платёж по банковскому кредиту/рассрочке = расход, категория «Долги».
- выдача и возврат личного долга, обмен валюты и движение между своими
  счетами = перевод; category для него null.
- Для перевода укажи transfer_direction: in — входящий, self — между своими
  счетами/кошельками, out — исходящий наружу. Неясное направление = out и
  needs_review=true.
- amount: число с точкой (779,96 → 779.96; 1 000 → 1000).
- category для расхода — одно из: {", ".join(EXPENSE_CATEGORIES)}.
  Для дохода: {", ".join(INCOME_CATEGORIES)}.
- Маркетплейсы и платежи в бюджет → Прочее + needs_review=true.
- comment: продавец или суть операции, коротко.
- needs_review=true, если какая-либо строка распознана неуверенно.

Карта MCC → категория:
{MCC_MAP}"""


CORRECT_PROMPT = """Ты правишь запись финансовой операции по указанию пользователя.
Текущая запись (JSON): {record}
Текст предыдущего сообщения бота или исходный контекст: «{context}»
Указание пользователя: «{instruction}»
Верни СТРОГО один JSON-объект той же структуры со ВСЕМИ полями
(и изменёнными, и оставшимися как были), без пояснений."""


def build_debt_intent_prompt(today: date) -> str:
    return f"""Ты короткий классификатор сообщений о долгах. Верни СТРОГО один
JSON-объект без пояснений:
{{"intent":"expense|debt_payment|personal_debt_new|personal_debt_repay",
"amount":число или null,"creditor":строка или null,"person":строка или null,
"direction":"owed_to_me|i_owe|null","date":"YYYY-MM-DD",
"due_date":"YYYY-MM-DD|null","comment":строка или null,
"needs_review":true|false}}

Правила:
- Обычная покупка или сообщение не о долге → intent expense.
- «Платёж по кредиту Сбер 15000», погашение рассрочки → debt_payment;
  creditor — банк/название кредита.
- «дал Васе 5000», «одолжил Васе» → personal_debt_new,
  direction owed_to_me.
- «занял у Маши 10000», «Маша одолжила мне» → personal_debt_new,
  direction i_owe.
- «Вася вернул 2000», «вернули мне» → personal_debt_repay,
  direction owed_to_me.
- «вернул Маше 10000», «погасил долг перед Машей» → personal_debt_repay,
  direction i_owe.
- date по умолчанию {today.isoformat()}; future недопустим.
- Не путай личный долг и банковский кредит. При неуверенности ставь
  needs_review=true, но выбирай самый вероятный intent."""


async def _call(model: str, messages: list, plugins: list | None = None) -> str:
    payload: dict = {"model": model, "messages": messages}
    if plugins:
        payload["plugins"] = plugins
    async with httpx.AsyncClient(timeout=LLM_TIMEOUT_SECONDS) as client:
        resp = await client.post(
            OPENROUTER_URL,
            headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}"},
            json=payload,
        )
        if resp.status_code >= 400:
            logger.error("OpenRouter %s: %s", resp.status_code, resp.text[:500])
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


def _messages(prompt: str, user_content) -> list:
    return [{"role": "system", "content": prompt},
            {"role": "user", "content": user_content}]


async def _extract(user_content, today: date, plugins: list | None = None) -> dict:
    """Primary → fallback-модель; полный провал → FALLBACK-запись."""
    if not is_available():
        return dict(FALLBACK, date=today)
    prompt = build_extract_prompt(today)
    for model in (PRIMARY_MODEL, FALLBACK_MODEL):
        try:
            raw = await _call(model, _messages(prompt, user_content), plugins)
            return parse_llm_response(raw, default_date=today)
        except Exception:
            logger.exception("LLM %s не ответила", model)
    return dict(FALLBACK, date=today)


async def _extract_many(user_content, today: date) -> list[dict]:
    if not is_available():
        return []
    prompt = build_extract_many_prompt(today)
    for model in (PRIMARY_MODEL, FALLBACK_MODEL):
        try:
            raw = await _call(model, _messages(prompt, user_content))
            parsed = parse_llm_response_many(raw, default_date=today)
            if parsed:
                return parsed
        except Exception:
            logger.exception("Мульти-разбор через %s не удался", model)
    return []


async def extract_debt_intent(text: str, today: date) -> dict:
    """Отдельный классификатор; для обычного текста сеть вообще не вызывается."""
    if not is_available() or not may_contain_debt_intent(text):
        return parse_debt_intent_response("", today)
    prompt = build_debt_intent_prompt(today)
    for model in (PRIMARY_MODEL, FALLBACK_MODEL):
        try:
            raw = await _call(model, _messages(prompt, text))
            return parse_debt_intent_response(raw, today)
        except Exception:
            logger.exception("Классификатор долгов через %s не ответил", model)
    return parse_debt_intent_response("", today)


async def extract_from_text(text: str, today: date) -> dict:
    return await _extract(text, today)


async def extract_from_image(data: bytes, mime: str, today: date) -> dict:
    uri = f"data:{mime};base64,{base64.b64encode(data).decode()}"
    content = [{"type": "image_url", "image_url": {"url": uri}}]
    return await _extract(content, today)


async def extract_many_from_image(data: bytes, mime: str, today: date) -> list[dict]:
    uri = f"data:{mime};base64,{base64.b64encode(data).decode()}"
    content = [{"type": "image_url", "image_url": {"url": uri}}]
    return await _extract_many(content, today)


async def extract_many_from_pdf(
    data: bytes, filename: str, today: date
) -> list[dict]:
    if not is_available():
        return []
    uri = f"data:application/pdf;base64,{base64.b64encode(data).decode()}"
    content = [{"type": "file", "file": {"filename": filename, "file_data": uri}}]
    prompt = build_extract_many_prompt(today)
    for model in (PRIMARY_MODEL, FALLBACK_MODEL):
        try:
            raw = await _call(
                model,
                _messages(prompt, content),
                [{"id": "file-parser", "pdf": {"engine": "mistral-ocr"}}],
            )
            parsed = parse_llm_response_many(raw, default_date=today)
            if parsed:
                return parsed
        except Exception:
            logger.exception("Мульти-разбор PDF через %s не удался", model)
    return []


async def extract_from_pdf(data: bytes, filename: str, today: date) -> dict:
    if not is_available():
        return dict(FALLBACK, date=today)
    uri = f"data:application/pdf;base64,{base64.b64encode(data).decode()}"
    content = [{"type": "file", "file": {"filename": filename, "file_data": uri}}]
    prompt = build_extract_prompt(today)
    # mistral-ocr рендерит PDF для модели; native был нужен только Gemini
    for model, engine in ((PRIMARY_MODEL, "mistral-ocr"),
                          (FALLBACK_MODEL, "mistral-ocr")):
        plugins = [{"id": "file-parser", "pdf": {"engine": engine}}]
        try:
            raw = await _call(model, _messages(prompt, content), plugins)
            return parse_llm_response(raw, default_date=today)
        except Exception:
            logger.exception("PDF через %s/%s не разобрался", model, engine)
    return dict(FALLBACK, date=today)


async def correct_operation(
    record: dict,
    instruction: str,
    today: date,
    context: str | None = None,
) -> dict:
    if not is_available():
        return dict(FALLBACK, date=today)
    serializable = {k: (str(v) if k == "amount" else
                        v.isoformat() if hasattr(v, "isoformat") else v)
                    for k, v in record.items()}
    prompt = CORRECT_PROMPT.format(
        record=json.dumps(serializable, ensure_ascii=False),
        context=(context or "нет")[:4000],
        instruction=instruction,
    )
    for model in (PRIMARY_MODEL, FALLBACK_MODEL):
        try:
            raw = await _call(model, [{"role": "user", "content": prompt}])
            return parse_llm_response(raw, default_date=today)
        except Exception:
            logger.exception("Правка через %s не удалась", model)
    return dict(FALLBACK, date=today)
