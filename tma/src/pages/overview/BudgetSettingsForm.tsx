import { useEffect, useState } from 'react'
import {
  TKButton,
  TKInput,
  TKNoticeBar,
  TKSpinner,
  TKSwitch,
} from 'tg-mini-app-uikit'

import { api, getBudgetSettings, updateBudgetSettings } from '../../api'
import type { BudgetSettings, Categories } from '../../types'

export function BudgetSettingsForm({ onSaved }: { onSaved: () => void }) {
  const [overallLimit, setOverallLimit] = useState('')
  const [categories, setCategories] = useState<string[]>([])
  const [entries, setEntries] = useState<Record<string, { enabled: boolean; limit: string }>>({})
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true
    setLoading(true)
    Promise.all([
      getBudgetSettings(),
      api<Categories>('/api/categories'),
    ])
      .then(([settings, categoryData]) => {
        if (!active) return
        setOverallLimit(settings.overall_limit || '')
        const configured = new Map(settings.categories.map((item) => [item.category, item.limit]))
        // Архивные лимиты, уже сохранённые, остаются видимыми и сохраняются,
        // если пользователь их не отключит (spec 01).
        const archivedConfigured = settings.categories
          .map((item) => item.category)
          .filter((name) => !categoryData.expense.includes(name))
        const rows = [...categoryData.expense, ...archivedConfigured]
        setCategories(rows)
        setEntries(Object.fromEntries(
          rows.map((category) => [category, {
            enabled: configured.has(category),
            limit: configured.get(category) || '',
          }]),
        ))
      })
      .catch((reason: Error) => active && setError(reason.message))
      .finally(() => active && setLoading(false))
    return () => { active = false }
  }, [])

  const activeCategories = categories
    .map((category) => ({ category, ...entries[category] }))
    .filter((item) => item.enabled)
  const canSave = !loading
    && isPositiveBudgetValue(overallLimit)
    && activeCategories.every(
      (item) => !item.limit.trim() || isPositiveBudgetValue(item.limit),
    )

  async function submit() {
    if (!canSave) {
      setError(
        !isPositiveBudgetValue(overallLimit)
          ? 'Задай положительный общий недельный лимит.'
          : 'Оставь лимит категории пустым или задай положительную сумму.'
      )
      return
    }
    setSaving(true)
    setError('')
    try {
      const payload: BudgetSettings = {
        overall_limit: overallLimit.trim().replace(',', '.'),
        categories: activeCategories.map((item) => ({
          category: item.category,
          limit: item.limit.trim()
            ? item.limit.trim().replace(',', '.')
            : null,
        })),
      }
      await updateBudgetSettings(payload)
      onSaved()
    } catch (reason) {
      setError((reason as Error).message)
    } finally {
      setSaving(false)
    }
  }

  if (loading) return <div className="budget-settings-loading"><TKSpinner label="Загружаю настройки" /></div>

  return (
    <div className="budget-settings-form">
      <TKInput
        label="Общий недельный лимит"
        inputMode="decimal"
        value={overallLimit}
        onChange={(value) => setOverallLimit(value.replace(',', '.'))}
        hint="Обязателен для сохранения бюджета; определяет общий статус и уведомления."
      />
      <p className="sheet-hint">Категории и их лимиты необязательны. Если категории не выбраны, общий бюджет считает все расходы за неделю.</p>
      <div className="budget-settings-list">
        {categories.map((category) => {
          const entry = entries[category]
          return (
            <div className="budget-setting-row" key={category}>
              <TKSwitch
                label={category}
                checked={entry?.enabled || false}
                onChange={(enabled) => setEntries((current) => ({
                  ...current,
                  [category]: { ...current[category], enabled },
                }))}
              />
                {entry?.enabled && (
                  <TKInput
                    label={`Лимит: ${category}`}
                    inputMode="decimal"
                    value={entry.limit}
                    onChange={(value) => setEntries((current) => ({
                      ...current,
                      [category]: { ...current[category], limit: value.replace(',', '.') },
                    }))}
                    hint="Необязательно: оставь пустым, если для категории не нужен отдельный лимит."
                  />
                )}
            </div>
          )
        })}
      </div>
      {error && <TKNoticeBar tone="red">{error}</TKNoticeBar>}
      <TKButton full variant="filled" loading={saving} disabled={!canSave} onClick={() => void submit()}>
        Сохранить бюджет
      </TKButton>
    </div>
  )
}

function isPositiveBudgetValue(value: string): boolean {
  const number = Number(value.trim().replace(',', '.'))
  return Boolean(value.trim()) && Number.isFinite(number) && number > 0
}
