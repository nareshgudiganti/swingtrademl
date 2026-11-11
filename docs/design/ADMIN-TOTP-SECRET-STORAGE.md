# Admin two-step sign-in: how the authenticator secret is stored (FOR OWNER REVIEW)

Status: **proposal only.** Nothing here is built, and admin two-step sign-in is not enabled in any
environment. Read this before it is switched on in staging.

## Today (what the code does now)

| Item | Stored as | Where |
|---|---|---|
| Authenticator secret (the base32 seed behind the 6-digit code) | **Plain text**, `admin_mfa.secret`, varchar(64) | `db/models/admin_mfa.py` |
| Recovery codes (10, single use) | SHA-256 of the code, one row each, `used_at` when spent | `admin_recovery_codes` |
| 15-minute "step-up" token | Signed token. Key = SHA-256 of `JWT_SECRET_KEY` + `:admin-mfa`. Not stored. | `services/admin_mfa.py` |
| Wrong-code lock, replay guard | `failed_count`, `locked_until`, `last_step` | `admin_mfa` |

Why the secret cannot simply be hashed: the server must recompute the 6-digit code from it on every
check, so it has to be recoverable. That is the whole reason for this note.

## What an attacker could do with each kind of leak

| Leak | Today | Impact |
|---|---|---|
| Database dump or backup copy | The secret is readable | The attacker can generate valid admin codes, but still needs the owner's password or session to reach an admin route. The second step is gone; the first still holds. |
| Database dump **and** `JWT_SECRET_KEY` | Both readable | They can mint step-up tokens directly and sign a session. Full admin. |
| `JWT_SECRET_KEY` alone | Step-up tokens can be forged | The same key also signs sessions, so one leaked key forges both steps. |
| Public repository | Nothing secret is in the repo | The repo is PUBLIC, so assume attackers read all code. Security must rest on keys held only in server settings, never on code secrecy. |
| Offsite backups (`docs/BACKUP-OFFSITE.md`) | Contain the plain secret | Anyone who can read a backup can read the seed. Backups often outlive the server and have wider access. |
| Application logs | The setup call returns the secret once | Make sure request and response bodies are never logged. |

Recovery codes are a plain, unsalted SHA-256 of a random code. That is fine only if the codes are long
and random. Worth confirming their length in review (not changed here); if short, add a per-code salt.

## Options

### A. Leave it in plain text (today)
- No work. Risk: a database or backup leak removes the second step entirely.
- Acceptable only for a private test phase. **Not recommended before real customers, or staging with real email.**

### B. Encrypt the secret at rest with an application key (recommended)
- A new setting `ADMIN_MFA_ENCRYPTION_KEY`, held only in the server's environment (the staging and
  production secret files), never in the repo and never in the database.
- Authenticated encryption (AES-256-GCM via the `cryptography` package, or Fernet, which wraps the same
  thing). Store `version:nonce:ciphertext` in the existing column, widened from 64 to 255 characters
  (one small migration).
- A key-version prefix (`v1:`) lets keys rotate: new writes use the newest key, reads accept any key still listed.
- Benefit: a database dump or backup alone no longer yields working codes. The attacker also needs the server's key.
- Cost: one more secret to manage, back up separately from the database, and rotate. Lose the key and the
  admin must re-enrol with a recovery code.

### C. Envelope encryption with a managed key service (cloud KMS)
- A KMS holds the master key; the app asks it to unwrap a data key.
- Stronger key custody and audit, but it adds a service and a bill, and our architecture rule is no new
  infrastructure. Not recommended for one admin on one droplet.

### D. Store no seed: use a hardware key (WebAuthn / passkey)
- No shared secret exists to leak. Best security, bigger build, needs a device. A good later step, not a
  replacement for a decision on A to C now.

### Also do, whichever option is chosen
1. Derive the step-up signing key from its **own** setting (`ADMIN_MFA_STEP_UP_KEY`) instead of from
   `JWT_SECRET_KEY`, so one leaked key does not forge both the session and the second step.
2. Keep recovery codes hashed; confirm each has at least 64 bits of randomness, or add a salt.
3. Never log the setup response, and send it with `Cache-Control: no-store`.
4. "Sign out everywhere" already invalidates step-up tokens (token version); keep that.

## Recommendation

**Option B**, plus items 1 to 3, before admin two-step sign-in is switched on anywhere real. It is a small
change: one setting, one widened column, one migration, one read/write helper, tests. Option D can follow later.

## Migration path for the existing plain-text secrets

Admin two-step sign-in is not on anywhere, so there are probably **zero** enrolled admins today. Confirm with
`SELECT count(*) FROM admin_mfa` on each environment. If zero:

1. Ship the encrypted write path. The migration only widens the column.
2. Treat any row without a `v1:` prefix as "needs re-setup": the admin runs setup again and the old seed is overwritten.

If an admin is already enrolled:

3. A one-off job encrypts rows in place inside a transaction, after a backup, then checks each row decrypts to the same seed.
4. After rollout, make a plain-text row an error rather than a fallback, so a silent downgrade cannot happen.

## What staging needs

- `ADMIN_MFA_ENCRYPTION_KEY` and `ADMIN_MFA_STEP_UP_KEY`: generated by `infra/staging/gen-secrets.sh`
  (to be extended), saved with `set-secret.sh`, never pasted in chat.
- Staging keys differ from production keys. A staging database copy must never open with production keys, nor the reverse.
- `ADMIN_MFA_ENFORCED=false` until the owner has enrolled and saved the recovery codes. The owner turns it on only after a rehearsal.
- A rehearsal: enrol, sign out, sign back in with a code, use a recovery code, and a lose-the-key drill.

## Rollback

- Turning `ADMIN_MFA_ENFORCED` off restores today's behaviour for the older admin routes at once. It is a setting change only.
- Encryption rollback: keep the old key listed for reads. If the key was lost, re-enrol. The migration only
  widens a column, so its downgrade is safe.
- Locked out: someone with database access deletes the admin's `admin_mfa` row and the admin sets up again.
  That is why database access must stay restricted.

## Decisions needed from the owner

1. Approve option B, or choose another.
2. Approve a separate key for the step-up token.
3. Confirm no admin is enrolled anywhere today (so we re-enrol rather than convert).
4. Who holds the offline copy of the encryption key, and where.
