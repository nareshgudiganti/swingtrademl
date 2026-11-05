import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToString } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import clientSource from '../api/client.ts?raw'
import type { RegistryModel, RegistrySlot, RegistrySlots } from '../api/types'
import appSource from '../App.tsx?raw'
import pageSource from './ModelRegistry.tsx?raw'
import { forwardText, metricText, RegistryBoard } from './ModelRegistry'

const NONE = { value: null, note: 'Not measured' }

function model(over: Partial<RegistryModel> = {}, auc: number | null = null): RegistryModel {
  return {
    slot: '5d-large',
    provenance: {
      model_id: 2,
      name: 'swing_classifier',
      version: 'v2',
      algorithm: 'lightgbm',
      horizon_days: 5,
      target_return_pct: 0.02,
      stop_return_pct: null,
      label_kind: 'endpoint',
      n_inputs: 37,
      inputs_fingerprint: 'abcdef0123456789',
      n_training_symbols: 49,
      training_universe_fingerprint: '0123456789abcdef',
      n_samples: null,
      train_start: null,
      train_end: '2025-10-09T18:30:00+00:00',
      trained_at: null,
      calibration: 'Unknown',
      model_file_fingerprint: 'Unknown',
    },
    registry_status: 'ACTIVE',
    active_strategies: [],
    active_strategies_note: '',
    evidence: {
      historical: {
        held_out_auc: { label: 'Held-out AUC (one historical split; not top-5 performance)', value: auc },
        precision_at_threshold: { label: 'Precision at threshold (historical split)', value: null },
        top5_ranking: { label: 'Top-5 ranking performance', ...NONE },
        net_return_after_costs: { label: 'Net return after costs', ...NONE },
        drawdown: { label: 'Drawdown', ...NONE },
      },
      forward: { label: 'Forward evidence', value: null, note: 'Read from the 5-day test report, not here' },
    },
    ...over,
  }
}

function slot(h: number, tier: RegistrySlot['cap_tier'], rank: number, models: RegistryModel[] = []): RegistrySlot {
  return {
    slot_key: `${h}d-${tier}`,
    horizon_days: h,
    cap_tier: tier,
    research_status: h === 5 ? 'researching' : 'not_started',
    priority: null,
    note: null,
    version: 1,
    updated_at: null,
    updated_by: null,
    rank,
    models,
  }
}

function data(over: Partial<RegistrySlots> = {}): RegistrySlots {
  const tiers: RegistrySlot['cap_tier'][] = ['large', 'midcap', 'smallcap']
  const slots = [15, 10, 5].flatMap((h, i) => tiers.map((t, j) => slot(h, t, i * 3 + j + 1)))
  slots.find((s) => s.slot_key === '5d-large')!.models = [model()]
  return {
    ordering: 'priority 1 first',
    slots,
    unassigned: [],
    statuses: ['not_started', 'researching', 'paused', 'dropped'],
    status_note: 'Research status is a descriptive label. It does not mean validated and starts nothing.',
    ...over,
  }
}

function render(d: RegistrySlots, forward: string | null = null): string {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  // Server rendering puts <!-- --> between adjacent text pieces; drop them so the text reads as the user sees it.
  return renderToString(
    <QueryClientProvider client={client}>
      <RegistryBoard data={d} forward={forward} />
    </QueryClientProvider>,
  ).replace(/<!-- -->/g, '')
}

describe('model registry page', () => {
  it('shows all nine slots', () => {
    const html = render(data())
    for (const h of [15, 10, 5])
      for (const t of ['Large cap', 'Mid cap', 'Small cap']) expect(html).toContain(`${h}-day · ${t}`)
  })

  it('says Not measured for anything nobody measured, and never shows zero for a missing metric', () => {
    expect(metricText({ label: 'x', value: null })).toBe('Not measured')
    expect(metricText({ label: 'x', value: null, note: 'Not measured' })).toBe('Not measured')
    const html = render(data())
    expect(html).toContain('Not measured')
    expect(html).not.toContain('<strong>0</strong>')
    expect(html).not.toContain('<strong>0.000</strong>')
  })

  it('labels AUC as a historical split, not as ranking performance', () => {
    expect(metricText({ label: 'x', value: 0.612 })).toBe('0.612')
    const html = render(data())
    expect(html).toContain('Held-out AUC (one historical split; not top-5 performance)')
    expect(html).toContain('Top-5 ranking performance')
  })

  it('keeps registry status and strategy usage as two separate facts', () => {
    const html = render(data())
    expect(html).toContain('Registry status: ACTIVE')
    expect(html).toContain('Used by strategies')
    expect(html).toContain('None. No switched-on strategy names this model.')
    expect(html).not.toMatch(/Not deployed|Deployed/)
  })

  it('says Unknown when the strategies could not be read', () => {
    const s = data()
    s.slots.find((x) => x.slot_key === '5d-large')!.models = [model({ active_strategies: null })]
    expect(render(s)).toContain('Unknown (strategies could not be read)')
  })

  it('lists unassigned models read only, and says they are never guessed', () => {
    const exp = model({
      slot: null,
      provenance: { ...model().provenance, model_id: 77, name: 'wf_h15_20260101', horizon_days: 15 },
    })
    const html = render(data({ unassigned: [exp] }))
    expect(html).toContain('Unassigned models (read only)')
    expect(html).toContain('wf_h15_20260101')
    expect(html).toContain('never guessed')
  })

  it('keeps forward evidence in its own block', () => {
    const html = render(data(), 'Not measured yet: the 5-day test has not recorded a run.')
    expect(html).toContain('Forward evidence (kept separate)')
    expect(html).toContain('the 5-day test has not recorded a run')
  })

  it('has no train, activate or promote control, and tells the owner saving starts nothing', () => {
    const html = render(data())
    expect(html).toContain('Save research notes')
    expect(html).toContain('does not start training, activate a model or change any trading')
    expect(html.toLowerCase()).not.toMatch(/<button[^>]*>\s*(activate|train|promote|deploy)/)
    expect(pageSource).not.toMatch(/activateModel|trainModel|\/ml\/|api\.train|api\.activate/)
  })

  it('offers only descriptive research labels', () => {
    const html = render(data())
    for (const word of ['Not started', 'Researching', 'Paused', 'Dropped']) expect(html).toContain(word)
    expect(html).not.toMatch(/Validated|Approved/)
  })
})

describe('forward text', () => {
  it('is honest about an empty or missing 5-day report', () => {
    expect(forwardText(undefined)).toBeNull()
    expect(forwardText({ runs: [] })).toContain('Not measured yet')
    expect(forwardText({ runs: [{}], verdict: { state: 'not_calculated' } })).toContain('not_calculated')
  })
})

describe('wiring', () => {
  it('writes through the one registry PATCH and nothing else', () => {
    expect(pageSource.match(/api\.\w+/g)?.sort()).toEqual(
      ['h05Report', 'modelRegistryChange', 'modelRegistrySlots'].map((n) => `${'api'}.${n}`).sort(),
    )
    expect(clientSource).toMatch(/patch<RegistrySlot>\(`\/model-registry\/slots\//)
  })

  it('is routed by URL only, with no menu entry', () => {
    expect(appSource).toContain("location.pathname === '/model-registry'")
    expect(appSource).not.toMatch(/to: '\/model-registry'/)
  })
})
