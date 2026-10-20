// ux6: the tax-records export on My Holdings > Real-money report (owner only), against the fake backend.
import type { Page } from '@playwright/test'

import realAccount from './fixtures/real-account.json' with { type: 'json' }
import { mockApi } from './support/mockApi'
import { expect, openPage, test } from './support/test'

const CSV = '﻿Stock,Bought on,Sold on,Shares\r\nSAMPLEA,2025-04-07,2025-06-02,10\r\n'

/** The shared fixture has no saved trades, which hides the report; give it one, and serve the CSV file. */
async function withHistory(page: Page) {
  const report = { ...realAccount.report, records: { total_fills: 2, first_at: '2025-04-07T04:30:00Z', last_at: '2025-06-02T04:30:00Z' } }
  await page.route(
    (url) => url.pathname === '/api/v1/real-report',
    (route) => route.fulfill({ contentType: 'application/json', body: JSON.stringify(report) }),
  )
  await page.route(
    (url) => url.pathname === '/api/v1/real-report/tax.csv',
    (route) => route.fulfill({ contentType: 'text/csv; charset=utf-8', body: CSV }),
  )
}

test('the owner can pick a financial year, download the tax file and open a printable page', async ({ page }) => {
  await mockApi(page)
  await withHistory(page)
  await openPage(page, '/trademind/holdings')
  await page.getByRole('tab', { name: 'Real-money report' }).click()

  const card = page.getByTestId('tax-export')
  await expect(page.getByText('For your tax records')).toBeVisible()
  await expect(card.getByText('Short-term gain or loss after charges')).toBeVisible()
  await expect(card.getByText(/no buy on record/)).toBeVisible()
  await expect(card.getByText(/ask a tax adviser/)).toBeVisible()

  const picker = page.getByTestId('tax-year')
  const asked = page.waitForRequest((r) => r.url().includes('/api/v1/real-report/tax?year=2024-25'))
  await picker.selectOption('2024-25')
  await asked

  const download = page.waitForEvent('download')
  await page.getByTestId('tax-download').click()
  const file = await download
  expect(file.suggestedFilename()).toBe('real-trades-tax-2024-25.csv')

  const popup = page.waitForEvent('popup')
  await page.getByTestId('tax-print').click()
  const printable = await popup
  await expect(printable.getByRole('heading', { name: /Real trades for tax/ })).toBeVisible()
  await expect(printable.getByText('Buy details missing — not in the totals')).toBeVisible()
})
