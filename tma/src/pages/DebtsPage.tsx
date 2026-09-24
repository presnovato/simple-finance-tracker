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
  TKNoticeBar,
  TKProgress,
  TKSegmented,
  TKSheet,
  TKSpinner,
} from 'tg-mini-app-uikit'

import {
  api,
  archiveDebt,
  archivePersonalDebt,
  deleteDebt,
  deletePersonalDebt,
} from '../api'
import { ConfirmSheet } from '../components/ConfirmSheet'
import { formatMoney, shiftMonth, todayMonth } from '../format'
import { haptic } from '../telegram'
import type {
  Debt,
  DebtPage,
  DebtSummary,
  PersonalDebt,
  PersonalDebtDirection,
  PersonalDebtPage,
} from '../types'
import { AdjustForm } from './debts/AdjustForm'
import { ArchiveForm } from './debts/ArchiveForm'
import { CreditCard } from './debts/CreditCard'
import { CreditForm } from './debts/CreditForm'
import { DebtActions } from './debts/DebtActions'
import { HistoryContent } from './debts/HistoryContent'
import { PaymentForm } from './debts/PaymentForm'
import { PersonalDebtCard } from './debts/PersonalDebtCard'
import { PersonalDebtForm } from './debts/PersonalDebtForm'
import { UpcomingPayments } from './debts/UpcomingPayments'
import {
  EMPTY_SECTION_LOADING,
  GREEN,
  SHEET_SWITCH_DELAY_MS,
  type CreditScope,
  type DebtChartPoint,
  type DebtLoadSection,
  type DebtTarget,
  type PersonalScope,
} from './debts/debtTypes'
import {
  buildUpcomingPayments,
  errorMessage,
  formatChartAxis,
  formatPercent,
  formatTime,
  monthLabel,
  rejectedMessages,
  targetTitle,
} from './debts/debtHelpers'


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
