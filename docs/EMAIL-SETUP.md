# Email setup (Resend)

TradeMind sends two kinds of email: "confirm your email" and "reset your password". Until you do the steps
below nothing is sent: the default `EMAIL_PROVIDER=log` only records messages in memory.

## What you do

1. **Create a Resend account** at resend.com.
2. **Add and verify your sending domain** in Resend (Domains > Add Domain). Resend then shows you the DNS
   records to add at your domain registrar: an SPF record and DKIM record(s) (TXT/CNAME as Resend lists them),
   and optionally a DMARC TXT record. Copy them exactly as the Resend dashboard shows them; the values are
   specific to your account and are not in this repo. Wait until the domain shows "Verified".
3. **Create an API key** (API Keys > Create) with **Sending access** only, limited to that domain.
4. **Set these four values in the deployment `.env`** on the server (never in the repo, never in chat):
   - `EMAIL_PROVIDER=resend`
   - `RESEND_API_KEY=<the key from step 3>`
   - `EMAIL_FROM=TradeMind <no-reply@your-verified-domain>`
   - `APP_BASE_URL=https://swingtrademl.com` (used to build the links in the emails; no trailing slash needed)
5. Restart the API container so it picks up the new settings.

Leave `REQUIRE_EMAIL_VERIFICATION=false` and `ALLOW_SIGNUP=false` until the private test below passes.
With `REQUIRE_EMAIL_VERIFICATION=false`, every existing member signs in exactly as before. Turn it on only
when you want unconfirmed email/password accounts refused at sign-in (the owner and Google accounts are never
blocked by it).

If `EMAIL_PROVIDER=resend` but the key or from-address is missing, the app sends nothing and logs a warning;
it does not crash.

## Private test plan (your own address only)

1. With the settings above in place, ask for a password reset for your own account's email on the sign-in
   page (or, as owner, use the "send reset" admin action for your own account).
2. Check your inbox (and spam) for "Reset your TradeMind password". Open the link, choose a new password of
   15+ characters, sign in with it. Confirm the old password no longer works and other signed-in devices were
   signed out.
3. Open the same link again: it should say the link is no longer valid (single use). Links expire after 1 hour
   (reset) or 24 hours (confirm email).
4. Ask for a reset for an email that has no account: the page must give the same answer and nothing is sent.
5. Sign-up gives the SAME answer whether or not the email is already registered ("If this email can be used, we
   have sent you a message with the next steps.") and never returns a login token. A new address gets the
   confirmation email; an existing one gets a private "someone tried to sign up" notice (at most one per hour)
   and nothing about the account changes. The person signs in after confirming.
6. To test sign-up and confirmation, set `ALLOW_SIGNUP=true` temporarily in a non-production environment (or
   briefly in production), register with your own second address, confirm the email, then set it back to false.

Do not send test emails to anyone else's address.

## What to check in Resend's dashboard

- **Domains**: status "Verified" for SPF and DKIM.
- **Emails** (log): each test shows as Delivered (not Bounced or Complained). Click a message to see the
  recipient and subject.
- **API Keys**: the key is "Sending access" only; delete and re-create it if it is ever exposed.
- **Usage**: stay within the free-plan daily and monthly limits.
