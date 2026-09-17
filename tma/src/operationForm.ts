import type {
  Operation,
  OperationCreatePayload,
  OperationType,
  TransferDirection,
} from './types'

export interface OperationForm {
  amount: string
  category: string
  op_date: string
  type: OperationType
  comment: string
  note: string
  transfer_direction: TransferDirection | ''
}

const TYPE_OPTIONS: Array<{ value: OperationType; label: string }> = [
  { value: 'расход', label: 'Расход' },
  { value: 'доход', label: 'Доход' },
  { value: 'перевод', label: 'Перевод' },
]

export function operationTypeOptions() {
  return TYPE_OPTIONS
}

function localToday(): string {
  const today = new Date()
  const month = String(today.getMonth() + 1).padStart(2, '0')
  const day = String(today.getDate()).padStart(2, '0')
  return `${today.getFullYear()}-${month}-${day}`
}

export function emptyOperationForm(): OperationForm {
  return {
    amount: '',
    category: 'Прочее',
    op_date: localToday(),
    type: 'расход',
    comment: '',
    note: '',
    transfer_direction: 'out',
  }
}

export function formFromOperation(operation: Operation): OperationForm {
  return {
    amount: operation.amount.replace(/\.00$/, ''),
    category: operation.category || '',
    op_date: operation.op_date,
    type: operation.type,
    comment: operation.comment || '',
    note: operation.note || '',
    transfer_direction: operation.transfer_direction || 'out',
  }
}

export function validateOperationForm(form: OperationForm): string | null {
  const amount = Number(form.amount.replace(/\s/g, '').replace(',', '.'))
  if (!form.amount.trim() || !Number.isFinite(amount) || amount <= 0) {
    return 'Укажи положительную сумму.'
  }
  if (!form.op_date) return 'Укажи дату операции.'
  if (form.type !== 'перевод' && !form.category) return 'Выбери категорию.'
  if (form.type === 'перевод' && !form.transfer_direction) return 'Выбери направление перевода.'
  return null
}

export function buildOperationCreatePayload(form: OperationForm): OperationCreatePayload {
  const payload: OperationCreatePayload = {
    type: form.type,
    amount: form.amount.replace(/\s/g, '').replace(',', '.'),
    op_date: form.op_date,
    comment: form.comment.trim() || undefined,
  }
  if (form.type === 'перевод') {
    if (form.transfer_direction) payload.transfer_direction = form.transfer_direction
  } else {
    payload.category = form.category || 'Прочее'
  }
  return payload
}

export function buildOperationPatch(
  form: OperationForm,
  baseline: OperationForm,
): Record<string, string | null> {
  const patch: Record<string, string | null> = {}
  const scalarFields: Array<keyof OperationForm> = [
    'amount', 'op_date', 'type', 'comment', 'note',
  ]
  for (const field of scalarFields) {
    if (form[field] !== baseline[field]) patch[field] = form[field] || null
  }
  if (form.category !== baseline.category || form.type !== baseline.type) {
    patch.category = form.type === 'перевод' ? null : form.category || null
  }
  if (
    form.transfer_direction !== baseline.transfer_direction
    || form.type !== baseline.type
  ) {
    patch.transfer_direction = form.type === 'перевод'
      ? form.transfer_direction
      : null
  }
  return patch
}
