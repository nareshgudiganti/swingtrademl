# System Versioning (v1 / v2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the whole trading configuration a named, stored version that can be switched and rolled back at runtime, so trying something new is never a one-way door.

**Architecture:** A version is a row, not a branch. `SystemVersion` holds a validated config (which trained model each cap tier runs, which stocks get shortlisted, whether regime switching is on). Exactly one version is `trading`; the others run `shadow`, producing signals and zero orders through the existing `execution_mode="advisory"` path. Every Signal, Trade and Position is stamped with the version that produced it, so switching never mixes evidence. Risk and exit rules are not part of a version and cannot be expressed by one.

**Tech Stack:** Python 3.12, SQLAlchemy 2.0, Alembic, Pydantic v2, FastAPI, pytest.

**Spec:** This plan. Decisions settled with the owner 2026-09-28; recorded in memory as `project-system-versioning`.

## Global Constraints

- Tests run as `cd backend && ./.venv/Scripts/python.exe -m pytest`. A bare `python -m pytest` fails.
- Postgres must be up via `docker-compose` on port **5433**. When it is down, DB tests hang silently for ~264s. A port check is not a liveness check.
- Line length 110 (ruff).
- **A version may never contain** `stop_loss_pct`, `take_profit_pct`, `risk_per_trade_pct`, `max_drawdown_pct`, `sector_cap_pct`, `cash_floor_pct`, `max_position_pct`, `max_positions`, `time_stop_days`, `scale_out_at_pct`, `scale_out_fraction`, `position_sizing_mode`. Enforced by `extra="forbid"`, not by review.
- **Stage 1 must not change behaviour.** With v1 current, a scan produces byte-identical output to today.
- Switching a version never writes to `Position`. Open positions run to their own stop, target and time limit.
- The trade spec is fixed in every version: +8% before −4%, 15 trading days, half out at +5%, 30-day time stop, 15% drawdown halt.

## Review Focus

Five things the design implies but no single task's happy path exercises:

1. **Two versions marked `trading` at once** — a partial failure during promotion must never leave the book ambiguous about which config it is running. Pinned in Task 4.
2. **A version naming a model that does not exist** — v2 names the barrier models before they are deployed; promoting it must refuse loudly rather than fall through to an arbitrary active model. Pinned in Task 4.
3. **Rows written before versioning existed** — every historical Signal and Trade has a null version and must stay readable, counted under "unversioned" rather than silently attributed to v1. Pinned in Task 5.
4. **A shadow version starving the trading version of position slots** — advisory strategies already deflate the per-strategy slot share (`risk.active_strategy_count`), and each shadow version adds three more. Pinned in Task 6.
5. **Promotion while positions are open** — the newly demoted version's open positions must keep their original exit rules, and the newly promoted version must not adopt them. Pinned in Task 4.

---

## Stage 1 — Versioning machinery, v1 registered, nothing behaves differently

The whole stage is invisible in the UI except a new version badge. That is deliberate: it lets the switch exist and be tested before anything is riding on it.

### Task 1: Stop the no-name model lookup from guessing — **DONE 2026-09-28**

**Files:**
- Modify: `backend/src/swing_trade_ml/ml/registry.py` (`get_active_model`)
- Modify: `backend/src/swing_trade_ml/api/v1/endpoints/portfolio.py:133`, `api/v1/endpoints/system.py:123`, `cli.py:289`, `ml/predict.py:483`
- Test: `backend/tests/test_active_model_requires_a_name.py`

**Why first:** this is live today. `get_active_model(db, None)` returns whichever model was activated most recently across all three cap tiers. Three are active at once, so the answer was decided by a 22-millisecond difference in activation time. It reaches the status header (`system.py:123`), the position-horizon lookup (`portfolio.py:133`), the CLI and `accuracy_at_horizon`.

**Corrected during implementation:** an earlier draft of this plan claimed `real_trading` was therefore scoring real holdings with the small-cap model. It is not. `BaseStrategy.__init__` merges `default_params` before the stored params (`self.params = {**self.default_params, **(config.params or {})}`), so `real_trading`'s empty `params` resolves to `swing_classifier`, the large-cap model. The API listing shows `model_name=None` because that is the *stored* column, not the resolved value. **Do not "fix" this** — the strategies are fine; only the nameless lookups were wrong.

- [ ] **Step 1: Write the failing test**

```python
def test_a_nameless_lookup_does_not_pick_an_arbitrary_tier(db_session):
    """Three models are active at once, one per cap tier. Asking for "the"
    active model has no correct answer, so it must not invent one by
    activation order — 22 milliseconds decided which tier scored real money."""
    _active(db_session, "swing_classifier", "v2", activated="2026-08-28T14:08:08.757Z")
    _active(db_session, "swing_classifier_midcap", "v2", activated="2026-08-28T14:08:08.770Z")
    _active(db_session, "swing_classifier_smallcap", "v1", activated="2026-08-28T14:08:08.779Z")

    with pytest.raises(ValueError, match="names a model"):
        get_active_model(db_session)


def test_a_named_lookup_still_returns_that_tier(db_session):
    _active(db_session, "swing_classifier", "v2")
    _active(db_session, "swing_classifier_smallcap", "v1")
    assert get_active_model(db_session, "swing_classifier").version == "v2"


def test_active_models_lists_every_tier(db_session):
    """What the status header actually wants: all of them, not one."""
    _active(db_session, "swing_classifier", "v2")
    _active(db_session, "swing_classifier_midcap", "v2")
    assert {m.name for m in active_models(db_session)} == {
        "swing_classifier", "swing_classifier_midcap"
    }
```

- [ ] **Step 2: Run to verify it fails**

`./.venv/Scripts/python.exe -m pytest tests/test_active_model_requires_a_name.py -v` — expect `ValueError` not raised, and `ImportError` for `active_models`.

- [ ] **Step 3: Implement**

```python
def get_active_model(db: Session, name: str | None = None) -> MLModel | None:
    """The active model for one name.

    `name` is required whenever more than one model is active. Three are —
    one per cap tier — and picking the most recently activated one meant a
    22ms difference in activation time decided which model scored real
    holdings. Callers that genuinely want "all of them" use active_models().
    """
    stmt = select(MLModel).where(MLModel.status == ModelStatus.ACTIVE)
    if name:
        return db.execute(stmt.where(MLModel.name == name).limit(1)).scalar_one_or_none()

    rows = list(db.execute(stmt).scalars().all())
    if len(rows) > 1:
        raise ValueError(
            f"{len(rows)} models are active ({', '.join(sorted(r.name for r in rows))}); "
            "the caller names a model or uses active_models()"
        )
    return rows[0] if rows else None


def active_models(db: Session) -> list[MLModel]:
    """Every active model, one per name, ordered by name."""
    return list(
        db.execute(
            select(MLModel).where(MLModel.status == ModelStatus.ACTIVE).order_by(MLModel.name)
        ).scalars().all()
    )
```

- [ ] **Step 4: Fix the four callers.** `system.py` and `portfolio.py` use `active_models()`. `cli.py` prints all. `predict.py:483` takes the name from its caller.
- [ ] **Step 5: Run the full suite.** `./.venv/Scripts/python.exe -m pytest -q` — expect no failures.
- [ ] **Step 6: Commit** — `fix: stop the nameless model lookup picking a cap tier by activation order`

Not done, and deliberately: `real_trading`'s stored `params` stays `{}`. Writing `swing_classifier` into it would change nothing at runtime and would need a data migration to make the existing prod row match. The legibility problem — an API listing that reads `model_name=None` — is better solved by Task 7 showing the resolved model, not by a migration.

### Task 2: The `SystemVersion` table

**Files:**
- Modify: `backend/src/swing_trade_ml/db/models/safety.py` (it already holds the owner-operated state)
- Create: `backend/alembic/versions/<rev>_system_versions.py` — `down_revision` must be the then-current head
- Test: `backend/tests/test_system_version_model.py`

**Interfaces — Produces:**

```python
class SystemVersion(Base, TimestampMixin):
    __tablename__ = "system_versions"
    id: Mapped[int]
    slug: Mapped[str]            # "v1", "v2" — unique, what the owner says out loud
    label: Mapped[str]           # "Current live system"
    description: Mapped[str | None]
    status: Mapped[str]          # trading | shadow | retired
    config: Mapped[dict]         # a VersionConfig, validated on read
    activated_at: Mapped[datetime | None]
```

Tests: slug is unique; status defaults to `shadow` so a newly created version can never start out spending money; config round-trips through a commit.

### Task 3: `VersionConfig` and the locked boundary

**Files:**
- Create: `backend/src/swing_trade_ml/services/versioning.py`
- Test: `backend/tests/test_version_config_boundary.py`

```python
class VersionConfig(BaseModel):
    """Everything a version is allowed to change.

    extra="forbid" is the boundary. A config carrying stop_loss_pct,
    risk_per_trade_pct, sector_cap_pct, time_stop_days or max_drawdown_pct
    raises at load — not at use, not in review. There is no field for any of
    them, so a version cannot express one even by accident.
    """
    model_config = ConfigDict(extra="forbid", frozen=True)

    models: dict[Literal["large", "midcap", "smallcap"], str]
    selection: SelectionConfig | None = None      # None = no shortlist, v1's behaviour
    regime_switching: bool = False
    min_confidence: float | None = Field(default=None, ge=0.50, le=0.95)
```

The boundary test mirrors the one planned for `SelectionProfile`, and adds the structural assertion that matters most:

```python
LOCKED_KEYS = frozenset({
    "stop_loss_pct", "take_profit_pct", "risk_per_trade_pct", "max_drawdown_pct",
    "sector_cap_pct", "cash_floor_pct", "max_position_pct", "max_positions",
    "time_stop_days", "scale_out_at_pct", "scale_out_fraction", "position_sizing_mode",
})

def test_no_locked_knob_is_even_a_field():
    assert LOCKED_KEYS.isdisjoint(VersionConfig.model_fields)

def test_each_locked_knob_is_rejected_by_name():
    for key in LOCKED_KEYS:
        with pytest.raises(ValidationError):
            VersionConfig(**{**VALID, key: 0.04})

def test_the_risk_layer_never_learns_about_versions():
    """The assertion that survives a future refactor: the moment risk.py or
    execution.py imports the versioning module, a selection knob has become a
    risk knob."""
    assert "versioning" not in _imported_module_names(risk)
    assert "versioning" not in _imported_module_names(execution)
```

### Task 4: Promote and demote, with one trading version at a time

**Files:**
- Modify: `backend/src/swing_trade_ml/services/versioning.py`
- Test: `backend/tests/test_version_promotion.py`

```python
def current_version(db: Session) -> SystemVersion | None: ...

def promote(db: Session, slug: str) -> SystemVersion:
    """Make one version the trading version and demote the incumbent to shadow.

    Both writes happen in one transaction, the same guarantee
    ml/registry.py::activate_model gives for models: there is never a window
    where two versions are trading, or none is.

    Refuses a version naming a model that is not active, because the
    alternative is falling through to an arbitrary model — exactly the defect
    Task 1 removed. v2 names the barrier models before they exist, so this
    refusal is the normal case until Stage 2 lands.

    Does not touch Position rows. Open positions keep the stop, target and
    time limit they were opened with.
    """
```

Tests, in this order:
- promoting demotes the incumbent to `shadow`, in one transaction
- exactly one `trading` version exists afterwards, asserted by query not by construction
- promoting a version whose models are not active raises, and **the incumbent is still trading** (the partial-failure case from Review Focus 2)
- promoting with open positions leaves every `Position.stop_loss`, `take_profit` and opened-at strategy untouched (Review Focus 5)
- promoting the already-trading version is a no-op, not an error

### Task 5: Stamp the evidence

**Files:**
- Modify: `db/models/trading.py` (`Strategy`, `Signal`, `Trade`, `Position` gain `system_version_id`, nullable, indexed)
- Modify: `services/engine.py`, `services/execution.py` (write it at creation)
- Create: migration
- Test: `backend/tests/test_version_evidence_separation.py`

Nullable because every historical row predates versioning. Tests:
- a signal generated under v1 carries v1's id
- after promoting v2, new signals carry v2's id and **v1's existing rows are unchanged**
- per-version stats never mix: `version_stats(db, "v1")` and `version_stats(db, "v2")` sum to the total, and neither includes the other's rows
- historical null-version rows are reported under `unversioned`, never folded into v1 (Review Focus 3)

### Task 6: Bootstrap v1 from what is actually running

**Files:**
- Modify: `backend/src/swing_trade_ml/services/versioning.py` (`bootstrap_v1`)
- Test: `backend/tests/test_v1_bootstrap_is_a_no_op.py`

Idempotent. Reads the live strategies, writes v1 with their model names, `selection=None`, `regime_switching=False`, status `trading`, and back-fills `system_version_id` on existing strategy rows.

**The test that matters:** run a full scan against a seeded DB with v1 current and assert the signals are identical — same symbols, same confidences, same verdicts — to a scan with the versioning code paths disabled. Stage 1 is defined as *behaviourally invisible*, and this is the proof.

Also assert (Review Focus 4) that registering a shadow version does not reduce the trading version's position-slot share — it must be excluded from `risk.active_strategy_count` exactly like any other advisory strategy.

### Task 7: API and the status header

**Files:**
- Create: `backend/src/swing_trade_ml/api/v1/endpoints/versions.py`
- Modify: `api/v1/router.py`, `api/v1/endpoints/system.py`, `frontend/src/api/types.ts`

```
GET    /api/v1/versions                 list, with each one's status and evidence count
GET    /api/v1/versions/current         what is trading right now, and why
POST   /api/v1/versions/{slug}/promote  switch; 409 if its models are not active
```

The status header stops showing `get_active_model(db)` and shows the current version plus its three models. That removes the "smallcap by default" confusion at its source.

**Stage 1 definition of done:** `v1` is registered and trading, a scan is byte-identical to today, `POST /versions/v1/promote` is a no-op, and promoting a not-yet-ready v2 refuses cleanly.

---

## Stage 2 — Train and deploy the barrier models *(critical path)*

Nothing in Stages 3–5 can produce evidence until this lands. Verified 2026-09-28: prod holds 20 models, every one `label=endpoint, target=0.02, horizon=5`, and **no barrier model or shadow strategy exists at all**. The 2026-09-15 retrain never reached the droplet.

Train the three cap-tier models on the existing +8%/−4%/15-bar barrier label with walk-forward validation, register them under `swing_classifier_barrier` / `_midcap_barrier` / `_smallcap_barrier`, and deploy the artifacts to prod. Set `MODEL_BACKUP_DIR` first so the artifacts are protected the moment they exist — this is the failure that already happened once.

Open question for the owner before this starts: in all three tiers a higher-scoring newer version sits archived while an older one is active (`swing_classifier` v12 at 0.549 archived, v2 at 0.528 active). Confirm whether that was a deliberate rollback.

## Stage 3 — v2 as a shadow

Register v2 with the barrier models, `selection=None`, `regime_switching=False`. Materialise its three advisory strategy rows. It produces signals and places no orders. This isolates one change — the model's question — so the comparison against v1 means something.

Promotion gate: 30+ resolved signals and calibration beating v1 over the same window.

## Stage 4 — Selection and regime into v2

The Track 2 work from the consolidated roadmap: feature cache, the advisory slot-share fix, `SelectionProfile`, the regime→profile resolver and the shortlist step. Added to v2's config, still shadowing, still comparable against v1.

## Stage 5 — Per-version reporting and the switch UI

A version comparison screen — each version's resolved signals, win rate, calibration and P&L side by side, with the baseline always visible and no win-rate badge below 30 resolved signals. The promote button lives here.

---

## Verification

1. **Invisibility:** Stage 1 scan output is identical to `main`'s for the same seeded DB.
2. **Boundary:** every locked key raises `ValidationError`; `risk.py` and `execution.py` do not import `versioning`.
3. **Atomicity:** kill the transaction mid-promote; exactly one version is still `trading`.
4. **Rollback:** promote v2, generate signals, promote v1 again — v1 trades, v2 keeps its own accumulated record intact, and open positions from either are untouched.
5. **Refusal:** `POST /versions/v2/promote` returns 409 while the barrier models are absent.
6. **Prod:** `GET /versions/current` names v1 and its three models, and the status header no longer reports a cap tier as "the" model.
