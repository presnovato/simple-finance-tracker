import type { Debt, PersonalDebt } from '../../types'

export const GREEN = '#77e6b6'
export const PURPLE = '#9f8cff'
// TKSheet keeps a closed panel mounted for 380ms to play its exit animation.
// Leave a small buffer before mounting the next panel so two sheets never
// animate over each other when moving from "Ещё" to an action form.
export const SHEET_SWITCH_DELAY_MS = 420

export type CreditScope = 'active' | 'closed' | 'archived'
export type PersonalScope = 'open' | 'closed' | 'archived'
export type DebtTarget = { kind: 'credit'; debt: Debt } | { kind: 'personal'; debt: PersonalDebt }
export type DebtLoadSection = 'credits' | 'summary' | 'personal'
export type DueTone = 'overdue' | 'today' | 'soon'
export type DueStatus = { label: string; tone: DueTone }
export type DebtChartPoint = { month: string; balance: string; value: number; label: string }
export type UpcomingPayment = {
  key: string
  title: string
  subtitle: string
  date: string
  days: number
  amount: number | null
  due: DueStatus
  target: DebtTarget
}

export const EMPTY_SECTION_LOADING: Record<DebtLoadSection, boolean> = {
  credits: true,
  summary: true,
  personal: true,
}
