import type { RefObject } from 'react'
import { TKCell, TKEmptyState, TKListGroup, TKSpinner } from 'tg-mini-app-uikit'

import { formatDay, formatMoney } from '../../format'
import type { Operation } from '../../types'
import { calculateDayTotals, compareOperations, formatDayNet } from './historyHelpers'

const EXPENSE = '#ff7f8e'
const INCOME = '#77e6b6'

export function HistoryGroups({
  items,
  loading,
  cursor,
  hasFilters,
  onOpen,
  sentinelRef,
}: {
  items: Operation[]
  loading: boolean
  cursor: string | null
  hasFilters: boolean
  onOpen: (operation: Operation) => void
  sentinelRef: RefObject<HTMLDivElement | null>
}) {
  const groups = new Map<string, Operation[]>()
  for (const item of [...items].sort(compareOperations)) {
    groups.set(item.op_date, [...(groups.get(item.op_date) || []), item])
  }

  return (
    <div className="history-groups">
      {[...groups.entries()].map(([opDate, operations]) => {
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
                      onClick={() => onOpen(operation)}
                      value={<b className={`operation-amount ${operation.type}`} style={{ color }}>{sign}{formatMoney(operation.amount)}</b>}
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

      <div ref={sentinelRef} className="load-sentinel">
        {loading ? <TKSpinner label="Загружаю" /> : cursor ? null : items.length ? (
          <span className="load-end-label">Это вся история</span>
        ) : null}
      </div>
    </div>
  )
}
