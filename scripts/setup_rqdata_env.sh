#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   bash scripts/setup_rqdata_env.sh "<RQDATA_LICENSE_TOKEN>"
# Optional env:
#   RQDATA_HOST (default: rqdatad-pro.ricequant.com)
#   RQDATA_PORT (default: 16011)
#   PERSIST_PROFILE=true to append export to ~/.bash_profile

license_token="${1:-}"
if [ -z "$license_token" ]; then
  echo "Usage: bash scripts/setup_rqdata_env.sh \"<RQDATA_LICENSE_TOKEN>\""
  exit 1
fi

host="${RQDATA_HOST:-rqdatad-pro.ricequant.com}"
port="${RQDATA_PORT:-16011}"
uri="rqdata://license:${license_token}@${host}:${port}"

export RQDATAC2_CONF="$uri"
echo "RQDATAC2_CONF exported for current shell"

if [ "${PERSIST_PROFILE:-false}" = "true" ]; then
  echo "export RQDATAC2_CONF='${uri}'" >> ~/.bash_profile
  echo "Appended to ~/.bash_profile"
fi

cat <<MSG
Next steps:
1) Put these into .env (without exposing token in git):
   RQDATA_AUTH_MODE=uri
   RQDATA_URI=${uri}
2) Run smoke test:
   uv run python scripts/rqdata_smoke_test.py
MSG
