#!/usr/bin/env bash
# Deploy an already-tested commit. Never enable trading or invoke a scan.
set -euo pipefail
# Where the app and the backups live. The defaults are the server's own; only the tests change them.
APP_DIR=${APP_DIR:-/root/app}
BACKUP_ROOT=${BACKUP_ROOT:-/root/backups}
cd "$APP_DIR"
release_sha=$1
previous_sha=$2
test "$(git rev-parse HEAD)" = "$release_sha"

# From here on, any failure or signal undoes what this script did (see rollback). The check above comes first on
# purpose: if this folder is not on the release commit, something else is wrong and nothing is touched.
# backup_dir is only used by the rollback after the worker was stopped, by which time it is set.
worker_stopped=false
dump_complete=false
rolled_back=false
# The rollback runs at most once, whichever way the script ends (a failed command, a signal, any non-zero exit).
# Before the worker was stopped the running site was never touched, so the only thing to undo is the checkout:
# deploy.yml has already put this folder on the release commit, and a folder left there after a failed release
# would make the next deploy record that commit as the one that was running.
rollback() {
  result=$1
  [ "$rolled_back" = true ] && return 0
  rolled_back=true
  # A second signal must not cut the rollback short, and nothing below may stop the next step: every step is
  # tried, and the script exits with the code of the failure that started the rollback, never one of its own.
  trap '' HUP INT TERM
  set +e
  if [ "$worker_stopped" = true ]; then
    echo 'Deployment failed; restoring previous application images. Database remains migrated.' >&2
    # A dump that did not finish is removed first: on 22 Nov it was the partial file that had filled the disk,
    # and restarting anything on a full disk fails. A finished dump (a later step failed) is kept.
    [ "$dump_complete" = true ] || rm -f "$backup_dir/database.sql"
    docker compose -f docker-compose.yml -f docker-compose.prod.yml stop worker
    git checkout --detach "$previous_sha" \
      || echo "WARNING: could not check out $previous_sha; the previous images are started anyway." >&2
    docker compose -f docker-compose.yml -f docker-compose.prod.yml \
      -f "$backup_dir/rollback.json" up -d --no-build api worker frontend \
      || echo "WARNING: could not start the previous images with compose." >&2
    # Last resort, whichever step above failed: the worker (exits, scans, the brain) must be running.
    if [ "$(docker inspect -f '{{.State.Running}}' stml-worker 2>/dev/null)" != true ]; then
      docker start stml-worker \
        || echo "ERROR: THE WORKER IS STOPPED and could not be started. Run 'docker start stml-worker' on the server now." >&2
    fi
  else
    echo "Deployment failed before the worker was stopped; the running version was not touched. Putting the folder back on $previous_sha." >&2
    git checkout --detach "$previous_sha" \
      || echo "WARNING: could not check out $previous_sha; check /root/app by hand before the next deploy." >&2
  fi
}
on_error() { result=$?; trap - ERR; rollback "$result"; exit "$result"; }
on_exit() { result=$?; trap - EXIT; if [ "$result" -ne 0 ]; then rollback "$result"; fi; exit "$result"; }
trap on_error ERR
trap on_exit EXIT
# A cancelled run, a dropped connection or the 30 minute limit end the script with a signal, which the ERR trap
# never sees. Each one exits with the usual 128 + signal number, and the EXIT trap does the rest.
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM


# The disk check lives in preflight.sh so that deploy.yml can run it before it checks out this commit. It is run
# again here, so a release started by hand is checked too. A refusal exits before anything is written or stopped.
bash "$APP_DIR/infra/deploy/preflight.sh"

compose=(docker compose -f docker-compose.yml -f docker-compose.prod.yml)
export GIT_SHA="$release_sha"  # baked into the image (backend/Dockerfile) for model cards
backup_dir="$BACKUP_ROOT/release-$(date +%Y%m%d_%H%M%S)-${release_sha:0:12}"
mkdir -p "$backup_dir"
printf '%s\n' "$previous_sha" > "$backup_dir/previous-sha"

# Keep exact previous images, even when builds replace Compose's image tags.
#
# A prune can delete an image out from under its own running container: the
# container keeps working, `docker inspect` still reports the ID, but `docker
# tag` fails with "No such image" — which aborted every deploy from 2026-09-14
# on, before the build step, leaving production pinned to stale containers.
# Committing the live container yields an equivalent rollback target, so a
# vanished image degrades the snapshot's provenance rather than the deploy.
for service in api worker frontend; do
  rollback_image="stml-rollback-$service:${release_sha:0:12}"
  image_id=$(docker inspect --format '{{.Image}}' "stml-$service")
  docker tag "$image_id" "$rollback_image" 2>/dev/null \
    || docker commit "stml-$service" "$rollback_image" >/dev/null
done
python3 - "$backup_dir/rollback.json" "${release_sha:0:12}" <<'PY'
import json, sys
with open(sys.argv[1], 'w') as stream:
    json.dump({'services': {s: {'image': f'stml-rollback-{s}:{sys.argv[2]}'}
                           for s in ('api', 'worker', 'frontend')}}, stream)
PY

"${compose[@]}" build api worker frontend
# Marked before the stop, not after: a stop that fails half way must still be rolled back.
worker_stopped=true
"${compose[@]}" stop worker
docker exec stml-postgres pg_dumpall -U swingtrade > "$backup_dir/database.sql"
test -s "$backup_dir/database.sql"
dump_complete=true
"${compose[@]}" run --rm -e DB_AUTO_MIGRATE=false api python -m alembic upgrade head
"${compose[@]}" up -d --no-build api frontend
"${compose[@]}" up -d --no-build worker

# Require a heartbeat from this deployment, not the previous worker's file.
verify_after=$(date +%s)
verified=false
for attempt in $(seq 1 36); do
  if docker exec -i stml-api python - "$verify_after" < infra/deploy/verify.py \
      && curl -fsS https://swingtrademl.com/ -o /dev/null; then
    verified=true
    break
  fi
  sleep 5
done
test "$verified" = true
echo "Verified deployment $release_sha; rollback images and database backup: $backup_dir"
