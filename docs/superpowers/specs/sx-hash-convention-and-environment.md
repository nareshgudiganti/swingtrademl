# SX5 / SX10: the one hash convention, the dependency environment, the feature manifests

Prepared: before signing. Status: DRAFT for the owner, UNSIGNED. Nothing was trained; everything below was computed without the database.
Code that reproduces every number: `backend/scripts/final_hash_sheet.py` (tests: `backend/tests/test_final_hash_sheet.py`).
Manifests as files: `docs/brain/evidence/sector_prep/feature_manifests_v3.json`.

## 1. Two column-list hashes exist: which one binds what

| Name | Definition | Where it is used |
|---|---|---|
| `feature_list_sha256` ("harness canonical") | `sha256(json.dumps(list(columns), sort_keys=True, separators=(",", ":")).encode("utf-8"))` | `sector_walkforward.feature_list_sha256` (via `_sha`). Written into every fold record (`feature_list_sha256`, `arm_feature_shas`), and **bound by the holdout registry and the approval file**: `holdout_registry` requires, per arm, `feature_list_sha256` and `fit_recipe_sha256`; `sector_walkforward` builds them from `arm_feature_shas`. |
| `manifest_sha256` ("plain") | `sha256(json.dumps(list(columns)).encode("utf-8"))` (Python default separators `", "` and `": "`) | `scripts/arm_row_counts_report.py` and the evidence JSON only. No code gate checks it. |

Values (identical under both naming schemes, recomputed at preparation from the code):

| Arm | Columns | `feature_list_sha256` (canonical, BINDING) | `manifest_sha256` (plain, cross-reference) |
|---|---|---|---|
| A_53 | 53 | `3bd35e8549ebddcea9f52ee680530cdef80a4bb524cf74b1a04c328e1a7141c4` | `f5a8d398d56e47d8bce33943ea78d50d949933022d12c2cb6ef24f5792086f29` |
| R_37 | 37 | `b00fc7076853bbd56ba3f32d254a57cfbc89ef19969f27564c4d5ac4939574c5` | `0615e2fb6c1c9ae120d1455895ad39d3422fcc1bd2053c4bd4b1a1476946d122` |
| C_56 | 56 | `123aa67a611a564d3e41a362b018c08f2d7d18606079abb3d3acb62c01303a0e` | `1a691d7df13366b2c438e5024878bfc228adaa4c77560a39ac39bfd3fd22b910` |

(`feature_manifests_v3.json` is generated from the code and a test asserts the file equals what the code produces. The "A_53 / R_37 / C_56 hashes" in older notes with the prefixes f5a8d398 / 0615e2fb / 1a691d7d are the plain ones.)

### Recommendation

Name **`feature_list_sha256` (the harness canonical form)** in the signed text, as the binding column-list hash, because it is the value the harness writes into every record and the registry and the approval file bind and compare. Keep `manifest_sha256` in the signed text only as a labelled human cross-reference ("not checked by any code"). Never write a bare "the feature hash": always the name plus the first 8 characters.

### Precise definition (the one to be signed)

1. Take the ORDERED list of the arm's column names (strings, exact spelling). Order is part of the hash; reordering changes it.
2. Serialise with JSON: `sort_keys=True` (no effect on a list), separators `","` and `":"` (no spaces), default `ensure_ascii=True` (all names are ASCII). Example: `["a","b","c"]` serialises to exactly the characters `["a","b","c"]`.
3. Encode as UTF-8 bytes.
4. SHA-256, lowercase hex, 64 characters.

Owner's independent re-computation (needs only Python; paste the list from `feature_manifests_v3.json`):

```python
import hashlib, json
cols = json.load(open("docs/brain/evidence/sector_prep/feature_manifests_v3.json"))["arms"]["C_56"]["columns"]
print(len(cols), hashlib.sha256(json.dumps(cols, separators=(",", ":")).encode("utf-8")).hexdigest())
# expect: 56 123aa67a611a564d3e41a362b018c08f2d7d18606079abb3d3acb62c01303a0e
print(hashlib.sha256(json.dumps(cols).encode("utf-8")).hexdigest())   # plain cross-reference: 1a691d7d...
```

Other hashes in the sheet and their exact definitions (so the signed text can name them unambiguously):

- **Row-list hash** (`dataset_rowlist_sha256`, `rows_sha256`): `sha256("\n".join(sorted(keys)).encode("utf-8"))` over keys `SYMBOL|YYYY-MM-DD` (no trailing newline) = `sector_reconcile.keys_sha256`. The `.txt.gz` files hold the same keys one per line with a final newline; `rowlist_text_sha256` is the sha256 of that decompressed text, a different number on purpose.
- **Matrix hash** (the harness `dataset_sha256` = `sector_research.matrix_sha256`): pandas `hash_pandas_object` of the 56 inputs + target + symbol + decision_date. It depends on the pandas version and needs the database build; it is not recomputed by the sheet script (carried from the verification run, labelled as carried).
- **Config hashes** (DatasetSpec, harness, fold definition, recipe, record seal): `sha256` of `json.dumps(obj, sort_keys=True[, separators=(",", ":")])`. NOTE the DatasetSpec `config_sha256` uses default separators (`sector_research.config_sha256`); the harness config, fold definition and recipe use compact separators. The script reproduces each exactly as the code does; do not hand-recompute them with the other separator.
- **File hashes** (events input, exclusion files, protocol files): sha256 of the raw file bytes as checked out. If a checkout converts line endings the hash changes; this repository stores the registry as `-text` and `core.autocrlf` is `true` on the Windows machine, so always hash the committed bytes (`git show <commit>:<path> | sha256sum`) when in doubt.

## 2. Dependency environment the recipe hash assumes

The recipe hash (`sx_recipe.SXRecipe().sha256()`, v `sx_recipe_v1`) is computed over the canonical JSON that INCLUDES the exact versions of `lightgbm`, `scikit-learn`, `numpy`, `pandas`, `scipy` (confirmed: field `versions` in `to_config`; `TRACKED_LIBRARIES`). `build_fit_fn` calls `verify_environment` and refuses (`RecipeVersionMismatch`) when any tracked version differs from the recipe's. So a different library version changes the hash AND is refused at fit time: the check the task asks for already exists.

Environment at hash time (from the script's `environment` block):

| Item | Value |
|---|---|
| Python | CPython 3.12.6, 64-bit |
| OS / platform | Windows 11 (10.0.26300), AMD64 |
| lightgbm | 4.7.0 |
| scikit-learn | 1.9.1 |
| numpy | 2.5.4 |
| pandas | 3.1.0 |
| scipy | 1.18.1 |
| sqlalchemy | 2.1.6 |
| psycopg (+ psycopg-binary) | 3.3.6 |
| project version (`backend/pyproject.toml`) | 0.1.0 |
| `pip freeze` | 97 lines; sha256 of the sorted lines joined by `"\n"` (no trailing newline) = `3e1095b7c20e1621fe6982c76cc0dfc87953ccde3782d2deecb741a4d04eee3c` |
| venv path convention | `<repo>/backend/.venv` |

The pip-freeze hash describes the environment of the machine the sheet was run on at preparation; the script recomputes it each time (`environment.pip_freeze_sorted_sha256`), and any later package change moves it. Only the five tracked libraries are checked by code.

`backend/pyproject.toml` does NOT pin versions: it uses lower bounds (`pandas>=2.2.3`, `numpy>=2.1.0`, `scikit-learn>=1.5.2`, `lightgbm>=4.5.0`, `sqlalchemy>=2.0.36`, `psycopg[binary,pool]>=3.2.3`, `requires-python >=3.11,<3.14`) and there is no lock file in the repository. Recommendation (not done here: it would edit or add project files): add `backend/requirements-research.lock` with the exact `==` lines of the packages above (taken from `pip freeze` of the signing environment), name its sha256 in the signed text, and have the signing step run the script, which prints the live freeze hash, and compare. The in-code refusal on the five tracked versions is the hard guard; the lock file makes the rest reproducible.

Platform notes: LightGBM and numpy results are deterministic for a fixed seed and `n_jobs=1` on the same build, but bit-identical predictions are NOT guaranteed across operating systems, CPU families or library builds (floating-point instruction sets, threading, compiler). The signed text should therefore bind the environment above and say that a re-run on another platform is expected to agree only to numerical tolerance for scores, while all hashes of inputs (columns, rows, configs, folds, files) are platform-independent. The matrix hash is the exception: it depends on the pandas build.

## 3. Feature manifests

Written to `docs/brain/evidence/sector_prep/feature_manifests_v3.json`: for A_53, R_37, C_56 the ordered column list, the count, and both hashes (table in section 1). A_53 = the 53 existing inputs; R_37 = the 37 saved inputs of production model 2 (names and order verified, values not an exact replay: see `R37_KNOWN_SEMANTIC_DIFFERENCES`); C_56 = A_53 plus `sector_ret_10d_vs_nifty`, `sector_rank_10d`, `stock_vs_sector_10d`. The test `test_manifest_file_equals_what_the_code_produces` fails if the file and the code ever disagree.

## 4. The final hash sheet

`python backend/scripts/final_hash_sheet.py <FULL 40-hex commit> [--out sheet.json] [--protocol LABEL=PATH ...] [--prior-sheet final_hashes_v3.json]`

- Refuses unless the argument is the full 40-hex lowercase string equal to `git rev-parse HEAD` and the working tree is completely clean (modified and untracked files both refuse).
- Prints (and optionally writes) JSON with: both column-list hashes per arm, the recipe hash with library versions, the environment block, and per candidate the row-list hashes, DatasetSpec config sha256, harness config sha256, fold-definition sha256 (dev+holdout, the one bound for a holdout run; and dev-only), exclusion file and key hashes, events input sha256, the matrix hash (carried), and the protocol-file hashes (`TO_BE_FILLED_AT_SIGNING` unless `--protocol` is given).
- Verified at preparation: with the repository files at HEAD 53bb5fd it reproduces every number in `final_hashes_v3.json` (row lists, spec and harness configs, folds, exclusions, events, recipe, manifests); test `test_real_repo_files_reproduce_the_verified_v3_hashes` keeps checking that.

**The FINAL commit hash cannot be fixed yet.** The protocol drafts, the registry and the harness are being edited by other agents and are uncommitted; the sheet refuses a dirty tree on purpose. After everything is committed, run the script on that commit (with the protocol files passed via `--protocol`), and sign the sheet it prints. Any later commit means regenerating the sheet and re-signing.
