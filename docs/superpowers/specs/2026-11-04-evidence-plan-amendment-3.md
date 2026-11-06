# Evidence plan, Amendment 3 — re-freeze the 15-day selection lab as `sl-protocol-v1.1` (DRAFT for owner review, 2026-11-04)

Status: **UNSIGNED. NOT ADOPTED until the owner signs. NO TAG CREATED.** (This file is the frozen-text copy of the draft, created on branch change/amendment-3-implementation; the signature lines below stay blank: signed by: ____ on ____.) Prepared by the assistant at the owner's request (decision of
2026-11-04: "amended re-freeze, do not revert PR #135"). Nothing in this file is in force. No signature, signing date or tag
appears here because none exists. Companion file with the exact replacement text and code/doc diffs as plain text:
`2026-11-04-amendment-3-proposed-changes.md`.

Evidence marks used throughout: **[V]** verified by reading the file or running a read-only git command in this worktree
(`origin/main` = `b41367a`); **[I]** inferred; **[U]** unknown / could not be checked.

---

## 1. Owner summary (plain English)

**What is wrong.** The lab's runner (`selection_lab_run.py`) has a list of "frozen files" that must be exactly the same as
at the signed git tag `sl-protocol-v1`. That list includes the design document
`2026-10-29-selection-model-experiments-design.md`. That document did **not exist** when the tag was made (tag made
2026-11-02 20:10 IST on commit `6371ea6`; the document arrived on `main` through PR #135, commit `3ae4d20`, 2026-11-03)
[V]. So the runner will always say "differs from the tagged version" and refuse to run any candidate. The start wrapper
(branch `change/lab-start-wrapper`, not yet on `main`) refuses for the same reason [V]. That is the safe direction, but the
lab can never start.

**What I propose.** Keep the old tag `sl-protocol-v1` exactly as it is. Add a **new, later, immutable** tag
**`sl-protocol-v1.1`**, made on a commit that already contains (a) the design document in its final form, (b) the runner and
lab code with the protocol name changed to `sl-protocol-v1.1`, and (c) this Amendment 3. Amendment 3 also cleans up four
places where the design document (written before the owner's later decisions) disagrees with the signed Amendment 2 and with
the code that was actually built. No candidate has ever been run, so nothing already run is changed [V, section 7].

**What you must approve** (details in section 9): the tag name; the precedence rule (Amendment 3 beats Amendment 2 beats the
design document); the exact "ranking only" replacement wording (section 4.3); the statistical family of four
(S1, S2, S1M, S2M); how BAJAJELEC and HINDUNILVR are treated; that the unresolved-event "sensitivity run" is not built and not
run; and the approval sequence in section 8. Until you approve and sign, nothing here is in force.

---

## 2. Facts found (all checked)

| # | Fact | Mark |
|---|---|---|
| F1 | `sl-protocol-v1` is an **annotated** tag object `92d31dd` pointing at commit `6371ea6` ("Merge pull request #130 from nareshgudiganti/evidence/amendment-2-signed"), message "sl-protocol-v1: 15-day selection lab, frozen at Amendment 2". It exists on origin (`git ls-remote --tags origin`). | V |
| F2 | At that tag, `selection_lab.py`, `selection_lab_run.py`, `EVIDENCE_PLAN_AMENDMENT_SIGNED.md` and `2026-11-02-evidence-plan-amendment-2.md` exist; the design document and `sl_v1/gap_classification.*` do **not**. | V (`git ls-tree -r sl-protocol-v1`) |
| F3 | Since the tag, `selection_lab.py` and `selection_lab_run.py` are byte-identical to the tag; the only frozen-list difference is the design document (+881 lines, added by PR #135) and the gap files were added (not in the frozen list). | V (`git diff --stat sl-protocol-v1 HEAD`) |
| F4 | Runner mechanism: `git_state()` runs `git diff --name-only <TAG> -- <FROZEN_FILES>`; a file added after the tag appears in that list; `refusal_reasons()` turns each into "`<path>` differs from the tagged version: a changed rule is sl-protocol-v2, not v1." | V |
| F5 | The wrapper has **no tag constant of its own**: it reads `runner.TAG` and `runner.FROZEN_FILES` (`evaluate()`), and calls `runner.git_state`, `runner.amendment_signed`, `runner.refusal_reasons`. Its `check_frozen_files` refuses when a file is present at HEAD and absent at the tag. The literal `sl-protocol-v1` appears only in its docstring, in `docs/brain/SELECTION-LAB-START.md` and in its test fake. | V |
| F6 | `git check-ref-format refs/tags/sl-protocol-v1.1` returns OK. | V |
| F7 | `amendment_signed()` only tests that `EVIDENCE_PLAN_AMENDMENT_SIGNED.md` exists and contains the substring `SIGNED` (case-sensitive). The existing Amendment 2 marker already satisfies it, so with no change the runner would **not** notice a missing Amendment 3. | V |
| F8 | No run folder `sl1-*` exists under `docs/brain/evidence/sl_v1/` on `origin/main`, in this worktree, or in the main checkout; `EXPOSURE-LEDGER.md` has zero lines containing `sl-protocol`. I also checked every sibling worktree under `D:\machine learning\`: no `sl-protocol-v1 <cand>` ledger row anywhere. Models named `sl1_*` in the local database: **not checked** (no database access allowed). | V (files); U (database) |
| F9 | The tag `wf-protocol-v2` (Phase B lock) does **not** exist locally or on origin. Origin has `wf-protocol-v1`, `fd-protocol-v1`, `td-protocol-v1`, `sl-protocol-v1` (no `wf-protocol-v2`). So the wrapper's Phase B check cannot pass today. | V |
| F10 | The runner does not check the date or Phase B itself. Only the wrapper does (`EARLIEST_START = date(2026, 12, 5)`, IST). | V |
| F11 | The runner trains/scores with `sl.train_lab_model(... record=load_gap_record(...))` and **never passes `drop_unresolved=True`**. The "sensitivity run" that the gap file and design section 4.2 describe is implemented as a function option but is not called by the runner. | V |
| F12 | Breadth-survivorship sensitivity run (design 6.2a), portfolio view, costs, winner selection, H1 held-back check, Stage 2 and Stage 3 are **not implemented** in the code. `evaluate_ranking` returns `"qualifies_for_winner": False` and `"money": MONEY_NOT_EVALUATED`. A test (`test_the_lab_contains_no_money_management`) enforces no money logic. | V |

---

## 3. Conflicts between the design document (rev 3), Amendment 2 and the code — and their resolution

Precedence proposed for Amendment 3 (a new rule): **Amendment 3 > Amendment 2 (signed 2026-11-02) > design document rev 3 >
code comments.** The code's behaviour is the thing that actually runs; where the signed text and the code differ, section 3
says which wins and, where the code must change, section 6 lists it.

| # | Item | Design doc rev 3 says | Amendment 2 / code says | Resolution in Amendment 3 |
|---|---|---|---|---|
| C1 | Candidate family | Release 1 builds S0, S1, S2, **S2r** (and S3 later). Family of four = {S1, S2, S2r, S3}. | A2 item 1: "Candidates S0, S1 and S2 (large group, the 49 stocks) and S0M, S1M and S2M (mid-cap group, 14 stocks), one run each ... S2r only if the owner adds it in writing. **S3 stays blocked**". Code: `CANDIDATES = ("S0","S1","S2","S0M","S1M","S2M")`; `main()` argparse `choices=CANDIDATES`. | Six candidates only. **S2r is not added. S3 stays blocked.** Controls are S0 and S0M. The statistical family is the four non-control candidates **S1, S2, S1M, S2M** (still four, so the 5%/4 Bonferroni constant is unchanged). |
| C2 | Bonferroni and S2r margin | `BONFERRONI_Q = 0.05 / 4` "over the four model candidates"; `NOT_WORSE_MARGIN = 0.005` "S2r against S2". | The constants sit in `selection_lab.py`. `run()` always passes `r4_mode="better"`, so the not-worse branch and `NOT_WORSE_MARGIN` are never reached. | Keep both constants as they are (no code change). State that 1.25% (5%/4) is the one-sided bound for the four-member family of C1, and that `NOT_WORSE_MARGIN` belongs to S2r, is unused, and creates no S2r permission. |
| C3 | Start date | "after 4 Dec" (design section 3, 16; A2 change-log line "may run offline after 2026-12-04"). | A2 item 2: "**Start no earlier than 2026-12-05**, after Phase B's lock date (2026-12-04)." Wrapper: `EARLIEST_START = date(2026, 12, 5)`, IST calendar date. `horizon_report.LAB_START_NOTE`: "before 5 Dec 2026". | One rule: the lab may start on or after **2026-12-05 in India time (Asia/Kolkata calendar date)**, and only through the wrapper with every check passing. "After 2026-12-04" is retired wording meaning the same day; the item-2 sentence governs. |
| C4 | Ranking vs money | 6.3: "**Both verdicts are required.** Ranking (R1–R4) and money (M0–M3) ... a candidate qualifies only if **both** pass." Row 11-01 "ranking and money both required". Section 6.2/6.2a already marked "Superseded for now". | A2 item 3: "**Ranking only (owner, 2026-11-02).** The lab judges the chart-based score, split by market condition. It contains no money management and produces no profit, cost, capital or account figure." Code: no money logic; "qualifies_for_winner": False. | Replace with the exact wording in section 4.3. "Qualify", "winner", M0–M3, N, H1, Stage 2/3 do not exist in this lab. |
| C5 | Held-back 129 | 6.3 H1 and Q5: "one use by the lab, winner only"; use count "Phase B 3 + lab 1 = 4". | A2 item 4: "**The 129 held-back stocks are not used by the lab in this release.** Their use count stays at Phase B's three. Any later use needs its own amendment." Code: `assert_no_held_back(held_back, bars, used49, extra128, mid, scored)` before any run; `collect_db` asserts on `symbols`; `mid_group_from` removes the 10 held-back members; manifest line "Held-back 129: not used". The only thing read from the split file's `reject_set` key is the list of symbols, to prove they are absent. | The 129 are not loaded, trained on, scored, chosen from or tuned on. H1 and "lab 1 use" are void. Use count stays 3. See section 5. |
| C6 | Unresolved-event sensitivity | 4.2: unresolved "kept in the main result, and a sensitivity result without them is reported; a candidate must pass in **both**". | Gap file: "kept in the main result and dropped only in the sensitivity run". Runner never calls it (F11). | Section 6 of the document sets out two options; recommended: the sensitivity run is **not performed** in `sl-protocol-v1.1`; the two unresolved events are reported as a disclosure. |
| C7 | Other items in rev 3 that no code implements | 6.2a breadth sensitivity, portfolio view; N rule (100 finished trades); baselines "phase_b functions" (every stock, random, risk-matched, NIFTY, cash); `sl-protocol-v1-locked`; Stage 2, Stage 3, D5 forward slot; F1 earnings filter. | Code compares only with the day's median stock and momentum 5 (R2), IC (R1), fold consistency (R3), paired IC against the compared candidate (R4). | Listed as **not part of `sl-protocol-v1.1`**. The rules in force are R1–R4 as the code implements them. |
| C8 | Name | "Proposed protocol name: `sl-protocol-v1`. Frozen only when the owner signs section 17 and the signed commit is tagged." The signature line in section 18 is blank. | Tag `sl-protocol-v1` exists, "frozen at Amendment 2". | The design document is *not* signed as such; Amendment 3 adopts it, as conformed by the banner in the companion file, under the new name. The old tag is left alone and keeps the meaning "Amendment 2 code only". |
| C9 | "PASS" wording | Best label "NO WARNING (diagnostic)", "never a PASS". | `ranking_verdict` takes values `pass`/`fail`/`insufficient`; `lane_freeze.history_passed()` reads `ranking_verdict == "pass"`. | Say explicitly: `ranking_verdict: pass` is a name for "R1–R4 all hold"; it is not the evidence label PASS and does not satisfy the Amendment 2 requirement of a separate approval with a money check before any next step. (Downstream use by lane freezing is outside this amendment and is flagged in risks.) |

---

## 4. Formal Amendment 3 text (the text to be adopted if the owner approves)

> **Evidence plan, Amendment 3 — `sl-protocol-v1.1`.** Status when adopted: **ADOPTED <date of the owner's instruction>** [the date and the
> instruction are the owner's to supply when signing; the assistant does not pre-fill them]. It follows Amendment 2
> (`2026-11-02-evidence-plan-amendment-2.md`, signed 2026-11-02) and changes only what is written here. Every other rule of
> the evidence plan and of Amendments 1 and 2 stands.

### 4.1 Purpose and identifier

1. The runner could not start because its frozen-file list names the design document, which was added to `main` (PR #135)
   after the tag `sl-protocol-v1` was made. This amendment fixes that by re-freezing, under a **new** identifier, without
   touching the old one.
2. The protocol identifier is **`sl-protocol-v1.1`**. The git tag is **`sl-protocol-v1.1`**, an annotated tag created by the
   owner on the commit that contains the files listed in 4.5. The ledger markers are
   `sl-protocol-v1.1 {candidate}, {first} to {last}` and `sl-protocol-v1.1 technical rerun {n} {candidate}, {first} to {last}`.
3. The tag `sl-protocol-v1` is **not moved, deleted, re-pointed or re-used**. It keeps its meaning (Amendment 2 code, frozen
   2026-11-02). No run was made under it (section 4.6), so nothing has to be carried over.
4. **Prospective only.** `sl-protocol-v1.1` applies to runs started after its tag exists. Its scope is the six candidates
   below; it does not re-open Phase B, the sealed trial, h05, td-protocol-v1 or fd-protocol-v1.

### 4.2 Scope: what runs

5. Candidates **S0, S1, S2** (large group, the 49) and **S0M, S1M, S2M** (mid-cap group, the 14), one run each, in the order
   S0 → S1 → S2 and S0M → S1M → S2M, offline, on the development window 2023-07-01 to 2026-08-15, comparisons as built
   (S1 vs S0, S2 vs S1, S1M vs S0M, S2M vs S1M). The technical-rerun rule of Amendment 2 item 1 stands unchanged
   (at most two reruns, one valid incident note per failed attempt, never a rerun of a finished result).
6. **S2r is not added.** The S2r feature-reduction procedure (design section 12) and its non-inferiority margin are not part
   of this protocol. **S3 stays blocked** until company-data timestamps, quality and licensing are verified (A2 item 1).
7. **Statistical family.** The four model candidates tested for "better than their comparison" are **S1, S2, S1M and S2M**.
   S0 and S0M are controls and not in the family. The one-sided bound for R1 and R4 is the 1.25th percentile (5% ÷ 4) of the
   15-day block bootstrap, as in the code. A candidate that cannot be tested still counts in the four.

### 4.3 Ranking only — exact replacement wording

The following replaces, wherever it appears in the design document, the wording "ranking and money both required", "Both
verdicts are required", "a candidate qualifies only if both pass", the rows M0–M3 and N of the Stage 1 table, "Choosing the one
winner", "Held-back check H1", Stage 2, Stage 3 and `sl-protocol-v1-locked`:

> **The selection lab is ranking only (owner, 2026-11-02; Amendment 2 item 3).** It measures whether a higher chart-based score
> picks stocks that do better than other stocks on the same day, split by market condition, using R1 (mean daily rank
> correlation and its cautious lower bound), R2 (best-5 excess over the day's median stock and over momentum 5), R3 (consistency
> across test periods) and, for S1, S2, S1M and S2M, R4 (paired difference against the comparison candidate). It contains no
> money management: no costs, capital, position sizes, trade results, profit, drawdown, account replay, capacity, portfolio
> view or net expectancy are computed, shown or implied. There is no "winner", no "qualification", no held-back check, no
> forward stage and no promotion in this protocol. The best possible label is **NO WARNING (diagnostic)**
> (**NO WARNING (diagnostic, limited sample)** for the 14-stock mid-cap group). The result field `ranking_verdict` takes the
> values `pass`, `fail` or `insufficient`; `pass` means only that R1–R4 hold in the development data; it is not the evidence
> label PASS, and it is not a statement that a trade would make money. Any next step requires a separate amendment adding
> (a) a check that the picks make money after costs, (b) the forward-test slot rule (D5), and (c) explicit owner approval,
> exactly as Amendment 2 says. Every report keeps the "ranking and trading are different questions" paragraph (design 6.4a)
> before any number.

### 4.4 Dates

8. Replacement for every date statement ("after 4 Dec", "after 2026-12-04", "before 9 Nov", "after the December review"):
   > **The lab may not start before 2026-12-05 (India time, calendar date in Asia/Kolkata), after Phase B's lock date
   > (2026-12-04), and only through the start wrapper with every check passing.** Phase B runs unchanged.
9. Nothing in this amendment starts, schedules or authorises a run today. No run happens before 2026-12-05 IST, before the
   **Phase B completion record** is verified (the annotated tag `phase-b-result` and the committed `PHASE_B_RESULT.json` with its
   ledger row, for EITHER outcome), or before all wrapper guards pass. **`wf-protocol-v2` is not a general precondition:** it is
   required (annotated, naming the survivor) only when the recorded outcome is SURVIVOR_SELECTED, and it must NOT exist when the
   recorded outcome is NO_SURVIVOR (its presence then makes the wrapper refuse as inconsistent). The wrapper never creates or asks
   for a survivor tag to be invented.

### 4.5 What is frozen under `sl-protocol-v1.1`

10. The frozen files are:
    - `backend/src/swing_trade_ml/brain/selection_lab.py`
    - `backend/src/swing_trade_ml/brain/selection_lab_run.py`
    - `docs/superpowers/specs/2026-10-29-selection-model-experiments-design.md` (with the conforming banner, rev 3.1)
    - `docs/superpowers/specs/2026-11-04-evidence-plan-amendment-3.md` (this amendment, final name when adopted)
11. The signed marker is `docs/brain/evidence/sl_v1/EVIDENCE_PLAN_AMENDMENT_3_SIGNED.md`. The runner and the wrapper accept it
    only if it has a line beginning **`SIGNED by the owner on `** followed by a date, and names `sl-protocol-v1.1` and
    "Amendment 3". The Amendment 2 marker file remains in place and is not edited.
12. `gap_classification.json` and `gap_classification.md` (6 classified moves) are **not edited**. They are inputs, not rules.

### 4.6 What is preserved

13. Phase B and its three candidates; the sealed 15-day trial (hold-out A); the 5-day lane (h05); td-protocol-v1; production
    models, scoring, orders, sizing, stops, limits; `TRADING_MODE=paper`; every existing `EXPOSURE-LEDGER.md` row (none is
    edited); the `sl-protocol-v1` tag; the Amendment 2 documents; the stock split file and its hash.
14. **Each candidate runs once.** As of this draft none of the six candidates has ever been run: no run folder, no ledger row
    containing `sl-protocol-v1` or `sl-protocol-v1.1` (checked on `origin/main` and every local worktree; local database model
    names `sl1_*` not checked, see risks). The new markers are different strings from the old ones, so a row written under the
    old marker, if one is ever found, would not satisfy the new guard; section 9 asks the owner how to treat that case.

### 4.7 The 129 held-back stocks

15. The 129 stocks under the key `reject_set` in `docs/brain/evidence/stock_split/stock_split_ev15.json` are not loaded, trained
    on, scored, used for choosing inputs, groups or settings, or used as a comparison. The mid-cap group is the active
    mid-cap model's training stocks minus the held-back stocks (24 − 10 = 14), none in the 49. The runner asserts this before
    reading any price. The lab's use count of the 129 is zero; Phase B's three uses are unchanged; the design document's
    "4 uses" and "H1" are void. Any later use needs its own amendment.

### 4.8 Data-quality treatment of large overnight moves

16. The classification file stands as signed. Class `verified_error` removes the affected training days; `real_gap` is always
    kept; `unresolved` is kept in the main result. **No sensitivity run is performed under `sl-protocol-v1.1`** (recommended
    option; see section 6). The report states the two unresolved events (BAJAJELEC 2023-09-14, KFINTECH 2025-04-07) as a
    disclosure.
17. Moves of 20% or less are never touched by the lab. Known data limitation, disclosed in every report: HINDUNILVR
    (2025-12-05, about −5.0%, a 1:1 demerger step; stored unadjusted; only about 1.6% of it is mechanical) is inside the 49 and
    is kept as an ordinary return.

---

## 5. The 129 held-back stocks: do code and design document agree?

| Place | What it does | Agrees with "not used"? | Mark |
|---|---|---|---|
| `selection_lab_run.load_held_back()` | Reads key `reject_set` of `stock_split_ev15.json` and returns the symbol list. Docstring: "Used ONLY to prove they are absent from every list; never loaded." | Yes (symbol names only, no prices) | V |
| `run()` | `sl.assert_no_held_back(held_back, bars=list(bars), used49=..., extra128=..., mid=..., scored=...)` before the guard; a violation raises `RunRefusedError`. | Yes | V |
| `collect_db()` | `mid = sl.mid_group_from(model.training_symbols, held_back, used)`; `symbols = sorted({*used, *extra, *mid})`; `assert_no_held_back(held_back, symbols=symbols)` before `load_bars_with_volume`. | Yes | V |
| `lane_universe.py` | Re-reads `reject_set` and calls `problems(...)` to refuse overlap. | Yes (lane universe, not the lab) | V (read) |
| manifest | `"Held-back 129": "not used"`. | Yes | V |
| Design doc rev 3, sections 0, 6.3 (H1), 7, 16, 17 Q5, 19.2 | "one use by the lab, winner only", "4 uses". | **No** — conflicts with A2 item 4 | V |

Amendment 3 states it in section 4.7 above, and the banner in the companion file voids design H1, Q5's lab use and the "4 uses"
count. Remaining risk: the same list-reading code exists in lane freezing; not part of this amendment.

---

## 6. Treatment of BAJAJELEC and HINDUNILVR

**What the signed files say** (quoted exactly).

`docs/brain/evidence/sl_v1/gap_classification.json` (added to `main` after the tag, commit `a68a0d8`; **not** in the tag [V]):
`"BAJAJELEC|2023-09-14": "unresolved"`, `"KFINTECH|2025-04-07": "unresolved"`.

`gap_classification.md`, BAJAJELEC row: "No source found for this day. Kept in the main run, dropped in the sensitivity run."
Closing paragraph: "\"verified_error\" removes the affected training days; \"real_gap\" is always kept; \"unresolved\" is kept in the main
result and dropped only in the sensitivity run. Prepared by the assistant from news reports; the owner reviews it by merging.
Nothing was run."

Design 4.2 (not yet signed): "**UNRESOLVED ANOMALY** (no record either way) → kept in the main result, and a sensitivity result without them is reported;
a candidate must pass in **both**."

**Answers.**

1. *Is "primary inclusion plus sensitivity exclusion" what the signed text says?* Yes for the inclusion half [V]. The gap file
   says `unresolved` is kept in the main result and "dropped only in the sensitivity run", and a sensitivity run is *named*
   in it, but the file does not oblige anyone to perform one. The "must pass in both" sentence is only in the unsigned design
   document.
2. *Does the code do the sensitivity half?* **No** (F11). `train_lab_model(..., drop_unresolved=...)` exists and is tested as a
   function, but `model_scores_db()` never sets it, and no second pass exists. So as built the lab does primary inclusion only.
3. *Is amendment text needed for "documented exclusions"?* Yes, one clause, because otherwise the signed gap text promises a
   sensitivity run that will not happen. Two options:
   - **Option S-A (recommended): no sensitivity run in `sl-protocol-v1.1`.** Clause 16 above. No code change; the report lists
     the two unresolved events; the "pass in both" rule is voided with the rest of the winner machinery. Reason: ranking-only,
     label capped at "diagnostic", and a second training pass per candidate adds compute and code to a frozen runner.
   - **Option S-B: wire the sensitivity run.** Needs runner change (second scoring pass per candidate, a second result block in
     `metrics.json`/`report.md`, an explicit statement that it is not a rerun). Larger frozen diff and a larger test burden; I did
     not prepare this text.
4. *BAJAJELEC.* The gap file records +32% (overnight move, the lab's own detector). The corporate-action audit
   (`docs/brain/evidence/corporate_actions/corporate_actions_audit.md`, "PRELIMINARY EVIDENCE") records +38.8% close-to-close and
   32.2% in its other column, volume 0.18× normal, and a BSE record date of 14 Sep 2023; it says the audit supports dropping it
   in the sensitivity run [V]. The cause of an *upward* step is "UNKNOWN" there. The signed class stays `unresolved`. I do not
   change the JSON. The 38.8%/32% difference is a different measure, not a conflict [I].
5. *HINDUNILVR.* Not in the gap file (the lab flags only overnight moves over 20% and the move is about −5.0%). It is among the
   49 [V per audit text]. No amendment can "classify" it without either editing the signed JSON (forbidden) or changing the
   runner to read a second file (a new rule). So clause 17 documents it as a known limitation only. If the owner wants it
   excluded, that is a new decision with a code change (see section 9, D6).
6. The six events in the gap file are the only moves the lab's rule flags; the audit's other unadjusted events (ALLCARGO, TRIVENI,
   NMDC, SIEMENS, SCI, TMPV) are "membership UNKNOWN" in the 177 [U per the audit]. The amendment does not touch them; the
   runner's own rule refuses to run if a >20% overnight move in the 177 has no classification, so any such event in the 177 would
   stop the run rather than slip through [V].

---

## 7. The exact code and document changes (table)

Line numbers are from `origin/main` `b41367a` unless marked WRAPPER (`change/lab-start-wrapper`: wrapper version TO BE NAMED AT SIGNING, see 8A R-WRAP; not on main). Nothing
has been applied. "Frozen?" = the file is in `FROZEN_FILES` under v1.1, so it must be final before the tag.

| # | File | Line(s) | Current text | Proposed text | Why | Frozen? |
|---|---|---|---|---|---|---|
| 1 | `backend/src/swing_trade_ml/brain/selection_lab_run.py` | 35 | `PROTOCOL = "sl-protocol-v1"` | `PROTOCOL = "sl-protocol-v1.1"` | Single source for the name | yes |
| 2 | same | 36 | `TAG = PROTOCOL` | unchanged | Tag = protocol id; wrapper reads `runner.TAG` | yes |
| 3 | same | 37 | `SPEC = "docs/superpowers/specs/2026-10-29-selection-model-experiments-design.md"` | unchanged (file stays at this path) | Stays frozen; must exist at the new tag | yes |
| 4 | same | 38–42 | `FROZEN_FILES = (selection_lab.py, selection_lab_run.py, SPEC)` | add `AMENDMENT_TEXT` (new constant, `docs/superpowers/specs/2026-11-04-evidence-plan-amendment-3.md`) as 4th entry | The adopted rules text becomes frozen with the code | yes |
| 5 | same | 44 | `AMENDMENT = f"{OUT_DIR}/EVIDENCE_PLAN_AMENDMENT_SIGNED.md"` | `AMENDMENT = f"{OUT_DIR}/EVIDENCE_PLAN_AMENDMENT_3_SIGNED.md"` | F7: the old marker would let the runner pass without Amendment 3 | yes |
| 6 | same | 57 | `LEDGER_MARKER = "sl-protocol-v1 {cand}, {first} to {last}"` | `LEDGER_MARKER = PROTOCOL + " {cand}, {first} to {last}"` (renders `sl-protocol-v1.1 S0, ...`) | New protocol = new ledger string; cannot be confused with the old | yes |
| 7 | same | 58 | `RERUN_MARKER = "sl-protocol-v1 technical rerun {n} {cand}, {first} to {last}"` | `RERUN_MARKER = PROTOCOL + " technical rerun {n} {cand}, {first} to {last}"` | same | yes |
| 8 | same | 121–124 | `amendment_signed`: exists and `"SIGNED" in text` | requires a line `^SIGNED by the owner on \d{4}-\d{2}-\d{2}` and the strings `sl-protocol-v1.1` and `Amendment 3` in the marker; keep Amendment 2 marker presence as a second condition | Makes the signature specific to this amendment | yes |
| 9 | same | 147, 245 | "... is sl-protocol-v2, not v1." / "... is sl-protocol-v2, a new protocol." | "... is a new protocol version (sl-protocol-v1.2 or sl-protocol-v2), not sl-protocol-v1.1." (use `{PROTOCOL}`) | Messages must not point to the wrong version | yes |
| 10 | same | 3, 9–16 (docstring) | "draft `sl-protocol-v1`", "the git tag `sl-protocol-v1`", "S2r and S3 are not built" | name changed to `sl-protocol-v1.1`; add "Amendment 3" and "ranking only" | Accurate description | yes |
| 11 | same | 172, 435, 545 | `sl1-{candidate}-*`, `sl1-...` run id, model name `sl1_{candidate}_{cutoff}` | **unchanged** | `lane_slots.py` prefixes (`sl1_S0_` etc.), registry and `existing_runs()` depend on the `sl1` family prefix; no run exists, so no collision. Deliberate non-change | yes |
| 12 | `backend/src/swing_trade_ml/brain/selection_lab.py` | 3 | docstring "draft protocol `sl-protocol-v1`" | `sl-protocol-v1.1` | Accurate | yes |
| 13 | same | 766 | `"protocol": "sl-protocol-v1 (draft; ranking only)"` | `"protocol": "sl-protocol-v1.1 (ranking only)"` | Written into every `metrics.json`; must match runner | yes |
| 14 | same | 413, 418 | `BONFERRONI_Q = 0.05 / 4`; `NOT_WORSE_MARGIN = 0.005` | **unchanged**; comment on 418 may add "unused: S2r is not part of sl-protocol-v1.1" (comment-only, optional) | Family of four S1,S2,S1M,S2M gives the same constant | yes |
| 15 | `docs/superpowers/specs/2026-10-29-selection-model-experiments-design.md` | line 1–5, plus per-section markers | rev 3, "Proposed protocol name `sl-protocol-v1`" | add the "rev 3.1 conformed to Amendment 3" banner and "superseded" markers (exact text in the companion file); do not rewrite the signed-rule body | Resolves C1–C9 without rewriting history | yes |
| 16 | `docs/superpowers/specs/2026-11-04-evidence-plan-amendment-3.md` (new, from this draft) | — | — | the adopted amendment text | Frozen rules text | yes |
| 17 | `docs/brain/evidence/sl_v1/EVIDENCE_PLAN_AMENDMENT_3_SIGNED.md` (new, written only after the owner's signing instruction) | — | — | marker, wording in section 8(a) | What `amendment_signed` checks | no (checked, not frozen) |
| 18 | `backend/src/swing_trade_ml/services/lane_slots.py` | 67, 77 | `protocol="sl-protocol-v1"` (two slots) | `protocol="sl-protocol-v1.1"` | Informational field only (class comment: "informational"); keep naming consistent | no |
| 19 | `backend/src/swing_trade_ml/shadow_lanes/horizon_report.py` | 61, 62 | `"sl-protocol-v1 (candidates S0, S1, S2)"` / `"... S0M, S1M, S2M)"` | `sl-protocol-v1.1 ...` | Display text; line 244 splits on first space, so a dotted token is safe | no |
| 20 | same | 63 | `LAB_START_NOTE = "before 5 Dec 2026 (signed Amendment 2)"` | wording "before 5 Dec" can be read as a deadline; propose `"not before 5 Dec 2026 (Amendments 2 and 3)"` | C3 date wording | no |
| 21 | `frontend/src/pages/HorizonReport.test.tsx` 23, 61; `frontend/e2e/fixtures/horizon-report.json` 37 | string `sl-protocol-v1` | match item 19 if tests assert text | Test fixtures follow the display text | no |
| 22 | `backend/tests/test_selection_lab_run.py` | 109, 115, 124, 260, 270, 322 | literal `"sl-protocol-v1 S0"`, `"git tag sl-protocol-v1 is not in..."`, `"sl-protocol-v1 S0M,"` | use `run.PROTOCOL` in the assertions; add new tests listed in section 8(b) | Tests must follow the constant | no |
| 23 | WRAPPER `backend/src/swing_trade_ml/brain/selection_lab_start.py` | 2 (docstring) | "(`sl-protocol-v1`)" | "(`sl-protocol-v1.1`)" | Text only. **No tag constant exists to change** (F5) | no |
| 24 | WRAPPER `docs/brain/SELECTION-LAB-START.md` | items 3, 5, 6 | "`sl-protocol-v1` exists", "(the design document is not on `main` today)", amendment signed | "`sl-protocol-v1.1`", delete the design-document remark, mention Amendment 3 marker | Documentation truth | no |
| 25 | WRAPPER `backend/tests/test_selection_lab_start.py` | 24, 56, 143, 148 | fake runner with `"sl-protocol-v1"` | use `"sl-protocol-v1.1"` and add the cases in 8(b) | Fixture follows runner | no |
| 26 | `shadow_lanes/lane_freeze.py`, `lane_universe.py` | 99; 84, 129 | import `collect_db`, `RunRefusedError`, `load_split` from `selection_lab_run` | **no change**: they import functions, not the protocol name or marker | Checked: no name dependency | — |
| 27 | `docs/superpowers/specs/2026-11-02-evidence-plan-amendment-2.md`; `sl_v1/EVIDENCE_PLAN_AMENDMENT_SIGNED.md`; `sl_v1/gap_classification.*`; `docs/brain/EXPOSURE-LEDGER.md` | — | — | **not edited** | Signed / append-only / evidence | — |

Places that parse or depend on the protocol name or marker [V]: `LEDGER_MARKER`/`RERUN_MARKER` are used with plain `in` substring
tests and `.format` in `ledger_attempts`, `add_ledger_row`, `ledger_row`; `existing_runs` uses a glob on `sl1-` (not the protocol
name); `git_state` uses `git tag --merged HEAD -l <TAG>` (a glob pattern; a dot is literal, `*?[` are the only specials);
`horizon_report` line 244 takes `split(' ')[0]`. A dotted name does not break any of these. Substring safety: the new marker
`sl-protocol-v1.1 S0,` does not contain the old `sl-protocol-v1 S0,` (the character after `v1` differs), so rows cannot be
mistaken for one another. The old tag also matches no new pattern, so having both tags in history is harmless.

---

## 8. Approval sequence for the owner

**(a) Amendment text approved and signed.**
- You read this draft and the companion file; you answer the decisions in section 9.
- On your written instruction (as with Amendment 2: an instruction in the working session), the assistant creates
  `docs/superpowers/specs/2026-11-04-evidence-plan-amendment-3.md` (this text with the status line changed to ADOPTED and your
  date) and the marker `docs/brain/evidence/sl_v1/EVIDENCE_PLAN_AMENDMENT_3_SIGNED.md`. Proposed marker wording, which the
  runner will check, modelled on Amendment 2's:
  ```
  # Evidence plan, Amendment 3: SIGNED

  SIGNED by the owner on <YYYY-MM-DD> (instruction "<your words>": A3-1 to A3-<n>).
  See docs/superpowers/specs/2026-11-04-evidence-plan-amendment-3.md. Protocol sl-protocol-v1.1.
  In force once merged to main. The sl-protocol-v1.1 tag is still needed before the lab will run.
  ```
  The `<...>` fields are blank until you give the instruction; the assistant must not invent them.

**(b) One pull request** (docs plus the small runner/lab-code edits in section 7 items 1–16, 18–22, and the wrapper changes
23–25, which are on a different branch and need their own PR or a rebase). Tests that must be in the PR and pass:
1. `PROTOCOL == "sl-protocol-v1.1"`, `TAG == PROTOCOL`, marker strings start with `PROTOCOL`, and neither marker contains the old marker.
2. `git check-ref-format --allow-onelevel`-equivalent check of `refs/tags/<TAG>`.
3. Frozen list: every path in `FROZEN_FILES` exists in the working tree; `selection_lab.py:766` string equals `PROTOCOL + " (ranking only)"`.
4. `amendment_signed`: false for no file, false for the Amendment 2 file only, false for "SIGNED" without date or without the two strings, true for the proper marker.
5. `refusal_reasons` with a fixture repo where a tag `sl-protocol-v1.1` contains all frozen files → no "differs from the tagged version" reason; with the design doc absent at the tag → the reason appears (regression of today's bug).
6. Held-back: `assert_no_held_back` still refuses a held-back symbol in each list (existing tests); manifest says "not used".
7. Wrapper check-only dry run with fake git/clock (the wrapper already accepts `git=`, `now_fn=`, `runner=`): all six checks `ok` at a clock of 2026-12-05 10:00 IST with tag `sl-protocol-v1.1`, the Phase B tags (`evidence-defs-v1`, `evidence-defs-v2`, `phase-b-settings`), a verified `phase-b-result` record (run once with a NO_SURVIVOR fixture, where `wf-protocol-v2` must be ABSENT, and once with a SURVIVOR_SELECTED fixture, where `wf-protocol-v2` must be present and name the survivor), ledger rows, clean tree, marker present, → "All checks passed (check-only: the runner was not called)"; and refuses on 2026-12-04 23:59 IST, and refuses a NO_SURVIVOR fixture that also has `wf-protocol-v2`.
8. The same dry run against the real repository state is *expected to refuse today* for date and Phase B only (see (d)).
9. No test may run a candidate or touch the database.

**(c) You create the tag** (assistant never does). After the PR is merged to `main` and you have checked `git diff` shows only the
intended frozen-file changes:
`git tag -a sl-protocol-v1.1 <merge-commit> -m "sl-protocol-v1.1: 15-day selection lab, ranking only, frozen at Amendment 3"` then
`git push origin sl-protocol-v1.1`. Verify with `git cat-file -t sl-protocol-v1.1` = `tag` and
`git rev-parse sl-protocol-v1 ` unchanged (`6371ea6…`^{commit}; tag object `92d31dd`). No later change to any of the four frozen files is allowed; any change
would need `sl-protocol-v1.2`.

**(d) Expected wrapper dry run** (`python -m swing_trade_ml.brain.selection_lab_start S0 --check-only`, from a clean checkout of
the tagged `main`), today or any day before 2026-12-05 [I — this run has not been done]:
- `date`: refused: "Too early: today is <date> (IST); the lab may start from 2026-12-05."
- `phase_b_lock`: refused while the annotated tag `phase-b-result` and its verified `PHASE_B_RESULT.json` record do not exist (Phase B has not finished). It does NOT ask for `wf-protocol-v2` unless the record says SURVIVOR_SELECTED, and it refuses if `wf-protocol-v2` exists while the record says NO_SURVIVOR. [I: wording of the refusal lines follows the wrapper version named in section 7a; not yet run.]
- `protocol_tag`, `clean_tree`, `frozen_files`, `runner_guard`: **ok** (the point of the amendment). `frozen_files` has no warnings.
- exit code 2, one audit line in `backend/data/lab_start_audit.jsonl` (git-ignored).
- On/after 2026-12-05 with Phase B done: "All checks passed (check-only: the runner was not called)", exit 0.

**(e) What stays blocked until 2026-12-05 and Phase B lock.** Every lab run (no candidate may start); S2r; S3; any use of the
129; any money evaluation; any use of lab output by the brain, lanes or orders. Also blocked until each is separately approved:
lane freezing from a lab result (`lane_freeze.history_passed` reads `ranking_verdict == "pass"`; see risk R5). The wrapper
refuses before 2026-12-05 IST and until the Phase B completion record (`phase-b-result`, `PHASE_B_RESULT.json`, ledger rows) is verified for either outcome (`wf-protocol-v2` only after a real survivor, forbidden after NO_SURVIVOR). Running the runner
directly bypasses the date and Phase B checks (F10); the rule is that nobody does so.

---

## 8A. Contradictions resolved in writing (owner-requested consolidation; all PROPOSED, unsigned)

**R-WF. `wf-protocol-v2` (fixed above).** Earlier text implied the lab needs the tag `wf-protocol-v2` before it can start. That is
wrong for NO_SURVIVOR and would invite a fake survivor tag. Rule: the Phase B completion record (`phase-b-result` tag +
`PHASE_B_RESULT.json` + ledger row) is the lock for BOTH outcomes; `wf-protocol-v2` exists only after a verified survivor and must not
exist after NO_SURVIVOR. This matches the finish module (`phase_b_finish.py`) and the wrapper's `check_phase_b_lock`.

**R-PASS. The word "pass".** Amendment 2 says the lab's best label is "NO WARNING (diagnostic)", "never a PASS", cannot reach Phase C
or any promotion, and any next step "needs a separate approval with a money check" (A2-5). The code says otherwise in one place:
`selection_lab.py:801` sets `ranking_verdict` to `"pass"`/`"fail"`/`"insufficient"`, and `lane_freeze.history_passed` treats
`ranking_verdict == "pass"` as a passed history test that allows freezing a model into a shadow lane. Resolution text:
> In the lab's output the word `pass` in `ranking_verdict` is the machine form of the label NO WARNING (diagnostic): every
> mechanical ranking check returned no warning. It is never a protocol PASS, carries no authority, and does not by itself allow
> any freeze, lane, promotion or order. A lane freeze from a lab result requires, in addition, a separately signed approval
> record that contains the money check required by Amendment 2 (A2-5). Until that record exists the freeze step is not run.
Consequences: (1) `selection_lab.py` is frozen under `sl-protocol-v1.1`, so the word is not changed; the meaning is fixed by this
text; (2) `lane_freeze` is outside the frozen list, so a small separate guard (refuse a 15-day candidate unless a signed approval
file naming the candidate and the money-check evidence exists) is RECOMMENDED as its own PR with the owner's approval; it is not part
of this amendment and is not built; (3) until the guard exists the rule is operational: nobody runs the freeze on a lab result.

**R-WRAP. Wrapper version.** The earlier drafts cite wrapper commit `1b19df8` (the original local commit on the old main). The branch
`change/lab-start-wrapper` was since rebased to `6e7c6fa` (parent `b41367a`), and its working tree holds further UNCOMMITTED
changes (the Phase B result-record verifier and tests). No single wrapper version has been committed that matches this amendment.
Resolution: the wrapper that is merged is ONE commit to be created from the tested working tree after the Phase B rehearsal passes and
the owner approves; its full 40-hex hash is named in the signed Amendment 3 and in the Phase B signature package, together with the
full hash of the finish module's commit. Neither `1b19df8` nor `6e7c6fa` may be cited as "the version". Until then every reference
reads "wrapper version: TO BE NAMED AT SIGNING".

---

## 9. Decisions needed from the owner

| ID | Decision | Recommendation |
|---|---|---|
| D1 | Tag and protocol name `sl-protocol-v1.1` (alternatives: `sl-protocol-v1a`, `sl-protocol-v1-r2`) | `sl-protocol-v1.1`; verified valid and safe for all parsers in section 7 |
| D2 | Precedence: Amendment 3 > Amendment 2 > design doc > code comments | Yes |
| D3 | Statistical family = S1, S2, S1M, S2M, constant 5%/4 unchanged | Yes (no code change); alternative would be to re-derive the correction for a different family, which changes `BONFERRONI_Q` in a frozen file |
| D4 | Exact ranking-only wording (section 4.3) and voiding of H1 / M0–M3 / N / winner / Stage 2–3 | Yes |
| D5 | Whether the design document stays as a conformed document (banner plus markers, recommended) or is rewritten to a clean rev 4 | Banner (smaller diff, history visible, same approach already used for 6.2) |
| D6 | Unresolved events: option S-A (no sensitivity run; recommended) or S-B (build it); and HINDUNILVR/BAJAJELEC remain in the primary data | S-A; keep both in |
| D7 | Make Amendment 3 text part of `FROZEN_FILES` and require the new marker path/wording (items 4, 5, 8) | Yes |
| D8 | Optional hardening: add the date (2026-12-05 IST) and Phase B completion-record checks (`phase-b-result`; never a survivor tag) to the runner itself so a direct run is also refused | Not in this PR (it changes behaviour of a frozen file and the wrapper's call signature); revisit only if you want the lock to be code, not rule |
| D9 | Treat any `sl-protocol-v1` ledger row, run folder or `sl1_*` model found later as consuming that candidate's one run (i.e. refuse the same candidate under v1.1) | Yes; none exists today as far as files go |
| D10 | Wrapper merged on its own PR before the tag (it is not frozen, so order is free) | Merge it first, then the amendment PR, then tag |

---

## 10. Risks and unknowns

| ID | Item | Mark |
|---|---|---|
| R1 | Local database may hold models named `sl1_*` or `research_lab_runs` rows from earlier experimentation; I could not check. A read-only query by name prefix should be done before signing (D9). | U |
| R2 | The wrapper branch is not on `main`; its tests were not run here; edits to it are proposals. | V (not on main) / U (tests) |
| R3 | The runner source changes after a tag-less period; a typo in the frozen files discovered after tagging forces `sl-protocol-v1.2`. Mitigation: the PR tests in 8(b), dry run on a throw-away tag **in a scratch clone only**, never the real tag. | I |
| R4 | The design document banner/markers leave the old rule text in place; a reader may still read H1/M0–M3 as active. Mitigation: the banner states precedence at the top and each section carries a one-line marker. | I |
| R5 | `lane_freeze.history_passed()` and `LANE_PROTOCOLS` consume `ranking_verdict == "pass"` to qualify a model for a shadow lane. Amendment 2 says a ranking pass is not a PASS and any next step needs a separate approval with a money check. These two statements are in tension for lane freezing. Not resolved here; outside this amendment's scope; owner should be aware. | I |
| R6 | A2's internal wording differs ("after 2026-12-04" in the change-log line vs "no earlier than 2026-12-05"). Resolved by precedence in C3; the signed file itself is not edited. | V |
| R7 | The gap classification file is described by the assistant as "Prepared by the assistant from news reports; the owner reviews it by merging". Whether the owner's "go a head" signing covered it explicitly is not written anywhere I can find; I treat it as an input in the tree, not as separately signed. | I |
| R8 | Two numbers for BAJAJELEC (+32% in the gap file, +38.8% in the corporate-action audit). I treat them as different measures; the audit does not state its column definitions in the part I read. | I |
| R9 | The corporate-action audit is "PRELIMINARY EVIDENCE" and itself says some of the other unadjusted events (ALLCARGO, TRIVENI, NMDC, SIEMENS, SCI, TMPV) have membership in the 177 UNKNOWN. If any is in the 177 and has an overnight move over 20%, the runner refuses (unclassified) rather than running. | V (runner rule) / U (membership) |
| R10 | Terminal state: the amendment does not authorise running, only unblocks the guard. The owner's separate go-ahead in the evidence plan sequence (Phase B finished, lock tag) still gates the start. | V |
| R11 | Tag creation by the owner is an irreversible-in-practice action (a pushed tag should never move). Do not create it until the PR is merged and the dry run on the merge commit is read. | I |
| R12 | This worktree's `git status` showed no changes before I created the two new files; nothing tracked was edited. | V |
