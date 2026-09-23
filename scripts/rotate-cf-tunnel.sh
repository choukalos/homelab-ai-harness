#!/usr/bin/bash
# Rotate the Cloudflare tunnel token.
# CF_ACCOUNT_ID / CF_TUNNEL_ID come from homelab/.env (gitignored, 600).
# CF_API_TOKEN comes from the environment — it is intentionally NOT stored
# in .env (2026-09-23), so the live token never touches disk:
#   CF_API_TOKEN='your-token' ./scripts/rotate-cf-tunnel.sh
# (A CF_API_TOKEN line in .env still works as a fallback, but is not
# recommended.)
set -euo pipefail

ENV_FILE="${ENV_FILE:-/home/chuck/homelab/.env}"
if [ ! -f "$ENV_FILE" ]; then
    echo "ERROR: $ENV_FILE not found" >&2
    exit 1
fi

# Load the non-secret CF_* vars from .env
eval "$(grep -E '^(CF_ACCOUNT_ID|CF_TUNNEL_ID)=' "$ENV_FILE")"

for v in CF_ACCOUNT_ID CF_TUNNEL_ID; do
    if [ -z "${!v:-}" ]; then
        echo "ERROR: $v not set in $ENV_FILE" >&2
        exit 1
    fi
done

# Token: environment first, .env as legacy fallback
if [ -z "${CF_API_TOKEN:-}" ]; then
    eval "$(grep -E '^CF_API_TOKEN=' "$ENV_FILE" || true)"
fi
if [ -z "${CF_API_TOKEN:-}" ]; then
    echo "ERROR: CF_API_TOKEN not set. Export it first, e.g.:" >&2
    echo "  CF_API_TOKEN='your-token' $0" >&2
    exit 1
fi

# need to copy/paste the result manually to see the output; look at result field for token.
curl -sS -w "\nHTTP_STATUS:%{http_code}\n" \
    -H "Authorization: Bearer $CF_API_TOKEN" \
    "https://api.cloudflare.com/client/v4/accounts/$CF_ACCOUNT_ID/cfd_tunnel/$CF_TUNNEL_ID/token"