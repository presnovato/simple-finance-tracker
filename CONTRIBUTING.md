# Участие в проекте

Спасибо за интерес к Finance Tracker. Небольшие исправления и улучшения можно
предлагать через pull request.

## Перед отправкой изменений

1. Создай отдельную ветку от актуального `main`.
2. Не добавляй `.env`, базу SQLite, токены, персональные финансовые данные и
   внутренние документы из `docs/`.
3. Для backend запусти:

   ```bash
   python -m ruff check finance_bot tests tools
   python -m coverage run -m pytest
   python -m coverage report --fail-under=75
   ```

4. Для TMA запусти из `tma/`:

   ```bash
   npm ci --legacy-peer-deps
   npm run typecheck
   npm test
   npm run build
   ```

Если изменился frontend, включи обновлённый `tma/dist/` в тот же pull request:
production-сервер раздаёт этот bundle.

## Принципы изменений

- Деньги обрабатываются через `Decimal` и integer-копейки в SQLite.
- Ручной сценарий должен оставаться работоспособным без AI.
- API должен сохранять owner-only защиту и валидацию входных данных.
- Для TMA проверяй узкий мобильный viewport и клавиатурные/семантические состояния
  интерактивных элементов.
- В описании pull request укажи причину изменения, проверенные команды и
  известные ограничения.
