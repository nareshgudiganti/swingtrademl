# Model activation: readiness checklist and rollback runbook (DRAFT for owner review)

Status: written 2026-11-09. A draft. It activates nothing and changes no code. **Passing tests does not authorise activation.**
Three stages stay separate: **implementation** (code exists) → **evaluation** (evidence under a signed protocol) → **activation**
(a model drives real decisions). Only the owner can move a model from evaluation to activation, in writing.

## 1. What "activation" means in this code (read from the code on 2026-11-09)

| Path | Code | What it does | Gate today |
|---|---|---|---|
| Promote a model version | `POST /api/v1/ml/models/{id}/activate` → `ml/registry.activate_model` | Marks that version ACTIVE and archives the previous ACTIVE one of the same name; clears the prediction cache | Only "model status is TRAINED or ARCHIVED". Route is behind the app's sign-in (`protected`). **No evidence check, no owner-only check, no `model_role` check was found in these functions.** |
| Switch a strategy on | `POST /api/v1/strategies/{id}/activate` | Sets `is_active = true` | None beyond sign-in |
| Shadow lane model | `shadow_lanes/lane_job.py`, setting `LANE_SHADOW_MODELS` (JSON slot → model id) | Lane scores with the owner-chosen model, shadow only, never trades | Needs `LANE_SHADOW_ENABLED=true`, an owner-chosen model, and `model_role == "final"` (`services/lane_slots.py`). Default off. |
| Brain stage (shadow → manual approval → auto) | M18, `docs/brain/GO_LIVE.md` | Brain ideas become orders only after manual approval, later auto | Owner's call; prod is in shadow stage |
| Real orders | real-orders switch | Off on prod (read-only check 2026-11-07) | Owner only; `TRADING_MODE` stays `paper` |

**Gap to close before any activation (proposal, needs owner approval because it touches model-decision code):** the model-promotion
route has no evidence gate. Proposed design: `activate_model` refuses unless (a) the model's `model_role` is `final`, and (b) an
approval record exists in the repo (`docs/brain/evidence/activation/<model-id>.md`) naming the model id, its file hash and the
evidence tag, signed by the owner. This only ever **blocks**; it cannot make a decision more aggressive. Not built. It would need a
test and the owner's approval before reaching `main`.

## 2. Evidence the owner set (all must hold before an activation REQUEST is made)

1. **Out-of-sample:** a signed protocol was run once on held-back data, result recorded and tagged (Phase B `phase-b-result`; 15D
   lab per `sl-protocol-v1.1`; SX5 per its signed protocol). A failed result stays on record and the model is not promoted.
2. **Forward evidence:** a forward lane (h05 for 5D) reached its verdict at fixed maturity (about 40 matured days or more; INCONCLUSIVE
   is normal until late December or later) with no missed-session or integrity events.
3. **Realistic economics:** net of fees and slippage, same dates and stocks as the baseline, compared with the simple-momentum and
   no-trade baselines. Backtest, forward-research and paper P&L are never combined into one profit figure.
4. **Acceptable risk:** drawdown and loss within the settled rules (+8% / −4%, half out at +5%, ≤15 trading days, 15% drawdown halt,
   25% sector cap).
5. **Integrity:** model file hash equals the recorded hash; train/serve feature parity checked (the known `obv_slope` mismatch on the
   5D models must be resolved or accepted in writing); no sealed-trial or signed-rule edit.

## 3. Pre-activation checklist (every line PASS, evidence attached, then the owner decides)

- [ ] Section 2 items 1 to 5 documented in one evidence note with tags and hashes.
- [ ] Full backend and frontend suites green on the exact commit; CI green including the secret scan.
- [ ] Production flags read directly on the droplet and recorded (names and values only): `TRADING_MODE=paper`, `ALLOW_LIVE_TRADING`,
      `TESTING_NO_LIMITS`, `BRAIN_ENABLED`, `LANE_SHADOW_ENABLED`, `LANE_SHADOW_MODELS`.
- [ ] Current ACTIVE model ids and versions written down (this is the rollback target).
- [ ] Offsite backup of the current models exists and a restore was checked (`docs/BACKUP-OFFSITE.md`).
- [ ] Deploy only after 16:30 IST on a weekday; a restart is expected.
- [ ] The owner's written approval names: model id, version, file hash, scope (shadow lane, brain stage, or promotion), and the date.

## 4. Activation steps (only after the owner's written approval; typed by the owner or by Claude on explicit instruction)

1. Record the before-state: `GET /ml/models` (ACTIVE ids), strategies list, flags.
2. Take the smallest step that fits the approval. Order of preference: shadow lane only → brain manual-approval stage → promotion.
3. Do the step; clear caches (the promote route does this); confirm the new model id is the one answering.
4. Watch the first sessions: predictions produced, no errors, hard limits unchanged, Telegram health message arrives.

## 5. Rollback (any time, no approval needed to make things SAFER)

| Situation | Action | Why it is safe |
|---|---|---|
| A promoted model misbehaves | `POST /api/v1/ml/models/{previous_id}/activate` (ARCHIVED models can be re-activated); this archives the bad one | previous version is kept in the registry |
| Strategy should stop | `POST /api/v1/strategies/{id}/deactivate` | no new entries; open positions keep their stops |
| Shadow lane misbehaves | set `LANE_SHADOW_ENABLED=false`, restart | lane is shadow-only and never trades |
| Brain should stop deciding | brain rollback in `docs/brain/GO_LIVE.md` (positions are kept) | per M18 decisions |
| Whole release bad | redeploy the previous `main` commit after 16:30 IST; tag `v1` (`64fcb05`) is the frozen reference | see `docs/DEPLOY.md` |
| Anything touching orders, sizing, stops or limits | stop; paper mode only; needs a test and owner approval | CLAUDE.md risk rules |

## 6. Known open items that block any activation today

- No model has completed Phase B, the 15D lab, or SX5; h05 is inconclusive until about late December or later.
- The promotion route has no evidence gate (section 1).
- `obv_slope` train/serve mismatch on the 5D models (inside the sealed trial; owner decision after the trial).
- TMCV not scorable until it has 252 bars (about 17 to 18 Nov).
- Mid-cap model-file hash is a recorded value; the file was not available to verify.
- Production flags have not been read directly on the droplet yet.
