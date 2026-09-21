#!/usr/bin/bash
# Rotate the Cloudflare tunnel token.
# Credentials live in homelab/.env (gitignored, 600) — never hardcode them here.
set -euo pipefail

ENV_FILE="${ENV_FILE:-/home/chuck/homelab/.env}"
if [ ! -f "$ENV_FILE" ]; then
    echo "ERROR: $ENV_FILE not found" >&2
    exit 1
fi

# Load only the CF_* vars we need
eval "$(grep -E '^(CF_API_TOKEN|CF_ACCOUNT_ID|CF_TUNNEL_ID)=' "$ENV_FILE")"

for v in CF_API_TOKEN CF_ACCOUNT_ID CF_TUNNEL_ID; do
    if [ -z "${!v:-}" ]; then
        echo "ERROR: $v not set in $ENV_FILE" >&2
        exit 1
    fi
done

# need to copy/paste the result manually to see the output; look at result field for token.
curl -sS -w "\nHTTP_STATUS:%{http_code}\n" \
    -H "Authorization: Bearer $CF_API_TOKEN" \
    "https://api.cloudflare.com/client/v4/accounts/$CF_ACCOUNT_ID/cfd_tunnel/$CF_TUNNEL_ID/token"