# Evidence plan, Amendment 2 — the 15-day selection lab (DRAFT for owner review, not signed)

Status: **DRAFT, 2026-11-02. Not signed. Nothing runs under it until the owner signs.** Follows Amendment 1
(`2026-10-21-evidence-plan-amendment-1.md`). It changes only what is written here; every other rule of the plan
(`2026-10-15-evidence-and-pilot-plan.md`) stands.

## Why

The plan has no phase for the 15-day selection lab (`2026-10-29-selection-model-experiments-design.md`, rev 3).
After Phase B it allows only Phase C or the December review. This amendment lets the lab run, offline, after
Phase B, under limits that keep Phase B, the sealed trial and the live brain exactly as they are.

## What is allowed

1. **Candidates S0, S1 and S2, one run each**, in that order, offline, on the development window
   2023-07-01 to 2026-08-15. S2r only if the owner adds it in writing. **S3 stays blocked** (owner 2026-10-29)
   until company-data timestamps, quality and licensing are verified.
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

## Owner decisions (to sign — nothing signed)

- [ ] A2-1 The lab may run after 2026-12-05, candidates S0, S1, S2 in order, one run each (items 1 and 2).
- [ ] A2-2 Ranking only, no money figures (item 3).
- [ ] A2-3 The 129 held-back stocks are not used in this release (item 4).
- [ ] A2-4 No paid data (item 5).
- [ ] A2-5 Diagnostic label only; any next step needs a separate approval with a money check (section above).

Signature (owner): ____________________  Date: __________

## Change-log line for the plan (added on signing)

| Date | Change |
|---|---|
| (signing date) | Amendment 2 adopted (`2026-11-02-evidence-plan-amendment-2.md`): the 15-day selection lab may run offline after 2026-12-04 as S0, S1, S2, ranking only, held-back 129 untouched, no paid data, diagnostic label only. |
