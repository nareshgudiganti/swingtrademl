# Production deploy checklist — 2026-10-05

SSH from this dev machine is **blocked** per [DEPLOY.md](../../DEPLOY.md). Deploy is **push to `main`** → GitHub Actions `Deploy to production`. Run the steps below **on the droplet** (or rely on CI migrate step) **after** the commit lands on `main`.

## 1. Release via Git

From a clean checkout rebased on `origin/main`:

```bash
git push origin main
```

Watch Actions until `Deploy to production` is `completed / success` for your SHA (see DEPLOY.md).

Confirm:

```bash
curl -s https://swingtrademl.com/api/v1/health
```

(`/status` needs `X-API-Key` from droplet `/root/app/.env` — do not paste keys into chat or docs.)

## 2. Alembic (if CI did not apply Service 1 P0)

If upgrade fails with duplicate brain tables / forked `alembic_version`, follow [alembic_local_20261005.md](alembic_local_20261005.md) (insert `p1a2n3s4f5r6` when schema matches, then upgrade). Target head: **`m3r6e5p1s1v1`**.

From repo on droplet (typical path `/root/app`):

```bash
docker exec stml-api alembic upgrade head
```

## 3. Rebuild api + worker (backend code changed)

From repo root on droplet:

```bash
docker compose build api worker
docker compose up -d api worker
docker exec stml-api alembic upgrade head
```

## 4. Service 1 / brain smoke (inside api container)

From [TESTING.md](../TESTING.md):

```bash
docker exec stml-api python -m swing_trade_ml.cli brain split-check
docker exec stml-api python -c "from swing_trade_ml.db.session import session_scope; from swing_trade_ml.services.watchlist_snapshots import record_watchlist_snapshot; _s=session_scope(); _db=_s.__enter__(); _n=record_watchlist_snapshot(_db); _db.commit(); _s.__exit__(None,None,None); print('watchlist_snapshots:', _n)"
```

Optional Phase 1 gate on prod DB (heavy; owner discretion):

```bash
docker exec stml-api python -m swing_trade_ml.cli brain replay-week --days 5 --book paper
docker exec stml-api python -m swing_trade_ml.cli brain rescore-learning --since 2026-09-01
```

## 5. Timing

Avoid deploy between **15:40–15:50 IST** on trading days (scan chain). See DEPLOY.md.

## 6. Never on prod without owner

- Do **not** set `TRADING_MODE=live` or `ALLOW_LIVE_TRADING=true`.
- M18 remains practice/shadow until owner advances stage per [GO_LIVE.md](../GO_LIVE.md).

## Verification (remote, no SSH)

**2026-10-05** — from dev machine (does not prove migrate/rebuild or SHA):

```text
GET https://swingtrademl.com/api/v1/health
→ {"status":"ok","app":"Swing Trade ML","environment":"production","version":"0.1.0"}
```

Confirm GitHub Actions **Deploy to production** succeeded for target SHA (`fcaef35` or later) in the
repo UI (`gh` auth required locally). Droplet steps in sections 2–4 still required after backend
changes even when health is `ok`.
