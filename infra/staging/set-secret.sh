#!/usr/bin/env bash
# Set ONE key in the staging .env without the value ever appearing on screen, in shell history
# or in chat. Run it on the staging server:
#
#   bash infra/staging/set-secret.sh RESEND_API_KEY
#
# It asks for the value with a hidden prompt (nothing is echoed), writes it to
# /root/app-staging/.env (mode 600) and prints only "Saved KEY".
set -euo pipefail
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=_envfile.sh
source "$here/_envfile.sh"

key=${1:-}
[ -n "$key" ] || { echo "Usage: bash infra/staging/set-secret.sh KEY_NAME" >&2; exit 2; }

cr=$(printf '\r')
read -r -s -p "Value for $key (hidden): " ENV_SET_VALUE; echo >&2
ENV_SET_VALUE=${ENV_SET_VALUE%"$cr"} # tolerate a pasted Windows line ending
[ -n "$ENV_SET_VALUE" ] || { echo "Empty value; nothing saved." >&2; exit 1; }
if [ "${STAGING_SET_SECRET_NO_CONFIRM:-}" != 1 ]; then
  read -r -s -p "Type it again to confirm: " again; echo >&2
  again=${again%"$cr"}
  [ "$again" = "$ENV_SET_VALUE" ] || { echo "The two entries differ; nothing saved." >&2; exit 1; }
fi
export ENV_SET_VALUE
env_set "$key"
unset ENV_SET_VALUE again
echo "Saved $key in $STAGING_ENV_FILE (mode 600)."
