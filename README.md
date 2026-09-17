# Finance Tracker

Owner-only Telegram-бот и Telegram Mini App для личного учёта финансов.
Данные хранятся в SQLite, а интерфейс TMA объединяет обзор, историю, долги,
криптоактивы и подписки.

**Статус:** 1.0.0 — Stable Release
**Лицензия:** [MIT](LICENSE)

## Возможности

- Ручной ввод без ИИ: команда `/manual` запускает пошаговый сценарий в Telegram;
  в TMA новую операцию можно добавить из «Истории».
- Опциональный AI-захват: текст, фото и PDF чеков разбираются через OpenRouter;
  без `OPENROUTER_API_KEY` ручной режим и TMA продолжают работать.
- Правка, подтверждение, soft delete и восстановление операций.
- Обзор месяца, история с фильтрами и поиском, недельный бюджет.
- Долги: кредиты, личные долги, платежи, корректировка остатка и прогноз.
- Отдельные разделы для криптоактивов и регулярных подписок.
- Вечернее напоминание со сводкой дня и операциями, требующими проверки.

## Архитектура

- `finance_bot/` — Python 3.11+, aiogram, aiohttp, SQLite/aiosqlite.
- `tma/` — React 19, TypeScript, Vite, `tg-mini-app-uikit`, Recharts.
- `finance_bot/api/` — owner-only API с проверкой Telegram `initData`.
- `tma/dist/` — production bundle, который раздаёт aiohttp-сервер.
- `tools/mock_api_server.py` и Docker mock-профиль — безопасный локальный просмотр TMA
  без Telegram и внешнего API.

## Быстрый старт

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
Copy-Item .env.example .env
python -m finance_bot.main
```

Для macOS/Linux используй `python3 -m venv .venv`, `source .venv/bin/activate`,
`pip install -r requirements-dev.txt` и `cp .env.example .env`.

Для локального SQLite в `.env` удобно указать `DB_PATH=./finance.db` и
`DB_REQUIRE_PERSISTENT_DIR=0`. `OPENROUTER_API_KEY` нужен только для AI-захвата;
ручной сценарий `/manual` от него не зависит.

Основные команды Telegram-бота:

- `/start` — справка и запуск;
- `/manual` — пошаговый ввод операции без ИИ;
- `/dashboard` — сводка и ссылка на TMA.

## Проверки

Backend:

```bash
python -m ruff check finance_bot tests tools
python -m coverage run -m pytest
python -m coverage report --fail-under=75
```

TMA:

```bash
cd tma
npm ci --legacy-peer-deps
npm run typecheck
npm test
npm run build
```

Production bundle обновляется после `npm run build` и должен попасть в коммит
вместе с исходниками.

## Локальный запуск TMA

Backend API запускается вместе с polling на `0.0.0.0:$PORT`. Для локального
фронтенда:

```bash
cd tma
npm ci --legacy-peer-deps
npm run dev
```

В другом терминале с заполненным `.env` сгенерируй подписанную dev-ссылку:

```bash
python tools/generate_tma_dev_init_data.py
```

Production bundle собирается командой `npm run build` и хранится в `tma/dist`;
его раздаёт тот же aiohttp-сервер.

Для просмотра всех пяти разделов без Telegram и без настоящей базы:

```bash
docker compose -f docker-compose.mock.yml up --build
```

Затем открой [http://localhost:8080](http://localhost:8080). Это development-only
профиль с отключённой авторизацией; не публикуй его наружу.

## Документация и участие

- [CONTRIBUTING.md](CONTRIBUTING.md) — локальная настройка и правила изменений;
- [SECURITY.md](SECURITY.md) — обращение с секретами и финансовыми данными;
- [CHANGELOG.md](CHANGELOG.md) — история стабильных релизов.

## Деплой

GitHub → Railway (auto-deploy), web process задаётся в `Procfile`, Railway Volume
монтируется в `/data`. Для production нужны `DB_PATH=/data/finance.db` и
`TMA_URL` с публичным HTTPS-доменом Railway; `PORT` подставляет Railway.
Секреты хранятся только в variables Railway и локальном `.env`.

## Лицензия

Проект распространяется под [MIT License](LICENSE).
