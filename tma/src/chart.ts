export function chartSeriesLabel(dataKey: unknown): 'Расход' | 'Доход' {
  return dataKey === 'expenseValue' ? 'Расход' : 'Доход'
}
