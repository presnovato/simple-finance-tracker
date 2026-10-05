import { useEffect, useState } from 'react'
import { TKCard, TKCell, TKIcon, TKNoticeBar } from 'tg-mini-app-uikit'

import { getUpcoming } from '../../api'
import { formatDay, formatMoney } from '../../format'
import type { UpcomingResponse } from '../../types'

export function UpcomingPaymentsCard({
  onOpen,
}: {
  onOpen: (kind: 'subscription' | 'debt', id: number) => void
}) {
  const [data, setData] = useState<UpcomingResponse | null>(null)
  const [error, setError] = useState('')
  const [open, setOpen] = useState(false)

  useEffect(() => {
    let active = true
    getUpcoming()
      .then((result) => active && setData(result))
      .catch((reason: Error) => active && setError(reason.message))
    return () => { active = false }
  }, [])

  const items = data?.items ?? []

  return (
    <TKCard className="upcoming-payments-card">
      <button
        type="button"
        className="category-disclosure-trigger"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        <span className="category-disclosure-copy">
          <span className="eyebrow">Обязательства</span>
          <span className="category-disclosure-title">Ближайшие платежи</span>
        </span>
        <span className="category-disclosure-summary">
          {items.length > 0 && <b className="upcoming-count">{items.length}</b>}
          <TKIcon
            name="chevronDown"
            size={20}
            strokeWidth={2.2}
            className={`disclosure-icon${open ? ' is-open' : ''}`}
          />
        </span>
      </button>
      {open && (
        <div className="upcoming-payments-list">
          {error && <TKNoticeBar tone="red">{error}</TKNoticeBar>}
          {!error && items.length === 0 && (
            <p className="category-breakdown-empty">Известных платежей на ближайшие 7 дней нет.</p>
          )}
          {items.map((item) => (
            <TKCell
              key={`${item.kind}-${item.id}`}
              title={item.name}
              subtitle={`${formatDay(item.date)} · ${item.kind === 'subscription' ? 'подписка' : 'платёж по долгу'}`}
              value={item.amount === null ? 'сумма не указана' : formatMoney(item.amount)}
              onClick={() => onOpen(item.kind, item.id)}
            />
          ))}
          {data?.errors?.length ? (
            <p className="category-breakdown-empty">Часть источников недоступна — список может быть неполным.</p>
          ) : null}
        </div>
      )}
    </TKCard>
  )
}
