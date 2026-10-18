#!/usr/bin/env bash
# Restore drill: prove the newest database backup can actually be restored.
#
# Restores the newest backup into a THROWAWAY Postgres container (same image, no volume, no network),
# then compares row counts of key tables with the live database. The live database is only ever read
# (SELECT count(*)). The throwaway container is removed at the end, pass or fail.
#
# Run on the droplet:   bash /root/app/infra/deploy/restore-drill.sh
# Optional settings:    BACKUP_ROOT (default /root/backups), BACKUP_FILE (a specific dump),
#                       LIVE_CONTAINER (default stml-postgres), DB_USER, DB_NAME
#                       UPGRADE_CHECK=1 also runs `alembic upgrade head` on the restored copy (tracker qa5),
#                       with the code of UPGRADE_REF (a branch, tag or commit on GitHub; default: the
#                       commit /root/app is on, i.e. what is deployed). Run it before deploying a migration.
#                       API_CONTAINER (default stml-api): its image supplies Python and the libraries.
# Exit code 0 = restored, counts agree (and the upgrade worked); 1 = the drill failed (read the summary).
set -euo pipefail

BACKUP_ROOT=${BACKUP_ROOT:-/root/backups}
LIVE_CONTAINER=${LIVE_CONTAINER:-stml-postgres}
DB_USER=${DB_USER:-swingtrade}
DB_NAME=${DB_NAME:-swing_trade_ml}
DRILL=stml-restore-drill
UPGRADE_CHECK=${UPGRADE_CHECK:-0}
UPGRADE_REF=${UPGRADE_REF:-}
API_CONTAINER=${API_CONTAINER:-stml-api}
APP_DIR=${APP_DIR:-/root/app}
# pg_dumpall recreates the app database under its own name, so the restored copy is ALSO called
# $DB_NAME: a "database name differs from live" guard cannot work here. The live database is kept out
# of reach by WHICH SERVER is used instead (the throwaway container; see the upgrade step below).
if [ "$DRILL" = "$LIVE_CONTAINER" ]; then
  echo "RESTORE DRILL REFUSED: the throwaway container name equals the live one ($LIVE_CONTAINER)" >&2
  exit 1
fi
drill_password="drill-$RANDOM-$RANDOM-$RANDOM"
upgrade_src=""
TABLES="instruments candles positions trades orders signals brain_runs brain_decisions ml_models users portfolio_snapshots"

# The newest copy: a deploy's plain database.sql or a nightly compressed database.sql.gz (daily-backup.sh).
dump=${BACKUP_FILE:-$(ls -t "$BACKUP_ROOT"/*/database.sql "$BACKUP_ROOT"/*/database.sql.gz 2>/dev/null | head -1 || true)}
if [ -z "$dump" ] || [ ! -s "$dump" ]; then
  echo "RESTORE DRILL FAILED: no backup file found under $BACKUP_ROOT" >&2
  exit 1
fi
echo "Backup:  $dump ($(du -h "$dump" | cut -f1), made $(date -r "$dump" '+%Y-%m-%d %H:%M'))"
plain_copy=""
if [ "${dump%.gz}" != "$dump" ]; then
  # The steps below read the dump several times; unpack once into a temporary file.
  plain_copy=$(mktemp)
  gunzip -c "$dump" >"$plain_copy"
  backup_label=$dump
  dump=$plain_copy
fi

# The live container's exact image (by ID, not by tag: "latest-pg17" may have been pulled again since)
# and the exact TimescaleDB version installed in the live database. Restoring with a different
# Timescale version fails at post_restore ("catalog version mismatch"), found on prod 2026-10-14.
image=$(docker inspect --format '{{.Image}}' "$LIVE_CONTAINER")
ts_version=$(docker exec "$LIVE_CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -tAc \
  "select extversion from pg_extension where extname = 'timescaledb'" | tr -d ' ')
# The Timescale catalog version written INSIDE the backup (_timescaledb_catalog.metadata,
# key timescaledb_version, in the app database's section). On prod 2026-10-14 the live extension
# reported 2.29.2 while the backup's catalog said 2.29.0, so restoring at the live version still failed.
# Restore at the backup's version, then upgrade to the live version, as a real recovery would.
dump_ts_version=$(awk -v app="$DB_NAME" '
    /^\\connect / { in_app = ($2 == app) }
    in_app && /^timescaledb_version\t/ { split($0, f, "\t"); print f[2]; exit }' "$dump")
restore_version=${dump_ts_version:-$ts_version}
echo "Image:   ${image:7:12} (the live database container's own image)"
echo "TimescaleDB: live database $ts_version, inside the backup ${dump_ts_version:-unknown}; restoring at $restore_version"
cleanup() {
  docker rm -f "$DRILL" >/dev/null 2>&1 || true
  [ -z "$plain_copy" ] || rm -f "$plain_copy"
  [ -z "$upgrade_src" ] || rm -rf "$upgrade_src"
}
trap cleanup EXIT
cleanup

# Throwaway server: random password, no published port, no network, no volume.
docker run -d --name "$DRILL" --network none \
  -e POSTGRES_USER="$DB_USER" -e POSTGRES_DB=postgres \
  -e POSTGRES_PASSWORD="$drill_password" "$image" >/dev/null
# The image starts a temporary server for first-time setup, stops it, then starts the real one.
# Wait for the "init process complete" line, then for the real server to answer a query.
ready=false
for _ in $(seq 1 90); do
  if docker logs "$DRILL" 2>&1 | grep -q 'init process complete' \
      && docker exec "$DRILL" psql -U "$DB_USER" -d postgres -tAc 'select 1' >/dev/null 2>&1; then
    ready=true; break
  fi
  sleep 2
done
if [ "$ready" != true ]; then echo "RESTORE DRILL FAILED: throwaway server did not start" >&2; exit 1; fi

echo "Restoring into the throwaway container..."
# TimescaleDB's restore procedure: create the database and extension first and switch Timescale into
# restore mode, so hypertables (candles) come back as hypertables. A plain replay of the dump brings the
# rows back but leaves candles a plain table ("table candles is not a hypertable"), found 2026-10-14.
in_drill() { docker exec "$DRILL" psql -U "$DB_USER" -v ON_ERROR_STOP=1 -q "$@" >/dev/null; }
# template0, not the default template1: the Timescale image pre-installs the extension (at the image's
# newest version) into template1, so every new database would already have it and the pinned
# "create extension ... version" below would be silently skipped (seen on prod 2026-10-14).
in_drill -d postgres -c "create database $DB_NAME template template0"
in_drill -d "$DB_NAME" -c "create extension if not exists timescaledb version '$restore_version'" \
  -c "select timescaledb_pre_restore()"
errors_file=$(mktemp)
# "-f -" makes psql prefix each error with its line in the dump ("psql:<stdin>:LINE: ERROR: ...").
docker exec -i "$DRILL" psql -U "$DB_USER" -d postgres -q -v ON_ERROR_STOP=0 -f - <"$dump" >/dev/null 2>"$errors_file" || true
in_drill -d "$DB_NAME" -c "select timescaledb_post_restore()"
if [ -n "$ts_version" ] && [ "$restore_version" != "$ts_version" ]; then
  # Upgrade must be the first command of a fresh session (-X: no psqlrc), per TimescaleDB.
  echo "Upgrading the restored copy from TimescaleDB $restore_version to $ts_version..."
  docker exec "$DRILL" psql -X -U "$DB_USER" -d "$DB_NAME" -v ON_ERROR_STOP=1 -q \
    -c "alter extension timescaledb update to '$ts_version'" >/dev/null
fi
restored_version=$(docker exec "$DRILL" psql -U "$DB_USER" -d "$DB_NAME" -tAc \
  "select extversion from pg_extension where extname = 'timescaledb'" | tr -d ' ')
echo "Restored copy is on TimescaleDB $restored_version"
# Which database each dump line belongs to: pg_dumpall switches with "\connect <db>" lines.
db_starts=$(mktemp)
grep -n '^\\connect ' "$dump" | sed -E 's/^([0-9]+):\\connect ([^ ]+).*/\1 \2/' >"$db_starts"
# Expected and harmless: the dump re-creates the role, database and extension prepared above. Only
# errors inside the app database ($DB_NAME) fail the drill; other databases in the dump are reported.
grep 'ERROR:' "$errors_file" \
  | grep -v -e "role \"$DB_USER\" already exists" -e "database \"$DB_NAME\" already exists" \
            -e 'extension "timescaledb" already exists' \
  | awk -v starts="$db_starts" -v app="$DB_NAME" '
      BEGIN { n = 0; while ((getline l < starts) > 0) { split(l, a, " "); at[++n] = a[1]; db[n] = a[2] } }
      { match($0, /:[0-9]+: ERROR/); line = substr($0, RSTART + 1, RLENGTH - 8) + 0; name = "(roles/globals)"
        for (i = 1; i <= n; i++) if (at[i] <= line) name = db[i]
        sub(/^.*ERROR: +/, ""); print (name == app ? "APP" : "OTHER") "\t" name "\t" $0 }' >"$errors_file.all" || true
grep '^APP' "$errors_file.all" | cut -f3 >"$errors_file.real" || true
other_errors=$(grep -c '^OTHER' "$errors_file.all" || true)
restore_errors=$(wc -l <"$errors_file.real" | tr -d ' ')

count() { # container table -> row count, or "missing"
  docker exec "$1" psql -U "$DB_USER" -d "$DB_NAME" -tAc "select count(*) from $2" 2>/dev/null | tr -d ' ' || true
}

failed=0
printf '\n%-22s %12s %12s  %s\n' TABLE BACKUP LIVE CHECK
for t in $TABLES; do
  restored=$(count "$DRILL" "$t"); live=$(count "$LIVE_CONTAINER" "$t")
  restored=${restored:-missing}; live=${live:-missing}
  verdict=ok
  if [ "$restored" = missing ]; then
    verdict="MISSING IN BACKUP"; failed=1
  elif [ "$live" != missing ] && [ "$live" -gt 0 ] && [ "$restored" -eq 0 ]; then
    verdict="EMPTY IN BACKUP"; failed=1
  elif [ "$live" != missing ] && [ "$restored" -gt "$live" ]; then
    verdict="note: live has fewer rows (rows deleted since the backup)"
  fi
  printf '%-22s %12s %12s  %s\n' "$t" "$restored" "$live" "$verdict"
done

hyper=$(docker exec "$DRILL" psql -U "$DB_USER" -d "$DB_NAME" -tAc \
  "select count(*) from timescaledb_information.hypertables where hypertable_name = 'candles'" 2>/dev/null | tr -d ' ' || true)
if [ "$hyper" = 1 ]; then
  echo "candles is a TimescaleDB hypertable after the restore: ok"
else
  echo "candles is NOT a hypertable after the restore"; failed=1
fi

echo
echo "Restore errors in $DB_NAME (other than the expected role/database/extension ones): $restore_errors"
if [ "$restore_errors" -gt 0 ]; then
  head -10 "$errors_file.real"
  failed=1
fi
if [ "${other_errors:-0}" -gt 0 ]; then
  echo "Note: $other_errors error(s) in OTHER databases in this backup (not the app database):"
  grep '^OTHER' "$errors_file.all" | cut -f2,3 | sort | uniq -c | head -10
fi
rm -f "$errors_file" "$errors_file.real" "$errors_file.all" "$db_starts"

# ---- Database upgrade test (tracker qa5): run the migrations on the restored, prod-shaped copy. ------
# Proves `alembic upgrade head` works on real prod data BEFORE a deploy runs it on the live database
# (release.sh migrates with the worker stopped; a migration failing there means a rollback).
# Runs after the row-count comparison above, so the migration cannot affect that comparison.
#
# SAFETY: this must never touch the live database. Independent guards:
#   1. the migration container joins the THROWAWAY container's network namespace
#      (--network container:$DRILL). That namespace has network "none": its only address is its own
#      localhost, so the live server (stml-postgres on the compose network) cannot even be reached;
#   2. the throwaway container is checked to really have network mode "none" and not be the live one;
#   3. before migrating, a guard script checks that the server it reached carries a marker database
#      that was created only inside the throwaway container. No marker = stop, nothing migrated;
#   4. the live .env is never loaded: the code is unpacked to a temporary folder that has no .env,
#      and DATABASE_URL (pointing at 127.0.0.1 in the throwaway namespace) is passed explicitly.
upgrade_line=""
if [ "$UPGRADE_CHECK" = 1 ] && [ "$failed" -eq 0 ]; then
  echo
  echo "Database upgrade test (alembic upgrade head on the restored copy)..."
  marker=stml_restore_drill_marker
  net_mode=$(docker inspect --format '{{.HostConfig.NetworkMode}}' "$DRILL")
  if [ "$net_mode" != none ] || [ "$DRILL" = "$LIVE_CONTAINER" ]; then
    echo "UPGRADE TEST REFUSED: the throwaway container is not isolated (network '$net_mode')" >&2
    failed=1
  else
    # The backup brought prod's role password with it; give the copy the drill's own password again.
    # Local socket inside the throwaway container only.
    in_drill -d postgres -c "alter role $DB_USER password '$drill_password'" -c "create database $marker"
    # Which code: UPGRADE_REF fetched from GitHub, or the commit the app folder is on (deployed).
    if [ -n "$UPGRADE_REF" ]; then
      git -C "$APP_DIR" fetch -q origin "$UPGRADE_REF"
      src_sha=$(git -C "$APP_DIR" rev-parse FETCH_HEAD)
    else
      src_sha=$(git -C "$APP_DIR" rev-parse HEAD)
    fi
    # Unpack only that commit's backend code to a temporary folder; the app folder's checkout is untouched.
    upgrade_src=$(mktemp -d)
    git -C "$APP_DIR" archive "$src_sha" backend/src backend/alembic backend/alembic.ini | tar -x -C "$upgrade_src"
    cat >"$upgrade_src/drill_guard.py" <<'PY'
import os
import sys

from sqlalchemy import create_engine, text

with create_engine(os.environ["DATABASE_URL"]).connect() as connection:
    found = connection.execute(
        text("select 1 from pg_database where datname = :marker"), {"marker": os.environ["MARKER"]}
    ).scalar()
if not found:
    sys.exit("Not the throwaway server (no marker database): refusing to migrate.")
PY
    chmod -R a+rX "$upgrade_src"
    api_image=$(docker inspect --format '{{.Image}}' "$API_CONTAINER")
    revision() {
      docker exec "$DRILL" psql -U "$DB_USER" -d "$DB_NAME" -tAc \
        "select string_agg(version_num, ',') from alembic_version" 2>/dev/null | tr -d ' ' || true
    }
    before=$(revision)
    echo "Code:    ${UPGRADE_REF:-deployed commit} = ${src_sha:0:12}"
    echo "Before:  database revision ${before:-none}"
    upgrade_log=$(mktemp)
    upgrade_status=0
    # Python and the libraries come from the live API image; the code (src + migrations) from src_sha.
    # A branch that ADDS a Python library will fail here on the import: that needs a real deploy build.
    docker run --rm --network "container:$DRILL" \
      -v "$upgrade_src:/drill-src:ro" -w /drill-src/backend \
      -e PYTHONPATH=/drill-src/backend/src \
      -e DATABASE_URL="postgresql+psycopg://$DB_USER:$drill_password@127.0.0.1:5432/$DB_NAME" \
      -e MARKER="$marker" -e DB_AUTO_MIGRATE=false -e ENABLE_SCHEDULER=false \
      -e TELEGRAM_ENABLED=false -e TRADING_MODE=paper -e ALLOW_LIVE_TRADING=false \
      --entrypoint sh "$api_image" -c \
      'set -e; python /drill-src/drill_guard.py; python -m alembic heads | sed "s/^/Head:    /"; python -m alembic upgrade head' \
      >"$upgrade_log" 2>&1 || upgrade_status=$?
    after=$(revision)
    grep '^Head:' "$upgrade_log" || true
    echo "After:   database revision ${after:-none}"
    if [ "$upgrade_status" -eq 0 ]; then
      echo "UPGRADE TEST PASSED: the migrations ran on the prod-shaped copy (${before:-none} -> ${after:-none})."
      upgrade_line=" upgrade ${src_sha:0:12} ${before:-none}->${after:-none}"
    else
      # Alembic's output names the failing migration and the SQL error (schema, not table rows).
      echo "UPGRADE TEST FAILED (exit $upgrade_status). Last lines from alembic:"
      grep -v '^Head:' "$upgrade_log" | tail -25 || true
      failed=1
      upgrade_line=" upgrade-FAILED ${src_sha:0:12}"
    fi
    rm -f "$upgrade_log"
  fi
elif [ "$UPGRADE_CHECK" = 1 ]; then
  echo "Database upgrade test skipped: the restore itself failed."
fi

record=$BACKUP_ROOT/restore-drill-last.txt
if [ "$failed" -eq 0 ]; then
  echo "RESTORE DRILL PASSED: the backup restores and every key table has its rows."
  [ -z "$upgrade_line" ] || echo "The migrations of ${UPGRADE_REF:-the deployed commit} also ran cleanly on the restored copy."
  printf 'passed %s %s%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${backup_label:-$dump}" "$upgrade_line" >"$record" 2>/dev/null || true
  exit 0
fi
echo "RESTORE DRILL FAILED: see the table and errors above. The live database was not touched." >&2
printf 'failed %s %s%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${backup_label:-$dump}" "$upgrade_line" >"$record" 2>/dev/null || true
exit 1
