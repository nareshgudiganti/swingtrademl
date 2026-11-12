#!/usr/bin/env bash
# Off-server copy of the model files + the manifest that records them (owner request, backup drill).
# Called by daily-backup.sh after the database copy; can also be run alone:  bash backup-models-offsite.sh [stamp]
#
# - Writes manifest.json from the live registry (read-only): name, version, status, file, size, sha256 for every
#   ml_models row, plus brain_meta_v* files (which have no row).
# - Each model file is uploaded ONCE, encrypted, as models/<sha256>.enc. The name is the content hash, so an
#   unchanged file is never transferred again and an uploaded file can never be overwritten by a different one.
#   Model files are never deleted from the remote.
# - The manifest is uploaded as manifests/manifest-<stamp>.json.enc, the same <stamp> as that night's
#   database-<stamp>.sql.gz.enc, so the two pair up for scripts/verify_restore.py. Manifests are tiny and kept.
# - Each file is re-hashed after copying out of the container; a file whose hash differs from the manifest
#   is NOT uploaded and the run fails.
# Same passphrase and rclone remote as daily-backup.sh. Reads the live database and files only.
set -euo pipefail

WORKER_CONTAINER=${WORKER_CONTAINER:-stml-worker}
MODEL_DIR_IN_CONTAINER=${MODEL_DIR_IN_CONTAINER:-/app/data/models}
REMOTE=${BACKUP_REMOTE:-gdrive:swingtrademl-backups}
PASSPHRASE_FILE=${PASSPHRASE_FILE:-/root/.backup-passphrase}
stamp=${1:-$(date +%Y%m%d_%H%M)}

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
enc() { openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -salt -pass "file:$PASSPHRASE_FILE" -in "$1" -out "$2"; }

docker exec "$WORKER_CONTAINER" python -m swing_trade_ml.ml.backup_manifest write --out /tmp/manifest.json
docker cp "$WORKER_CONTAINER:/tmp/manifest.json" "$work/manifest.json"

# "<sha256> <file name>" for every file the manifest says exists (models and brain_meta files).
python3 - "$work/manifest.json" >"$work/list.txt" <<'PY'
import json, sys
m = json.load(open(sys.argv[1]))
for e in m["models"] + m["extra_files"]:
    if e.get("sha256") and e.get("file"):
        print(e["sha256"], e["file"])
PY

uploaded=0; present=0; failed=0
while read -r sha name; do
  if [ -n "$(rclone lsf "$REMOTE/models/$sha.enc" 2>/dev/null)" ]; then present=$((present + 1)); continue; fi
  docker cp "$WORKER_CONTAINER:$MODEL_DIR_IN_CONTAINER/$name" "$work/$name"
  if [ "$(sha256sum "$work/$name" | cut -d' ' -f1)" != "$sha" ]; then
    echo "MODEL BACKUP: $name does not match its recorded sha256 - NOT uploaded." >&2
    failed=$((failed + 1)); rm -f "$work/$name"; continue
  fi
  enc "$work/$name" "$work/$sha.enc"
  rclone copy "$work/$sha.enc" "$REMOTE/models" && uploaded=$((uploaded + 1)) || failed=$((failed + 1))
  rm -f "$work/$name" "$work/$sha.enc"
done <"$work/list.txt"

enc "$work/manifest.json" "$work/manifest-$stamp.json.enc"
rclone copy "$work/manifest-$stamp.json.enc" "$REMOTE/manifests"
missing=$(python3 -c "import json,sys; print(sum(1 for e in json.load(open(sys.argv[1]))['models'] if e['missing']))" "$work/manifest.json")
echo "Model files off-server: uploaded $uploaded, already there $present, failed $failed; registry rows with no file: $missing"
[ "$failed" -eq 0 ]
