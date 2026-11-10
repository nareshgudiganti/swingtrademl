# Staging: a safe second copy of TradeMind for testing sign-up, email and billing

Written for the owner. Plain English, numbered, copy-paste. Every step says WHO does it:

- **OWNER** - only you can do it (your accounts, your money, your DNS, your IP).
- **CLAUDE-CAN-DO-LATER** - Claude can do it in a later session once you have done the OWNER steps and said go.

Nothing in this file has been run yet. No server exists, nothing was deployed, nothing was contacted.

## Golden rules

1. **Staging shares nothing with production.** Own server, own database, own secrets, own web address.
2. **You never paste a secret into chat.** Secrets are typed into a hidden prompt on the staging server
   (`infra/staging/set-secret.sh`) or generated on the server and never shown (`infra/staging/gen-secrets.sh`).
3. **No production member in staging.** Do not invite, copy or type any real member's or customer's
   email or data into staging. Only synthetic accounts, plus `+tag` aliases of your own address.
4. **No live money, no broker, no Telegram.** Staging runs paper mode, Razorpay TEST mode, and has no
   Kite or Telegram settings at all. `infra/staging/preflight.sh` refuses to start otherwise.

---

## 1. What exists today (checked in the repo)

**There is no isolated staging environment yet.** What exists:

| Thing | Where | What it is |
|---|---|---|
| `ENVIRONMENT` setting accepts `staging` | `backend/src/swing_trade_ml/core/config.py` line 35 (`Literal["local","staging","production"]`) | Only a label. It changes log format (`core/logging.py`) and Telegram is production-only (`TELEGRAM_SEND_OUTSIDE_PRODUCTION`). The strict secret check runs for `production` only (`_production_secrets`). |
| `.env.example` | line 16: "local \| staging \| production" | A comment, no staging values. |
| A planned "staging copy" | `docs/superpowers/specs/2026-09-29-*-blueprint*.html`, `docs/superpowers/research/2026-09-13-digitalocean-migration-plan.md` line 291 | Plans and mentions only. Nothing built. |
| `docker-compose.yml` | repo root | Local laptop stack (project `swing-trade-ml`, ports 5433/6379/8000/5173 published on all interfaces). Not a staging file. |
| `docker-compose.prod.yml` | repo root | Production override. |
| `.github/workflows/deploy.yml` | | Deploys **production** on every push to `main`. No staging job. |
| `infra/deploy/release.sh`, `smoke.py`, `verify.py` | | Production only (`/root/app`, `swingtrademl.com`, container names `stml-*`). |

What did **not** exist before this change: a second database, second secrets, a second host, a
staging deploy path, a staging compose file, any staging preflight. This change adds them (files in
section 17). Docs `docs/EMAIL-SETUP.md` and `docs/BILLING-SANDBOX.md` are not on this base; they live on
other branches (email, `change/billing-razorpay-sandbox`).

---

## 2. Recommended topology: one small separate droplet

**Recommendation:** a separate DigitalOcean droplet, 2 GB RAM, running the same Docker setup as
production but with `docker-compose.staging.yml` (no worker, no brain, no scheduler), behind its own
host nginx at `https://staging.swingtrademl.com`.

Why not the production droplet: it has only 4 GB and has already run out of memory (October 2026).
A second stack there would make production's out-of-memory problem worse, and "nothing shared"
would be a promise rather than a fact.

| | **Small separate droplet (recommended)** | Locally on your PC behind a tunnel | Same host as production |
|---|---|---|---|
| Cost | about USD 12-18 per month for 2 GB (confirm current price on DigitalOcean); delete it when not needed | free, but a tunnel with a stable address may cost | free, but see risk |
| Razorpay webhook reachable | Yes, a normal https address, always up | Only while your PC and tunnel are on; address may change; flaky | Yes |
| Resend links / DNS | `staging.swingtrademl.com` works the same as a real site | Needs a tunnel address registered in DNS | Yes |
| Realism (same OS, Docker, nginx, TLS) | High: same recipe as production | Low: Windows, no real nginx/TLS | High |
| Isolation from production | Complete (different machine) | Complete | Weak: same disk, memory, Docker daemon |
| Out-of-memory risk to production | None | None | Real |
| Effort | Highest first time (about 1-2 hours) | Low | Medium |

The 2 GB size works because staging runs only postgres, redis, api and the static frontend (no worker,
no brain, no model training). If a build runs out of memory, add 1 GB swap (step 5.4) or build on a
bigger droplet temporarily.

---

## 3. Create the droplet and firewall (OWNER)

1. **OWNER** DigitalOcean, Create, Droplet. Ubuntu 24.04 LTS, Basic, 2 GB RAM, a region near you,
   authentication = SSH key (a **new** key just for staging, not production's). Name it `trademind-staging`.
2. **OWNER** Create a Cloud Firewall named `trademind-staging-fw` and attach it to that droplet:
   - Inbound: SSH (TCP 22) from **your IP only**; HTTP (TCP 80) from all; HTTPS (TCP 443) from all.
   - Nothing else inbound. Never open 5432 (Postgres), 6379 (Redis), 8100 or 8180.
   - (Find your IP by searching "what is my IP". If your IP changes, update the rule.)
3. Why this is enough: in `docker-compose.staging.yml` Postgres and Redis publish **no** host port at all,
   and the API and web containers publish only on `127.0.0.1` (8100 and 8180). Docker bypasses the
   Ubuntu firewall (`ufw`), which is how production's database was once exposed - so the DigitalOcean
   firewall plus loopback-only ports are both required.

---

## 4. DNS (OWNER)

Your DNS provider is not known, so these steps are provider-neutral. Wherever `swingtrademl.com` DNS is
managed, add:

| Type | Name / Host | Value | TTL |
|---|---|---|---|
| A | `staging` (some providers want `staging.swingtrademl.com`) | the staging droplet's public IPv4 (from the DigitalOcean page) | 300 seconds while setting up, later 3600 |

Do not touch the existing records for `swingtrademl.com` or `www`.

Check, from any machine: `nslookup staging.swingtrademl.com` shows the staging IP. (Can take minutes.)

The email records are in section 7, after Resend shows you the exact values.

---

## 5. Prepare the server (OWNER types, CLAUDE-CAN-DO-LATER can drive over SSH if you grant access)

SSH in: `ssh root@staging.swingtrademl.com` (or the IP).

```bash
# 5.1 Updates and tools
apt-get update && apt-get -y upgrade
apt-get -y install git nginx certbot python3-certbot-nginx openssl curl ca-certificates
# 5.2 Docker (official convenience script)
curl -fsSL https://get.docker.com | sh
docker compose version        # must be v2.24 or newer (the compose files use !reset / !override)
# 5.3 The code (the repo is public, so no key is needed to read it)
git clone https://github.com/nareshgudiganti/swingtrademl.git /root/app-staging
cd /root/app-staging && git checkout main      # or the branch you want to test
# 5.4 Swap, so a build cannot run the 2 GB droplet out of memory
fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab
```

The folder name `/root/app-staging` matters: the scripts check it.

---

## 6. Secrets: the full list and where each one lives

**Rule:** staging secrets exist in exactly one place: `/root/app-staging/.env` on the staging server,
mode 600 (readable by root only). If a deploy workflow is used (section 12), only the SSH-access
secrets live in the GitHub Environment named `staging`, never the app secrets. Nothing goes in the
repo, in chat, in screenshots, or in `docker-compose` files.

Start the file (on the server):

```bash
cd /root/app-staging
cp .env.staging.example .env && chmod 600 .env
bash infra/staging/gen-secrets.sh         # writes the three random ones, prints only their names
```

| Secret | How it is created | Who | Where it lives |
|---|---|---|---|
| `JWT_SECRET_KEY` | `gen-secrets.sh` (`openssl rand -hex 32`) | CLAUDE-CAN-DO-LATER or OWNER | server `.env` |
| `API_KEY` | `gen-secrets.sh` | same | server `.env` (must differ from production's) |
| `POSTGRES_PASSWORD` | `gen-secrets.sh` | same | server `.env`; keep it once the database exists |
| `RESEND_API_KEY` | Resend dashboard, API Keys, create a key (section 7) | OWNER | typed with `set-secret.sh` |
| `RAZORPAY_KEY_ID` | Razorpay dashboard in **Test Mode** (starts `rzp_test_`) | OWNER | `set-secret.sh` |
| `RAZORPAY_KEY_SECRET` | same page | OWNER | `set-secret.sh` |
| `RAZORPAY_WEBHOOK_SECRET` | you choose it when creating the test webhook (section 8) | OWNER | `set-secret.sh` |
| plan id (`RAZORPAY_PLAN_ID`) | the test plan's id; **confirm the exact setting name in `docs/BILLING-SANDBOX.md` on branch `change/billing-razorpay-sandbox`** | OWNER | `set-secret.sh` (not secret, but kept with the rest) |
| owner / admin password | you choose, at least 12 characters | OWNER | typed into a hidden prompt when seeding (section 11); stored only as a hash in the staging database |
| test-account password | you choose | OWNER | same hidden prompt |
| basic-auth password | **not used**: access is an IP allowlist (section 9) | - | - |
| Kite / Telegram / Google | **none**. Never created for staging. | - | `set-secret.sh` refuses Kite and Telegram names |

How to type a secret safely (the value never shows on screen, never enters shell history, never goes to chat):

```bash
cd /root/app-staging
bash infra/staging/set-secret.sh RESEND_API_KEY
# prompt: "Value for RESEND_API_KEY (hidden):"  paste, Enter, paste again to confirm
```

Check the file without showing a value: `bash infra/staging/preflight.sh .env --allow-pending-third-party`
(prints key names with ok/FAIL only).

---

## 7. Email: Resend with a staging-only sender (OWNER)

Sender: `TradeMind Staging <no-reply@send.staging.swingtrademl.com>`. Links in emails use
`APP_BASE_URL=https://staging.swingtrademl.com`, so verification and reset links open staging, never
production. The sending subdomain is staging-only, so staging mail can never be mistaken for production
mail and the main domain's reputation is untouched.

1. **OWNER** Resend dashboard, Domains, Add Domain: `send.staging.swingtrademl.com`.
2. Resend now **shows the exact records** to add (normally an SPF TXT, DKIM TXT, and a MX for bounces;
   the exact names and values are Resend's). **OWNER** copies each one exactly into your DNS provider,
   as shown. These values are not written here on purpose: they are specific to your account and must
   not be guessed.
3. **OWNER** Optional DMARC TXT record as Resend suggests (for example a monitor-only policy).
4. **OWNER** In Resend click Verify; wait until the domain shows verified (minutes to hours).
5. **OWNER** Resend, API Keys, create a key limited to sending for this domain. Then on the server:
   `bash infra/staging/set-secret.sh RESEND_API_KEY`.
6. `EMAIL_FROM`, `EMAIL_PROVIDER=resend`, `APP_BASE_URL` and `REQUIRE_EMAIL_VERIFICATION=true` are already
   in `.env.staging.example`. See `docs/EMAIL-SETUP.md` (on the email branch) for the app-side details.

---

## 8. Razorpay: a separate TEST-mode setup (OWNER)

Use Razorpay's **Test Mode** only. Keys start `rzp_test_`. `preflight.sh` refuses a key that does not.
Nothing here can charge a real card. Staging also has `ALLOW_LIVE_BILLING=false`.

1. **OWNER** Razorpay dashboard, switch to **Test Mode**, Settings, API Keys, generate test keys.
   On the server: `bash infra/staging/set-secret.sh RAZORPAY_KEY_ID` and again for `RAZORPAY_KEY_SECRET`.
2. **OWNER** Create **one** test plan (Subscriptions, Plans) for the Pro price you want to test. Put its id
   in the plan setting (name per `docs/BILLING-SANDBOX.md` on branch `change/billing-razorpay-sandbox`).
3. **OWNER** Settings, Webhooks, Add new webhook in Test Mode (a **separate** webhook from any production one):
   - URL: `https://staging.swingtrademl.com/api/v1/billing/webhook`
     (Confirm this path from `docs/BILLING-SANDBOX.md` on branch `change/billing-razorpay-sandbox`;
     it is not in this branch. If the path there differs, change it in Razorpay **and** in
     `infra/staging/nginx-staging.conf.template`.)
   - Secret: choose a long random value yourself, then
     `bash infra/staging/set-secret.sh RAZORPAY_WEBHOOK_SECRET` and paste the same value.
   - Events: tick **the subscription events listed in `docs/BILLING-SANDBOX.md`** on that branch
     (the list is defined there; do not guess it).
4. The webhook path is public on purpose (Razorpay's servers cannot be on your IP allowlist). It is
   protected by Razorpay's signature, which the app checks with the webhook secret.
5. Test cards and the test flow: Razorpay's test-mode documentation; steps for the app are in `docs/BILLING-SANDBOX.md`.

---

## 9. Restricted access and TLS (OWNER types; CLAUDE-CAN-DO-LATER can do it over SSH)

Staging is private: only your IP may open it. Exceptions are the Razorpay webhook path and
`/api/v1/health`. Email-link pages (verify, reset) are part of the web app and stay behind the allowlist,
so open them from an allowed IP (add a tester's IP with another `allow` line if needed).

Why an IP allowlist and not a password prompt: the app sends its own login token in the `Authorization`
header on every API call, which replaces a basic-auth header, so a basic-auth prompt would block the app's own API.

```bash
cd /root/app-staging
MYIP=1.2.3.4        # <- your real public IP; example value, replace it
sed -e "s|__OWNER_IP__|$MYIP|" infra/staging/nginx-staging.conf.template > /etc/nginx/sites-available/staging
ln -s /etc/nginx/sites-available/staging /etc/nginx/sites-enabled/staging
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx
# TLS: needs the A record from section 4 to be live
certbot --nginx -d staging.swingtrademl.com        # answer the questions; choose redirect HTTP to HTTPS
```

Certbot renews automatically (`systemctl list-timers | grep certbot`). Every response carries
`X-Robots-Tag: noindex, nofollow`, so search engines skip it.

---

## 10. First start, preflight, smoke test

```bash
cd /root/app-staging
bash infra/staging/preflight.sh .env --allow-pending-third-party   # first start, before Resend/Razorpay are done
# when everything in sections 7-8 is done, run it WITHOUT the flag; it must pass before every start
docker compose -f docker-compose.yml -f docker-compose.staging.yml config >/dev/null && echo compose-ok
bash infra/staging/release-staging.sh "$(git rev-parse HEAD)"
```

`release-staging.sh` re-runs preflight, builds, migrates the staging database, starts api and web, and
waits for `/api/v1/ready`. It refuses on a host that has production's containers.

Smoke checks (from a machine on the allowlist):

```bash
curl -s https://staging.swingtrademl.com/api/v1/health
curl -s https://staging.swingtrademl.com/api/v1/ready
curl -sI https://staging.swingtrademl.com/ | head -5        # 200 and X-Robots-Tag
# From a phone on mobile data (a different IP): the site must answer 403, but /api/v1/health must answer 200.
```

Note `infra/deploy/smoke.py` is written for production (it also checks the brain stage, which staging
does not run), so use the checks above, or run it knowing the brain-stage line will fail.

Then do one end-to-end pass: sign up with a `+tag` alias (section 11), receive the Resend email, click
the staging link, subscribe with a Razorpay test card, and confirm the webhook arrived.

### 10a. Memory check during the demo (OWNER, 2 minutes)

The staging server has only 2 GB. `docker-compose.staging.yml` caps each container so one runaway
process cannot take the whole server down: postgres 512 MB, redis 128 MB, api 768 MB, frontend 64 MB.
That is 1,472 MB in total, which leaves about 550 MB for Ubuntu, nginx and Docker, plus the swap from
step 5.4 as a safety net. (There is no worker container, no brain and no model training, so these
numbers are not tight for sign-up, email and billing tests. They are estimates, not measurements: check them.)

Run these once after the first start, once during a sign-up and a test payment, and once more at the end:

```bash
docker stats --no-stream      # MEM USAGE / LIMIT per container; any one above 80% of its limit is a warning
free -m                       # "available" should stay above ~300 MB and swap "used" should stay small
```

If `api` is close to 768 MB or a container shows as restarted (`docker ps`), tell Claude before
raising a limit; do not just remove it.

---

## 11. Synthetic accounts, and resetting to a clean state

Accounts made by `infra/staging/seed_synthetic_accounts.py` (runs inside the staging api container,
refuses unless `ENVIRONMENT=staging`; uses the app's own password hashing and user model):

| Username | Email | Role / plan |
|---|---|---|
| `staging-owner` | `<your-address>+stg-owner@<your-domain>` (your own inbox) | owner |
| `free.test` | `free.test@example.test` | member, Free |
| `pro.test` | `pro.test@example.test` | member, Pro (plan set the way the Plans Manager sets it) |
| `member.test` | `member.test@example.test` | member, Free (second ordinary member, for "can A see B's data?" checks) |

`*.example.test` can never receive mail (reserved domain). For tests that need a real email, sign up in
the web app using `+tag` aliases of **your own** address (`you+stg-a@gmail.com`, `you+stg-b@gmail.com`);
they all arrive in your inbox. Never use anyone else's address.

```bash
cd /root/app-staging
read -r -s -p "Owner password: " SEED_OWNER_PASSWORD; echo
read -r -s -p "Test-account password: " SEED_TEST_PASSWORD; echo
read -r -p  "Your own plain address (e.g. you@gmail.com): " SEED_OWNER_EMAIL
export SEED_OWNER_PASSWORD SEED_TEST_PASSWORD SEED_OWNER_EMAIL
docker compose -f docker-compose.yml -f docker-compose.staging.yml exec -T \
  -e SEED_OWNER_PASSWORD -e SEED_TEST_PASSWORD -e SEED_OWNER_EMAIL \
  api python - < infra/staging/seed_synthetic_accounts.py
unset SEED_OWNER_PASSWORD SEED_TEST_PASSWORD
```

Passwords are never printed. Re-running updates the same accounts. On this base there is no
"email verified" field; the email-verification and billing branches add one (the script sets it only if it exists).
When those branches merge, re-check the seed script against them.

**Reset staging to a clean state** (deletes staging data only; production is a different machine):

```bash
cd /root/app-staging
docker compose -f docker-compose.yml -f docker-compose.staging.yml down -v     # -v deletes staging's volumes
bash infra/staging/gen-secrets.sh --force                                        # fresh database password and keys
bash infra/staging/preflight.sh .env
bash infra/staging/release-staging.sh "$(git rev-parse HEAD)"
```

then run the seeding commands again. Because `--force` changes `POSTGRES_PASSWORD`, only use it together with `down -v`.
Razorpay test subscriptions are not removed by this: clean them in the Razorpay Test Mode dashboard.

---

## 12. Manual deploy workflow (optional; OWNER adds the GitHub secrets, CLAUDE-CAN-DO-LATER runs it)

`.github/workflows/deploy-staging.yml` runs **only** when you press Run workflow
(`workflow_dispatch`). It has no push trigger, so it cannot run when `main` changes, and it uses its
own GitHub Environment `staging`, which cannot read production's secrets.

Set-up (OWNER, GitHub, Settings):
1. Environments, New environment `staging`. Optionally restrict it to specific branches.
2. Add environment **secrets**: `STAGING_HOST` (the droplet IP or `staging.swingtrademl.com`), `STAGING_USER`
   (`root`), `STAGING_SSH_KEY` (the private half of the staging-only key; paste it into GitHub's secret
   box, never into chat), and optionally `STAGING_URL` (`https://staging.swingtrademl.com`).
3. Add a repository **variable** `PRODUCTION_HOST` = production's address, so the workflow can refuse
   if `STAGING_HOST` ever equals it. (It also refuses any `swingtrademl.com` name other than
   `staging.swingtrademl.com`.)
4. To deploy: Actions, Deploy to staging, Run workflow, pick the branch in "Use workflow from" (the
   tip of that branch is tested then deployed), leave "Run the full test suite" ticked.

Heads-up: GitHub lists a workflow in the Actions screen only when its file is on the default branch
(`main`). Merging this change to `main` also triggers one normal production deploy, because every push
to `main` does; it only adds files, no runtime code changes. Or deploy by hand with section 10 until then.
For the very first demo prefer the by-hand route (section 10, `release-staging.sh`): it needs no GitHub secrets, no Environment and no dispatch, and a failure is visible on the server straight away. GitHub only allows `workflow_dispatch` for a workflow file that exists on the default branch, so use the workflow after the file is on `main`.

The app secrets (section 6) are **not** in GitHub; they stay in the server `.env`.

---

## 13. The exact flag values staging must have

`preflight.sh` fails if any is different. `docker-compose.staging.yml` also forces the first six on the containers.

| Setting | Value | What it protects |
|---|---|---|
| `ENVIRONMENT` | `staging` | JSON logs, no production-only behaviour such as Telegram; seeding script refuses otherwise |
| `TRADING_MODE` | `paper` | No real trades |
| `ALLOW_LIVE_TRADING` | `false` | Second lock against live trading |
| `ALLOW_REAL_HOLDINGS_ORDERS` | `false` | No real Zerodha buy/sell from My Holdings |
| `ENABLE_SCHEDULER` | `false` | No trading, ingest or Kite jobs; there is also no worker container |
| `BRAIN_ENABLED` | `false` | Brain not run (owner may decide otherwise, section 16) |
| `TELEGRAM_ENABLED` | `false` | Staging never messages your phone |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | empty | Cannot reach production's chat |
| `KITE_API_KEY`, `KITE_API_SECRET`, `KITE_USER_ID`, `KITE_PASSWORD`, `KITE_TOTP_SECRET` | all empty / unset | No broker access of any kind |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | empty | Production's Google login is not reused |
| `TESTING_NO_LIMITS` | unset | Risk limits stay on |
| `ALLOW_SIGNUP` | `true` | Staging only: lets you test sign-up (production keeps it off) |
| `REQUIRE_EMAIL_VERIFICATION` | `true` | Tests the real verify-your-email flow |
| `EMAIL_PROVIDER` | `resend` | Real delivery, from the staging-only sender |
| `EMAIL_FROM` | contains `staging` | Staging mail is recognisable |
| `APP_BASE_URL` (also `FRONTEND_URL`, `CORS_ORIGINS`) | `https://staging.swingtrademl.com` | Email links open staging, never production |
| `BILLING_ENABLED` | `true` | Billing flow is being tested |
| `BILLING_PROVIDER` | `razorpay` | |
| `ALLOW_LIVE_BILLING` | `false` | Live Razorpay is refused |
| `BILLING_ACCEPT_NEW_CHECKOUTS` | `true` | New test checkouts allowed |
| `RAZORPAY_KEY_ID` | starts `rzp_test_` | Cannot charge real cards |
| `JWT_SECRET_KEY`, `API_KEY`, `POSTGRES_PASSWORD` | random, 32+ characters, all different, none shared with production | A production login or key does not work on staging, and vice versa |
| `.env` file mode | `600` | Other users on the server cannot read it |

The billing and email settings are added to the app by other branches; on this base `config.py` does
not define them, so until those branches merge the app ignores them. Preflight checks them anyway so staging is never started with the wrong values.

---

## 14. What must never be copied from production

- **Data:** no database dump, backup, restore, `pg_dump`, export, screenshot of real accounts or holdings.
  Do not restore a production backup into staging (the restore drill uses its own throwaway container and stays that way).
- **Secrets:** not `API_KEY`, `JWT_SECRET_KEY`, `POSTGRES_PASSWORD`, any `KITE_*`, `TELEGRAM_*`, `GOOGLE_*`, `RESEND_API_KEY`,
  the production Razorpay keys or webhook. Staging gets its own, created fresh.
- **Models:** trained models are not needed and are best omitted (staging has no worker and runs no scans).
- **People:** **no production member in staging.** Do not invite or sign up any real member or customer on staging, and do not
  type their email or details. Staging users are the four synthetic accounts and `+tag` aliases of your own address.
- **Servers:** no shared Postgres or Redis, no shared Docker volume, no shared droplet, no shared SSH key.

---

## 15. Teardown and cost

- Stop it but keep data: `docker compose -f docker-compose.yml -f docker-compose.staging.yml down`.
- Delete everything: add `-v` to the line above, then in DigitalOcean destroy the droplet and the firewall.
  Remove the `staging` A record, the Resend domain and its DNS records, the Razorpay Test Mode webhook, the GitHub `staging` environment.
- Cost: the 2 GB droplet is roughly USD 12-18 per month while it exists (check DigitalOcean's current price; it is billed
  while powered off too, so destroy it, or snapshot then destroy, when you pause for weeks). Resend and Razorpay test mode: free tiers/no charge; confirm on their pricing pages.

---

## 16. Decisions left to the owner

1. Droplet size and region (recommended 2 GB, region near you).
2. Who provides DNS (not known), and whether you want TTL 300 or 3600.
3. IP allowlist (recommended, and what is built) versus basic auth (will not work with the app's own API calls as built; would cover only the page shell).
4. Whether testers other than you need access (each needs their IP on the allowlist).
5. Whether staging runs the brain or the scheduler: **recommend no.** It would need a worker container, market data feeds and more memory than 2 GB, and would not add anything to sign-up / email / billing testing.
6. Whether the Razorpay webhook path and event list are as assumed (confirm from the billing branch before step 8).
7. Whether to add the manual deploy workflow (section 12) or deploy by hand.

---

## 17. Files added by this change

`docs/STAGING-SETUP.md` (this file), `docker-compose.staging.yml`, `.env.staging.example`,
`infra/staging/preflight.sh`, `infra/staging/set-secret.sh`, `infra/staging/gen-secrets.sh`, `infra/staging/_envfile.sh`,
`infra/staging/nginx-staging.conf.template`, `infra/staging/release-staging.sh`, `infra/staging/seed_synthetic_accounts.py`,
`.github/workflows/deploy-staging.yml`, `backend/tests/test_staging_preflight.py`, and one line in `.gitignore`
(so `.env.staging.example` can be committed; real `.env*` files stay ignored).
No backend or frontend code was changed. Production files (`deploy.yml`, `release.sh`, `docker-compose.prod.yml`) are untouched.
