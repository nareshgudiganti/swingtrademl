# Model artifact backup (off-droplet)

Production trains and serves models from **`MODEL_ARTIFACT_DIR`** (default `./data/models` in the app
working directory). Settings also support **`MODEL_BACKUP_DIR`** for a second on-disk copy when set in
`.env` on the droplet (see `core/config.py` — do not commit `.env`).

## Why

A 2026-09-15 recovery lost trained artifacts on the droplet. Git does not store model binaries.

## What to copy

From the droplet app root (typical `/root/app`), inside the api container or on the host bind mount:

- Everything under the resolved `MODEL_ARTIFACT_DIR` (`.pkl`, `.joblib`, metadata JSON if present).
- Note the **git SHA** and date in your backup folder name, e.g. `models-backup-20261005-fcaef35`.

## One-time manual backup (on droplet)

```bash
cd /root/app
SHA=$(git rev-parse --short HEAD)
DEST=/root/backups/models-$SHA-$(date +%Y%m%d)
mkdir -p "$DEST"
docker exec stml-api sh -c 'ls -la "${MODEL_ARTIFACT_DIR:-./data/models}"' 2>/dev/null || ls -la data/models
# If models live on the host volume:
cp -a data/models/* "$DEST/" 2>/dev/null || docker cp stml-api:/app/data/models "$DEST"
```

Adjust paths if your compose mounts differ.

## Copy off the droplet (from your PC)

Use `scp` or `rsync` with SSH key (IP in `docs/ROADMAP_TRACKER.md` — whitelist on Kite separately):

```bash
rsync -avz root@<droplet-ip>:/root/backups/models-* ./local-backups/
```

Never paste droplet passwords or API keys into chat or docs.

## Optional: enable `MODEL_BACKUP_DIR`

On the droplet, set `MODEL_BACKUP_DIR` to a second path on disk (e.g. `/root/backups/models-live`)
in `/root/app/.env`, restart api/worker, and confirm training code writes duplicates (if wired for your
model train path). If unset, rely on scheduled `rsync` above.

## Cadence

- After every **meta-train** or promotion you care about.
- Before **major deploys** that touch `ml/` or training jobs.
- Monthly minimum while M06/M09 evidence is being collected.

Mark ROADMAP Phase 0 “Model artifact off-droplet backup” done when you have at least one verified
off-droplet copy and a repeat date on your calendar.

## Where the copies live (read this first)

| Copy | Where | Survives losing the server? |
|---|---|---|
| Live models (`MODEL_ARTIFACT_DIR`) | droplet disk | no |
| Daily server-side copy (`job_backup_models` -> `MODEL_BACKUP_DIR`, second volume) | **same droplet disk** | **no** - protects against a deleted or corrupted file, not a lost server |
| PC copy (below) | your Windows PC | **yes - this is the only off-server copy** |

## Off-server copy without SSH (route + script)

- **Route:** `GET /api/v1/ml/backup/models.zip` (same API-key protection as the rest of `/ml`; 401/403
  without it). Read-only. Streams a zip of every registered artifact, archived versions included,
  plus `manifest.json` (model, version, status, file name in the zip, size, sha256, produced-at, and
  `missing: true` for registry rows whose file is gone). No server paths, env values or secrets are
  included. Built from the same registry/path logic as the server-side backup (`ml/backup.py`).
- **Script:** `scripts/backup-models-from-prod.ps1` reads the key from the user environment variable
  `STML_API_KEY`, downloads to `%USERPROFILE%\stml-model-backups\stml-models-<date>.zip`, checks every
  sha256 against the manifest, keeps the newest 8 zips (`-Keep`), and exits non-zero with a plain
  message on any failure. A "server is missing files" warning is printed (exit 0) when the manifest
  lists missing artifacts - treat it as a finding. Registering it as a weekly Windows task is shown in
  the comment at the top of the script.

## Not covered

Database dumps taken at each deploy (`infra/deploy/release.sh`) are also stored only on the server.
This change does **not** back them up off-server; the registry rows, predictions and trades would still
be lost with the droplet.
