const integerMoneyFormatter = new Intl.NumberFormat('ru-RU', {
  maximumFractionDigits: 0,
})

const fractionalMoneyFormatter = new Intl.NumberFormat('ru-RU', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})

export function formatMoney(value: string | number): string {
  const amount = Number(value)
  const sign = amount < 0 ? '−' : ''
  const formatter = Number.isInteger(amount) ? integerMoneyFormatter : fractionalMoneyFormatter
  return `${sign}${formatter.format(Math.abs(amount))} ₽`
}

export function formatDay(value: string): string {
  return new Intl.DateTimeFormat('ru-RU', {
    day: 'numeric',
    month: 'long',
  }).format(new Date(`${value}T12:00:00`))
}

export function formatShortDay(value: string): string {
  return new Intl.DateTimeFormat('ru-RU', { day: 'numeric' }).format(
    new Date(`${value}T12:00:00`),
  )
}

const PERIOD_AXIS_DAYS = new Set([1, 6, 11, 16, 21, 26])

export function formatPeriodAxisDay(value: string | number): string {
  const dateValue = String(value)
  const day = Number(dateValue.slice(-2))
  return PERIOD_AXIS_DAYS.has(day) ? formatShortDay(dateValue) : ''
}

export function monthTitle(value: string): string {
  const [year, month] = value.split('-').map(Number)
  const title = new Intl.DateTimeFormat('ru-RU', {
    month: 'long',
    year: 'numeric',
  }).format(new Date(year, month - 1, 1))
  const withoutYearSuffix = title.replace(/\s*г\.$/, '')
  return withoutYearSuffix[0].toUpperCase() + withoutYearSuffix.slice(1)
}

export function shiftMonth(value: string, offset: number): string {
  const [year, month] = value.split('-').map(Number)
  const shifted = new Date(year, month - 1 + offset, 1)
  return `${shifted.getFullYear()}-${String(shifted.getMonth() + 1).padStart(2, '0')}`
}

export function todayMonth(): string {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`
}

/**
 * Разбивает ненулевые расходы месяца на четыре квартильных уровня.
 * Нулевые дни всегда получают уровень 0.
 */
export function expenseIntensityLevels(values: Array<string | number>): number[] {
  const numbers = values.map((value) => Number(value))
  const nonZero = numbers.filter((value) => value > 0).sort((a, b) => a - b)
  if (!nonZero.length) return numbers.map(() => 0)

  const quantile = (ratio: number): number => {
    const position = (nonZero.length - 1) * ratio
    const lower = Math.floor(position)
    const upper = Math.ceil(position)
    if (lower === upper) return nonZero[lower]
    return nonZero[lower] + (nonZero[upper] - nonZero[lower]) * (position - lower)
  }
  const first = quantile(.25)
  const second = quantile(.5)
  const third = quantile(.75)

  return numbers.map((value) => {
    if (value <= 0) return 0
    if (value <= first) return 1
    if (value <= second) return 2
    if (value <= third) return 3
    return 4
  })
}
