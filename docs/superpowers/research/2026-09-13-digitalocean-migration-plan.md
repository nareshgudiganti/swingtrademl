# DigitalOcean migration plan (research)

**Status: research only. Nothing in this document has been provisioned. No
`doctl` command was run against live infrastructure, and no money has been
spent.** This is a planning document for the user to review and approve
before any real DigitalOcean resource is created.

Date: 2026-09-13

---

## 0. Important — a discrepancy found while researching this

While checking the current DNS/HTTP state of `swingtrademl.com` (a read-only
lookup, no changes made) to plan the cutover section below, two things didn't
match what `render.yaml` implies is running today:

- `swingtrademl.com` resolves (A record) directly to `147.182.176.105` — an IP
  in a block DigitalOcean commonly assigns to Droplets — and serving that page
  returns `Server: nginx/1.24.0 (Ubuntu)` with a **Vite dev server** payload
  (`/@vite/client`, `injectIntoGlobalHook` HMR bootstrap), not a built static
  production bundle. That looks like the local dev-mode frontend container
  (`docker-compose.yml`'s `frontend` service, which uses `target: development`)
  exposed directly on a raw Ubuntu box, not the Render static site the
  blueprint describes.
- The API hostname `render.yaml` wires the frontend to,
  `swingtrade-api.onrender.com`, currently returns `HTTP 404` with header
  `x-render-routing: no-server` — Render's own signal that no service is
  currently bound to that hostname.
- The domain's nameservers are Cloudflare (`journey.ns.cloudflare.com`), and
  the root-domain request bypassed Cloudflare's proxy (no `cf-ray` header on
  that response) while the `onrender.com` request did go through Cloudflare —
  consistent with the root domain being DNS-only (grey-clouded) pointed
  straight at a Droplet-like IP, separate from whatever Render still has
  configured.

I did not chase this further — it's outside this task's scope, and I only
have public DNS/HTTP visibility, not console access to either provider. But
it means **the premise "production is live at swingtrademl.com on Render per
render.yaml" should be confirmed, not assumed**, before executing the cutover
plan below. Two concrete possibilities: (a) someone already stood up a
Droplet informally (e.g. for a quick test) and it's what the domain currently
points at, with the Render blueprint stale/unused, or (b) DNS is mid-change
for some other reason. Either way, a raw Vite dev server exposed to the
internet is also a real exposure on its own (no production build, HMR
websocket open, `ENVIRONMENT=production` gating from `core/config.py` doesn't
apply to a dev server invocation at all) and is worth checking regardless of
the DigitalOcean decision.

**Recommended first step, before anything else in this document: log into
the Render dashboard and confirm what's actually deployed there today, and
separately check whether a DigitalOcean Droplet already exists on this
account.** The rest of this plan assumes the `render.yaml` topology is (or
was) the real one, per the task's framing, but that assumption needs a human
to confirm against both provider dashboards.

---

## 1. Current topology (from the repo)

`render.yaml` (production, as designed):

| Service | Render type | Plan | Role |
|---|---|---|---|
| `swingtrade-api` | web (Docker) | starter | FastAPI app, scheduler off |
| `swingtrade-worker` | worker (Docker) | starter | same image, scheduler on |
| `swingtrade-redis` | managed Redis | starter | job/cache backing store |
| `swingtrade-frontend` | static site | — | Vite build, SPA rewrite |

Two things `render.yaml`'s own comments flag as unsolved on Render:

1. **Database**: Render's managed Postgres doesn't support the `timescaledb`
   extension the `candles` hypertable needs, so `DATABASE_URL` is deliberately
   left unset (`sync: false`) and pointed at an external Timescale Cloud
   instance instead.
2. **Model artifacts**: Render's persistent disks aren't shared across
   services, so a model trained by `swingtrade-worker` wouldn't be visible to
   `swingtrade-api`. Current guidance in the blueprint: train locally, treat
   Render as inference/paper-trading only.

`docker-compose.yml` (local, the topology all of this mirrors): a
`timescale/timescaledb` Postgres container, a `redis:7-alpine` container, and
`api`/`worker`/`frontend` app containers, where `api` and `worker` both mount
the **same named volume** (`model_data:/app/data/models`) — this is exactly
what Render's per-service disks can't reproduce, and it's the thing to keep
in mind when comparing DigitalOcean options below.

`backend/src/swing_trade_ml/core/config.py` confirms both settings are
already fully provider-agnostic:

- `DATABASE_URL` (line 71) is a plain connection string read from the
  environment — psycopg-compatible, no Render-specific logic anywhere.
- `MODEL_ARTIFACT_DIR` (line 170) is a plain filesystem path; the validator
  at line 190 just resolves it to an absolute path against `cwd` and
  `model_dir` (line 250) does `Path(...).mkdir(parents=True, exist_ok=True)`.
  It assumes a **real, persistent, shared local filesystem** — nothing more,
  nothing less. That assumption is what decides which DigitalOcean option
  needs code changes and which doesn't (see §4).

---

## 2. The two constraints, checked against DigitalOcean today

### 2a. TimescaleDB extension on managed Postgres

**Finding: DigitalOcean Managed Databases for PostgreSQL supports the
`timescaledb` extension natively today.** Confirmed directly on DigitalOcean's
own supported-extensions documentation
([docs.digitalocean.com/products/databases/postgresql/details/supported-extensions](https://docs.digitalocean.com/products/databases/postgresql/details/supported-extensions/)):
`timescaledb` is listed as supported on PostgreSQL 14–18 (Standard Edition)
and 16–18 (Advanced Edition), described as "enables scalable inserts and
complex queries for time-series data." It can be enabled with a plain
`CREATE EXTENSION timescaledb;` over a normal connection — no external
service required.

This is a genuine improvement over Render: **the external Timescale Cloud
workaround is not needed on DigitalOcean.** `candles` can live as a
hypertable directly on DigitalOcean Managed PostgreSQL.

Caveat (needs verification): the docs page confirms the extension *loads*,
but says nothing about operational specifics this app might touch later —
background workers for continuous aggregates/compression jobs, restrictions
on `ALTER SYSTEM`-level Timescale tuning, etc. The app today just creates a
hypertable via a migration and inserts/queries candles; that baseline is
almost certainly fine given the extension is officially listed as supported,
but if compression policies or continuous aggregates get added later, smoke-test
those specifically on a real DO cluster first. Verify at:
https://docs.digitalocean.com/products/databases/postgresql/details/supported-extensions/

### 2b. Shared storage for model artifacts

**Finding: DigitalOcean App Platform is *more* restrictive than Render here,
not equivalent.** Per DigitalOcean's own docs
([docs.digitalocean.com/products/app-platform/how-to/store-data](https://docs.digitalocean.com/products/app-platform/how-to/store-data/)
and
[.../app-platform/details/limits](https://docs.digitalocean.com/products/app-platform/details/limits/)):
App Platform components get **no persistent volumes at all** — only a 4 GiB
ephemeral scratch filesystem per instance, wiped on every deploy, restart, or
scale event, and never shared between components (each instance, and each
component, has its own separate filesystem). DigitalOcean's own recommendation
for anything that needs to persist or be shared is Spaces (S3-compatible
object storage) or a Managed Database — i.e. get it off local disk entirely.

So on App Platform, `MODEL_ARTIFACT_DIR` pointing at a local path doesn't
just fail to share between `api` and `worker` (Render's problem) — a
retrained model would vanish on the *next redeploy of the same component*.
Using App Platform for this app would require a real code change: swap the
plain `Path`-based read/write in `MODEL_ARTIFACT_DIR`/`model_dir` (and
wherever `ml/predict.py`, `ml/dataset.py`, etc. read/write under it) for
something backed by Spaces — either an S3 client wrapping save/load, or
syncing the directory to/from a bucket around training and startup.

**DigitalOcean Droplets don't have this problem at all**, and need **no code
change**: a Droplet is a real VM with a real persistent disk. Running `api`
and `worker` as containers on the *same* Droplet, sharing a bind-mounted
directory (or a named Docker volume) for `/app/data/models`, is exactly what
`docker-compose.yml` already does locally — `MODEL_ARTIFACT_DIR` stays
untouched, pointing at a plain local path both containers see. This is the
single biggest factor in the recommendation below.

---

## 3. App Platform vs Droplets vs Kubernetes (DOKS)

**DOKS (managed Kubernetes) is overkill here, and the doc says so plainly:**
this is a single-user app with two long-running processes, a cache, and a
frontend bundle. Kubernetes buys you multi-node scheduling, rolling
deployments across many replicas, and horizontal autoscaling — none of which
this app needs (the worker *must* stay at exactly one replica, per
`docker-compose.yml`'s own comment, to avoid two schedulers double-placing
trades). The control plane is free on DigitalOcean and worker nodes are just
billed as Droplets, so DOKS isn't expensive to try — but it adds real
operational surface (node pools, cluster upgrades, YAML manifests, ingress
controllers) to solve a problem this app doesn't have. Not recommended.

**App Platform** — closest analog to Render, managed containers, less ops
work in theory. But per §2b it has *zero* persistent storage of any kind,
which for this app means a mandatory code change (Spaces-backed model
storage) just to reach parity with what `docker-compose.yml` already does for
free. It would also mean a fourth billing relationship (App Platform compute
+ Managed Postgres + Managed Valkey since there's no VM to self-host Redis on
+ Spaces), each metered separately.

**Droplets** — a VM, run via Docker Compose (essentially a production variant
of the existing `docker-compose.yml`). More ops responsibility in the
abstract (you own OS patching, the Docker daemon, and TLS termination), but
in practice for this stack that responsibility is small: the database is
still a managed service (DigitalOcean Managed PostgreSQL, so no DB ops at
all), and `api` + `worker` + `redis` + a reverse proxy are four containers on
one box — the same shape as local dev today, just with `docker compose up -d`
on a server instead of a laptop. It's also cheaper (see §6) and needs no code
changes.

### Recommendation: Droplets, running Docker Compose

For this specific app, at this specific scale (single user, two processes,
one cheap VM's worth of load), Droplets win on every axis that matters here:
zero code changes for shared model storage, lower cost, and a deployment
shape the team already understands and runs locally every day. App
Platform's "less ops work" pitch doesn't actually save ops work once you
account for the Spaces-backed storage rewrite it forces — it trades
infrastructure ops for application code ops, for a single-user app where
neither burden is large. If a stronger case emerges later for elastic scaling
or a team of operators who don't want to touch a VM, App Platform stays
available as a later migration (nothing here forecloses it), but it's not the
right first move.

---

## 4. Recommended DigitalOcean architecture

One Droplet running Docker Compose (api, worker, redis, and a reverse proxy
for TLS), plus DigitalOcean Managed PostgreSQL, plus optional Spaces for
backups.

### Service mapping

| `render.yaml` service | DigitalOcean equivalent | Notes |
|---|---|---|
| `swingtrade-api` (web, starter) | `api` container in Compose on the Droplet, behind Caddy or nginx for TLS | Same image, same Dockerfile, no changes. `ENABLE_SCHEDULER=false` as today. |
| `swingtrade-worker` (worker, starter) | `worker` container in the same Compose stack | Same image. `ENABLE_SCHEDULER=true` as today. Stays at exactly 1 replica — same reasoning as the current comment in `docker-compose.yml`. |
| `swingtrade-redis` (managed Redis, starter, $10/mo) | Self-hosted `redis:7-alpine` container in the same Compose stack | At single-user load, self-hosting Redis on the same box (as `docker-compose.yml` already does locally) avoids DigitalOcean Managed Valkey's $15+/mo entirely. DO Managed Valkey remains available later if hands-off Redis ops becomes worth $15/mo. |
| `swingtrade-frontend` (static site) | `frontend` build served by the same Caddy/nginx reverse proxy on the Droplet | Simplest v1: build the Vite bundle at deploy time and serve the static files alongside the API reverse-proxy, one fewer moving part, no extra cost. DigitalOcean Spaces+CDN or an App Platform static-site component are viable upgrades later if edge caching/geographic latency ever matters — not needed for a single-country single-user app. |
| Render managed Postgres — actually external Timescale Cloud (workaround) | **DigitalOcean Managed PostgreSQL**, `timescaledb` extension enabled directly | Per §2a, no external Timescale Cloud dependency needed — one fewer vendor, one fewer bill. Smoke-test hypertable creation + the app's actual query patterns on a real cluster before fully committing (see needs-verification list). |
| — (n/a on Render) | Optional: DigitalOcean Spaces, cheapest tier | For off-Droplet backups: periodic `pg_dump` (belt-and-suspenders alongside DO's automated Postgres backups) and/or a copy of `model_data` for disaster recovery, since a single Droplet is a single point of failure for anything not on the managed DB. |

### Droplet sizing

Render's `starter` plan is 0.5 vCPU / 512 MiB per service; `api` and `worker`
together on Render today total roughly 1 vCPU / 1 GiB. Adding Redis and a
reverse proxy on the same box, plus headroom for LightGBM training spikes
(the ML stack — numpy/scipy/scikit-learn/lightgbm — is more memory-hungry
during training than at inference), a **2 vCPU / 2 GiB Basic Droplet
($18/mo)** is a sensible starting point — comfortable headroom without
over-provisioning for a single-user app. Resizing a Droplet up later is a
few minutes of API-visible downtime, not a migration, so this isn't a
high-stakes choice.

### Code changes needed

- **`DATABASE_URL`**: no change. It's already just a connection string;
  pointing it at DigitalOcean Managed PostgreSQL instead of Timescale Cloud
  is an env var change, not a code change.
- **`MODEL_ARTIFACT_DIR`**: no change, on the Droplet path. Keep the existing
  local-path behavior; mount a shared directory into both `api` and `worker`
  containers exactly as `docker-compose.yml` does today with `model_data`.
  (This is precisely the code change that *would* be required if App
  Platform were chosen instead — see §2b/§3 — and is the main reason it
  isn't.)
- **`CORS_ORIGINS` / `FRONTEND_URL` / the frontend's `VITE_API_BASE_URL`**:
  values need updating for the new domain layout (e.g. deciding whether the
  API stays on the same origin behind the reverse proxy at
  `swingtrademl.com/api/v1`, or moves to a subdomain like
  `api.swingtrademl.com`) — an env var/config change at deploy time, not a
  code change. Worth deciding this explicitly since §0 suggests the current
  live setup may not match `render.yaml`'s subdomain-based layout anyway.
- **`KITE_REDIRECT_URL`**: already dead code (per this repo's own prior
  finding — Zerodha's console controls the redirect, not this app's config).
  Unaffected by the hosting move as long as the Kite Connect app's registered
  redirect URL still points at `swingtrademl.com` by cutover time — no
  action needed here beyond keeping the domain the same.
- Nothing else in `core/config.py`, the Dockerfile, or `alembic` migrations
  is Render-specific. The Dockerfile builds a plain Python wheel into a slim
  runtime image with no platform assumptions baked in.

---

## 5. Cutover plan

1. **Confirm current state first** (§0) — resolve the Render-vs-what's-
   actually-live discrepancy before scheduling any DNS change.
2. **Stand up DigitalOcean Managed PostgreSQL** with `timescaledb` enabled.
   Run the existing Alembic migrations (`alembic upgrade head`) against it
   from a local machine or a throwaway Droplet — this validates the
   hypertable creation path on real DO infrastructure before anything else
   depends on it.
3. **Backfill/copy data** from whatever database is authoritative today
   (Timescale Cloud, if `render.yaml` reflects reality) into the new DO
   Postgres instance — `pg_dump`/`pg_restore` works across Postgres-
   compatible targets. Do this with the source database still live and
   read/write; DO Postgres is not yet in the path, so there's no risk to
   production during this step.
4. **Stand up the Droplet**: install Docker, deploy the Compose stack
   pointed at the new DO Postgres and a fresh `model_data` volume, with
   `TELEGRAM_ENABLED=false` and `ENABLE_SCHEDULER=false` on both `api` and
   `worker` initially — i.e. bring it up cold, verified via its own IP/a
   temporary hostname, with the scheduler and notifications off so it cannot
   place trades or duplicate alerts while still side-by-side with the
   current live system.
5. **Verify in isolation**: hit the new Droplet directly by IP (or a
   staging subdomain), confirm `/api/v1/health`, confirm the frontend build
   loads and talks to the right API origin, confirm a manual Kite login and
   a manual signal-scan run work end to end against the new database.
6. **Run both in parallel** — yes, this is safe and recommended. Nothing
   about DNS changes what's currently live at the old location until step 7;
   DigitalOcean and Render (or whatever's actually running today) can serve
   from entirely separate infrastructure simultaneously, since they don't
   share state (the new DO Postgres is a copy, not the same database). The
   only shared external resource is Kite's daily token — only flip
   `ENABLE_SCHEDULER=true` and re-point Kite's redirect testing to the new
   side once you're ready to treat it as primary, not before.
7. **Cut over DNS.** The domain's nameservers are on Cloudflare
   (confirmed live, §0), which makes this straightforward regardless of
   which registrar owns the domain: update the `A`/`CNAME` record for
   `swingtrademl.com` (and any subdomain in use, e.g. an API subdomain) in
   the Cloudflare dashboard to point at the Droplet's IP (or a DO Load
   Balancer/Reserved IP in front of it, if used). Cloudflare TTLs are
   typically short (the SOA default TTL observed was 1800s/30min), so
   propagation should be fast. If Cloudflare's orange-cloud proxy is enabled
   for the record, DigitalOcean's own TLS cert isn't strictly required
   (Cloudflare can terminate TLS at its edge) — but terminating TLS on the
   Droplet too (Caddy auto-provisions Let's Encrypt certs with zero config)
   is simpler to reason about and avoids depending on Cloudflare's proxy
   mode being set correctly.
8. **Flip the scheduler and Telegram on** on the new side only once DNS has
   settled and you've confirmed the old side is no longer receiving traffic
   (check its logs/metrics go quiet). Turn `ENABLE_SCHEDULER=false` on the
   old side at the same time, so there is never a window with two live
   schedulers.
9. **Rollback plan**: keep the old infrastructure running, untouched, for a
   defined window (a few days to a week) after cutover. Rolling back is
   just reverting the DNS record in Cloudflare — no data migrates backward
   automatically, so if any live trades or paper trades happen on the new
   side during that window, reconciling them before rollback is a manual
   step, not automatic. Decommission the old side only after that window
   passes with no issues.

Order of migration to minimize downtime: **database first (parallel copy,
zero downtime), then app stack (stood up cold, verified in isolation, zero
downtime since it's not receiving traffic yet), then DNS (the only step with
any user-visible effect, and even that is typically seconds to minutes given
short TTLs, not an outage)**. There is no step in this plan that requires
taking the current production system offline.

---

## 6. Cost comparison

All DigitalOcean figures below are from DigitalOcean's own current pricing
pages, fetched live during this research (2026-09-13):
[App Platform](https://www.digitalocean.com/pricing/app-platform),
[Managed Databases](https://www.digitalocean.com/pricing/managed-databases),
[Droplets](https://www.digitalocean.com/pricing/droplets),
[Spaces](https://www.digitalocean.com/pricing/spaces-object-storage),
[Kubernetes](https://docs.digitalocean.com/products/kubernetes/details/pricing/).
Render and Timescale figures are noted per-line with their confidence level.

### Current Render + Timescale Cloud (as `render.yaml` describes it)

| Item | Plan | Monthly cost |
|---|---|---|
| `swingtrade-api` | Starter (0.5 vCPU / 512 MiB) | ~$7 |
| `swingtrade-worker` | Starter (0.5 vCPU / 512 MiB) | ~$7 |
| `swingtrade-redis` | Starter (256 MiB) | ~$10 |
| `swingtrade-frontend` | Static site | $0 |
| Timescale Cloud (external DB) | Free 30-day trial of "Performance," then $30+/mo compute + $0.177/GiB-month storage | $0 during trial, **$30-40+/mo ongoing** |
| **Total** | | **~$24/mo during any Timescale trial window, ~$54-64+/mo once that trial lapses** |

Confidence notes: the Render figures ($7/$7/$10) are cross-referenced from
several third-party pricing summaries, not fetched directly from render.com's
own pricing page (which is JavaScript-rendered and didn't return tabular data
to this research's fetch tool) — **worth confirming directly at
https://render.com/pricing** before treating them as exact. The Timescale
figures came directly from Tiger Data's own pricing page
(https://www.tigerdata.com/pricing), which currently advertises **only a
30-day free trial of the Performance plan, not an ongoing free tier** —
notably different from what `render.yaml`'s own comment implies ("has a free
tier"). **This is worth verifying directly at
https://console.cloud.timescale.com against whatever plan the account is
actually on today** — if the current production database has been sitting on
a genuinely free tier for longer than 30 days, either Tiger Data's terms have
changed since that page was last updated, or the account is already paying
more than `render.yaml`'s comment suggests.

### Recommended DigitalOcean setup

| Item | Plan | Monthly cost |
|---|---|---|
| Droplet (api + worker + redis + reverse proxy) | Basic, 2 vCPU / 2 GiB / 60 GiB SSD | $18 |
| Managed PostgreSQL (with `timescaledb`) | 1 vCPU / 1 GiB, 10-30 GiB storage | $15.15 |
| Spaces (optional — off-Droplet backups) | 250 GiB + 1 TiB transfer | $5 (optional) |
| Droplet automated backups (optional) | ~20% of Droplet cost | ~$3.60 (optional) |
| **Total (core, no optional backups)** | | **~$33/mo** |
| **Total (with recommended backups)** | | **~$42/mo** |

### Rejected alternative: App Platform, for comparison

| Item | Plan | Monthly cost |
|---|---|---|
| `api` component | Basic, 1 vCPU / 1 GiB (fixed) | $10 |
| `worker` component | Basic, 1 vCPU / 1 GiB (fixed) | $10 |
| Managed PostgreSQL | same as above | $15.15 |
| Managed Valkey (no VM to self-host Redis on) | cheapest tier, 1 GiB | $15 |
| Spaces (mandatory here, not optional — §2b) | cheapest tier | $5 |
| Static site | bundled or standalone | $0-3 |
| **Total** | | **~$55-58/mo, plus the engineering time to rewrite model-artifact storage against Spaces** |

**Bottom line**: the recommended Droplet setup (~$33-42/mo) is cheaper than
the current Render+Timescale setup once Timescale's trial lapses, and
meaningfully cheaper than the App Platform alternative — while also being
the only option that needs zero code changes for shared model storage.
Consolidating onto one provider (DigitalOcean for compute, database, and
optional storage/backups) also removes a second vendor relationship
(Timescale Cloud) entirely.

---

## 7. Needs-verification list

Marked here explicitly rather than guessed at:

- **Render's exact current plan pricing** — cross-referenced from
  third-party sources, not fetched from render.com's own pricing page.
  Verify at https://render.com/pricing.
- **Timescale Cloud's actual current billing on this account** — Tiger
  Data's public pricing page shows only a 30-day free trial, not an ongoing
  free tier, which doesn't match `render.yaml`'s comment. Verify at
  https://console.cloud.timescale.com (log in and check the account's actual
  plan and current invoice).
- **TimescaleDB operational specifics beyond "the extension is supported"**
  — background workers for compression/continuous-aggregate jobs, any
  DigitalOcean-specific tuning limits. The app's current usage (a single
  hypertable, no compression policies yet) is very likely fine per the
  official supported-extensions listing, but smoke-test on a real DO cluster
  before fully committing, and re-check if compression/continuous
  aggregates get added later. Verify at
  https://docs.digitalocean.com/products/databases/postgresql/details/supported-extensions/.
- **What's actually deployed at swingtrademl.com and on Render right now**
  — see §0. This needs a human with dashboard access to both providers,
  not another DNS/HTTP probe.
- **Current DNS registrar/record details beyond nameservers** — confirmed
  Cloudflare nameservers and a direct A record via public lookup; the actual
  record type/TTL/proxy-status for every subdomain in use should be
  confirmed in the Cloudflare dashboard before cutover.

---

## 8. Next steps checklist

Steps 1-3 are read-only investigation and cost nothing — safe to do anytime.
**Every step from 4 onward creates real infrastructure or spends real money
and requires the user's explicit go-ahead before running.**

1. [ ] Log into the Render dashboard and confirm what's actually deployed
   there today (services, plans, whether they match `render.yaml`).
2. [ ] Log into (or check for) a DigitalOcean account/Droplet — confirm
   whether `147.182.176.105` (currently serving `swingtrademl.com`) is
   already a DigitalOcean resource on this account, per §0.
3. [ ] Check the Timescale Cloud console for the account's actual current
   plan and bill, per §7.
4. [ ] **(requires go-ahead — creates a billed resource)** Create a
   DigitalOcean Managed PostgreSQL cluster (smallest tier, $15.15/mo),
   enable `timescaledb`, and run `alembic upgrade head` against it from a
   local machine to validate the hypertable migration path on real DO
   infrastructure.
5. [ ] **(requires go-ahead — creates a billed resource)** Create the
   Droplet ($18/mo, 2 vCPU/2 GiB), install Docker + Docker Compose, and
   deploy the `api`/`worker`/`redis`/reverse-proxy stack pointed at the new
   database, with the scheduler and Telegram notifications off.
6. [ ] Copy/backfill production data into the new database (`pg_dump`/
   `pg_restore`), with the source database still live.
7. [ ] Verify the new stack end-to-end in isolation (health check, frontend
   build, a manual Kite login, a manual signal scan) before it receives any
   real traffic.
8. [ ] **(requires explicit go-ahead — user-visible change)** Cut over DNS
   in the Cloudflare dashboard for `swingtrademl.com` (and any subdomains in
   use) to point at the new Droplet.
9. [ ] Flip `ENABLE_SCHEDULER=true` on the new worker and confirm the old
   side has gone quiet, keeping the old infrastructure intact as a rollback
   path for a defined window (a few days to a week).
10. [ ] **(requires go-ahead — deletes/stops billed resources)** After the
    rollback window passes with no issues, decommission the old Render
    services and the Timescale Cloud instance, and optionally add DigitalOcean
    Spaces + Droplet automated backups (~$3.60-8.60/mo combined) for
    ongoing disaster recovery.
