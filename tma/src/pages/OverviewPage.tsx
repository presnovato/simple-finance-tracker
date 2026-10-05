import { useEffect, useState } from 'react'
import { TKIconButton, TKNoticeBar, TKSheet } from 'tg-mini-app-uikit'

import { api, getBudget, queryString } from '../api'
import { PageError, PageLoading } from '../components/PageState'
import { formatDay, formatMoney, monthTitle, shiftMonth, todayMonth } from '../format'
import type {
  BudgetResponse,
  CashBalance,
  HistoryPreset,
  Summary,
} from '../types'
import { AnalyticsBlock } from './overview/AnalyticsBlock'
import { AnchorForm } from './overview/AnchorForm'
import { BudgetCard } from './overview/BudgetCard'
import { BudgetSettingsForm } from './overview/BudgetSettingsForm'
import { CategoryBreakdown } from './overview/CategoryBreakdown'
import { LiquidityMetricTile } from './overview/LiquidityMetricTile'
import { MetricTile } from './overview/MetricTile'
import { ReviewQueueCard } from './overview/ReviewQueueCard'
import { RhythmChart } from './overview/RhythmChart'
import { UpcomingPaymentsCard } from './overview/UpcomingPaymentsCard'
import { periodComparison } from './overview/overviewHelpers'

const SHOW_CATEGORY_BREAKDOWN = true

interface Props {
  openHistory: (preset: HistoryPreset) => void
  openUpcoming: (kind: 'subscription' | 'debt', id: number) => void
}

export function OverviewPage({ openHistory, openUpcoming }: Props) {
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

  const categoryTotal = Number(summary?.expense || 0)

  if (loading && !summary) {
    return (
      <div className="page overview-page">
        <OverviewHeading />
        <PageLoading label="Собираю цифры" />
      </div>
    )
  }
  if (error && !summary) {
    return (
      <div className="page overview-page">
        <OverviewHeading />
        <PageError message={error} onRetry={() => setSummaryRefresh((value) => value + 1)} />
      </div>
    )
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
        <div className="overview-budget-loading"><PageLoading label="Загружаю бюджет" /></div>
      )}
      {budgetError && !budget && <TKNoticeBar tone="red">{budgetError}</TKNoticeBar>}
      {budget && (
        <BudgetCard
          budget={budget}
          onConfigure={() => setBudgetSheetOpen(true)}
        />
      )}

      <ReviewQueueCard
        count={summary.review_count}
        onOpen={() => openHistory({ needs_review: true })}
      />

      <UpcomingPaymentsCard onOpen={(kind, id) => openUpcoming(kind, id)} />

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

      <RhythmChart summary={summary} onOpenHistory={openHistory} />

      {SHOW_CATEGORY_BREAKDOWN && (
        <CategoryBreakdown
          categories={summary.categories}
          total={categoryTotal}
          open={categoriesOpen}
          onToggle={() => setCategoriesOpen((value) => !value)}
          onOpenHistory={openHistory}
        />
      )}

      <AnalyticsBlock month={month} />
    </div>
  )
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
