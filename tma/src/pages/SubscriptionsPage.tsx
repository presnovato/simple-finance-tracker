import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  TKButton,
  TKCard,
  TKCell,
  TKEmptyState,
  TKInput,
  TKListGroup,
  TKNativeField,
  TKNoticeBar,
  TKSegmented,
  TKSheet,
  TKSpinner,
  TKTextarea,
} from 'tg-mini-app-uikit'

import {
  cancelSubscription,
  chargeSubscription,
  createSubscription,
  listSubscriptions,
  patchSubscription,
} from '../api'
import { ConfirmSheet } from '../components/ConfirmSheet'
import { formatDay, formatMoney } from '../format'
import { haptic } from '../telegram'
import type {
  Subscription,
  SubscriptionPeriod,
  SubscriptionsResponse,
  UpcomingCharge,
} from '../types'

export function SubscriptionsPage() {
  const [data, setData] = useState<SubscriptionsResponse | null>(null)
  const [archive, setArchive] = useState<Subscription[]>([])
  const [archiveOpen, setArchiveOpen] = useState(false)
  const [archiveLoaded, setArchiveLoaded] = useState(false)
  const [editing, setEditing] = useState<Subscription | null>(null)
  const [sheetOpen, setSheetOpen] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [busyId, setBusyId] = useState<number | null>(null)
  const [removing, setRemoving] = useState<Subscription | null>(null)
  const [removeError, setRemoveError] = useState('')
  const [removingId, setRemovingId] = useState<number | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      setData(await listSubscriptions())
    } catch (reason) {
      setError((reason as Error).message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void load() }, [load])

  const active = useMemo(
    () => [...(data?.items ?? [])].sort((a, b) => a.next_charge.localeCompare(b.next_charge)),
    [data],
  )
  const groupedUpcoming = useMemo(() => groupUpcoming(data?.upcoming ?? []), [data])
  const upcomingTotal = useMemo(
    () => (data?.upcoming ?? []).reduce((total, item) => total + Number(item.amount), 0),
    [data],
  )
  const due = active.filter((item) => item.due)

  const loadArchive = async () => {
    setError('')
    try {
      const response = await listSubscriptions('cancelled')
      setArchive(response.items)
      setArchiveLoaded(true)
    } catch (reason) {
      setError((reason as Error).message)
    }
  }

  const charge = async (subscription: Subscription, confirmed: boolean) => {
    setBusyId(subscription.id)
    setError('')
    setData((current) => current ? {
      ...current,
      items: current.items.map((item) => item.id === subscription.id
        ? { ...item, due: false }
        : item),
    } : current)
    try {
      const response = await chargeSubscription(subscription.id, confirmed, subscription.next_charge)
      setData((current) => current ? {
        ...current,
        items: current.items.map((item) => item.id === subscription.id
          ? response.subscription
          : item),
      } : current)
      haptic('medium')
      void load()
    } catch (reason) {
      setData((current) => current ? {
        ...current,
        items: current.items.map((item) => item.id === subscription.id
          ? { ...item, due: true }
          : item),
      } : current)
      setError((reason as Error).message)
    } finally {
      setBusyId(null)
    }
  }

  const save = () => {
    setSheetOpen(false)
    setEditing(null)
    haptic('medium')
    void load()
  }

  const restore = async (subscription: Subscription) => {
    setError('')
    try {
      await patchSubscription(subscription.id, { status: 'active' })
      await loadArchive()
      void load()
      haptic('light')
    } catch (reason) {
      setError((reason as Error).message)
    }
  }

  const remove = (subscription: Subscription) => {
    setRemoving(subscription)
    setRemoveError('')
  }

  const confirmRemove = async () => {
    if (!removing) return
    setRemovingId(removing.id)
    setRemoveError('')
    try {
      await cancelSubscription(removing.id)
      setRemoving(null)
      setSheetOpen(false)
      setEditing(null)
      await load()
      haptic('light')
    } catch (reason) {
      setRemoveError((reason as Error).message)
    } finally {
      setRemovingId(null)
    }
  }

  if (loading && !data) {
    return <div className="page-state"><TKSpinner label="Загружаю подписки" /></div>
  }

  return (
    <div className="page subscriptions-page">
      <header className="page-heading">
        <div>
          <span className="eyebrow">Регулярные расходы</span>
          <h1>Подписки</h1>
        </div>
        <TKButton size="sm" variant="filled" onClick={() => { setEditing(null); setSheetOpen(true) }}>
          + Подписка
        </TKButton>
      </header>

      {error && <TKNoticeBar tone="red">{error}</TKNoticeBar>}

      {data && (
        <>
          <section className="subscription-summary" aria-label="Стоимость подписок">
            <TKCard className="subscription-metric">
              <span>В месяц</span>
              <strong>{formatMoney(data.monthly_cost)}</strong>
            </TKCard>
            <TKCard className="subscription-metric">
              <span>В год</span>
              <strong>{formatMoney(data.yearly_cost ?? '0')}</strong>
            </TKCard>
            {data.share_percent !== null && (
              <p className="subscription-share">
                {data.share_percent.replace('.', ',')} % расходов этого месяца
              </p>
            )}
          </section>

          {due.length > 0 && (
            <section className="subscription-section" aria-labelledby="due-heading">
              <div className="section-heading">
                <div>
                  <span className="eyebrow">Нужно ответить</span>
                  <h2 id="due-heading">Ждут подтверждения</h2>
                </div>
                <span>{due.length}</span>
              </div>
              <div className="subscription-due-list">
                {due.map((subscription) => (
                  <TKCard key={subscription.id} className="subscription-due-card">
                    <div>
                      <strong>{subscription.title}</strong>
                      <span>{formatMoney(subscription.amount)} · {formatDay(subscription.next_charge)}</span>
                    </div>
                    <div className="subscription-actions">
                      <TKButton
                        size="sm"
                        variant="filled"
                        loading={busyId === subscription.id}
                        onClick={() => void charge(subscription, true)}
                      >
                        Списалось
                      </TKButton>
                      <TKButton
                        size="sm"
                        variant="surface"
                        disabled={busyId === subscription.id}
                        onClick={() => void charge(subscription, false)}
                      >
                        Пропустить
                      </TKButton>
                    </div>
                  </TKCard>
                ))}
              </div>
            </section>
          )}

          <section className="subscription-section" aria-labelledby="active-heading">
            <div className="section-heading">
              <div>
                <span className="eyebrow">Текущие сервисы</span>
                <h2 id="active-heading">Активные</h2>
              </div>
              <span>{active.length}</span>
            </div>
            {active.length ? (
              <TKListGroup inset separatorInset={16}>
                {active.map((subscription) => (
                  <TKCell
                    key={subscription.id}
                    className={subscription.due ? 'subscription-cell due' : 'subscription-cell'}
                    chevron
                    title={subscription.title}
                    subtitle={subscriptionSubtitle(subscription)}
                    value={<b>{formatMoney(subscription.amount)}{subscription.period === 'yearly' ? '/год' : '/мес'}</b>}
                    onClick={() => { setEditing(subscription); setSheetOpen(true) }}
                    wrap
                  />
                ))}
              </TKListGroup>
            ) : (
              <TKEmptyState title="Подписок пока нет" text="Добавь сервис, сумму и дату ближайшего списания." />
            )}
          </section>

          <section className="subscription-section" aria-labelledby="upcoming-heading">
            <div className="section-heading">
              <div>
                <span className="eyebrow">Следующие 30 дней</span>
                <h2 id="upcoming-heading">Календарь списаний</h2>
              </div>
              <span>итого {formatMoney(String(upcomingTotal))}</span>
            </div>
            {groupedUpcoming.length ? (
              <TKListGroup inset separatorInset={16}>
                {groupedUpcoming.map(([chargeDate, charges]) => (
                  <TKCell
                    key={chargeDate}
                    title={formatDay(chargeDate)}
                    subtitle={charges.map((charge) => charge.title).join(' · ')}
                    value={<b>{formatMoney(String(charges.reduce((sum, item) => sum + Number(item.amount), 0)))}</b>}
                    wrap
                  />
                ))}
              </TKListGroup>
            ) : (
              <TKEmptyState title="Ближайших списаний нет" text="Здесь появятся даты активных подписок на 30 дней вперёд." />
            )}
          </section>

          <details
            className="subscription-archive"
            open={archiveOpen}
            onToggle={(event) => {
              const open = (event.currentTarget as HTMLDetailsElement).open
              setArchiveOpen(open)
              if (open && !archiveLoaded) void loadArchive()
            }}
          >
            <summary>Архив отменённых ({archive.length})</summary>
            {archiveLoaded && (archive.length ? (
              <TKListGroup inset separatorInset={16}>
                {archive.map((subscription) => (
                  <TKCell
                    key={subscription.id}
                    title={subscription.title}
                    subtitle={`${formatMoney(subscription.amount)}${subscription.period === 'yearly' ? '/год' : '/мес'} · отменена`}
                    after={<TKButton size="sm" variant="surface" onClick={() => void restore(subscription)}>Вернуть</TKButton>}
                    wrap
                  />
                ))}
              </TKListGroup>
            ) : <TKEmptyState title="Архив пуст" text="Отменённые подписки появятся здесь." />)}
          </details>
        </>
      )}

      <TKSheet
        open={sheetOpen}
        onClose={() => { setSheetOpen(false); setEditing(null) }}
        title={editing ? 'Править подписку' : 'Новая подписка'}
      >
        <SubscriptionForm
          key={editing?.id ?? 'new'}
          subscription={editing}
          onSaved={save}
          onCancel={editing ? () => void remove(editing) : undefined}
        />
      </TKSheet>

      <ConfirmSheet
        open={removing !== null}
        title="Отменить подписку"
        text={removing ? `«${removing.title}» будет перенесена в архив отменённых.` : ''}
        confirmLabel="Отменить подписку"
        loading={removingId !== null}
        error={removeError}
        onClose={() => setRemoving(null)}
        onConfirm={() => void confirmRemove()}
      />
    </div>
  )
}

function SubscriptionForm({
  subscription,
  onSaved,
  onCancel,
}: {
  subscription: Subscription | null
  onSaved: () => void
  onCancel?: () => void
}) {
  const [form, setForm] = useState(() => ({
    title: subscription?.title ?? '',
    amount: subscription?.amount ?? '',
    period: subscription?.period ?? 'monthly' as SubscriptionPeriod,
    next_charge: subscription?.next_charge ?? todayIso(),
    category: subscription?.category ?? 'Подписки',
    comment: subscription?.comment ?? '',
  }))
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const submit = async () => {
    setSaving(true)
    setError('')
    try {
      const payload = Object.fromEntries(
        Object.entries(form).filter(([, value]) => value !== ''),
      )
      if (subscription) await patchSubscription(subscription.id, payload)
      else await createSubscription(payload)
      onSaved()
    } catch (reason) {
      setError((reason as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="subscription-form">
      <TKInput label="Название сервиса" value={form.title} onChange={(value) => setForm({ ...form, title: value })} />
      <div className="subscription-form-grid">
        <TKInput label="Сумма" inputMode="decimal" value={form.amount} onChange={(value) => setForm({ ...form, amount: value.replace(',', '.') })} />
        <TKSegmented
          full
          ariaLabel="Период подписки"
          options={[{ value: 'monthly', label: 'В месяц' }, { value: 'yearly', label: 'В год' }]}
          value={form.period}
          onChange={(value) => setForm({ ...form, period: value as SubscriptionPeriod })}
        />
      </div>
      <TKNativeField type="date" label="Следующее списание" value={form.next_charge} onChange={(value) => setForm({ ...form, next_charge: value })} />
      <TKInput label="Категория" value={form.category} onChange={(value) => setForm({ ...form, category: value })} />
      <TKTextarea label="Комментарий" rows={2} value={form.comment} onChange={(value) => setForm({ ...form, comment: value })} />
      {error && <TKNoticeBar tone="red">{error}</TKNoticeBar>}
      <TKButton full variant="filled" loading={saving} onClick={() => void submit()}>
        {subscription ? 'Сохранить' : 'Добавить подписку'}
      </TKButton>
      {onCancel && <TKButton full variant="destructive" onClick={onCancel}>Отменить подписку</TKButton>}
    </div>
  )
}

function subscriptionSubtitle(subscription: Subscription): string {
  const parts = [
    subscription.period === 'yearly' ? 'годовая' : 'ежемесячная',
    `следующее ${formatDay(subscription.next_charge)}`,
    daysUntil(subscription.next_charge),
  ]
  if (subscription.due) parts.push('ждёт подтверждения')
  if (subscription.comment) parts.push(subscription.comment)
  return parts.join(' · ')
}

function groupUpcoming(charges: UpcomingCharge[]): Array<[string, UpcomingCharge[]]> {
  const grouped = new Map<string, UpcomingCharge[]>()
  for (const charge of charges) {
    const list = grouped.get(charge.charge_date) ?? []
    list.push(charge)
    grouped.set(charge.charge_date, list)
  }
  return [...grouped.entries()].sort(([a], [b]) => a.localeCompare(b))
}

function daysUntil(value: string): string {
  const today = new Date(`${todayIso()}T12:00:00`)
  const target = new Date(`${value}T12:00:00`)
  const days = Math.round((target.getTime() - today.getTime()) / 86_400_000)
  if (days < 0) return `просрочено на ${Math.abs(days)} дн.`
  if (days === 0) return 'сегодня'
  return `через ${days} дн.`
}

function todayIso(): string {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
}
