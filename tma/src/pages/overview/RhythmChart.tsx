import {
  Bar,
  CartesianGrid,
  ComposedChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { TKCard } from 'tg-mini-app-uikit'

import { chartSeriesLabel } from '../../chart'
import { formatDay, formatMoney, formatPeriodAxisDay } from '../../format'
import type { HistoryPreset, Summary } from '../../types'
import { formatDayLabel } from './overviewHelpers'

const EXPENSE_CHART = '#77e6b6'
const INCOME_CHART = '#68b8ff'

export function RhythmChart({
  summary,
  onOpenHistory,
}: {
  summary: Summary
  onOpenHistory: (preset: HistoryPreset) => void
}) {
  const chartDays = summary.days.map((day) => ({
    ...day,
    expenseValue: Number(day.expense),
    incomeValue: Number(day.income),
  }))
  const hasChartData = chartDays.some((day) => day.expenseValue > 0 || day.incomeValue > 0)

  const handleBarClick = (entry: unknown) => {
    const row = entry as { op_date?: string; payload?: { op_date?: string } }
    const opDate = row.op_date || row.payload?.op_date
    if (opDate) onOpenHistory({ date: opDate })
  }

  return (
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
              formatter={(value, _name, item) => [
                formatMoney(String(value)),
                chartSeriesLabel(item.dataKey),
              ]}
            />
            <ReferenceLine y={Number(summary.average_daily)} stroke="#ffca6a" strokeDasharray="5 5" />
            <Bar
              dataKey="expenseValue"
              name="Расход"
              fill={EXPENSE_CHART}
              radius={[5, 5, 2, 2]}
              minPointSize={2}
              onClick={handleBarClick}
            />
            <Bar
              dataKey="incomeValue"
              name="Доход"
              fill={INCOME_CHART}
              radius={[5, 5, 2, 2]}
              minPointSize={2}
              onClick={handleBarClick}
            />
          </ComposedChart>
        </ResponsiveContainer>
        </div>
      ) : (
        <div className="chart-empty">За выбранный период нет расходов и доходов для динамики.</div>
      )}
    </TKCard>
  )
}
