import { useState } from 'react'
import { TKButton, TKInput, TKNativeField, TKNoticeBar } from 'tg-mini-app-uikit'

import { api } from '../../api'
import type { Debt } from '../../types'


export function CreditForm({ debt, onSaved }: { debt?: Debt; onSaved: () => void }) {
  const [form, setForm] = useState({
    creditor: debt?.creditor ?? '',
    loan_name: debt?.loan_name ?? '',
    contract_ref: debt?.contract_ref ?? '',
    principal: debt?.principal ?? '',
    rate: debt?.rate ?? '',
    next_payment_amount: debt?.next_payment_amount ?? debt?.min_payment ?? '',
    opened_at: debt?.opened_at ?? '',
    next_payment_date: debt?.next_payment_date ?? '',
    priority: debt?.priority == null ? '' : String(debt.priority),
    maturity_date: debt?.maturity_date ?? debt?.due_date ?? '',
  })
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const readyToCreate = Boolean(
    form.creditor.trim()
      && form.principal.trim()
      && Number(form.principal) > 0
      && form.opened_at,
  )

  const submit = async () => {
    if (!debt && !form.opened_at) {
      setError('Укажи дату начала кредита')
      return
    }
    setSaving(true)
    setError('')
    try {
      const payload = Object.fromEntries(
        Object.entries(form).filter(([, value]) => value !== ''),
      )
      if (payload.next_payment_amount) {
        payload.min_payment = payload.next_payment_amount
      }
      await api<Debt>(debt ? `/api/debts/${debt.id}` : '/api/debts', {
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
      <TKInput label="Банк или кредитор *" value={form.creditor} onChange={(value) => setForm({ ...form, creditor: value })} />
      <div className="debt-form-grid">
        <TKInput label="Название кредита" value={form.loan_name} onChange={(value) => setForm({ ...form, loan_name: value })} />
        <TKInput label="Договор / последние 4 цифры" value={form.contract_ref} onChange={(value) => setForm({ ...form, contract_ref: value })} />
      </div>
      <TKInput label="Начальная сумма тела *" inputMode="decimal" value={form.principal} onChange={(value) => setForm({ ...form, principal: value.replace(',', '.') })} />
      <div className="debt-form-grid">
        <TKInput label="Ставка, % (справочно)" inputMode="decimal" value={form.rate} onChange={(value) => setForm({ ...form, rate: value.replace(',', '.') })} />
        <TKInput label="Ежемесячный платёж" inputMode="decimal" value={form.next_payment_amount} onChange={(value) => setForm({ ...form, next_payment_amount: value.replace(',', '.') })} />
      </div>
      <div className="debt-form-grid">
        <TKNativeField type="date" label="Дата начала *" value={form.opened_at} onChange={(value) => setForm({ ...form, opened_at: value })} />
        <TKNativeField type="date" label="Следующий платёж" value={form.next_payment_date} onChange={(value) => setForm({ ...form, next_payment_date: value })} />
      </div>
      <div className="debt-form-grid">
        <TKInput label="Приоритет (1 — выше)" inputMode="numeric" value={form.priority} onChange={(value) => setForm({ ...form, priority: value.replace(/\D/g, '') })} />
        <TKNativeField type="date" label="Дата полного погашения" value={form.maturity_date} onChange={(value) => setForm({ ...form, maturity_date: value })} />
      </div>
      <p className="sheet-hint">* Обязательные поля. Остаток и прогресс считаются по телу кредита. Ставка хранится справочно и не начисляет проценты автоматически.</p>
      {error && <TKNoticeBar tone="red">{error}</TKNoticeBar>}
      <TKButton full variant="filled" loading={saving} disabled={!debt && !readyToCreate} onClick={() => void submit()}>{debt ? 'Сохранить изменения' : 'Создать кредит'}</TKButton>
    </div>
  )
}
