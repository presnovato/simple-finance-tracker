import { TKButton, TKCard } from 'tg-mini-app-uikit'

import { formatDay, formatMoney } from '../../format'
import type { DebtTarget, UpcomingPayment } from './debtTypes'
import { sumPayments } from './debtHelpers'


export function UpcomingPayments({
  payments,
  onPay,
}: {
  payments: UpcomingPayment[]
  onPay: (target: DebtTarget) => void
}) {
  const overdueTotal = sumPayments(payments, (item) => item.days < 0)
  const nextSevenDaysTotal = sumPayments(payments, (item) => item.days >= 0 && item.days <= 7)
  const nextThirtyDaysTotal = sumPayments(payments, (item) => item.days >= 0 && item.days <= 30)
  const visiblePayments = payments.slice(0, 5)

  return (
    <TKCard className="debt-priority-card">
      <div className="debt-priority-heading">
        <div>
          <span className="eyebrow">На контроле</span>
          <h3>Ближайшие платежи</h3>
        </div>
        {overdueTotal > 0 && <span className="debt-alert-label">Есть просрочка</span>}
      </div>
      <div className="debt-obligation-grid">
        <div>
          <span>Просрочено</span>
          <strong className={overdueTotal > 0 ? 'negative' : ''}>{formatMoney(overdueTotal)}</strong>
        </div>
        <div>
          <span>Ближайшие 7 дней</span>
          <strong>{formatMoney(nextSevenDaysTotal)}</strong>
        </div>
        <div>
          <span>Ближайшие 30 дней</span>
          <strong>{formatMoney(nextThirtyDaysTotal)}</strong>
        </div>
      </div>
      {visiblePayments.length > 0 ? (
        <div className="upcoming-payment-list">
          {visiblePayments.map((payment) => (
            <div className={`upcoming-payment-row ${payment.due.tone}`} key={payment.key}>
              <div className="upcoming-payment-copy">
                <strong>{payment.title}</strong>
                <span>{payment.subtitle} · {formatDay(payment.date)}</span>
              </div>
              <div className="upcoming-payment-amount">
                <strong>{payment.amount == null ? 'Сумма не указана' : formatMoney(payment.amount)}</strong>
                <span>{payment.due.label}</span>
              </div>
              <TKButton size="sm" variant="tonal" onClick={() => onPay(payment.target)}>Внести</TKButton>
            </div>
          ))}
        </div>
      ) : (
        <p className="debt-priority-empty">На ближайшие 30 дней нет платежей с указанным сроком.</p>
      )}
      {payments.length > visiblePayments.length && (
        <span className="debt-priority-more">Показаны ближайшие 5 обязательств</span>
      )}
    </TKCard>
  )
}
