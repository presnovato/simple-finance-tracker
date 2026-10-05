import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  TKButton,
  TKChip,
  TKNoticeBar,
  TKSearch,
  TKSegmented,
  TKSheet,
} from 'tg-mini-app-uikit'

import { api, queryString } from '../api'
import { PageError } from '../components/PageState'
import { formatDay } from '../format'
import { haptic } from '../telegram'
import type {
  Categories,
  HistoryPreset,
  Operation,
  OperationPage,
  OperationType,
} from '../types'
import { HistoryFilterSheets } from './history/HistoryFilterSheets'
import { HistoryGroups } from './history/HistoryGroups'
import { OperationEditor } from './history/OperationEditor'

interface Props {
  preset: HistoryPreset
  presetVersion: number
}

const TYPE_OPTIONS = [
  { value: '', label: 'Все' },
  { value: 'расход', label: 'Расход' },
  { value: 'доход', label: 'Доход' },
  { value: 'перевод', label: 'Перевод' },
]

export function HistoryPage({ preset, presetVersion }: Props) {
  const [items, setItems] = useState<Operation[]>([])
  const [categories, setCategories] = useState<Categories>({ expense: [], income: [], archived_expense: [] })
  const [category, setCategory] = useState('')
  const [categoryNull, setCategoryNull] = useState(false)
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
    const presetCategory = preset.category || ''
    if (presetCategory === 'Без категории') {
      setCategory('')
      setCategoryNull(true)
    } else {
      setCategory(presetCategory)
      setCategoryNull(false)
    }
    setDate(preset.date || '')
    setDateFrom(preset.date_from || '')
    setDateTo(preset.date_to || '')
    setNeedsReview(Boolean(preset.needs_review))
  }, [presetVersion, preset.category, preset.date, preset.date_from, preset.date_to, preset.needs_review])

  useEffect(() => {
    const timer = window.setTimeout(() => setSearch(searchInput.trim()), 300)
    return () => window.clearTimeout(timer)
  }, [searchInput])

  const filterQuery = useMemo(() => ({
    category: category || undefined,
    category_null: categoryNull ? true : undefined,
    type: type || undefined,
    date: date || undefined,
    date_from: dateFrom || undefined,
    date_to: dateTo || undefined,
    q: search || undefined,
    needs_review: needsReview ? true : undefined,
  }), [category, categoryNull, type, date, dateFrom, dateTo, search, needsReview])

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
          .sort((left, right) => right.op_date.localeCompare(left.op_date) || right.id - left.id)
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
    setCategoryNull(false)
    setType('')
    setDate('')
    setDateFrom('')
    setDateTo('')
    setNeedsReview(false)
    setSearchInput('')
    setSearch('')
  }
  const hasFilters = Boolean(
    category || categoryNull || type || date || dateFrom || dateTo || needsReview || searchInput,
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
    ...categories.expense.map((value) => ({ value, label: value })),
    ...categories.archived_expense.map((value) => ({ value, label: `${value} · архив` })),
    ...categories.income
      .filter((item) => !categories.expense.includes(item) && !categories.archived_expense.includes(item))
      .map((value) => ({ value, label: value })),
  ]
  const periodLabel = dateFrom || dateTo
    ? `${formatDay(dateFrom || dateTo)}${dateFrom && dateTo ? ` — ${formatDay(dateTo)}` : ''}`
    : ''
  const activeFilterCount = Number(needsReview)
    + Number(Boolean(dateFrom || dateTo))
    + Number(Boolean(date))
    + Number(Boolean(category))
    + Number(categoryNull)

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
            {categoryNull && (
              <TKChip selected removable onClick={() => setCategoryNull(false)} onRemove={() => setCategoryNull(false)}>
                Без категории
              </TKChip>
            )}
          </div>
        )}
      </div>

      {error && !items.length && (
        <PageError message={error} onRetry={refreshHistory} />
      )}
      {error && items.length > 0 && <TKNoticeBar tone="red">{error}</TKNoticeBar>}

      <HistoryGroups
        items={items}
        loading={loading}
        cursor={cursor}
        hasFilters={hasFilters}
        onOpen={setEditing}
        sentinelRef={sentinel}
      />

      <HistoryFilterSheets
        filterOpen={filterSheetOpen}
        periodOpen={periodSheetOpen}
        category={category}
        categoryNull={categoryNull}
        date={date}
        needsReview={needsReview}
        categoryChips={categoryChips}
        periodLabel={periodLabel}
        periodDraft={periodDraft}
        periodError={periodError}
        activeFilterCount={activeFilterCount}
        onCloseFilter={() => setFilterSheetOpen(false)}
        onClosePeriod={() => setPeriodSheetOpen(false)}
        onCategory={setCategory}
        onToggleCategoryNull={() => {
          setCategory('')
          setCategoryNull((value) => !value)
        }}
        onDate={setDate}
        onToggleNeedsReview={() => setNeedsReview((value) => !value)}
        onOpenPeriod={openPeriodSheet}
        onPeriodDraft={setPeriodDraft}
        onApplyPeriod={applyPeriod}
        onClearPeriod={clearPeriod}
        onClearFilters={clearFilters}
      />

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
