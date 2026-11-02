import { TKIconButton } from 'tg-mini-app-uikit'

import { formatDay, formatMoney } from '../../format'
import type { CashBalance } from '../../types'

export function LiquidityMetricTile({
  balance,
  error,
  onOpen,
}: {
  balance: CashBalance | null
  error: string
  onOpen: () => void
}) {
  const hasAnchor = Boolean(balance?.has_anchor && balance.amount && balance.anchor_date)

  return (
    <div className="metric-tile liquidity-tile">
      <div className="metric-tile-heading">
        <span className="metric-label">Ликвидность</span>
        <span className="metric-action">
          <TKIconButton
            size="sm"
            variant="plain"
            icon="edit"
            label={hasAnchor ? 'Изменить деньги на руках' : 'Задать деньги на руках'}
            onClick={onOpen}
          />
        </span>
      </div>
      <strong className="metric-value">{hasAnchor ? formatMoney(balance!.amount!) : '—'}</strong>
      <span className="metric-note">
        {hasAnchor ? `Якорь на ${formatDay(balance!.anchor_date!)}` : 'Задай исходный остаток'}
      </span>
      {error && <span className="metric-error">{error}</span>}
    </div>
  )
}
