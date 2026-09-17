import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  TKButton,
  TKCell,
  TKChip,
  TKEmptyState,
  TKInput,
  TKListGroup,
  TKNativeField,
  TKNoticeBar,
  TKSearch,
  TKSegmented,
  TKSelect,
  TKSheet,
  TKSpinner,
  TKTextarea,
} from 'tg-mini-app-uikit'

import { api, createOperation, queryString } from '../api'
import { formatDay, formatMoney } from '../format'
import {
  buildOperationCreatePayload,
  buildOperationPatch,
  emptyOperationForm,
  formFromOperation,
  validateOperationForm,
} from '../operationForm'
import { haptic } from '../telegram'
import type {
  Categories,
  HistoryPreset,
  Operation,
  OperationPage,
  OperationType,
  TransferDirection,
} from '../types'

interface Props {
  preset: HistoryPreset
  presetVersion: number
}

const EXPENSE = '#ff7f8e'
const INCOME = '#77e6b6'

const TYPE_OPTIONS = [
  { value: '', label: 'Все' },
  { value: 'расход', label: 'Расход' },
  { value: 'доход', label: 'Доход' },
  { value: 'перевод', label: 'Перевод' },
]

export function HistoryPage({ preset, presetVersion }: Props) {
  const [items, setItems] = useState<Operation[]>([])
  const [categories, setCategories] = useState<Categories>({ expense: [], income: [] })
  const [category, setCategory] = useState('')
  const [type, setType] = useState<OperationType | ''>('')
  const [date, setDate] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [periodDraft, setPeriodDraft] = useState({ from: '', to: '' })
  const [periodError, setPeriodError] = useState('')
  const [filterSheetOpen, setFilterSheetOpen] = useState(false)
  const [periodSheetOpen, setPeriodSheetOpen] = useState(false)
  const [needsReview, setNeedsReview] = useState(false)
  const [searchInput, setSearchInput] = useState('')
  const [search, setSearch] = useState('')
  const [cursor, setCursor] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [refreshVersion, setRefreshVersion] = useState(0)
  const [editing, setEditing] = useState<Operation | null>(null)
  const [creating, setCreating] = useState(false)
  const [undo, setUndo] = useState<Operation | null>(null)
  const undoTimer = useRef<number | null>(null)
  const requestVersion = useRef(0)
  const sentinel = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    api<Categories>('/api/categories').then(setCategories).catch(() => undefined)
  }, [])

  useEffect(() => {
    setCategory(preset.category || '')
    setDate(preset.date || '')
    setDateFrom(preset.date_from || '')
    setDateTo(preset.date_to || '')
  }, [presetVersion, preset.category, preset.date, preset.date_from, preset.date_to])

  useEffect(() => {
    const timer = window.setTimeout(() => setSearch(searchInput.trim()), 300)
    return () => window.clearTimeout(timer)
  }, [searchInput])

  const filterQuery = useMemo(() => ({
    category: category || undefined,
    type: type || undefined,
    date: date || undefined,
    date_from: dateFrom || undefined,
    date_to: dateTo || undefined,
    q: search || undefined,
    needs_review: needsReview ? true : undefined,
  }), [category, type, date, dateFrom, dateTo, search, needsReview])

  useEffect(() => {
    const version = ++requestVersion.current
    setLoading(true)
    setError('')
    api<OperationPage>(`/api/operations${queryString(filterQuery)}`)
      .then((page) => {
        if (version !== requestVersion.current) return
        setItems(page.items)
        setCursor(page.next_cursor)
      })
      .catch((reason: Error) => version === requestVersion.current && setError(reason.message))
      .finally(() => version === requestVersion.current && setLoading(false))
  }, [filterQuery, refreshVersion])

  const loadMore = useCallback(async () => {
    if (!cursor || loading) return
    const version = requestVersion.current
    setLoading(true)
    try {
      const page = await api<OperationPage>(
        `/api/operations${queryString({ ...filterQuery, before: cursor })}`,
      )
      if (version !== requestVersion.current) return
      setItems((current) => {
        const known = new Set(current.map((item) => item.id))
        return [...current, ...page.items.filter((item) => !known.has(item.id))]
          .sort(compareOperations)
      })
      setCursor(page.next_cursor)
    } catch (reason) {
      if (version === requestVersion.current) setError((reason as Error).message)
    } finally {
      if (version === requestVersion.current) setLoading(false)
    }
  }, [cursor, filterQuery, loading])

  useEffect(() => {
    const node = sentinel.current
    if (!node) return
    const scrollRoot = node.closest('.app-content')
    const observer = new IntersectionObserver(
      ([entry]) => entry.isIntersecting && void loadMore(),
      {
        root: scrollRoot instanceof Element ? scrollRoot : null,
        rootMargin: '240px',
      },
    )
    observer.observe(node)
    return () => observer.disconnect()
  }, [loadMore])

  useEffect(() => () => {
    if (undoTimer.current !== null) window.clearTimeout(undoTimer.current)
  }, [])

  const groups = useMemo(() => {
    const grouped = new Map<string, Operation[]>()
    for (const item of [...items].sort(compareOperations)) {
      grouped.set(item.op_date, [...(grouped.get(item.op_date) || []), item])
    }
    return [...grouped.entries()]
  }, [items])

  const refreshHistory = () => {
    requestVersion.current += 1
    setRefreshVersion((value) => value + 1)
  }

  const replaceItem = () => {
    setEditing(null)
    setCreating(false)
    refreshHistory()
  }

  const confirm = async (operation: Operation) => {
    try {
      await api<Operation>(`/api/operations/${operation.id}/confirm`, { method: 'POST' })
      setEditing(null)
      refreshHistory()
      haptic('medium')
    } catch (reason) {
      setError((reason as Error).message)
    }
  }

  const remove = async (operation: Operation) => {
    try {
      await api(`/api/operations/${operation.id}`, { method: 'DELETE' })
      setItems((current) => current.filter((item) => item.id !== operation.id))
      setEditing(null)
      setUndo(operation)
      refreshHistory()
      if (undoTimer.current !== null) window.clearTimeout(undoTimer.current)
      undoTimer.current = window.setTimeout(() => setUndo(null), 5_000)
      haptic('medium')
    } catch (reason) {
      setError((reason as Error).message)
    }
  }

  const restore = async () => {
    if (!undo) return
    try {
      await api<Operation>(`/api/operations/${undo.id}/restore`, { method: 'POST' })
      setUndo(null)
      refreshHistory()
      if (undoTimer.current !== null) window.clearTimeout(undoTimer.current)
    } catch (reason) {
      setError((reason as Error).message)
    }
  }

  const clearFilters = () => {
    setCategory('')
    setType('')
    setDate('')
    setDateFrom('')
    setDateTo('')
    setNeedsReview(false)
    setSearchInput('')
    setSearch('')
  }
  const hasFilters = Boolean(
    category || type || date || dateFrom || dateTo || needsReview || searchInput,
  )

  const openPeriodSheet = () => {
    setPeriodDraft({ from: dateFrom, to: dateTo })
    setPeriodError('')
    setPeriodSheetOpen(true)
  }

  const applyPeriod = () => {
    if (periodDraft.from && periodDraft.to && periodDraft.from > periodDraft.to) {
      setPeriodError('Начало периода не может быть позже конца.')
      return
    }
    setDate('')
    setDateFrom(periodDraft.from)
    setDateTo(periodDraft.to)
    setPeriodSheetOpen(false)
  }

  const clearPeriod = () => {
    setPeriodDraft({ from: '', to: '' })
    setDateFrom('')
    setDateTo('')
  }

  const categoryChips = [
    ...categories.expense,
    ...categories.income.filter((item) => !categories.expense.includes(item)),
  ]
  const periodLabel = dateFrom || dateTo
    ? `${formatDay(dateFrom || dateTo)}${dateFrom && dateTo ? ` — ${formatDay(dateTo)}` : ''}`
    : ''
  const activeFilterCount = Number(needsReview)
    + Number(Boolean(dateFrom || dateTo))
    + Number(Boolean(date))
    + Number(Boolean(category))

  return (
    <div className="page history-page">
      <header className="page-heading">
        <div>
          <span className="eyebrow">Архив</span>
          <h1>История</h1>
        </div>
        <div className="page-heading-actions">
          <TKButton size="sm" variant="filled" onClick={() => setCreating(true)}>
            + Операция
          </TKButton>
          {hasFilters && (
            <TKButton size="sm" variant="plain" onClick={clearFilters}>Сбросить</TKButton>
          )}
        </div>
      </header>

      <div className="history-toolbar">
        <TKSearch
          value={searchInput}
          onChange={setSearchInput}
          placeholder="Поиск по комментарию"
          showCancelAction={false}
        />
        <TKButton size="sm" variant="tonal" onClick={() => setFilterSheetOpen(true)}>
          {activeFilterCount ? `Фильтры · ${activeFilterCount}` : 'Фильтры'}
        </TKButton>
      </div>

      <div className="history-filter-options">
        <TKSegmented
          full
          ariaLabel="Тип операции"
          options={TYPE_OPTIONS}
          value={type}
          onChange={(value) => setType(value as OperationType | '')}
        />
        {activeFilterCount > 0 && (
          <div className="history-active-filters">
            {needsReview && (
              <TKChip
                selected
                removable
                onClick={() => setNeedsReview(false)}
                onRemove={() => setNeedsReview(false)}
              >
                ⚠ Проверить
              </TKChip>
            )}
            {periodLabel && (
              <TKChip selected removable onClick={openPeriodSheet} onRemove={clearPeriod}>
                {periodLabel}
              </TKChip>
            )}
            {date && (
              <TKChip selected removable onClick={() => setDate('')} onRemove={() => setDate('')}>
                День · {formatDay(date)}
              </TKChip>
            )}
            {category && (
              <TKChip selected removable onClick={() => setCategory('')} onRemove={() => setCategory('')}>
                {category}
              </TKChip>
            )}
          </div>
        )}
      </div>

      {error && <TKNoticeBar tone="red">{error}</TKNoticeBar>}

      <div className="history-groups">
        {groups.map(([opDate, operations]) => {
          const dayTotals = calculateDayTotals(operations)
          const dayNet = dayTotals.income - dayTotals.expense
          return (
            <div className="history-group" key={opDate}>
              <TKListGroup
                separatorInset={16}
                title={(
                  <span className="history-day-title">
                    <strong>{formatDay(opDate)}</strong>
                    <span className={`history-day-net ${dayNet > 0 ? 'positive' : dayNet < 0 ? 'negative' : ''}`}>
                      {formatDayNet(dayNet)}
                    </span>
                  </span>
                )}
              >
                {operations.map((operation) => {
                  const sign = operation.type === 'расход'
                    ? '−'
                    : operation.type === 'доход'
                      ? '+'
                      : operation.transfer_direction === 'in' ? '+' : ''
                  const color = operation.type === 'расход' ? EXPENSE : operation.type === 'доход' ? INCOME : 'var(--tk-text-2)'
                  const transferLabel = operation.type === 'перевод' && operation.transfer_direction === 'self'
                    ? 'между своими'
                    : null
                  return (
                    <div key={operation.id}>
                      <TKCell
                        className={`operation-cell${operation.needs_review ? ' needs-review' : ''}`}
                        title={operation.comment || operation.category || 'Без описания'}
                        subtitle={[operation.note ? '📝' : null, operation.category, transferLabel, operation.type].filter(Boolean).join(' · ')}
                        onClick={() => setEditing(operation)}
                        value={<b className={`operation-amount ${operation.type}`}>{sign}{formatMoney(operation.amount)}</b>}
                      />
                    </div>
                  )
                })}
              </TKListGroup>
            </div>
          )
        })}

        {!loading && !items.length && (
          <TKEmptyState
            title={hasFilters ? 'Ничего не найдено' : 'История пока пуста'}
            text={hasFilters ? 'Измени или сбрось фильтры.' : 'Добавь первую операцию кнопкой выше или через бота.'}
          />
        )}

        <div ref={sentinel} className="load-sentinel">
          {loading ? <TKSpinner label="Загружаю" /> : cursor ? null : items.length ? (
            <span className="load-end-label">Это вся история</span>
          ) : null}
        </div>
      </div>

      <TKSheet
        open={filterSheetOpen}
        onClose={() => setFilterSheetOpen(false)}
        title="Фильтры истории"
      >
        <div className="history-filter-sheet">
          <section className="history-filter-section">
            <div className="history-filter-section-heading">
              <strong>Период</strong>
              <span>{periodLabel || (date ? `День ${formatDay(date)}` : 'Любой')}</span>
            </div>
            <TKButton
              full
              variant="tonal"
              onClick={() => {
                setFilterSheetOpen(false)
                openPeriodSheet()
              }}
            >
              {periodLabel ? `Изменить: ${periodLabel}` : 'Выбрать период'}
            </TKButton>
            {date && (
              <TKChip selected removable onClick={() => setDate('')} onRemove={() => setDate('')}>
                День · {formatDay(date)}
              </TKChip>
            )}
          </section>

          <section className="history-filter-section">
            <div className="history-filter-section-heading">
              <strong>Категория</strong>
              <span>{[needsReview ? 'На проверке' : null, category || null].filter(Boolean).join(' · ') || 'Любая'}</span>
            </div>
            <div className="history-category-options">
              <TKChip selected={needsReview} onClick={() => setNeedsReview((value) => !value)}>
                ⚠ Проверить
              </TKChip>
              {categoryChips.map((value) => (
                <TKChip
                  key={value}
                  selected={category === value}
                  onClick={() => setCategory(category === value ? '' : value)}
                >
                  {value}
                </TKChip>
              ))}
            </div>
          </section>

          {activeFilterCount > 0 && (
            <TKButton
              full
              variant="plain"
              onClick={() => {
                clearFilters()
                setFilterSheetOpen(false)
              }}
            >
              Сбросить фильтры
            </TKButton>
          )}
        </div>
      </TKSheet>

      <TKSheet
        open={periodSheetOpen}
        onClose={() => setPeriodSheetOpen(false)}
        title="Период истории"
      >
        <div className="history-period-form">
          <div className="history-period-fields">
            <TKNativeField
              type="date"
              label="От"
              value={periodDraft.from}
              onChange={(value) => setPeriodDraft((current) => ({ ...current, from: value }))}
            />
            <TKNativeField
              type="date"
              label="До"
              value={periodDraft.to}
              onChange={(value) => setPeriodDraft((current) => ({ ...current, to: value }))}
            />
          </div>
          {periodError && <TKNoticeBar tone="red">{periodError}</TKNoticeBar>}
          <TKButton full variant="filled" onClick={applyPeriod}>Применить период</TKButton>
          {(periodDraft.from || periodDraft.to) && (
            <TKButton full variant="plain" onClick={clearPeriod}>Очистить период</TKButton>
          )}
        </div>
      </TKSheet>

      <TKSheet open={Boolean(editing)} onClose={() => setEditing(null)} title="Редактировать">
        {editing && (
          <OperationEditor
            key={editing.id}
            operation={editing}
            categories={categories}
            onSaved={replaceItem}
            onConfirm={() => void confirm(editing)}
            onDelete={() => void remove(editing)}
          />
        )}
      </TKSheet>

      {undo && (
        <div className="undo-toast">
          <TKNoticeBar
            tone="accent"
            action={<TKButton size="sm" variant="plain" onClick={() => void restore()}>Отменить</TKButton>}
          >
            Операция удалена
          </TKNoticeBar>
        </div>
      )}

      <TKSheet open={creating} onClose={() => setCreating(false)} title="Новая операция">
        <OperationEditor
          key="new-operation"
          operation={null}
          categories={categories}
          onSaved={replaceItem}
        />
      </TKSheet>
    </div>
  )
}

interface EditorProps {
  operation: Operation | null
  categories: Categories
  onSaved: () => void
  onConfirm?: () => void
  onDelete?: () => void
}

function OperationEditor({ operation, categories, onSaved, onConfirm, onDelete }: EditorProps) {
  const initialForm = operation ? formFromOperation(operation) : emptyOperationForm()
  const baseline = useRef(initialForm)
  const [form, setForm] = useState(initialForm)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const categoryOptions = form.type === 'доход' ? categories.income : categories.expense

  const submit = async () => {
    setSaving(true); setError('')
    try {
      const validationError = validateOperationForm(form)
      if (validationError) {
        setError(validationError)
        return
      }
      if (operation) {
        const patch = buildOperationPatch(form, baseline.current)
        if (!Object.keys(patch).length) {
          onSaved()
          return
        }
        await api<Operation>(`/api/operations/${operation.id}`, {
          method: 'PATCH', body: JSON.stringify(patch),
        })
        baseline.current = form
        onSaved()
      } else {
        await createOperation(buildOperationCreatePayload(form))
        onSaved()
      }
      haptic('medium')
    } catch (reason) {
      setError((reason as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="history-editor-form">
      <TKInput
        label="Сумма"
        inputMode="decimal"
        value={form.amount}
        onChange={(value) => setForm({ ...form, amount: value.replace(',', '.') })}
      />
      <TKSelect
        label="Тип"
        options={[
          { value: 'расход', label: 'Расход' },
          { value: 'доход', label: 'Доход' },
          { value: 'перевод', label: 'Перевод' },
        ]}
        value={form.type}
        onChange={(value) => {
          const nextType = value as OperationType
          const nextOptions = nextType === 'доход' ? categories.income : categories.expense
          setForm((current) => ({
            ...current,
            type: nextType,
            category: nextType === 'перевод'
              ? ''
              : nextOptions.includes(current.category) ? current.category : '',
            transfer_direction: nextType === 'перевод'
              ? current.transfer_direction || 'out'
              : 'out',
          }))
        }}
      />
      <TKSelect
        label="Категория"
        disabled={form.type === 'перевод'}
        placeholder="Без категории"
        options={['', ...categoryOptions].map((item) => ({ value: item, label: item || 'Без категории' }))}
        value={form.category}
        onChange={(value) => setForm((current) => ({ ...current, category: value }))}
      />
      {form.type === 'перевод' && (
        <TKSelect
          label="Направление"
          options={[
            { value: 'in', label: 'Входящий' },
            { value: 'out', label: 'Исходящий' },
            { value: 'self', label: 'Между своими' },
          ]}
          value={form.transfer_direction}
          onChange={(value) => setForm((current) => ({
            ...current,
            transfer_direction: value as TransferDirection,
          }))}
        />
      )}
      <TKNativeField
        type="date"
        label="Дата"
        value={form.op_date}
        onChange={(value) => setForm({ ...form, op_date: value })}
      />
      <TKTextarea
        label="Комментарий"
        rows={2}
        value={form.comment}
        onChange={(value) => setForm({ ...form, comment: value })}
      />
      {operation && (
        <div className="history-editor-note">
          <TKTextarea
            label="Заметка"
            rows={2}
            value={form.note}
            onChange={(value) => setForm({ ...form, note: value })}
          />
          <span>
            Не перезаписывается ботом
          </span>
        </div>
      )}
      {error && <TKNoticeBar tone="red">{error}</TKNoticeBar>}
      {operation?.needs_review && onConfirm && (
        <TKButton full variant="tonal" onClick={onConfirm}>Подтвердить запись</TKButton>
      )}
      <TKButton full variant="filled" loading={saving} onClick={() => void submit()}>
        {operation ? 'Сохранить' : 'Записать операцию'}
      </TKButton>
      {operation && onDelete && (
        <TKButton full variant="destructive" onClick={onDelete}>Удалить операцию</TKButton>
      )}
    </div>
  )
}

function compareOperations(left: Operation, right: Operation): number {
  return right.op_date.localeCompare(left.op_date) || right.id - left.id
}

function calculateDayTotals(operations: Operation[]) {
  return operations.reduce(
    (result, operation) => {
      const amount = Number(operation.amount)
      if (operation.type === 'расход') result.expense += amount
      if (operation.type === 'доход') result.income += amount
      if (operation.type === 'перевод') result.transfer += amount
      return result
    },
    { expense: 0, income: 0, transfer: 0 },
  )
}

function formatDayNet(value: number): string {
  return value > 0 ? `+${formatMoney(value)}` : formatMoney(value)
}
