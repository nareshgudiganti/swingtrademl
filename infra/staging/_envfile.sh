#!/usr/bin/env bash
# Shared helpers for the staging scripts. Sourced, not run.
# Secrets are passed to awk through the environment, never on a command line (visible in `ps`)
# and never echoed.

STAGING_ENV_FILE="${STAGING_ENV_FILE:-/root/app-staging/.env}"

# Keys that must never be written into a staging .env.
env_key_forbidden() {
  case "$1" in KITE_*|TELEGRAM_BOT_TOKEN|TELEGRAM_CHAT_ID) return 0 ;; esac
  return 1
}

# env_set KEY   (the value is read from the variable ENV_SET_VALUE)
# Replaces the KEY line in place or appends it. File stays mode 600.
env_set() {
  local key=$1 tmp
  [[ $key =~ ^[A-Z][A-Z0-9_]*$ ]] || { echo "Not a valid setting name: $key" >&2; return 1; }
  if env_key_forbidden "$key"; then
    echo "Refusing $key: Kite and Telegram settings must never exist in staging." >&2; return 1
  fi
  case "$ENV_SET_VALUE" in *$'\n'*|*$'\r'*) echo "Value contains a line break; refusing." >&2; return 1 ;; esac
  umask 077
  [ -f "$STAGING_ENV_FILE" ] || : > "$STAGING_ENV_FILE"
  tmp=$(mktemp "${STAGING_ENV_FILE}.XXXXXX")
  KEY="$key" awk '
    BEGIN { k = ENVIRON["KEY"]; v = ENVIRON["ENV_SET_VALUE"]; done = 0 }
    index($0, k "=") == 1 { if (!done) { print k "=" v; done = 1 } ; next }
    { print }
    END { if (!done) print k "=" v }
  ' "$STAGING_ENV_FILE" > "$tmp"
  chmod 600 "$tmp"
  mv "$tmp" "$STAGING_ENV_FILE"
}

# env_get KEY -> prints the value (callers must not print it to a terminal log)
env_get() {
  [ -f "$STAGING_ENV_FILE" ] || return 0
  awk -v k="$1" 'index($0, k "=") == 1 { v = substr($0, length(k) + 2) } END { printf "%s", v }' "$STAGING_ENV_FILE"
}
