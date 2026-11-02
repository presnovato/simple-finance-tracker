import type { CSSProperties } from 'react'
import { TKButton, TKCard, TKProgress } from 'tg-mini-app-uikit'

import { formatDay, formatMoney } from '../../format'
import type { Debt } from '../../types'
import { GREEN, PURPLE } from './debtTypes'
import { dueStatus, formatPercent, repaidPrincipalAmount } from './debtHelpers'


export function CreditCard({
  debt,
  onPay,
  onMore,
  onRestore,
}: {
  debt: Debt
  onPay: () => void
  onMore: () => void
  onRestore: () => void
}) {
  const paymentAmount = debt.next_payment_amount ?? debt.min_payment
  const paymentDue = debt.next_payment_date && debt.status === 'active'
    ? dueStatus(debt.next_payment_date)
    : null
  return (
    <TKCard className={debt.status === 'closed' ? 'credit-card closed' : 'credit-card'}>
      <div className="credit-card-head">
        <div>
          <span className="eyebrow">{debt.status === 'closed' ? 'Закрыт' : debt.priority == null ? 'Приоритет не задан' : `Приоритет №${debt.priority}`}</span>
          <h3>{debt.loan_name || debt.creditor}</h3>
          {(debt.loan_name || debt.contract_ref) && (
            <span className="credit-card-subtitle">
              {debt.loan_name ? debt.creditor : null}
              {debt.contract_ref ? `${debt.loan_name ? ' · ' : ''}договор ${debt.contract_ref}` : null}
            </span>
          )}
        </div>
        <strong>{formatMoney(debt.balance)}</strong>
      </div>
      <TKProgress
        value={Number(debt.progress)}
        label={`${debt.creditor}: погашено ${debt.progress}%`}
        size="md"
        style={{ '--tk-accent-grad': debt.status === 'closed' ? GREEN : PURPLE } as CSSProperties}
      />
      <div className="credit-progress-caption">
        Погашено тела {formatMoney(repaidPrincipalAmount(debt.principal, debt.balance))} ({formatPercent(debt.progress)}%)
      </div>
      <div className="credit-meta">
        {paymentDue && debt.next_payment_date && (
          <span className={`debt-due-status ${paymentDue.tone}`}>
            <strong>{paymentDue.label}</strong>
            <span>{formatDay(debt.next_payment_date)} · {paymentAmount ? formatMoney(paymentAmount) : 'сумма не указана'}</span>
          </span>
        )}
        {!paymentDue && paymentAmount && <span>Платёж {formatMoney(paymentAmount)}</span>}
        {debt.status === 'closed' && <span>Погашен</span>}
      </div>
      {!debt.archived && debt.status === 'active' && (
        <div className="credit-actions">
          <TKButton size="sm" variant="filled" onClick={onPay}>Внести платёж</TKButton>
          <TKButton size="sm" variant="surface" onClick={onMore}>Ещё</TKButton>
        </div>
      )}
      {!debt.archived && debt.status === 'closed' && (
        <div className="credit-actions">
          <TKButton size="sm" variant="surface" onClick={onMore}>Ещё</TKButton>
        </div>
      )}
      {debt.archived && (
        <div className="credit-actions">
          <TKButton size="sm" variant="surface" onClick={onRestore}>Восстановить</TKButton>
          <TKButton size="sm" variant="surface" onClick={onMore}>Ещё</TKButton>
        </div>
      )}
    </TKCard>
  )
}
