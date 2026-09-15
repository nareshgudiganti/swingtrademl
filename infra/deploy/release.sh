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

# Keep exact previous images, even when builds replace Compose's image tags.
for service in api worker frontend; do
  image_id=$(docker inspect --format '{{.Image}}' "stml-$service")
  docker tag "$image_id" "stml-rollback-$service:${release_sha:0:12}"
done
python3 - "$backup_dir/rollback.json" "${release_sha:0:12}" <<'PY'
import json, sys
with open(sys.argv[1], 'w') as stream:
    json.dump({'services': {s: {'image': f'stml-rollback-{s}:{sys.argv[2]}'}
                           for s in ('api', 'worker', 'frontend')}}, stream)
PY

worker_stopped=false
rollback() {
  result=$?
  trap - ERR
  if [ "$worker_stopped" = true ]; then
    echo 'Deployment failed; restoring previous application images. Database remains migrated.' >&2
    docker compose -f docker-compose.yml -f docker-compose.prod.yml stop worker || true
    git checkout --detach "$previous_sha"
    docker compose -f docker-compose.yml -f docker-compose.prod.yml \
      -f "$backup_dir/rollback.json" up -d --no-build api worker frontend || true
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
