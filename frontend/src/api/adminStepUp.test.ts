import { afterEach, describe, expect, it, vi } from 'vitest'

import { api, registerStepUpHandler, setAdminStepUp } from './client'

function reply(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

afterEach(() => {
  registerStepUpHandler(null)
  setAdminStepUp('')
  vi.unstubAllGlobals()
})

describe('admin two-step code on privileged calls', () => {
  it('asks for the code once, then repeats the same call with it', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(reply(403, { detail: { code: 'mfa_required', message: 'Enter your two-step code.' } }))
      .mockResolvedValueOnce(reply(200, { enabled: true }))
    vi.stubGlobal('fetch', fetchMock)
    const ask = vi.fn().mockResolvedValue('tok123')
    registerStepUpHandler(ask)

    await expect(api.setPlanSwitch(true)).resolves.toEqual({ enabled: true })

    expect(ask).toHaveBeenCalledWith('verify')
    expect(fetchMock).toHaveBeenCalledTimes(2)
    const second = fetchMock.mock.calls[1]![1] as RequestInit
    expect((second.headers as Record<string, string>)['X-Admin-Mfa']).toBe('tok123')
  })

  it('walks through setup first when two-step is not set up yet', async () => {
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValueOnce(reply(403, { detail: { code: 'mfa_setup_required', message: 'Set up two-step sign-in first.' } }))
        .mockResolvedValueOnce(reply(200, [])),
    )
    const ask = vi.fn().mockResolvedValue('t')
    registerStepUpHandler(ask)
    await api.users()
    expect(ask).toHaveBeenCalledWith('enrol')
  })

  it('fails with the plain message when the admin cancels, and never loops', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(reply(403, { detail: { code: 'mfa_required', message: 'Enter your two-step code.' } }))
    vi.stubGlobal('fetch', fetchMock)
    registerStepUpHandler(vi.fn().mockResolvedValue(null))
    await expect(api.users()).rejects.toMatchObject({ message: 'Enter your two-step code.', code: 'mfa_required' })
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('only retries once if the new code is also refused', async () => {
    const fetchMock = vi
      .fn()
      .mockImplementation(() => Promise.resolve(reply(403, { detail: { code: 'mfa_required', message: 'x' } })))
    vi.stubGlobal('fetch', fetchMock)
    const ask = vi.fn().mockResolvedValue('bad')
    registerStepUpHandler(ask)
    await expect(api.users()).rejects.toMatchObject({ code: 'mfa_required' })
    expect(ask).toHaveBeenCalledTimes(1)
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('does not send the code to non-admin paths', async () => {
    const fetchMock = vi.fn().mockResolvedValue(reply(200, {}))
    vi.stubGlobal('fetch', fetchMock)
    setAdminStepUp('tok')
    await api.h05Report()
    const init = fetchMock.mock.calls[0]![1] as RequestInit
    expect((init.headers as Record<string, string>)['X-Admin-Mfa']).toBeUndefined()
  })
})
