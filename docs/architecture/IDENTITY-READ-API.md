# Identity read API (#389): what Tracks B and C may rely on

Status: stable from `main` 90f0250 (PR #448). A contract test pins it: `backend/tests/test_identity_read_contract.py`.
Changing anything below means changing that test on purpose, and telling the lead first.

Import only from `swing_trade_ml.services.identity`. Do not read the identity tables directly.

## 1. Resolve a stock

```python
from swing_trade_ml.services.identity import resolve, get_ref

resolve(db, *, symbol=None, isin=None, token=None, exchange="NSE", on_date=None) -> int | None
get_ref(db, security_id, *, exchange="NSE", on_date=None) -> SecurityRef | None
```

`resolve` returns the permanent `security_id`, or `None`. It accepts any one of the three identifiers, or several.

| Rule | Meaning |
|---|---|
| Never writes | Safe in any read path. It never creates a security. |
| `None` on doubt | Unknown stock, malformed identifier, or identifiers that name different stocks all give `None`. Never a guess. |
| Several identifiers | They must agree. An identifier that is merely unknown is ignored when another one resolves. |
| `on_date` | `None` means today (IST). A symbol resolves through its dated history, so an old symbol resolves for the dates it was valid. If the symbol HAS history that does not cover the date, the answer is `None` (it was another company then). Only a symbol with no history at all falls back to the current instrument row. |
| Rename | The `security_id` does not change. Resolve the old symbol with an old `on_date`, the new one with a new date. |
| Re-issued Kite token | Another alias of the same security: `resolve(db, token=old)` and `resolve(db, token=new)` agree. |
| Normalising | Symbols and ISINs are upper-cased and trimmed first. A token may be an int or digits. A malformed ISIN, token or symbol returns `None`. |
| ISIN disagreement | If two records answer differently for one ISIN, the answer is `None`. |

```python
@dataclass(frozen=True)
class SecurityRef:
    id: int
    isin: str | None       # None until an ISIN source is loaded
    name: str | None
    exchange: str
    symbol: str | None     # the symbol valid on on_date; None when none is recorded for that date
    status: str            # "active" | "delisted"
```

`get_ref` returns `None` for an id that does not exist.

Tests without a database: `with identity.use_store(InMemoryStore()):` (`services.identity.memory`).
Passing `db=None` to `resolve` uses a store that knows nothing, so every call returns `None`.

## 2. Read score history

```python
from swing_trade_ml.services.identity import ledger

ledger.history(db, security_id, *, view="latest", horizon_days=None, source=None,
               since=None, until=None) -> list[ScoreLedger]   # oldest session first
```

| Rule | Meaning |
|---|---|
| `view="latest"` | The newest revision of each key. This is what a screen shows. |
| `view="first"` | Revision 1 of each key. This is the evidence for accuracy work. |
| `view="all"` | Every revision. |
| Key | session date, horizon, source, model name, model version. |
| Revisions | A re-run with a different value is revision 2, 3 and so on, `supersedes_id` pointing at the one it replaces. Nothing is updated or deleted (the database refuses it). The same value again is a no-op. |
| Gaps | A stock that was meant to be scored and was not is a row with `status = "missing"` and `score = None`. A session with no row at all means the stock was not in that scan's universe. Never read a missing score as 0. |
| `session_date` | The market session of the candle that was scored (IST), never the clock day of the call. |

`ScoreLedger` fields a reader may use: `security_id`, `session_date`, `horizon_days` (5, 10, 15 or `None` when
the model is unknown), `source` (`v1_scan`, `prediction`, `brain`, `catch_up`, `backfill`), `model_id` (or `None`),
`model_name`, `model_version` (empty text when not recorded), `score` (or `None`), `status` (`scored`, `missing`,
`stale`, `late`, `no_score`), `scan_key`, `revision`, `supersedes_id`, `input_cutoff`, `scored_at`, `run_ref`
(brain run id or prediction id when known, else `None`), `note` (the reason for a gap).

Writers (`ledger.append_score`, `append_missing`, `writer.*`) are not part of this contract. Readers never call them.

## 3. What is NOT promised

- No `security_id` column exists yet on `instruments` or `user_watchlist_items`. Resolve by symbol or token.
- Account data (positions, tracking rows) is never part of an identity answer; join it per account in your own code.
- Horizon 10 and 15 histories exist only when a writer records them. 5-day recommendations need only 5.
