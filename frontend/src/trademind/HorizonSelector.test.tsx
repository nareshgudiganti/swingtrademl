import { renderToString } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { HorizonSelector, HorizonUnavailable } from './HorizonSelector'
import { HORIZONS, horizonById } from './horizons'

const noop = () => {}
const text = (html: string) => html.replace(/<!-- -->/g, '').replace(/<[^>]+>/g, ' ').replace(/&#x27;|&apos;/g, "'").replace(/\s+/g, ' ')

describe('HorizonSelector', () => {
  it('offers all five horizons as tabs, with the chosen one selected', () => {
    const html = renderToString(<HorizonSelector value="15d" onChange={noop} />)
    expect(html.match(/role="tab"/g)?.length).toBe(5)
    expect(html.match(/aria-selected="true"/g)?.length).toBe(1)
    expect(html).toMatch(/aria-selected="true"[^>]*data-horizon="15d"|data-horizon="15d"[^>]*aria-selected="true"/)
  })

  it('shows the validation label beside 15 days and "No supported trading strategy" on the others', () => {
    const t = text(renderToString(<HorizonSelector value="15d" onChange={noop} />))
    expect(t).toContain('Experimental, unproven')
    expect(t.match(/No supported trading strategy/g)?.length).toBe(4)
    expect(t).not.toMatch(/Validated/)
  })

  it('shows a count only for a supported horizon', () => {
    const t = text(renderToString(<HorizonSelector value="15d" onChange={noop} variant="pills" count={12} />))
    expect(t).toContain('15 Days (12)')
    for (const h of HORIZONS.filter((x) => !x.available)) expect(t).toContain(`${h.title} (—)`)
  })
})

describe('HorizonUnavailable', () => {
  it('says no trading idea is available and shows no idea rows', () => {
    const html = renderToString(<HorizonUnavailable horizon={horizonById('30d')} />)
    expect(text(html)).toContain('No supported trading strategy for 30 Days')
    expect(text(html)).toMatch(/no trading idea/i)
    expect(html).not.toContain('<table')
  })

  it('on 5 days, separates the research predictions from a trading plan', () => {
    const t = text(renderToString(<HorizonUnavailable horizon={horizonById('5d')} />))
    expect(t).toMatch(/research/i)
    expect(t).toMatch(/not a trading plan/i)
  })

  it('never offers 15-day ideas under another horizon name', () => {
    for (const h of HORIZONS.filter((x) => !x.available)) {
      const t = text(renderToString(<HorizonUnavailable horizon={h} />))
      expect(t).not.toMatch(/15 Days tab|15-day ideas/)
    }
  })
})
