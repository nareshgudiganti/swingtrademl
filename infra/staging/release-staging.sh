#!/usr/bin/env bash
# Deploy a commit to STAGING. Runs ON the staging droplet, from /root/app-staging.
# Separate from infra/deploy/release.sh (production), which is not touched or reused.
#
#   bash infra/staging/release-staging.sh <commit-sha>
#
# It cannot act on production: it refuses on a host that has production's containers, uses only the
# stml-staging project, and runs preflight first. It never starts the worker, a scan or Kite.
set -euo pipefail

release_sha=${1:?usage: release-staging.sh <commit-sha>}
APP_DIR=${STAGING_APP_DIR:-/root/app-staging}
cd "$APP_DIR"
test "$(git rev-parse HEAD)" = "$release_sha"

# Never on the production host: its containers are named stml-api / stml-postgres / stml-worker.
if docker ps -a --format '{{.Names}}' | grep -Eq '^stml-(api|postgres|worker|frontend|redis)$'; then
  echo "Refusing: this host has production-named containers (stml-api etc). Staging is a separate droplet." >&2
  exit 1
fi
test "$(basename "$APP_DIR")" = app-staging || { echo "Refusing: unexpected app dir $APP_DIR" >&2; exit 1; }

bash infra/staging/preflight.sh "$APP_DIR/.env"

compose=(docker compose -f docker-compose.yml -f docker-compose.staging.yml)
"${compose[@]}" build api frontend
"${compose[@]}" up -d postgres redis
"${compose[@]}" run --rm -e DB_AUTO_MIGRATE=false api python -m alembic upgrade head
"${compose[@]}" up -d --no-build api frontend

ok=false
for attempt in $(seq 1 36); do
  if curl -fsS http://127.0.0.1:8100/api/v1/ready -o /dev/null && curl -fsS http://127.0.0.1:8180/ -o /dev/null; then
    ok=true
    break
  fi
  sleep 5
done
test "$ok" = true || { echo "Staging did not become ready; see: ${compose[*]} logs api" >&2; exit 1; }
echo "Staging release $release_sha is up (local ports 8100 api, 8180 frontend)."
