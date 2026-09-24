import { useState } from 'react'
import { TKButton, TKInput, TKNoticeBar, TKSelect, TKTextarea, TKNativeField } from 'tg-mini-app-uikit'

import { api } from '../../api'
import type { PersonalDebt, PersonalDebtDirection } from '../../types'
import { todayIso } from './debtHelpers'


export function PersonalDebtForm({
  debt,
  initialDirection,
  onSaved,
}: {
  debt?: PersonalDebt
  initialDirection: PersonalDebtDirection
  onSaved: () => void
}) {
  const [form, setForm] = useState({
    person: debt?.person ?? '',
    direction: debt?.direction ?? initialDirection,
    principal: debt?.principal ?? '',
    opened_at: debt?.opened_at ?? todayIso(),
    due_date: debt?.due_date ?? '',
    comment: debt?.comment ?? '',
  })
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const submit = async () => {
    setSaving(true)
    setError('')
    try {
      const payload = Object.fromEntries(
        Object.entries(form).filter(([, value]) => value !== ''),
      )
      await api<PersonalDebt>(debt ? `/api/personal-debts/${debt.id}` : '/api/personal-debts', {
        method: debt ? 'PATCH' : 'POST', body: JSON.stringify(payload),
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
      <TKInput label="Человек" value={form.person} onChange={(value) => setForm({ ...form, person: value })} />
      <TKSelect
        label="Направление"
        options={[{ value: 'owed_to_me', label: 'Мне должны' }, { value: 'i_owe', label: 'Я должен' }]}
        value={form.direction}
        onChange={(value) => setForm({ ...form, direction: value as PersonalDebtDirection })}
      />
      <TKInput label="Сумма" inputMode="decimal" value={form.principal} onChange={(value) => setForm({ ...form, principal: value.replace(',', '.') })} />
      <div className="debt-form-grid">
        <TKNativeField type="date" label="Дата" value={form.opened_at} onChange={(value) => setForm({ ...form, opened_at: value })} />
        <TKNativeField type="date" label="Срок (необязательно)" value={form.due_date} onChange={(value) => setForm({ ...form, due_date: value })} />
      </div>
      <TKTextarea label="Комментарий" rows={2} value={form.comment} onChange={(value) => setForm({ ...form, comment: value })} />
      {error && <TKNoticeBar tone="red">{error}</TKNoticeBar>}
      <TKButton full variant="filled" loading={saving} onClick={() => void submit()}>{debt ? 'Сохранить изменения' : 'Добавить долг'}</TKButton>
    </div>
  )
}
