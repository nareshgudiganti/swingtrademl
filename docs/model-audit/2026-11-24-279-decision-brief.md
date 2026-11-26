# #279 Model requirements: decision brief (Track A, Feature 1 #218)

Written 2026-11-24 (IST). Read-only. **#279 is NOT signed.** Nothing here approves it.

Sources read: issue #279 body (0 comments on GitHub), local draft spec
`docs/superpowers/specs/2026-11-14-5d-paper-trial-protocol-v1.md` (untracked, revision 4, 321 lines,
sha256 `c5cfbaf1c137311c31559a9da7b7cda52004c83f4badc4f8b64e4e0f965f934f`), `#415` status comment.

## 1. What is already approved (and what is not)

| Item | Status | Evidence |
|---|---|---|
| Existing models and the running h05 trial stay untouched | Approved, standing rule | #279 intro, #272 owner comment 2026-11-15 |
| 5D first; 10D deferred / research-only; 15D behind its lab gate | Approved | #279 intro, DEV-QUEUE P0 (23 Nov) |
| 5D rule numbers +2% / -4% / 5 sessions as one versioned config `hz-rules-v1` | Merged (#449, `770cd13`), values only, not the trial protocol | #415 comment 2026-11-23 |
| Section H recommended values "approved for drafting" | **Drafting only.** The spec header says "approved by Naresh on 2026-11-14 for drafting this spec". No GitHub record (0 comments on #279) | spec line 6 |
| Section H as binding rules, sections A-G frozen, sha256 recorded | **Open: needs owner sign-off** | spec sign-off block blank (line 321) |
| E2 model requirement sections 1-14 (purpose, universe, inputs, algorithm, ... approval gates) | **Open: all 14 unticked** | #279 E2 |

Note: memory recorded the draft as revision 3 with sha `0df1ee71…`. The file on disk is now revision 4 with the sha above. Sign against the file on disk.

## 2. Decisions needing sign-off (H-1 … H-15), recommendation and why

| # | Decision | Recommended | Why |
|---|---|---|---|
| 1 | Which protocol governs the new 5D paper trial | The v1 spec file, frozen by sha256, separate from h05 | One immutable rule book; approving it does not approve or change h05 |
| 2 | Reference exit rule | h05 trade rule: +2% / -4% from the entry fill, max 5 sessions, stop checked first, both-levels candle = stop, gaps fill at the open | Same code path as h05 (`h05_rules.py:107-174`) and `hz-rules-v1`, so results compare. Cautious on ambiguity |
| 2b | Model-target anchor | Signal-day close; session-5 close at least +2% | This is what model 2 was trained to predict. Track B is verifying the label in code |
| 3 | Fill window | Session-1 open; the row must be recorded before that session opens, otherwise UNRESOLVED `recorded_late` | Stops back-dated fills |
| 4 | Large-cap slippage | 10 bps per side | Conservative for NIFTY-50 names. It's an assumption, not measured, and the spec says so |
| 5 | Cost wording | Accept about 44 bps round trip; fix the h05 text only after the h05 trial ends | The code already charges correctly. Only the h05 text is wrong (says 15.9 bps for a Rs 15.93 flat fee) |
| 6 | Rs 1,00,000 | Reference order size, charges on top; portfolios keep their own cash caps | Matches `h05_rules.py:134,173` |
| 7 | Pass gates | SELECTION and ECONOMIC only, never merged into one word | "Ranks better than average" and "makes money after costs" are different claims |
| 8 | Momentum baseline | 20-session split/bonus-adjusted return, ties A to Z, comparison only (not a gate) | Cheap, honest yardstick. Making it a gate can wait for evidence |
| 9 | Random five | Comparison only, 200 draws, seed 7, pools sorted by symbol, seed/pool hash stored | Fixes the h05 non-reproducible ordering (`h05_report.py:303`) in the new trial only |
| 10 | Matured day | At least 10 **scored** stocks and at least one finished counted pick; ledger keeps every eligible stock | Matches the h05 code (`h05_report.py:99-102`) |
| 11 | Minimum evidence | 60-session runs, at least 40 matured days, short top-5 on at most 20% of days | Same as h05. Enough days for a block bootstrap |
| 11b | Three-run rule | Per verdict: at least 2 PASS, no FAIL, pooled range above 0; an INCONCLUSIVE run is final but neither | Stops one lucky run deciding |
| 12 | UNRESOLVED picks | More than 10%: warning only. More than 20%: run INCONCLUSIVE (new rule, not in h05) | Moves toward caution if data gaps cluster in picks |
| 13 | Repeat rule | Blocked D+1..D+4, counts again from D+5; memory resets at run boundary | Same as the h05 code; only the wording is corrected |
| 14 | Separate cap-group / pattern models | Defer until the 5D large-cap verdict exists | Not enough evidence yet to justify more models (#220) |
| 15 | Financial-year start | April | Indian FY |

**Also needs a yes/no:** the six clarifications in spec section 11 (revisions 2-4: repeat wording, market-check meaning, three cohorts, stale marks, read-only h05 access by DB permissions, stale cut-off from session 0). Recommended: accept. None of them changes how a reference outcome is calculated.

## 3. Conflicts with the frozen h05 trial

No rule in the spec changes h05 code, data or text. These are the points where the two meet:

| # | Point | Risk | Proposed handling |
|---|---|---|---|
| C1 | **Model 2 `obv_slope` train/serve mismatch** (since 2026-10-05). The new trial scores with prod model 2 as served, so it inherits the mismatch | The trial would measure a model that isn't the one that was trained | **Add to sign-off:** state that v1 measures "model 2 as served" and record the input definition and version on every score row. Any fix is a separate, versioned candidate (#272), never an edit. Track C will size the effect |
| C2 | h05 text vs code differences (cost total, "eligible" vs "scored", pool order) | Two documents disagree | New trial follows the h05 **code**. The h05 text is fixed only after the h05 trial (#342 gated) |
| C3 | Shared tables | A bug could write into sealed tables | Spec section 9: separate writable storage, h05 read via a SELECT-only role. Needs a test before build |
| C4 | Universe = frozen 52-stock large-cap h05 list | That list is fixed today. It is not point-in-time membership as #219 asks, so there is some survivorship bias | Accept for v1 and label it in reports. Point-in-time membership goes to the identity work (#389) and #219 research |
| C5 | Same model, same days, two trials | h05 and the 5D trial results are not independent evidence | Never pool them, and report them separately |

## 4. Proposed research and promotion gates (Feature 1)

| Gate | What | Exit condition (evidence) | Owner approval |
|---|---|---|---|
| R0 | As-built evidence: #267, #269-#271 (Track B), #226/#272 (Track C) | Docs in `docs/model-audit/` with file:line and artifact sha256; gaps listed | no (read-only) |
| R1 | Sign #279: H-1..H-15 plus section 11, freeze the spec by sha256, commit it | Signed sha in the file and on #279 | **yes** |
| R2 | Answer E2 sections 1-14 for 5D large cap | Each section has a written answer and a test method | **yes** |
| R3 | #280 gap table: requirement vs as-built, keep / retrain / replace / retire per model | Table with source refs and baseline SHA; owner decision per row | **yes** |
| R4 | Pre-register each 5D candidate (#219-#222): new versioned spec, inputs verified for train = serve parity | One file per candidate, hashed before any training | **yes** |
| R5 | Offline research: local walk-forward and replay (#262/#329), out-of-sample, after costs, vs every-stock and momentum | Reproducible run (seeded, hashed data), sample sizes, limitations | no (local only) |
| R6 | Forward shadow under the signed protocol, 3 × 60 sessions | SELECTION / ECONOMIC verdicts per G2 | no (shadow) |
| R7 | Promotion / activation | Written owner decision. Never automatic | **yes** |

10D (#223) and 15D (#224, #225) stay at R5 at most until their own validation gates are approved.
Nothing in R0-R6 trains in production, activates a model, or touches sealed trial models or evidence.

## 5. What I need from the owner

1. Sign or edit H-1..H-15 and the section 11 clarifications (recommended: as above).
2. Accept C1 handling: measure "model 2 as served" and record the input version on every score row.
3. Approve gates R0-R7 as the Feature 1 path.
