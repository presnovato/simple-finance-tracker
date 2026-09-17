import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from 'react'
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import {
  TKButton,
  TKCard,
  TKEmptyState,
  TKIconButton,
  TKInput,
  TKNativeField,
  TKNoticeBar,
  TKProgress,
  TKSelect,
  TKSegmented,
  TKSheet,
  TKSpinner,
  TKSwitch,
  TKTextarea,
} from 'tg-mini-app-uikit'

import {
  api,
  archiveDebt,
  archivePersonalDebt,
  deleteDebt,
  deletePersonalDebt,
  listDebtHistory,
  listPersonalDebtHistory,
  payDebt,
  payPersonalDebt,
} from '../api'
import { ConfirmSheet } from '../components/ConfirmSheet'
import { formatDay, formatMoney, shiftMonth, todayMonth } from '../format'
import { haptic } from '../telegram'
import type {
  Debt,
  DebtPage,
  DebtSummary,
  DebtHistoryEntry,
  DebtCashEffect,
  DebtPaymentType,
  PersonalDebt,
  PersonalDebtDirection,
  PersonalDebtPage,
} from '../types'

const GREEN = '#77e6b6'
const PURPLE = '#9f8cff'
// TKSheet keeps a closed panel mounted for 380ms to play its exit animation.
// Leave a small buffer before mounting the next panel so two sheets never
// animate over each other when moving from "Ещё" to an action form.
const SHEET_SWITCH_DELAY_MS = 420

type CreditScope = 'active' | 'closed' | 'archived'
type PersonalScope = 'open' | 'closed' | 'archived'
type DebtTarget = { kind: 'credit'; debt: Debt } | { kind: 'personal'; debt: PersonalDebt }
type DebtLoadSection = 'credits' | 'summary' | 'personal'
type DueTone = 'overdue' | 'today' | 'soon'
type DueStatus = { label: string; tone: DueTone }
type DebtChartPoint = { month: string; balance: string; value: number; label: string }
type UpcomingPayment = {
  key: string
  title: string
  subtitle: string
  date: string
  days: number
  amount: number | null
  due: DueStatus
  target: DebtTarget
}

const EMPTY_SECTION_LOADING: Record<DebtLoadSection, boolean> = {
  credits: true,
  summary: true,
  personal: true,
}

export function DebtsPage() {
  const [activeCredits, setActiveCredits] = useState<Debt[]>([])
  const [closedCredits, setClosedCredits] = useState<Debt[]>([])
  const [archivedCredits, setArchivedCredits] = useState<Debt[]>([])
  const [summary, setSummary] = useState<DebtSummary | null>(null)
  const [openPersonal, setOpenPersonal] = useState<PersonalDebt[]>([])
  const [closedPersonal, setClosedPersonal] = useState<PersonalDebt[]>([])
  const [archivedPersonal, setArchivedPersonal] = useState<PersonalDebt[]>([])
  const [direction, setDirection] = useState<PersonalDebtDirection>('owed_to_me')
  const [creditScope, setCreditScope] = useState<CreditScope>('active')
  const [personalScope, setPersonalScope] = useState<PersonalScope>('open')
  const [creating, setCreating] = useState(false)
  const [editingCredit, setEditingCredit] = useState<Debt | null>(null)
  const [creatingPersonal, setCreatingPersonal] = useState(false)
  const [editingPersonal, setEditingPersonal] = useState<PersonalDebt | null>(null)
  const [adjusting, setAdjusting] = useState<Debt | null>(null)
  const [paying, setPaying] = useState<DebtTarget | null>(null)
  const [history, setHistory] = useState<DebtTarget | null>(null)
  const [archiving, setArchiving] = useState<DebtTarget | null>(null)
  const [actions, setActions] = useState<DebtTarget | null>(null)
  const [removing, setRemoving] = useState<DebtTarget | null>(null)
  const [removeError, setRemoveError] = useState('')
  const [removingId, setRemovingId] = useState<number | null>(null)
  const sheetSwitchTimer = useRef<number | null>(null)
  const requestVersion = useRef(0)
  const [loading, setLoading] = useState(true)
  const [sectionLoading, setSectionLoading] = useState(EMPTY_SECTION_LOADING)
  const [sectionErrors, setSectionErrors] = useState<Partial<Record<DebtLoadSection, string>>>({})
  const [actionError, setActionError] = useState('')
  const [lastLoadedAt, setLastLoadedAt] = useState<Date | null>(null)

  const load = useCallback(async () => {
    const version = requestVersion.current + 1
    requestVersion.current = version
    setLoading(true)
    setActionError('')
    setSectionLoading(EMPTY_SECTION_LOADING)
    setSectionErrors({})

    const loadCredits = async () => {
      const results = await Promise.allSettled([
        api<DebtPage>('/api/debts?status=active'),
        api<DebtPage>('/api/debts?status=closed'),
        api<DebtPage>('/api/debts?archived=1'),
      ])
      if (version !== requestVersion.current) return
      const [activePage, closedPage, archivedPage] = results
      if (activePage.status === 'fulfilled') setActiveCredits(activePage.value.items)
      if (closedPage.status === 'fulfilled') setClosedCredits(closedPage.value.items)
      if (archivedPage.status === 'fulfilled') setArchivedCredits(archivedPage.value.items)
      const errors = rejectedMessages(results)
      if (errors.length) setSectionErrors((current) => ({ ...current, credits: errors.join(' · ') }))
      setSectionLoading((current) => ({ ...current, credits: false }))
    }

    const loadSummary = async () => {
      try {
        const debtSummary = await api<DebtSummary>('/api/debts/summary')
        if (version !== requestVersion.current) return
        setSummary(debtSummary)
      } catch (reason) {
        if (version === requestVersion.current) {
          setSectionErrors((current) => ({ ...current, summary: errorMessage(reason) }))
        }
      } finally {
        if (version === requestVersion.current) {
          setSectionLoading((current) => ({ ...current, summary: false }))
        }
      }
    }

    const loadPersonal = async () => {
      const results = await Promise.allSettled([
        api<PersonalDebtPage>('/api/personal-debts?status=open'),
        api<PersonalDebtPage>('/api/personal-debts?status=closed'),
        api<PersonalDebtPage>('/api/personal-debts?archived=1'),
      ])
      if (version !== requestVersion.current) return
      const [openPage, personalClosedPage, personalArchivedPage] = results
      if (openPage.status === 'fulfilled') setOpenPersonal(openPage.value.items)
      if (personalClosedPage.status === 'fulfilled') setClosedPersonal(personalClosedPage.value.items)
      if (personalArchivedPage.status === 'fulfilled') setArchivedPersonal(personalArchivedPage.value.items)
      const errors = rejectedMessages(results)
      if (errors.length) setSectionErrors((current) => ({ ...current, personal: errors.join(' · ') }))
      setSectionLoading((current) => ({ ...current, personal: false }))
    }

    await Promise.allSettled([loadCredits(), loadSummary(), loadPersonal()])
    if (version === requestVersion.current) {
      setLoading(false)
      setLastLoadedAt(new Date())
    }
  }, [])

  useEffect(() => { void load() }, [load])

  useEffect(() => () => {
    if (sheetSwitchTimer.current !== null) window.clearTimeout(sheetSwitchTimer.current)
  }, [])

  const debts = creditScope === 'active'
    ? activeCredits
    : creditScope === 'closed' ? closedCredits : archivedCredits
  const personal = personalScope === 'open'
    ? openPersonal
    : personalScope === 'closed' ? closedPersonal : archivedPersonal
  const shownPersonal = personal.filter((item) => item.direction === direction)
  const personalTotals = useMemo(() => [...openPersonal, ...closedPersonal].reduce((totals, item) => {
    const amount = Number(item.balance)
    if (item.direction === 'owed_to_me') totals.owedToMe += amount
    else totals.iOwe += amount
    return totals
  }, { owedToMe: 0, iOwe: 0 }), [openPersonal, closedPersonal])
  const netBalance = personalTotals.owedToMe - personalTotals.iOwe
  const chartData = useMemo<DebtChartPoint[]>(() => {
    const actualCurve = summary?.curve ?? []
    if (actualCurve.length >= 2) {
      return actualCurve.map((point) => ({
        ...point,
        value: Number(point.balance),
        label: monthLabel(point.month),
      }))
    }

    const currentBalance = Number(summary?.total_balance ?? 0)
    const monthlyPayment = activeCredits.reduce((total, debt) => (
      total + Math.max(0, Number(debt.next_payment_amount ?? debt.min_payment ?? 0))
    ), 0)
    if (!Number.isFinite(currentBalance) || currentBalance <= 0 || monthlyPayment <= 0) return []

    return Array.from({ length: 7 }, (_, index) => {
      const balance = Math.max(0, currentBalance - monthlyPayment * index)
      const month = shiftMonth(todayMonth(), index)
      return {
        month,
        balance: String(balance),
        value: balance,
        label: monthLabel(month),
      }
    })
  }, [activeCredits, summary])
  const chartIsProjection = (summary?.curve.length ?? 0) < 2 && chartData.length > 0
  const upcomingPayments = useMemo(
    () => buildUpcomingPayments(activeCredits, openPersonal),
    [activeCredits, openPersonal],
  )
  const hasOutgoingDebts = activeCredits.length > 0
    || openPersonal.some((item) => item.direction === 'i_owe')
  const hasAnyLoadedData = Boolean(summary)
    || activeCredits.length > 0
    || closedCredits.length > 0
    || archivedCredits.length > 0
    || openPersonal.length > 0
    || closedPersonal.length > 0
    || archivedPersonal.length > 0
  const initialLoading = loading && !hasAnyLoadedData

  const refresh = useCallback(() => {
    haptic('medium')
    void load()
  }, [load])

  const runAction = useCallback(async (action: () => Promise<unknown>) => {
    setActionError('')
    try {
      await action()
      haptic('medium')
      await load()
    } catch (reason) {
      setActionError(errorMessage(reason))
    }
  }, [load])

  const confirmRemove = useCallback(async () => {
    if (!removing) return
    setRemovingId(removing.debt.id)
    setRemoveError('')
    try {
      if (removing.kind === 'credit') await deleteDebt(removing.debt.id)
      else await deletePersonalDebt(removing.debt.id)
      setRemoving(null)
      haptic('medium')
      await load()
    } catch (reason) {
      setRemoveError(errorMessage(reason))
    } finally {
      setRemovingId(null)
    }
  }, [load, removing])

  return (
    <div className="page debts-page">
      <header className="page-heading">
        <div>
          <span className="eyebrow">Контур обязательств</span>
          <h1>Долги</h1>
          {lastLoadedAt && <span className="debt-freshness">Обновлено в {formatTime(lastLoadedAt)}</span>}
        </div>
      </header>

      {actionError && <TKNoticeBar tone="red">Не удалось выполнить действие: {actionError}</TKNoticeBar>}
      {initialLoading ? (
        <div className="debts-loader"><TKSpinner label="Собираю долги" /></div>
      ) : (
        <>
          <section className="debt-section" aria-labelledby="credits-heading">
            <div className="section-heading">
              <div>
                <span className="eyebrow">Банки и рассрочки</span>
                <h2 id="credits-heading">Кредиты</h2>
              </div>
            </div>
            <TKSegmented
              full
              ariaLabel="Фильтр кредитов"
              options={[
                { value: 'active', label: `Активные (${activeCredits.length})` },
                { value: 'closed', label: `Закрытые (${closedCredits.length})` },
                { value: 'archived', label: `Архив (${archivedCredits.length})` },
              ]}
              value={creditScope}
              onChange={(value) => setCreditScope(value as CreditScope)}
            />

            {!sectionLoading.credits && !sectionLoading.personal && hasOutgoingDebts && (
              <UpcomingPayments payments={upcomingPayments} onPay={setPaying} />
            )}
            {sectionErrors.credits && <TKNoticeBar tone="red">Не удалось загрузить часть кредитов: {sectionErrors.credits}</TKNoticeBar>}
            {sectionLoading.credits ? (
              <div className="debt-inline-loading"><TKSpinner label="Загружаю кредиты" /></div>
            ) : (
              <>
                {creditScope === 'active' && sectionLoading.summary && (
                  <div className="debt-inline-loading"><TKSpinner label="Загружаю сводку" /></div>
                )}
                {sectionErrors.summary && <TKNoticeBar tone="red">Не удалось загрузить сводку: {sectionErrors.summary}</TKNoticeBar>}
                {creditScope === 'active' && summary && activeCredits.length > 0 && (
                  <TKCard className="debt-total-card">
                    {creditScope === 'active' && chartData.length > 0 && (
                      <div className="debt-total-chart">
                        <div className="card-heading">
                          <div>
                            <span className="eyebrow">{chartIsProjection ? 'Проекция' : 'Динамика'}</span>
                            <h3>{chartIsProjection ? 'Снижение при текущих платежах' : 'Снижение общего долга'}</h3>
                          </div>
                        </div>
                        <div className="debt-chart" aria-label="График снижения долга">
                          <ResponsiveContainer width="100%" height="100%">
                            <LineChart data={chartData} margin={{ top: 8, right: 4, bottom: 0, left: 0 }}>
                              <CartesianGrid vertical={false} stroke="#242834" strokeDasharray="3 6" />
                              <XAxis dataKey="label" tick={{ fill: '#777e90', fontSize: 10 }} axisLine={false} tickLine={false} />
                              <YAxis tick={{ fill: '#777e90', fontSize: 10 }} tickFormatter={formatChartAxis} axisLine={false} tickLine={false} width={70} />
                              <Tooltip
                                contentStyle={{ background: '#171a22', border: '1px solid #2d3240', borderRadius: 12 }}
                                formatter={(value) => [formatMoney(Number(value)), 'Остаток']}
                              />
                              <Line type="monotone" dataKey="value" stroke={GREEN} strokeWidth={3} dot={{ r: 3 }} activeDot={{ r: 5 }} />
                            </LineChart>
                          </ResponsiveContainer>
                        </div>
                      </div>
                    )}
                    <div className="debt-total-copy">
                      <div>
                        <TKIconButton
                          icon="plus"
                          size={36}
                          variant="filled"
                          label="Новый кредит"
                          title="Новый кредит"
                          onClick={() => setCreating(true)}
                        />
                        <strong>{formatMoney(summary.total_balance)}</strong>
                      </div>
                      <small>Погашено тела {formatMoney(summary.total_paid)} ({formatPercent(summary.progress)}%) из {formatMoney(summary.total_principal)}</small>
                    </div>
                    <TKProgress
                      value={Number(summary.progress)}
                      label={`Погашено ${summary.progress}%`}
                      size="lg"
                      style={{ '--tk-accent-grad': GREEN } as CSSProperties}
                    />
                  </TKCard>
                )}

                <div className="credit-grid">
                  {debts.map((debt) => (
                    <CreditCard
                      key={debt.id}
                      debt={debt}
                      onPay={() => setPaying({ kind: 'credit', debt })}
                      onMore={() => setActions({ kind: 'credit', debt })}
                      onRestore={() => void runAction(() => archiveDebt(debt.id, false))}
                    />
                  ))}
                </div>
                {!debts.length && (
                  <div className="debt-empty">
                    <TKEmptyState
                      title={creditScope === 'archived' ? 'Архив кредитов пуст' : creditScope === 'closed' ? 'Закрытых кредитов нет' : 'Кредитов пока нет'}
                      text={creditScope === 'active' ? 'Добавь банковский кредит или рассрочку — платежи затем можно записывать сообщением боту.' : 'Здесь появятся записи после изменения их статуса.'}
                    />
                    {creditScope === 'active' && <TKButton variant="filled" onClick={() => setCreating(true)}>Добавить кредит</TKButton>}
                  </div>
                )}

              </>
            )}

          </section>

          <section className="debt-section personal-section" aria-labelledby="personal-heading">
            <div className="section-heading">
              <div>
                <span className="eyebrow">Кто кому</span>
                <h2 id="personal-heading">Личные долги</h2>
              </div>
              <div className="section-actions">
                <TKButton size="sm" variant="surface" onClick={() => setCreatingPersonal(true)}>Добавить</TKButton>
              </div>
            </div>
            {sectionErrors.personal && <TKNoticeBar tone="red">Не удалось загрузить часть личных долгов: {sectionErrors.personal}</TKNoticeBar>}
            {!sectionLoading.personal && (
              <div className="personal-debt-totals" aria-label="Итоги личных долгов">
                <div>
                  <span>Мне должны</span>
                  <strong className="positive">{formatMoney(personalTotals.owedToMe)}</strong>
                </div>
                <div>
                  <span>Я должен</span>
                  <strong className="negative">{formatMoney(personalTotals.iOwe)}</strong>
                </div>
                <div className={`personal-debt-net${netBalance < 0 ? ' negative' : netBalance > 0 ? ' positive' : ''}`}>
                  <span>Сальдо</span>
                  <strong>{formatMoney(netBalance)}</strong>
                </div>
              </div>
            )}
            <TKSegmented
              full
              ariaLabel="Фильтр личных долгов"
              options={[
                { value: 'open', label: `Открытые (${openPersonal.length})` },
                { value: 'closed', label: `Закрытые (${closedPersonal.length})` },
                { value: 'archived', label: `Архив (${archivedPersonal.length})` },
              ]}
              value={personalScope}
              onChange={(value) => setPersonalScope(value as PersonalScope)}
            />
            <TKSegmented
              full
              ariaLabel="Направление личного долга"
              options={[
                { value: 'owed_to_me', label: 'Мне должны' },
                { value: 'i_owe', label: 'Я должен' },
              ]}
              value={direction}
              onChange={(value) => setDirection(value as PersonalDebtDirection)}
            />

            {sectionLoading.personal ? (
              <div className="debt-inline-loading"><TKSpinner label="Загружаю личные долги" /></div>
            ) : shownPersonal.length ? (
              <div className="personal-debt-grid">
                {shownPersonal.map((debt) => (
                  <PersonalDebtCard
                    key={debt.id}
                    debt={debt}
                    onPay={() => setPaying({ kind: 'personal', debt })}
                    onMore={() => setActions({ kind: 'personal', debt })}
                    onRestore={() => void runAction(() => archivePersonalDebt(debt.id, false))}
                  />
                ))}
              </div>
            ) : (
              <TKEmptyState
                title={personalScope === 'archived' ? 'Архив личных долгов пуст' : personalScope === 'closed' ? 'Закрытых личных долгов нет' : direction === 'owed_to_me' ? 'Никто не должен' : 'Ты никому не должен'}
                text={personalScope === 'open' ? 'Добавь личный долг кнопкой выше или текстом через бота.' : 'Здесь появятся записи после изменения их статуса.'}
              />
            )}
          </section>
        </>
      )}

      <TKSheet open={creating || Boolean(editingCredit)} onClose={() => { setCreating(false); setEditingCredit(null) }} title={editingCredit ? 'Редактировать кредит' : 'Новый кредит'}>
        <CreditForm debt={editingCredit ?? undefined} onSaved={() => { setCreating(false); setEditingCredit(null); refresh() }} />
      </TKSheet>

      <TKSheet open={Boolean(adjusting)} onClose={() => setAdjusting(null)} title="Корректировка остатка">
        {adjusting && <AdjustForm debt={adjusting} onSaved={() => { setAdjusting(null); refresh() }} />}
      </TKSheet>

      <TKSheet open={creatingPersonal || Boolean(editingPersonal)} onClose={() => { setCreatingPersonal(false); setEditingPersonal(null) }} title={editingPersonal ? 'Редактировать личный долг' : 'Новый личный долг'}>
        <PersonalDebtForm debt={editingPersonal ?? undefined} initialDirection={direction} onSaved={() => { setCreatingPersonal(false); setEditingPersonal(null); refresh() }} />
      </TKSheet>

      <TKSheet open={Boolean(paying)} onClose={() => setPaying(null)} title="Внести платёж">
        {paying && <PaymentForm target={paying} onSaved={() => { setPaying(null); refresh() }} />}
      </TKSheet>

      <TKSheet open={Boolean(history)} onClose={() => setHistory(null)} title="История операций">
        {history && <HistoryContent target={history} />}
      </TKSheet>

      <TKSheet open={Boolean(archiving)} onClose={() => setArchiving(null)} title="Архивировать запись">
        {archiving && <ArchiveForm target={archiving} onSaved={() => { setArchiving(null); refresh() }} />}
      </TKSheet>

      <TKSheet open={Boolean(actions)} onClose={() => setActions(null)} title="Действия">
        {actions && (
          <DebtActions
            target={actions}
            onTransition={(next) => {
              if (sheetSwitchTimer.current !== null) return
              setActions(null)
              sheetSwitchTimer.current = window.setTimeout(() => {
                sheetSwitchTimer.current = null
                next()
              }, SHEET_SWITCH_DELAY_MS)
            }}
            onEdit={() => actions.kind === 'credit'
              ? setEditingCredit(actions.debt)
              : setEditingPersonal(actions.debt)}
            onAdjust={actions.kind === 'credit' ? () => setAdjusting(actions.debt) : undefined}
            onHistory={() => setHistory(actions)}
            onArchive={() => setArchiving(actions)}
            onDelete={() => {
              const target = actions
              if (!target) return
              setActions(null)
              setRemoveError('')
              setRemoving(target)
            }}
          />
        )}
      </TKSheet>

      <ConfirmSheet
        open={removing !== null}
        title="Удалить запись"
        text={removing ? `${targetTitle(removing)} будет удалён без возможности восстановления.` : ''}
        confirmLabel="Удалить запись"
        loading={removingId !== null}
        error={removeError}
        onClose={() => setRemoving(null)}
        onConfirm={() => void confirmRemove()}
      />
    </div>
  )
}

function UpcomingPayments({
  payments,
  onPay,
}: {
  payments: UpcomingPayment[]
  onPay: (target: DebtTarget) => void
}) {
  const overdueTotal = sumPayments(payments, (item) => item.days < 0)
  const nextSevenDaysTotal = sumPayments(payments, (item) => item.days >= 0 && item.days <= 7)
  const nextThirtyDaysTotal = sumPayments(payments, (item) => item.days >= 0 && item.days <= 30)
  const visiblePayments = payments.slice(0, 5)

  return (
    <TKCard className="debt-priority-card">
      <div className="debt-priority-heading">
        <div>
          <span className="eyebrow">На контроле</span>
          <h3>Ближайшие платежи</h3>
        </div>
        {overdueTotal > 0 && <span className="debt-alert-label">Есть просрочка</span>}
      </div>
      <div className="debt-obligation-grid">
        <div>
          <span>Просрочено</span>
          <strong className={overdueTotal > 0 ? 'negative' : ''}>{formatMoney(overdueTotal)}</strong>
        </div>
        <div>
          <span>Ближайшие 7 дней</span>
          <strong>{formatMoney(nextSevenDaysTotal)}</strong>
        </div>
        <div>
          <span>Ближайшие 30 дней</span>
          <strong>{formatMoney(nextThirtyDaysTotal)}</strong>
        </div>
      </div>
      {visiblePayments.length > 0 ? (
        <div className="upcoming-payment-list">
          {visiblePayments.map((payment) => (
            <div className={`upcoming-payment-row ${payment.due.tone}`} key={payment.key}>
              <div className="upcoming-payment-copy">
                <strong>{payment.title}</strong>
                <span>{payment.subtitle} · {formatDay(payment.date)}</span>
              </div>
              <div className="upcoming-payment-amount">
                <strong>{payment.amount == null ? 'Сумма не указана' : formatMoney(payment.amount)}</strong>
                <span>{payment.due.label}</span>
              </div>
              <TKButton size="sm" variant="tonal" onClick={() => onPay(payment.target)}>Внести</TKButton>
            </div>
          ))}
        </div>
      ) : (
        <p className="debt-priority-empty">На ближайшие 30 дней нет платежей с указанным сроком.</p>
      )}
      {payments.length > visiblePayments.length && (
        <span className="debt-priority-more">Показаны ближайшие 5 обязательств</span>
      )}
    </TKCard>
  )
}

function CreditCard({
  debt,
  onPay,
  onMore,
  onRestore,
}: {
  debt: Debt
  onPay: () => void
  onMore: () => void
  onRestore: () => void
}) {
  const paymentAmount = debt.next_payment_amount ?? debt.min_payment
  const paymentDue = debt.next_payment_date && debt.status === 'active'
    ? dueStatus(debt.next_payment_date)
    : null
  return (
    <TKCard className={debt.status === 'closed' ? 'credit-card closed' : 'credit-card'}>
      <div className="credit-card-head">
        <div>
          <span className="eyebrow">{debt.status === 'closed' ? 'Закрыт' : debt.priority == null ? 'Приоритет не задан' : `Приоритет №${debt.priority}`}</span>
          <h3>{debt.loan_name || debt.creditor}</h3>
          {(debt.loan_name || debt.contract_ref) && (
            <span className="credit-card-subtitle">
              {debt.loan_name ? debt.creditor : null}
              {debt.contract_ref ? `${debt.loan_name ? ' · ' : ''}договор ${debt.contract_ref}` : null}
            </span>
          )}
        </div>
        <strong>{formatMoney(debt.balance)}</strong>
      </div>
      <TKProgress
        value={Number(debt.progress)}
        label={`${debt.creditor}: погашено ${debt.progress}%`}
        size="md"
        style={{ '--tk-accent-grad': debt.status === 'closed' ? GREEN : PURPLE } as CSSProperties}
      />
      <div className="credit-progress-caption">
        Погашено тела {formatMoney(repaidPrincipalAmount(debt.principal, debt.balance))} ({formatPercent(debt.progress)}%)
      </div>
      <div className="credit-meta">
        {paymentDue && debt.next_payment_date && (
          <span className={`debt-due-status ${paymentDue.tone}`}>
            <strong>{paymentDue.label}</strong>
            <span>{formatDay(debt.next_payment_date)} · {paymentAmount ? formatMoney(paymentAmount) : 'сумма не указана'}</span>
          </span>
        )}
        {!paymentDue && paymentAmount && <span>Платёж {formatMoney(paymentAmount)}</span>}
        {debt.status === 'closed' && <span>Погашен</span>}
      </div>
      {!debt.archived && debt.status === 'active' && (
        <div className="credit-actions">
          <TKButton size="sm" variant="filled" onClick={onPay}>Внести платёж</TKButton>
          <TKButton size="sm" variant="surface" onClick={onMore}>Ещё</TKButton>
        </div>
      )}
      {!debt.archived && debt.status === 'closed' && (
        <div className="credit-actions">
          <TKButton size="sm" variant="surface" onClick={onMore}>Ещё</TKButton>
        </div>
      )}
      {debt.archived && (
        <div className="credit-actions">
          <TKButton size="sm" variant="surface" onClick={onRestore}>Восстановить</TKButton>
          <TKButton size="sm" variant="surface" onClick={onMore}>Ещё</TKButton>
        </div>
      )}
    </TKCard>
  )
}

function DebtActions({
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

function CreditForm({ debt, onSaved }: { debt?: Debt; onSaved: () => void }) {
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

function PersonalDebtForm({
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

function AdjustForm({ debt, onSaved }: { debt: Debt; onSaved: () => void }) {
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

function PersonalDebtCard({
  debt,
  onPay,
  onMore,
  onRestore,
}: {
  debt: PersonalDebt
  onPay: () => void
  onMore: () => void
  onRestore: () => void
}) {
  const due = debt.due_date && debt.status === 'open' && !debt.archived
    ? dueStatus(debt.due_date)
    : null
  return (
    <TKCard className={isStale(debt) ? 'personal-debt-card stale' : 'personal-debt-card'}>
      <div className="personal-debt-head">
        <div>
          <span className="eyebrow">{debt.status === 'closed' ? 'Закрыт' : debt.direction === 'owed_to_me' ? 'Мне должны' : 'Я должен'}</span>
          <h3>{debt.person}</h3>
        </div>
        <strong>{formatMoney(debt.balance)}</strong>
      </div>
      <p className="personal-debt-subtitle">{personalSubtitle(debt)}</p>
      {due && debt.due_date && (
        <div className={`debt-due-status ${due.tone}`}>
          <strong>{due.label}</strong>
          <span>{formatDay(debt.due_date)}</span>
        </div>
      )}
      {!debt.archived && debt.status === 'open' && (
        <div className="credit-actions">
          <TKButton size="sm" variant="filled" onClick={onPay}>Внести платёж</TKButton>
          <TKButton size="sm" variant="surface" onClick={onMore}>Ещё</TKButton>
        </div>
      )}
      {!debt.archived && debt.status === 'closed' && (
        <div className="credit-actions">
          <TKButton size="sm" variant="surface" onClick={onMore}>Ещё</TKButton>
        </div>
      )}
      {debt.archived && (
        <div className="credit-actions">
          <TKButton size="sm" variant="surface" onClick={onRestore}>Восстановить</TKButton>
          <TKButton size="sm" variant="surface" onClick={onMore}>Ещё</TKButton>
        </div>
      )}
    </TKCard>
  )
}

function PaymentForm({ target, onSaved }: { target: DebtTarget; onSaved: () => void }) {
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

function HistoryContent({ target }: { target: DebtTarget }) {
  const [items, setItems] = useState<DebtHistoryEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    setLoading(true)
    setError('')
    const request = target.kind === 'credit'
      ? listDebtHistory(target.debt.id)
      : listPersonalDebtHistory(target.debt.id)
    void request.then((page) => setItems(page.items))
      .catch((reason) => setError((reason as Error).message))
      .finally(() => setLoading(false))
  }, [target])

  if (loading) return <div className="debts-loader"><TKSpinner label="Загружаю историю" /></div>
  if (error) return <TKNoticeBar tone="red">{error}</TKNoticeBar>
  if (!items.length) return <TKEmptyState title="История пуста" text="Платежей и корректировок ещё нет." />

  return (
    <div className="debt-history">
      <div className="debt-history-summary">
        <span>Исходная сумма</span>
        <strong>{formatMoney(target.debt.principal)}</strong>
        <span>Текущий остаток тела</span>
        <strong>{formatMoney(target.debt.balance)}</strong>
      </div>
      {items.map((item) => (
        <div className="debt-history-row" key={`${item.kind}-${item.id}`}>
          <div>
            <strong>
              {item.kind === 'adjustment'
                ? 'Корректировка остатка'
                : item.payment_type === 'early' ? 'Досрочное погашение' : 'Обычный платёж'}
            </strong>
            <span>
              {formatDay(item.pay_date)}
              {item.kind === 'adjustment'
                ? ` · новый остаток${item.reason ? ` · ${item.reason}` : ''}`
                : [
                    item.principal_amount != null
                      ? `в тело ${formatMoney(item.principal_amount)}`
                      : 'тело не указано',
                    item.interest_amount != null
                      ? `проценты ${formatMoney(item.interest_amount)}`
                      : null,
                    item.cash_effect === 'already_in_balance'
                      ? 'уже учтено в балансе'
                      : null,
                  ].filter(Boolean).join(' · ')}
            </span>
          </div>
          <b>{formatMoney(item.amount)}</b>
        </div>
      ))}
    </div>
  )
}

function ArchiveForm({ target, onSaved }: { target: DebtTarget; onSaved: () => void }) {
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

function targetTitle(target: DebtTarget): string {
  return target.kind === 'credit'
    ? `Кредит «${target.debt.loan_name || target.debt.creditor}»`
    : `Долг ${target.debt.person}`
}

function errorMessage(reason: unknown): string {
  if (reason instanceof Error && reason.message) return reason.message
  if (typeof reason === 'string' && reason) return reason
  return 'Неизвестная ошибка'
}

function rejectedMessages(results: Array<PromiseSettledResult<unknown>>): string[] {
  return [...new Set(
    results
      .filter((result): result is PromiseRejectedResult => result.status === 'rejected')
      .map((result) => errorMessage(result.reason)),
  )]
}

function paymentKey(): string {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) return crypto.randomUUID()
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`
}

function monthLabel(month: string): string {
  return new Intl.DateTimeFormat('ru-RU', { month: 'short' })
    .format(new Date(`${month}-01T12:00:00`))
    .replace('.', '')
}

function formatTime(value: Date): string {
  return new Intl.DateTimeFormat('ru-RU', { hour: '2-digit', minute: '2-digit' }).format(value)
}

function formatPercent(value: string | number): string {
  const amount = Number(value)
  if (!Number.isFinite(amount)) return '0'
  return new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 }).format(amount)
}

function repaidPrincipalAmount(principal: string, balance: string): number {
  const amount = Number(principal) - Number(balance)
  return Number.isFinite(amount) ? Math.max(0, amount) : 0
}

function formatChartAxis(value: number | string): string {
  const amount = Number(value)
  if (!Number.isFinite(amount)) return ''
  const sign = amount < 0 ? '−' : ''
  const absolute = Math.abs(amount)
  const compact = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 })
  if (absolute >= 1_000_000) return `${sign}${compact.format(absolute / 1_000_000)} млн ₽`
  if (absolute >= 1_000) return `${sign}${compact.format(absolute / 1_000)} тыс. ₽`
  return formatMoney(amount)
}

function dueStatus(date: string): DueStatus {
  const days = daysUntil(date)
  if (days < 0) return { label: 'просрочен', tone: 'overdue' }
  if (days === 0) return { label: 'сегодня', tone: 'today' }
  return { label: `через ${days} ${pluralDays(days)}`, tone: 'soon' }
}

function pluralDays(value: number): string {
  const mod100 = value % 100
  const mod10 = value % 10
  if (mod100 >= 11 && mod100 <= 14) return 'дней'
  if (mod10 === 1) return 'день'
  if (mod10 >= 2 && mod10 <= 4) return 'дня'
  return 'дней'
}

function daysUntil(date: string): number {
  return Math.round((isoDateTimestamp(date) - isoDateTimestamp(todayIso())) / 86_400_000)
}

function isoDateTimestamp(value: string): number {
  const [year, month, day] = value.split('-').map(Number)
  return Date.UTC(year, month - 1, day)
}

function buildUpcomingPayments(credits: Debt[], personal: PersonalDebt[]): UpcomingPayment[] {
  const payments: UpcomingPayment[] = []
  for (const debt of credits) {
    if (debt.status !== 'active' || debt.archived || !debt.next_payment_date) continue
    const amountValue = debt.next_payment_amount ?? debt.min_payment
    const days = daysUntil(debt.next_payment_date)
    if (days > 30 && days >= 0) continue
    payments.push({
      key: `credit-${debt.id}`,
      title: debt.loan_name || debt.creditor,
      subtitle: `Кредит · ${debt.creditor}`,
      date: debt.next_payment_date,
      days,
      amount: amountValue && Number(amountValue) > 0 ? Number(amountValue) : null,
      due: dueStatus(debt.next_payment_date),
      target: { kind: 'credit', debt },
    })
  }
  for (const debt of personal) {
    if (debt.status !== 'open' || debt.archived || debt.direction !== 'i_owe' || !debt.due_date) continue
    const days = daysUntil(debt.due_date)
    if (days > 30 && days >= 0) continue
    payments.push({
      key: `personal-${debt.id}`,
      title: debt.person,
      subtitle: 'Я должен',
      date: debt.due_date,
      days,
      amount: Number(debt.balance) > 0 ? Number(debt.balance) : null,
      due: dueStatus(debt.due_date),
      target: { kind: 'personal', debt },
    })
  }
  return payments.sort((left, right) => left.days - right.days || (right.amount ?? 0) - (left.amount ?? 0))
}

function sumPayments(payments: UpcomingPayment[], predicate: (payment: UpcomingPayment) => boolean): number {
  return payments.reduce((total, payment) => (
    predicate(payment) ? total + (payment.amount ?? 0) : total
  ), 0)
}

function personalSubtitle(debt: PersonalDebt): string {
  const pieces = [`открыт ${formatDay(debt.opened_at)}`]
  if (debt.comment) pieces.push(debt.comment)
  if (isStale(debt)) pieces.push('требует внимания')
  return pieces.join(' · ')
}

function todayIso(): string {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
}

function isStale(debt: PersonalDebt): boolean {
  if (debt.archived || debt.status !== 'open') return false
  const ninetyDays = 90 * 24 * 60 * 60 * 1000
  return Boolean(debt.due_date && daysUntil(debt.due_date) < 0)
    || Date.now() - isoDateTimestamp(debt.opened_at) > ninetyDays
}
