import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from 'recharts'
import { TKCard, TKIcon, TKProgress } from 'tg-mini-app-uikit'

import { formatMoney } from '../../format'
import type { HistoryPreset, Summary } from '../../types'

const COLORS = ['#77e6b6', '#9f8cff', '#ffca6a', '#ff7f8e', '#68b8ff', '#c7e36d']

export function CategoryBreakdown({
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
