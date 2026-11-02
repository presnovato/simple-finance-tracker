import { useState } from 'react'
import { TKButton, TKNoticeBar } from 'tg-mini-app-uikit'

import { archiveDebt, archivePersonalDebt } from '../../api'
import type { DebtTarget } from './debtTypes'


export function ArchiveForm({ target, onSaved }: { target: DebtTarget; onSaved: () => void }) {
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const submit = async () => {
    setSaving(true)
    setError('')
    try {
      if (target.kind === 'credit') await archiveDebt(target.debt.id, true)
      else await archivePersonalDebt(target.debt.id, true)
      onSaved()
    } catch (reason) {
      setError((reason as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="debt-form">
      <p className="sheet-hint">Запись будет скрыта из активного списка. История и восстановление останутся доступны в архиве.</p>
      {error && <TKNoticeBar tone="red">{error}</TKNoticeBar>}
      <TKButton full variant="filled" loading={saving} onClick={() => void submit()}>Переместить в архив</TKButton>
    </div>
  )
}
