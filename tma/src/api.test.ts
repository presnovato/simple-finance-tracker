import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createOperation, submissionKey } from './api'

vi.mock('./telegram', () => ({ telegramInitData: () => 'test-init-data' }))

function lastRequest(): RequestInit {
  const mock = fetch as unknown as ReturnType<typeof vi.fn>
  return mock.mock.calls[0][1] as RequestInit
}

describe('submissionKey', () => {
  it('reuses the key for a retry of the same payload', () => {
    const first = submissionKey(null, { amount: '100', type: 'расход' })
    const retry = submissionKey(first, { amount: '100', type: 'расход' })

    expect(retry.key).toBe(first.key)
  })

  it('generates a new key for a different payload', () => {
    const first = submissionKey(null, { amount: '100' })
    const next = submissionKey(first, { amount: '200' })

    expect(next.key).not.toBe(first.key)
  })
})

describe('createOperation idempotency header', () => {
  beforeEach(() => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        new Response(JSON.stringify({ id: 1 }), {
          status: 201,
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
    )
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('sends Idempotency-Key when a key is given', async () => {
    await createOperation({} as never, 'key-1')

    const headers = new Headers(lastRequest().headers)
    expect(headers.get('Idempotency-Key')).toBe('key-1')
  })

  it('omits the header without a key', async () => {
    await createOperation({} as never)

    const headers = new Headers(lastRequest().headers)
    expect(headers.get('Idempotency-Key')).toBeNull()
  })
})
