import { describe, expect, it } from 'vitest'

import { resolveUpcomingFocus } from './upcomingFocus'
import type { UpcomingFocus } from '../types'

function focus(overrides: Partial<UpcomingFocus> = {}): UpcomingFocus {
  return { kind: 'subscription', id: 7, nonce: 1, ...overrides }
}

describe('resolveUpcomingFocus', () => {
  it('open when the exact kind and id are loaded', () => {
    expect(resolveUpcomingFocus(focus(), 'subscription', 0, true, [3, 7])).toEqual({
      status: 'open',
      focus: focus(),
    })
  })

  it('ignore a request for another entity kind', () => {
    // Одинаковый id у подписки и кредита не должен открывать чужую запись.
    const debtFocus = focus({ kind: 'debt', id: 7 })
    expect(resolveUpcomingFocus(debtFocus, 'subscription', 0, true, [7])).toEqual({
      status: 'ignore',
    })
  })

  it('ignore an already handled (stale) request', () => {
    expect(resolveUpcomingFocus(focus({ nonce: 5 }), 'subscription', 5, true, [7])).toEqual({
      status: 'ignore',
    })
  })

  it('wait while the target list is not loaded yet', () => {
    expect(resolveUpcomingFocus(focus(), 'subscription', 0, false, [])).toEqual({
      status: 'wait',
    })
  })

  it('missing when the record is unavailable after loading', () => {
    expect(resolveUpcomingFocus(focus({ id: 9 }), 'subscription', 0, true, [3, 7])).toEqual({
      status: 'missing',
      focus: focus({ id: 9 }),
    })
  })

  it('ignore when there is no request at all', () => {
    expect(resolveUpcomingFocus(null, 'debt', 0, true, [7])).toEqual({ status: 'ignore' })
  })
})
