# Horizon lanes — shared infrastructure design (DRAFT for owner review)

Status: **DRAFT, not approved to build.** Nothing here changes a frozen file. Written 2026-10-26.
Owner direction (2026-10-26): three horizons only — 5, 10 and 15 trading days. 15D is the locked C1 trial and
stays as it is. 5D and 10D get their own lanes, shadow-only, after their own historical evidence gates.

## 1. Goal and non-goals

Goal: let a second and third horizon be tested forward, side by side with 15D, without any of them able to
change, slow or contaminate another.

Non-goals / anti-goals:
- No change to the 15D rules, models, files or counting. If a change would touch them, the design is wrong.
- No broker or paper orders from a shadow lane. No customer-facing recommendations from 5D or 10D.
- No pooling of results across horizons. Every number carries its lane label.
- No new infrastructure (CLAUDE.md principle 1): Postgres, Redis, APScheduler only.

## 2. What "a lane" is

One lane = one horizon + one frozen protocol tag + its own model, ideas, outcomes, clock and evidence.

| Lane | Horizon | Protocol | Status |
|---|---|---|---|
| `h15` | 15 trading days, +8% / −4% | wf-protocol-v1, evidence-defs-v2, Phase B | the existing C1 trial — **not** re-implemented as a lane; it stays on its current code |
| `h05` | 5 trading days, +2% / −4% (prod rule) | fd-protocol-v1 | historical test pending; forward not started |
| `h10` | 10 trading days, setting proposed in `td-protocol-v1` | td-protocol-v1 (proposal) | not started |

`h15` appears in the lane registry only as a read-only label so reports can list all three. Its numbers are
read from where they already live.

## 3. Isolation rules (each must have a test)

1. **Code.** Lanes live in new files (`brain/lanes/`). They may import frozen modules; they never edit them.
   `tests/test_trial_freeze.py` must pass with no new approval entry.
2. **Data.** New tables, each with a `lane` column in the primary key. No new column, index or trigger on an
   existing brain table. A lane writes only rows with its own lane id.
3. **Slots.** Shadow lanes hold no positions and take no slots. They read the same point-in-time data
   (`DatedReader`) and never read or write the paper account, so 15D and v1 slot counts cannot change.
4. **Orders.** A lane has no import path to order placement. A test greps the lane package for the execution
   and broker modules and fails if found.
5. **Clocks.** Each lane has its own lock date, 3-month check and 6-month verdict, stored in the lane
   registry. Starting or stopping one lane does not move another's.
6. **Evidence.** Output goes to `docs/brain/evidence/<protocol>/`. Historical and prospective results are
   separate files with separate headings; a report refuses to print one under the other's label.
7. **Switches.** `LANE_H05_ENABLED` and `LANE_H10_ENABLED`, both false by default, and a lane also refuses
   without its protocol tag in history (same guard idea as `five_day.py`).
8. **Customer.** No lane ideas in any customer endpoint or screen. Admin/owner views only, labelled
   "research — not a recommendation".

## 4. Parts

- **Lane registry** — lane id, horizon, protocol tag, lock date, switch state, status.
- **Horizon-parameterised outcome scorer** — a new function with the same barrier rules as
  `m09_learn/outcomes.py` (stop checked before target, bar-touching-both = stop, unknown until the horizon
  passes) but taking the horizon and levels as arguments. Not a change to the frozen one. A test feeds both
  the same 15-bar cases and requires identical results.
- **Lane shadow store** — top 5 ideas a day per lane, no repeats, recorded even when an order would have been
  blocked (the C1 counting rule from the testing plan), scored when the horizon ends.
- **Lane models** — one trained model per lane, trained with a cutoff of outcomes known by then. `h05` reuses
  `five_day_train.py`; `h10` gets its own after `td-protocol-v1` is signed.
- **Diagnostic store** — failed experiments and WATCH-idea outcomes, kept in separate tables and report
  sections marked "diagnostic — not official trial evidence". Nothing there can feed a pass/fail.
- **Daily job** — one APScheduler job per enabled lane, after market close, off by default.

## 5. Dependencies (order)

1. Verify git and prod state (done for git 2026-10-26; prod pending).
2. Run 5D layer 1 once (needs owner go after the pre-run checklist).
3. Sign `td-protocol-v1`.
4. Approve this design, then write the implementation plan.
5. Build lanes (additive) with the isolation tests.
6. Run 10D history once.
7. A lane enters forward shadow only after its own history gate **and** its counting rules are approved.

## 6. Testing requirements

- Trial freeze test unchanged and green.
- 15D before/after test: run the 15D idea/outcome path on a fixed fixture with lanes off and on; outputs
  identical.
- Isolation tests: a lane write cannot create/alter a 15D row, a position, an order or a slot count.
- Scorer parity with the 15D scorer on shared cases; horizon-boundary and gap cases.
- No look-ahead: existing point-in-time tests repeated for lane readers.
- Counting: top 5, no repeats, blocked-order ideas still counted, nothing counted before the lock date.
- Guards: run tools refuse without tag, with changed frozen files, or on a second run.

## 7. Open points for the owner

- O1: confirm 5D forward counting rules before any `h05` forward job (the signed protocol only says "own
  book / reserved slot"; a shadow lane needs its own wording so it does not double count v1 trades).
- O2: confirm that lane evidence stays out of the M18 30-idea gate.
- O3: confirm the diagnostic store may keep WATCH outcomes for 15D too, read-only, without changing M09.
