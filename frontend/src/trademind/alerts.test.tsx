// Admin > Alerts (ux3): the owner's choices are edited correctly, bad times are caught before saving, and the page
// shows every switchable message with a plain explanation and the safety messages as "Always on".
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToString } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import { draftFrom, heldText, inWindow, isOn, problem, quietText, sameDraft, toggle } from './alerts'
import type { AlertSettings } from './alerts'
import Alerts, { AlertsForm } from './pages/Alerts'

const settings: AlertSettings = {
  switchable: [
    { key: 'trade_ideas', label: 'New buy ideas', explain: 'A message when a stock is worth buying.', on: true },
    { key: 'paper_buys', label: 'Practice buys', explain: 'A message when the bot buys with pretend money.', on: false },
  ],
  always_on: [
    { key: 'sells', label: 'Sells and stop-losses', explain: 'You may need to act quickly.', on: true },
    { key: 'real_orders', label: 'Real-money orders', explain: 'Real money is involved.', on: true },
  ],
  disabled: ['paper_buys'],
  quiet_enabled: true,
  quiet_start: '22:00',
  quiet_end: '07:00',
  digest_enabled: false,
  digest_time: '18:00',
  last_digest_on: null,
  held: 2,
  timezone: 'IST',
}

const text = (html: string) =>
  html.replace(/<!-- -->/g, '').replace(/<[^>]+>/g, ' ').replace(/&#x27;|&apos;/g, "'").replace(/\s+/g, ' ')

function render(node: React.ReactNode, data?: AlertSettings): string {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  if (data) client.setQueryData(['alert-settings'], data)
  return renderToString(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/trademind/alerts']}>{node}</MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('editing the choices', () => {
  const d = draftFrom(settings)

  it('switches one type off and back on, leaving the others alone', () => {
    const off = toggle(d, 'trade_ideas', false)
    expect(isOn(off, 'trade_ideas')).toBe(false)
    expect(isOn(off, 'paper_buys')).toBe(false)
    const back = toggle(off, 'trade_ideas', true)
    expect(sameDraft(back, d)).toBe(true)
  })

  it('never lists a type twice', () => {
    expect(toggle(toggle(d, 'trade_ideas', false), 'trade_ideas', false).disabled).toEqual(['paper_buys', 'trade_ideas'])
  })
})

describe('quiet hours in India time', () => {
  it('handles overnight windows: start minute inside, end minute outside', () => {
    expect(inWindow('22:00', '22:00', '07:00')).toBe(true)
    expect(inWindow('03:00', '22:00', '07:00')).toBe(true)
    expect(inWindow('07:00', '22:00', '07:00')).toBe(false)
    expect(inWindow('21:59', '22:00', '07:00')).toBe(false)
    expect(inWindow('14:00', '13:00', '15:00')).toBe(true)
    expect(inWindow('15:00', '13:00', '15:00')).toBe(false)
  })

  it('describes the window plainly', () => {
    expect(quietText('22:00', '07:00')).toBe('22:00 to 07:00 (overnight)')
    expect(quietText('13:00', '15:00')).toBe('13:00 to 15:00')
  })
})

describe('what cannot be saved', () => {
  const d = draftFrom(settings)

  it('a digest inside quiet hours would never be sent', () => {
    expect(problem({ ...d, digest_enabled: true, digest_time: '23:00' })).toMatch(/outside your quiet hours/)
    expect(problem({ ...d, digest_enabled: true, digest_time: '18:00' })).toBeNull()
  })

  it('times must be real times, and a window needs two different ends', () => {
    expect(problem({ ...d, quiet_start: '' })).toMatch(/07:30/)
    expect(problem({ ...d, quiet_start: '07:00', quiet_end: '07:00' })).toMatch(/differ/)
  })

  it('says how many messages are waiting', () => {
    expect(heldText(0)).toBeNull()
    expect(heldText(1)).toMatch(/^1 message is waiting/)
    expect(heldText(3)).toMatch(/^3 messages are waiting/)
  })
})

describe('the page', () => {
  const html = render(<AlertsForm data={settings} />)
  const words = text(html)

  it('shows each switchable message with its state and a tap-to-read explanation', () => {
    expect(words).toContain('New buy ideas')
    expect(words).toContain('Practice buys')
    expect(html.match(/<details/g)?.length).toBe(2)
    expect(words).toContain('A message when a stock is worth buying.')
    expect(html).toMatch(/id="alert-trade_ideas"[^>]*checked/)
    expect(html).not.toMatch(/id="alert-paper_buys"[^>]*checked/)
  })

  it('shows the safety messages as always on, with the reason, and no switch', () => {
    expect(words).toContain('Sells and stop-losses')
    expect(words.match(/Always on/g)?.length).toBeGreaterThanOrEqual(3) // card title + one tag each
    expect(words).toContain('You may need to act quickly.')
    expect(html).not.toContain('id="alert-sells"')
  })

  it('shows quiet hours, the digest and what is waiting, in India time', () => {
    expect(words).toContain('Quiet from 22:00 to 07:00 (overnight).')
    expect(words).toContain('Daily digest')
    expect(words).toContain('2 messages are waiting to be sent')
    expect(words).toContain('never change what the bot buys or sells')
  })

  it('starts with Save off, since nothing has changed', () => {
    expect(html).toMatch(/<button[^>]*disabled=""[^>]*>Save<\/button>/)
  })

  it('loads through the shared page states', () => {
    expect(text(render(<Alerts />))).toContain('Loading your alert settings')
    expect(text(render(<Alerts />, settings))).toContain('New buy ideas')
  })
})
