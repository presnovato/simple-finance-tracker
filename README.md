# Finance Tracker

Owner-only Telegram-бот и Telegram Mini App для личного учёта финансов.
Данные хранятся в SQLite, а интерфейс TMA объединяет обзор, историю, долги,
криптоактивы и подписки.

**Статус:** 1.1.0
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

> ⚠️ Не запускай локальную копию с production-токеном. Два поллера на одном
> токене конфликтуют (`TelegramConflictError`), и апдейты случайно делятся
> между ними. Заведи отдельного dev-бота в @BotFather, используй его токен и
> локальный `DB_PATH`. В логе при старте видно, к какому боту подключился
> процесс: `Бот @<username> (id=<id>) запущен`.

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

Гарантии mock-профиля:

- порт публикуется только на `127.0.0.1` — с других машин в сети он недоступен;
- оба контейнера запускаются с `FINANCE_TRACKER_MOCK=1`, а
  `tools/mock_tma_server.py` и `tools/seed_mock_database.py` откажутся работать
  без этой переменной, при наличии переменных Railway или с настоящим
  `BOT_TOKEN`;
- сервер раздаёт только базу, помеченную `settings.mock_database=1`, а
  `MOCK_RESET=1` не удалит файл без этой метки;
- внутри контейнера сервер слушает `MOCK_BIND_HOST=0.0.0.0` (нужно для
  проброса порта Docker), локально по умолчанию — `127.0.0.1`.

> ⚠️ Никогда не запускай скрипты из `tools/` с production-`.env`: mock-инструменты
> работают только с отдельной mock-базой.

## Резервные копии и восстановление

Каждую ночь (по умолчанию в `BACKUP_HOUR=4` по `TIMEZONE`) бот присылает в чат
владельца сжатый файл `finance_backup_ГГГГ-ММ-ДД.db.gz` с полной копией базы.
Если база не менялась с прошлой отправки, файл не отправляется — вместо этого
обновляется отметка `backup_last_checked_at`. Если бот был выключен в момент
запуска задачи, пропущенный бэкап догоняется примерно через минуту после старта.
Перед каждой новой миграцией схемы рядом с базой сохраняется снимок
`<db_dir>/backups/pre-migration-v<N>-<UTC>.db` (хранятся три последних).

### Локальное восстановление

```bash
gunzip finance_backup_2026-09-24.db.gz
sqlite3 finance.db "PRAGMA integrity_check"   # должно вывести ok
DB_PATH=./finance.db DB_REQUIRE_PERSISTENT_DIR=0 python -m finance_bot.main
```

### Восстановление на Railway

Файл можно положить на Volume через Railway CLI (`railway volume files`).
Останови сервис перед заменой базы, чтобы не было двух писателей и лишнего WAL:

```bash
gunzip finance_backup_2026-09-24.db.gz
sqlite3 finance.db "PRAGMA integrity_check"
railway volume files --volume <volume> list /
railway volume files --volume <volume> upload ./finance.db /finance.db --overwrite
```

Если в списке остались `finance.db-wal` или `finance.db-shm` от старой базы,
удали их через `railway volume browse /` (или `railway volume files delete`),
затем запусти сервис заново. После старта проверь `/health` и что в «Истории»
видны последние операции.

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
