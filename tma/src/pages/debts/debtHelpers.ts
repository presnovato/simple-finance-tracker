import { formatDay, formatMoney } from '../../format'
import type { Debt, PersonalDebt } from '../../types'
import type { DebtChartPoint, DebtTarget, DueStatus, UpcomingPayment } from './debtTypes'


export function targetTitle(target: DebtTarget): string {
  return target.kind === 'credit'
    ? `Кредит «${target.debt.loan_name || target.debt.creditor}»`
    : `Долг ${target.debt.person}`
}

export function errorMessage(reason: unknown): string {
  if (reason instanceof Error && reason.message) return reason.message
  if (typeof reason === 'string' && reason) return reason
  return 'Неизвестная ошибка'
}

export function rejectedMessages(results: Array<PromiseSettledResult<unknown>>): string[] {
  return [...new Set(
    results
      .filter((result): result is PromiseRejectedResult => result.status === 'rejected')
      .map((result) => errorMessage(result.reason)),
  )]
}

export function paymentKey(): string {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) return crypto.randomUUID()
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`
}

export function monthLabel(month: string): string {
  return new Intl.DateTimeFormat('ru-RU', { month: 'short' })
    .format(new Date(`${month}-01T12:00:00`))
    .replace('.', '')
}

export function formatTime(value: Date): string {
  return new Intl.DateTimeFormat('ru-RU', { hour: '2-digit', minute: '2-digit' }).format(value)
}

export function formatPercent(value: string | number): string {
  const amount = Number(value)
  if (!Number.isFinite(amount)) return '0'
  return new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 }).format(amount)
}

export function repaidPrincipalAmount(principal: string, balance: string): number {
  const amount = Number(principal) - Number(balance)
  return Number.isFinite(amount) ? Math.max(0, amount) : 0
}

export function formatChartAxis(value: number | string): string {
  const amount = Number(value)
  if (!Number.isFinite(amount)) return ''
  const sign = amount < 0 ? '−' : ''
  const absolute = Math.abs(amount)
  const compact = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 })
  if (absolute >= 1_000_000) return `${sign}${compact.format(absolute / 1_000_000)} млн ₽`
  if (absolute >= 1_000) return `${sign}${compact.format(absolute / 1_000)} тыс. ₽`
  return formatMoney(amount)
}

export function dueStatus(date: string): DueStatus {
  const days = daysUntil(date)
  if (days < 0) return { label: 'просрочен', tone: 'overdue' }
  if (days === 0) return { label: 'сегодня', tone: 'today' }
  return { label: `через ${days} ${pluralDays(days)}`, tone: 'soon' }
}

export function pluralDays(value: number): string {
  const mod100 = value % 100
  const mod10 = value % 10
  if (mod100 >= 11 && mod100 <= 14) return 'дней'
  if (mod10 === 1) return 'день'
  if (mod10 >= 2 && mod10 <= 4) return 'дня'
  return 'дней'
}

export function daysUntil(date: string): number {
  return Math.round((isoDateTimestamp(date) - isoDateTimestamp(todayIso())) / 86_400_000)
}

export function isoDateTimestamp(value: string): number {
  const [year, month, day] = value.split('-').map(Number)
  return Date.UTC(year, month - 1, day)
}

export function buildUpcomingPayments(credits: Debt[], personal: PersonalDebt[]): UpcomingPayment[] {
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

export function sumPayments(payments: UpcomingPayment[], predicate: (payment: UpcomingPayment) => boolean): number {
  return payments.reduce((total, payment) => (
    predicate(payment) ? total + (payment.amount ?? 0) : total
  ), 0)
}

export function personalSubtitle(debt: PersonalDebt): string {
  const pieces = [`открыт ${formatDay(debt.opened_at)}`]
  if (debt.comment) pieces.push(debt.comment)
  if (isStale(debt)) pieces.push('требует внимания')
  return pieces.join(' · ')
}

export function todayIso(): string {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
}

export function isStale(debt: PersonalDebt): boolean {
  if (debt.archived || debt.status !== 'open') return false
  const ninetyDays = 90 * 24 * 60 * 60 * 1000
  return Boolean(debt.due_date && daysUntil(debt.due_date) < 0)
    || Date.now() - isoDateTimestamp(debt.opened_at) > ninetyDays
}
