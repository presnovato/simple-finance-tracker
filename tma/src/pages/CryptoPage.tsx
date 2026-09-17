import { useCallback, useEffect, useState } from 'react'
import {
  TKButton,
  TKCell,
  TKEmptyState,
  TKInput,
  TKListGroup,
  TKNativeField,
  TKNoticeBar,
  TKSelect,
  TKSheet,
  TKSpinner,
} from 'tg-mini-app-uikit'

import { api, updateCryptoOverviewVisibility } from '../api'
import { ConfirmSheet } from '../components/ConfirmSheet'
import { formatCryptoQuantity, isCryptoOverviewVisible, setCryptoOverviewVisible } from '../crypto'
import { formatDay, formatMoney } from '../format'
import { haptic } from '../telegram'
import type { CryptoHolding, CryptoPageData, CryptoTransaction } from '../types'

type CryptoKind = 'buy' | 'sell'

interface Props {
  onOverviewVisibilityChange: (visible: boolean) => void
}

export function CryptoPage({ onOverviewVisibilityChange }: Props) {
  const [data, setData] = useState<CryptoPageData | null>(null)
  const [creating, setCreating] = useState(false)
  const [adjusting, setAdjusting] = useState<CryptoHolding | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [showOnOverview, setShowOnOverview] = useState(() => isCryptoOverviewVisible())
  const [savingOverview, setSavingOverview] = useState(false)
  const [removing, setRemoving] = useState<CryptoTransaction | null>(null)
  const [removeError, setRemoveError] = useState('')
  const [removingId, setRemovingId] = useState<number | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const next = await api<CryptoPageData>('/api/crypto')
      setData(next)
      if (typeof next.overview_visible === 'boolean') {
        setShowOnOverview(next.overview_visible)
        setCryptoOverviewVisible(next.overview_visible)
        onOverviewVisibilityChange(next.overview_visible)
      }
    } catch (reason) {
      setError((reason as Error).message)
    } finally {
      setLoading(false)
    }
  }, [onOverviewVisibilityChange])

  useEffect(() => { void load() }, [load])

  const remove = (transaction: CryptoTransaction) => {
    setRemoving(transaction)
    setRemoveError('')
  }

  const confirmRemove = async () => {
    if (!removing) return
    setRemovingId(removing.id)
    setRemoveError('')
    try {
      await api(`/api/crypto/transactions/${removing.id}`, { method: 'DELETE' })
      setRemoving(null)
      haptic('medium')
      await load()
    } catch (reason) {
      setRemoveError((reason as Error).message)
    } finally {
      setRemovingId(null)
    }
  }

  const toggleOverview = async () => {
    const next = !showOnOverview
    setSavingOverview(true)
    setError('')
    try {
      const result = await updateCryptoOverviewVisibility(next)
      setShowOnOverview(result.overview_visible)
      setCryptoOverviewVisible(result.overview_visible)
      onOverviewVisibilityChange(result.overview_visible)
      haptic()
    } catch (reason) {
      setError((reason as Error).message)
    } finally {
      setSavingOverview(false)
    }
  }

  return (
    <div className="page crypto-page">
      <header className="page-heading crypto-page-heading">
        <div>
          <span className="eyebrow">Другие активы</span>
          <h1>Крипта</h1>
        </div>
        <div className="crypto-page-actions">
          <TKButton size="sm" variant="surface" loading={savingOverview} onClick={() => void toggleOverview()}>
            {showOnOverview ? 'Скрыть с обзора' : 'Показывать на обзоре'}
          </TKButton>
          <TKButton size="sm" variant="filled" onClick={() => setCreating(true)}>
            + Операция
          </TKButton>
        </div>
      </header>

      {error && <TKNoticeBar tone="red">{error}</TKNoticeBar>}
      {loading && !data ? (
        <div className="debts-loader"><TKSpinner label="Собираю криптоактивы" /></div>
      ) : data && (
        <>
          <section className="crypto-section" aria-labelledby="crypto-holdings-heading">
            <div className="section-heading">
              <div>
                <span className="eyebrow">Остатки</span>
                <h2 id="crypto-holdings-heading">Кошельки</h2>
              </div>
              <TKButton size="sm" variant="surface" onClick={() => setAdjusting({ asset: '', quantity: '', updated_at: '' })}>
                Уточнить
              </TKButton>
            </div>
            {data.items.length ? (
              <TKListGroup inset separatorInset={16}>
                {data.items.map((holding) => (
                  <TKCell
                    key={holding.asset}
                    className="crypto-holding-cell"
                    title={holding.asset}
                    subtitle="Нажми, чтобы изменить остаток"
                    after={<strong className="crypto-quantity">{formatCryptoQuantity(holding.quantity)}</strong>}
                    onClick={() => setAdjusting(holding)}
                    wrap
                  />
                ))}
              </TKListGroup>
            ) : (
              <TKEmptyState
                title="Активов пока нет"
                text="Укажи остаток вручную или добавь первую покупку."
              />
            )}
          </section>

          <section className="crypto-section" aria-labelledby="crypto-history-heading">
            <div className="section-heading">
              <div>
                <span className="eyebrow">Движения</span>
                <h2 id="crypto-history-heading">История операций</h2>
              </div>
            </div>
            {data.transactions.length ? (
              <TKListGroup inset separatorInset={16}>
                {data.transactions.map((transaction) => (
                  <TKCell
                    key={transaction.id}
                    className="crypto-history-cell"
                    title={`${transaction.asset} · ${transaction.quantity_delta.startsWith('-') ? 'Продажа' : 'Покупка'}`}
                    subtitle={(
                      <small>
                        {formatDay(transaction.op_date)} · {formatMoney(transaction.rub_amount)}
                        {transaction.comment ? ` · ${transaction.comment}` : ''}
                      </small>
                    )}
                    after={(
                      <div style={{ display: 'grid', justifyItems: 'end', gap: 5 }}>
                        <strong className="crypto-quantity">
                          {transaction.quantity_delta.startsWith('-') ? '−' : '+'}
                          {formatCryptoQuantity(transaction.quantity_delta.replace(/^-/, ''))}
                        </strong>
                        <TKButton size="sm" variant="plain" onClick={() => void remove(transaction)}>
                          Удалить
                        </TKButton>
                      </div>
                    )}
                    wrap
                  />
                ))}
              </TKListGroup>
            ) : (
              <TKEmptyState title="Операций пока нет" text="Покупки и продажи появятся здесь." />
            )}
          </section>
        </>
      )}

      <TKSheet open={creating} onClose={() => setCreating(false)} title="Операция с криптой">
        <CryptoForm
          onSaved={() => {
            setCreating(false)
            haptic('medium')
            void load()
          }}
        />
      </TKSheet>

      <TKSheet open={adjusting !== null} onClose={() => setAdjusting(null)} title="Остаток крипты">
        <HoldingForm
          holding={adjusting}
          onSaved={() => {
            setAdjusting(null)
            haptic('medium')
            void load()
          }}
        />
      </TKSheet>

      <ConfirmSheet
        open={removing !== null}
        title="Удалить криптооперацию"
        text={removing ? `Операция ${removing.asset} будет удалена из истории и остатка.` : ''}
        confirmLabel="Удалить операцию"
        loading={removingId !== null}
        error={removeError}
        onClose={() => setRemoving(null)}
        onConfirm={() => void confirmRemove()}
      />
    </div>
  )
}

function CryptoForm({ onSaved }: { onSaved: () => void }) {
  const [form, setForm] = useState({
    asset: '',
    kind: 'buy' as CryptoKind,
    quantity: '',
    rub_amount: '',
    op_date: todayIso(),
    comment: '',
  })
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const submit = async () => {
    setSaving(true)
    setError('')
    try {
      const quantity = form.kind === 'buy' ? form.quantity : `-${form.quantity}`
      await api<CryptoTransaction>('/api/crypto/transactions', {
        method: 'POST',
        body: JSON.stringify({
          asset: form.asset,
          quantity_delta: quantity,
          rub_amount: form.rub_amount,
          op_date: form.op_date,
          comment: form.comment || null,
        }),
      })
      onSaved()
    } catch (reason) {
      setError((reason as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="crypto-form">
      <TKInput label="Актив" placeholder="BTC или USDT" value={form.asset} onChange={(value) => setForm({ ...form, asset: value.toUpperCase() })} />
      <TKSelect
        label="Тип операции"
        options={[{ value: 'buy', label: 'Покупка' }, { value: 'sell', label: 'Продажа' }]}
        value={form.kind}
        onChange={(value) => setForm({ ...form, kind: value as CryptoKind })}
      />
      <TKInput label="Количество" inputMode="decimal" value={form.quantity} onChange={(value) => setForm({ ...form, quantity: value.replace(',', '.') })} />
      <TKInput label="Сумма в ₽" inputMode="decimal" value={form.rub_amount} onChange={(value) => setForm({ ...form, rub_amount: value.replace(',', '.') })} />
      <TKNativeField type="date" label="Дата" value={form.op_date} onChange={(value) => setForm({ ...form, op_date: value })} />
      <TKInput label="Комментарий" value={form.comment} onChange={(value) => setForm({ ...form, comment: value })} />
      {error && <TKNoticeBar tone="red">{error}</TKNoticeBar>}
      <TKButton full variant="filled" loading={saving} onClick={() => void submit()}>Записать операцию</TKButton>
    </div>
  )
}

function HoldingForm({ holding, onSaved }: { holding: CryptoHolding | null; onSaved: () => void }) {
  const [asset, setAsset] = useState(holding?.asset || '')
  const [quantity, setQuantity] = useState(holding?.quantity || '')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const submit = async () => {
    setSaving(true)
    setError('')
    try {
      await api<CryptoHolding>(`/api/crypto/holdings/${encodeURIComponent(asset)}`, {
        method: 'PATCH', body: JSON.stringify({ quantity }),
      })
      onSaved()
    } catch (reason) {
      setError((reason as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="crypto-form">
      <TKInput label="Актив" placeholder="BTC или USDT" value={asset} disabled={Boolean(holding?.asset)} onChange={(value) => setAsset(value.toUpperCase())} />
      <TKInput label="Текущий остаток" inputMode="decimal" value={quantity} onChange={(value) => setQuantity(value.replace(',', '.'))} />
      <p className="sheet-hint">Это ручная сверка кошелька, без записи покупки или продажи.</p>
      {error && <TKNoticeBar tone="red">{error}</TKNoticeBar>}
      <TKButton full variant="filled" loading={saving} onClick={() => void submit()}>Сохранить остаток</TKButton>
    </div>
  )
}

function todayIso(): string {
  return new Date().toISOString().slice(0, 10)
}
