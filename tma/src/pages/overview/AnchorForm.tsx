import { useState } from 'react'
import { TKButton, TKInput, TKNoticeBar, TKNativeField } from 'tg-mini-app-uikit'

import { updateCashBalance } from '../../api'
import type { CashBalance } from '../../types'
import { todayIsoDate } from './overviewHelpers'

export function AnchorForm({
  balance,
  onSaved,
}: {
  balance: CashBalance | null
  onSaved: (balance: CashBalance) => void
}) {
  const [amount, setAmount] = useState(balance?.anchor_amount || '')
  const [anchorDate, setAnchorDate] = useState(balance?.anchor_date || todayIsoDate())
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  async function submit() {
    if (!amount.trim()) {
      setError('Укажи сумму')
      return
    }
    setSaving(true)
    setError('')
    try {
      const next = await updateCashBalance(amount.replace(',', '.'), anchorDate)
      onSaved(next)
    } catch (reason) {
      setError((reason as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="debt-form">
      <TKInput
        label="Сумма на руках"
        inputMode="decimal"
        value={amount}
        onChange={(value) => setAmount(value.replace(',', '.'))}
      />
      <TKNativeField type="date" label="Дата пересчёта" value={anchorDate} onChange={setAnchorDate} />
      <p className="sheet-hint">Укажи фактический остаток на эту дату. Операции после неё будут добавляться и вычитаться автоматически.</p>
      {error && <TKNoticeBar tone="red">{error}</TKNoticeBar>}
      <TKButton full variant="filled" loading={saving} onClick={() => void submit()}>Сохранить якорь</TKButton>
    </div>
  )
}
