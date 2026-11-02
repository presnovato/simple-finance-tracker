import { TKButton, TKCard } from 'tg-mini-app-uikit'

import { formatDay, formatMoney } from '../../format'
import type { PersonalDebt } from '../../types'
import { dueStatus, isStale, personalSubtitle } from './debtHelpers'


export function PersonalDebtCard({
  debt,
  onPay,
  onMore,
  onRestore,
}: {
  debt: PersonalDebt
  onPay: () => void
  onMore: () => void
  onRestore: () => void
}) {
  const due = debt.due_date && debt.status === 'open' && !debt.archived
    ? dueStatus(debt.due_date)
    : null
  return (
    <TKCard className={isStale(debt) ? 'personal-debt-card stale' : 'personal-debt-card'}>
      <div className="personal-debt-head">
        <div>
          <span className="eyebrow">{debt.status === 'closed' ? 'Закрыт' : debt.direction === 'owed_to_me' ? 'Мне должны' : 'Я должен'}</span>
          <h3>{debt.person}</h3>
        </div>
        <strong>{formatMoney(debt.balance)}</strong>
      </div>
      <p className="personal-debt-subtitle">{personalSubtitle(debt)}</p>
      {due && debt.due_date && (
        <div className={`debt-due-status ${due.tone}`}>
          <strong>{due.label}</strong>
          <span>{formatDay(debt.due_date)}</span>
        </div>
      )}
      {!debt.archived && debt.status === 'open' && (
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
