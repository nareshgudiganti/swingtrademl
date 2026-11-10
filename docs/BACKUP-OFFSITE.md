# Off-server database copy (Google Drive)

Every night at 23:00 IST GitHub runs `infra/deploy/daily-backup.sh` on the droplet (workflow
"Daily backup"). It always keeps a compressed copy on the server for 14 days. Once the steps
below are done it also **encrypts** that copy and puts it in a Google Drive folder, kept 15 days.
Nothing unencrypted leaves the server. Google never sees the data, only scrambled bytes.

A copy is about 50 MB (compressed and encrypted), so 15 days is under 1 GB of the free 15 GB.

## One-time setup (about 10 minutes, owner)

You need: the droplet console (DigitalOcean panel → Droplet → Console) and your PC.

1. **Install rclone on the droplet** (console):

   ```bash
   curl https://rclone.org/install.sh | sudo bash
   ```

2. **Get a Google Drive login token on your PC** (the droplet has no browser).
   Install rclone on Windows (`winget install Rclone.Rclone`), then in a terminal:

   ```bash
   rclone authorize "drive" "eyJzY29wZSI6ImRyaXZlLmZpbGUifQ"
   ```

   The quoted text means "drive.file" access: rclone can only see files it created itself, not
   the rest of your Drive. A browser opens: sign in with your Google account and allow.
   The terminal then prints a token (a block starting `{"access_token":...`). Copy it all.
   This token is a password: never paste it anywhere except the next step.

3. **Link the droplet to Drive** (console):

   ```bash
   rclone config
   ```

   Answer: `n` (new remote) → name **`gdrive`** → storage **`drive`** → client id/secret: press
   Enter (blank) → scope **`drive.file`** → service account file: Enter → advanced config: `n` →
   auto config: **`n`** → paste the token from step 2 → shared drive: `n` → `y` to keep → `q`.

   Check it works: `rclone mkdir gdrive:swingtrademl-backups && rclone lsd gdrive:`

4. **Make the encryption passphrase** (console):

   ```bash
   openssl rand -base64 32 > /root/.backup-passphrase
   chmod 600 /root/.backup-passphrase
   cat /root/.backup-passphrase
   ```

   **Save the printed passphrase in your password manager now.** If the server is lost, this
   passphrase is the only way to open the Drive copies. Without it they are useless.

5. **Test it**: GitHub → Actions → "Daily backup" → Run workflow. The log should end with
   `DAILY BACKUP OK (off-server: ok)` and a file `database-YYYYmmdd_HHMM.sql.gz.enc` appears in
   the Drive folder `swingtrademl-backups`.

## Getting a copy back (if the server is lost)

On any Linux machine or a new droplet with rclone linked as above (or download the file from
the Drive website):

```bash
rclone copy gdrive:swingtrademl-backups/database-YYYYmmdd_HHMM.sql.gz.enc .
openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -pass file:passphrase.txt \
  -in database-YYYYmmdd_HHMM.sql.gz.enc | gunzip > database.sql
```

`passphrase.txt` holds the passphrase from your password manager. Then restore `database.sql`
exactly as the restore drill does (`infra/deploy/restore-drill.sh`, TimescaleDB pre/post restore).
The drill also accepts the server's own `database.sql.gz` copies directly.

## What gets messaged

- The nightly job fails (no copy, damaged copy, or the Drive upload failed): Telegram, with a link to the run.
- Not set up yet: no message; the log says "not set up".
- `/root/backups/daily-last.txt` on the droplet always shows the last result.

## Model files and the full restore drill

Before this section the Drive held only the database dump. Model files lived on the server (volume
`model_data`, second copy in volume `model_backups`: same disk) and in a zip the owner pulled by hand to a PC
(`scripts/backup-models-from-prod.ps1`). The database stores each model's path, not its sha256, and the
`brain_meta_v*` combiner files have no database row at all.

**What now leaves the server each night** (`infra/deploy/backup-models-offsite.sh`, called by the daily backup,
needs nothing new on the Drive beyond the setup above):

| Drive folder | Content | Kept |
|---|---|---|
| `swingtrademl-backups/database-<stamp>.sql.gz.enc` | database dump (as before) | 15 days |
| `swingtrademl-backups/models/<sha256>.enc` | one encrypted model file, named by its content hash | forever, never overwritten |
| `swingtrademl-backups/manifests/manifest-<stamp>.json.enc` | name, version, status, file, size, sha256 of every model row plus `brain_meta_v*` files | forever |

An unchanged model file is never sent twice (the file name is its hash; the script checks the Drive first).
A file whose hash on the server differs from the manifest is not uploaded and the nightly run fails, so you get
the usual Telegram message.

**Drill (on your PC, needs Docker with the local Postgres container running; it creates and drops a scratch
database `drill_scratch_<time>` and never touches `swing_trade_ml`):**

1. Make a folder, e.g. `drill-set`, and put in it: `database.sql.gz` (decrypted as in "Getting a copy back"),
   `manifest.json` (decrypt `manifests/manifest-<stamp>.json.enc` with the same `openssl enc -d` command), and a
   subfolder `files/` holding each model file under its manifest name: for every entry in the manifest,
   decrypt `models/<sha256>.enc` to `files/<file>`.
2. Run: `python scripts/verify_restore.py --backup-dir drill-set`
3. Read the table. `OVERALL: PASS` means: the database restored with no real errors, every file's sha256 and size
   match the manifest, every `ml_models` row has a file, every file has a row, and status/version/file name equal
   what the manifest recorded. Any FAIL line names the model or file.

Rows whose file was already gone on the server when the backup ran show as `missing_at_source` and make the drill
FAIL on purpose: that is a real hole (local rehearsal 2026-11-03: 216 of 278 rows).

**Still manual or untested:** the nightly upload has not run against a real Drive; `python3` must exist on the
droplet; the weekly PC zip (`backup-models-from-prod.ps1`) is unchanged and still useful as a second route.

**Switched off by default.** The model-file copy and manifest only run if the file `/root/.backup-models-enabled` exists on the droplet. Create it (`touch /root/.backup-models-enabled`) only after rclone is set up and `scripts/verify_restore.py` has passed a recovery test. Remove the file to switch it off again. Until then the nightly backup behaves exactly as before.
