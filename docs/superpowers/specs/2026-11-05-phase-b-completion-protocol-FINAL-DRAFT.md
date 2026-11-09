# Phase B completion protocol (FINAL DRAFT for signature, UNSIGNED)

Status: **FINAL DRAFT FOR THE OWNER'S SIGNATURE. NOT SIGNED. NOT TAGGED. NOT IN FORCE.** It replaces the
working draft `2026-11-04-phase-b-no-survivor-DRAFT.md` (left untouched) and writes into text the six owner decisions A to F of
2026-11-04. It changes no signed rule, number, setting, tag or result. It must be signed and merged by **2026-11-08**,
before Phase B starts on **2026-11-09**. Once Phase B execution begins, sections 3 to 5 (survival, confidence method, tie
ladder) are **sealed** and may not be changed.

Marks: **[V]** verified by reading the file, running a read-only git command, or the scratch rehearsal described in
`phase-b-signature-package.md`; **[I]** inferred; **[U]** not stated in signed text. Signed sentences are quoted exactly.

**Revision 2026-11-05 (owner's five conditions).** The owner approved the recommended defaults for the five open Phase B
decisions with these conditions, all written in below: (1) the best survivor is chosen only among candidates that pass all
mandatory gates (section 2a, item B); (2) the result is saved as structured JSON **and** a readable Markdown report with
hashes, metrics and gate outcomes (sections 3 D, 6); (3) the 5 December lab after NO SURVIVOR is independent experimental
research only, and no failed model is promoted (item H); (4) `phase_b_finish.py` is separate, idempotent and has explicit
finalization checks (item E, section 8a); (5) each candidate's reproducible results are committed before the next candidate
runs, with no secrets and no large datasets (item C, section 7).

Companion code (built, tested on fixtures and in a scratch-repo rehearsal, never run on real data; the final code is committed on the
local branch `release/phase-b-code` tip `a05c619` (children of `change/phase-b-finish` `9de70ca` and `change/lab-start-wrapper`
`d7fc0a6`); none pushed; the binding is by blob id in section 11, not by these hashes):
`backend/src/swing_trade_ml/brain/phase_b_finish.py` (branch `change/phase-b-finish`), the lab wrapper
`backend/src/swing_trade_ml/brain/selection_lab_start.py` (branch `change/lab-start-wrapper`), and the data file
`docs/brain/evidence/phase_b/.gitattributes`. `brain/phase_b.py` is not edited: it is byte-identical to the blob in tag
`phase-b-settings` [V, `git diff phase-b-settings HEAD -- backend/src/swing_trade_ml/brain/phase_b.py` is empty].

---

## 1. Owner summary (plain English)

- Phase B tries three ideas (B1, B2, B3) once each, in that order, from 9 November to 4 December. An idea "survives" only if it
  beats both "buy every stock" and "buy the momentum stocks" on average profit per trade after costs, **and** is not worse than
  "every stock" on 129 stocks it never saw.
- The signed plan says "the single best survivor" is kept but never says what "best" means. This text fixes it **now,
  before any result exists**: among survivors, the one with the highest **pessimistic estimate of its edge over every-stock**
  (`edge_low`, defined exactly in section 4). If still tied, three more fixed yardsticks, then the lower candidate number. The
  whole ladder is printed in section 5. Nobody chooses after seeing results.
- After each idea runs, its complete output and a fingerprint file are committed **before** the next idea runs.
- At the end one record is made: `PHASE_B_RESULT.json`, one new exposure-ledger line, and the git tag `phase-b-result`. It says
  **SURVIVOR_SELECTED** (and which) or **NO_SURVIVOR**. `wf-protocol-v2` is created only for a survivor.
- If a run is interrupted, the rule is **fail closed** (section 9): it is written down, the evidence is kept, and a run may be
  repeated only with the owner's signed recovery note, and never once any result has been exposed.
- A small separate tool prepares the record and refuses anything incomplete, invalid, duplicated or inconsistent. It never
  commits, tags or creates `wf-protocol-v2`: you do those steps. Nothing is merged automatically.
- Phase B does not start until every item in the gate checklist (section 11) is verified.

---

## 2. What the signed documents already say (relied on)

| # | Signed sentence (exact) | Source | Mark |
|---|---|---|---|
| S1 | "A candidate survives Phase B only if, on development data, it beats **both** every-stock and momentum on average result per trade after costs, **and** is not worse than every-stock on the reject set." | Plan section 3 | V |
| S2 | "**Stop rule:** if no candidate survives, Phase C is skipped and the decision review (section 6) happens in December. No fourth candidate is invented." | Plan section 3 | V |
| S3 | "The single best survivor is locked as `wf-protocol-v2` (rules, settings, code commit, tag) by 2026-12-04." | Plan section 3 | V |
| S4 | "Exactly three candidates, each with fixed settings written down before it is run, **one run each, no retuning**" | Plan section 3 | V |
| S5 | "Rules before results. Every test is locked (written, committed, tagged) before it is run. A failed result stays on record; a re-run with new rules is a new protocol version." | Plan section 0 | V |
| S6 | "**Confidence method.** Lower bound = 5th percentile of the mean day edge, by block bootstrap over runs of 15 consecutive trading days, 2,000 draws, seed 7 (`walk_forward.bootstrap_low`, as in wf-protocol-v1). Fewer than 30 trading days with ideas → **Insufficient evidence**." | Plan section 3a | V |
| S7 | "**Start no earlier than 2026-12-05**, after Phase B's lock date (2026-12-04). Phase B runs unchanged." | Amendment 2, item 2 | V |
| S8 | "Changing anything below after the tag is a new settings version with its own tag, recorded here, and only before that candidate's one run. A candidate that has run is never re-run with new settings." | Phase B settings note | V |
| S9 | "Exposure ledger \| The runner writes the candidate's row **before** results; the row is also its one-run lock. If a run crashes after the row, the owner edits the ledger before that candidate can run" | Phase B settings note | V |
| S10 | "Point averages, gated at >= 30 trading days with ideas; an INCONCLUSIVE reject-set check counts as "does not survive" (cautious)" | Phase B settings note | V |

**Not in any signed text [V, searched plan, Amendments 1 and 2, settings note]:** the meaning of "best"; any record, tag, file or
ledger row for the Phase B outcome; whether the lab may run after NO SURVIVOR; any rule on committing between runs; what an
interrupted run must record. Hence this protocol.

### 2a. What "survives" means in the stored files [V]

"Survives" is S1 only. In code (`phase_b.survives`, unchanged): `beats_label == "NO WARNING (diagnostic)"` and
`reject_label == "NO WARNING (diagnostic)"`, where these are the stored check labels:

| Row (check id in the result JSON) | Rule (stored text) | Decides survival? |
|---|---|---|
| `phase_b_beats_every_stock_and_momentum` | "average per trade after costs above every-stock and momentum (plan section 3)"; gated to INCONCLUSIVE if fewer than 30 trading days with ideas | **Yes** |
| `reject_set` | "not worse than every-stock on the reject set (reject only)"; INCONCLUSIVE counts as does-not-survive | **Yes** |
| `net_return`, `baselines_trade_level`, `baselines_portfolio_level`, `statistical_confidence`, `drawdown`, `market_conditions`, `coverage`, `consistency`, `mid_small_cap_index` | the Phase C pass rules, reported on development data | **No**, reported and copied into the record only |

The tool re-derives survival from the two deciding labels and refuses if the stored `survives` boolean disagrees.

**"Mandatory gates" (owner condition 1) means exactly these two rows** (S1 as signed, with the S6 minimum of 30 trading days with
ideas that is already inside the first row). A candidate that is INCONCLUSIVE, FAIL or NOT TESTABLE on either row is not a
survivor, whatever its other figures are, and is never ranked, however high its `edge_low` is. The ranking ladder (section 5) is
applied **only** to the survivors; the tool and its tests (`test_best_survivor_is_chosen_only_among_survivors`) enforce this. The
other rows (the Phase C pass rules) stay "reported, not deciding", because making them mandatory would change the signed
sentence S1. **[V] Owner confirmed on 2026-11-07 (in the working session) that "mandatory gates" means exactly these two rows; this remains subject to the owner's signature of this text.**

---

## 3. The amendment text (proposed for signature)

> **Amendment 3a to the evidence plan: completing Phase B.**
> Status: PROPOSED, unsigned. Amends only what is written here. Every other rule of the plan, Amendment 1, Amendment 2, the
> settings note `phase-b-settings`, the tags `evidence-defs-v1`, `evidence-defs-v2` and `phase-b-settings`, and the sealed 15-day
> trial stand unchanged. It must be merged and tagged before 2026-11-09. Items A to C (the evaluation rules) may not be changed
> after the first Phase B result exists.
>
> **A. `edge_low` (owner decision A).** `edge_low` is the lower confidence bound of the 5th-percentile edge using the predefined
> statistical method: the value stored at `trade_level.candidate.edge_low` in each candidate's result file, which is the 5th
> percentile of 2,000 block-bootstrap means of the candidate's daily edge over every-stock, 15-day blocks, seed 7, exactly as
> `phase_b.py` computes it and as section 4 states precisely. It is read from the stored file and never recomputed.
>
> **B. Best survivor (owner decision B).** Only a candidate that passes **both mandatory gates** (section 2a) can be a survivor
> or be ranked. If more than one of B1, B2, B3 survives (plan section 3), the single best survivor
> is chosen by the ladder printed in full in section 5: highest `edge_low` first, then the fixed tie-breaks in the order and with
> the rounding rule written there. The ladder is applied only to the stored result files. There is **no discretionary
> tie-breaking after results**; the first step that separates the top two decides, and the record stores which step.
>
> **C. Run order and evidence (owner decision C).** Candidates are run once each in the order **B1, then B2, then B3**. After each
> candidate finishes, its immutable outputs (`.md`, `.json`, its exposure-ledger row) and its evidence manifest
> `MANIFEST_<Bn>.json` are committed in one commit on a clean tree **before the next candidate runs** (section 7), so that
> each candidate's results are reproducible from git alone (code commit, tags, split hash, file hashes, ledger row). Only these
> small text files are committed: **no secrets, no `.env`, no price or feature datasets, no model files, no other large data**;
> the tool refuses an evidence folder holding anything else (section 8a, "hygiene"). A committed output is never edited,
> renamed or deleted.
>
> **D. Record and tags (owner decision D).** The owner personally approves this signed protocol and its tags. When all three
> candidates have a complete, verified result, and no later than 2026-12-04 (India time), the record is made:
> `docs/brain/evidence/phase_b/PHASE_B_RESULT.json`, its readable Markdown report `PHASE_B_RESULT.md` (the report shows the
> outcome in plain English, every tag and commit hash, the split hash, the file and manifest hashes, the metrics of each
> candidate and the outcome of each gate; it is derived byte-for-byte from the JSON and re-checked by the tool) and one
> exposure-ledger row, committed together, then the annotated tag
> `phase-b-result` on that commit. The tag `phase-b-result` is reserved for a completed, verified result and is not created
> before. The tag `wf-protocol-v2` is reserved for a valid survivor (`SURVIVOR_SELECTED`), is created only after `phase-b-result`,
> and is never created for `NO_SURVIVOR`. Neither tag is created prematurely. Nothing is merged automatically: every merge of
> Phase B material to `main` is the owner's own act, by merge commit or fast-forward, never by squash or rebase (section 10).
>
> **E. Separate tool and checks (owner decision E).** The record is prepared by the separate module `brain/phase_b_finish.py`
> with its own tests; `brain/phase_b.py` is not edited. The tool is a dry run unless `--apply` is given, writes only the record
> file, its report (or, with `--manifest`, one manifest) and one ledger row, and never commits, tags or creates `wf-protocol-v2`.
> It is **idempotent**: if the record (or a manifest) already exists, a re-run only verifies it against the committed results,
> the report, the single ledger row and any `phase-b-result` tag (exit 0, nothing written, or exit 2 with reasons, nothing
> written); it never rewrites. Its finalization checks are listed in section 8a. The lab start
> wrapper `brain/selection_lab_start.py` verifies the record with its own strict checks and tests (section 12). The code
> versions are bound to this text by git blob id (section 11, gate G8).
>
> **F. Interruptions fail closed (owner decision F).** An interrupted run is recorded, its evidence is preserved, and a re-run
> needs a signed recovery authorisation. Unauthorised re-runs are never permitted, and no recovery is permitted at all once any
> protected result has been exposed. Section 9 is part of this item.
>
> **G. If Phase B cannot finish.** If any candidate has no complete, valid, consistent result by 2026-12-04, no record is written,
> nothing is called NO SURVIVOR, and the owner decides in writing what happens next.
>
> **H. NO SURVIVOR.** If the outcome is `NO_SURVIVOR`: Phase C is skipped, the decision review happens in December, no fourth
> candidate is invented, no candidate is re-run, and `wf-protocol-v2` is not created. The 15-day lab may begin from 2026-12-05
> subject to Amendment 3, the evidence gates and the readiness gates, **only as independent experimental research**: it is
> not a continuation, rescue or re-test of B1, B2 or B3, and it may not use a Phase B result to justify anything. **No model
> that failed Phase B is promoted, approved, enabled or given a role by the lab or by this record.** The lab wrapper prints this
> notice on every NO SURVIVOR start and stores it in its audit log. A `NO_SURVIVOR` record does not by itself promote, approve
> or enable anything.
>
> **I. Start gate.** Phase B does not start until every gate in section 11 is verified and the owner has said so in writing.

---

## 4. The defined `edge_low` [V, read in `phase_b.py` and `walk_forward.py`]

`trade_level.candidate.edge_low` is produced by `phase_b.trade_summary`, which calls
`walk_forward.daily_edge` and then `phase_b.confidence_range` (which calls `walk_forward.bootstrap_low`):

1. **Daily edge list.** For each decision day, in date order, take the candidate's finished ideas of that day and the
   every-stock group's finished ideas of that day (every one of the scored stocks, same day). A day counts only when both sides
   have at least one finished idea with a net return. The day's edge = (average net return after costs of the candidate's
   finished ideas) minus (average net return after costs of every-stock's finished ideas). Let *n* be the number of counting days.
2. **Minimum evidence.** If *n* < max(5, 2 x 15) = **30**, `edge_low` is `null` (the plan's "Insufficient evidence").
3. **Block bootstrap.** A fresh random generator `random.Random(7)`. Each draw rebuilds a series from *k* = ceil(*n* / 15)
   blocks; each block starts at an integer chosen uniformly from 0 to *n* - 15 and takes 15 consecutive days of the edge list
   (blocks may overlap; a draw may therefore hold up to 14 more days than *n*). The draw's value is the mean of all its days.
   2,000 draws.
4. **The 5th percentile.** The 2,000 draw means are sorted ascending; `edge_low` is the element at zero-based index
   `int(0.05 x 2000) = 100` (the 101st smallest). That is a one-sided 95% **lower confidence bound** of the mean daily edge, as the
   plan states (S6; Amendment 1: "The 5th-percentile lower bound of the mean day edge must be **above zero** (one-sided 95%)").
5. **Companions stored beside it:** `edge_per_day` (the plain mean of the edge list) and `edge_high` (the same bootstrap on the
   negated edges, negated back; the 95th percentile). The same value is stored at `checks[id = statistical_confidence].value.low`;
   the finish tool refuses if the two differ.

It is **not** recomputed at selection: the result files do not hold the per-day edges [V]. The ladder reads the stored number.
This is the reading approved as decision A. A second, nested bound on this number is not defined anywhere in signed text and is
not used.

---

## 5. The complete tie ladder (owner decision B)

**Who is in the ladder.** The survivors (section 2a). Zero survivors: `NO_SURVIVOR`, no ladder. Exactly one: that one,
`decided_by = only_survivor`, no ladder. Two or three: the ladder below.

**The figures** (each read from the stored result JSON of that candidate; fractions, so 0.004 means 0.4 percentage points):

| Step | Yardstick | Exact field in the result JSON | Rule | `decided_by` value if this step separates the top two |
|---|---|---|---|---|
| 1 | Pessimistic edge over every-stock | `trade_level.candidate.edge_low` | higher wins | `edge_low` |
| 2 | Average edge per day over every-stock | `trade_level.candidate.edge_per_day` | higher wins | `edge_per_day` |
| 3 | Average result per trade after costs | `trade_level.candidate.avg_net` | higher wins | `avg_net` |
| 4 | Pessimistic edge over momentum | `edge_vs_momentum.edge_low` | higher wins | `edge_vs_momentum_low` |
| 5 | Candidate number | the candidate id | **lower** wins: B1 before B2 before B3 | `candidate_id` |

**Rounding rule.** Every figure is converted to a number and rounded to **6 decimal places** with Python `round(x, 6)` before it
is compared (0.0001 percentage points; this stops the last digits of a floating-point number from deciding a tie). Two figures
are equal if their rounded values are equal. **Missing rule.** A figure that is `null`, absent or not a number counts as
minus infinity, so it loses to every number and ties only with another missing figure.

**How the ladder is applied.** Each survivor gets the four rounded figures as a list in the order of steps 1 to 4. Survivors are
ordered by those lists, compared step by step from the left (highest first); candidates whose four figures are all equal are
ordered by step 5. The first survivor is the winner. The step that separates the first two survivors is stored as
`selection.decided_by`; the figures of **all** survivors are stored in `selection.ranking` in ranked order. Only the winner is
locked (S3); the others are recorded and are not locked, re-run or kept as reserves. No other yardstick, judgement or later look is
allowed. Worked example (synthetic numbers, from the rehearsal): B1 `edge_low` 0.0040000012 and B2 0.0040000034 both round to
0.004, so step 1 ties; B2 `edge_per_day` 0.0072 beats B1 0.0061; B2 wins, `decided_by = edge_per_day`.

The code implements this exactly (`phase_b_finish.LADDER`, `rank_key`, `select_outcome`) and the lab wrapper re-checks that the
named survivor is first in the stored ranking [V, tests and rehearsal]. The order of steps 2 to 4 and the final rule are part of
what the owner signs; they cannot be changed after the first result exists.

---

## 6. The record: `PHASE_B_RESULT.json` (schema `phase-b-result-v1`)

Deterministic: UTF-8, LF, sorted keys, one-space indent, trailing newline, so its sha256 is stable [V].

| Field | Content |
|---|---|
| `schema` | `"phase-b-result-v1"` |
| `outcome` | `"SURVIVOR_SELECTED"` or `"NO_SURVIVOR"` (nothing else) |
| `survivor` | `"B1"`, `"B2"`, `"B3"`, or `null` (null if and only if `NO_SURVIVOR`) |
| `selection` | `method` (`phase-b-completion-v1`), `outcome`, `survivor`, `survivors[]`, `ranking[]` (id and the four ladder figures, ranked), `decided_by` |
| `written_at_ist` | ISO time, India time; between 2026-11-09 and 2026-12-04 23:59:59 |
| `deadline_ist` | `"2026-12-04T23:59:59+05:30"` |
| `code_commit_finish` | full sha of HEAD when written |
| `protocol`, `defs_version` | `"evidence-plan-phase-b v1"`, `"evidence-defs-v2"` |
| `tags` | for each of `evidence-defs-v1`, `evidence-defs-v2`, `phase-b-settings`: `tag_object` sha and `commit` sha |
| `split` | `file` path and `sha256` (equals the note's recorded hash and every result's `manifest.stocks.split_sha256`) |
| `window` | `["2025-02-01","2026-08-15"]` |
| `counts` | `candidates` (3), `survivors`, `trading_days`, `folds` (identical in all three results) |
| `candidates.B1/B2/B3` | `name`, `survives`, `pass_rows` (every check id and its label, verbatim), `B1_B2_B3_rule_rows` (the two deciding labels), `figures` (the four ladder figures), `avg_net_every_stock`, `avg_net_momentum`, `ideas`, `days`, `code_commit_run`, `evidence_commit`, `ledger_marker`, `result_files` (sha256 of the `.md` and `.json`), `manifest_file`, `manifest_sha256` |
| `evidence_manifest` | `per_candidate_sha256` and `combined_sha256` |
| `ledger` | `result_row_marker` = `"Phase B result record"` |
| `wf_protocol_v2_expected` | true if and only if `SURVIVOR_SELECTED` |

**Readable report** `PHASE_B_RESULT.md` (written with the JSON, committed with it): plain-English outcome; the JSON's sha256;
written time and deadline; protocol and definitions versions; window; split file hash; finish-tool commit; combined manifest hash;
trading days, folds and survivor count; a table of the three tags (tag object and commit); a table of the two mandatory gates per
candidate with the survives flag; a metrics table (`edge_low`, edge per day, average per trade, edge over momentum, every-stock and
momentum averages, ideas, days); the ranking and `decided_by`; every other pass rule label (reported, not deciding); and a table of
evidence commits and sha256 of every result file and manifest. It is a pure function of the JSON (`phase_b_finish.render_report`);
on every re-run the tool compares it byte-for-byte and refuses a hand-edited report.

Ledger row (one, appended at the end of the "Local data" table; no existing row is edited; it carries the sha256 of the record):
`| 2025-02-01 to 2026-08-15 (49 stocks; reject set of 129) | Phase B result record: <outcome[: Bn]>. No data looked at beyond B1, B2, B3 | Recorded only; <next step> | <IST date> | `phase_b/PHASE_B_RESULT.json` sha256 <64 hex> |`

Tag `phase-b-result`: annotated; message lines `outcome=`, `survivor=` (`none` for NO_SURVIVOR), `result_sha256=`,
`ledger_row=Phase B result record`, `written_at_ist=`. The tool prints the exact commands; the owner runs them.

---

## 7. Per-candidate procedure and manifest

**Manifest** `docs/brain/evidence/phase_b/MANIFEST_<Bn>.json` (schema `phase-b-candidate-manifest-v1`), written by
`phase_b_finish --manifest Bn --apply` (dry run by default): `candidate`, `written_at_ist`, `code_commit` (from the result),
`phase_b_py_blob`, `split_sha256`, `tags` (tag object shas), `files` (sha256 of the `.md` and `.json`), `ledger_row` (the exact
line) and `ledger_row_sha256`, `survives`. Never rewritten.

**Procedure, once per candidate, in the order B1, B2, B3:**

1. Preconditions: gates G1 to G13 of section 11 hold; for B2 and B3 the previous candidate is already committed.
2. Run the candidate once (the command form in the note after step 6; `swingtrade brain phase-b --candidate Bn` as typed fails with a circular import and runs nothing). It writes
   `phase_b_<Bn>_2025-02-01_2026-08-15.{md,json}` and adds the ledger row `Phase B candidate <Bn>` **before** the results.
3. Do not edit, rename, tidy or re-run anything. Do not edit the candidate's ledger row (not even its decision cell): the tool
   compares the row text exactly [V, rehearsal F8]. The owner's reading of a result goes into a separate dated note after the
   record exists.
4. `phase_b_finish --root . --manifest Bn` (dry run), read it, then `--apply` (always with `--root .`, see the note after step 6).
5. Run the two printed git commands (`git add` naming the candidate's `.md`, `.json`, `MANIFEST_<Bn>.json` and
   `docs/brain/EXPOSURE-LEDGER.md` explicitly, then `git commit`): one commit with exactly those four items. Look at
   `git show --stat` before moving on: nothing else may be in it (no `.env`, no data, no models). Check the tree is clean. Only then
   start the next candidate. The manifest step already refuses an evidence folder with unexpected, oversized or secret-naming files.
6. A committed output is never edited, renamed or deleted.

**Command forms verified on 2026-11-07 (documentation only; no code or signed rule changes).** Three traps were found while checking
every command in this text; each fails closed (nothing runs or is written):
(i) `python -m swing_trade_ml.cli ...` and the `swingtrade` command fail with a circular import. The working form, typed from the repo
root, is `python -c "import sys, swing_trade_ml.brain.service; from swing_trade_ml.cli import main; sys.argv=['swingtrade','brain','phase-b','--candidate','Bn']; raise SystemExit(main())"`
(the same form with `--dry-run` appended was run and printed the plan). (ii) `python -m swing_trade_ml.brain.phase_b_finish` has a wrong
default repository root (one folder above the repo, so it reports every tag as missing); always run it from the repo root with
`--root .`. It is left unfixed because its file is bound by blob id in section 11. (iii) The app's default database address (port 5432)
is not the local Docker database (`localhost:5433`, database `swing_trade_ml`); a real Phase B run reads the database and needs
`DATABASE_URL` set to that local address (never a production address; the December helper scripts set it and refuse anything else).
Gate G6 and the other read-only gates do not read the database. The exact typed forms and the helper scripts are in
`docs/brain/DECEMBER-RUNBOOK.md`.

At the final step the tool checks (via git) that each candidate's evidence commit holds its four items, is an ancestor of HEAD,
is the **only** commit that ever touched its outputs, and is a strict ancestor of the next candidate's evidence commit; that the
ledger rows are in the order B1, B2, B3; that `phase_b.py` at HEAD and at each run's code commit equals the blob at
`phase-b-settings`; and that every file still hashes to its manifest [V, tests and rehearsal].

---

## 8. Invalid, incomplete, duplicate, inconsistent

In every case the tool exits non-zero, **writes nothing**, and lists every reason. No case is ever turned into NO SURVIVOR.

| Class | Defined as (all tested) | Handling |
|---|---|---|
| **Invalid** | JSON unreadable; wrong window, protocol or defs version; unknown check label; run on an unclean tree or with no code commit; split file edited after lock; a required tag missing, lightweight or not an ancestor; `phase_b.py` differs from the settings tag; date outside 2026-11-09..2026-12-04 IST; candidates not run in the order B1, B2, B3 | Fix the cause only if it is outside the result (clock, tag, tree). A result file is never edited or regenerated. A bad result is reported to the owner. |
| **Incomplete** | A candidate's `.md` or `.json` missing; missing keys; missing ledger row; missing manifest; manifest not committed | No record. Owner decides in writing (item G). Never described as NO SURVIVOR. |
| **Duplicate** | `PHASE_B_RESULT.json` exists; tag `phase-b-result` exists; a "Phase B result record" ledger row exists; more than one ledger row for a candidate; a manifest already exists | Refuse. Never overwrite. A correction is a new dated note, not a rewrite. |
| **Inconsistent** | stored `survives` differs from the rule re-derived from the stored labels; figures differ between `checks` and `trade_level`; `trading_days`/`folds` differ between candidates; split hash differs; a file hash differs from its manifest; an output changed after its evidence commit (including delete-and-re-run); candidates committed together or out of order | Refuse; owner investigates; stored results stay as they are. |

### 8a. Finalization checks of `phase_b_finish.py` (explicit, all tested)

Before it writes anything it checks, and lists every failure: India-time window; the three tags (annotated, ancestors); reserved tag
and record absent; clean tree; split file against its recorded hash; for B1, B2, B3 the two result files, the manifest and exactly one
ledger row; each result complete and self-consistent; survival re-derived from the stored labels; `trading_days` and `folds` equal
across candidates; `phase_b.py` equal to the settings blob at HEAD and at each run commit; manifests match files; evidence commits in
order B1, B2, B3 and unchanged since; **hygiene** (only the expected small text files in the evidence folder, none over 5 MB, none
naming a secret setting; names only, no value is ever stored or printed). It then writes the record, the report and one ledger row
together or, if any write fails, restores the ledger byte-for-byte and removes what it wrote.

**Idempotence.** Re-running with the record present never rewrites: it re-derives the outcome from the committed results and compares it
to the stored record (all fields except the two that legitimately change, the write time and the HEAD at write time, which must still be
an ancestor), requires the canonical byte form, exactly one result ledger row carrying the record's sha256, a report identical to what
the JSON produces, and, if the tag exists, a tag message carrying `result_sha256=<that sha256>`. All good: "ALREADY FINALIZED", exit 0,
nothing written (also after 4 December and on a dirty tree, because it only reads). Anything else: exit 2, the reasons, nothing written.
`--manifest Bn` behaves the same way for a manifest. A half-done finalization (record written, not yet committed or tagged) is therefore
safe to re-run: the tool reports what verifies and the printed git commands remain the owner's next step.

---

## 9. Interruptions: fail closed (owner decision F)

### 9a. What `phase_b.py` itself does on a re-run [V, code and rehearsal F3, F5]

`run_real` checks, in this order: (1) the start guard (date from 2026-11-09 IST, the three tags, the split hash); (2) if the
candidate's `.md` **or** `.json` already exists, it refuses ("has already run"); (3) if the ledger already holds
`Phase B candidate <Bn>`, it refuses ("has already had its one run"); then it loads data, trains each fold with the leakage check,
writes the ledger row, computes, and finally writes the `.md` and then the `.json`. So:

| State found after a stop | Ledger row | `.md` / `.json` | `phase_b.py` re-run | Finish tool |
|---|---|---|---|---|
| **I0** stopped before the ledger row (data load, training, leakage check) | none | none | **allowed** (nothing was recorded or exposed) | nothing to check |
| **I1** stopped after the ledger row, before any output | present (the one-run lock) | none | **refused** by the row | refuses: result files missing |
| **I2** stopped while or after writing outputs, incomplete or unreadable | present | one or both, partial | **refused** | refuses: missing or unreadable result |
| **I3** both files written and valid | present | both complete | **refused** | proceeds normally (`--manifest Bn`) |

`phase_b.py` is not modified. The only exit from I1 is the owner's edit of the ledger that the settings note (S9) already allows.
This protocol adds conditions to that edit; it does not widen it.

### 9b. Rules

1. **Record every interruption before anything else.** Stop. Do not re-run. Do not open, print or look at any result file. Create
   `docs/brain/evidence/phase_b/INTERRUPTION_<Bn>_1.md` (never overwritten; a second interruption of the same candidate is
   `_2` and is always final, see rule 5). It states: candidate; the India time the run started and the time it stopped; what
   stopped it (as far as known); the state (I0, I1, I2 or I3); the exact list of files in the evidence folder, with sizes and
   sha256; the exact ledger line if present; the output of `git status --porcelain --untracked-files=all` and of
   `git diff -- docs/brain/EXPOSURE-LEDGER.md`; the code commit and the blob of `phase_b.py`; and a statement of what any person
   saw on screen. Commit it **together with the ledger row exactly as found**, in one commit, so that git history shows the row.
   Partial output files, if any, are committed as found in that same commit, never deleted. This is evidence, not a result.
2. **I3 is not a lost result.** Proceed under section 7. Still write the record of what happened.
3. **I0 (nothing recorded):** the interruption record is enough. No authorisation is needed because no row exists and nothing was
   exposed; the run may be started again once.
4. **I1 (row only, nothing exposed):** a re-run needs a **recovery authorisation**, `RECOVERY_<Bn>_1.md`, signed by the owner,
   committed as a separate commit before anything else changes. Then a third commit deletes exactly the one ledger line it names
   (`git diff --numstat` must show 0 added and 1 deleted for the ledger). Only then may the candidate be run again, once,
   unchanged (same code blob, same tags). The new run writes a new row. A candidate gets at most **one** recovery.
5. **I2, or any exposure: no recovery.** If any `.md` or `.json` of that candidate exists in any form, or any result figure, table
   or chart of that run was displayed, copied, saved, read out or seen by anyone, the protected results are exposed. The candidate
   is closed as `INTERRUPTED_EXPOSED`: it is never re-run, it is not described as survived or failed, no record may be written,
   and item G applies (the owner decides in writing; a re-run with new rules is a new protocol version, S5). The same applies to
   a second interruption of the same candidate.
6. **Unauthorised re-runs are never permitted.** A candidate whose row or outputs were deleted, moved or replaced without the
   steps above is invalid. The finish tool already refuses delete-and-re-run of committed outputs [V, rehearsal F5]. Deleting a
   row that was never committed would leave no trace, which is why rule 1 commits the row first and gate G14 checks the ledger
   history.
7. **Window.** A recovery re-run must still finish inside 2026-11-09..2026-12-04.

### 9c. What a signed recovery authorisation looks like (Phase B, for I1 only)

```
PHASE B RECOVERY AUTHORISATION  <Bn> #1                      (file RECOVERY_<Bn>_1.md)
Interruption record: INTERRUPTION_<Bn>_1.md, sha256 <64 hex>, committed in <commit>.
I confirm that, to my knowledge and from the record:
 1. the run stopped after the ledger row was written and before any result file existed;
 2. the evidence folder holds no phase_b_<Bn>_* file and no result figure was displayed, saved, copied or seen;
 3. phase_b.py is the blob of tag phase-b-settings and the three tags are unchanged;
 4. this is the first and only recovery of <Bn>;
 5. the only ledger change is deleting this one line, verbatim:
    <the full ledger line>
 6. the re-run uses the settings and code of the tags, unchanged, inside 2026-11-09..2026-12-04.
Owner: ______________________   Date (IST): ______________
```
A recovery note that is unsigned, missing a sentence, or committed after the ledger change is not an authorisation.

### 9d. What the tools check and what they do not

The finish tool and the wrapper refuse every partial state above and refuse delete-and-re-run of committed outputs. They do **not**
read `INTERRUPTION_*.md` or `RECOVERY_*.md`, so an unauthorised removal of a never-committed row cannot be detected by code. The
owner's gate G14 checks it with git history. This is recorded as a residual risk.

---

## 10. Tags (all annotated, never moved, never deleted, pushed one at a time)

| Tag | Exists now | Created by / when | On which commit | Message lines |
|---|---|---|---|---|
| `evidence-defs-v1`, `evidence-defs-v2`, `phase-b-settings` | yes [V] | already created | unchanged | unchanged |
| `phase-b-completion-v1` (proposed name for this signed text; the owner may rename it before signing) | no | the owner, after signing and merging this text and the two code branches, before 2026-11-09 | the commit on `main` that holds the signed text | `signed=<owner name, date>`, `finish_blob=`, `lab_wrapper_blob=`, `phase_b_blob=` (as in the table in section 11) |
| `phase-b-result` | no | the owner, only after the finish tool's `--apply` and the record commit; reserved for a completed verified result; never before | the one commit that adds `PHASE_B_RESULT.json` and the result ledger row (and nothing else) | `outcome=`, `survivor=`, `result_sha256=`, `ledger_row=Phase B result record`, `written_at_ist=` (the tool prints the command) |
| `wf-protocol-v2` | no | the owner, only for `SURVIVOR_SELECTED`, after `phase-b-result`, by 2026-12-04 | same commit as `phase-b-result` (`phase-b-result~0`) | `survivor=<Bn>`, `result_tag=phase-b-result` |

Merging: Phase B runs on a branch cut from the commit tagged `phase-b-completion-v1`. When the owner merges that branch to `main`
it must be a merge commit or fast-forward, **never squash or rebase**, because the evidence commit hashes are written in the record
and the tags point at them. A push to `main` deploys; the material is documents only. Tags are pushed one by one
(`git push origin <tag>`), never `--tags`.

---

## 11. Pre-start gate checklist (all must be true before the first Phase B run; all are read-only)

Python: `D:/machine learning/swing-trade-bot/backend/.venv/Scripts/python.exe`, `PYTHONPATH=backend/src`, with
`env -u API_KEY -u DATABASE_URL -u JWT_SECRET_KEY -u TRADING_MODE`. Commands run from the root of the checkout that will run Phase B.

| Gate | Must be true | Command (expected output) |
|---|---|---|
| G1 | On the Phase B branch; the signed-text tag is in its history | `git branch --show-current` (the branch); `git merge-base --is-ancestor phase-b-completion-v1 HEAD && echo ok` (ok) |
| G2 | Clean tree, nothing untracked | `git status --porcelain --untracked-files=all` (no output) |
| G3 | Four tags exist, annotated, ancestors | `for t in evidence-defs-v1 evidence-defs-v2 phase-b-settings phase-b-completion-v1; do echo $t $(git cat-file -t $t); git merge-base --is-ancestor $t HEAD && echo ok; done` (each `tag`, ok) |
| G4 | Reserved tags absent, locally and on origin | `git tag -l phase-b-result wf-protocol-v2` and `git ls-remote --tags origin phase-b-result wf-protocol-v2` (both empty) |
| G5 | `phase_b.py` identical to the settings tag | `git diff --exit-code phase-b-settings HEAD -- backend/src/swing_trade_ml/brain/phase_b.py` (exit 0) |
| G6 | Split file matches its recorded hash, and the runner's own guard has nothing to say | `python -c "import swing_trade_ml.brain.service; from swing_trade_ml.brain import phase_b as pb; from pathlib import Path; print(pb.refusal_reasons(today=pb.ist_today(), tags=pb.git_tags(Path('.')), split_dir=Path('docs/brain/evidence/stock_split')))"` (`[]`) |
| G7 | Date window, India time | `python -c "from datetime import datetime; from zoneinfo import ZoneInfo; d=datetime.now(ZoneInfo('Asia/Kolkata')).date(); print(d, '2026-11-09' <= str(d) <= '2026-12-04')"` (`True`) |
| G8 | Code versions are exactly the ones named in the signed text | `git rev-parse HEAD:backend/src/swing_trade_ml/brain/phase_b_finish.py HEAD:backend/tests/test_phase_b_finish.py HEAD:backend/src/swing_trade_ml/brain/selection_lab_start.py HEAD:backend/tests/test_selection_lab_start.py HEAD:backend/src/swing_trade_ml/brain/phase_b.py HEAD:docs/brain/evidence/phase_b/.gitattributes HEAD:docs/brain/PHASE-B-FINISH.md HEAD:docs/brain/SELECTION-LAB-START.md HEAD:backend/tests/trial_freeze.json` (the nine blob ids in the table below); and `git diff --exit-code phase-b-completion-v1 HEAD -- backend/src/swing_trade_ml/brain/phase_b_finish.py backend/src/swing_trade_ml/brain/selection_lab_start.py` (exit 0) |
| G9 | Finish tests, wrapper tests, freeze test green | `python -m pytest backend/tests/test_phase_b_finish.py backend/tests/test_selection_lab_start.py backend/tests/test_selection_lab_runner_guard.py backend/tests/test_trial_freeze.py -q -p no:cacheprovider` (all pass; 190 passed on 2026-11-07 on `release/nov-completion` after the 15D runner guard (wrapper blobs below re-issued; the five finish blobs, `phase_b.py` and `trial_freeze.json` unchanged); earlier: 166 passed on 2026-11-05 on `release/phase-b-code` a05c619, and 166 passed again on 2026-11-06 on the merged branch (a73b938 = a05c619 merged with `origin/main` cbdb3f6); re-run and record the count at signing) |
| G10 | Evidence files are protected from line-ending conversion | `git check-attr text -- docs/brain/evidence/phase_b/x.json` (`text: unset`) |
| G11 | No Phase B outputs or rows yet (before B1) | `grep -c "Phase B candidate" docs/brain/EXPOSURE-LEDGER.md` (0); `ls -A docs/brain/evidence/phase_b` (only `.gitattributes`) |
| G12 | Ledger history clean of candidate rows (before B1) | `git log --oneline -S"Phase B candidate" -- docs/brain/EXPOSURE-LEDGER.md` (no output) |
| G13 | Before B2 and B3: the previous candidate is committed and nothing is open | `git status --porcelain --untracked-files=all` (no output); `git log --oneline -1 -- docs/brain/evidence/phase_b/MANIFEST_B1.json` (a commit) |
| G14 | No unresolved interruption; any removed row has a signed recovery note | `git log --oneline -S"Phase B candidate <Bn>" -- docs/brain/EXPOSURE-LEDGER.md` shows exactly one commit (the evidence commit), or for a recovered candidate exactly three (record, removal, evidence) with `RECOVERY_<Bn>_1.md` committed between the first two; `ls docs/brain/evidence/phase_b/INTERRUPTION_*` has a signed `RECOVERY_*` for every I1 |
| G15 | The owner has said "start" in writing, and the signatures on this text are filled | owner's written note |

Re-verified 2026-11-06 on the merged branch `release/phase-b-code` a73b938 (`a05c619` merged with `origin/main` cbdb3f6, no conflicts): all nine blob ids below equal the table, and `phase_b.py` equals tag `phase-b-settings`. The binding is still by blob id.

Code-binding table (git blob ids of the COMMITTED files, local branch `release/phase-b-code` tip
`a05c619` (see above); re-verify at signing against `main`; any later change to any of them voids this binding
and the text must be re-issued with new ids). The binding is by blob id, which survives any merge method; the merge-commit hash is
added by the owner at signing:

| File | Git blob id | sha256 of the committed bytes |
|---|---|---|
| `backend/src/swing_trade_ml/brain/phase_b_finish.py` | `e34e0e42a35ed4fadb4ba5769c1e603e9ffbbb12` | `a6f0e5deeeec9daa60474ac96074eca1232886995001079bba2250fbff1e598b` |
| `backend/tests/test_phase_b_finish.py` | `db6a3bb3b0316f0d86ba40930a98715949e6a509` | `7ffa244e636fdd9b209586d58a9f7cf1f0ae5312c836b00bbca9b9107928995f` |
| `backend/src/swing_trade_ml/brain/selection_lab_start.py` | `8d5225c78b113c2e168f8d45d3f322c91b847284` | `93ef5a9689dfbadf5b054788cf0ebe3f4a3b83ef3f7fce51201d5b3f3d311df2` |
| `backend/tests/test_selection_lab_start.py` | `855330abb14d70a5c19b00cee6df3f0e6e8a6d14` | `6807a75b4f60157ab343d683a134f67d9b835af3c1449a8fb78aeb454454b91a` |
| `docs/brain/evidence/phase_b/.gitattributes` | `fa1385d99a319b43c06f5309d1aae9fdd3adea46` | `705fd4d6451a31d36b3df7de96f83f30ac976c9b4a6d1e51671d8e2f33e2d0da` |
| `docs/brain/PHASE-B-FINISH.md` | `46d3d7f83aafa2de0b40b255ec462cff1605829d` | `532f864f0e8bf71dff12a2794e5425a1e13cbd479af38c7f1fed8a5da4bb0243` |
| `docs/brain/SELECTION-LAB-START.md` | `d051cb00d5635f2a50410f93a5f4ad3bff942ff2` | `5cbbf86d6c5ae5adcdfe18a2667219727a47e363c5a7d470e787954258ff0cb8` |
| `backend/src/swing_trade_ml/brain/phase_b.py` (= tag `phase-b-settings`, not edited) | `a64f99a9040ddfed477c7d3a7d98a59191b3d17f` | compare by blob id |
| `backend/tests/trial_freeze.json` (frozen, not edited) | `8997b469c1b6697b70337c1a7c1473639bcb5584` | compare by blob id |

(G8's `git rev-parse` prints the ids in the order of the paths on its command line: finish, its test, wrapper, its test,
`phase_b.py`, `.gitattributes`, `PHASE-B-FINISH.md`, `SELECTION-LAB-START.md`, `trial_freeze.json`. Compare each to its row.) sha256 values are of git's stored bytes (`git show HEAD:<path> | sha256sum`).
Merge-commit hash (full 40-hex, filled in by the owner at signing), the commit on `main` that carries all of the above:
`______________________________________`

---

## 12. How the lab wrapper verifies (built in `change/lab-start-wrapper`, committed; code binding in section 11)

Fail closed, reading from the commit of `phase-b-result`, not only the working tree: the three tags annotated and ancestors;
`phase-b-result` annotated and created no later than 2026-12-04 23:59:59 IST; its message `result_sha256` equals the file's
sha256 and the sha in the single result ledger row; every result and manifest file exists, is unchanged since the tag, and
matches its recorded hash; exactly one ledger row per candidate and one result row; outcome equals the tag message; survivors
re-derived from the stored labels; the ranking names the survivor first; evidence commits are ancestors, contain their four
items and are a strict chain in ledger-row order; `SURVIVOR_SELECTED` requires an annotated `wf-protocol-v2` naming the same
survivor and `phase-b-result`; `NO_SURVIVOR` requires that `wf-protocol-v2` does not exist [V, wrapper tests and rehearsal].

**Runner guard (owner confirmed 2026-11-07).** The frozen 15-day runner `brain/selection_lab_run.py` no longer relies on the wrapper alone: its own guard (`selection_lab_start.guard_for_runner`, the same check code the wrapper uses, no copy) enforces the date (2026-12-05 IST or later) and the Phase B terminal-record verification of this section, from the command line and from a direct call, and fails closed. It is on branch `change/lab-runner-guard`, inside `release/nov-completion`, and is the reason the wrapper blobs in section 11 differ from the 5 Nov values. It changes no evaluation rule, number, threshold, seed or candidate definition.

---

## 13. What is NOT changed

Tag `phase-b-settings` and its note (candidate settings, 49/129/128 split, seeds, windows, guard); `phase_b.py` (byte-identical);
the plan's survival sentence S1, the stop rule S2, one run each S4; tags `evidence-defs-v1/-v2`; the Phase C pass rules; the trial
freeze and everything fingerprinted in `backend/tests/trial_freeze.json`; Amendment 2 and the Amendment 3 drafts; the lab's own
rules; no number, threshold, seed or window anywhere.

---

## 13a. Disclosure: known price-data steps (added 2026-11-06, widened 2026-11-07; disclosure only)

Known mechanical price steps (splits, bonuses, demergers and spin-offs that the stored daily prices do not fully adjust) exist in the data Phase B reads. They are disclosed here, before any result exists. Phase B settings, stock lists, the split file, windows and every signed rule are not changed, and **no price is corrected, replaced or re-fetched for Phase B: results are disclosed, not corrected.** Source of every figure: `docs/brain/evidence/corporate_actions/phase_b_anomaly_impact.md` (counts of bar dates only; no price, return, model score or candidate output was read) with `verify49_report.md` and `corporate_actions_audit.md` in the same folder.

**Inside the 49 scored stocks (all three candidates).** ITC 2025-01-06 (+6.3%): 0 label days, 231 feature days (1.24% of scored stock-days at the 252-bar lookback), test folds 1 to 13, in training in all 20 folds. HINDUNILVR 2025-12-05 (-5.0%, stored unadjusted for the Kwality Wall's demerger): 14 label days (0.075% of the 18,571 scored stock-days, fold 11), 171 feature days (0.92%, folds 11 to 20), in training in folds 12 to 20. RELIANCE 2023-07-20 (-3.3%): nothing inside the development window.

**In B2's extra training set of 128 stocks (training only, never scored).** ABFRL 2025-05-22 (-55.9%, folds 5 to 20), SANOFI 2024-06-13 (-28.0%, all folds), VEDL 2026-04-30 (-32.9%, folds 18 to 20), BAJAJELEC 2023-09-14 (+38.8%, unexplained; 14 label rows, 0.008% to 0.014%, and 251 feature rows, 0.15% to 0.24%, of B2 training in every fold). Share of training rows touched by any step: 0.92% to 1.39% for B1 and B3, 0.66% to 0.88% for B2.

**In the reject set (never trained on; used only for the reject-set check).** Inside the development window: ALLCARGO 2025-11-12 (-60.1%), TRIVENI 2026-07-22 (-41.6%), SIEMENS 2025-04-07 (-25.1%), TMPV 2025-10-14 (-13.1%): 56 reject-set stock-days (0.115%) have a path crossing a step. Before the window, never scored: NMDC (2022), SCI (2023) and an earlier ALLCARGO event (2023).

**Measured impact (counts and structural bounds only).** The label channel touches 0.075% of scored stock-days. A wrong net return E on one stock on one day moves the mean daily edge by at most A x E x (1/m + 1/49) / N (A affected days, m picks that day, N days with ideas). For HINDUNILVR (A = 14) the bound on a top-5 edge at N = 379 days is 0.016 percentage points for a price-level error of 1.91 points and 0.098 for a worst-case 12-point flip (0.059 and 0.37 at N = 100; 0.20 and 1.2 at N = 30); a one-idea-per-day candidate such as B1 is bounded at 0.45 points (12-point flip, N = 379), a figure that needs the stock to be picked on all 14 days. The reject-set average moves by at most 0.014 percentage points. A false loss lowers the every-stock baseline, so candidates would look slightly better than they are (the optimistic direction). The 30-trading-day minimum counts days with ideas and does not depend on returns, so prices cannot change it. **The feature channel (HUL 171 and ITC 231 stock-days) cannot be bounded tightly without model scores and was deliberately NOT tested, because Phase B results are sealed until the runs; B3's breadth series was likewise not looked at.** Conclusion of the note: negligible in the realistic case, cannot-tell only for the feature channel and an extreme concentration case.

**Owner decision (2026-11-07, relayed in the working session; confirmed by the owner's signature of this text).** Accept and disclose. The owner's read-only fresh fetch for HINDUNILVR and BAJAJELEC is **not required**: the exclusion and the disclosure are final for Phase B, and nothing a later fetch shows changes Phase B. Fetching fresh prices, or excluding stocks or rows, would change the locked inputs (split hash `bc8878f2...`, `phase-b-settings`) and would need a new signed protocol version; neither was chosen.

## 14. Decisions

All six owner decisions A to F are written into section 3. Remaining for the owner at signing: (i) confirm or rename the tag
`phase-b-completion-v1`; (ii) fill the merge-commit hash in section 11 after the code is on `main` (the safe order of merges, deploys and checks is in
`phase-b-signature-package.md`, section 5; one combined code PR is recommended); (iii) sign. Nothing else is open.

Signature lines (leave blank until signed):

Owner: ______________________   Date (IST): ______________

Tag name and commit: ______________________

[V] The 2026-11-05 additions (report, idempotent re-run, hygiene, NO SURVIVOR notice) are covered by unit tests with fake git
(166 pass across the finish, wrapper and freeze tests); they were **not** re-run in the earlier scratch-repo rehearsal and have never touched real data.

[V] Not done in drafting this text: nothing was committed, tagged, pushed, signed, merged or deployed; Phase B, the finish command
on real data and the lab were not run; no prod write, Kite call or `.env` read.
