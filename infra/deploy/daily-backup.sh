#!/usr/bin/env bash
# Daily database copy (tracker af4). Run nightly by .github/workflows/daily-backup.yml over the deploy key.
#
# 1. On the server: pg_dumpall, compressed, into /root/backups/daily-YYYYmmdd_HHMM/database.sql.gz.
#    The 14 newest daily copies are kept. The restore drill reads these copies too.
# 2. Off the server (once set up, docs/BACKUP-OFFSITE.md): the same copy, encrypted with the passphrase
#    in /root/.backup-passphrase (AES-256, openssl), uploaded with rclone to Google Drive. Copies older
#    than 15 days are removed there. Nothing unencrypted ever leaves the server.
# 3. Deploy copies (release-*/database.sql, ~260 MB each, never removed until now): the dump is
#    deleted from all but the 5 newest releases. Their rollback.json and previous-sha stay.
#
# Writes /root/backups/daily-last.txt: "<ok|failed> <UTC time> local=<file> offsite=<ok|not set up|failed>".
# Exit 0 = the local copy is good and the off-server copy is ok or not set up yet; 1 = something failed.
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
note() { printf '%s %s local=%s offsite=%s\n' "$1" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$file" "$2" >"$record"; }

echo "Free disk before: $(df -h / | awk 'NR==2 {print $4}')"
if ! docker exec "$LIVE_CONTAINER" pg_dumpall -U "$DB_USER" | gzip -6 >"$file" \
    || ! gzip -t "$file" || [ "$(stat -c %s "$file")" -lt 1000000 ]; then
  echo "DAILY BACKUP FAILED: the database copy could not be made or is damaged/too small." >&2
  note failed "skipped"
  exit 1
fi
echo "Local copy: $file ($(du -h "$file" | cut -f1))"

# Keep the newest KEEP_DAILY daily copies.
ls -1dt "$BACKUP_ROOT"/daily-*/ 2>/dev/null | tail -n +"$((KEEP_DAILY + 1))" | xargs -r rm -rf
# Deploy copies: drop the big dump from all but the newest few releases (rollback info stays).
ls -1dt "$BACKUP_ROOT"/release-*/ 2>/dev/null | tail -n +"$((KEEP_RELEASE_DUMPS + 1))" \
  | while read -r old; do rm -f "${old}database.sql"; done

offsite="not set up"
if command -v rclone >/dev/null 2>&1 && [ -s "$PASSPHRASE_FILE" ] \
    && rclone listremotes 2>/dev/null | grep -qx "${REMOTE%%:*}:"; then
  enc="$dir/database-$stamp.sql.gz.enc"
  if openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -salt -pass "file:$PASSPHRASE_FILE" -in "$file" -out "$enc" \
      && rclone copy "$enc" "$REMOTE" \
      && rclone check --one-way --size-only "$dir" "$REMOTE" --include "$(basename "$enc")"; then
    rclone delete "$REMOTE" --min-age "$REMOTE_KEEP_AGE" || echo "Note: could not remove old off-server copies."
    offsite=ok
    echo "Off-server copy: $REMOTE/$(basename "$enc")"
  else
    offsite=failed
    echo "OFF-SERVER COPY FAILED: the local copy is fine; check rclone and $PASSPHRASE_FILE." >&2
  fi
  rm -f "$enc"
else
  echo "Off-server copy not set up yet (rclone remote '${REMOTE%%:*}' or $PASSPHRASE_FILE missing); see docs/BACKUP-OFFSITE.md."
fi
echo "Free disk after: $(df -h / | awk 'NR==2 {print $4}')"

if [ "$offsite" = failed ]; then note failed "$offsite"; exit 1; fi
note ok "$offsite"
echo "DAILY BACKUP OK (off-server: $offsite)"
