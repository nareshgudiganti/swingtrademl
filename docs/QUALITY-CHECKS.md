# Quality checks: what runs automatically, and what to do when one fails

Tracker section `qa` (System Atlas). Each check below says when it runs, what it protects,
and what to do if it goes red.

## Secret scan (qa3): `.github/workflows/secret-scan.yml`

- **When:** every push to any branch, every pull request.
- **What:** gitleaks scans the whole git history for keys, tokens and passwords. Rules and the
  allowlist of known-fake values: `.gitleaks.toml`. Output is redacted.
- **If it fails:** the repo is public, so treat the secret as already stolen.
  1. Rotate it first (new Kite API secret, new Telegram bot token, new `JWT_SECRET_KEY`, …).
  2. Only then remove it from the code. Deleting the line does not remove it from history.
  3. If it is a fake value used in a test, add that exact value (never a path or whole rule) to
     the allowlist in `.gitleaks.toml`, with a comment saying why it is fake.

## Library audit (qa4): `.github/workflows/dependency-audit.yml` + `.github/dependabot.yml`

- **When:** Mondays 09:00 IST, and on pull requests that change dependencies.
- **What:** pip-audit on a fresh backend install (same as the Docker build); npm audit on the
  frontend lockfile. Dependabot opens weekly update PRs (never merged automatically).
- **Fails on:** any backend finding not on the ignore list; high/critical issues in frontend
  code that ships to the browser. Build/test-only tools are shown but do not fail the run.
- **Ignore list:** in the workflow header, each with a reason. Re-check monthly; remove an entry
  as soon as a fixed version exists.
- **Known, not yet fixed (2026-10-18):** vitest 3 (test runner only) needs vitest 5, which needs
  a Vite major upgrade; @capacitor/cli (phone build tool). Neither ships to prod.

## Browser and accessibility tests (qa1, qa10): `frontend/e2e/` + job `e2e` in `.github/workflows/test.yml`

- **When:** every push to `develop` and every pull request (same triggers as the other test jobs).
- **How it runs:** Playwright builds the app into `frontend/dist-e2e/`, serves it with `vite preview`
  and drives Chromium. There is **no backend**: every `/api/v1/...` call is answered by
  `frontend/e2e/support/mockApi.ts` from the JSON in `frontend/e2e/fixtures/` (paper mode, made-up
  values). Anything not in the fixtures gets a 404, and every change request (buy, sell, halt, …)
  gets a 403, so a test can never place or change anything, and nothing can reach production.
- **Journeys (qa1, `journeys.spec.ts`):**
  1. Sign in with username and password (and a wrong password, and logging out).
  2. Today: market mode, idea counts, holdings needing attention, top ideas, insights.
  3. Stock page: opened by tapping a top idea; chart, brain decision, tabs.
  4. Portfolio: all four tabs open, each with the right Paper / Real strip.
  5. Admin: the owner opens all six Admin pages; a non-owner sees no Admin, no Testing and no
     real-money tab, and owner addresses send them back.
  6. Phone width (390 x 844): no sideways scrolling on the main pages; the menu and page tabs
     work by tapping.
  Any uncaught JavaScript error on a page fails the test.
- **Accessibility (qa10, `a11y.spec.ts`):** axe (WCAG 2.0/2.1 A and AA, plus 2.2 AA) scans sign-in,
  Today, a stock page, the four Portfolio tabs and Admin (Control), once with the browser in light
  mode and once in dark. It **fails on serious or critical problems** (for example poor contrast or
  a button with no name). At phone width, the section menu, page tabs and top-bar buttons must be at
  least 24 x 24 px (WCAG 2.2 target size), and the icon-only account button must have a name a
  screen reader can read. The TradeMind screens have one dark theme whatever the browser setting,
  so the light and dark scans differ only where the browser's own colours apply.
- **Known debt:** `frontend/e2e/a11y-allowlist.json` lists problems that exist today, each with the
  rule, the page and a TODO. Listed problems do not fail the check; anything new does. When the run
  prints an `allowlist-entry-now-passes` note, delete that entry. Today (2026-10-18) it holds two
  colour-contrast items (the blue Sign in button, and grey table headings), left for the owner to
  approve because fixing them changes how the app looks.
- **Run it locally** (in `frontend/`): `npx playwright install chromium` once, then `npm run e2e`.
  `npm run e2e:typecheck` checks the test code's types. One spec: `npx playwright test e2e/a11y.spec.ts`.
- **If it fails:** the list output names the step and the missing text, or the axe rule, element
  and contrast numbers. If a screen changed on purpose, update the text the test looks for (or the
  fixture). If the screen now calls a new endpoint, add it to `mockApi.ts` with a fixture. Do not
  add a new axe problem to the allowlist to make CI green; fix it, or ask the owner first.
  Nothing (traces, screenshots, reports) is uploaded from CI: the repo is public.
- **Known issue found while writing these tests (not fixed here, app behaviour):** for the owner,
  loading a `/trademind/...` address directly (bookmark, refresh) lands on Today instead of that
  page, because the app decides before the account status has arrived. The tests therefore load
  Today first and then move inside the app (`openPage` in `e2e/support/test.ts`).
