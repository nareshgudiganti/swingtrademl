"""RESEARCH-ONLY, durable, append-only HOLDOUT-USE REGISTRY for the sector experiments (SX5 / SX10).

Why it exists: the per-run marker of the walk-forward harness lives under the run's `out_root` (or `marker_dir`), so
pointing those elsewhere would silently re-open a holdout. This registry lives at a FIXED repository location that
no run argument can move, is committed to git (durable, diffable), and records every holdout authorisation and use.

Nothing here fits a model, reads data, or touches the database, Kite, prod or `.env`.

Registry file: docs/brain/evidence/sector_prep/HOLDOUT-REGISTRY.jsonl (one canonical JSON object per line).
  * APPEND-ONLY and HASH-CHAINED: every entry stores `seq` and `prev_sha256` = sha256 of the previous line (without
    its newline; the first entry uses 64 zeros). `verify()` detects an edited, deleted-in-the-middle or reordered
    line. The file is never rewritten: appends use O_APPEND plus fsync, under a cross-process file lock.
  * A local guard (backend/data/research_holdout.lock + research_holdout.guard.json, gitignored) serialises writers
    and remembers the head of the chain, so a TRUNCATED tail (which a chain alone cannot show) is detected on this
    machine, and an in-progress event whose registry lines vanished is refused.

Entry types and the per-event state machine (all rules are enforced by `_replay`, on every append and in verify):
  AUTHORISED -> STARTED -> COMPLETED | ABORTED
  AUTHORISED          owner-signed record (signer, date, protocol id + sha256, sha256 of the authorisation text),
                      bound to the dataset sha256, DatasetSpec config sha256, harness config sha256, fold sha256, the
                      code version string, the horizon, and ALL arms with their feature-list and fit-recipe hashes.
  STARTED             written BEFORE any holdout fit or prediction; a STARTED event without COMPLETED/ABORTED means
                      the holdout is CONSUMED. An interrupted run never re-opens it.
  COMPLETED           after every arm's holdout records exist, carrying their record hashes.
  ABORTED(reason)     informational crash note; the holdout STAYS consumed.
  RECOVERY_AUTHORISATION  the only way to re-run a consumed (STARTED/ABORTED) event: owner-signed, references the
                      STARTED line by hash, states that no holdout predictions/metrics were observed, bound again
                      to the same hashes. It permits exactly one further STARTED.
A SECOND event for the same horizon (a new AUTHORISED) is only possible when it names the consumed event it
supersedes plus a reason, signed by the owner. Output path, run name, protocol file copy and seed play no role.

Limits (honest): the chain protects against accidental or casual editing, not against a determined owner who
rewrites git history and the local guard. The signature is a name plus the hash of the authorisation text, not a
cryptographic signature.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timezone
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[3]
REPO_ROOT = BACKEND_ROOT.parent
REGISTRY_PATH = REPO_ROOT / "docs" / "brain" / "evidence" / "sector_prep" / "HOLDOUT-REGISTRY.jsonl"
LOCK_PATH = BACKEND_ROOT / "data" / "research_holdout.lock"
GUARD_PATH = BACKEND_ROOT / "data" / "research_holdout.guard.json"

GENESIS = "0" * 64
HORIZON_CANDIDATE = {5: "SX5", 10: "SX10"}
REQUIRED_BASE_ARMS = ("A_53", "R_37")
LOCK_TIMEOUT_S = 30.0

T_AUTH, T_START, T_DONE, T_ABORT, T_RECOVER = (
    "AUTHORISED",
    "STARTED",
    "COMPLETED",
    "ABORTED",
    "RECOVERY_AUTHORISATION",
)
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
BOUND_SCALARS = (
    "candidate",
    "horizon",
    "protocol_id",
    "protocol_sha256",
    "dataset_sha256",
    "config_sha256",
    "harness_config_sha256",
    "fold_definition_sha256",
    "code_version",
)


class HoldoutRegistryError(RuntimeError):
    pass


class HoldoutRefused(HoldoutRegistryError):
    """The holdout may not be started / the entry may not be appended."""


class RegistryCorrupt(HoldoutRegistryError):
    """The registry file fails verification (edited, deleted, reordered, malformed or truncated)."""


class _Invalid(Exception):
    pass


# ------------------------------------------------------------------------------------------------ hashing / io
def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _canon(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _line_sha(line: str) -> str:
    return hashlib.sha256(line.encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    raw = path.read_bytes()
    if not raw:
        return []
    if not raw.endswith(b"\n"):
        raise RegistryCorrupt("the registry does not end with a newline (partial or hand-edited write)")
    text = raw.decode("utf-8")
    lines = text.split("\n")[:-1]
    if any(ln == "" for ln in lines):
        raise RegistryCorrupt("blank line in the registry")
    return lines


def _parse_chain(lines: Sequence[str]) -> list[dict]:
    entries, prev = [], GENESIS
    for i, ln in enumerate(lines):
        try:
            e = json.loads(ln)
        except ValueError as exc:
            raise RegistryCorrupt(f"line {i + 1} is not valid JSON") from exc
        if not isinstance(e, dict) or _canon(e) != ln:
            raise RegistryCorrupt(f"line {i + 1} is not in canonical form (edited by hand?)")
        if e.get("seq") != i:
            raise RegistryCorrupt(
                f"line {i + 1}: seq is {e.get('seq')!r}, expected {i} (deleted or reordered)"
            )
        if e.get("prev_sha256") != prev:
            raise RegistryCorrupt(f"line {i + 1}: hash chain broken (line edited, deleted or reordered)")
        e = {**e, "_line_sha256": _line_sha(ln)}
        entries.append(e)
        prev = e["_line_sha256"]
    return entries


# ------------------------------------------------------------------------------------------------ validation
def _hex(v, name):
    if not isinstance(v, str) or not _HEX64.match(v):
        raise _Invalid(f"{name} must be a 64-character lowercase sha256 hex string")


def _nonempty(v, name):
    if not isinstance(v, str) or not v.strip():
        raise _Invalid(f"{name} must be a non-empty string")


def _iso_date(v, name):
    try:
        date.fromisoformat(v)
    except (TypeError, ValueError):
        raise _Invalid(f"{name} must be an ISO date (YYYY-MM-DD)") from None


def _check_arms(arms):
    if not isinstance(arms, Mapping) or len(arms) < 3:
        raise _Invalid("arms must name every approved arm (A_53, R_37 and one C_* arm)")
    for b in REQUIRED_BASE_ARMS:
        if b not in arms:
            raise _Invalid(f"arms lacks {b}")
    c_arms = [a for a in arms if str(a).startswith("C_")]
    if len(c_arms) != 1 or len(arms) != 3:
        raise _Invalid("arms must be exactly A_53, R_37 and one C_* arm")
    for a, v in arms.items():
        if not isinstance(v, Mapping) or set(v) != {"feature_list_sha256", "fit_recipe_sha256"}:
            raise _Invalid(f"arm {a}: needs feature_list_sha256 and fit_recipe_sha256")
        _hex(v["feature_list_sha256"], f"arm {a} feature_list_sha256")
        _hex(v["fit_recipe_sha256"], f"arm {a} fit_recipe_sha256")


def _check_bound(b: Mapping):
    for k in BOUND_SCALARS:
        if k not in b:
            raise _Invalid(f"missing {k}")
    if b["horizon"] not in HORIZON_CANDIDATE or HORIZON_CANDIDATE[b["horizon"]] != b["candidate"]:
        raise _Invalid("horizon must be 5 (SX5) or 10 (SX10) and match the candidate")
    _nonempty(b["protocol_id"], "protocol_id")
    _nonempty(b["code_version"], "code_version")
    for k in (
        "protocol_sha256",
        "dataset_sha256",
        "config_sha256",
        "harness_config_sha256",
        "fold_definition_sha256",
    ):
        _hex(b[k], k)
    _check_arms(b.get("arms"))


def _check_signed(b: Mapping):
    _nonempty(b.get("signer"), "signer")
    _iso_date(b.get("signed_date"), "signed_date")
    _hex(b.get("authorisation_text_sha256"), "authorisation_text_sha256")
    _nonempty(b.get("reason"), "reason")


def _bound_of(b: Mapping) -> dict:
    return {**{k: b[k] for k in BOUND_SCALARS}, "arms": {a: dict(v) for a, v in b["arms"].items()}}


def _replay(entries: Sequence[dict]) -> dict[str, dict]:
    """Apply the state machine; raise _Invalid on any rule violation. Returns {event_id: info}."""
    ev: dict[str, dict] = {}
    by_h: dict[int, list[str]] = {}
    for e in entries:
        t, eid, body = e.get("type"), e.get("event_id"), e.get("body")
        n = f"entry {e.get('seq')}"
        try:
            _nonempty(eid, "event_id")
            if not isinstance(body, dict):
                raise _Invalid("body must be an object")
            if t == T_AUTH:
                if eid in ev:
                    raise _Invalid("event_id already used")
                _check_bound(body)
                _check_signed(body)
                h = body["horizon"]
                prior = by_h.get(h, [])
                sup = body.get("supersedes_event_id")
                if not prior:
                    if sup is not None:
                        raise _Invalid(
                            "supersedes_event_id given but no earlier event exists for this horizon"
                        )
                else:
                    last = ev[prior[-1]]
                    if last["state"] == "AUTHORISED":
                        raise _Invalid(
                            f"an unused authorisation ({prior[-1]}) already exists for horizon {h}"
                        )
                    if last["state"] == "RECOVERY_AUTHORISED":
                        raise _Invalid(f"event {prior[-1]} has an open recovery authorisation")
                    if sup != prior[-1]:
                        raise _Invalid(
                            f"horizon {h} is consumed by {prior[-1]}: a new authorisation must set "
                            f"supersedes_event_id to {prior[-1]!r} (and give a reason)"
                        )
                ev[eid] = {
                    "state": "AUTHORISED",
                    "bound": _bound_of(body),
                    "horizon": h,
                    "auth_seq": e["seq"],
                }
                by_h.setdefault(h, []).append(eid)
                continue
            if eid not in ev:
                raise _Invalid("unknown event_id (no AUTHORISED entry before this one)")
            info = ev[eid]
            if t == T_START:
                if info["state"] not in ("AUTHORISED", "RECOVERY_AUTHORISED"):
                    raise _Invalid(f"cannot start from state {info['state']}: the holdout is consumed")
                _check_bound(body)
                if _bound_of(body) != info["bound"]:
                    raise _Invalid("STARTED is not bound to the same values as the authorisation")
                if (
                    info["state"] == "RECOVERY_AUTHORISED"
                    and body.get("recovery_entry_sha256") != info["recovery_sha"]
                ):
                    raise _Invalid("STARTED after recovery must cite the recovery entry hash")
                info.update(
                    state="STARTED", started_sha=e["_line_sha256"], attempts=info.get("attempts", 0) + 1
                )
            elif t == T_DONE:
                if info["state"] != "STARTED":
                    raise _Invalid(f"COMPLETED needs state STARTED, found {info['state']}")
                recs = body.get("holdout_records")
                if not isinstance(recs, Mapping) or set(recs) != set(info["bound"]["arms"]):
                    raise _Invalid(
                        "COMPLETED must carry holdout record hashes for exactly the authorised arms"
                    )
                for a, shas in recs.items():
                    if not shas or not all(isinstance(s, str) and _HEX64.match(s) for s in shas):
                        raise _Invalid(f"arm {a}: holdout record hashes missing or malformed")
                info["state"] = "COMPLETED"
            elif t == T_ABORT:
                if info["state"] != "STARTED":
                    raise _Invalid(f"ABORTED needs state STARTED, found {info['state']}")
                _nonempty(body.get("reason"), "reason")
                info["state"] = "ABORTED"
            elif t == T_RECOVER:
                if info["state"] not in ("STARTED", "ABORTED"):
                    raise _Invalid(f"recovery needs a STARTED/ABORTED event, found {info['state']}")
                _check_bound(body)
                _check_signed(body)
                if _bound_of(body) != info["bound"]:
                    raise _Invalid("recovery is not bound to the same values as the authorisation")
                if body.get("started_entry_sha256") != info["started_sha"]:
                    raise _Invalid("recovery must reference the STARTED entry by its line sha256")
                if body.get("no_predictions_or_metrics_observed") is not True:
                    raise _Invalid("recovery must state that no holdout predictions or metrics were observed")
                info.update(state="RECOVERY_AUTHORISED", recovery_sha=e["_line_sha256"])
            else:
                raise _Invalid(f"unknown entry type {t!r}")
        except _Invalid as exc:
            raise _Invalid(f"{n} ({t}): {exc}") from None
    return ev


# ------------------------------------------------------------------------------------------------ lock / guard
_THREAD_LOCK = threading.Lock()


class _FileLock:
    """Cross-process exclusive lock on one byte of the lock file (msvcrt on Windows, flock elsewhere)."""

    def __init__(self, path: Path, timeout: float = LOCK_TIMEOUT_S):
        self.path, self.timeout, self.fd = Path(path), timeout, None

    def __enter__(self):
        if not _THREAD_LOCK.acquire(timeout=self.timeout):
            raise HoldoutRegistryError("could not take the in-process holdout lock")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.fd = os.open(self.path, os.O_RDWR | os.O_CREAT)
            if os.fstat(self.fd).st_size == 0:
                os.write(self.fd, b"L")
            deadline = time.monotonic() + self.timeout
            while True:
                try:
                    self._try()
                    return self
                except OSError:
                    if time.monotonic() > deadline:
                        raise HoldoutRegistryError(
                            "could not take the holdout file lock (another writer?)"
                        ) from None
                    time.sleep(0.02)
        except BaseException:
            self._close()
            _THREAD_LOCK.release()
            raise

    def _try(self):
        os.lseek(self.fd, 0, os.SEEK_SET)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(self.fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _close(self):
        if self.fd is not None:
            try:
                os.lseek(self.fd, 0, os.SEEK_SET)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(self.fd, msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
            os.close(self.fd)
            self.fd = None

    def __exit__(self, *exc):
        self._close()
        _THREAD_LOCK.release()


def _guard_path(lock_path: Path) -> Path:
    return Path(lock_path).with_name(Path(lock_path).stem + ".guard.json")


def _read_guard(lock_path: Path) -> dict | None:
    g = _guard_path(lock_path)
    if not g.exists():
        return None
    try:
        return json.loads(g.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise RegistryCorrupt("the local holdout guard file is unreadable") from None


def _write_guard(lock_path: Path, entries: Sequence[dict], registry_path: Path) -> None:
    open_events = []
    try:
        ev = _replay(entries)
        open_events = sorted(k for k, v in ev.items() if v["state"] == "STARTED")
    except _Invalid:
        pass
    g = {
        "registry": registry_path.name,
        "n_entries": len(entries),
        "head_sha256": entries[-1]["_line_sha256"] if entries else GENESIS,
        "line_sha256": [e["_line_sha256"] for e in entries],
        "in_progress_events": open_events,
    }
    tmp = _guard_path(lock_path).with_suffix(".tmp")
    tmp.write_text(json.dumps(g, sort_keys=True), encoding="utf-8")
    os.replace(tmp, _guard_path(lock_path))


def _check_guard(lock_path: Path, entries: Sequence[dict]) -> None:
    g = _read_guard(lock_path)
    if g is None:
        return
    shas = [e["_line_sha256"] for e in entries]
    known = g.get("line_sha256", [])
    if len(shas) < len(known) or shas[: len(known)] != known:
        raise RegistryCorrupt(
            "the registry no longer contains the entries this machine last saw (truncated or rewritten)"
        )


def _load(registry_path: Path, lock_path: Path) -> list[dict]:
    entries = _parse_chain(_read_lines(registry_path))
    try:
        _replay(entries)
    except _Invalid as exc:
        raise RegistryCorrupt(str(exc)) from None
    _check_guard(lock_path, entries)
    return entries


def _append(
    registry_path: Path, lock_path: Path, entries: list[dict], typ: str, eid: str, body: dict
) -> dict:
    """Caller holds the lock and passes the freshly loaded entries."""
    prev = entries[-1]["_line_sha256"] if entries else GENESIS
    entry = {
        "seq": len(entries),
        "prev_sha256": prev,
        "type": typ,
        "event_id": eid,
        "recorded_at": _now(),
        "body": body,
    }
    line = _canon(entry)
    candidate = [*entries, {**entry, "_line_sha256": _line_sha(line)}]
    try:
        _replay(candidate)
    except _Invalid as exc:
        raise HoldoutRefused(str(exc)) from None
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(registry_path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_BINARY", 0))
    try:
        os.write(fd, (line + "\n").encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)
    _write_guard(lock_path, candidate, registry_path)
    return candidate[-1]


# ------------------------------------------------------------------------------------------------ public API
def verify(registry_path: str | Path | None = None, lock_path: str | Path | None = None) -> dict:
    """Verify chain, canonical form, sequence, state machine and the local guard. Raises RegistryCorrupt."""
    rp, lp = Path(registry_path or REGISTRY_PATH), Path(lock_path or LOCK_PATH)
    entries = _load(rp, lp)
    ev = _replay(entries)
    return {
        "entries": len(entries),
        "head_sha256": entries[-1]["_line_sha256"] if entries else GENESIS,
        "events": {k: v["state"] for k, v in ev.items()},
    }


def event_states(
    registry_path: str | Path | None = None, lock_path: str | Path | None = None
) -> dict[str, str]:
    return verify(registry_path, lock_path)["events"]


def append_authorisation(
    event_id: str,
    *,
    authorisation_text: str,
    signer: str,
    signed_date: str,
    reason: str,
    bound: Mapping,
    supersedes_event_id: str | None = None,
    registry_path: str | Path | None = None,
    lock_path: str | Path | None = None,
) -> dict:
    """OWNER ACTION (never called by the harness): append an owner-signed holdout authorisation.
    `bound` holds the BOUND_SCALARS plus `arms`; the text hash is computed here from the text itself."""
    rp, lp = Path(registry_path or REGISTRY_PATH), Path(lock_path or LOCK_PATH)
    body = {
        **_bound_of(bound),
        "signer": signer,
        "signed_date": signed_date,
        "reason": reason,
        "authorisation_text_sha256": sha256_text(authorisation_text),
        "supersedes_event_id": supersedes_event_id,
    }
    with _FileLock(lp):
        entries = _load(rp, lp)
        return _append(rp, lp, entries, T_AUTH, event_id, body)


def append_recovery_authorisation(
    event_id: str,
    *,
    authorisation_text: str,
    signer: str,
    signed_date: str,
    reason: str,
    no_predictions_or_metrics_observed: bool,
    registry_path: str | Path | None = None,
    lock_path: str | Path | None = None,
) -> dict:
    """OWNER ACTION: re-open ONE crashed attempt. Binds again to the authorisation's hashes and cites the STARTED line."""
    rp, lp = Path(registry_path or REGISTRY_PATH), Path(lock_path or LOCK_PATH)
    with _FileLock(lp):
        entries = _load(rp, lp)
        ev = _replay(entries)
        if event_id not in ev:
            raise HoldoutRefused(f"unknown event {event_id}")
        info = ev[event_id]
        if info["state"] not in ("STARTED", "ABORTED"):
            raise HoldoutRefused(f"event {event_id} is {info['state']}: nothing to recover")
        body = {
            **info["bound"],
            "signer": signer,
            "signed_date": signed_date,
            "reason": reason,
            "authorisation_text_sha256": sha256_text(authorisation_text),
            "started_entry_sha256": info["started_sha"],
            "no_predictions_or_metrics_observed": bool(no_predictions_or_metrics_observed),
        }
        return _append(rp, lp, entries, T_RECOVER, event_id, body)


def _mismatches(auth: Mapping, run: Mapping) -> list[str]:
    # the harness knows the protocol FILE (sha256), not its id; the id is taken from the authorisation unless given
    run = {**run, "protocol_id": run.get("protocol_id") or auth["protocol_id"]}
    bad = [k for k in BOUND_SCALARS if run.get(k) != auth[k]]
    ra = run.get("arms") or {}
    if set(ra) != set(auth["arms"]):
        bad.append(
            f"arms (run has {sorted(ra)}, authorised {sorted(auth['arms'])}: partial or different arm set)"
        )
    else:
        for a in auth["arms"]:
            if dict(ra[a]) != auth["arms"][a]:
                bad.append(f"arms.{a} (feature list or fit recipe hash)")
    return bad


def _select(ev: dict, horizon: int) -> tuple[str | None, dict | None, str]:
    ids = [k for k, v in ev.items() if v["horizon"] == horizon]
    if not ids:
        return None, None, f"no owner authorisation exists for the horizon-{horizon} holdout"
    last = ids[-1]
    st = ev[last]["state"]
    if st in ("AUTHORISED", "RECOVERY_AUTHORISED"):
        return last, ev[last], ""
    return (
        None,
        None,
        (
            f"the horizon-{horizon} holdout is CONSUMED (event {last} is {st}); it needs a new owner-signed "
            f"authorisation that supersedes {last}, or a recovery authorisation for a crashed attempt"
        ),
    )


def check_authorised(run: Mapping, registry_path=None, lock_path=None) -> str:
    """READ-ONLY pre-check (no write). Returns the event_id that would be used, or raises HoldoutRefused."""
    rp, lp = Path(registry_path or REGISTRY_PATH), Path(lock_path or LOCK_PATH)
    try:
        entries = _load(rp, lp)
    except RegistryCorrupt as exc:
        raise HoldoutRefused(f"registry failed verification: {exc}") from exc
    eid, info, why = _select(_replay(entries), run.get("horizon"))
    if info is None:
        raise HoldoutRefused(why)
    bad = _mismatches(info["bound"], run)
    if bad:
        raise HoldoutRefused(f"run does not match the authorisation {eid}: {bad}")
    return eid


def require_authorised_and_mark_started(run: Mapping, registry_path=None, lock_path=None) -> str:
    """Call BEFORE the first holdout fit/prediction. Under the file lock: verify the registry, find the owner
    authorisation for this horizon, check every bound value, then append STARTED (fsync'd). Refuses otherwise."""
    rp, lp = Path(registry_path or REGISTRY_PATH), Path(lock_path or LOCK_PATH)
    with _FileLock(lp):
        try:
            entries = _load(rp, lp)
        except RegistryCorrupt as exc:
            raise HoldoutRefused(f"registry failed verification: {exc}") from exc
        eid, info, why = _select(_replay(entries), run.get("horizon"))
        if info is None:
            raise HoldoutRefused(why)
        bad = _mismatches(info["bound"], run)
        if bad:
            raise HoldoutRefused(f"run does not match the authorisation {eid}: {bad}")
        body = _bound_of({**run, "protocol_id": run.get("protocol_id") or info["bound"]["protocol_id"]})
        if info["state"] == "RECOVERY_AUTHORISED":
            body["recovery_entry_sha256"] = info["recovery_sha"]
        _append(rp, lp, entries, T_START, eid, body)
        return eid


def mark_completed(
    event_id: str, holdout_records: Mapping[str, Sequence[str]], registry_path=None, lock_path=None
) -> dict:
    """After ALL arms' holdout records exist: {arm: [record_sha256, ...]}."""
    rp, lp = Path(registry_path or REGISTRY_PATH), Path(lock_path or LOCK_PATH)
    with _FileLock(lp):
        entries = _load(rp, lp)
        body = {"holdout_records": {a: list(s) for a, s in holdout_records.items()}}
        return _append(rp, lp, entries, T_DONE, event_id, body)


def mark_aborted(event_id: str, reason: str, registry_path=None, lock_path=None) -> dict:
    """Crash note. Does NOT re-open the holdout."""
    rp, lp = Path(registry_path or REGISTRY_PATH), Path(lock_path or LOCK_PATH)
    with _FileLock(lp):
        entries = _load(rp, lp)
        return _append(rp, lp, entries, T_ABORT, event_id, {"reason": reason})


# ------------------------------------------------------------------------------------------------ harness hook
class HoldoutGate:
    """What the walk-forward harness holds for one real run that includes the holdout."""

    def __init__(self, run: dict, registry_path, lock_path):
        self.run, self.registry_path, self.lock_path, self.event_id = run, registry_path, lock_path, None

    def require_authorised_and_mark_started(self) -> None:
        self.event_id = require_authorised_and_mark_started(self.run, self.registry_path, self.lock_path)

    def mark_completed(self, records: Sequence[Mapping]) -> None:
        by_arm: dict[str, list[str]] = {a: [] for a in self.run["arms"]}
        for r in records:
            if r["fold"]["kind"] == "holdout":
                by_arm[r["arm"]].append(r["record_sha256"])
        mark_completed(self.event_id, by_arm, self.registry_path, self.lock_path)


def gate_for_run(
    *,
    synthetic: bool,
    folds: Sequence,
    holdout_start: date,
    run: Mapping,
    protocol_path: str | Path | None,
    fit_fn,
    registry_path=None,
    lock_path=None,
) -> HoldoutGate | None:
    """Pre-loop hook. None for synthetic runs (they touch no real data). For a real run it (1) refuses any
    non-holdout fold that reaches the holdout dates, (2) for holdout runs binds the run to its protocol file and
    fit recipe and does the read-only authorisation pre-check."""
    if synthetic:
        return None
    has_holdout = False
    for f in folds:
        if f.kind == "holdout":
            has_holdout = True
        elif f.test_end >= holdout_start:
            raise HoldoutRefused(
                f"fold {f.index} is not a holdout fold but its test window reaches {f.test_end} >= {holdout_start}"
            )
    if not has_holdout:
        return None
    if protocol_path is None or not Path(protocol_path).is_file():
        raise HoldoutRefused(
            "a real holdout run needs holdout_protocol_path (the protocol file it is bound to)"
        )
    rec = getattr(fit_fn, "recipe_sha256", None)
    if not isinstance(rec, str) or not _HEX64.match(rec):
        raise HoldoutRefused(
            "a real holdout run needs a fit_fn that carries recipe_sha256 (see ml/sx_recipe.py)"
        )
    full = {
        **run,
        "protocol_sha256": sha256_file(protocol_path),
        "arms": {
            a: {"feature_list_sha256": s, "fit_recipe_sha256": rec}
            for a, s in run["arm_feature_shas"].items()
        },
    }
    full.pop("arm_feature_shas")
    gate = HoldoutGate(full, Path(registry_path or REGISTRY_PATH), Path(lock_path or LOCK_PATH))
    check_authorised(full, gate.registry_path, gate.lock_path)
    return gate
