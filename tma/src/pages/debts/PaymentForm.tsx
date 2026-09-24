import { useState } from 'react'
import { TKButton, TKInput, TKNoticeBar, TKSelect, TKSwitch, TKNativeField } from 'tg-mini-app-uikit'

import { payDebt, payPersonalDebt } from '../../api'
import { formatMoney } from '../../format'
import type { DebtCashEffect, DebtPaymentType } from '../../types'
import type { DebtTarget } from './debtTypes'
import { paymentKey, targetTitle, todayIso } from './debtHelpers'


export function PaymentForm({ target, onSaved }: { target: DebtTarget; onSaved: () => void }) {
  const balance = target.debt.balance
  const [amount, setAmount] = useState(target.kind === 'credit'
    ? target.debt.next_payment_amount ?? target.debt.min_payment ?? balance
    : balance)
  const [date, setDate] = useState(todayIso())
  const [paymentType, setPaymentType] = useState<DebtPaymentType>('regular')
  const [principalAmount, setPrincipalAmount] = useState('')
  const [cashEffect, setCashEffect] = useState<DebtCashEffect>('movement')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [idempotencyKey] = useState(paymentKey)

  const submit = async () => {
    if (!amount || Number(amount) <= 0) {
      setError('Укажи сумму платежа')
      return
    }
    if (target.kind !== 'credit' && Number(amount) > Number(balance)) {
      setError(`Платёж не может быть больше остатка ${formatMoney(balance)}`)
      return
    }
    if (target.kind === 'credit' && principalAmount.trim()) {
      if (Number(principalAmount) > Number(amount)) {
        setError('Часть платежа в тело не может быть больше суммы платежа')
        return
      }
      if (Number(principalAmount) > Number(balance)) {
        setError(`Часть платежа в тело не может быть больше остатка ${formatMoney(balance)}`)
        return
      }
    }
    setSaving(true)
    setError('')
    try {
      if (target.kind === 'credit') {
        await payDebt(
          target.debt.id,
          amount,
          date,
          idempotencyKey,
          paymentType,
          cashEffect,
          principalAmount.trim() || undefined,
        )
      } else {
        await payPersonalDebt(target.debt.id, amount, date, idempotencyKey, cashEffect)
      }
      onSaved()
    } catch (reason) {
      setError((reason as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="debt-form">
      <p className="sheet-hint">{targetTitle(target)} · остаток {target.kind === 'credit' ? 'тела ' : ''}{formatMoney(balance)}.</p>
      <TKInput label="Сумма платежа" inputMode="decimal" value={amount} onChange={(value) => setAmount(value.replace(',', '.'))} />
      <div className="payment-quick-actions">
        <TKButton
          size="sm"
          variant="surface"
          onClick={() => {
            setAmount(balance)
            if (target.kind === 'credit') setPrincipalAmount(balance)
          }}
        >Весь остаток тела</TKButton>
      </div>
      {target.kind === 'credit' && (
        <>
          <TKInput
            label="В тело кредита (если известно)"
            inputMode="decimal"
            value={principalAmount}
            onChange={(value) => setPrincipalAmount(value.replace(',', '.'))}
          />
          <p className="sheet-hint">Сумма платежа может включать проценты. Без разбивки платёж сохранится как расход, но остаток тела не изменится — его можно уточнить по банковскому приложению.</p>
          <TKSelect
            label="Тип платежа"
            options={[
              { value: 'regular', label: 'Обычный платёж' },
              { value: 'early', label: 'Досрочное погашение' },
            ]}
            value={paymentType}
            onChange={(value) => setPaymentType(value as DebtPaymentType)}
          />
          {paymentType === 'early' && (
            <p className="sheet-hint">Досрочный платёж уменьшит остаток и попадёт в историю отдельно. Банковский график автоматически не пересчитывается.</p>
          )}
        </>
      )}
      <TKNativeField type="date" label="Дата платежа" value={date} onChange={setDate} />
      <TKSwitch
        label="Деньги уже учтены в текущем балансе"
        checked={cashEffect === 'already_in_balance'}
        onChange={(checked) => setCashEffect(checked ? 'already_in_balance' : 'movement')}
      />
      {cashEffect === 'already_in_balance' && (
        <p className="sheet-hint">Запишет платёж в историю, но не создаст расход. Тело уменьшится только на указанную часть.</p>
      )}
      {error && <TKNoticeBar tone="red">{error}</TKNoticeBar>}
      <TKButton full variant="filled" loading={saving} onClick={() => void submit()}>Записать платёж</TKButton>
    </div>
  )
}
