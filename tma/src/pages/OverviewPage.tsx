import { useEffect, useMemo, useState } from 'react'
import {
  Bar,
  CartesianGrid,
  Cell,
  ComposedChart,
  Pie,
  PieChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import {
  TKButton,
  TKCard,
  TKIcon,
  TKIconButton,
  TKInput,
  TKNativeField,
  TKNoticeBar,
  TKProgress,
  TKSwitch,
  TKSheet,
  TKSpinner,
} from 'tg-mini-app-uikit'

import {
  api,
  getBudget,
  getBudgetSettings,
  queryString,
  updateBudgetSettings,
  updateCashBalance,
} from '../api'
import {
  formatDay,
  formatMoney,
  formatPeriodAxisDay,
  monthTitle,
  shiftMonth,
  todayMonth,
} from '../format'
import type {
  BudgetResponse,
  BudgetSettings,
  CashBalance,
  Categories,
  HistoryPreset,
  Summary,
} from '../types'

const COLORS = ['#77e6b6', '#9f8cff', '#ffca6a', '#ff7f8e', '#68b8ff', '#c7e36d']
const EXPENSE_CHART = '#77e6b6'
const INCOME_CHART = '#68b8ff'
const SHOW_CATEGORY_BREAKDOWN = true

interface Props {
  openHistory: (preset: HistoryPreset) => void
}

export function OverviewPage({ openHistory }: Props) {
  const [month, setMonth] = useState(todayMonth())
  const [summary, setSummary] = useState<Summary | null>(null)
  const [previousSummary, setPreviousSummary] = useState<Summary | null>(null)
  const [cashBalance, setCashBalance] = useState<CashBalance | null>(null)
  const [cashBalanceError, setCashBalanceError] = useState('')
  const [anchorSheetOpen, setAnchorSheetOpen] = useState(false)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [summaryRefresh, setSummaryRefresh] = useState(0)
  const [budget, setBudget] = useState<BudgetResponse | null>(null)
  const [budgetError, setBudgetError] = useState('')
  const [budgetLoading, setBudgetLoading] = useState(true)
  const [budgetRefresh, setBudgetRefresh] = useState(0)
  const [budgetSheetOpen, setBudgetSheetOpen] = useState(false)
  const [categoriesOpen, setCategoriesOpen] = useState(true)

  useEffect(() => {
    let active = true
    setLoading(true)
    setError('')
    setPreviousSummary(null)
    api<Summary>(`/api/summary${queryString({ month })}`)
      .then((data) => active && setSummary(data))
      .catch((reason: Error) => active && setError(reason.message))
      .finally(() => active && setLoading(false))
    api<Summary>(`/api/summary${queryString({ month: shiftMonth(month, -1) })}`)
      .then((data) => active && setPreviousSummary(data))
      .catch(() => undefined)
    return () => { active = false }
  }, [month, summaryRefresh])

  useEffect(() => {
    let active = true
    api<CashBalance>('/api/balance')
      .then((data) => active && setCashBalance(data))
      .catch((reason: Error) => active && setCashBalanceError(reason.message))
    return () => { active = false }
  }, [])

  useEffect(() => {
    let active = true
    setBudgetLoading(true)
    setBudgetError('')
    getBudget()
      .then((data) => active && setBudget(data))
      .catch((reason: Error) => active && setBudgetError(reason.message))
      .finally(() => active && setBudgetLoading(false))
    return () => { active = false }
  }, [budgetRefresh])

  const chartDays = useMemo(
    () => summary?.days.map((day) => ({
      ...day,
      expenseValue: Number(day.expense),
      incomeValue: Number(day.income),
    })) ?? [],
    [summary],
  )
  const categoryTotal = Number(summary?.expense || 0)
  const hasChartData = chartDays.some((day) => day.expenseValue > 0 || day.incomeValue > 0)

  if (loading && !summary) {
    return (
      <div className="page overview-page">
        <OverviewHeading />
        <div className="overview-loading"><TKSpinner label="Собираю цифры" /></div>
      </div>
    )
  }
  if (error && !summary) {
    return <div className="page overview-page"><OverviewHeading /><TKNoticeBar tone="red">{error}</TKNoticeBar></div>
  }
  if (!summary) return null

  return (
    <div className="page overview-page">
      <OverviewHeading />

      {summary.period_mode === 'anchor' ? (
        <div className="period-heading">
          <span className="eyebrow">Период по якорю</span>
          <strong>С {formatDay(summary.period_start)} по {formatDay(summary.period_end)}</strong>
        </div>
      ) : (
        <div className="month-controls">
          <TKIconButton
            size="md"
            variant="surface"
            icon="chevronLeft"
            label="Предыдущий месяц"
            onClick={() => setMonth(shiftMonth(month, -1))}
          />
          <div className="month-period-title">
            <span className="eyebrow">Месяц</span>
            <strong>{monthTitle(month)}</strong>
          </div>
          <TKIconButton
            size="md"
            variant="surface"
            icon="chevronRight"
            label="Следующий месяц"
            disabled={month >= todayMonth()}
            onClick={() => setMonth(shiftMonth(month, 1))}
          />
        </div>
      )}

      {budgetLoading && !budget && (
        <TKCard className="overview-budget-loading">
          <TKSpinner label="Загружаю бюджет" />
        </TKCard>
      )}
      {budgetError && !budget && <TKNoticeBar tone="red">{budgetError}</TKNoticeBar>}
      {budget && (
        <BudgetCard
          budget={budget}
          onConfigure={() => setBudgetSheetOpen(true)}
        />
      )}

      <div className="summary-metrics">
        <MetricTile
          className="metric-income"
          label="Доход"
          value={formatMoney(summary.income)}
          note={periodComparison(summary.income, previousSummary?.income)}
        />
        <MetricTile
          className="metric-expense"
          label="Расход"
          value={formatMoney(summary.expense)}
          note={periodComparison(summary.expense, previousSummary?.expense)}
        />
        <MetricTile
          className={`balance-tile${Number(summary.balance) < 0 ? ' metric-expense' : ''}`}
          label="Баланс периода"
          value={formatMoney(summary.balance)}
          note={Number(summary.transfer_in) || Number(summary.transfer_out)
            ? 'доходы − расходы ± переводы'
            : 'доходы − расходы'}
        />
        <LiquidityMetricTile
          balance={cashBalance}
          error={cashBalanceError}
          onOpen={() => setAnchorSheetOpen(true)}
        />
      </div>

      <TKSheet
        open={budgetSheetOpen}
        onClose={() => setBudgetSheetOpen(false)}
        title="Настройка недельного бюджета"
      >
        <BudgetSettingsForm
          onSaved={() => {
            setBudgetSheetOpen(false)
            setBudgetRefresh((value) => value + 1)
          }}
        />
      </TKSheet>

      <TKSheet
        open={anchorSheetOpen}
        onClose={() => setAnchorSheetOpen(false)}
        title={cashBalance?.has_anchor ? 'Изменить якорь' : 'Задать деньги на руках'}
      >
        <AnchorForm
          key={`${cashBalance?.anchor_amount ?? ''}-${cashBalance?.anchor_date ?? ''}`}
          balance={cashBalance}
          onSaved={(next) => {
            setCashBalance(next)
            setAnchorSheetOpen(false)
            setSummaryRefresh((value) => value + 1)
          }}
        />
      </TKSheet>

      <TKCard className="overview-chart-card">
        <div className="chart-heading">
          <div>
            <span className="eyebrow">Ритм периода</span>
            <h2>Динамика по дням</h2>
          </div>
          <div className="chart-averages">
            <span><i className="chart-average-dot chart-average-dot--expense" />Расход {formatMoney(summary.average_daily)}</span>
            <span><i className="chart-average-dot chart-average-dot--income" />Доход {formatMoney(summary.average_daily_income)}</span>
          </div>
        </div>
        {hasChartData ? (
          <div className="bar-chart" aria-label="Динамика расходов и доходов по дням">
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={chartDays} margin={{ top: 10, right: 0, left: 0, bottom: 0 }}>
              <CartesianGrid vertical={false} stroke="#242834" strokeDasharray="3 6" />
              <XAxis dataKey="op_date" tickFormatter={formatPeriodAxisDay} tick={{ fill: '#777e90', fontSize: 10 }} axisLine={false} tickLine={false} interval={0} minTickGap={0} />
              <YAxis tick={{ fill: '#777e90', fontSize: 10 }} axisLine={false} tickLine={false} width={48} />
              <Tooltip
                cursor={{ fill: 'rgba(119, 230, 182, .08)' }}
                contentStyle={{ background: '#171a22', border: '1px solid #2d3240', borderRadius: 12 }}
                labelFormatter={(label) => formatDayLabel(String(label))}
                formatter={(value, name) => [
                  formatMoney(String(value)),
                  name === 'expenseValue' ? 'Расход' : 'Доход',
                ]}
              />
              <ReferenceLine y={Number(summary.average_daily)} stroke="#ffca6a" strokeDasharray="5 5" />
              <Bar
                dataKey="expenseValue"
                name="Расход"
                fill={EXPENSE_CHART}
                radius={[5, 5, 2, 2]}
                minPointSize={2}
                onClick={(entry: unknown) => {
                  const row = entry as { op_date?: string; payload?: { op_date?: string } }
                  const opDate = row.op_date || row.payload?.op_date
                  if (opDate) openHistory({ date: opDate })
                }}
              />
              <Bar
                dataKey="incomeValue"
                name="Доход"
                fill={INCOME_CHART}
                radius={[5, 5, 2, 2]}
                minPointSize={2}
                onClick={(entry: unknown) => {
                  const row = entry as { op_date?: string; payload?: { op_date?: string } }
                  const opDate = row.op_date || row.payload?.op_date
                  if (opDate) openHistory({ date: opDate })
                }}
              />
            </ComposedChart>
          </ResponsiveContainer>
          </div>
        ) : (
          <div className="chart-empty">За выбранный период нет расходов и доходов для динамики.</div>
        )}
      </TKCard>

      {SHOW_CATEGORY_BREAKDOWN && (
        <CategoryBreakdown
          categories={summary.categories}
          total={categoryTotal}
          open={categoriesOpen}
          onToggle={() => setCategoriesOpen((value) => !value)}
          onOpenHistory={openHistory}
        />
      )}

    </div>
  )
}

function LiquidityMetricTile({
  balance,
  error,
  onOpen,
}: {
  balance: CashBalance | null
  error: string
  onOpen: () => void
}) {
  const hasAnchor = Boolean(balance?.has_anchor && balance.amount && balance.anchor_date)

  return (
    <div className="metric-tile liquidity-tile">
      <div className="metric-tile-heading">
        <span className="metric-label">Ликвидность</span>
        <span className="metric-action">
          <TKIconButton
            size="sm"
            variant="plain"
            icon="edit"
            label={hasAnchor ? 'Изменить деньги на руках' : 'Задать деньги на руках'}
            onClick={onOpen}
          />
        </span>
      </div>
      <strong className="metric-value">{hasAnchor ? formatMoney(balance!.amount!) : '—'}</strong>
      <span className="metric-note">
        {hasAnchor ? `Якорь на ${formatDay(balance!.anchor_date!)}` : 'Задай исходный остаток'}
      </span>
      {error && <span className="metric-error">{error}</span>}
    </div>
  )
}

function CategoryBreakdown({
  categories,
  total,
  open,
  onToggle,
  onOpenHistory,
}: {
  categories: Summary['categories']
  total: number
  open: boolean
  onToggle: () => void
  onOpenHistory: (preset: HistoryPreset) => void
}) {
  const chartCategories = categories
    .filter((category) => Number(category.total) > 0)
    .map((category) => ({ ...category, amount: Number(category.total) }))

  return (
    <TKCard className="category-breakdown-card">
      <button
        type="button"
        className="category-disclosure-trigger"
        aria-controls="category-breakdown-list"
        aria-expanded={open}
        onClick={onToggle}
      >
        <span className="category-disclosure-copy">
          <span className="eyebrow">Структура</span>
          <span className="category-disclosure-title">Расходы по категориям</span>
        </span>
        <span className="category-disclosure-summary">
          <TKIcon
            name="chevronDown"
            size={20}
            strokeWidth={2.2}
            className={`disclosure-icon${open ? ' is-open' : ''}`}
          />
        </span>
      </button>

      <div className="category-breakdown-content">
        {chartCategories.length > 0 && (
          <div className="category-pie" role="img" aria-label={`Расходы по категориям: ${formatMoney(String(total))}`}>
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={chartCategories}
                  dataKey="amount"
                  nameKey="category"
                  cx="50%"
                  cy="50%"
                  innerRadius="54%"
                  outerRadius="80%"
                  paddingAngle={2}
                  stroke="none"
                  isAnimationActive={false}
                >
                  {chartCategories.map((category, index) => (
                    <Cell key={category.category} fill={COLORS[index % COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip
                  contentStyle={{ background: '#171a22', border: '1px solid #2d3240', borderRadius: 12 }}
                  formatter={(value, name) => [formatMoney(String(value)), String(name)]}
                />
              </PieChart>
            </ResponsiveContainer>
            <div className="category-pie-center" aria-hidden="true">
              <strong>{formatMoney(String(total))}</strong>
              <span>расходы</span>
            </div>
          </div>
        )}

        {open && (
          <div id="category-breakdown-list" className="category-breakdown-list">
            {categories.map((category, index) => {
              const percent = total ? Number(category.total) / total * 100 : 0
              const color = COLORS[index % COLORS.length]
              return (
                <button
                  key={category.category}
                  type="button"
                  className="category-breakdown-row"
                  onClick={() => onOpenHistory({ category: category.category })}
                >
                  <span className="category-breakdown-values">
                    <span className="category-breakdown-label">
                      <i className="category-breakdown-swatch" style={{ background: color }} aria-hidden="true" />
                      <b>{category.category}</b>
                    </span>
                    <strong>{formatMoney(category.total)}</strong>
                  </span>
                  <TKProgress
                    value={Math.max(percent, 2)}
                    label={`${category.category}: ${Math.round(percent)}%`}
                    size="sm"
                    style={{
                      ['--tk-accent' as string]: color,
                      ['--tk-accent-grad' as string]: color,
                    }}
                  />
                </button>
              )
            })}
            {!categories.length && (
              <p className="category-breakdown-empty">В этом периоде расходов пока нет.</p>
            )}
          </div>
        )}
      </div>
    </TKCard>
  )
}

function BudgetCard({
  budget,
  onConfigure,
}: {
  budget: BudgetResponse
  onConfigure: () => void
}) {
  const overall = budget.overall
  const categories = budget.categories || []
  const [categoriesOpen, setCategoriesOpen] = useState(false)
  const hasCategories = categories.length > 0

  function toggleCategories() {
    if (hasCategories) setCategoriesOpen((value) => !value)
  }

  return (
    <TKCard className="overview-budget-card">
      <div className="budget-heading">
        <div>
          <span className="eyebrow">Недельный бюджет</span>
          <h2>Лимиты расходов</h2>
          <span className="budget-week-label">
            {formatDay(budget.week_start)} — {formatDay(budget.week_end)}
          </span>
        </div>
        {budget.is_current && (
          <TKIconButton
            size="md"
            variant="surface"
            icon="edit"
            label="Настроить бюджет"
            onClick={onConfigure}
          />
        )}
      </div>

      {!budget.configured ? (
        <div className="budget-empty">
          <p>Бюджет ещё не создан. Задай общий недельный лимит; категории и их лимиты можно добавить по желанию.</p>
          {budget.is_current && <TKButton variant="filled" onClick={onConfigure}>Настроить бюджет</TKButton>}
        </div>
      ) : (
        <>
          {overall ? (
            <div
              className={`budget-overall budget-status-${overall.status}${hasCategories ? ' budget-overall-clickable' : ''}`}
              role={hasCategories ? 'button' : undefined}
              tabIndex={hasCategories ? 0 : undefined}
              aria-expanded={hasCategories ? categoriesOpen : undefined}
              aria-controls={hasCategories ? 'budget-category-list' : undefined}
              onClick={hasCategories ? toggleCategories : undefined}
              onKeyDown={hasCategories ? (event) => {
                if (event.key === 'Enter' || event.key === ' ') {
                  event.preventDefault()
                  toggleCategories()
                }
              } : undefined}
            >
              <div className="budget-value-row budget-overall-main">
                <span className="budget-overall-label">Остаток</span>
                <span className="budget-overall-value">
                  <strong>{formatMoney(overall.spent)} из {formatMoney(overall.limit)}</strong>
                  {hasCategories && (
                    <TKIcon
                      name="chevronDown"
                      size={18}
                      strokeWidth={2.2}
                      className={`disclosure-icon${categoriesOpen ? ' is-open' : ''}`}
                    />
                  )}
                </span>
              </div>
              <TKProgress
                value={progressValue(overall.percent)}
                label={`Общий бюджет: ${overall.percent}%`}
                size="sm"
              />
            </div>
          ) : (
            <div className="budget-category-only">
              <span>Общий лимит не задан</span>
              <strong>{formatMoney(budget.selected_spent || '0')}</strong>
            </div>
          )}

          {categoriesOpen && (
            <div id="budget-category-list" className="budget-category-list">
              {categories.map((category) => (
                <div className="budget-category-row" key={category.category}>
                  <div className="budget-value-row">
                    <span>{category.category}</span>
                    <strong>
                      {category.limit
                        ? `${formatMoney(category.spent)} из ${formatMoney(category.limit)}`
                        : `${formatMoney(category.spent)} · без отдельного лимита`}
                    </strong>
                  </div>
                  {category.limit ? (
                    <>
                      <div className="budget-value-row budget-subvalue">
                        <span>{category.percent}%</span>
                        <strong>{budgetRemainingLabel(category.remaining)}</strong>
                      </div>
                      <TKProgress
                        value={progressValue(category.percent)}
                        label={`${category.category}: ${category.percent}%`}
                        size="sm"
                        style={{
                          ['--tk-accent' as string]: budgetStatusColor(category.status),
                          ['--tk-accent-grad' as string]: budgetStatusColor(category.status),
                        }}
                      />
                    </>
                  ) : (
                    <div className="budget-value-row budget-subvalue">
                      <span>Отдельный лимит не задан</span>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </TKCard>
  )
}

function BudgetSettingsForm({ onSaved }: { onSaved: () => void }) {
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
        setCategories(categoryData.expense)
        const configured = new Map(settings.categories.map((item) => [item.category, item.limit]))
        setEntries(Object.fromEntries(
          categoryData.expense.map((category) => [category, {
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

function periodComparison(current: string, previous?: string): string | undefined {
  if (previous === undefined) return undefined
  const delta = Number(current) - Number(previous)
  if (!Number.isFinite(delta)) return undefined
  if (delta === 0) return 'К прошлому месяцу: без изменений'
  return 'К прошлому месяцу: ' + (delta > 0 ? '+' : '−') + formatMoney(String(Math.abs(delta)))
}

function progressValue(percent: string | null): number {
  return Math.min(100, Math.max(0, Number(percent) || 0))
}

function budgetStatusColor(status: string | null): string {
  return status === 'exceeded' ? 'var(--red)' : status === 'warning' ? 'var(--yellow)' : 'var(--green)'
}

function budgetRemainingLabel(value: string | null): string {
  if (value === null) return 'Без отдельного лимита'
  const amount = Number(value)
  return amount < 0 ? `Перерасход ${formatMoney(String(Math.abs(amount)))}` : `Остаток ${formatMoney(value)}`
}

function AnchorForm({
  balance,
  onSaved,
}: {
  balance: CashBalance | null
  onSaved: (balance: CashBalance) => void
}) {
  const [amount, setAmount] = useState(balance?.anchor_amount || '')
  const [anchorDate, setAnchorDate] = useState(balance?.anchor_date || todayIsoDate())
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  async function submit() {
    if (!amount.trim()) {
      setError('Укажи сумму')
      return
    }
    setSaving(true)
    setError('')
    try {
      const next = await updateCashBalance(amount.replace(',', '.'), anchorDate)
      onSaved(next)
    } catch (reason) {
      setError((reason as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="debt-form">
      <TKInput
        label="Сумма на руках"
        inputMode="decimal"
        value={amount}
        onChange={(value) => setAmount(value.replace(',', '.'))}
      />
      <TKNativeField type="date" label="Дата пересчёта" value={anchorDate} onChange={setAnchorDate} />
      <p className="sheet-hint">Укажи фактический остаток на эту дату. Операции после неё будут добавляться и вычитаться автоматически.</p>
      {error && <TKNoticeBar tone="red">{error}</TKNoticeBar>}
      <TKButton full variant="filled" loading={saving} onClick={() => void submit()}>Сохранить якорь</TKButton>
    </div>
  )
}

function todayIsoDate(): string {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Europe/Moscow',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(new Date())
  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]))
  return `${values.year}-${values.month}-${values.day}`
}

function OverviewHeading() {
  return (
    <header className="page-heading">
      <div>
        <span className="eyebrow">Обзор</span>
        <h1>Деньги в фокусе</h1>
      </div>
    </header>
  )
}

function MetricTile({
  label,
  value,
  className = '',
  note,
}: {
  label: string
  value: string
  className?: string
  note?: string
}) {
  return (
    <div className={`metric-tile ${className}`.trim()}>
      <span className="metric-label">{label}</span>
      <strong className="metric-value">{value}</strong>
      {note && <span className="metric-note">{note}</span>}
    </div>
  )
}

function formatDayLabel(value: string): string {
  return new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'long' }).format(new Date(`${value}T12:00:00`))
}
