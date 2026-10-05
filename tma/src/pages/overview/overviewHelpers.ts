import { formatMoney } from '../../format'

export function periodComparison(current: string, previous?: string): string | undefined {
  if (previous === undefined) return undefined
  const delta = Number(current) - Number(previous)
  if (!Number.isFinite(delta)) return undefined
  if (delta === 0) return 'К прошлому месяцу: без изменений'
  return 'К прошлому месяцу: ' + (delta > 0 ? '+' : '−') + formatMoney(String(Math.abs(delta)))
}

export function progressValue(percent: string | null): number {
  return Math.min(100, Math.max(0, Number(percent) || 0))
}

export function budgetStatusColor(status: string | null): string {
  return status === 'exceeded' ? 'var(--red)' : status === 'warning' ? 'var(--yellow)' : 'var(--green)'
}

export function budgetRemainingLabel(value: string | null): string {
  if (value === null) return 'Без отдельного лимита'
  const amount = Number(value)
  return amount < 0 ? `Перерасход ${formatMoney(String(Math.abs(amount)))}` : `Остаток ${formatMoney(value)}`
}

export function todayIsoDate(): string {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Europe/Moscow',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(new Date())
  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]))
  return `${values.year}-${values.month}-${values.day}`
}

export function formatDayLabel(value: string): string {
  return new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'long' })
    .format(new Date(`${value}T12:00:00`))
}
