#!/usr/bin/env bash
# Deploy an already-tested commit. Never enable trading or invoke a scan.
set -euo pipefail
cd /root/app
release_sha=$1
previous_sha=$2
test "$(git rev-parse HEAD)" = "$release_sha"
compose=(docker compose -f docker-compose.yml -f docker-compose.prod.yml)
backup_dir="/root/backups/release-$(date +%Y%m%d_%H%M%S)-${release_sha:0:12}"
mkdir -p "$backup_dir"
printf '%s\n' "$previous_sha" > "$backup_dir/previous-sha"

# Preserve the running images for rollback, tagging them by the reference
# Compose created them under while it still points at the running build:
# `docker tag` cannot resolve a container's raw image ID ({{.Image}}, a config
# digest) under the containerd image store. A service whose running image is
# no longer reachable by name — prune collects it once a rebuild moves the tag
# — is skipped, not fatal: refusing to deploy would leave no way out of that
# state, and the database backup below is the safety net that matters.
preserved=0
for service in api worker frontend; do
  image_ref=$(docker inspect --format '{{.Config.Image}}' "stml-$service")
  running_id=$(docker inspect --format '{{.Image}}' "stml-$service")
  tagged_id=$(docker image inspect "$image_ref" --format '{{.Id}}' 2>/dev/null || true)
  if [ -n "$tagged_id" ] && [ "$tagged_id" = "$running_id" ]; then
    docker tag "$image_ref" "stml-rollback-$service:${release_sha:0:12}"
    preserved=$((preserved + 1))
  else
    echo "WARNING: no rollback image for $service; it is not running $image_ref." >&2
  fi
done
if [ "$preserved" -eq 3 ]; then
python3 - "$backup_dir/rollback.json" "${release_sha:0:12}" <<'PY'
import json, sys
with open(sys.argv[1], 'w') as stream:
    json.dump({'services': {s: {'image': f'stml-rollback-{s}:{sys.argv[2]}'}
                           for s in ('api', 'worker', 'frontend')}}, stream)
PY
else
  echo "WARNING: only $preserved/3 images preserved; a failed release will be rolled back by rebuilding $previous_sha." >&2
fi

worker_stopped=false
rollback() {
  result=$?
  trap - ERR
  if [ "$worker_stopped" = true ]; then
    echo 'Deployment failed; restoring the previous release. Database remains migrated.' >&2
    docker compose -f docker-compose.yml -f docker-compose.prod.yml stop worker || true
    git checkout --detach "$previous_sha"
    if [ "$preserved" -eq 3 ]; then
      docker compose -f docker-compose.yml -f docker-compose.prod.yml \
        -f "$backup_dir/rollback.json" up -d --no-build api worker frontend || true
    else
      docker compose -f docker-compose.yml -f docker-compose.prod.yml \
        up -d --build api worker frontend || true
    fi
  fi
  exit "$result"
}
trap rollback ERR

"${compose[@]}" build api worker frontend
"${compose[@]}" stop worker
worker_stopped=true
docker exec stml-postgres pg_dumpall -U swingtrade > "$backup_dir/database.sql"
test -s "$backup_dir/database.sql"
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
