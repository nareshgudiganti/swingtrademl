#!/usr/bin/env bash
# Generate the random staging secrets ON THE SERVER and write them straight into the staging .env.
# Nothing is printed except the key names. Re-running keeps values that already exist (changing
# POSTGRES_PASSWORD after the database was created would lock the app out of its own database);
# pass --force only for a full reset (docs/STAGING-SETUP.md, section 11).
#
#   bash infra/staging/gen-secrets.sh
set -euo pipefail
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=_envfile.sh
source "$here/_envfile.sh"
command -v openssl >/dev/null || { echo "openssl is required." >&2; exit 1; }

force=false
[ "${1:-}" = "--force" ] && force=true
for key in JWT_SECRET_KEY API_KEY POSTGRES_PASSWORD; do
  if [ "$force" = false ] && [ -n "$(env_get "$key")" ]; then
    echo "$key already set; kept."
    continue
  fi
  ENV_SET_VALUE=$(openssl rand -hex 32) # 64 hex characters
  export ENV_SET_VALUE
  env_set "$key"
  unset ENV_SET_VALUE
  echo "$key generated and saved."
done
