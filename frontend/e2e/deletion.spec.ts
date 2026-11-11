// Account deletion screens and the Admin menu entry, in a real browser against the fake backend (support/mockApi.ts).
// Nothing real is deleted or emailed here. The server rules (who may delete, grace period, owner refused) are tested
// in backend/tests/test_account_deletion.py; this checks that each screen shows the account's CURRENT status.
import type { Page } from '@playwright/test'

import { BILLING_FAIL_TOKEN, DELETION_PASSWORD, VALID_LINK_TOKEN, mockApi } from './support/mockApi'
import { expect, openPage, test } from './support/test'

const card = (page: Page) => page.getByTestId('delete-account')

test.describe('delete my account (on the Account page)', () => {
  test('while the switch is off it says so plainly and offers no button', async ({ page }) => {
    await mockApi(page, { role: 'member', saas: {} })
    await openPage(page, '/trademind/account')
    await expect(card(page)).toHaveAttribute('data-state', 'off')
    await expect(card(page)).toContainText('not open yet')
    await expect(page.getByTestId('deletion-request')).toHaveCount(0)
  })

  test('nothing asked yet: asks for the password, refuses a wrong one, then says to check email', async ({ page }) => {
    const mock = await mockApi(page, { role: 'member', saas: { deletion: { status: null } } })
    await openPage(page, '/trademind/account')
    await expect(card(page)).toHaveAttribute('data-state', 'none')
    await expect(card(page)).toContainText('14 days')

    await page.getByTestId('deletion-request').click()
    await page.getByTestId('deletion-password').fill('wrong password')
    await page.getByRole('button', { name: 'Email me the confirm link' }).click()
    await expect(page.getByRole('dialog')).toContainText('That password is not right.')
    expect(mock.saasCalls).not.toContain('POST /account/deletion/confirm')

    await page.getByTestId('deletion-password').fill(DELETION_PASSWORD)
    await page.getByRole('button', { name: 'Email me the confirm link' }).click()
    await expect(card(page)).toHaveAttribute('data-state', 'requested')
    await expect(page.getByTestId('deletion-headline')).toHaveText('Check your email to finish')
    await expect(card(page)).toContainText('Nothing is deleted')
    await expect(page.getByTestId('deletion-request')).toHaveText('Send the link again')
  })

  test('grace period: shows the deletion date and no new request button', async ({ page }) => {
    await mockApi(page, {
      role: 'member',
      saas: { deletion: { status: 'scheduled', scheduled_for: '2026-11-25T10:00:00+00:00' } },
    })
    await openPage(page, '/trademind/account')
    await expect(card(page)).toHaveAttribute('data-state', 'scheduled')
    await expect(page.getByTestId('deletion-headline')).toContainText('25 Nov 2026')
    await expect(page.getByTestId('deletion-request')).toHaveCount(0)
  })

  test('after "keep my account" it says the account is kept and allows asking again', async ({ page }) => {
    await mockApi(page, { role: 'member', saas: { deletion: { status: 'cancelled' } } })
    await openPage(page, '/trademind/account')
    await expect(card(page)).toHaveAttribute('data-state', 'kept')
    await expect(page.getByTestId('deletion-headline')).toHaveText('Your account is kept')
    await expect(page.getByTestId('deletion-request')).toBeVisible()
  })

  test('"Download my data" saves the person own data as a file', async ({ page }) => {
    await mockApi(page, { role: 'member', saas: { deletion: { status: null } } })
    await openPage(page, '/trademind/account')
    const download = page.waitForEvent('download')
    await page.getByTestId('export-data').click()
    expect((await download).suggestedFilename()).toBe('my-trademind-data.json')
    await expect(page.getByTestId('deletion-notice')).toContainText('saved to a file')
  })
})

test.describe('the emailed links', () => {
  test('confirm link: nothing happens on load; one click starts the grace period and clears the sign-in', async ({ page }) => {
    const mock = await mockApi(page, { role: 'member', saas: { deletion: { status: 'pending' } } })
    await page.goto(`/confirm-deletion?token=${VALID_LINK_TOKEN}`)
    await expect(page.getByTestId('deletion-confirm-text')).toBeVisible()
    await expect(page).toHaveURL(/\/confirm-deletion$/) // the one-time token is taken out of the address bar
    expect(mock.saasCalls).not.toContain('POST /account/deletion/confirm')

    await page.getByTestId('deletion-go').click()
    await expect(page.getByTestId('deletion-done')).toContainText('will be deleted on 25 Nov 2026')
    expect(await page.evaluate(() => localStorage.getItem('stml.token'))).toBeNull() // no dead sign-in left behind
  })

  test('confirm link while Pro cannot be cancelled: says nothing changed and can be tried again', async ({ page }) => {
    await mockApi(page, { signedIn: false, saas: { deletion: { status: 'pending' } } })
    await page.goto(`/confirm-deletion?token=${BILLING_FAIL_TOKEN}`)
    await page.getByTestId('deletion-go').click()
    await expect(page.getByTestId('deletion-retry')).toContainText('nothing has been changed')
    await expect(page.getByTestId('deletion-go')).toBeEnabled()
  })

  test('a used, wrong or missing confirm link says so', async ({ page }) => {
    await mockApi(page, { signedIn: false, saas: { deletion: { status: 'pending' } } })
    await page.goto('/confirm-deletion?token=old')
    await page.getByTestId('deletion-go').click()
    await expect(page.getByTestId('deletion-bad')).toContainText('not valid any more')
    await page.goto('/confirm-deletion')
    await expect(page.getByTestId('deletion-bad')).toContainText('incomplete')
  })

  test('keep-my-account link works signed out, even while the deletion switch is off', async ({ page }) => {
    await mockApi(page, { signedIn: false, saas: {} })
    await page.goto(`/cancel-deletion?token=${VALID_LINK_TOKEN}`)
    await page.getByTestId('keep-go').click()
    await expect(page.getByTestId('keep-done')).toContainText('Your account is kept')
    await expect(page.getByRole('link', { name: 'Sign in' })).toBeVisible()
  })

  test('a wrong keep link says it is no longer valid', async ({ page }) => {
    await mockApi(page, { signedIn: false, saas: { deletion: { status: 'scheduled' } } })
    await page.goto('/cancel-deletion?token=old')
    await page.getByTestId('keep-go').click()
    await expect(page.getByTestId('deletion-bad')).toContainText('not valid any more')
  })
})

test.describe('Admin menu: the People console is for the admin only', () => {
  test('the owner finds People in the Admin menu and reaches the two-step setup', async ({ page }) => {
    await mockApi(page)
    await openPage(page, '/trademind')
    await page.getByTestId('nav-admin').click()
    await page.getByTestId('subnav').getByRole('link', { name: 'People' }).click()
    await expect(page).toHaveURL(/\/trademind\/people$/)
    await expect(page.getByText('Set up two-step sign-in')).toBeVisible()
  })

  test('a member has no Admin entry, and going to /trademind/people by address sends them back to Today', async ({ page }) => {
    await mockApi(page, { role: 'member' })
    await openPage(page, '/trademind')
    await expect(page.getByTestId('nav-admin')).toHaveCount(0)
    await openPage(page, '/trademind/people')
    await expect(page).toHaveURL(/\/trademind$/)
    await expect(page.getByText('Set up two-step sign-in')).toHaveCount(0)
  })
})
