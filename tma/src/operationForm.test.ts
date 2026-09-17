import { describe, expect, it } from 'vitest'

import {
  buildOperationCreatePayload,
  buildOperationPatch,
  emptyOperationForm,
  validateOperationForm,
  type OperationForm,
} from './operationForm'

function form(overrides: Partial<OperationForm> = {}): OperationForm {
  return { ...emptyOperationForm(), ...overrides }
}

describe('operation form', () => {
  it('builds an expense payload without AI fields', () => {
    expect(buildOperationCreatePayload(form({
      amount: '1 250,50',
      category: 'Продукты',
      comment: 'рынок',
    }))).toEqual({
      type: 'расход',
      amount: '1250.50',
      op_date: expect.any(String),
      category: 'Продукты',
      comment: 'рынок',
    })
  })

  it('builds a transfer payload with direction and no category', () => {
    expect(buildOperationCreatePayload(form({
      type: 'перевод',
      amount: '500',
      category: '',
      transfer_direction: 'self',
    }))).toMatchObject({
      type: 'перевод',
      amount: '500',
      transfer_direction: 'self',
    })
    expect(buildOperationCreatePayload(form({ type: 'перевод' }))).not.toHaveProperty('category')
  })

  it('rejects incomplete form and accepts a valid one', () => {
    expect(validateOperationForm(form({ amount: '' }))).toBe('Укажи положительную сумму.')
    expect(validateOperationForm(form({ amount: '1250.50', category: '' }))).toBe('Выбери категорию.')
    expect(validateOperationForm(form({ amount: '1250.50', type: 'перевод', category: '', transfer_direction: '' }))).toBe('Выбери направление перевода.')
    expect(validateOperationForm(form({ amount: '1250.50' }))).toBeNull()
  })

  it('creates only changed patch fields and clears transfer metadata', () => {
    const baseline = form({ amount: '500', category: 'Продукты' })
    expect(buildOperationPatch(
      form({ ...baseline, type: 'перевод', category: '', transfer_direction: 'out' }),
      baseline,
    )).toEqual({
      type: 'перевод',
      category: null,
      transfer_direction: 'out',
    })
  })
})
