import { formatMoney } from '../../format'
import type { Operation } from '../../types'

export function compareOperations(left: Operation, right: Operation): number {
  return right.op_date.localeCompare(left.op_date) || right.id - left.id
}

export function calculateDayTotals(operations: Operation[]) {
  return operations.reduce(
    (result, operation) => {
      const amount = Number(operation.amount)
      if (operation.type === 'расход') result.expense += amount
      if (operation.type === 'доход') result.income += amount
      if (operation.type === 'перевод') result.transfer += amount
      return result
    },
    { expense: 0, income: 0, transfer: 0 },
  )
}

export function formatDayNet(value: number): string {
  return value > 0 ? `+${formatMoney(value)}` : formatMoney(value)
}
