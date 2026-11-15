#!/usr/bin/env bash
# Daily database copy (tracker af4). Run nightly by .github/workflows/daily-backup.yml over the deploy key.
#
# 1. On the server: pg_dumpall, compressed, into /root/backups/daily-YYYYmmdd_HHMM/database.sql.gz.
#    The 14 newest daily copies are kept. The restore drill reads these copies too.
# 2. Off the server (once set up, docs/BACKUP-OFFSITE.md): the same copy, encrypted with the passphrase
#    in /root/.backup-passphrase (AES-256, openssl), uploaded with rclone to Google Drive. Copies older
#    than 15 days are removed there. Nothing unencrypted ever leaves the server.
# 2b. Model files + their sha256 manifest go off the server too (backup-models-offsite.sh); scripts/verify_restore.py
#    checks the database and every file together (docs/BACKUP-OFFSITE.md).
# 3. Deploy copies (release-*/database.sql, ~260 MB each, never removed until now): the dump is
#    deleted from all but the 5 newest releases. Their rollback.json and previous-sha stay.
#
# Writes /root/backups/daily-last.txt: "<ok|failed> <UTC time> local=<file> offsite=<ok|not set up|failed>"
# (+ " cleanup=failed" when old copies could not be listed, or " stopped=exit-N" after an unexpected stop).
# Writing it is best effort: if it cannot be written, a WARNING goes to stderr and the exit code is unchanged.
# Exit 0 = the local copy is good and the off-server copy is ok or not set up yet; non-zero = something failed.
# Reads the live database only (pg_dumpall). Never touches trading.
set -euo pipefail

BACKUP_ROOT=${BACKUP_ROOT:-/root/backups}
LIVE_CONTAINER=${LIVE_CONTAINER:-stml-postgres}
DB_USER=${DB_USER:-swingtrade}
KEEP_DAILY=${KEEP_DAILY:-14}
KEEP_RELEASE_DUMPS=${KEEP_RELEASE_DUMPS:-5}
REMOTE=${BACKUP_REMOTE:-gdrive:swingtrademl-backups}
PASSPHRASE_FILE=${PASSPHRASE_FILE:-/root/.backup-passphrase}
REMOTE_KEEP_AGE=${REMOTE_KEEP_AGE:-15d}

stamp=$(date +%Y%m%d_%H%M)
dir="$BACKUP_ROOT/daily-$stamp"
file="$dir/database.sql.gz"
record="$BACKUP_ROOT/daily-last.txt"
mkdir -p "$dir"
recorded=0
# Best effort (#362): a status record that cannot be written is reported on stderr and never changes
# the run's result or exit code (the nightly workflow alerts on the exit code).
write_record() {
  if ! { printf '%s\n' "$1" >"$record"; } 2>/dev/null; then
    echo "WARNING: could not write the status record $record (the backup result above stands): $1" >&2
  fi
}
note() {
  recorded=1
  write_record "$1 $(date -u +%Y-%m-%dT%H:%M:%SZ) local=$file offsite=$2${3:+ $3}"
}
# Any exit that did not write the status record (a command failing under set -e) still leaves one,
# so a stopped run is never mistaken for "no news", and keeps the exit code that stopped it (#362).
trap 'rc=$?; [ "$recorded" = 1 ] || write_record "failed $(date -u +%Y-%m-%dT%H:%M:%SZ) local=$file offsite=unknown stopped=exit-$rc"; exit "$rc"' EXIT

echo "Free disk before: $(df -h / | awk 'NR==2 {print $4}')"
if ! docker exec "$LIVE_CONTAINER" pg_dumpall -U "$DB_USER" | gzip -6 >"$file" \
    || ! gzip -t "$file" || [ "$(stat -c %s "$file")" -lt 1000000 ]; then
  echo "DAILY BACKUP FAILED: the database copy could not be made or is damaged/too small." >&2
  note failed "skipped"
  exit 1
fi
echo "Local copy: $file ($(du -h "$file" | cut -f1))"

# Folders in BACKUP_ROOT matching $1, newest first, one per line ending in "/".
# No match is normal and prints nothing (a new server has no release-* folder before its first
# deploy, #362). A real listing error (e.g. permission denied) makes find, and so this, fail.
newest_first() {
  find "$BACKUP_ROOT" -mindepth 1 -maxdepth 1 -type d -name "$1" -printf '%T@ %p/\n' | sort -rn | cut -d' ' -f2-
}
cleanup=""
if daily_dirs=$(newest_first 'daily-*') && release_dirs=$(newest_first 'release-*'); then
  # Keep the newest KEEP_DAILY daily copies.
  printf '%s\n' "$daily_dirs" | tail -n +"$((KEEP_DAILY + 1))" | xargs -r -d '\n' rm -rf
  # Deploy copies: drop the big dump from all but the newest few releases (rollback info stays).
  printf '%s\n' "$release_dirs" | tail -n +"$((KEEP_RELEASE_DUMPS + 1))" \
    | while read -r old; do [ -z "$old" ] || rm -f "${old}database.sql"; done
else
  cleanup="cleanup=failed"
  echo "BACKUP CLEAN-UP FAILED: could not list $BACKUP_ROOT, so old copies were not removed (the new local copy is fine)." >&2
fi

offsite="not set up"
if command -v rclone >/dev/null 2>&1 && [ -s "$PASSPHRASE_FILE" ] \
    && rclone listremotes 2>/dev/null | grep -qx "${REMOTE%%:*}:"; then
  enc="$dir/database-$stamp.sql.gz.enc"
  if openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -salt -pass "file:$PASSPHRASE_FILE" -in "$file" -out "$enc" \
      && rclone copy "$enc" "$REMOTE" \
      && rclone check --one-way --size-only "$dir" "$REMOTE" --include "$(basename "$enc")"; then
    # Only the nightly database copies expire; models/ and manifests/ (backup-models-offsite.sh) are kept.
    rclone delete "$REMOTE" --min-age "$REMOTE_KEEP_AGE" --exclude "models/**" --exclude "manifests/**" \
      || echo "Note: could not remove old off-server copies."
    offsite=ok
    echo "Off-server copy: $REMOTE/$(basename "$enc")"
    # Model files + their sha256 manifest (same stamp as the database copy). A failure here fails the run.
    # OFF by default (owner decision Q11): runs only when the flag file exists on the droplet, created by the owner
    # after rclone is set up and scripts/verify_restore.py has been tested (docs/BACKUP-OFFSITE.md).
    if [ ! -e "${MODELS_OFFSITE_FLAG:-/root/.backup-models-enabled}" ]; then
      echo "Off-server model copy is switched off (no ${MODELS_OFFSITE_FLAG:-/root/.backup-models-enabled}); see docs/BACKUP-OFFSITE.md."
    elif ! bash "$(dirname "$0")/backup-models-offsite.sh" "$stamp"; then
      offsite=failed
      echo "OFF-SERVER MODEL COPY FAILED: the database copy is fine; see the lines above." >&2
    fi
  else
    offsite=failed
    echo "OFF-SERVER COPY FAILED: the local copy is fine; check rclone and $PASSPHRASE_FILE." >&2
  fi
  rm -f "$enc"
else
  echo "Off-server copy not set up yet (rclone remote '${REMOTE%%:*}' or $PASSPHRASE_FILE missing); see docs/BACKUP-OFFSITE.md."
fi
echo "Free disk after: $(df -h / | awk 'NR==2 {print $4}')"

if [ "$offsite" = failed ] || [ -n "$cleanup" ]; then note failed "$offsite" "$cleanup"; exit 1; fi
note ok "$offsite"
echo "DAILY BACKUP OK (off-server: $offsite)"
