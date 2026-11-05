# Evidence plan, Amendment 2 — the 15-day selection lab (ADOPTED on the owner's instruction, 2026-11-02)

Status: **ADOPTED 2026-11-02, on the owner's written instruction "go a head" to sign Amendment 2, Q1 and Q7. It takes effect only when the owner merges this change.** Follows Amendment 1
(`2026-10-21-evidence-plan-amendment-1.md`). It changes only what is written here; every other rule of the plan
(`2026-10-15-evidence-and-pilot-plan.md`) stands.

## Why

The plan has no phase for the 15-day selection lab (`2026-10-29-selection-model-experiments-design.md`, rev 3).
After Phase B it allows only Phase C or the December review. This amendment lets the lab run, offline, after
Phase B, under limits that keep Phase B, the sealed trial and the live brain exactly as they are.

## What is allowed

1. **Candidates S0, S1 and S2 (large group, the 49 stocks) and S0M, S1M and S2M (mid-cap group, 14 stocks), one run
   each**, S0 then S1 then S2, and S0M then S1M then S2M, offline, on the development window
   2023-07-01 to 2026-08-15. S2r only if the owner adds it in writing. **S3 stays blocked** (owner 2026-10-29)
   until company-data timestamps, quality and licensing are verified.
   The mid-cap group is the 24 training stocks of the app's mid-cap model minus the 10 of them that are in the
   held-back 129, so 14 stocks, none in the 49. It is a **limited experiment**: results carry the warning "Limited
   experiment: 14 stocks. Wide uncertainty. Not a basis for trading approval on its own." and the label is capped at
   "NO WARNING (diagnostic, limited sample)". Results are also split by size group, each group measured against its
   own median and its own average stock.
   **Technical rerun.** A candidate whose attempt crashed (ledger row written, no result) may be rerun at most twice,
   only with one incident note per failed attempt (kind execution or data-integrity failure, result never read, same
   code and rules), each rerun logged in the exposure ledger. A finished result is never rerun.
2. **Start no earlier than 2026-12-05**, after Phase B's lock date (2026-12-04). Phase B runs unchanged.
3. **Ranking only (owner, 2026-11-02).** The lab judges the chart-based score, split by market condition. It
   contains no money management and produces no profit, cost, capital or account figure. The brain's risk gate is
   where money is handled.
4. **The 129 held-back stocks are not used by the lab in this release.** Their use count stays at Phase B's three.
   Any later use needs its own amendment.
5. **No paid data and no new service** (Q7). Everything runs on data already held, on the owner's laptop.
6. **Models are registered TRAINED and never activated.** Nothing is connected to the brain, M06, the v1 bot or
   any order path.

## What a result can and cannot be

- The best label is **NO WARNING (diagnostic)**. It is never a PASS and cannot reach Phase C or any promotion.
- A candidate that ranks well may be proposed for a **separate** next step only, which must add (a) a check that
  its picks make money after costs, (b) the forward-test slot rule (only one 15-day candidate in forward test at a
  time, D5), and (c) explicit owner approval. This amendment grants none of those.
- Results go to the next decision review. No fallback, no retuning, no fifth candidate, no re-run.

## What stays untouched

Phase B and its three candidates; the sealed 15-day trial; the 5-day lane (h05); the 10-day protocol
(`td-protocol-v1`); production models, scoring, orders, sizing, stops and limits; `TRADING_MODE=paper`.

## How the code enforces it

The runner refuses unless the `sl-protocol-v1` tag exists, the frozen files are unchanged, the working tree is clean,
every overnight move over 20% is classified in writing, the candidate has not run before, and this amendment's
signed marker file exists: `docs/brain/evidence/sl_v1/EVIDENCE_PLAN_AMENDMENT_SIGNED.md`, containing the word SIGNED.
The exposure-ledger row is written before any model is scored.

## Owner decisions (signed)

- [x] A2-1 The lab may run after 2026-12-05, candidates S0, S1, S2 (large) and S0M, S1M, S2M (mid, 14 stocks) in order, one run each, with the technical-rerun rule (items 1 and 2).
- [x] A2-2 Ranking only, no money figures (item 3).
- [x] A2-3 The 129 held-back stocks are not used in this release (item 4).
- [x] A2-4 No paid data (item 5).
- [x] A2-5 Diagnostic label only; any next step needs a separate approval with a money check (section above).

Signature (owner): instruction "go a head" in the working session, recorded by the assistant at the owner's request. Date: 2026-11-02. Q1 (lab pre-registration) and Q7 (wait for Phase C, no paid data) are covered by the same instruction.

## Change-log line for the plan (added on signing)

| Date | Change |
|---|---|
| 2026-11-02 | Amendment 2 adopted (`2026-11-02-evidence-plan-amendment-2.md`): the 15-day selection lab may run offline after 2026-12-04 as S0, S1, S2 and S0M, S1M, S2M, ranking only, held-back 129 untouched, no paid data, diagnostic label only. |
