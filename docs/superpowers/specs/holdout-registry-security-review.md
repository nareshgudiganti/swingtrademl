# Holdout registry: concurrency, durability and recovery security review

Scope: `backend/src/swing_trade_ml/ml/holdout_registry.py` (registry), the 6-line hook in `ml/sector_walkforward.py`,
tests `test_holdout_registry.py` (updated) and `test_holdout_registry_security.py` (new, 25 tests). Owner requirement
(item 5): a recovery must not permit another evaluation after any holdout result was exposed. Synthetic data and
scratch registries only. The committed `HOLDOUT-REGISTRY.jsonl` is still 0 bytes.

## 1. Findings (line numbers are in the file as it was at HEAD 53bb5fd)

| # | Defect | Where | Fix |
|---|---|---|---|
| D1 | Recovery needed only the owner's sentence "no predictions or metrics were observed". Nothing machine-checkable said a result had left the process. A crash after the first holdout `predict` (or after records were written) was still recoverable. | registry :297-308; harness `sector_walkforward.py` :565-573 | New entry `RESULTS_EXPOSED`, written and fsync'd after the holdout fit and before `predict()` is called (harness hook). Recovery is refused in the registry whatever the owner states. |
| D2 | `COMPLETED` only needed `STARTED`. | :281 | `COMPLETED` needs `RESULTS_EXPOSED` first. |
| D3 | A recovery was not limited: after a recovered attempt crashed, a second recovery could follow. | :297-308 | At most one recovery per event; a further event needs a new owner authorisation. |
| D4 | A recovery could reuse the text of the original authorisation or of another recovery (text hash never compared). | :306 | A text hash already used by any AUTHORISED / RECOVERY entry is refused. |
| D5 | Record files already on disk did not block a recovery. | n/a | `STARTED` now names `locations` (`marker_file`, `record_dirs`); recovery is refused if any `holdout_*.json` exists under a listed dir, and when the STARTED entry names no locations (fail closed). |
| D6 | After a recovery the crashed run's marker file still blocked the harness, and nothing in the registry said so. | :610-612; harness :446 | A recovered STARTED must name a NEW marker file (not the old one, not an existing file): "fresh marker directory required", enforced in `_replay` and in `require_authorised_and_mark_started`. |
| D7 | A superseding event for an exposed horizon could reuse the same protocol id. | :250 | After exposure the new authorisation must carry a protocol id not used by any exposed event of that horizon. |
| D8 | `verify()` and `check_authorised()` read the file without the lock, so they could read a writer's half-written line and report corruption (false alarm) or act on it. | :465-469, :583 | Both take the cross-process lock. |
| D9 | The append used a single `os.write` (a short write would leave a torn line), the guard file was written with `write_text` without fsync, and no directory fsync existed. | :456, :408 | `_write_all` loops until the whole line is written; guard written with fsync then `os.replace` then directory fsync (POSIX); directory fsync when the registry file is first created. |
| D10 | `mark_*` functions leaked `RegistryCorrupt` instead of `HoldoutRefused` (inconsistent for callers). | :616-632 | `mark_results_exposed` converts it (the other owner-side helpers keep `RegistryCorrupt`; harmless: both refuse). |

Confirmed sound (no change): the cross-process lock covers read, state check and append in one critical section
(`_FileLock` is taken before `_load` in every writer, and the replay of the candidate list runs inside it, so there is
no TOCTOU between the check and the append). The OS releases an `msvcrt`/`flock` byte lock when the holder dies, so a
crash cannot leave a stale lock; a leftover lock file is harmless because the lock is on file content, not on file
existence (test `test_lock_is_released_when_the_holder_dies...`). The in-process lock is one global `threading.Lock`
(non-reentrant: no registry function calls another locking function while holding it). A hash-chain edit, delete,
reorder, blank line, non-canonical JSON, partial last line and truncated tail are all detected.

## 2. Exposure model

The exposure point is the first moment any holdout-derived value can leave the fit/predict step. In
`run_walkforward` the flow for a holdout fold is: `fit_fn(train...)` (sees training rows only) -> `predict(test_X)`
(first holdout score) -> `evaluate_fold` (first metric) -> `predictions_sha256` -> record -> files -> `COMPLETED`.
The hook runs `gate.mark_results_exposed()` between `fit_fn` and `predict`:

```
predict = fit_fn(train ...)
if gate and fold.kind == "holdout":
    gate.mark_results_exposed()      # appends + fsyncs RESULTS_EXPOSED; if it raises, predict() is never called
scores = predict(test_X)
```

The call is idempotent per run, so only the first holdout prediction triggers the write. If the write fails, the
exception propagates and no prediction exists. If every holdout fold was skipped (no predictions), the gate writes
the marker just before `COMPLETED`, because `COMPLETED` needs it. The fit sees no holdout rows, and a fit that prints
or logs still reveals only training information; anything printed or logged by `predict`, the metrics or the record
writers happens after the marker.

Ordering and hard-kill windows (all tested):

| Kill point | Registry state | Holdout information left the process? | Recovery |
|---|---|---|---|
| before STARTED | AUTHORISED | no | not needed, start again |
| after STARTED, during fit (before marker) | STARTED | no | possible once, with owner statement |
| after fit, marker write fails or is killed mid-append | STARTED (a torn tail makes the registry refuse everything until the owner repairs it) | no: `predict` was not called | possible once, after the owner repairs a torn tail |
| after the marker, before/within `predict` | RESULTS_EXPOSED | possibly (a kill right after the marker may have exposed nothing, but this is unprovable) | IMPOSSIBLE; new protocol id |
| records written, `COMPLETED` not written | RESULTS_EXPOSED | yes | IMPOSSIBLE; the owner may still write `COMPLETED` (bookkeeping, no new evaluation) |
| after COMPLETED | COMPLETED | yes | IMPOSSIBLE; new protocol id |

There is no window in which a result exists without the marker. The reverse (a marker without a result) is accepted
on purpose: the system errs toward "consumed".

## 3. Concurrency

* Same machine, same working copy: serialised by the lock (file lock + thread lock). Tested: 8 threads, 2 processes
  starting, 2 processes recovering at once (exactly one wins), recovery against exposure at once (exactly one of the
  two entries appears, never both), start against recovery (start only ever runs after the recovery entry).
* Two worktrees or clones on one machine: the lock and the guard live under that working copy's `backend/data`, so
  two working copies do NOT exclude each other. The registry file is the source of truth: a clone with a missing
  or stale guard still refuses a consumed horizon as soon as its copy of the registry contains the consumption
  (tested). What no code can see is a registry copy that is behind: if clone B has not pulled the commit holding
  `STARTED`, it sees `AUTHORISED` and would start again. Rule: the holdout is run from ONE working copy, which must
  have the committed registry at its current head (`git fetch` and compare with the owner's tag before the run) and
  the registry commit must be pushed immediately after STARTED/RESULTS_EXPOSED are written. A guard that is ahead of
  an older registry copy is refused (tested).

## 4. Durability (what is and is not guaranteed)

* Append: `O_APPEND`, binary mode, full-write loop, `fsync` of the file before returning. A torn last line (crash
  mid-append, tested by simulating a half write) has no newline and is refused by every load; a short write is
  completed (tested). The torn entry never counts as an entry, so a torn STARTED means "not started" and a torn
  RESULTS_EXPOSED means "predict never ran" because the harness stops when the append raises.
* Directory: on POSIX the directory is fsync'd when the file is created and when the guard is replaced. On Windows a
  directory cannot be opened with `os.open`; the NTFS journal normally covers a new directory entry but the code
  cannot force it. Residual risk: a power cut right after the very first append on Windows could lose the file
  itself. Mitigation in the procedure: the owner reads the registry back after STARTED and commits it.
* Tail truncation: the chain cannot show a missing tail; the guard (`research_holdout.guard.json`, gitignored)
  remembers every line hash and is rejected if the registry no longer contains them. Its limits: it is local, it is
  written after the registry append (a crash between them leaves it one entry behind, harmless), a deleted guard
  provides no protection, and the owner can edit both.
* Line endings: `.gitattributes` marks the registry `-text`, so git never converts line endings; a CRLF
  conversion is detected by the canonical-form check (tested).
* Reordering and editing: caught by `seq`, `prev_sha256` and canonical JSON; a forged but internally valid chain is
  still caught by the state machine replay (tested for COMPLETED without exposure and recovery after exposure).

## 5. Residual risks (stated plainly)

1. A determined owner can rewrite git history and the local guard, then re-run. The registry deters accidents and
   casual edits; it is not an adversary-proof seal.
2. Signatures are a name, a date and a text hash, not cryptography. To make the registry tamper-evident to a third
   party the owner should make a signed git tag (or a signed commit) over the registry commit immediately after
   `AUTHORISED`, again after `STARTED`/`RESULTS_EXPOSED`, and after `COMPLETED`, and publish the tag hashes. A later
   rewrite then contradicts the published tag. No keys are implemented here.
3. A copy of the registry that is behind (section 3) is undetectable by code.
4. `record_dirs` is scanned only where STARTED names it. Records written elsewhere are not seen. The harness passes
   `out_root/<candidate>`.
5. A kill after the marker but before any prediction closes the holdout although nothing was seen: accepted.
6. A torn tail blocks every operation until the owner trims the partial last line in git (the diff shows exactly
   what was removed). That is an owner edit of the file, so it is allowed only for a partial line without a newline,
   and the reviewer should see the diff.
7. The guard write happens after the registry append. If it raises (disk full), the entry is already on disk and the
   caller sees an exception; the next load accepts the registry. This errs toward "consumed".

## 6. Entry sequences

Normal event: `AUTHORISED` (owner) -> `STARTED` (harness, before any holdout fit; names marker file and record dirs)
-> `RESULTS_EXPOSED` (harness, after the first holdout fit, before the first predict) -> `COMPLETED` (harness, with
all arms' record hashes).

Crash before exposure (kill during the fit, or marker write failed), with recovery: `AUTHORISED` -> `STARTED` ->
`RECOVERY_AUTHORISATION` (owner) -> `STARTED` (names a new marker file, cites the recovery hash) ->
`RESULTS_EXPOSED` -> `COMPLETED`. A second crash before exposure cannot be recovered again: a new owner-signed
authorisation superseding the event is needed.

Crash after exposure: `AUTHORISED` -> `STARTED` -> `RESULTS_EXPOSED` (-> `ABORTED` note, optional). Nothing re-opens
it. A further event needs `AUTHORISED` with `supersedes_event_id` set and a NEW protocol id, signed by the owner.

## 7. Recovery procedure text for the signed protocol

> A holdout run that stops without a `COMPLETED` entry never re-opens the holdout by itself. Only the owner may
> authorise ONE recovery per event, and only when ALL of the following hold: (a) the latest registry state of the
> event is `STARTED` or `ABORTED`; (b) there is no `RESULTS_EXPOSED` entry for the event; (c) no `holdout_*.json`
> file exists in any record directory named in the `STARTED` entry; (d) the owner checked these facts by running
> `verify()` and reading the registry, and states that no holdout prediction, metric or record was observed. If any of
> (a) to (d) fails, or after `RESULTS_EXPOSED`, `COMPLETED` or a second crash, no recovery exists: a new event
> requires a new owner-signed `AUTHORISED` entry that names the consumed event it supersedes, a reason and a NEW
> protocol id. The recovery entry cites the `STARTED` line hash, repeats every bound hash, carries the signer, the
> date and the hash of a recovery text that has never been used before, and is used up by the next `STARTED`. The
> recovered run must use a fresh marker directory (a marker file that does not exist and differs from the crashed
> run's); the crashed run's marker is never deleted or edited. Before any holdout run the owner confirms that the
> working copy holds the current committed registry, runs from that single working copy, and commits and pushes the
> registry after `STARTED` and after `COMPLETED`. Preferably the owner makes a signed git tag over each of those
> registry commits.

## 8. Tests

* New: `test_holdout_registry_security.py` (25 tests): exposure marker and refusal, forged recovery after exposure,
  COMPLETED needs exposure, new protocol id, recovery binding, single use, after COMPLETED, changed hash, text reuse,
  record files/unknown locations, fresh marker, hard kill before/after the marker in the real harness (3 orderings),
  torn append, truncated/CRLF, `.gitattributes`, short writes, missing/stale/ahead guard and second clone, four
  multi-process races, lock release after a crash.
* Updated on purpose (`test_holdout_registry.py`): helpers now pass `locations`, `complete()` marks exposure first,
  the entry count is 4, the recovered start uses a fresh marker, the superseding event uses a new protocol id, the
  forged-sequence test expects the new COMPLETED message. Reason: the intended semantics changed (D1, D2, D6, D7).
* Run: registry 36 + security 25 + recipe 12 + walkforward + trial_freeze = 102 passed, 1 failed. The failure,
  `test_sector_walkforward.py::test_nothing_in_the_app_imports_the_harness_...`, comes from another agent's new
  file `ml/sx_verdict.py`, whose docstring contains the text `sector_walkforward`; it is unrelated to this work.
