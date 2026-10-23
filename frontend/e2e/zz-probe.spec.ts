import { test } from '@playwright/test'
import { mockApi } from './support/mockApi'
import { openPage } from './support/test'
test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true })
for (const path of ['/trademind', '/trademind/opportunities', '/trademind/stock/INFY', '/trademind/positions']) {
  test(`probe ${path}`, async ({ page }) => {
    await mockApi(page)
    await openPage(page, path)
    await page.waitForTimeout(800)
    const out = await page.evaluate(() => {
      const vw = document.documentElement.clientWidth
      const rows: string[] = [`scroll=${document.documentElement.scrollWidth} client=${vw}`]
      for (const el of Array.from(document.querySelectorAll('body *'))) {
        const r = el.getBoundingClientRect()
        let clipped = false
        for (let p = el.parentElement; p; p = p.parentElement) { const o = getComputedStyle(p).overflowX; if (o !== 'visible') { clipped = true; break } }
        if (!clipped && r.width > 0 && r.right > vw) rows.push(`${Math.round(r.right)} ${el.tagName.toLowerCase()}.${typeof el.className === 'string' ? el.className.replace(/\s+/g, '.') : ''} "${(el.textContent || '').trim().slice(0, 40)}"`)
      }
      return rows.slice(0, 12)
    })
    console.log('PROBE', path, '\n  ' + out.join('\n  '))
  })
}
