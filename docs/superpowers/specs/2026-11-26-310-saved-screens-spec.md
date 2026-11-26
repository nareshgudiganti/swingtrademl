# #310 Saved screens and change digest: specification

Status: DRAFT for owner approval. Planning only: no code, no migration file. Written 2026-11-26 (IST).
Issue: #310 (Backlog, not started). Hard dependency: #260 (scan record and per-scan ranks, not built).

## 1. In plain English

Today you set the filters on Discover every visit. This feature lets you save a set of filters under a name
("5-day, large companies, pullbacks"), open it later and get exactly the same settings back. Next to your
watchlist it also adds a short "what changed" note: which stocks entered your saved screen since the last
scan, which left, and the reason, taken only from what the system stored. It never says a stock will make
money. The score is a place in a ranking, not a chance of profit.

## 2. User stories

1. As a person with an account, I save the filters I set (time window, company size, pattern, word, sector)
   under a name so I do not set them again.
2. I open a saved screen and every control shows the saved value, and the list matches those filters.
3. I see "What changed since your last visit": stocks that came in, stocks that dropped out, and one plain
   sentence each saying why.
4. I rename, replace or delete a saved screen. Deleting a screen never touches my watchlist or any trade.
5. I never see another person's saved screens.
6. If the data behind a screen is missing or old, the screen says so and shows nothing that looks more
   confident than the data allows.

## 3. Current behaviour (origin/main, verified by reading code, 2026-11-26)

- New-look Discover is `frontend/src/trademind/pages/DiscoverNew.tsx`. Filters live only in React state and
  are lost on reload: word filter `useState<DiscoverFilter>('ALL')` (line 66), sector (67), search text (68),
  table or slides layout (70; read once from `?layout=`). Only `?view=cards` and `?layout=` are in the URL
  (lines 44, 70). Nothing is saved.
- Word, sector and search filtering is a pure function, `filterIdeas`
  (`frontend/src/trademind/discoverRules.ts:50-61`); words are ALL/TRADE/WATCH/WAIT/AVOID (line 13). The sector
  list is hidden when the account cannot read the sector map (`discoverRules.ts:63-72`, `DiscoverNew.tsx:72-82`).
- The time window selector is `HorizonSelector` (`frontend/src/trademind/HorizonSelector.tsx`); the windows
  and whether each is available come from `frontend/src/trademind/horizons.ts:36-75` (1d, 5d, 15d, 30d with
  an `available` flag). A window with no supported strategy shows "unavailable", never another window's ideas
  (`HorizonSelector.tsx:1-3`).
- Company size ("cap tier") is derived from the strategy's model name:
  `backend/src/swing_trade_ml/strategies/tier.py:9-19` (large / midcap / smallcap), mirrored in
  `frontend/src/trademind/cap.ts` and returned as `cap_tier` by `GET /signals/picks`, `/signals/top-picks`,
  `/signals/track-record` (`backend/src/swing_trade_ml/api/v1/endpoints/signals.py:192, 281-302, 475`).
  Top picks has an `include_smallcap` switch, default off (`signals.py:213-215`).
- Pattern tags ("pullback in up-trend", "breakout", "base", ...) come from stored candles via
  `find_setups` (`backend/src/swing_trade_ml/brain/modules/m12_stock/setups.py:47`; labels at lines 32, 66, 78).
  #239 verified they are point-in-time and absent with too little data
  (`backend/tests/test_discover_filters_239.py:294-361`).
- #497 (merged 2026-11-25, `111581ed`) changed the buy list and top picks to count 5 completed trading
  sessions and give one row per stock (`signals.py:140-150`, `buy_fresh_since`). It did not add a saved
  filter or a new UI filter. #239's filter checks are in `backend/tests/test_discover_filters_239.py`.
- Watchlist: a per-person list exists. Table `user_watchlist_items`, one row per (person, stock), `user_id`
  foreign key to `users.id` with delete cascade, `removed_at` instead of hard delete, unique
  (`user_id`,`symbol`) (`backend/src/swing_trade_ml/db/models/user_watchlist.py:20-35`). Endpoints under
  `/me/watchlist` (`backend/src/swing_trade_ml/api/v1/endpoints/my_watchlist.py:33`): list (138), search
  (152), add (177), remove (209), edit (222), tracker (247), sold (330, 380). Limit `MAX_ITEMS = 50` (line 36).
  The person is taken from the credential, never from the body or path (`my_watchlist.py:5, 43-50`).
  It is not the bot's global watchlist (`instruments.is_watchlisted`, `db/models/market.py:48`) and nothing in
  trading reads it (`user_watchlist.py:1-8`).
- Multi-user ownership pattern to copy: a `user_id` column with `ondelete="CASCADE"` and an index, and every
  query filtered by the credential's user (`_mine`, `my_watchlist.py:130-135`). Same pattern in
  `db/models/billing.py:33`, `auth_tokens.py:20`, `audit.py:46`.
- A change view already exists for brain ideas: `GET /brain/changes` (ux11,
  `backend/src/swing_trade_ml/api/v1/endpoints/brain_changes.py:21-28`, logic in
  `backend/src/swing_trade_ml/services/brain_changes.py:146-215`). It compares the latest finished live
  nightly run with the previous trading day's, per stock: word, reasons, downgrade reason, owner overrule,
  and place in the ranking ("3rd of 120", never a raw number; `brain_changes.py:66-80, 94-134`). It never
  includes results (sealed trial, `brain_changes.py:9-12`). Frontend mapper:
  `frontend/src/trademind/changes.ts`. It is read-only and writes nothing.
- Brain ideas are already stored per run and per stock (`brain_runs`, `brain_decisions`:
  `db/models/brain.py:31, 68-110`: word, confidence, reasons, `horizon_days`, `score_source`). These are
  brain ranks, not the v1 scan ranks #260 will add.
- There is no saved-screen table, endpoint or UI anywhere (searched `backend/src` and `frontend/src`).

## 4. What a saved screen stores

Per person (never shared, never global). One row per screen. Fields:

| Field | Meaning | Allowed values |
|---|---|---|
| name | The person's label | 1-60 characters, unique per person (case-insensitive) |
| horizon | Time window | one id from `horizons.ts` (1d/5d/15d/30d). A saved window that is unavailable later is kept and shown as unavailable |
| cap_tiers | Company sizes to include | subset of large, midcap, smallcap; empty = all |
| patterns | Pattern tags to require | subset of the labels `find_setups` can return; empty = any |
| word | Decision word | ALL, TRADE, WATCH, WAIT, AVOID |
| sector | Sector | text or null (only offered when the account may read the sector map) |
| query | Search text | up to 32 characters |
| layout | table or slides | for restoring the view |
| watch_only | Limit to my watchlist | boolean |
| filters_version | Integer | so old saved screens can be read after filters change |

It does not store: results, scores, prices, profit, or any trade instruction. Limit proposal: 20 screens per
person (owner decision D3).

Restore rule: opening a screen sets every control from the stored values. A value that no longer exists
(a removed pattern label, an unavailable window) is shown as "no longer available" and that filter is NOT
silently dropped or replaced; the list then shows the empty state rather than a different list.

## 5. Screens and wording

All words plain English; detail on tap. Vocabulary is TRADE/WATCH/WAIT/AVOID (the app's labels call TRADE
"BUY": `DiscoverNew.tsx:31`; keep that).

1. Discover toolbar: a "Saved screens" menu next to the filters: choose one, "Save current filters",
   "Save as new", "Rename", "Delete". After a choice, a line: "Showing: 5-day, Large companies, Pullback in
   up-trend".
2. Save dialog: name box and a read-back of the filters being saved. Button "Save screen".
3. Change digest panel (on a saved screen and on My Watchlist): title "What changed since the last scan".
   Two lists, "Came in" and "Dropped out". Each row: stock, one sentence why, and the place in the ranking
   if stored ("3rd of 120 on 25 Nov, 7th of 118 on 26 Nov").
   Example sentences (all built from stored fields, no free text invented):
   - Came in: "Moved up to 3rd of 120 and now passes your pattern filter (pullback in up-trend)."
   - Dropped out: "The brain moved it from WATCH to WAIT. Stored reason: market is weak."
   - Dropped out: "No longer matches your pattern filter: the pullback pattern is not present on the latest candles."
4. Footer on the panel, always visible: "This is a ranking among stocks checked that night. It is not a chance of
   profit and not advice."
5. Empty and caution states: see section 8.

Never shown: profit, return, win chance, "likely to rise", or any outcome of an idea (outcomes are sealed
during the trial, `brain_changes.py:9-12`).

## 6. Change digest rules

A stock "came in" to a saved screen when, in the latest stored scan, it matches every filter and in the
previous stored scan it did not (or was not scanned). "Dropped out" is the reverse. Unchanged stocks are not
listed.

1. Derived only from stored rows: stored per-scan ranks and words (#260), stored brain decisions, and stored
   candles for the pattern test. Nothing is recomputed from live data, nothing is guessed.
2. Each entry gets exactly one primary reason from this fixed list, chosen by the first rule that matches,
   in this order: (a) data problem (stale or missing, section 8); (b) the decision word changed (from/to plus
   the stored reason text); (c) the pattern appeared or disappeared; (d) the rank crossed the screen's
   cut-off (from place to place); (e) the cap tier or window of its signal changed; (f) "Not recorded" when
   no stored field explains it. Never a guessed reason.
3. The comparison is between the two latest finished scans on trading sessions (IST date), not "yesterday"
   by clock, so weekends and holidays work. Scans from replays, failed runs, superseded runs or intraday
   runs are excluded, the same rule as `brain_changes.py:36-52`.
4. Words use only TRADE/WATCH/WAIT/AVOID; an owner overrule is shown as the overruled word with its reason,
   as in `brain_changes.py:101-103`.
5. For accounts that are not the owner, only public verdict fields are used (no account-room text), as
   `brain_changes.py:112-130` does.
6. Rank is always "place of N", never the raw score, and ranked only among scores of the same kind
   (`brain_changes.py:66-80`).
7. Wording never promises gain. A "came in" stock is described as "now matches", never "buy now".
8. The digest never alters a decision, order, size, stop or limit. Read only.

## 7. Data model proposal (NEEDS OWNER MIGRATION APPROVAL, not written)

Table `saved_screens` (one new table, no change to existing tables):

- id (integer, primary key)
- user_id (foreign key to `users.id`, on delete cascade, indexed): ownership, as `user_watchlist_items`
- name (string 60), unique with user_id, case-insensitive
- spec (JSONB): the fields in section 4
- filters_version (integer)
- last_seen_scan_id (nullable; set by "mark as seen" so "since your last visit" works)
- created_at, updated_at (timestamps, as `TimestampMixin`)

Digest data (read side, from #260, NOT created here): a scan record per run and a score/rank row per stock
per scan, with the input version used. Fields the digest needs from #260: scan id, trading session (IST
date), kind (finished live scan), per-stock symbol, horizon, score, rank, rank_of, score kind, decision word,
and the coverage and stale flags. Those tables are #260's own migration and approval (#260 items 2 and 3).
If #260 stays blocked, see owner decision D1.

Pattern membership is not stored per scan today: it is derived from stored candles at the scan's date (point
in time). To list "pattern disappeared" truthfully the digest evaluates `find_setups` at each of the two scan
dates from stored candles. No pattern column is added.

## 8. Missing or stale data (only toward caution)

- Fewer than two comparable scans: the panel says "Not enough scan history yet to say what changed" and lists
  nothing (same as `brain_changes.py:23-25`).
- Latest scan not finished, or stale or missing candles for a stock (the data check, constitution C5,
  `brain/constitution.py:10`): that stock is listed as "Data not fresh, not compared" and is never listed as
  "came in". It may be listed as "dropped out" only with the reason "Data not fresh".
- Missing rank for a stock in one scan: no rank text for that stock; the reason falls to the next rule in
  section 6.
- Missing pattern evidence (too few candles, `setups.py` MIN_BARS): the stock does not match a pattern
  filter. It is never counted as matching by default.
- Saved filter value no longer exists: show "no longer available" and the empty state (section 4).
- Window unavailable: the screen shows the existing unavailable text (`HorizonSelector.tsx:1-3`), never
  another window's ideas.
- Brain switched off or the account lacks plan access: the digest endpoint answers the same way as
  `/brain/changes` (gated, `brain_changes.py:18`); saved screens still open with the plain filters.
- Any error loading the digest: show the saved screen without the digest and a plain line, never a stale digest.
- Stale or missing data can only remove a stock from "came in" or add a caution; it can never add a stock or
  upgrade a word.

## 9. API proposal (all under the credential's user, never a user id in path or body)

- `GET /me/screens` list my screens.
- `POST /me/screens` create (body: name, spec). 409 when the name exists, 422 when over the limit or a value is invalid.
- `GET /me/screens/{id}` one screen with its spec (404 for another person's id, same as not found).
- `PATCH /me/screens/{id}` rename or replace spec.
- `DELETE /me/screens/{id}` hard delete (it holds only settings, no history to keep).
- `GET /me/screens/{id}/digest` the change digest for that screen: `{comparable, note, current, previous, came_in[], dropped_out[], not_compared[]}`, same shape and honesty as `/brain/changes`.
- `GET /me/watchlist/digest` the same digest for my watchlist (`user_watchlist_items` already stores it).
- `POST /me/screens/{id}/seen` mark the digest as seen (updates `last_seen_scan_id`).

Auth uses the same `get_principal` dependency as `my_watchlist.py:43-50`. No endpoint writes to trading tables.

## 10. Acceptance criteria (each pass or fail)

- A1. (issue) Save a screen, change the filters, open the saved screen: every control (window, company size,
  pattern, word, sector, search, layout) shows the saved value and the list equals the list those filters
  give. PASS = identical lists; FAIL = any difference.
- A2. (issue) For a stock that entered or left, the digest explains why from a stored field. PASS when every
  row has a stored reason or "Not recorded"; FAIL when any reason text is not traceable to a stored field.
- A3. Another person cannot list, read, change, delete or see the digest of my screen (404). Test with two accounts.
- A4. Deleting my account deletes my screens (cascade).
- A5. Screen names are unique per person; the limit (D3) is enforced; invalid filter values are rejected with 422.
- A6. A saved value that no longer exists is shown as "no longer available" and never substituted.
- A7. With fewer than two scans the digest says there is not enough history and lists nothing.
- A8. A stock with stale or missing data never appears under "Came in".
- A9. No digest text contains profit, return, chance, "will rise" or an outcome; ranks appear only as "place of N".
- A10. Words in the digest are only TRADE/WATCH/WAIT/AVOID (shown as BUY/WATCH/WAIT/AVOID on screen).
- A11. The digest endpoints write nothing (row counts of trading, signal and brain tables unchanged).
- A12. Excluded scans (replay, failed, superseded, intraday) never feed the digest.
- A13. Non-owner accounts get no account-room text in digest reasons.
- A14. Discover with no saved screen behaves as today (existing tests still pass).
- A15. Works at phone width; the classic Opportunities page is untouched.

## 11. Test plan

Focused tests per change (risk-based rule), run with `backend/.venv/Scripts/python.exe` and the env unset as
CLAUDE.md says, Docker Postgres up.

- Backend unit: spec validation (allowed values, limit, unique name); digest classifier for each reason in
  section 6 using fixed stored rows; order of reasons; same-kind ranking.
- Backend API: A3 two-account isolation (list, get, patch, delete, digest), A4 cascade, A5, A7, A8, A11
  (row counts before and after), A12, A13.
- Backend wording: scan every digest string for banned words (profit, return, chance, gain, "will").
- Frontend (vitest, in the style of `newLookW2.test.tsx`): A1 restore, A6 missing value, A9, digest panel
  states (loading, not enough history, normal, data not fresh). Then `npx tsc --noEmit -p .`.
- No look-ahead test: the digest for scan date D reads nothing stamped after D (IST date,
  `.astimezone(IST).date()`).
- The feature touches no trading path, so no `review-risk` run; one full regression before merge.

## 12. Dependencies

1. #260 first: scan record and per-stock per-scan rank (needs a migration and owner approval; #260 items 2
   and 3 in its 25 Nov plan). Also needs #316 approval (scan waits for candles) and the gated bugs #353 (no
   score from a stale or missing candle) and #360 (no duplicate signals on re-run), both post-trial and
   approval-gated. Without #353 and #360 the digest could show a "came in" caused by a duplicate or stale score.
2. Migration approval for `saved_screens` (section 7).
3. 5-day rankings (#260 item 4) for the 5-day window; before that, the 5d window stays "unavailable"
   (`horizons.ts`) and saved screens on it show that.
4. Reuses, no change needed: `/brain/changes` logic, `/me/watchlist`, `find_setups`, `cap_tier`.

## 13. Out of scope

Alerts or Telegram messages when a stock enters or leaves; sharing screens between people; public or
template screens; any outcome, return or backtest figure; changing scores, ranks, words or thresholds;
changing the global watchlist; any order or sizing change; classic-look Opportunities changes; the digest for
the version 1 bot's strategy signals; copying any third-party product's features or branding.

## 14. Owner decisions needed

- D1. Build the digest only after #260 lands (the issue's order, safest), OR ship saved screens first and a
  digest for brain ideas only from existing `brain_decisions` (no new rank storage)? The second gives an
  early version but covers brain ideas, not the v1 scan ranks #260 adds.
- D2. Approve the `saved_screens` table (new migration).
- D3. Maximum screens per person (proposal 20) and name length (60).
- D4. Digest for non-owner accounts: allowed with public wording only (proposal), or owner-only at first?
- D5. "Since your last visit" (per person, needs `last_seen_scan_id`) or "since the previous scan" (same for everyone)?
- D6. Is a saved screen part of the Free plan or a paid plan? (plan access rules, #335/#458)
- D7. Pattern filter: stored-date evaluation only (proposal), or evaluate live from candles when the page opens?
- D8. Wait for #353 and #360 (proposal), or accept that a duplicate or stale score could create a false "came in"?

## 15. Decisions: recommendations (26 Nov)

Status: RECOMMENDATIONS ONLY. Nothing below is decided; the owner decides each item. Written 2026-11-26 (IST)
after the owner asked: "Provide decisions D1-D8 with your recommendation for each. Identify which saved-screen
requirements can remain independent of #260. Avoid unnecessary coupling."

Checked in code on origin/main (897da862): `GET /brain/changes` is gated by `brain_route_access` as "trademind"
(`core/plans.py:132-147`) and the code has two plans, `free` and `pro` (`core/plans.py:22, 100-110`); `/me/*`
routes are allowed per plan from an explicit list (`core/plans.py:191-198`), so new `/me/screens` routes need
adding there or they stay owner-only. `brain_decisions` already holds word, reasons, `horizon_days`, downgrade
and overrule fields (`db/models/brain.py:68-110`) and also outcome fields (`outcome`, `outcome_return`, ...),
which the digest must never read (sealed trial).

| # | Question | Options | Recommendation | Why, in plain English |
|---|---|---|---|---|
| D1 | Wait for #260 before any digest? | (a) wait; (b) saved screens first, then a digest from stored brain ideas only, v1 scan ranks added later | (b) | Saving filters needs nothing from #260. A "what changed" note for brain ideas can use data already stored every night. The v1 scan ranks are a later add-on, so #260 being late blocks nothing. |
| D2 | Approve the `saved_screens` table? | yes / no / store in browser only | Yes, one small table, when the owner approves migrations | Browser-only storage would not follow the person to another phone or laptop and could not be tested for privacy. One table of settings, no history, is the smallest safe version. Not written until approved. |
| D3 | How many screens, how long a name? | 20 and 60 chars / smaller / unlimited | 10 screens, 60 characters | Nobody needs 20 saved screens; a short list stays easy to use. Easy to raise later, harder to lower once people have more. |
| D4 | Digest for people who are not the owner? | public wording for all / owner only first | Public wording for all, same as `/brain/changes` | The existing change view already hides private owner text for others. Reusing that rule adds no new risk; owner-only would need extra code to switch off later. |
| D5 | "Since your last visit" or "since the previous scan"? | per person (needs `last_seen_scan_id`) / same for everyone | "Since the previous scan" first | It needs no extra stored field and nothing to keep in step per person. "Since your last visit" can be added later if people ask. |
| D6 | Which plan gets saved screens? | Free / Pro / split | Saved filters on Free (small limit, e.g. 3); digest on Pro with the `trademind` feature | The digest reads the same brain data that `/brain/changes` already gates for Pro, so it follows the same rule with no new plan logic. Saving filters costs almost nothing, so a small free allowance helps people try it. Plan details stay with #335/#458. |
| D7 | Pattern filter: scan date or live candles? | stored date / live | Stored date for the digest, live candles for the Discover list | The digest compares two past nights, so it uses each night's own candles (no look-ahead). The list you see today behaves as Discover does now, so a restored screen gives the same list as setting the filters by hand (A1). |
| D8 | Wait for #353 and #360 before the digest? | wait / accept risk | Do not wait for the brain-idea digest; do wait for the v1 scan-rank digest | #353 (stale candle gives a score) and #360 (duplicate signals on re-run) are about v1 signals. The brain-idea digest uses only finished live runs, so a false "came in" from them is not expected there. This is an inference from reading the code, to be confirmed by a test (A12) before shipping. The v1 rank digest should wait. |

## 16. Delivery slices

The spec ties the whole feature to #260 (section 12, item 1). Only the "which stocks moved by scan rank" part
truly needs it. Two slices avoid that coupling.

### Slice A: can ship without #260

Reads: the user's own `saved_screens` rows (new table, D2), existing `/signals/picks` fields (`cap_tier`),
`horizons.ts`, `find_setups` on stored candles, `user_watchlist_items`, and for the digest the existing
`brain_runs` / `brain_decisions` through the same logic as `services/brain_changes.py`. No new rank table.

| Id | Item | Data source |
|---|---|---|
| Stories 1, 2, 4, 5, 6 | Save, restore, rename, delete, privacy, caution | `saved_screens`, existing Discover data |
| Section 4, section 5 items 1-2, section 9 `/me/screens` CRUD | Saved-screen storage and menu | `saved_screens` |
| Section 9 digest endpoints, reduced to brain ideas | Digest for a screen and for the watchlist | `brain_runs`, `brain_decisions`, `user_watchlist_items` |
| Story 3, section 5 items 3-4 | "What changed", reasons and footer, brain ideas only | `brain_decisions` (word, reasons, downgrade, overrule), brain "place of N" as `brain_changes.py:66-80` |
| Section 6 rules 1, 3-8 | Rules, with "scan" meaning a finished live nightly brain run | as `brain_changes.py:36-52` |
| Section 6 rule 2, reasons (a), (b), (c), (f) | Data problem, word changed, pattern appeared or disappeared, not recorded | `brain_decisions`, stored candles |
| A1 | Restore equals hand-set filters | existing list endpoints and front-end filter functions |
| A2 | Every digest reason traceable (brain reasons only) | `brain_decisions` |
| A3, A4, A5 | Two-account isolation, cascade, name/limit/422 | `saved_screens` |
| A6 | "No longer available", never substituted | `horizons.ts`, `find_setups` labels |
| A7 | Fewer than two runs gives "not enough history" | `brain_runs` |
| A8 | Stale or missing data never "came in" | `brain_decisions`, candles |
| A9, A10 | Banned words; four words only | digest strings |
| A11 | Digest writes nothing | all tables |
| A12 | Replay, failed, superseded, intraday runs excluded | `brain_runs` |
| A13 | No account-room text for non-owners | public fields as `brain_changes.py:112-130` |
| A14, A15 | Discover unchanged without a screen; phone width | front end |

Rule to keep in the test plan: the digest query must not select `outcome`, `outcome_return`, `max_up`,
`max_down`, `resolved_on`.

### Slice B: needs #260

| Id | Item | Data source (does not exist yet) |
|---|---|---|
| Section 6 rule 2, reason (d) | "Rank crossed the screen's cut-off", "left because rank fell" | #260 per-stock per-scan rank rows |
| Section 6 rule 2, reason (e) | Cap tier or window of a v1 signal changed | #260 per-scan rows (horizon, kind) |
| Section 5 item 3, rank wording for v1 | "7th of 118 on 26 Nov" for v1 scan scores | #260 `rank`, `rank_of`, score kind |
| Section 7 digest data, coverage and stale flags | Scan coverage (how many stocks were checked) | #260 scan record |
| Section 12 item 3 | 5-day window digest | #260 item 4 (5-day rankings) |
| A2, A7, A8, A12 applied to v1 scans | Same rules for v1 scans | #260 scan record; also #316, #353, #360 |

### Unnecessary coupling in the spec

1. Section 12 item 1 makes #260, #316, #353 and #360 a hard dependency of the whole feature. Only Slice B needs
   them. Saved screens and a brain-idea digest need none of them.
2. Section 7 says the digest reads "a scan record per run" from #260. For brain ideas the equivalent already
   exists (`brain_runs`, `brain_decisions`), and `/brain/changes` already compares two runs.
3. `last_seen_scan_id` (section 7) ties the new table to the #260 scan id. With D5 "since the previous scan" the
   column is not needed in the first version.
4. The 5-day window being "unavailable" until #260 item 4 (section 12 item 3) only affects Slice B. Saved
   screens on a window show it as unavailable by the existing rule anyway (A6).
5. Section 6 rule 2 can ship with reasons (a), (b), (c), (f) in Slice A and gain (d), (e) in Slice B without
   changing the order or the wording rules.
