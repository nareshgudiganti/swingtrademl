# Running SX5 (development run only): `backend/scripts/sx5_run.py`

Status: built and tested on SYNTHETIC data only (`backend/tests/test_sx5_run.py`). Never run on real data. Nothing here
is a signature, an approval or a training authorisation. SX10 stays deferred; this script has no SX10 mode.

The script is the "thin signed caller" named in section 11 of the SX5 protocol. It runs the three arms (A_53, C_56,
R_37) over the 34 development folds with the existing harness and recipe, calls the mechanical verdict once with
development records only, and writes the verdict write-once. It does **not** run the holdout, write the holdout registry,
train a production model, touch the database (SELECT only, local database, read-only transaction) or commit, tag or sign
anything. A `PENDING_HOLDOUT` outcome ends the script: the holdout steps (protocol section 10) stay with the owner.

## When it may run

On or after **2026-12-04**, and only after the owner has signed the SX5 protocol, tagged the signing commit, and
written the two files below. Before that every real run is refused (checked: date, files, tree, commit, hashes,
registry).

## December commands (from `backend/`, Git Bash; same environment rules as the tests)

```
# 1. DRY RUN (the default): prints the plan, every check (PASS/FAIL) and the hash values the authorisation must repeat.
env -u API_KEY -u DATABASE_URL -u JWT_SECRET_KEY -u TRADING_MODE PYTHONPATH=src \
  .venv/Scripts/python.exe scripts/sx5_run.py

# 2. DRY RUN that also reads the data (SELECT only, local Docker Postgres) and prints the row count and the two
#    data hashes. Expected: rows 45935; rowlist_sha256 = fdf0b5665613a501f059d6f6de421463673156efcc1b5a9e7a35fe18e1d19f04;
#    dataset_sha256 = the matrix hash of the signing environment (the v3 value d131c710... was computed on another pandas
#    build, so this is the "TO BE FILLED AT SIGNING" value).
env -u API_KEY -u DATABASE_URL -u JWT_SECRET_KEY -u TRADING_MODE PYTHONPATH=src \
  .venv/Scripts/python.exe scripts/sx5_run.py --with-data

# 3. THE REAL DEVELOPMENT RUN (needs the approval file and the separate authorisation file, see below).
env -u API_KEY -u DATABASE_URL -u JWT_SECRET_KEY -u TRADING_MODE PYTHONPATH=src \
  .venv/Scripts/python.exe scripts/sx5_run.py --run \
  --approval C:/path/to/SX5_approval.json --authorisation C:/path/to/SX5_training_authorisation.json
```

Leave `SECTOR_FEATURES_DSN` unset: the loader then reads the local Docker Postgres. Never point it at production. The
output goes under `backend/data/research_models/walkforward/SX5/run_<id>/` (gitignored): 102 record files
(`dev_NNN_<arm>.json`), `manifest.json`, `VERDICT_dev.json`, `VERDICT_dev.txt` (the protocol's report header first),
`RUN_CONTEXT.json`. Exit code 0 means a verdict was written; 2 means refused (nothing fitted or written; the reasons
are printed). Copy the run folder into the evidence folder and commit it yourself (small text files only).

## The two files the owner writes

**Approval file** (the harness's own format, with one extra key the harness ignores and this script requires):

```
{"protocol_id": "<set at signing>", "approved_by": "<owner>", "candidate": "SX5",
 "config_sha256": "fb5648bbf66a2c00ae0c24cd019d1c6079ff1c3fe2cb203e9bb2ed164d382371",
 "code_commit": "<FULL 40-hex signing commit = git rev-parse HEAD>"}
```

**Training authorisation** (separate, schema `sx5-training-authorisation-v1`; development only; the script refuses any
file that mentions `holdout_authorised: true`):

```
{"schema": "sx5-training-authorisation-v1", "candidate": "SX5", "scope": "development_only",
 "training_authorised": true, "protocol_id": "<same as the approval>", "authorised_by": "<owner>",
 "authorised_on": "<YYYY-MM-DD, India time, 2026-12-04 or later, not in the future>",
 "statement": "<owner's own words authorising the SX5 development run>",
 "code_commit": "<same full commit>", "mde_h": 0.0018,
 "protocol_sha256": "...", "config_sha256": "...", "verdict_params_sha256": "...", "verdict_code_sha256": "...",
 "recipe_sha256": "...", "lock_file_sha256": "...", "rowlist_sha256": "...", "dataset_sha256": "..."}
```

`mde_h` is the signed MDE_H as a FRACTION of one holding return (0.0018 = 0.18 percentage points per trade; typing 0.18
is refused). E\* (checklist decision 2) is not used by the code and is not part of these files. Step 1's output prints the
six hashes that can be computed without data (`authorisation_must_repeat`); step 2 prints the other two.

## What a real run checks (each is printed on every dry run)

1. India-time date is 2026-12-04 or later. 2. The approval file names SX5 and the complete `config_sha256`.
3. The separate authorisation is well formed, development-only, dated 2026-12-04..today, and does not open the holdout.
4. Clean tree (nothing modified, nothing untracked). 5. HEAD, the approval's `code_commit` and the authorisation's
`code_commit` are the same full commit (it is also the records' `code_version`). 6. The protocol file, DatasetSpec
config, verdict parameter set (with the signed MDE_H), verdict code, recipe and lock file hash to the authorisation's
values; after the data is read and before any fit, the row-list hash and the matrix hash do too.
7. The holdout registry loads read-only, verifies, and shows no consumed event.

It also uses seed 42 (the harness refuses any other), passes only development folds (never a holdout fold), and the
harness itself refuses any output folder that is a production model location.

## After the run

* `PASS`, `FAIL`, `INCONCLUSIVE`: record with equal prominence (protocol section 9). No re-run under the same protocol id.
* `PENDING_HOLDOUT`: stop. The holdout needs the owner's separate signed registry authorisation (protocol section 10),
  which this script neither writes nor uses.
* Any crash: write down what happened before anything else, do not re-run, and decide in writing (the harness refuses
  to overwrite records).

## Tests

`env -u API_KEY -u DATABASE_URL -u JWT_SECRET_KEY -u TRADING_MODE PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/test_sx5_run.py -q`
(no database; about one minute).
