# Manual test plan — Swing Trade ML / TradeMind

**Tester:** Vijay (or assignee)  
**Default environment:** local — `http://localhost:5173` (UI), `http://localhost:8000` (API)  
**Optional:** production read-only smoke with owner permission — `https://swingtrademl.com`

**Result codes:** `PASS` | `FAIL` | `BLOCKED` (could not run) | `SKIP` (not in scope today) | `N/A`

Record **FAIL** with: test ID, what you did, expected, actual, screenshot path (if any), browser (Chrome/Edge).

---

## S — Daily smoke (run every working day, ~15 minutes)

| ID | Area | Steps | Pass criteria |
|----|------|--------|----------------|
| S-01 | Stack | `docker compose ps` — api, worker, postgres, redis, frontend up; api/worker healthy | All required containers up |
| S-02 | API health | Open `http://localhost:8000/api/v1/health` | JSON `status` ok |
| S-03 | UI load | Open `http://localhost:5173` | Login or dashboard loads, no white screen |
| S-04 | Auth | Log in (account created for you) | Lands on dashboard or TradeMind home |
| S-05 | Mode | Settings or `/api/v1/status` — trading mode | Shows **paper**, not live |
| S-06 | Brain gate | If `BRAIN_ENABLED=true`: open `/trademind` or `/brain` | Not 404; banner or brain UI visible |
| S-07 | No console crash | Browser devtools → Console on home page | No uncaught errors on first load |

---

## A — Authentication and accounts

| ID | Steps | Pass criteria |
|----|--------|----------------|
| A-01 | **Sign up** (local only, if `ALLOW_SIGNUP=true`): new username + password 8+ chars | Success; redirected in app; `users` row exists (owner can verify) |
| A-02 | **Sign up disabled**: with `ALLOW_SIGNUP=false`, try signup | Clear error; no login |
| A-03 | **Wrong password** | Generic “incorrect” message; no hint which field failed |
| A-04 | **Logout** → login again | Session restored |
| A-05 | **Google** (if configured): allowed email | Login works; blocked email shows “not permitted” |
| A-06 | **Kite** (optional, owner approval): `/api/v1/auth/kite/login` flow | Success page; does **not** create dashboard user by itself |

---

## C — Classic app (v1 navigation)

Use main nav after login. Owner account sees all tabs; plan-gated tabs may be hidden on Free — note in report.

| ID | Page | Steps | Pass criteria |
|----|------|--------|----------------|
| C-01 | Dashboard `/dashboard` | Open page | Loads; numbers or empty states; no crash |
| C-02 | Strategies `/strategies` | List strategies; find **TradeMind brain** | Row visible; state shown (active/inactive) |
| C-03 | Holdings `/holdings` | Open | Table or empty state with explanation |
| C-04 | Capital `/capital` | Open | Loads |
| C-05 | Safety `/safety` | Open | Limits / halt info readable |
| C-06 | Scan Results `/scans` | Open (if in menu) | Loads or feature gate message |
| C-07 | Reports `/reports` | Open (if in menu) | Loads or feature gate |
| C-08 | Settings `/settings` | Open via URL | Watchlist / sync section visible |
| C-09 | Mobile width | Resize to &lt;800px or phone | Bottom nav works; no overlapping unusable UI |

**Do not** run destructive settings (delete all data, live mode) without owner sign-off.

---

## P — Manual paper positions (TradeMind)

These trades live under **Portfolio → Testing**. The existing **Positions** tab is unchanged. They are **not** the bot’s automatic buys (those stay on **Overview**).

**Buy only from Discover → Watchlist.** There is no separate Paper testing page.

**Before you start (owner must set this once):**

- `TRADING_MODE=paper`
- `PAPER_TESTER_ENABLED=true`
- Restart the API after changing `.env`

If **Watchlist** is missing under Discover, mark every P case **BLOCKED** and write “not an owner login, or API not restarted”. Do not treat that as a product bug.

**Free and Pro do not get Watchlist or this Positions book.** Owner only.

**Rules**

- **Buy** only on Watchlist. **Paper sell** only on Testing. No OTP.
- Do **not** expect these stocks on **Overview** (bot/brain book).
- Company size (Large / Mid / Small) is **your** choice at buy time.

| ID | Steps | Pass criteria |
|----|--------|----------------|
| P-01 | TradeMind → **Portfolio → Testing** | New tab next to Positions. The old Positions page is still there and unchanged |
| P-02 | **Discover → Watchlist** | Same style of table as Opportunities. Only watchlist symbols. Each row has **Buy** |
| P-03 | On one row: **Buy**, quantity 1, **Large**, **Paper buy** | Success. **Portfolio → Testing** shows that stock as Large. **Positions** does not |
| P-04 | Open **Portfolio → Overview** (and classic `/portfolio` if you use it) | That manual stock is **not** listed as a bot holding |
| P-05 | On **Testing**, click **Paper sell** and confirm | Position disappears; cash / profit banked updates; no crash |
| P-06 | On **Testing**, switch Daily, then Weekly, then Monthly | Closed sale shows under Daily (count ≥ 1, net shown). Empty weeks/months are OK |
| P-07 | Buy two different symbols the same day (different sizes if you want) | Both open; sector list (if shown) lists them; best/worst cards only when one is up and one is down |
| P-08 | Next calendar day (or later the same week): buy one more, sell one still open | Old open stock still there until you sell; new buy appears; reports still count earlier sales |

**What to report if it breaks:** button does nothing, buy error text, stock showed up on Overview, numbers that jump to zero after refresh.

---

## T — TradeMind UI (`/trademind/*`)

| ID | Page | Steps | Pass criteria |
|----|------|--------|----------------|
| T-01 | Home `/trademind` | Open | Banner (NORMAL/DEFENSIVE/NO NEW TRADES) + plain English |
| T-02 | AI `/trademind/ai` | Open | Content loads; no infinite spinner &gt;30s |
| T-03 | Opportunities | Open list | Cards or honest empty state |
| T-04 | Market | Open | Market context loads |
| T-05 | Stock detail | Click one symbol from opportunities/home | Detail page; TRADE/WATCH/WAIT/AVOID or holding word |
| T-06 | Positions | Open | Positions or empty |
| T-07 | My Holdings | Open | Aligns with classic holdings or explains gap |
| T-08 | Records | Open | History or empty |
| T-09 | Learn | Open | Learning UI; no fake numbers labeled as real |
| T-10 | Control | Open | Read-only checks OK; **do not** change prod stage |
| T-11 | Go-live | Open | Shows **Practice (shadow)**; counter “N of 30” if applicable |
| T-12 | Risk | Open | Risk copy readable |
| T-13 | System | Open | System/status info |
| T-14 | Setup | Open | Setup checklist or connection hints |
| T-15 | Navigation | Click each top section (Decisions, Discover, …) | No dead links in menu |

**Expected caution (not a fail):** banner **NO NEW TRADES** or mostly **WAIT** when market data is stale — brain is being safe. Note it in the report under “Observations”.

---

## B — Brain (owner console `/brain` and API)

Use [../brain/TESTING.md](../brain/TESTING.md) Level 1–2 in detail. Summary:

| ID | Steps | Pass criteria |
|----|--------|----------------|
| B-01 | `/brain` UI | Latest nightly date ≈ last trading day | |
| B-02 | One stock card | Word + reasons in English | |
| B-03 | Stage card | **Practice (shadow)** unless owner changed | |
| B-04 | Strategies | TradeMind brain **Active** | |
| B-05 | No Approve in shadow | Ideas list has **no** Approve button | Correct for M18 shadow |
| B-06 | API `GET /brain/health` (logged in or API key) | `last_run.status` done or explainable; failures low | |
| B-07 | API `GET /brain/runs/latest?kind=nightly` | `status: done`, `live: true` when run exists | |

---

## K — Data and jobs (local, when stack has data)

Run only if owner said candles/models are set up.

| ID | Steps | Pass criteria |
|----|--------|----------------|
| K-01 | `docker compose exec api swingtrade status` | Command succeeds; summary readable |
| K-02 | After 16:00 IST (India) | Next-day report: worker ran brain job (owner logs or `/brain/health`) | |
| K-03 | Settings → sync/backfill (if exposed) | Progress or clear error — do not run huge backfill without owner |

---

## R — Regression / safety

| ID | Steps | Pass criteria |
|----|--------|----------------|
| R-01 | Open API docs `/docs` | Swagger loads |
| R-02 | Call protected route without token | 401 |
| R-03 | Brain strategy off → brain run behavior | Owner documents expected; note if ideas stop |
| R-04 | Refresh browser on `/trademind` | Still logged in (token valid) |
| R-05 | Two tabs same user | No corrupt state |

---

## W — Weekly (once per week, ~2 hours)

| ID | Activity |
|----|----------|
| W-01 | Full pass: all **T** and **B** cases |
| W-02 | One **C** screen deep test (forms, filters, sort) |
| W-03 | Cross-browser: Chrome + Edge |
| W-04 | Re-test all **FAIL** from last 7 daily reports |
| W-05 | Read `docs/architecture/CURRENT-STATE.md` — verify known issues still documented |

---

## Bug report format (for each FAIL)

```text
ID: T-05
Severity: High | Medium | Low
Environment: local | prod
Commit: abc1234
Steps: ...
Expected: ...
Actual: ...
Screenshot: reports/assets/2026-10-06-t05.png (optional)
```

**Severity guide**

- **High:** crash, wrong money/risk display, auth bypass, data loss
- **Medium:** wrong label, broken nav, API 500 on core page
- **Low:** typo, cosmetic, edge case

---

## Test rotation (suggested Mon–Fri)

| Day | Focus sections |
|-----|----------------|
| Mon | S + A + C (dashboard, strategies) |
| Tue | S + T (Decisions + Discover) |
| Wed | S + T (Portfolio + Performance) **or** S + **P** (Paper testing) when the flag is on |
| Thu | S + B + K |
| Fri | S + W weekly items + report summary for the week |
