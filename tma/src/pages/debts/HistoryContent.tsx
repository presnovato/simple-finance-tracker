import { useEffect, useState } from 'react'
import { TKEmptyState, TKNoticeBar, TKSpinner } from 'tg-mini-app-uikit'

import { listDebtHistory, listPersonalDebtHistory } from '../../api'
import { formatDay, formatMoney } from '../../format'
import type { DebtHistoryEntry } from '../../types'
import type { DebtTarget } from './debtTypes'


export function HistoryContent({ target }: { target: DebtTarget }) {
  const [items, setItems] = useState<DebtHistoryEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    setLoading(true)
    setError('')
    const request = target.kind === 'credit'
      ? listDebtHistory(target.debt.id)
      : listPersonalDebtHistory(target.debt.id)
    void request.then((page) => setItems(page.items))
      .catch((reason) => setError((reason as Error).message))
      .finally(() => setLoading(false))
  }, [target])

  if (loading) return <div className="debts-loader"><TKSpinner label="Загружаю историю" /></div>
  if (error) return <TKNoticeBar tone="red">{error}</TKNoticeBar>
  if (!items.length) return <TKEmptyState title="История пуста" text="Платежей и корректировок ещё нет." />

  return (
    <div className="debt-history">
      <div className="debt-history-summary">
        <span>Исходная сумма</span>
        <strong>{formatMoney(target.debt.principal)}</strong>
        <span>Текущий остаток тела</span>
        <strong>{formatMoney(target.debt.balance)}</strong>
      </div>
      {items.map((item) => (
        <div className="debt-history-row" key={`${item.kind}-${item.id}`}>
          <div>
            <strong>
              {item.kind === 'adjustment'
                ? 'Корректировка остатка'
                : item.payment_type === 'early' ? 'Досрочное погашение' : 'Обычный платёж'}
            </strong>
            <span>
              {formatDay(item.pay_date)}
              {item.kind === 'adjustment'
                ? ` · новый остаток${item.reason ? ` · ${item.reason}` : ''}`
                : [
                    item.principal_amount != null
                      ? `в тело ${formatMoney(item.principal_amount)}`
                      : 'тело не указано',
                    item.interest_amount != null
                      ? `проценты ${formatMoney(item.interest_amount)}`
                      : null,
                    item.cash_effect === 'already_in_balance'
                      ? 'уже учтено в балансе'
                      : null,
                  ].filter(Boolean).join(' · ')}
            </span>
          </div>
          <b>{formatMoney(item.amount)}</b>
        </div>
      ))}
    </div>
  )
}
