import { telegramInitData } from './telegram'
import type {
  BudgetResponse,
  BudgetSettings,
  ChargeSubscriptionResponse,
  Subscription,
  SubscriptionsResponse,
} from './types'

export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message)
  }
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers)
  headers.set('X-Telegram-Init-Data', telegramInitData())
  if (options.body) headers.set('Content-Type', 'application/json')

  const response = await fetch(path, { ...options, headers })
  const payload = await response.json().catch(() => ({}))
  if (!response.ok) {
    throw new ApiError(payload.error || 'Ошибка запроса', response.status)
  }
  return payload as T
}

export function queryString(values: Record<string, string | boolean | undefined>): string {
  const params = new URLSearchParams()
  Object.entries(values).forEach(([key, value]) => {
    if (value !== undefined && value !== '') params.set(key, String(value))
  })
  const result = params.toString()
  return result ? `?${result}` : ''
}

export function updateCashBalance(amount: string, anchorDate: string) {
  return api<import('./types').CashBalance>('/api/balance', {
    method: 'PATCH',
    body: JSON.stringify({ amount, anchor_date: anchorDate }),
  })
}

export function createOperation(
  payload: import('./types').OperationCreatePayload,
  idempotencyKey?: string,
) {
  return api<import('./types').Operation>('/api/operations', {
    method: 'POST',
    ...(idempotencyKey ? { headers: { 'Idempotency-Key': idempotencyKey } } : {}),
    body: JSON.stringify(payload),
  })
}

export interface SubmissionKey {
  key: string
  payload: string
}

/**
 * Ключ идемпотентности отправки: новый для нового payload и тот же самый
 * при повторной попытке с тем же payload (таймаут сети, повторный тап).
 */
export function submissionKey(
  previous: SubmissionKey | null,
  payload: unknown,
): SubmissionKey {
  const serialized = JSON.stringify(payload)
  if (previous && previous.payload === serialized) return previous
  return { key: requestKey(), payload: serialized }
}

export function getBudget(weekStart?: string): Promise<BudgetResponse> {
  return api<BudgetResponse>(`/api/budget${queryString({ week_start: weekStart })}`)
}

export function getBudgetSettings(): Promise<BudgetSettings> {
  return api<BudgetSettings>('/api/budget/settings')
}

export function updateBudgetSettings(payload: BudgetSettings): Promise<BudgetSettings> {
  return api<BudgetSettings>('/api/budget/settings', {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
}

export function updateCryptoOverviewVisibility(visible: boolean) {
  return api<{ overview_visible: boolean }>('/api/crypto/overview', {
    method: 'PATCH',
    body: JSON.stringify({ visible }),
  })
}

export function getCryptoOverviewVisibility() {
  return api<{ overview_visible: boolean }>('/api/crypto/overview')
}

export function listSubscriptions(status?: 'active' | 'cancelled'): Promise<SubscriptionsResponse> {
  return api<SubscriptionsResponse>(`/api/subscriptions${queryString({ status })}`)
}

export function createSubscription(payload: Partial<Subscription>): Promise<Subscription> {
  return api<Subscription>('/api/subscriptions', {
    method: 'POST', body: JSON.stringify(payload),
  })
}

export function patchSubscription(id: number, payload: Partial<Subscription>): Promise<Subscription> {
  return api<Subscription>(`/api/subscriptions/${id}`, {
    method: 'PATCH', body: JSON.stringify(payload),
  })
}

export function cancelSubscription(id: number): Promise<Subscription> {
  return api<Subscription>(`/api/subscriptions/${id}`, { method: 'DELETE' })
}

export function chargeSubscription(
  id: number, confirmed: boolean, opDate?: string,
): Promise<ChargeSubscriptionResponse> {
  return api<ChargeSubscriptionResponse>(`/api/subscriptions/${id}/charge`, {
    method: 'POST', body: JSON.stringify({ confirmed, ...(opDate ? { op_date: opDate } : {}) }),
  })
}

export function payDebt(
  id: number,
  amount: string,
  date?: string,
  idempotencyKey?: string,
  paymentType: import('./types').DebtPaymentType = 'regular',
  cashEffect: import('./types').DebtCashEffect = 'movement',
  principalAmount?: string,
) {
  return api<import('./types').Debt>(`/api/debts/${id}/pay`, {
    method: 'POST', body: JSON.stringify({
      amount,
      ...(date ? { date } : {}),
      ...(principalAmount ? { principal_amount: principalAmount } : {}),
      payment_type: paymentType,
      cash_effect: cashEffect,
      idempotency_key: idempotencyKey || requestKey(),
    }),
  })
}

export function deleteDebt(id: number) {
  return api<{ deleted: boolean }>(`/api/debts/${id}`, { method: 'DELETE' })
}

export function payPersonalDebt(
  id: number, amount: string, date?: string, idempotencyKey?: string,
  cashEffect: import('./types').DebtCashEffect = 'movement',
) {
  return api<import('./types').PersonalDebt>(`/api/personal-debts/${id}/pay`, {
    method: 'POST', body: JSON.stringify({
      amount,
      ...(date ? { date } : {}),
      cash_effect: cashEffect,
      idempotency_key: idempotencyKey || requestKey(),
    }),
  })
}

export function deletePersonalDebt(id: number) {
  return api<{ deleted: boolean }>(`/api/personal-debts/${id}`, { method: 'DELETE' })
}

export function archiveDebt(id: number, archived: boolean) {
  return api<import('./types').Debt>(
    `/api/debts/${id}/${archived ? 'archive' : 'restore'}`,
    { method: 'POST' },
  )
}

export function archivePersonalDebt(id: number, archived: boolean) {
  return api<import('./types').PersonalDebt>(
    `/api/personal-debts/${id}/${archived ? 'archive' : 'restore'}`,
    { method: 'POST' },
  )
}

export function listDebtHistory(id: number) {
  return api<import('./types').DebtHistoryPage>(`/api/debts/${id}/payments`)
}

export function listPersonalDebtHistory(id: number) {
  return api<import('./types').DebtHistoryPage>(
    `/api/personal-debts/${id}/payments`,
  )
}

export function requestKey(): string {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) return crypto.randomUUID()
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`
}
