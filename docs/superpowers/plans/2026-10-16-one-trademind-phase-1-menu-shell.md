# One TradeMind app, Phase 1 (menu shell) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Status: for review. Not approved to build or deploy.** Deployment is a separate approval and a separate owner push.

**Goal:** replace TradeMind's six flat menu sections with the five approved sections (**Today · Discover ·
Portfolio · Insights · Admin**), and add the two safety nets later phases depend on: menu tests and a
classic-feature parity check. **No page changes. No URL changes. No backend changes.**

**Architecture:** the menu data and the "which section is this path in" logic move out of
`TradeMindApp.tsx` into one small pure module, `trademind/menu.ts`, which can be tested. `TradeMindApp.tsx`
renders from it. The route table is untouched, so every existing URL keeps working. A dependency-free script
lists which backend calls each classic screen makes that no TradeMind page makes.

**Tech stack:** TypeScript, React 19, react-router-dom 7, Vite 6. New dev-only dependency: `vitest` (needs
your yes, Task 1).

**Spec:** `docs/superpowers/specs/2026-10-16-one-trademind-design.md` (sections 1, 6, 8, 9).

## Global Constraints

- **Frontend only.** No file under `backend/` changes. No file under `brain/`, `strategies/`, `workers/`,
  `db/`, `alembic/`, `infra/` changes. No API contract changes, no migration.
- **No route path is added, removed or renamed in `TradeMindApp.tsx`'s `<Routes>` table**, and no element in it
  changes. Only the menu around it changes.
- **Classic screens and `App.tsx` are not touched.**
- Section ids and labels (exact): `today` "Today", `discover` "Discover", `portfolio` "Portfolio",
  `insights` "Insights", `admin` "Admin" (owner only).
- Owner-only pages keep their existing gates (the route elements already redirect non-owners; the menu only
  hides what a non-owner cannot open).
- Plain English in every label; no new jargon.
- Run frontend checks from `frontend/`: `npm run typecheck`, `npm run build`, and (after Task 1) `npm test`.
  Do not run prettier on existing files. Match the surrounding code style.
- **Git:** branch `feature/one-trademind-phase-1` off `origin/main`, in its own worktree. Do not push, merge or
  deploy without the owner. Commits end with the attribution line in force for the session.
- Deploys only after 16:30 IST on weekdays (or at weekends), by the owner's push.

## Review Focus

The input classes and failure modes most likely to bite a real user, with the test that pins each:

1. **A page no section lists** (it still works by URL but has no menu entry, as happened once with a new page).
   Pinned by `menu.test.ts` "every route in TradeMindApp.tsx belongs to a section".
2. **A non-owner sees an Admin entry, or the owner-only sub-row flashes on a direct URL.** Pinned by
   "a non-owner never sees an owner-only section or page" and "a non-owner on an admin path resolves to Today".
3. **Wrong section highlighted on parameter routes** (`/trademind/stock/INFY`, `/positions/INFY`, `/ai/INFY`).
   Pinned by "parameter routes resolve to their section".
4. **A section whose first page is owner-only links to a page the viewer cannot open.** Pinned by "a section's
   link is its first page visible to this viewer".
5. **Five items plus the chips overflow a phone-width top bar.** Pinned by browser check B6 (Task 5).

---

## File map

| File | Responsibility |
|---|---|
| `frontend/src/trademind/menu.ts` (new) | the five sections, the owner-only rules, `findSection`, `resolveSection`, `visibleSections`, `visiblePages` |
| `frontend/src/trademind/menu.test.ts` (new) | menu contract tests |
| `frontend/src/trademind/TradeMindApp.tsx` (edit) | render the top bar and sub-row from `menu.ts`; the `<Routes>` table is untouched |
| `frontend/scripts/classic-parity.mjs` (new) | compute and check classic-vs-TradeMind API parity; CLI |
| `frontend/scripts/classic-parity-allowlist.json` (new) | every classic call with no TradeMind equivalent, each explained |
| `frontend/scripts/classic-parity.test.mjs` (new) | tests for the script, plus a guard on the real tree |
| `frontend/package.json`, `package-lock.json` (edit) | `vitest` dev dependency and `"test"` script (Task 1, needs approval) |
| `frontend/vitest.config.ts` (new) | minimal test config |
| `.github/workflows/test.yml` (edit) | run `npm test` in the frontend job (Task 1, needs approval) |

---

### Task 0: Branch and base

**Files:** none.

- [ ] **Step 1: Confirm the Observatory is on `main`, then create the worktree**

```bash
cd "D:/machine learning/swing-trade-bot"
git fetch origin
git merge-base --is-ancestor a7adcaa origin/main && echo "Observatory is in main" || echo "STOP: deploy/merge the Observatory first"
git worktree add .claude/worktrees/one-app-p1 -b feature/one-trademind-phase-1 origin/main
```

Expected: "Observatory is in main". If not, stop: this plan edits `TradeMindApp.tsx`, which the Observatory also
edits, and must start from a `main` that already contains it.

- [ ] **Step 2: Record the baseline**

```bash
cd .claude/worktrees/one-app-p1/frontend
# node_modules is not in a new worktree: link the main checkout's, and remove the link at the end of the task.
powershell -NoProfile -Command "New-Item -ItemType Junction -Path 'node_modules' -Target 'D:\machine learning\swing-trade-bot\frontend\node_modules' | Out-Null"
node node_modules/typescript/bin/tsc --noEmit -p . ; echo "baseline typecheck exit=$?"
```

Expected: exit 0. Keep the junction for Tasks 1-5; delete it only with
`powershell -NoProfile -Command "(Get-Item 'node_modules').Delete()"` (never `rm -rf`, which would follow the
link and delete the main checkout's modules). Task 1 installs into the main checkout's `node_modules` through
this link, so it needs your approval first.

---

### Task 1: Test tooling (needs owner approval)

**Files:**
- Modify: `frontend/package.json`, `frontend/package-lock.json`
- Create: `frontend/vitest.config.ts`
- Modify: `.github/workflows/test.yml` (frontend job)

**Why:** the frontend has no unit-test tooling. The menu is the thing every later phase edits, so it needs a
test that fails when a page loses its menu entry. `vitest` is dev-only and has no effect on the shipped app.
**If you decline it,** Tasks 2 and 4 keep their tests as Node scripts run by hand and by the browser checks, and
nothing guards the menu in CI. I'd rather not.

- [ ] **Step 1: Install**

```bash
cd frontend
npm install --save-dev vitest@^3.0.0
```

- [ ] **Step 2: Add the script and a minimal config**

In `package.json` `"scripts"` add `"test": "vitest run"`. Create `vitest.config.ts`:

```ts
import { defineConfig } from 'vitest/config'

// Kept apart from vite.config.ts so tests do not load the PWA plugin.
export default defineConfig({
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts', 'scripts/**/*.test.mjs'],
  },
})
```

- [ ] **Step 3: Run with no tests yet**

Run: `npm test`
Expected: exits non-zero with "No test files found" until Task 2 adds one. That is fine; do not add
`passWithNoTests`.

- [ ] **Step 4: CI step (needs approval, one line)**

In `.github/workflows/test.yml`, in the `frontend` job, after the `Typecheck` step add:

```yaml
      - name: Unit tests
        working-directory: frontend
        run: npm test
```

- [ ] **Step 5: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/vitest.config.ts .github/workflows/test.yml
git commit -m "Frontend: vitest (dev only) and a Unit tests step in CI"
```

(Commit after Task 2 if you want CI to stay green between commits, since an empty `npm test` fails. Either order
is acceptable; CI is not run on a feature branch until it is pushed.)

---

### Task 2: The menu module and its tests

**Files:**
- Create: `frontend/src/trademind/menu.ts`
- Test: `frontend/src/trademind/menu.test.ts`

**Interfaces:**
- Produces:
  - `type Page = { to: string; label: string; end?: boolean; ownerOnly?: boolean }`
  - `type SectionId = 'today' | 'discover' | 'portfolio' | 'insights' | 'admin'`
  - `type Section = { id: SectionId; label: string; pages: Page[]; also?: string[]; ownerOnly?: boolean }`
  - `SECTIONS: Section[]` (five, in order), `ADMIN_SECTION: Section`
  - `matches(path: string, to: string, end?: boolean): boolean`
  - `findSection(path: string): Section | undefined`
  - `resolveSection(path: string, owner: boolean): Section` (falls back to Today)
  - `visibleSections(owner: boolean): Section[]`
  - `visiblePages(section: Section, owner: boolean): Page[]`

- [ ] **Step 1: Write the failing tests**

`frontend/src/trademind/menu.test.ts`:

```ts
import { describe, expect, it } from 'vitest'

import appSource from './TradeMindApp.tsx?raw'
import { ADMIN_SECTION, SECTIONS, findSection, resolveSection, visiblePages, visibleSections } from './menu'

// Every TradeMind path that existed before the redesign, and the section it now belongs to.
const EXPECTED: Record<string, string> = {
  '/trademind': 'today',
  '/trademind/dashboard': 'today',
  '/trademind/opportunities': 'discover',
  '/trademind/watchlist': 'discover',
  '/trademind/market': 'discover',
  '/trademind/ai': 'discover',
  '/trademind/positions': 'portfolio',
  '/trademind/testing': 'portfolio',
  '/trademind/holdings': 'portfolio',
  '/trademind/portfolio': 'portfolio',
  '/trademind/records': 'insights',
  '/trademind/learn': 'insights',
  '/trademind/control': 'admin',
  '/trademind/golive': 'admin',
  '/trademind/risk': 'admin',
  '/trademind/system': 'admin',
  '/trademind/setup': 'admin',
  '/trademind/observatory': 'admin',
}
const PARAM_ROUTES: Record<string, string> = {
  '/trademind/stock/INFY': 'discover',
  '/trademind/positions/INFY': 'portfolio',
  '/trademind/ai/INFY': 'discover',
}

describe('the five sections', () => {
  it('are Today, Discover, Portfolio, Insights, Admin, in that order', () => {
    expect(SECTIONS.map((s) => s.label)).toEqual(['Today', 'Discover', 'Portfolio', 'Insights', 'Admin'])
    expect(SECTIONS.map((s) => s.id)).toEqual(['today', 'discover', 'portfolio', 'insights', 'admin'])
  })

  it('show five to the owner and four (no Admin) to anyone else', () => {
    expect(visibleSections(true).map((s) => s.id)).toEqual(['today', 'discover', 'portfolio', 'insights', 'admin'])
    expect(visibleSections(false).map((s) => s.id)).toEqual(['today', 'discover', 'portfolio', 'insights'])
  })

  it('list no page twice', () => {
    const all = SECTIONS.flatMap((s) => s.pages.map((p) => p.to))
    expect(new Set(all).size).toBe(all.length)
    expect(all.every((to) => to.startsWith('/trademind'))).toBe(true)
  })

  it('make Admin the only owner-only section, holding the same pages the avatar menu lists', () => {
    expect(SECTIONS.filter((s) => s.ownerOnly).map((s) => s.id)).toEqual(['admin'])
    expect(ADMIN_SECTION.id).toBe('admin')
  })
})

describe('where every existing page lives', () => {
  it.each(Object.entries(EXPECTED))('%s is in %s', (path, id) => {
    expect(findSection(path)?.id).toBe(id)
    expect(resolveSection(path, true).id).toBe(id)
  })

  it.each(Object.entries(PARAM_ROUTES))('parameter routes resolve to their section: %s', (path, id) => {
    expect(findSection(path)?.id).toBe(id)
  })

  it('does not treat a longer path as a prefix of "/trademind" itself', () => {
    expect(findSection('/trademind/dashboard')?.id).toBe('today')
    expect(findSection('/trademind/nothing-here')).toBeUndefined()
  })

  it('every route in TradeMindApp.tsx belongs to a section', () => {
    const routes = [...appSource.matchAll(/<Route\s+path="([^"]+)"/g)].map((m) => m[1]!)
    const concrete = routes
      .filter((r) => r !== '/trademind' && r !== '*')
      .map((r) => `/trademind/${r.replace(/:[A-Za-z]+/g, 'X')}`)
    concrete.push('/trademind')
    expect(concrete.length).toBeGreaterThan(15) // the route table was actually read
    const orphans = concrete.filter((p) => findSection(p) === undefined)
    expect(orphans).toEqual([])
  })
})

describe('what a non-owner can see', () => {
  const ownerOnlyPaths = ['/trademind/watchlist', '/trademind/testing', '/trademind/holdings', ...SECTIONS.filter((s) => s.ownerOnly).flatMap((s) => s.pages.map((p) => p.to))]

  it('never includes an owner-only section or page', () => {
    for (const sec of visibleSections(false)) {
      expect(sec.ownerOnly).toBeFalsy()
      for (const page of visiblePages(sec, false)) expect(ownerOnlyPaths).not.toContain(page.to)
    }
  })

  it('a non-owner on an admin path resolves to Today, never to the hidden Admin section', () => {
    for (const p of ['/trademind/control', '/trademind/golive', '/trademind/observatory']) {
      expect(resolveSection(p, false).id).toBe('today')
    }
  })

  it("a section's link is its first page visible to this viewer", () => {
    for (const owner of [true, false]) {
      for (const sec of visibleSections(owner)) {
        const first = visiblePages(sec, owner)[0]
        expect(first, `${sec.id} has a visible page for owner=${owner}`).toBeDefined()
        expect(first!.ownerOnly && !owner).toBeFalsy()
      }
    }
  })

  it('keeps the pages a non-owner could open before the redesign', () => {
    const shown = new Set(visibleSections(false).flatMap((s) => visiblePages(s, false).map((p) => p.to)))
    for (const p of ['/trademind', '/trademind/dashboard', '/trademind/opportunities', '/trademind/market', '/trademind/ai', '/trademind/positions', '/trademind/portfolio', '/trademind/records', '/trademind/learn']) {
      expect(shown.has(p), p).toBe(true)
    }
  })
})
```

- [ ] **Step 2: Run, expect FAIL**

Run: `cd frontend && npm test`
Expected: FAIL, "Failed to resolve import ./menu".

- [ ] **Step 3: Implement `menu.ts`**

```ts
// The TradeMind menu: five sections (owner-approved 2026-10-16), the pages in each, and which of them only
// the owner may open. Pure data and functions, so it can be tested; TradeMindApp.tsx renders from it.
// The route table in TradeMindApp.tsx is separate and unchanged: this only decides where a page appears
// in the menu and which section is highlighted.

export type Page = { to: string; label: string; end?: boolean; ownerOnly?: boolean }
export type SectionId = 'today' | 'discover' | 'portfolio' | 'insights' | 'admin'
export type Section = { id: SectionId; label: string; pages: Page[]; also?: string[]; ownerOnly?: boolean }

export const SECTIONS: Section[] = [
  {
    id: 'today',
    label: 'Today',
    pages: [
      { to: '/trademind', label: 'Today', end: true },
      { to: '/trademind/dashboard', label: 'Swing Picks' },
    ],
  },
  {
    id: 'discover',
    label: 'Discover',
    pages: [
      { to: '/trademind/opportunities', label: 'Opportunities' },
      { to: '/trademind/watchlist', label: 'Watchlist', ownerOnly: true },
      { to: '/trademind/market', label: 'Market' },
      { to: '/trademind/ai', label: 'Why (AI)' },
    ],
    also: ['/trademind/stock'],
  },
  {
    id: 'portfolio',
    label: 'Portfolio',
    pages: [
      { to: '/trademind/positions', label: 'Positions' },
      { to: '/trademind/testing', label: 'Testing', ownerOnly: true },
      { to: '/trademind/holdings', label: 'My Holdings', ownerOnly: true },
      { to: '/trademind/portfolio', label: 'Overview' },
    ],
  },
  {
    id: 'insights',
    label: 'Insights',
    pages: [
      { to: '/trademind/records', label: 'Records' },
      { to: '/trademind/learn', label: 'Learn' },
    ],
  },
  {
    id: 'admin',
    label: 'Admin',
    ownerOnly: true,
    pages: [
      { to: '/trademind/control', label: 'Control' },
      { to: '/trademind/golive', label: 'Go-live' },
      { to: '/trademind/risk', label: 'Risk' },
      { to: '/trademind/system', label: 'System' },
      { to: '/trademind/setup', label: 'Setup' },
      { to: '/trademind/observatory', label: 'Observatory' },
    ],
  },
]

export const ADMIN_SECTION: Section = SECTIONS.find((s) => s.id === 'admin')!

export function matches(path: string, to: string, end?: boolean): boolean {
  return end ? path === to || path === `${to}/` : path === to || path.startsWith(`${to}/`)
}

/** The section a path belongs to, or undefined when no section lists it. */
export function findSection(path: string): Section | undefined {
  return SECTIONS.find(
    (s) => s.pages.some((p) => matches(path, p.to, p.end)) || s.also?.some((a) => matches(path, a)),
  )
}

/** The section to highlight. A non-owner never lands in an owner-only section: they get Today. */
export function resolveSection(path: string, owner: boolean): Section {
  const found = findSection(path)
  if (!found || (found.ownerOnly && !owner)) return SECTIONS[0]!
  return found
}

export function visibleSections(owner: boolean): Section[] {
  return SECTIONS.filter((s) => owner || !s.ownerOnly)
}

export function visiblePages(section: Section, owner: boolean): Page[] {
  return section.pages.filter((p) => owner || !p.ownerOnly)
}
```

- [ ] **Step 4: Run, expect PASS**

Run: `npm test`
Expected: all menu tests pass. If "every route ... belongs to a section" fails, the failure lists the orphan
path: that is the test doing its job, so add the page to the right section, not to the test's allow-list.

- [ ] **Step 5: Mutation check (not committed)**

Remove `/trademind/observatory` from `ADMIN_SECTION.pages`: the "every route belongs to a section" test must
fail naming it. Restore. Change `ownerOnly: true` on Watchlist to nothing: "never includes an owner-only page"
must fail. Restore. Record both results in the PR description.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/trademind/menu.ts frontend/src/trademind/menu.test.ts
git commit -m "TradeMind menu: five sections as data, with tests (no page or URL changes)"
```

---

### Task 3: Render the top bar from the menu

**Files:**
- Modify: `frontend/src/trademind/TradeMindApp.tsx`

**Interfaces:**
- Consumes: `ADMIN_SECTION`, `resolveSection`, `visibleSections`, `visiblePages` from `./menu`.

The `<Routes>` table and every page element stay exactly as they are. Do this as four edits, in order.

- [ ] **Step 1: Replace the local menu definitions**

Delete everything from the line `type Page = { to: string; label: string; end?: boolean }` through the end of
`function sectionFor(...) { ... }` (the `Page`/`Section` types, `SECTIONS`, `OWNER_SECTION`, `matches`, `sectionFor`),
keeping the file's top comment. Add to the imports:

```tsx
import { ADMIN_SECTION, resolveSection, visiblePages, visibleSections } from './menu'
```

- [ ] **Step 2: Replace the section computation inside `TradeMindApp`**

Replace this block:

```tsx
  const visibleSections = SECTIONS.map((s) => {
    ...
    return s
  })
  const location = useLocation()
  const found = sectionFor(location.pathname)
  // The row under the bar lists only pages this account can open.
  const section = visibleSections.find((s) => s.label === found.label) ?? found
```

with:

```tsx
  const location = useLocation()
  const sections = visibleSections(ownerConsole)
  const section = resolveSection(location.pathname, ownerConsole)
  // The row under the bar lists only pages this account can open.
  const pages = visiblePages(section, ownerConsole)
```

- [ ] **Step 3: Replace the nav, avatar menu and sub-row**

Top nav:

```tsx
        <nav className="tm-nav" aria-label="Sections">
          {sections.map((sec) => (
            <Link
              key={sec.id}
              to={visiblePages(sec, ownerConsole)[0]!.to}
              className={sec.id === section.id ? 'active' : ''}
              data-testid={`nav-${sec.id}`}
            >
              {sec.label}
            </Link>
          ))}
        </nav>
```

Avatar menu (keep every existing shortcut; only the source of the list changes):
replace `OWNER_SECTION.pages.map(` with `ADMIN_SECTION.pages.map(`.

Sub-row:

```tsx
      {pages.length > 1 && (
        <nav className="tm-subnav" aria-label={`${section.label} pages`} data-testid="subnav">
          {pages.map((pg) => (
            <NavLink key={pg.to} to={pg.to} end={pg.end} className={({ isActive }) => (isActive ? 'active' : '')}>
              {pg.label}
            </NavLink>
          ))}
        </nav>
      )}
```

- [ ] **Step 4: Update the file comment, then verify**

Change the "One final app in five sections" comment (it moved with the deleted block) to a one-line pointer:
`// The menu lives in ./menu.ts (five sections: Today, Discover, Portfolio, Insights, Admin).`

Run:

```bash
cd frontend
node node_modules/typescript/bin/tsc --noEmit -p . ; echo "typecheck exit=$?"
npm test
node node_modules/vite/bin/vite.js build --outDir "<scratchpad>/dist_p1" --emptyOutDir
git diff --stat -- frontend/src/trademind/TradeMindApp.tsx
git diff -- frontend/src/trademind/TradeMindApp.tsx | grep -c "^[+-].*<Route"
```

Expected: typecheck exit 0; tests pass; build succeeds; the last command prints **0** (no `<Route` line changed).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/trademind/TradeMindApp.tsx
git commit -m "TradeMind: top bar and sub-row rendered from the five-section menu (routes unchanged)"
```

---

### Task 4: Classic-feature parity script and allow-list

**Files:**
- Create: `frontend/scripts/classic-parity.mjs`, `frontend/scripts/classic-parity-allowlist.json`
- Test: `frontend/scripts/classic-parity.test.mjs`

**Interfaces:**
- Produces:
  - `computeParity(srcDir: string): { page: string; lines: number; calls: string[]; gaps: string[] }[]`
    (`gaps` = calls this classic page makes that no file under `trademind/` makes)
  - `checkAllowlist(parity, allowlist, { strict }): { unexplained: {page, call}[]; planned: {page, call, task}[]; ok: boolean }`
  - CLI: `node scripts/classic-parity.mjs [--check] [--strict] [--json]`

Allow-list statuses: `v2` (not built until v2), `deferred` (waits for a stated event), `separate_app` (Finance),
`planned` (to be built; names the task). `--check` fails on any **unexplained** gap. `--strict` also fails on any
**planned** entry: that is the Phase 6 deletion gate.

- [ ] **Step 1: Write the failing tests**

`frontend/scripts/classic-parity.test.mjs`:

```js
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

import { checkAllowlist, computeParity } from './classic-parity.mjs'

function tree(files) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'parity-'))
  for (const [rel, text] of Object.entries(files)) {
    const full = path.join(root, rel)
    fs.mkdirSync(path.dirname(full), { recursive: true })
    fs.writeFileSync(full, text)
  }
  return root
}

describe('computeParity', () => {
  it('lists the calls a classic page makes that no TradeMind file makes', () => {
    const src = tree({
      'pages/Safety.tsx': 'api.riskEvents(); api.safetyState()',
      'pages/Other.tsx': 'api.status()',
      'trademind/pages/Control.tsx': 'api.safetyState(); api.status()',
    })
    const rows = Object.fromEntries(computeParity(src).map((r) => [r.page, r]))
    expect(rows.Safety.gaps).toEqual(['riskEvents'])
    expect(rows.Other.gaps).toEqual([])
    expect(rows.Safety.calls).toEqual(['riskEvents', 'safetyState'])
  })

  it('counts a call made anywhere under trademind/ (hooks included)', () => {
    const src = tree({ 'pages/A.tsx': 'api.x()', 'trademind/live.ts': 'api.x()' })
    expect(computeParity(src)[0].gaps).toEqual([])
  })
})

describe('checkAllowlist', () => {
  const parity = [
    { page: 'Capital', lines: 1, calls: ['riskEvents'], gaps: ['riskEvents'] },
    { page: 'Models', lines: 1, calls: ['train', 'mystery'], gaps: ['train', 'mystery'] },
    { page: 'Finance', lines: 1, calls: ['a', 'b'], gaps: ['a', 'b'] },
  ]
  const allow = {
    Capital: { riskEvents: { status: 'planned', task: 'oa2' } },
    Models: { train: { status: 'v2' } },
    Finance: { '*': { status: 'separate_app' } },
  }

  it('fails on a gap nobody explained', () => {
    const r = checkAllowlist(parity, allow, { strict: false })
    expect(r.unexplained).toEqual([{ page: 'Models', call: 'mystery' }])
    expect(r.ok).toBe(false)
  })

  it('passes when every gap is explained, treating planned as acceptable', () => {
    const ok = checkAllowlist(parity, { ...allow, Models: { train: { status: 'v2' }, mystery: { status: 'deferred' } } }, { strict: false })
    expect(ok.unexplained).toEqual([])
    expect(ok.planned).toEqual([{ page: 'Capital', call: 'riskEvents', task: 'oa2' }])
    expect(ok.ok).toBe(true)
  })

  it('strict mode (the deletion gate) fails while anything is still only planned', () => {
    const a = { ...allow, Models: { train: { status: 'v2' }, mystery: { status: 'deferred' } } }
    expect(checkAllowlist(parity, a, { strict: true }).ok).toBe(false)
    const done = { ...a, Capital: { riskEvents: { status: 'v2' } } }
    expect(checkAllowlist(parity, done, { strict: true }).ok).toBe(true)
  })

  it('a "*" entry explains every call of a page (the separate Finance app)', () => {
    expect(checkAllowlist(parity.slice(2), allow, { strict: true }).ok).toBe(true)
  })

  it('rejects an unknown status, so a typo cannot hide a gap', () => {
    const r = checkAllowlist(parity.slice(0, 1), { Capital: { riskEvents: { status: 'later' } } }, { strict: false })
    expect(r.ok).toBe(false)
    expect(r.unexplained).toEqual([{ page: 'Capital', call: 'riskEvents' }])
  })
})

describe('the real tree', () => {
  it('has no unexplained classic-only call (new gaps must be added to the allow-list on purpose)', () => {
    const here = path.dirname(fileURLToPath(import.meta.url))
    const parity = computeParity(path.join(here, '..', 'src'))
    const allow = JSON.parse(fs.readFileSync(path.join(here, 'classic-parity-allowlist.json'), 'utf8'))
    expect(parity.length).toBeGreaterThan(10)
    const r = checkAllowlist(parity, allow, { strict: false })
    expect(r.unexplained).toEqual([])
  })
})
```

- [ ] **Step 2: Run, expect FAIL** (`Cannot find module ./classic-parity.mjs`)

Run: `cd frontend && npm test`

- [ ] **Step 3: Implement the script**

`frontend/scripts/classic-parity.mjs`:

```js
// Which backend calls do the classic screens make that no TradeMind page makes?
// A reproducible check, not a judgement: every gap must be explained in classic-parity-allowlist.json,
// and the Phase 6 deletion gate (--strict) also refuses anything still only "planned".
// Usage: node scripts/classic-parity.mjs [--check] [--strict] [--json]

import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const CALL = /\bapi\.([A-Za-z0-9_]+)/g
const EXPLAINED = new Set(['v2', 'deferred', 'separate_app', 'planned'])

function walk(dir) {
  if (!fs.existsSync(dir)) return []
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const full = path.join(dir, e.name)
    return e.isDirectory() ? walk(full) : [full]
  })
}

function callsIn(file) {
  return new Set([...fs.readFileSync(file, 'utf8').matchAll(CALL)].map((m) => m[1]))
}

export function computeParity(srcDir) {
  const pagesDir = path.join(srcDir, 'pages')
  const trademind = new Set()
  for (const f of walk(path.join(srcDir, 'trademind')).filter((f) => /\.tsx?$/.test(f))) {
    for (const c of callsIn(f)) trademind.add(c)
  }
  return fs
    .readdirSync(pagesDir)
    .filter((f) => f.endsWith('.tsx'))
    .sort()
    .map((f) => {
      const file = path.join(pagesDir, f)
      const calls = [...callsIn(file)].sort()
      return {
        page: f.replace(/\.tsx$/, ''),
        lines: fs.readFileSync(file, 'utf8').split('\n').length,
        calls,
        gaps: calls.filter((c) => !trademind.has(c)),
      }
    })
}

export function checkAllowlist(parity, allowlist, { strict = false } = {}) {
  const unexplained = []
  const planned = []
  for (const row of parity) {
    const entries = allowlist[row.page] ?? {}
    for (const call of row.gaps) {
      const e = entries[call] ?? entries['*']
      if (!e || !EXPLAINED.has(e.status)) unexplained.push({ page: row.page, call })
      else if (e.status === 'planned') planned.push({ page: row.page, call, task: e.task ?? '' })
    }
  }
  return { unexplained, planned, ok: unexplained.length === 0 && !(strict && planned.length > 0) }
}

function main() {
  const here = path.dirname(fileURLToPath(import.meta.url))
  const parity = computeParity(path.join(here, '..', 'src'))
  const allow = JSON.parse(fs.readFileSync(path.join(here, 'classic-parity-allowlist.json'), 'utf8'))
  const strict = process.argv.includes('--strict')
  const result = checkAllowlist(parity, allow, { strict })
  if (process.argv.includes('--json')) console.log(JSON.stringify({ parity, ...result }, null, 2))
  else {
    for (const r of parity) console.log(`${r.page.padEnd(16)} ${String(r.lines).padStart(5)} lines ${String(r.calls.length).padStart(3)} calls | gaps: ${r.gaps.join(', ') || 'none'}`)
    console.log(`\nunexplained: ${result.unexplained.length}  planned: ${result.planned.length}  strict: ${strict}  => ${result.ok ? 'OK' : 'FAIL'}`)
    for (const u of result.unexplained) console.log(`  unexplained: ${u.page}.${u.call}`)
    if (strict) for (const p of result.planned) console.log(`  still planned: ${p.page}.${p.call} (${p.task})`)
  }
  if (process.argv.includes('--check') || strict) process.exit(result.ok ? 0 : 1)
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) main()
```

- [ ] **Step 4: Create the allow-list from the 2026-10-16 run (spec section 6)**

`frontend/scripts/classic-parity-allowlist.json`:

```json
{
  "Finance": { "*": { "status": "separate_app", "note": "Personal Finance stays its own app (owner, 2026-10-04)" } },
  "Capital": { "riskEvents": { "status": "planned", "task": "oa2" } },
  "Safety": { "riskEvents": { "status": "planned", "task": "oa2" } },
  "Dashboard": {
    "predict": { "status": "v2", "note": "'Score now' is dropped until v2" },
    "strategySignals": { "status": "planned", "task": "oa5", "note": "read-only per-strategy signal list in Discover" }
  },
  "Models": {
    "activateModel": { "status": "v2" },
    "train": { "status": "v2" },
    "predictions": { "status": "planned", "task": "oa11", "note": "model accuracy history, Insights" }
  },
  "PlanHome": {
    "picks": { "status": "planned", "task": "oa10", "note": "only used when the plans switch is on (off on prod)" },
    "topPicks": { "status": "planned", "task": "oa10" }
  },
  "PlansManager": { "*": { "status": "planned", "task": "oa3", "note": "Admin > Plans" } },
  "Strategies": {
    "createStrategy": { "status": "v2" },
    "deleteStrategy": { "status": "v2" },
    "strategyTypes": { "status": "v2" },
    "scanAll": { "status": "deferred", "task": "oa4", "note": "after the trial; never creates trades on its own" },
    "positionsAllBooks": { "status": "planned", "task": "oa6", "note": "Portfolio > Overview, books labelled, never summed" }
  }
}
```

- [ ] **Step 5: Run, expect PASS**

Run: `npm test` then `node scripts/classic-parity.mjs --check` (exit 0) and `node scripts/classic-parity.mjs --strict`
(**exit 1**, listing what is still planned: that is correct today and becomes the Phase 6 gate).

- [ ] **Step 6: Commit**

```bash
git add frontend/scripts
git commit -m "Classic feature parity script and allow-list (reproduces the 2026-10-16 matrix; strict mode is the deletion gate)"
```

---

### Task 5: Browser acceptance, scope guard and screenshots

**Files:** none committed (scripts live in the scratchpad). Use the `browser-automation` skill against a local
API and Vite dev server, as in the Observatory run. Local only: paper mode, Telegram off, no Kite login.

Local setup (do not print secrets): start the API from this worktree with explicit environment variables and the
local development database (as the Observatory run did), and Vite on port **5173** (the API's CORS allows only
5173). Mint a local owner token for an existing superuser and, for B3, create then delete a throwaway non-owner
user in the local development database. Stop both servers and remove the `node_modules` link afterwards.

- [ ] **Step 1: DOM checks (each is an assertion, not a screenshot)**

| ID | Check |
|---|---|
| B1 | Owner: the top bar shows exactly Today, Discover, Portfolio, Insights, Admin, in that order |
| B2 | Owner: clicking each section opens its first page; the sub-row lists exactly that section's pages; Admin's sub-row lists Control, Go-live, Risk, System, Setup, Observatory |
| B3 | Non-owner: four sections, no Admin; none of Watchlist, Testing, My Holdings, Observatory in any sub-row |
| B4 | **Every old URL still opens its page** as the owner (client-side navigation from the menu, because a deep link to an owner page redirects before the account loads in the existing app): `/trademind`, `/dashboard`, `/opportunities`, `/watchlist`, `/market`, `/stock/INFY`, `/ai`, `/ai/INFY`, `/positions`, `/positions/INFY`, `/testing`, `/holdings`, `/portfolio`, `/records`, `/learn`, `/control`, `/golive`, `/risk`, `/system`, `/setup`, `/observatory` |
| B5 | On each of those pages the highlighted top-bar section equals the expected one (the `EXPECTED` table in `menu.test.ts`) |
| B6 | At 390 px width: no horizontal page scroll; all five section links visible or reachable; chips do not overlap the nav |
| B7 | Console: no errors and no failed requests on the pages above (except deliberate ones) |
| B8 | Classic URLs unchanged: `/dashboard`, `/strategies`, `/safety` still load for the owner when the brain is off, or redirect exactly as on `main` (compare with a run of the baseline build) |

- [ ] **Step 2: Baseline equivalence**

On the baseline worktree (`origin/main`) and on this branch, run the same B4 script and compare the list of
pages reached and the page titles: **identical**. Record both outputs.

- [ ] **Step 3: Scope guard**

```bash
git diff --name-only origin/main...HEAD
```

Expected, exactly: `frontend/src/trademind/menu.ts`, `menu.test.ts`, `TradeMindApp.tsx`,
`frontend/scripts/classic-parity*`, `frontend/package.json`, `frontend/package-lock.json`,
`frontend/vitest.config.ts`, `.github/workflows/test.yml`, plus this plan and the spec. Anything under
`backend/`, `App.tsx`, `pages/`, or any other `trademind/pages/` file fails the guard.

- [ ] **Step 4: Screenshots** of the owner view (top bar plus sub-row for each of the five sections) and a phone
width view. Keep them outside the repo.

---

### Task 6: Independent review and report

- [ ] **Step 1:** Build the review package and dispatch one fresh, read-only reviewer on the most capable model
with this plan's Review Focus verbatim. Fix Critical and Important findings test-first, in one pass.
- [ ] **Step 2:** Final gates: `npm run typecheck`, `npm run build`, `npm test`,
`node scripts/classic-parity.mjs --check`, the full backend suite unchanged and green, the scope guard.
- [ ] **Step 3:** Report to the owner: test results, the B1-B8 results, the screenshots, rulings, deferred
minors. **Do not push to `main`, merge or deploy.** Ask for deployment approval separately.

---

## Self-review

- **Spec coverage:** section 1 (five sections) Task 2-3; section 6 (parity, deletion gate) Task 4 and the strict
  mode; section 8 acceptance for oa1 (five to owner, four to non-owner, every URL opens and highlights) Task 2 and
  Task 5 B1-B5; oa17 (menu tests, parity script) Tasks 2 and 4. Phases 2-6 are deliberately out of scope.
- **No placeholders:** every code step shows the code; the only deferred values are the local scratchpad path and
  the owner's approvals.
- **Type consistency:** `Section`, `Page`, `SectionId`, `findSection`, `resolveSection`, `visibleSections`,
  `visiblePages` and `ADMIN_SECTION` are defined in Task 2 and used with the same names in Task 3; `computeParity`
  and `checkAllowlist` are defined in Task 4 and used with the same shapes in its tests and CLI.
- **Open items needing the owner before building:** the `vitest` dev dependency and the one-line CI step (Task 1);
  whether the avatar menu keeps its shortcuts (this plan keeps them, unchanged).
