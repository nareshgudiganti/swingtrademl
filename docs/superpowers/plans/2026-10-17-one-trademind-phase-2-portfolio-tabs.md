# One TradeMind, Phase 2: Portfolio with four tabs (plan for owner review)

**Spec:** `docs/superpowers/specs/2026-10-16-one-trademind-design.md` section 4, tasks oa6 and bx2. Phase 1 is live (PR #5).
**Status:** plan only. Nothing is built until the owner approves it. No push, merge or deploy without separate approval.

## Goal
The Portfolio section shows four clearly named tabs, and every money figure says whether it is **Paper** or **Real**. No total ever mixes the two books. Nothing is deleted and no URL changes.

## What exists today (checked on `main` 9531be3)
- Phase 1 already shows four pages under Portfolio: Positions, Testing (owner), My Holdings (owner), Overview. So Phase 2 is **naming, labelling, gating and verification**, not a rewrite.
- `MyHoldings.tsx` (957 lines) carries the real-order screens and safety checks. **It is not edited.**
- Overview calls `summary`, `positions` (`book=bot`), `equityCurve` and `riskLimits`. Whether each of these is paper-only on the server has to be proven by a test (Task 1), not assumed.
- The Testing page already shows a "switched off" card when paper testing is off; the sub-row still lists it.

## Scope (frontend only; no backend, brain, trading, order, sizing, stop or limit change)
| # | Change | Files |
|---|---|---|
| 1 | Prove which book each Overview figure comes from (tests that fail if a real-book number reaches Overview) | new `portfolio-books.test.tsx`, read-only backend probe in the PR notes |
| 2 | Tab names per spec: **Bot (paper)**, **My Zerodha (real)**, **Testing**, **Overview** (same URLs) | `menu.ts`, `menu.test.ts` |
| 3 | A `BookBadge` ("Paper" / "Real") in the trademind ui kit, shown in each tab's header and beside every total | `ui.tsx`, the four pages (header line only) |
| 4 | Testing tab hidden from the tab row while paper testing is off (the direct URL keeps its existing "switched off" card) | `TradeMindApp.tsx` passes one flag into `visiblePages` |
| 5 | My Zerodha tab keeps its existing owner gate; the stricter real-account gate is a separate change (see Known issue 1 of PR #5) | none |
| 6 | Browser verification against the pre-change app: same data, same actions, new labels only | scratch scripts + screenshots |

## Not in Phase 2
Real BUY/SELL changes, any backend change, merging the four pages into one component, moving figures between books, Phase 3+.

## Tasks (TDD, one commit each, local branch `feature/one-trademind-phase-2`)
1. **Book audit test.** For Overview's four queries, assert (backend test, read-only) that a paper-only account and a real-book row never produce a mixed total. If a mix exists, stop and report; do not fix trading code.
2. **Tab names + flag.** RED: menu tests for the new labels, URLs unchanged, Testing hidden when the flag is off, owner-only unchanged. GREEN: `menu.ts`.
3. **`BookBadge`.** RED: render tests that each of the four pages shows exactly one correct badge and that Overview shows only "Paper". GREEN: component and header lines.
4. **Gates.** typecheck, all unit tests, build, parity `--check` (strict still fails by design), scope guard (only frontend and tests change).
5. **Browser verification (owner and non-owner, desktop and phone).** Every Portfolio URL renders the same data as the baseline; labels as specified; no real figure on Overview; no console errors.
6. **Independent review**, fix pass, then PR for owner review. Atlas oa6: "built and tested, pending production verification".

## Acceptance
- Four tabs with the spec names; all old URLs work; owner-only unchanged.
- Every total says Paper or Real; Overview never shows a real figure.
- Testing tab absent from the tab row when paper testing is off.
- 0 backend files, 0 `MyHoldings.tsx` lines changed.

## Rollback
Frontend only: revert the merge commit.

## Questions for the owner
1. Is the tab name "My Zerodha (real)" right, or keep "My Holdings"?
2. Should Overview stay paper-only, or also get a separate, clearly labelled Real block for the owner?
