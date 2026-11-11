# Admin route audit: which routes need the two-step code

Setting: `ADMIN_MFA_ENFORCED` (default **false**, so nothing changes until the owner turns it on).
When on, a gated route needs a signed-in owner-role person who has set up two-step sign-in and holds a
live `X-Admin-Mfa` token. The shared API key is refused (no person is behind it). A test fails if a new
`/admin` write route is added without the gate (`test_every_admin_write_route_is_gated_or_listed`).

| Route | Gated | Why |
|---|---|---|
| `PUT /admin/switch` | Yes | Turns plan gating on or off for every customer. |
| `PUT /admin/plans/{key}` | Yes | Edits what Free and Pro may do. |
| `GET /admin/users` | Yes | Lists every user's email and plan. Personal data. |
| `PUT /admin/users/{id}/plan` | Yes | Changes a person's plan. |
| `GET /admin/users/{id}/grants` | Yes | Grant reasons are free text about a person. |
| `POST /admin/users/{id}/grants` | Yes | Gives free Pro. |
| `DELETE /admin/users/{id}/grants/{grant_id}` | Yes | Removes a grant. |
| `POST /admin/users/{id}/send-reset` | Yes | Sends a password-reset email to any account. |
| `POST /admin/invites/{id}/approve`, `/new-code`, `/reject` | Yes | Decides who may join; the first two return a sign-up code. |
| `POST /admin/service-keys`, `/{id}/rotate`, `/{id}/revoke` | Yes | Creates, replaces or kills machine keys. |
| `GET /admin/switch`, `/features`, `/plans` | No | Read-only settings, no personal data. Owner sign-in is still required. |
| `GET /admin/invites` | No | Read-only list for the Invites screen. Decisions on it are gated. Revisit if the list gains more personal data. |
| `GET /admin/service-keys` | No | Shows key prefixes and scopes only, never a key. |
| `GET /admin/jobs`, `/admin/server-health`, `/admin/release-switches` | No | Read-only operational views. |
| `/admin/mfa/*` | Own checks | Setup and verify are the two-step flow itself. Replacing an active setup needs a live token. |
| `/admin/console/*` | Own checks | Already needs the token (from the admin users PR). |

The screens do not change. When a gated call is refused, the app asks for the two-step code (or walks the
admin through setup), then repeats the call.
