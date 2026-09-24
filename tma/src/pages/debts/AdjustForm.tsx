import { useState } from 'react'
import { TKButton, TKInput, TKNoticeBar, TKTextarea } from 'tg-mini-app-uikit'

import { api } from '../../api'
import { formatMoney } from '../../format'
import type { Debt } from '../../types'


export function AdjustForm({ debt, onSaved }: { debt: Debt; onSaved: () => void }) {
  const [balance, setBalance] = useState(debt.balance.replace(/\.00$/, ''))
  const [reason, setReason] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const submit = async () => {
    if (!reason.trim()) {
      setError('Укажи причину корректировки')
      return
    }
    setSaving(true)
    setError('')
    try {
      await api<Debt>(`/api/debts/${debt.id}/adjust`, {
        method: 'POST', body: JSON.stringify({ balance, reason }),
      })
      onSaved()
    } catch (reason) {
      setError((reason as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="debt-form">
      <p className="sheet-hint">Текущий остаток тела по «{debt.creditor}»: {formatMoney(debt.balance)}.</p>
      <TKInput label="Новый остаток тела" inputMode="decimal" value={balance} onChange={(value) => setBalance(value.replace(',', '.'))} />
      <TKTextarea label="Причина корректировки" rows={2} value={reason} onChange={setReason} />
      {error && <TKNoticeBar tone="red">{error}</TKNoticeBar>}
      <TKButton full variant="filled" loading={saving} onClick={() => void submit()}>Сохранить остаток</TKButton>
    </div>
  )
}
