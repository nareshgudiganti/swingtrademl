# One TradeMind, Phase 3: one idea card, horizon labels, Today

**Status:** plan for owner review. Nothing is built until approved. No push, merge or deploy without separate approval.
**Spec:** `docs/superpowers/specs/2026-10-16-one-trademind-design.md` sections 2 and 3; tasks oa12, oa13, oa5. Phases 1 and 2 are live.

## Decision needed first: there must be only one idea card
The Safe-now session (local branch `feature/beginner-safe-now`, not built here) already has an `IdeaCard` component, and your review of it says "use the same idea card across applicable screens". Phase 3's recommendation card (oa12) is the same thing. Building a second card would break that rule.

| Option | What happens | Cost |
|---|---|---|
| **A (recommended)** | Safe-now's `IdeaCard` becomes the one card. Phase 3 waits until Safe-now has merged (after B1), then places that card on Today, Discover, the stock page and Swing Picks, and adds the horizon labels | Phase 3 starts later |
| B | Phase 3 builds the card now on `main`; Safe-now must later drop its own card and switch to this one | Rework in Safe-now; two sessions editing the same idea |
| C | Phase 3a now: only the parts no card depends on (horizon labels and model-status wording as small shared pieces, used by both). Phase 3b (card placement, Today merge) after Safe-now merges | Two smaller releases |

## Goal (once the card question is settled)
- One card for every stock idea, everywhere it appears: signal, model score (a ranking, never called a chance unless calibrated), entry/target/stop/last day/half-out level **only for TRADE**, risk-check result, plain-English reasons, evidence, horizon chip, model status. Missing items say "Not available" and why.
- Horizon labels: **15 days = "Experimental, unproven"**. 1, 5, 30, 90 days = "Unavailable" (not built; validating them is a separate project). Nothing is labelled "Validated" today.
- Today = today's Home plus the Swing Picks summary in one page; `/trademind/dashboard` keeps working.

## Rules (from your decisions)
- No buy plan (entry, target, stop, shares, money at stake) for WATCH, WAIT or AVOID.
- Do not imply the model has proven skill; the evidence wording is "What evidence supports this idea?" style, with sample size and limits.
- Brain trial outcomes stay sealed until the scheduled review.
- No change to stock selection, trading rules, risk settings, the frozen trial, or the backend. Frontend only.
- Same URLs; owner-only stays owner-only.

## Steps (tests first, local branch only)
1. Shared pieces: `HorizonChip` and `ModelStatus` with the three states; tests that 15 is "Experimental, unproven", others "Unavailable", nothing "Validated".
2. Card placement on Discover (Opportunities featured cards and stock page) using the one card; tests that WATCH/WAIT/AVOID never show a buy plan.
3. Today: Home plus Swing Picks summary; Dashboard URL keeps working; render tests for owner and non-owner.
4. Gates: typecheck, unit tests, backend regression, build, parity (strict still fails by design), scope check (frontend only).
5. Browser check against the live version: owner and non-owner, desktop and phone, in-app clicks between Today, Discover, stock page and Portfolio; loading, empty and error states.
6. Independent review, fix pass, PR for your review. Atlas oa12/oa13/oa5 marked "built and tested", not done.

## Done when
- Every idea shows the same card; only TRADE shows a buy plan.
- Every horizon shows the right status; nothing claims "Validated".
- Today combines Home and the Swing Picks summary; all old URLs work.
- No backend or trading change.

## Rollback
Frontend only: revert the merge commit.

## Questions for you
1. Option A, B or C for the card?
2. On Today, should Swing Picks (the old ML picks) appear below the brain's ideas, or only as a link?
