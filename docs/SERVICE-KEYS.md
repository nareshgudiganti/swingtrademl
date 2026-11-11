# Scoped service keys (replacing the shared API_KEY)

Scripts and GitHub workflows (uptime, daily-check watch, h05 watch, deploy smoke test) used to share one
`API_KEY` that acts as the owner. Each one can now have its own key that can only do what it needs.

## What a key can do

| Scope | Can read | Everything else |
|---|---|---|
| `read_status` | `/status`, `/market/session`, `/risk/limits`, `/brain/stage`, `/brain/daily-checks/latest` | refused (403) |
| `read_all` | any read-only screen outside the private areas below | refused (403) |

No scope can write, place or change anything, see the real Zerodha account, or reach `/admin`, `/auth`,
`/finance`, `/mutual-funds`, `/safety`, `/notifications`, `/brain/alerts`, `/brain/approvals` or `/me`.
Routes that are owner-only by design (for example `/research/h05/report`) also refuse a service key, so the
h05 watch keeps using the shared key until that route is opened to a read scope in a later change.

Only a SHA-256 hash is stored. The key (starts with `stk_`) is shown once, when it is created or rotated.

## Owner steps (sign in as the owner; the shared key cannot create keys)

All calls are under `/api/v1/admin/service-keys` and need your bearer token.

1. Create: `POST` with `{"name": "uptime-watch", "scope": "read_status"}` (optional `expires_in_days`).
   Copy the `key` from the answer into the GitHub secret / script setting. Do not paste it into chat or a file.
2. Switch the workflow or script from `X-API-Key: <shared key>` to `X-API-Key: <new key>`.
3. Check: `GET /admin/service-keys` shows `last_used_at` for each key, so you can see the new key is in use.
4. When every caller uses its own key, set `LEGACY_API_KEY_ENABLED=false` in the server `.env` and redeploy.
   From then on the shared `API_KEY` is refused (401). Turning it back to `true` is the rollback.
5. Rotate: `POST /admin/service-keys/{id}/rotate` returns a new key with the same name and scope. The old key
   keeps working for `overlap_hours` (default 24, `0` = stop at once) so the secret can be swapped without a gap.
6. Revoke: `POST /admin/service-keys/{id}/revoke` stops a key immediately.

Every create, rotate and revoke is written to the audit trail (who, which key id; never the key).

## Safety notes

- Until `LEGACY_API_KEY_ENABLED` is turned off, nothing changes for existing callers or the owner's read-only
  production checks.
- A wrong, expired or revoked `stk_` key is a plain 401. It never falls back to the shared key.
- Migration `servicekeys01` only adds one table. Downgrade (`alembic downgrade billing01`) drops it, which
  invalidates all service keys; the app keeps working with the shared key.
