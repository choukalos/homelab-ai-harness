#!/usr/bin/env bash
# litellm-keys.sh — LiteLLM key management helper (auth_todo.md Phase 5.1).
#
# Subcommands:
#   list              List all keys (alias | user_id | token preview).
#   generate <alias> [user_id] [max_budget]
#                     Generate a new key. Prints the raw value ONCE (capture it).
#   delete <token>    Delete a key by raw token (not by alias — the API doesn't
#                     support that).
#
# Env:
#   LITELLM_MASTER_KEY  (required) — the proxy master key.
#   LITELLM_BASE_URL    (default http://192.168.4.54:4000)
#
# Security:
#   - Raw key values are printed to stdout ONLY on `generate` (one-time capture).
#   - `list` shows a masked preview (first 4 + last 4 chars).
#   - No raw values in logs.

set -euo pipefail

LITELLM_BASE_URL="${LITELLM_BASE_URL:-http://192.168.4.54:4000}"
MASTER_KEY="${LITELLM_MASTER_KEY:-}"

if [[ -z "$MASTER_KEY" ]]; then
  # Try to load from .env
  if [[ -f "$(dirname "$0")/../.env" ]]; then
    MASTER_KEY=$(grep -E "^LITELLM_MASTER_KEY=" "$(dirname "$0")/../.env" | head -1 | sed 's/^LITELLM_MASTER_KEY=//' | tr -d '\n')
  fi
fi
if [[ -z "$MASTER_KEY" ]]; then
  echo "ERROR: LITELLM_MASTER_KEY not set (env or .env)." >&2
  exit 1
fi

cmd="${1:-}"
shift || true

case "$cmd" in
  list)
    echo "alias | user_id | token-preview"
    # /key/list returns masked tokens; /key/info with a raw token returns metadata.
    # We can only list masked tokens (the API doesn't return raw values).
    curl -s -H "Authorization: Bearer $MASTER_KEY" "$LITELLM_BASE_URL/key/list" \
      | jq -r '.keys[] | . as $t | "  \($t[0:4])...(\($t[-4:]))"' 2>/dev/null || echo "  (failed)"
    ;;
  generate)
    alias="${1:?Usage: litellm-keys.sh generate <alias> [user_id] [max_budget]}"
    user_id="${2:-$alias}"
    max_budget="${3:-}"
    body="{\"key_alias\":\"$alias\",\"user_id\":\"$user_id\""
    if [[ -n "$max_budget" ]]; then
      body="$body,\"max_budget\":$max_budget"
    fi
    body="$body}"
    resp=$(curl -s -X POST -H "Authorization: Bearer $MASTER_KEY" \
      -H "Content-Type: application/json" -d "$body" "$LITELLM_BASE_URL/key/generate")
    new_key=$(echo "$resp" | jq -r '.key // empty')
    if [[ -z "$new_key" ]]; then
      echo "ERROR: $(echo "$resp" | jq -r '.error | tojson' 2>/dev/null)" >&2
      exit 1
    fi
    # Print the raw value ONCE (capture it now — it's never retrievable again).
    echo "$new_key"
    echo "  (alias=$alias user_id=$user_id) — capture this value; it will not be shown again." >&2
    ;;
  delete)
    token="${1:?Usage: litellm-keys.sh delete <raw-token>}"
    resp=$(curl -s -X DELETE -H "Authorization: Bearer $token" "$LITELLM_BASE_URL/key")
    if echo "$resp" | jq -e '.success' >/dev/null 2>&1; then
      echo "deleted."
    else
      echo "ERROR: $(echo "$resp" | jq -r '.error | tojson' 2>/dev/null)" >&2
      exit 1
    fi
    ;;
  *)
    echo "Usage: litellm-keys.sh {list|generate|delete}" >&2
    exit 1
    ;;
esac