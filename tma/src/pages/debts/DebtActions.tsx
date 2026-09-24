import { TKButton } from 'tg-mini-app-uikit'

import type { DebtTarget } from './debtTypes'


export function DebtActions({
  target,
  onTransition,
  onEdit,
  onAdjust,
  onHistory,
  onArchive,
  onDelete,
}: {
  target: DebtTarget
  onTransition: (next: () => void) => void
  onEdit: () => void
  onAdjust?: () => void
  onHistory: () => void
  onArchive: () => void
  onDelete: () => void
}) {
  const active = target.kind === 'credit'
    ? target.debt.status === 'active'
    : target.debt.status === 'open'
  const archived = target.debt.archived
  const historyCount = target.kind === 'credit'
    ? target.debt.history_count
    : target.debt.payment_count
  const hasHistory = historyCount == null || historyCount > 0

  return (
    <div className="debt-action-sheet">
      {!archived && <TKButton full variant="surface" onClick={() => onTransition(onEdit)}>Изменить</TKButton>}
      {active && onAdjust && <TKButton full variant="surface" onClick={() => onTransition(onAdjust)}>Уточнить остаток</TKButton>}
      <TKButton full variant="surface" onClick={() => onTransition(onHistory)}>История</TKButton>
      {!archived && <TKButton full variant="surface" onClick={() => onTransition(onArchive)}>В архив</TKButton>}
      {!hasHistory && (
        <TKButton full variant="destructive" onClick={onDelete}>Удалить запись</TKButton>
      )}
    </div>
  )
}
