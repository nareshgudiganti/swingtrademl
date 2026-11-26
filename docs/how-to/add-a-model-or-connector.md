# How to add a data connector, a model, or a module

For one developer. Plain English. Every path and name below is checked by
`backend/tests/test_howto_add_connector_doc.py`, so if code moves, that test fails and tells you which line to fix.

Ground rules (from `CLAUDE.md`, not negotiable here):

- One backend. No new service, queue, bucket or database. Reuse Postgres, Redis and the scheduler.
- Bad or missing data only ever makes a decision more cautious.
- Brain modules are pure and read only through `swing_trade_ml.brain.reader.DatedReader`, which stops at the run's `as_of` date (no look-ahead).
- The v1 data and trading path stay untouched. New data sits next to it.
- Paper trading only. Nothing here turns on live trading.

Background and a walked example of every step: `docs/verification/259-add-model-connector.md` and
`backend/tests/test_add_model_connector_259.py`.

## A. Add a data connector

A connector is code that fetches from an outside provider. Two small shared pieces make it safe.

### A1. Fetch through the shared HTTP helper

Use `backend/src/swing_trade_ml/core/http_client.py`, never `httpx.get` or `requests.get` directly.

- `swing_trade_ml.core.http_client.get` (blocking) and `swing_trade_ml.core.http_client.aget` (async) always send a timeout.
  The default is `swing_trade_ml.core.http_client.DEFAULT_TIMEOUT` (30 seconds, 10 to connect). Pass your own `timeout=` if the provider is slow.
- They retry twice (`swing_trade_ml.core.http_client.RETRIES`) with a short wait, for timeouts, network errors, HTTP 429 and HTTP 5xx. Other 4xx answers are final.
- On failure they raise `swing_trade_ml.core.http_client.HttpError`. Its `kind` is one of `timeout`, `network`, `server`, `rate_limited`, `not_found`, `client`.
  The message never contains the URL query, so a token in the URL cannot leak into logs.
- A status you expect (say a 404 on a holiday) goes in `ok_statuses=(404,)`, and you get the response back instead of an error.
- For tests, pass `transport=` (an `httpx.MockTransport`) and `sleep=` so nothing touches the network or waits. See `backend/tests/test_http_client_259.py`.

Real examples that already use it:

- NSE feeds: `swing_trade_ml.services.market_feeds.fetch` in `backend/src/swing_trade_ml/services/market_feeds.py` returns the file, or None on a 404 (holiday or not published yet).
- Company filings: `backend/src/swing_trade_ml/services/company_filings.py` (three calls per symbol).
- AMFI mutual fund prices: `swing_trade_ml.services.finance.mutual_funds.sync_nav_snapshot` in `backend/src/swing_trade_ml/services/finance/mutual_funds.py`.

`test_no_outbound_http_call_in_src_lacks_a_timeout` in `backend/tests/test_http_client_259.py` fails the build if any new code makes an HTTP call without a timeout.

### A2. Wrap it in the adapter shape

`backend/src/swing_trade_ml/core/adapters.py` is a convention, not a framework. A provider is a small class with:

- `name`, and `module_id` (its on/off switch, see section C, or None),
- `fetch()` returning `swing_trade_ml.core.adapters.Fetched`: the `value` plus `fetched_at`, the time the value was really fetched,
- `health()` returning `swing_trade_ml.core.adapters.Health`.

This is the `swing_trade_ml.core.adapters.Adapter` protocol. Rules:

- Call it through `swing_trade_ml.core.adapters.fetch_with_stale`. It never raises. If the module switch is off you get a result with `disabled=True`.
  If the fetch fails with `HttpError` you get `stale=True` carrying the last good value and its old `fetched_at`, so a screen can say "as of 10:15" instead of showing an error. One provider failing never touches another.
- Tests use `swing_trade_ml.core.adapters.FakeAdapter`. Set `fail_with=` to a `HttpError` to simulate an outage. It counts `calls` and keeps its own `Health`.
- Honest status: today the three feeds above use the HTTP helper directly. No production provider is wrapped in an adapter yet, so a new connector is the first real user of `fetch_with_stale`. Keep the wrapper thin.

### A3. Make it a point-in-time feed

- Store each row with the date it describes, and let the brain read it only through `DatedReader`, bounded by `as_of`. Never read "latest" inside a module.
- Daily candles are stamped IST midnight (18:30 UTC the day before): always convert with `.astimezone(IST).date()`.
- Put the feed in the quality check list so empty or late data is reported. How a late feed is reported, and why a connector that must stop trading needs its own rule, is walked in the connector tests of `backend/tests/test_add_model_connector_259.py`.
- A new table needs an Alembic migration. A schema migration needs the owner's approval.

Checklist: helper used, timeout kept, `Fetched.fetched_at` set, `FakeAdapter` test written, module declared (section C), dated reads only, migration approved if any.

## B. Add a model

Today's flow, in order. Nothing in this flow switches a model on by itself.

1. **Train.** `swing_trade_ml.ml.train.train_model` (in `backend/src/swing_trade_ml/ml/train.py`) trains, tests on a held-out future window and registers the result as TRAINED. From the command line: `swingtrade train`. Training is never blocked, and `auto_activate` defaults to off.
2. **Register.** The model file is saved once, never overwritten, by `swing_trade_ml.ml.registry.save_artifact`, under a version from `swing_trade_ml.ml.registry.next_version`. The database row is `MLModel` in `backend/src/swing_trade_ml/db/models/ml.py`, holding the version, horizon, input list and the file's hash. The registry code is `backend/src/swing_trade_ml/ml/registry.py`. `swing_trade_ml.ml.registry.load_model_artifact` refuses a file that is not the one its row describes.
3. **Card (#328).** `swing_trade_ml.ml.model_card.build_card` (in `backend/src/swing_trade_ml/ml/model_card.py`) records exactly how the model was made: data window, inputs, library versions, code state. It lands in the row's `metrics["card"]` and in the saved file. Anything unknown is recorded as None, never guessed. The five-day and selection-lab trainers are frozen by their protocols, so they get a card file beside the model through `swing_trade_ml.brain.card_trainers.train_endpoint_model_with_card` and `swing_trade_ml.brain.card_trainers.train_lab_model_with_card` instead.
4. **Slot and evidence.** `swing_trade_ml.services.model_registry.slot_for` says which research slot a model name and horizon belong to (`backend/src/swing_trade_ml/services/model_registry.py`). Keep horizons separate: a model is never compared against a different horizon.
5. **Promote.** `swing_trade_ml.ml.registry.activate_model` makes one version ACTIVE and archives the old one of the same name. It checks the file first. The gate in front of it is `swing_trade_ml.core.release_switches.promotion_refusal`: while the `model_promotion` switch (setting `ALLOW_MODEL_PROMOTION`) is off, `POST /api/v1/ml/models/{id}/activate`, training with `auto_activate`, and `swingtrade train --activate` all refuse.

**Model activation needs the owner's approval.** Do not turn the switch on, activate a model, or run an activation against production yourself. Hand over the model id, its card and its evidence, and wait.

Known gaps, written down as expected failures in `backend/tests/test_add_model_connector_259.py` (they are not fixed, so do not assume the checks exist): activation does not check that every input is produced by the live pipeline, does not compare the horizon with the model it replaces, and a row saved without a horizon is stored as 15 days.

Tests to read or copy: `backend/tests/test_model_artifact_safety.py` (version and file checks), `backend/tests/test_model_promotion_switch.py` (the promotion gate).

Brain rule: a brain module that uses a model stays pure. It takes the score from its view and returns a contribution. Loading models and writing results happen in the service layer, never inside the module.

## C. Declare the module

Every optional part of the product (including a new connector's routes and scheduled jobs) is one entry in `REGISTRY` in `backend/src/swing_trade_ml/core/modules.py`.

1. Add one `swing_trade_ml.core.modules.Module` line: `id`, a plain-English `label`, its `route_prefixes` (paths without `/api/v1`), its scheduler `jobs` ids, and `depends_on` if it needs another module. New modules are on by default; use `state=ModuleState.DEVELOPMENT` to keep one off until the owner says so.
2. Guard its router with `swing_trade_ml.core.modules.require_module` (see how `backend/src/swing_trade_ml/api/v1/router.py` does it). Scheduled jobs are left out by `swing_trade_ml.core.modules.apply_to_scheduler` for you.
3. Put the same id in your adapter's `module_id`, so switching the module off also gives `disabled=True` from `fetch_with_stale`.
4. Nothing else: no new settings file, table or service for the switch. State lives in the existing `module_switches` table and every change is audited. Core modules (sign-in, risk limits, orders, health) can never be switched off, and `swing_trade_ml.core.modules.validate` rejects a bad declaration (duplicate id, missing dependency, cycle) before the app starts.

The test that proves "one declaration and nothing else" is `test_a_new_optional_module_is_one_declaration_and_the_registry_enforces_the_rules_for_it` in `backend/tests/test_add_model_connector_259.py`. The registry's own rules are tested in `backend/tests/test_module_registry.py`, which also checks that every declared route prefix and job id exists in the real app.

## Before you open a pull request

- Run only the focused tests for what you touched (see `CLAUDE.md` for the exact test command and the Docker Postgres note).
- Format only the files you touched.
- Anything touching order placement, sizing, stops or limits needs a test, the `review-risk` skill and the owner's approval before it reaches `main`. Merging does not deploy; a deploy is a separate approval.
