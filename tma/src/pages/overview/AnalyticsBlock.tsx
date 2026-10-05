import { useEffect, useState } from 'react'
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { TKCard, TKIcon, TKNoticeBar, TKSpinner } from 'tg-mini-app-uikit'

import { getBalanceHistory, getCategoryComparison } from '../../api'
import { formatMoney, formatPeriodAxisDay } from '../../format'
import type {
  BalanceHistoryPoint,
  BalanceHistoryResponse,
  CategoryComparisonResponse,
} from '../../types'
import { formatDayLabel, todayIsoDate } from './overviewHelpers'

const HISTORY_DAYS = 90
const CASH_CHART = '#68b8ff'

function shiftDays(iso: string, days: number): string {
  const [year, month, day] = iso.split('-').map(Number)
  return new Date(Date.UTC(year, month - 1, day + days)).toISOString().slice(0, 10)
}

function buildCashSeries(
  from: string,
  to: string,
  points: BalanceHistoryPoint[],
): Array<{ date: string; amountValue: number | null }> {
  const byDate = new Map(points.map((point) => [point.date, Number(point.amount)]))
  const series: Array<{ date: string; amountValue: number | null }> = []
  let cursor = from
  while (cursor <= to) {
    const value = byDate.get(cursor)
    series.push({ date: cursor, amountValue: value === undefined ? null : value })
    cursor = shiftDays(cursor, 1)
  }
  return series
}

export function AnalyticsBlock({ month }: { month: string }) {
  const [open, setOpen] = useState(false)
  const [comparison, setComparison] = useState<CategoryComparisonResponse | null>(null)
  const [cash, setCash] = useState<BalanceHistoryResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!open) return
    let active = true
    setLoading(true)
    setError('')
    const to = todayIsoDate()
    const from = shiftDays(to, -(HISTORY_DAYS - 1))
    Promise.all([getCategoryComparison(month), getBalanceHistory(from, to)])
      .then(([nextComparison, nextCash]) => {
        if (!active) return
        setComparison(nextComparison)
        setCash(nextCash)
      })
      .catch((reason: Error) => active && setError(reason.message))
      .finally(() => active && setLoading(false))
    return () => { active = false }
  }, [open, month])

  const categories = comparison?.categories ?? []
  const cashSeries = cash ? buildCashSeries(cash.date_from, cash.date_to, cash.items) : []
  const hasCash = Boolean(cash && cash.items.length)

  return (
    <TKCard className="analytics-card">
      <button
        type="button"
        className="category-disclosure-trigger"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        <span className="category-disclosure-copy">
          <span className="eyebrow">Аналитика</span>
          <span className="category-disclosure-title">Сравнение и деньги на руках</span>
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

      {open && (
        <div className="analytics-content">
          {loading && <TKSpinner label="Считаю аналитику" />}
          {error && <TKNoticeBar tone="red">{error}</TKNoticeBar>}
          {!loading && !error && (
            <>
              <section className="analytics-section">
                <h3>Расходы по категориям к прошлому периоду</h3>
                {categories.length === 0 && (
                  <p className="category-breakdown-empty">В выбранном месяце расходов нет.</p>
                )}
                {categories.map((item) => {
                  const change = Number(item.change)
                  return (
                    <div className="analytics-row" key={item.category}>
                      <span className="analytics-row-label">{item.category}</span>
                      <span className="analytics-row-values">
                        <strong>{formatMoney(item.current)}</strong>
                        <span>было {formatMoney(item.previous)}</span>
                      </span>
                      <span className={`analytics-row-change ${change > 0 ? 'negative' : change < 0 ? 'positive' : ''}`}>
                        {item.appeared
                          ? 'появилась'
                          : `${change > 0 ? '+' : ''}${formatMoney(item.change)}${item.percent !== null ? ` · ${item.percent}%` : ''}`}
                      </span>
                    </div>
                  )
                })}
              </section>

              <section className="analytics-section">
                <h3>Деньги на руках</h3>
                <p className="analytics-hint">
                  Только счета и наличные; крипта и долги не входят. Разрывы — дни без снимка.
                </p>
                {hasCash ? (
                  <div className="analytics-chart" style={{ height: 180 }}>
                    <ResponsiveContainer width="100%" height="100%">
                      <LineChart data={cashSeries} margin={{ top: 10, right: 8, left: 0, bottom: 0 }}>
                        <CartesianGrid vertical={false} stroke="#242834" strokeDasharray="3 6" />
                        <XAxis
                          dataKey="date"
                          tickFormatter={formatPeriodAxisDay}
                          tick={{ fill: '#777e90', fontSize: 10 }}
                          axisLine={false}
                          tickLine={false}
                          minTickGap={24}
                        />
                        <YAxis
                          tick={{ fill: '#777e90', fontSize: 10 }}
                          axisLine={false}
                          tickLine={false}
                          width={52}
                        />
                        <Tooltip
                          contentStyle={{ background: '#171a22', border: '1px solid #2d3240', borderRadius: 12 }}
                          labelFormatter={(label) => formatDayLabel(String(label))}
                          formatter={(value) => [formatMoney(String(value)), 'Деньги на руках']}
                        />
                        <Line
                          type="monotone"
                          dataKey="amountValue"
                          stroke={CASH_CHART}
                          strokeWidth={2}
                          dot={false}
                          connectNulls={false}
                          isAnimationActive={false}
                        />
                      </LineChart>
                    </ResponsiveContainer>
                  </div>
                ) : (
                  <p className="category-breakdown-empty">
                    История начнёт накапливаться с момента включения функции.
                  </p>
                )}
              </section>
            </>
          )}
        </div>
      )}
    </TKCard>
  )
}
