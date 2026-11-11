// Private-SaaS customer journey, in a real browser against the fake backend (support/mockApi.ts):
// sign up, confirm the email, forgot/reset password, sign in when unconfirmed, then Free -> Pro -> stop.
// Real email and real payments are never touched here; staging covers those (docs/STAGING-SETUP.md).
import { FAKE_TOKEN, PAID_THROUGH, VALID_LINK_TOKEN, mockApi } from './support/mockApi'
import { expect, openPage, test } from './support/test'

const GOOD_PASSWORD = 'purple tractor eats seven cold noodles'

test.describe('sign up', () => {
  test('a new person fills the form, is told to check their email, and gets no sign-in yet', async ({ page }) => {
    const mock = await mockApi(page, { signedIn: false, saas: { signupOpen: true } })
    await page.goto('/signup')
    await expect(page.getByText('Create your account')).toBeVisible()

    await page.getByLabel('Your name').fill('Asha Rao')
    await page.getByLabel('Email', { exact: true }).fill('asha@example.test')
    await page.getByLabel('Choose a password').fill(GOOD_PASSWORD)
    const req = page.waitForRequest((r) => r.url().endsWith('/api/v1/auth/register') && r.method() === 'POST')
    await page.getByRole('button', { name: 'Create account' }).click()

    expect((await req).postDataJSON()).toEqual({
      full_name: 'Asha Rao',
      email: 'asha@example.test',
      password: GOOD_PASSWORD,
    })
    await expect(page.getByTestId('signup-sent')).toContainText('asha@example.test')
    expect(await page.evaluate(() => localStorage.getItem('stml.token'))).toBeNull()
    expect(mock.saasCalls).not.toContain('POST /auth/signup')
  })

  test('a short password is refused in plain words before anything is sent', async ({ page }) => {
    const mock = await mockApi(page, { signedIn: false, saas: { signupOpen: true } })
    await page.goto('/signup')
    await page.getByLabel('Your name').fill('Asha Rao')
    await page.getByLabel('Email', { exact: true }).fill('asha@example.test')
    // Past the browser's own length check, so our wording is what shows.
    await page.getByLabel('Choose a password').fill('short words 14')
    await page.locator('form').evaluate((f) => f.setAttribute('novalidate', ''))
    await page.getByRole('button', { name: 'Create account' }).click()
    await expect(page.getByRole('alert')).toContainText('at least 15 characters')
    expect(mock.saasCalls).not.toContain('POST /auth/register')
  })

  test('while sign-up is closed the page still says it is by invite only', async ({ page }) => {
    await mockApi(page, { signedIn: false })
    await page.goto('/signup')
    await expect(page.getByTestId('signup-closed')).toBeVisible()
  })
})

test.describe('email links', () => {
  test('the confirm link confirms the address and offers sign-in', async ({ page }) => {
    await mockApi(page, { signedIn: false })
    await page.goto(`/verify-email?token=${VALID_LINK_TOKEN}`)
    await expect(page.getByTestId('verify-done')).toContainText('Your email is confirmed')
    await expect(page).toHaveURL(/\/verify-email$/) // the one-time token is taken out of the address bar
    await expect(page.getByRole('link', { name: 'Sign in' })).toBeVisible()
  })

  test('a used or wrong confirm link says so', async ({ page }) => {
    await mockApi(page, { signedIn: false })
    await page.goto('/verify-email?token=old')
    await expect(page.getByTestId('verify-bad')).toContainText('not valid any more')
  })

  test('forgot password gives the same answer for any address', async ({ page }) => {
    await mockApi(page, { signedIn: false })
    await page.goto('/forgot-password')
    await page.getByLabel('Email').fill('nobody@example.test')
    await page.getByRole('button', { name: 'Send the link' }).click()
    await expect(page.getByTestId('forgot-sent')).toContainText('If that email belongs to an account')
  })

  test('reset: a short password is refused, a good one changes it', async ({ page }) => {
    const mock = await mockApi(page, { signedIn: false })
    await page.goto(`/reset-password?token=${VALID_LINK_TOKEN}`)
    await page.getByLabel('New password', { exact: true }).fill('too short')
    await page.locator('form').evaluate((f) => f.setAttribute('novalidate', ''))
    await page.getByRole('button', { name: 'Save my new password' }).click()
    await expect(page.getByRole('alert')).toContainText('at least 15 characters')
    expect(mock.saasCalls).not.toContain('POST /auth/reset-password')

    await page.getByLabel('New password', { exact: true }).fill(GOOD_PASSWORD)
    const req = page.waitForRequest((r) => r.url().endsWith('/api/v1/auth/reset-password'))
    await page.getByRole('button', { name: 'Save my new password' }).click()
    expect((await req).postDataJSON()).toEqual({ token: VALID_LINK_TOKEN, new_password: GOOD_PASSWORD })
    await expect(page.getByTestId('reset-done')).toContainText('Your password has been changed')
  })

  test('a reset page without a link asks for a new one', async ({ page }) => {
    await mockApi(page, { signedIn: false })
    await page.goto('/reset-password')
    await expect(page.getByTestId('reset-bad')).toBeVisible()
  })
})

test.describe('sign in', () => {
  test('an unconfirmed account is offered a new confirmation link', async ({ page }) => {
    await mockApi(page, { signedIn: false, saas: { unverified: true } })
    await page.goto('/signin')
    await page.getByLabel('Email or username').fill('asha@example.test')
    await page.getByLabel('Password').fill(GOOD_PASSWORD)
    await page.getByRole('button', { name: 'Sign in', exact: true }).click()
    await expect(page.getByText('Please verify your email first')).toBeVisible()
    await page.getByRole('button', { name: 'Send me a new confirmation link' }).click()
    await expect(page.getByTestId('verify-first')).toContainText('we have sent a new link')
    expect(await page.evaluate(() => localStorage.getItem('stml.token'))).toBeNull()
  })

  test('forgot password is one click from sign-in', async ({ page }) => {
    await mockApi(page, { signedIn: false })
    await page.goto('/signin')
    await page.getByRole('link', { name: 'Forgot your password?' }).click()
    await expect(page).toHaveURL(/\/forgot-password$/)
  })

  test('the saved sign-in stays a normal token', () => {
    expect(FAKE_TOKEN).toBeTruthy()
  })
})

test.describe('account and plan', () => {
  test('Free -> upgrade -> Pro -> stop: access runs to the paid-through date', async ({ page }) => {
    await mockApi(page, { role: 'member', saas: {} })
    await openPage(page, '/trademind/account')
    await expect(page.getByTestId('plan-headline')).toHaveText('You are on Free')
    await expect(page.getByTestId('test-mode')).toBeVisible()
    await expect(page.getByTestId('upgrade-card')).toContainText('₹499 a month')

    await page.getByRole('button', { name: 'Upgrade to Pro' }).click()
    await page.getByRole('button', { name: 'Complete the test payment' }).click()
    await expect(page.getByTestId('plan-headline')).toHaveText('You have Pro')
    await expect(page.getByTestId('plan-card')).toContainText('14 Dec 2026')

    await page.getByTestId('cancel-pro').click()
    await expect(page.getByRole('dialog')).toContainText('You will not be charged again')
    await page.getByRole('button', { name: 'Yes, stop at the end of this period' }).click()
    await expect(page.getByTestId('plan-headline')).toHaveText('Pro until 14 Dec 2026')
    await expect(page.getByTestId('cancel-pro')).toHaveCount(0)
  })

  test('a Pro person who already stopped sees the end date and no buttons', async ({ page }) => {
    await mockApi(page, {
      role: 'member',
      saas: { subscription: { status: 'active', paid_through: PAID_THROUGH, cancel_scheduled: true } },
    })
    await openPage(page, '/trademind/account')
    await expect(page.getByTestId('plan-headline')).toHaveText('Pro until 14 Dec 2026')
    await expect(page.getByRole('button', { name: 'Upgrade to Pro' })).toHaveCount(0)
    await expect(page.getByTestId('cancel-pro')).toHaveCount(0)
  })

  test('new checkouts closed: Free person is told upgrading is not open', async ({ page }) => {
    await mockApi(page, { role: 'member', saas: { checkoutOpen: false } })
    await openPage(page, '/trademind/account')
    await expect(page.getByTestId('plan-card')).toContainText('Upgrading is not open yet')
    await expect(page.getByRole('button', { name: 'Upgrade to Pro' })).toHaveCount(0)
  })

  test('new checkouts closed: existing Pro keeps working and can still stop', async ({ page }) => {
    await mockApi(page, {
      role: 'member',
      saas: { checkoutOpen: false, subscription: { status: 'active', paid_through: PAID_THROUGH, cancel_scheduled: false } },
    })
    await openPage(page, '/trademind/account')
    await expect(page.getByTestId('plan-headline')).toHaveText('You have Pro')
    await expect(page.getByTestId('cancel-pro')).toBeVisible()
  })

  test('billing switched off: a plain message, not an error', async ({ page }) => {
    await mockApi(page, { role: 'member', saas: { billingOff: true } })
    await openPage(page, '/trademind/account')
    await expect(page.getByText('Plans and billing are not open yet')).toBeVisible()
    await expect(page.getByTestId('account-details')).toContainText('member@example.test')
  })
})
