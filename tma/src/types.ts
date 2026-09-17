export type OperationType = 'расход' | 'доход' | 'перевод'
export type TransferDirection = 'in' | 'out' | 'self'

export interface OperationCreatePayload {
  type: OperationType
  amount: string
  op_date?: string
  category?: string
  comment?: string
  account?: string
  transfer_direction?: TransferDirection
}

interface TelegramHapticFeedback {
  impactOccurred?: (kind: 'light' | 'medium') => void
}

interface TelegramWebApp {
  initData?: string
  ready?: () => void
  expand?: () => void
  setHeaderColor?: (color: string) => void
  setBackgroundColor?: (color: string) => void
  HapticFeedback?: TelegramHapticFeedback
}

declare global {
  interface Window {
    Telegram?: {
      WebApp?: TelegramWebApp
    }
  }
}

export interface Operation {
  id: number
  created_at: string
  op_date: string
  type: OperationType
  amount: string
  category: string | null
  comment: string | null
  note: string | null
  account: string | null
  transfer_direction: TransferDirection | null
  source: string | null
  needs_review: boolean
  tg_message_id: number | null
  deleted_at: string | null
  subscription_id: number | null
}

export interface SummaryDay {
  op_date: string
  expense: string
  income: string
}

export interface SummaryCategory {
  category: string
  total: string
}

export interface Summary {
  month: string
  period_mode: 'anchor' | 'month'
  period_start: string
  period_end: string
  chart_start: string
  chart_end: string
  expense: string
  income: string
  transfer_in: string
  transfer_out: string
  balance: string
  average_daily: string
  average_daily_income: string
  days: SummaryDay[]
  categories: SummaryCategory[]
}

export interface CashBalance {
  has_anchor: boolean
  amount?: string
  anchor_date?: string
  anchor_amount?: string
}

export interface OperationPage {
  items: Operation[]
  next_cursor: string | null
  totals?: OperationTotals
}

export interface OperationTotals {
  total_count: number
  expense: string
  income: string
  transfer: string
}

export interface Categories {
  expense: string[]
  income: string[]
}

export type BudgetStatus = 'ok' | 'warning' | 'exceeded'

export interface BudgetCategory {
  category: string
  limit: string | null
  spent: string
  remaining: string | null
  percent: string | null
  status: BudgetStatus | null
}

export interface BudgetOverall {
  limit: string
  spent: string
  remaining: string
  percent: string
  status: BudgetStatus
}

export interface BudgetResponse {
  configured: boolean
  week_start: string
  week_end: string
  is_current: boolean
  selected_spent?: string
  category_limits_total?: string
  overall?: BudgetOverall | null
  categories?: BudgetCategory[]
  previous_week_start: string | null
  next_week_start: string | null
}

export interface BudgetSettings {
  overall_limit: string | null
  categories: Array<{ category: string; limit: string | null }>
}

export interface HistoryPreset {
  date?: string
  date_from?: string
  date_to?: string
  category?: string
}

export interface Debt {
  id: number
  creditor: string
  loan_name: string | null
  contract_ref: string | null
  principal: string
  balance: string
  rate: string | null
  min_payment: string | null
  next_payment_amount: string | null
  opened_at: string | null
  next_payment_date: string | null
  payment_day: number | null
  priority: number | null
  due_date: string | null
  maturity_date: string | null
  status: 'active' | 'closed'
  archived: boolean
  created_at: string
  forecast_date: string | null
  payment_count: number
  history_count?: number
  progress: string
}

export interface DebtPage {
  items: Debt[]
}

export interface DebtSummary {
  total_principal: string
  total_balance: string
  total_paid: string
  progress: string
  active_count: number
  closed_count: number
  curve: Array<{ month: string; balance: string }>
}

export type PersonalDebtDirection = 'owed_to_me' | 'i_owe'

export interface PersonalDebt {
  id: number
  person: string
  direction: PersonalDebtDirection
  principal: string
  balance: string
  opened_at: string
  due_date: string | null
  comment: string | null
  status: 'open' | 'closed'
  archived: boolean
  operation_id: number | null
  payment_count?: number
}

export interface DebtHistoryEntry {
  id: number
  debt_id?: number
  personal_debt_id?: number
  operation_id: number | null
  pay_date: string
  amount: string
  principal_amount?: string | null
  interest_amount?: string | null
  kind: 'payment' | 'adjustment'
  payment_type?: 'regular' | 'early'
  cash_effect?: DebtCashEffect
  reason?: string | null
}

export type DebtPaymentType = 'regular' | 'early'
export type DebtCashEffect = 'movement' | 'already_in_balance'

export interface DebtHistoryPage {
  items: DebtHistoryEntry[]
}

export interface PersonalDebtPage {
  items: PersonalDebt[]
}

export type SubscriptionPeriod = 'monthly' | 'yearly'

export interface Subscription {
  id: number
  title: string
  amount: string
  period: SubscriptionPeriod
  next_charge: string
  category: string | null
  comment: string | null
  status: 'active' | 'cancelled'
  due: boolean
  created_at: string
}

export interface UpcomingCharge {
  subscription_id: number
  title: string
  amount: string
  charge_date: string
}

export interface SubscriptionsResponse {
  items: Subscription[]
  monthly_cost: string
  yearly_cost: string | null
  month_expenses: string | null
  share_percent: string | null
  upcoming: UpcomingCharge[]
}

export interface ChargeSubscriptionResponse {
  subscription: Subscription
  operation_id: number | null
}

export interface CryptoHolding {
  asset: string
  quantity: string
  updated_at: string
}

export interface CryptoTransaction {
  id: number
  asset: string
  quantity_delta: string
  rub_amount: string
  op_date: string
  operation_id: number | null
  comment: string | null
}

export interface CryptoPageData {
  items: CryptoHolding[]
  transactions: CryptoTransaction[]
  overview_visible: boolean
}
