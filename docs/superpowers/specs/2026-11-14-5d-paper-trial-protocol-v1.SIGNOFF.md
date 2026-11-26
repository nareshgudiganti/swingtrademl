# Sign-off record: 5D paper trial protocol v1 (#279)

| Field | Value |
|---|---|
| Spec file | `2026-11-14-5d-paper-trial-protocol-v1.md` (revision 4), committed unchanged |
| sha256 at sign-off | `c5cfbaf1c137311c31559a9da7b7cda52004c83f4badc4f8b64e4e0f965f934f`. This is the hash of the file as stored in git (LF line endings): verify with `git show HEAD:<path> \| sha256sum`. A Windows checkout may convert to CRLF and give a different hash for the same text |
| Approved by | Owner (Naresh), in the Claude Code session, words: "approve as recommended" |
| Date and time | 2026-11-25 00:57 IST |
| What was shown | The minimum sign-off table and the R4 research budget (`docs/model-audit/2026-11-24-279-approval-table.md`, sections A, C and E) |

The spec file is not edited to add this signature: editing it would change its sha256. Any change to the rules is a new file (`-v2.md`).

**Note (2026-11-26).** The spec file's own header still reads "DRAFT FOR OWNER SIGN-OFF" on purpose: the file is sha256-pinned (`c5cfbaf1…934f`) and is not edited. This record, not the header, is the evidence of approval. Exact time of the typed reply: 2026-11-25 00:57:25 IST (issue #279 comment of 26 Nov).

## Approved (as recommended)

- **Section H:** H-1 (this file governs, separate from h05), H-2 (+2% / −4% from the entry fill, max 5 sessions, stop first, both-levels candle = stop, gaps at the open), H-2b (model target: session-5 close at least signal close × 1.02), H-7 (SELECTION and ECONOMIC, never merged), H-11 (60-session runs, at least 40 matured days, shortfall at most 20%), H-11b (per verdict: at least 2 PASS, no FAIL, pooled range above 0; a PASS is evidence for the owner, never automatic promotion).
- **Requirement sections:** 1 (purpose: top-5 ranking signal, not a probability), 3 (fixed 52-stock universe, results labelled "selection-biased exploratory evidence"; point-in-time membership required before any promotion claim), 4 (one versioned input formula for training and serving; a different serving formula is a new model version; score only completed bars; save prediction inputs write-once), 14 (gates R0-R7; owner approval at R1, R3 for active models, R4 once, R7 in writing).
- **R4 research envelope:** local machine and local dev database only, no production data. 5D only: large cap (#219) first, then #220, then mid/small (#221/#222). Today's 53 inputs plus the corrected `obv_slope` as its own version. LightGBM and logistic regression, with momentum as the comparison. At most 6 candidates, each fingerprinted before training. Judged out-of-sample, after costs, against every eligible stock, momentum and model 2 as served. Results recorded in `docs/model-audit/`. **Nothing activated, promoted or deployed.**

## Not yet signed

- 11.4 and 11.5 (portfolio and display rules for the paper trial). Needed before the paper trial is built (#321).
- The remaining DELEGATED rows stand as recommended defaults, per the approval table.

## Unchanged by this approval

The h05 trial (its own protocol, code, data and evidence). No model is trained in production, activated, replaced, retired or promoted. The database changes (trial roles, the provenance columns) still need their own migration approval.
