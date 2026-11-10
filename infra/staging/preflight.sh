#!/usr/bin/env bash
# Staging preflight. Refuses (exit 1) unless the staging .env is safe to start.
# Prints key names and ok/FAIL only - never a value.
#
#   bash infra/staging/preflight.sh [path/to/.env] [--allow-pending-third-party]
#
# --allow-pending-third-party: lets RESEND_API_KEY and the three RAZORPAY_* secrets still be empty
# (first start, before Resend DNS / Razorpay are set up). A value that IS filled in is still checked.
set -uo pipefail

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
envfile=""
pending=false
for arg in "$@"; do
  case "$arg" in
    --allow-pending-third-party) pending=true ;;
    *) envfile=$arg ;;
  esac
done
envfile=${envfile:-$here/../../.env}
fails=0
fail() { echo "FAIL  $1"; fails=$((fails + 1)); }
pass() { echo "ok    $1"; }
warn() { echo "warn  $1"; }

[ -f "$envfile" ] || { echo "FAIL  env file not found: $envfile"; exit 1; }

# --- parse KEY=VALUE (last wins; quotes stripped; CR removed) ---
declare -A V
dq='"'
sq="'"
while IFS= read -r line || [ -n "$line" ]; do
  line=${line%$'\r'}
  [[ $line =~ ^[[:space:]]*# ]] && continue
  [[ $line =~ ^([A-Za-z_][A-Za-z0-9_]*)=(.*)$ ]] || continue
  k=${BASH_REMATCH[1]}
  val=${BASH_REMATCH[2]}
  if [ "${#val}" -ge 2 ]; then
    first=${val:0:1}
    last=${val: -1}
    if { [ "$first" = "$dq" ] && [ "$last" = "$dq" ]; } || { [ "$first" = "$sq" ] && [ "$last" = "$sq" ]; }; then
      val=${val:1:${#val}-2}
    fi
  fi
  V[$k]=$val
done < "$envfile"
get() { printf '%s' "${V[$1]:-}"; }

# --- file mode ---
mode=$(stat -c '%a' "$envfile" 2>/dev/null || stat -f '%Lp' "$envfile" 2>/dev/null || echo unknown)
if [ "$mode" = 600 ]; then pass "file mode is 600"; else fail "file mode must be 600 (chmod 600 on the file)"; fi

# --- exact flags ---
expect() {
  if [ "$(get "$1")" = "$2" ]; then pass "$1=$2"; else fail "$1 must be exactly $2"; fi
}
expect ENVIRONMENT staging
expect TRADING_MODE paper
expect ALLOW_LIVE_TRADING false
expect ALLOW_REAL_HOLDINGS_ORDERS false
expect ENABLE_SCHEDULER false
expect BRAIN_ENABLED false
expect TELEGRAM_ENABLED false
expect ALLOW_SIGNUP true
expect REQUIRE_EMAIL_VERIFICATION true
expect EMAIL_PROVIDER resend
expect BILLING_ENABLED true
expect BILLING_PROVIDER razorpay
expect ALLOW_LIVE_BILLING false
expect BILLING_ACCEPT_NEW_CHECKOUTS true

case "$(get TESTING_NO_LIMITS)" in
  ""|false) pass "TESTING_NO_LIMITS is off" ;;
  *) fail "TESTING_NO_LIMITS must be unset" ;;
esac
case "$(get TELEGRAM_SEND_OUTSIDE_PRODUCTION)" in
  ""|false) ;;
  *) fail "TELEGRAM_SEND_OUTSIDE_PRODUCTION must be unset or false" ;;
esac

# --- nothing from production's integrations ---
integ_bad=0
for k in "${!V[@]}"; do
  case "$k" in
    KITE_*|TELEGRAM_BOT_TOKEN|TELEGRAM_CHAT_ID|GOOGLE_CLIENT_ID|GOOGLE_CLIENT_SECRET)
      if [ -n "${V[$k]}" ]; then fail "$k must be empty in staging"; integ_bad=1; fi ;;
  esac
done
[ "$integ_bad" -eq 0 ] && pass "KITE_*, TELEGRAM_*, GOOGLE_* are empty"

# --- placeholders ---
is_placeholder() {
  local v=${1,,}
  [ -z "$v" ] && return 0
  case "$v" in
    change-me|changeme|"<"*|*replace*|*placeholder*|your-*|your_*|xxx*|todo*|test|password|secret) return 0 ;;
  esac
  return 1
}

# --- secrets present, real-looking, long enough ---
third_party="RESEND_API_KEY RAZORPAY_KEY_ID RAZORPAY_KEY_SECRET RAZORPAY_WEBHOOK_SECRET"
for k in JWT_SECRET_KEY API_KEY POSTGRES_PASSWORD $third_party; do
  v=$(get "$k")
  if [ -z "$v" ] && [ "$pending" = true ] && [[ " $third_party " == *" $k "* ]]; then
    warn "$k not set yet (allowed by --allow-pending-third-party)"
    continue
  fi
  if is_placeholder "$v"; then fail "$k is empty or a placeholder"; else pass "$k is set"; fi
done
for k in JWT_SECRET_KEY API_KEY POSTGRES_PASSWORD; do
  v=$(get "$k")
  if [ "${#v}" -ge 32 ]; then pass "$k has at least 32 characters"; else fail "$k must have at least 32 characters"; fi
done
j=$(get JWT_SECRET_KEY); a=$(get API_KEY); p=$(get POSTGRES_PASSWORD)
if [ -n "$j" ] && { [ "$j" = "$a" ] || [ "$j" = "$p" ] || [ "$a" = "$p" ]; }; then
  fail "JWT_SECRET_KEY, API_KEY and POSTGRES_PASSWORD must all differ"
fi

# --- Razorpay must be TEST mode ---
rid=$(get RAZORPAY_KEY_ID)
if [ -n "$rid" ]; then
  if [[ $rid == rzp_test_* ]]; then pass "RAZORPAY_KEY_ID is a test key"; else fail "RAZORPAY_KEY_ID must start with rzp_test_"; fi
fi

# --- links and sender must say staging ---
for k in EMAIL_FROM APP_BASE_URL FRONTEND_URL CORS_ORIGINS; do
  if [[ "$(get "$k")" == *staging* ]]; then pass "$k mentions staging"; else fail "$k must mention staging"; fi
done
if [[ "$(get APP_BASE_URL)" == https://* ]]; then pass "APP_BASE_URL uses https"; else fail "APP_BASE_URL must start with https://"; fi

echo
if [ "$fails" -gt 0 ]; then
  echo "PREFLIGHT FAILED: $fails problem(s). Staging will not start until they are fixed."
  exit 1
fi
echo "PREFLIGHT PASSED."
