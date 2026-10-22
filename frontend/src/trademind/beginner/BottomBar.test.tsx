import { renderToString } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import { SECTIONS, visiblePages } from '../menu'
import BottomBar from './BottomBar'

const render = (isOwner: boolean, activePath = '/trademind') =>
  renderToString(
    <MemoryRouter>
      <BottomBar isOwner={isOwner} activePath={activePath} />
    </MemoryRouter>,
  )
const count = (html: string) => (html.match(/<a /g) ?? []).length

describe('BottomBar', () => {
  it('shows 5 items for the owner and 4 for others', () => {
    expect(count(render(true))).toBe(5)
    expect(count(render(false))).toBe(4)
    expect(render(false)).not.toContain('Admin')
  })
  it('links each section to its first page, same as SECTIONS', () => {
    const html = render(true)
    for (const s of SECTIONS) expect(html).toContain(`href="${visiblePages(s, true)[0]!.to}"`)
  })
  it('non-owner never links to owner-only pages', () => {
    const html = render(false)
    expect(html).not.toContain('/trademind/control')
  })
  it('marks the active section', () => {
    const html = render(true, '/trademind/stock/INFY')
    const tag = html.split('<a ').find((t) => t.includes('href="/trademind/opportunities"'))
    expect(tag).toContain('aria-current="page"')
    expect((html.match(/aria-current="page"/g) ?? []).length).toBe(1)
  })
})
