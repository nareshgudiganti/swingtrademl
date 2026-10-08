# TradeMind — solution overview (vision, architecture, gaps)

**Purpose:** Single reference for what TradeMind is meant to be, how the approved build maps to that
vision, and what is still missing. Complements day-to-day status in
[`CURRENT-STATE.md`](CURRENT-STATE.md) and Service 1 detail in
[`architecture-gaps.md`](architecture-gaps.md).

**Last updated:** 2026-10-05  
**Production baseline:** GitHub `main`; brain in **M18 practice (shadow)** since 2026-10-04.

---

## 1. What we are building (one sentence)

**TradeMind** turns **trustworthy, point-in-time market data** into **cautious, explainable swing
ideas**, proves them in **shadow and learning loops** against version 1, and only then allows
**owner-controlled** paper or live execution — all on **one backend** a single developer can operate.

---

## 2. End-to-end workflow

This is the operational story behind product diagrams and the build book:

```text
Collect market data
    → Analyze with TradeMind Brain (8 steps)
    → Generate opportunities (TRADE / WATCH / WAIT / AVOID)
    → Apply risk & allocate (size, gates, banner)
    → Execute (paper / shadow / approval / auto)
    → Learn from outcomes (failures, drift, proposals)
```

**Settled rules (do not change without the owner):**

- Horizon ≤ **15 trading days**; **+8%** target, **−4%** stop, half out at **+5%**.
- **Paper first** in prod (`TRADING_MODE=paper`); live auto is owner-only after M18 gates.
- **Service 1 prepares data; the brain decides** — no ranking or risk logic in the data layer.
- Decisions only move toward **caution**; missing risk gate → **no new trades**.
- Vocabulary: ideas **TRADE / WATCH / WAIT / AVOID**; holdings **HOLD / MONITOR / REDUCE / EXIT**;
  banner **NORMAL / DEFENSIVE / NO_NEW_TRADES**.

---

## 3. Conceptual architecture (product diagram)

High-level boxes from the owner’s solution diagram, aligned to this repo.

```text
                    ┌──────────────────────────┐
                    │       TRADEMIND           │
                    │      AI Trading Brain     │
                    └────────────┬─────────────┘
                                 │
        ┌────────────────────────┼────────────────────────┐
        │                        │                        │
        ▼                        ▼                        ▼
  MARKET INTELLIGENCE      OPPORTUNITY CENTER       PORTFOLIO
  ────────────────         ──────────────────       ──────────
  Market regime            Best opportunities       Current positions
  Sector regime            TRADE / WATCH / WAIT     Risk exposure
  News & events            Confidence (rank)        Allocation
  Market health            Why / why not            P&L
        │                        │                        │
        └────────────────────────┼────────────────────────┘
                                 ▼
                    ┌──────────────────────────┐
                    │      TRADEMIND BRAIN      │
                    │  PERCEIVE → STATE →       │
                    │  RECOGNISE → REMEMBER →   │
                    │  REASON → RISK → DECIDE → │
                    │  LEARN                    │
                    └────────────┬─────────────┘
                                 │
              ┌──────────────────┼──────────────────┐
              ▼                  ▼                  ▼
        DECISION CENTER     STOCK INTELLIGENCE   AI COPILOT
        (why / risks /      (history, tech,      (chat research —
         size)               ML, news)            not in build)
              │
              ▼
       ┌──────────────────────┐
       │   VALIDATION LAYER   │
       │ Shadow · replay ·    │
       │ 30 ideas · failures  │
       │ compare · health       │
       └──────────┬───────────┘
                  ▼
       ┌──────────────────────┐
       │ EXECUTION / PAPER    │
       │ Approval · Kite ·    │
       │ risk gates · halt    │
       └──────────────────────┘
```

**Important:** Marketing diagrams often show **many microservices** and **six external data columns**.
The **approved implementation** is **one FastAPI app**, Postgres/TimescaleDB, Redis, APScheduler — no
Kafka, Airflow, S3 data lake, or vector DB. See §8.

---

## 4. TradeMind Brain — eight steps and modules

Pipeline definition: `backend/src/swing_trade_ml/brain/module.py` (`Step` enum).

| Step | Role | Primary modules | Code path |
|------|------|-----------------|-----------|
| **Perceive** | Clean features, snapshots | M02 Perception | `brain/modules/m02_perception/` |
| **State** | Market, sectors, book, halt | M03 State; M10 Market; M11 Sector; M14 Portfolio | `m03_state`, `m10_market`, `m11_sector`, `m14_portfolio` |
| **Recognise** | Situations, setups, events | M04 Situations; M12 Stock; M13 News | `m04_situations`, `m12_stock`, `m13_news` |
| **Remember** | Similar cases, experience | M05 Memory | `m05_memory` |
| **Reason** | ML scores, meta-model | M06 Reason | `m06_reason` |
| **Risk** | Gates, sizing inputs | M07 Risk | `m07_risk` |
| **Decide** | Final word, evidence text | M08 Decide | `m08_decide` |
| **Learn** | Outcomes, drift, proposals | M09 Learn | `m09_learn` |

**Plug-ins (not separate steps):**

| ID | Name | When it runs |
|----|------|----------------|
| M00 | Brain core / runner | Orchestration, constitution, `DatedReader` |
| M15 | Trade tracker | Intraday holdings check |
| M16 | Alerts | What changed since last run |
| M17 | Brain console | `/brain` + TradeMind System / traces |
| M18 | Go-live switch | Shadow → approval → auto (`services/brain_golive/`) |
| M19 | User brain | **Deferred** (Pro product) |

Module registry: `brain/modules/__init__.py` (M01–M15 registered). M16–M18 are integration/console,
not `Module` subclasses in that list.

**Intraday path** skips recognise, remember, reason, learn — only perceive → state → risk → decide
(for open positions).

---

## 5. Data sources — vision vs today

| Diagram source | Today | Notes |
|----------------|-------|-------|
| Stock market data | **Yes** | Kite candles, quotes; v1 ingest |
| News & events | **Partial** | M13 calendar/events; not a full news product |
| Sector & macro | **Partial** | M11 sector ranks; index regime via M10 |
| Fundamental data | **No (UI placeholder)** | Stock detail “Fundamental” tab not connected |
| Alternative data | **Out of scope** | Owner decision: not planned |
| Broker data (Zerodha) | **Yes** | v1 execution; brain orders only via M18 approvals |

**Service 1** (logical data layer — not a separate deployable service): ingestion, side feeds,
`DatedReader`, M01 quality, M02 snapshots. Full gap table:
[`architecture-gaps.md`](architecture-gaps.md). Spec:
[`service-01-market-data.md`](service-01-market-data.md).

---

## 6. Web application — diagram modules vs routes

TradeMind UI: `frontend/src/trademind/TradeMindApp.tsx` at **`/trademind`**. Classic v1 UI remains
at existing routes (e.g. `/brain` for owner M17 console).

| Diagram module | TradeMind / app route | Status |
|----------------|----------------------|--------|
| Dashboard | `/trademind` (Home) | **Shipped** — banner, top ideas, insights |
| Market Intelligence | `/trademind/market` | **Shipped** — regime, sectors, episodes |
| Opportunity Center | `/trademind/opportunities` | **Shipped** — filter TRADE/WATCH/WAIT/AVOID |
| Stock Intelligence | `/trademind/stock/:symbol` | **Mostly** — technicals, AI tab; fundamentals/options N/A |
| Portfolio & Risk | `/trademind/portfolio`, `/positions`, `/risk` | **Shipped** |
| Decision & explainability | `/trademind/ai`, stock detail | **Shipped** — trace, evidence (owner tabs) |
| Shadow & replay | `/trademind/golive`, `/records`, Learn | **Partial** — shadow/compare in UI; **replay = CLI** |
| AI Copilot | — | **Not built** — no LLM chat in scope |

**Nav note:** Live app uses five sections (Decisions, Discover, Portfolio, Performance, Settings), not
the three-column marketing layout. Functionally similar.

**Plans (Free/Plus/Pro):** feature branch; off by default in prod. Gates some AI tabs via
`usePlan()`.

---

## 7. Validation layer

What the diagram calls “validation” is spread across code, CLI, and screens:

| Capability | Where | Status |
|------------|-------|--------|
| Shadow trading (M18) | `services/brain_golive/shadow.py`, nightly job | **Prod: practice mode** |
| Brain vs v1 compare | `GET /brain/compare`, Go-live page | **Shipped** |
| 30 finished ideas gate | `brain_golive/stage.py`, Go-live UI | **In progress** (owner evidence) |
| Human approval path | `approvals.py`, Go-live | **Built**; not prod trial until after gate |
| Decision replay | `swingtrade brain replay-week` | **CLI**; not a dedicated TradeMind hub |
| Failure analysis | M09 `failures.py`, Learn page, Home insights | **Partial** |
| Split / contamination check | `brain split-check` | **Shipped** |
| Rescore learning | `brain rescore-learning` | **Shipped** |
| Brain health | `/brain/health`, System page, weekly checklist | **Shipped** |
| Champion / challenger | — | **Roadmap Phase 5–6** — not built |

Deep inspection (read-only baseline): [`../brain/VALIDATION_PHASE_INSPECTION.md`](../brain/VALIDATION_PHASE_INSPECTION.md).

M18 operator guide: [`../brain/GO_LIVE.md`](../brain/GO_LIVE.md).

---

## 8. Execution, paper, and safety

| Capability | Status |
|------------|--------|
| Paper trading (`TRADING_MODE=paper`) | **Prod default** |
| v1 scan + execution path | **Live stack** |
| Brain auto orders | **Blocked** — shadow only; then approval → auto per M18 |
| Risk gates (drawdown, sector limits, cool-down) | **v1 + M07** |
| Portfolio halt (kill switch for new entries) | **Control** `/trademind/control` + `system_state` |
| Exits while halted | **Yes** — exits still run |
| Live money blockers | **Open** — see [`../brain/LIVE_READINESS.md`](../brain/LIVE_READINESS.md) (GTT, AMO, DDPI, etc.) |

**Known M18 minors** (see [`CURRENT-STATE.md`](CURRENT-STATE.md)): no v1 cash reservation on brain
buys; paper price can be prior close without Kite; approvals may wait on Telegram; audit `by` is
client-set.

---

## 9. Technical stack — diagram vs settled build

| Diagram box | Settled implementation |
|-------------|-------------------------|
| FastAPI backend | **Yes** — `swing_trade_ml/main.py` |
| Separate “analysis / portfolio / risk” services | **Logical modules** inside one app |
| PostgreSQL + time series | **Postgres/TimescaleDB** |
| Redis | **Yes** — worker/cache |
| Model + feature storage | **Disk** (`MODEL_ARTIFACT_DIR`) + `feature_snapshots` table |
| Docker / CI / droplet | **Yes** — see [`../DEPLOY.md`](../DEPLOY.md) |
| S3 / object store for data lake | **Not used** |
| GitHub CI/CD | **Yes** — push `main` deploys swingtrademl.com |

---

## 10. Gap register (consolidated)

### 10.1 Product / UX (vs full platform diagram)

| Gap | Priority | Notes |
|-----|----------|-------|
| AI Copilot (chat, scenarios) | Deferred / new scope | Not in brain build book; LLM does not decide trades |
| Unified “Validation” screen | Optional UX | Today: Go-live + Learn + System + CLI |
| Fundamentals tab | Medium | Placeholder in StockDetail |
| Options chain tab | Low | Placeholder; not needed for daily swing at current size |
| Champion / challenger models | Phase 5–6 | [`../brain/ROADMAP.md`](../brain/ROADMAP.md) |
| M19 user brain / Pro | Deferred | |
| Three-pillar marketing IA | Cosmetic | Five-section TradeMind nav is canonical |

### 10.2 Brain quality and roadmap

| Gap | Priority | Notes |
|-----|----------|-------|
| M06 meta-model often SHADOW / WAIT | Phase 2 | Evidence doc pending |
| M11 sector gate | Phase 3 | Config off |
| Playbook candidates → M08 | Phase 3 | |
| 30 shadow ideas + weekly health | **Ops now** | Owner |
| M18 approval trial | Phase 4 | After gates |

### 10.3 Service 1 (data) — see architecture-gaps.md

| # | Gap | Status (summary) |
|---|-----|------------------|
| 1 | Point-in-time / as-of | Partial (corrections lite) |
| 2 | Security master / ISIN | Pending lite |
| 3 | Adjusted prices | **Deferred** (split-check clean) |
| 4 | Universe / eligibility | Partial — **next priority** |
| 5–8 | Lineage, versioning | Partial — `data_manifest` |
| 9 | Quality breakdown UI | Pending |
| 10 | Per-stock readiness labels | Partial |
| 11 | Calendar | Partial (2027 provisional) |
| 12 | Microstructure | Deferred |
| 13 | Late corrections | **Done** |
| 6 | Multi-source reconciliation | Deferred |

### 10.4 Explicitly not building

Kafka, Airflow, S3 raw-data lake, dead-letter service, alt-data feeds, extra vendor news APIs, BSE
feed, 1m/5m bars — listed in [`architecture-gaps.md`](architecture-gaps.md).

---

## 11. Production and evidence snapshot (2026-10-05)

- **v1** on swingtrademl.com; paper trial from 2026-09-28.
- **Brain M00–M18** on `main`; TradeMind wired to live brain runs.
- **Service 1 P0** shipped (snapshots, corrections, manifest, health feeds, split-check CLI).
- **Phase 1 gate** (local): `replay-week` + `rescore-learning` documented.
- **M06:** meta-model below break-even — many **WAIT** ideas expected until Phase 2 evidence.

For live checklist after deploy: [`../brain/evidence/prod_deploy_20261005.md`](../brain/evidence/prod_deploy_20261005.md).

---

## 12. Related documents

| Topic | Document |
|-------|----------|
| What shipped / next task | [`CURRENT-STATE.md`](CURRENT-STATE.md) |
| Service 1 gaps (13 items) | [`architecture-gaps.md`](architecture-gaps.md) |
| Service 1 architecture | [`service-01-market-data.md`](service-01-market-data.md) |
| ADR: gaps vs brain split | [`../decisions/ADR-001-service-01-gaps.md`](../decisions/ADR-001-service-01-gaps.md) |
| Brain roadmap phases | [`../brain/ROADMAP.md`](../brain/ROADMAP.md) |
| M18 go-live | [`../brain/GO_LIVE.md`](../brain/GO_LIVE.md) |
| Live blockers | [`../brain/LIVE_READINESS.md`](../brain/LIVE_READINESS.md) |
| Testing & health | [`../brain/TESTING.md`](../brain/TESTING.md) |
| Build book (HTML spec) | [`../superpowers/specs/2026-09-29-trademind-brain-build-book.html`](../superpowers/specs/2026-09-29-trademind-brain-build-book.html) |
| Agent / dev rules | [`../../CLAUDE.md`](../../CLAUDE.md) |

---

## 13. Maintaining this file

Update this overview when:

- A diagram module moves from partial → shipped (or is explicitly deferred).
- M18 stage changes in production (shadow → approval → auto).
- Service 1 gap statuses change in `architecture-gaps.md`.
- A major phase completes in `docs/brain/ROADMAP.md`.

Do **not** duplicate the full 13-row gap table here — link to `architecture-gaps.md` instead.
