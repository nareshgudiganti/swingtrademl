import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import adminSource from './AdminUsers.tsx?raw'
import { ModuleListView, refusalText, submitSwitch, summaryText, type AdminCall, type ModuleList } from './AdminModules'

const LIST: ModuleList = {
  scope: 'shared',
  state_unknown: false,
  modules: [
    { id: 'core.safety', label: 'Safety limits', core: true, state: 'active', enabled: true, jobs: [] },
    { id: 'finance', label: 'Finance', core: false, state: 'parked', enabled: true, jobs: [] },
    { id: 'research_lanes', label: 'Research lanes', core: false, state: 'active', enabled: false, jobs: [] },
  ],
}
const noCall = (async () => undefined) as unknown as AdminCall
const view = (data: ModuleList) => renderToStaticMarkup(<ModuleListView data={data} call={noCall} onChanged={() => {}} />)

const DETAILED: ModuleList = {
  scope: 'shared',
  state_unknown: false,
  modules: [
    {
      id: 'brain',
      label: 'TradeMind Brain',
      core: false,
      state: 'active',
      enabled: true,
      jobs: ['brain_nightly', 'brain_score'],
      route_prefixes: ['/brain', '/ideas'],
      capabilities: ['ideas', 'reports'],
      depends_on: ['core.orders'],
      packages: ['swing_trade_ml.brain'],
    },
    { id: 'finance', label: 'Finance', core: false, state: 'parked', enabled: true, jobs: [], route_prefixes: [], capabilities: [], depends_on: [], packages: [] },
  ],
}

describe('parts of the app (admin): what each part owns and needs', () => {
  it('lists the inventory in plain words under a details row', () => {
    const html = view(DETAILED)
    expect(html).toContain('<details')
    for (const label of ['Needs', 'Screens’ data paths', 'Background jobs', 'What it can do', 'Code packages']) {
      expect(html).toContain(label)
    }
    for (const value of ['/brain', '/ideas', 'brain_nightly', 'brain_score', 'core.orders', 'swing_trade_ml.brain', 'reports']) {
      expect(html).toContain(value)
    }
  })

  it('shows core or optional and the stage', () => {
    const html = view(DETAILED)
    expect(html).toContain('Optional')
    expect(html).toContain('Stage: parked')
    expect(view({ ...LIST, modules: LIST.modules.filter((m) => m.core) })).toContain('Core')
  })

  it('says "none" for an empty list and survives a server that omits the fields', () => {
    const html = view(DETAILED)
    expect(html).toContain('none')
    expect(() => view(LIST)).not.toThrow()
  })
})

describe('parts of the app (admin)', () => {
  it('is a tab of the admin screen, which already needs the two-step code', () => {
    expect(adminSource).toContain("'modules'")
    expect(adminSource).toContain('<AdminModules')
  })

  it('answers first: which parts are off', () => {
    expect(summaryText(LIST.modules)).toBe('1 part is switched off: Research lanes.')
    expect(summaryText(LIST.modules.slice(0, 2))).toBe('Everything is on.')
    expect(view(LIST)).toContain('1 part is switched off: Research lanes.')
  })

  it('shows core parts as always on, with no control', () => {
    const html = view({ ...LIST, modules: LIST.modules.filter((m) => m.core) })
    expect(html).toContain('Always on')
    expect(html).not.toContain('<button')
  })

  it('offers switch off for an on part and switch on for an off part', () => {
    const html = view(LIST)
    expect(html).toContain('Switch off')
    expect(html).toContain('Switch on')
  })

  it('warns when the saved switches could not be read', () => {
    expect(view({ ...LIST, state_unknown: true })).toContain('could not be read')
    expect(view(LIST)).not.toContain('could not be read')
  })

  it('sends the switch with a reason and reports success', async () => {
    const seen: { path: string; init?: RequestInit }[] = []
    const call = (async (path: string, init?: RequestInit) => {
      seen.push({ path, init })
      return {}
    }) as unknown as AdminCall
    const result = await submitSwitch(call, 'finance', false, '  parking it  ')
    expect(result).toEqual({ ok: true })
    expect(seen[0]?.path).toBe('/admin/modules/finance')
    expect(seen[0]?.init?.method).toBe('PUT')
    expect(JSON.parse(String(seen[0]?.init?.body))).toEqual({ enabled: false, reason: 'parking it' })
  })

  it('needs a reason and sends nothing without one', async () => {
    let calls = 0
    const call = (async () => {
      calls += 1
    }) as unknown as AdminCall
    const result = await submitSwitch(call, 'finance', false, ' ')
    expect(result.ok).toBe(false)
    expect(calls).toBe(0)
  })

  it('goes back to the code prompt when the two-step code has expired', async () => {
    const call = (async () => {
      throw { status: 403, code: 'mfa_required', message: 'Enter your two-step code.' }
    }) as unknown as AdminCall
    const result = await submitSwitch(call, 'finance', false, 'because')
    expect(result).toEqual({ ok: false, expired: true, message: '' })
  })

  it('never sends a core part, and encodes the id in the path', async () => {
    const seen: string[] = []
    const call = (async (path: string) => {
      seen.push(path)
      return {}
    }) as unknown as AdminCall
    const core = await submitSwitch(call, 'core.safety', false, 'because')
    expect(core.ok).toBe(false)
    await submitSwitch(call, 'a b/c', false, 'because')
    expect(seen).toEqual(['/admin/modules/a%20b%2Fc'])
  })

  it('claims no state and disables every control when the saved switches cannot be read', () => {
    const html = view({ ...LIST, state_unknown: true })
    expect(html).toContain('Can&#x27;t read the current switches right now')
    expect(html).not.toContain('Everything is on')
    expect(html).not.toContain('switched off:')
    expect(html).not.toContain('>On<')
    expect(html).not.toContain('>Off<')
    expect(html.match(/<button[^>]*disabled/g)?.length).toBe(2)
    expect(html.match(/<button/g)?.length).toBe(2)
  })

  it('explains each refusal in plain words', async () => {
    const failing = (status: number, message = 'x') =>
      (async () => {
        throw { status, message }
      }) as unknown as AdminCall
    const not409 = await submitSwitch(failing(409, 'brain depends on finance: switch them off first'), 'finance', false, 'because')
    expect(not409).toEqual({
      ok: false,
      message: 'Not changed. brain depends on finance: switch them off first',
    })
    const not403 = await submitSwitch(failing(403), 'finance', false, 'because')
    expect(not403.ok === false && not403.message).toContain('Only the named owner')
    expect(refusalText({ status: 404 })).toContain('no longer exists')
    expect(refusalText({ status: 500 })).toContain('Try again')
  })
})
