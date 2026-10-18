import { renderToString } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { Glossary, Term, TermIf, TermView, WordTag, popoverPosition, termKeyAction } from './term'
import { ActionPill } from './ui'
import {
  GLOSSARY,
  GLOSSARY_GROUPS,
  HOLDING_WORDS,
  IDEA_WORDS,
  MARKET_LABEL,
  MARKET_MODES,
  isGlossaryKey,
  wordTone,
} from './vocab'
import type { GlossaryKey } from './vocab'

const text = (html: string) =>
  html
    .replace(/<!-- -->/g, '')
    .replace(/<[^>]+>/g, ' ')
    .replace(/&#x27;|&apos;/g, "'")
    .replace(/&amp;/g, '&')
    .replace(/\s+/g, ' ')

describe('glossary', () => {
  it('explains every word the app shows on a badge or banner', () => {
    const words = [...IDEA_WORDS, ...HOLDING_WORDS, ...MARKET_MODES, ...Object.keys(MARKET_LABEL)]
    for (const w of words) expect(isGlossaryKey(w), w).toBe(true)
    // Every word that gets its own colour has an explanation too.
    for (const w of ['TRADE', 'HOLD', 'WATCH', 'WAIT', 'MONITOR', 'AVOID', 'REDUCE', 'EXIT']) {
      expect(wordTone(w)).not.toBe('neutral')
      expect(isGlossaryKey(w)).toBe(true)
    }
  })

  it('keeps every explanation short and in a listed group', () => {
    const groups = new Set(GLOSSARY_GROUPS.map((g) => g.id))
    for (const [k, e] of Object.entries(GLOSSARY)) {
      expect(e.text.length, k).toBeLessThanOrEqual(240)
      expect(e.text.length, k).toBeGreaterThan(20)
      expect(groups.has(e.group), k).toBe(true)
    }
  })

  it('uses the real trading rules', () => {
    expect(GLOSSARY.target.text).toContain('8%')
    expect(GLOSSARY.stop_loss.text).toContain('4%')
    expect(GLOSSARY.half_out.text).toContain('5%')
    expect(GLOSSARY.REDUCE.text).toContain('5%')
    expect(GLOSSARY.horizon.text).toContain('15 trading days')
    expect(GLOSSARY.drawdown.text).toContain('15%')
    expect(GLOSSARY.sector.text).toContain('25%')
    expect(GLOSSARY.DEFENSIVE.text).toMatch(/two new ideas.*half/)
  })

  it('says the model score is a ranking, not a chance of winning', () => {
    expect(GLOSSARY.model_score.text).toMatch(/ranking, not a chance/)
  })

  it('lists every word on the glossary page', () => {
    const t = text(renderToString(<Glossary />))
    for (const e of Object.values(GLOSSARY)) expect(t).toContain(e.label)
  })
})

describe('Term', () => {
  it('is a closed button until tapped', () => {
    const html = renderToString(<Term k="drawdown">drawdown</Term>)
    expect(html).toMatch(/<button[^>]*type="button"/)
    expect(html).toContain('aria-expanded="false"')
    expect(html).toContain('aria-haspopup="dialog"')
    expect(text(html)).toContain('drawdown (what does this mean?)')
    expect(html).not.toContain('role="dialog"')
  })

  it('when open shows the explanation in a labelled dialog the button points to', () => {
    const html = renderToString(
      <TermView k="drawdown" id="t1" open>
        drawdown
      </TermView>,
    )
    expect(html).toContain('aria-expanded="true"')
    expect(html).toContain('aria-controls="t1"')
    expect(html).toMatch(/id="t1"[^>]*role="dialog"|role="dialog"[^>]*id="t1"/)
    expect(html).toContain('aria-labelledby="t1-title"')
    expect(text(html)).toContain(GLOSSARY.drawdown.text)
    expect(text(html)).toContain('Close')
  })

  it('closes on Escape, and only when open', () => {
    expect(termKeyAction('Escape', true)).toBe('close')
    expect(termKeyAction('Esc', true)).toBe('close')
    expect(termKeyAction('Escape', false)).toBe('none')
    expect(termKeyAction('Enter', true)).toBe('none')
  })

  it('keeps the box on a phone screen', () => {
    const vp = { width: 360, height: 640 }
    const near = popoverPosition({ left: 340, top: 100, bottom: 120 }, vp)
    expect(near.left as number).toBeGreaterThanOrEqual(16)
    expect((near.left as number) + (near.width as number)).toBeLessThanOrEqual(360 - 16)
    expect(near.top).toBe(126)
    const low = popoverPosition({ left: 10, top: 600, bottom: 620 }, vp)
    expect(low.top).toBeUndefined()
    expect(low.bottom).toBe(640 - 600 + 6)
  })

  it('makes the coloured words explain themselves', () => {
    const pill = renderToString(<ActionPill action="TRADE" />)
    expect(text(pill)).toContain('TRADE (what does this mean?)')
    expect(pill).toContain('tm-pill-trade')
    const tag = renderToString(<WordTag word="EXIT" />)
    expect(text(tag)).toContain('EXIT (what does this mean?)')
    expect(tag).toContain('tm-tag-red')
  })

  it('leaves a word the glossary does not know as plain text', () => {
    expect(renderToString(<WordTag word="SOMETHING_NEW" />)).not.toContain('<button')
    expect(renderToString(<TermIf k="SOMETHING_NEW">x</TermIf>)).not.toContain('<button')
    expect(renderToString(<TermIf k={'NORMAL' as GlossaryKey}>Normal</TermIf>)).toContain('<button')
  })
})
