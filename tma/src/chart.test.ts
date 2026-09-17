import { describe, expect, it } from 'vitest'
import { chartSeriesLabel } from './chart'

describe('chartSeriesLabel', () => {
  it('maps the expense data key to the expense label', () => {
    expect(chartSeriesLabel('expenseValue')).toBe('Расход')
  })

  it('uses the income label for the income data key', () => {
    expect(chartSeriesLabel('incomeValue')).toBe('Доход')
  })
})
