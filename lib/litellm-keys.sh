# ─── LiteLLM Key Management ──────────────────────────────────────────
# Sourced by homelab.sh — do not run standalone.
#
# LiteLLM Proxy API uses SHA256 hashes internally. All CRUD operations
# accept the hash as the "key" field. The actual sk-... token is only
# returned on creation and is not retrievable afterwards.

LITELLM_PROXY="${LITELLM_PROXY:-http://127.0.0.1:4000}"
LITELLM_MASTER="${LITELLM_MASTER:-}"
LAN_BASE="http://192.168.4.54:4000/v1"
EXT_BASE="https://llm.choukalos.com/v1"
LITELLM_PUBLIC="${LITELLM_PUBLIC_API_KEY:-5c11ca96def48aa972ce08bea1412429e973236a3a48ba1cac164a2289938429}"

_litellm() {
  local subcmd="${1:-help}"
  case "${subcmd}" in
    help)
      cat <<'HELP'
LiteLLM Key Management
======================

  ./homelab.sh key add <username> [options]
      Create a new API key for a user.

      Options:
        --models m1,m2      Comma-separated model names (default: all models)
                            Available: matrix-coder, matrix-gemma4-moe,
                                       studio-gemma4-4b, embeddings
        --budget N           Max budget in USD (default: unlimited)
        --rpm N              Max requests per minute (default: unlimited)
        --tpm N              Max tokens per minute (default: unlimited)
        --duration D         Key expiry: e.g. 30d, 1h, 1mo (default: never)
        --alias a            Short alias for the key (default: username)

      Examples:
        ./homelab.sh key add simba --models matrix-coder,studio-gemma4-4b --budget 100
        ./homelab.sh key add jessica --tpm 50000
        ./homelab.sh key add dev --alias "dev-laptop"
        ./homelab.sh key add family         # unlimited, all models
        ./homelab.sh key add guest --duration 30d --budget 5

  ./homelab.sh key list
      List all keys with user, models, spend, and status.

  ./homelab.sh key info <key-or-alias-or-username>
      Show full details for a specific key.

  ./homelab.sh key update <key-or-alias-or-username> [options]
      Update an existing key (same options as add).

  ./homelab.sh key delete <key-or-alias-or-username>
      Delete a key.

  ./homelab.sh key block <key-or-alias-or-username>
      Block a key (soft disable — can be unblocked).

  ./homelab.sh key unblock <key-or-alias-or-username>
      Unblock a previously blocked key.
HELP
      ;;

    add)     shift; _key_add "$@" ;;
    list)    shift; _key_list "$@" ;;
    info)    shift; _key_info "$@" ;;
    update)  shift; _key_update "$@" ;;
    delete)  shift; _key_delete "$@" ;;
    block)   shift; _key_block "$@" ;;
    unblock) shift; _key_unblock "$@" ;;
    *)
      echo "Unknown key subcommand: ${subcmd}" >&2
      _litellm help
      exit 1
      ;;
  esac
}

# ── Internal: fetch all keys as JSON array ──
# Builds from /key/list (hashes) + /key/info per hash.
# Returns JSON: [{hash, key_name, user_id, alias, models, spend,
#                 max_budget, rpm_limit, tpm_limit, blocked, expires,
#                 created_at, last_active}, ...]

_key_fetch_all() {
  local list_resp
  list_resp=$(curl -s -H "Authorization: Bearer ${LITELLM_MASTER}" \
    "${LITELLM_PROXY}/key/list")

  local hashes
  hashes=$(echo "${list_resp}" | python3 -c "
import sys, json
data = json.load(sys.stdin)
for k in data.get('keys', []):
    print(k)
" 2>/dev/null)

  if [[ -z "${hashes}" ]]; then
    echo "[]"
    return
  fi

  local all_json="["
  local first=true
  while IFS= read -r hash; do
    local info_resp
    info_resp=$(curl -s -H "Authorization: Bearer ${LITELLM_MASTER}" \
      "${LITELLM_PROXY}/key/info?key=${hash}")

    local entry
    entry=$(echo "${info_resp}" | python3 -c "
import sys, json
data = json.load(sys.stdin)
info = data.get('info', data)
e = {
    'hash': data.get('key', ''),
    'key_name': info.get('key_name', ''),
    'user_id': info.get('user_id', ''),
    'alias': info.get('key_alias') or '',
    'models': info.get('models') or [],
    'spend': info.get('spend', 0) or 0,
    'max_budget': info.get('max_budget'),
    'rpm_limit': info.get('rpm_limit'),
    'tpm_limit': info.get('tpm_limit'),
    'blocked': info.get('blocked'),
    'expires': info.get('expires'),
    'created_at': info.get('created_at'),
    'last_active': info.get('last_active')
}
print(json.dumps(e))
" 2>/dev/null)
    if [[ -n "${entry}" ]]; then
      if [[ "${first}" == "true" ]]; then first=false; else all_json+=","; fi
      all_json+="${entry}"
    fi
  done <<< "${hashes}"
  echo "${all_json}]"
}

# ── Internal: find a hash by user_id, alias, key_name, or partial match ──

_key_find_hash() {
  local identifier="$1"
  local all_json
  all_json=$(_key_fetch_all)

  echo "${all_json}" | python3 -c "
import sys, json
keys = json.load(sys.stdin)
target = sys.argv[1].lower()
# Exact match on user_id, alias, or key_name
for k in keys:
    uid = (k.get('user_id') or '').lower()
    alias = (k.get('alias') or '').lower()
    name = (k.get('key_name') or '').lower()
    if target in (uid, alias, name):
        print(k['hash']); sys.exit(0)
# Partial match
for k in keys:
    uid = (k.get('user_id') or '').lower()
    alias = (k.get('alias') or '').lower()
    name = (k.get('key_name') or '').lower()
    if target in uid or target in alias or target in name:
        print(k['hash']); sys.exit(0)
print('NOT_FOUND')
" "$identifier" 2>/dev/null
}

# ── Internal: get one entry from all_json by hash ──

_key_get_by_hash() {
  local all_json="$1"
  local hash="$2"
  echo "${all_json}" | python3 -c "
import sys, json
keys = json.load(sys.stdin)
target = sys.argv[1]
k = next((x for x in keys if x['hash'] == target), None)
print(json.dumps(k) if k else 'NOT_FOUND')
" "$hash" 2>/dev/null
}

# ── key add ──

_key_add() {
  local username="${1:?Usage: ./homelab.sh key add <username> [options]}"
  shift
  local models="" budget="" rpm="" tpm="" duration="" alias="${username}"

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --models)   models="$2";    shift 2 ;;
      --budget)   budget="$2";    shift 2 ;;
      --rpm)      rpm="$2";      shift 2 ;;
      --tpm)      tpm="$2";      shift 2 ;;
      --duration) duration="$2";  shift 2 ;;
      --alias)    alias="$2";     shift 2 ;;
      *)          echo "Unknown option: $1" >&2; exit 1 ;;
    esac
  done

  local payload
  payload=$(python3 -c "
import json, sys
d = {'user_id': sys.argv[1], 'key_alias': sys.argv[2]}
models, budget, rpm, tpm, duration = sys.argv[3:8]
if models:   d['models'] = models.split(',')
if budget:   d['max_budget'] = float(budget)
if rpm:      d['rpm_limit'] = int(rpm)
if tpm:      d['tpm_limit'] = int(tpm)
if duration: d['duration'] = duration
print(json.dumps(d))
" "${username}" "${alias}" "${models}" "${budget}" "${rpm}" "${tpm}" "${duration}")

  local resp
  resp=$(curl -s -X POST "${LITELLM_PROXY}/key/generate" \
    -H "Authorization: Bearer ${LITELLM_MASTER}" \
    -H "Content-Type: application/json" \
    -d "${payload}")

  local key
  key=$(echo "${resp}" | python3 -c "import sys,json; print(json.load(sys.stdin).get('key',''))" 2>/dev/null)

  if [[ -z "${key}" || "${key}" == "null" ]]; then
    echo "❌ Failed to create key. Response: ${resp}" >&2
    exit 1
  fi

  # Print copy-paste block for the user
  echo ""
  echo "✅ Key created for user: ${username}"
  echo ""
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "  🔑  Share this with ${username}:"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo ""
  echo "  API Key:      ${key}"
  echo ""
  echo "  ┌─ From inside the house (LAN) ──────────────────────┐"
  echo "  │  Base URL:  ${LAN_BASE}"
  echo "  │  API Key:   ${key}"
  echo "  └─────────────────────────────────────────────────────┘"
  echo ""
  echo "  ┌─ From outside (remote) ────────────────────────────┐"
  echo "  │  Base URL:  ${EXT_BASE}"
  echo "  │  API Key:   ${LITELLM_PUBLIC}"
  echo "  └─────────────────────────────────────────────────────┘"
  echo ""
  echo "  ┌─ For Cursor / Windsurf / IDEs ─────────────────────┐"
  echo "  │  Settings → AI → Custom API:"
  echo "  │    URL:    ${LAN_BASE}"
  echo "  │    Key:    ${key}"
  echo "  │    Model:  matrix-coder"
  echo "  └─────────────────────────────────────────────────────┘"
  echo ""
  echo "  ┌─ Open WebUI (LAN) ─────────────────────────────────┐"
  echo "  │  URL: http://192.168.4.54:3000"
  echo "  │  (Create a user account on first visit)"
  echo "  └─────────────────────────────────────────────────────┘"
  echo ""
  echo "  Models:    ${models:-all (matrix-coder, matrix-gemma4-moe, studio-gemma4-4b, embeddings)}"
  if [[ -n "${budget}" ]]; then
    echo "  Budget:    \$${budget}"
  else
    echo "  Budget:    unlimited (tracked)"
  fi
  [[ -n "${rpm}" ]]  && echo "  RPM Limit: ${rpm}"
  [[ -n "${tpm}" ]]  && echo "  TPM Limit: ${tpm}"
  [[ -n "${duration}" ]] && echo "  Expires:   ${duration} from now"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
}

# ── key list ──

_key_list() {
  local all_json
  all_json=$(_key_fetch_all)

  echo "${all_json}" | python3 -c "
import sys, json
keys = json.load(sys.stdin)
if not keys:
    print('No keys found.'); sys.exit(0)
print(f'{\"User\":<15} {\"Key\":<18} {\"Models\":<40} {\"Spend\":>8} {\"Budget\":>10} {\"Status\":<10} {\"Alias\":<15}')
print('-' * 130)
for k in keys:
    uid = k.get('user_id') or 'N/A'
    name = k.get('key_name', 'N/A')
    models = ', '.join(k.get('models', [])) or 'all'
    if len(models) > 38: models = models[:35] + '...'
    spend = k.get(\"spend\", 0) or 0
    if spend == 0:    spend_str = \"\\u00240.00\"
    elif spend < 0.01: spend_str = f\"\\u0024{spend:.8f}\"
    elif spend < 1:   spend_str = f\"\\u0024{spend:.6f}\"
    elif spend < 100: spend_str = f\"\\u0024{spend:.4f}\"
    else:             spend_str = f\"\\u0024{spend:.2f}\"
    spend = spend_str
    budget = k.get('max_budget')
    budget_str = f'\${budget}' if budget else 'unlimited'
    blocked = 'blocked' if k.get('blocked') else 'active'
    alias = k.get('alias') or ''
    print(f'{uid:<15} {name:<18} {models:<40} {spend:>8} {budget_str:>10} {blocked:<10} {alias:<15}')
" 2>/dev/null || { echo "Failed to parse key list." >&2; exit 1; }
}

# ── key info ──

_key_info() {
  local identifier="${1:?Usage: ./homelab.sh key info <key-or-alias-or-username>}"
  local hash
  hash=$(_key_find_hash "${identifier}")
  if [[ "${hash}" == "NOT_FOUND" || -z "${hash}" ]]; then
    echo "❌ Key/user '${identifier}' not found." >&2
    exit 1
  fi

  local all_json
  all_json=$(_key_fetch_all)
  local entry
  entry=$(_key_get_by_hash "${all_json}" "${hash}")
  if [[ "${entry}" == "NOT_FOUND" ]]; then
    echo "❌ Key lookup failed internally." >&2
    exit 1
  fi

  echo "${entry}" | python3 -c "
import sys, json
k = json.load(sys.stdin)
print(f'User:       {k.get(\"user_id\", \"N/A\")}')
print(f'Alias:      {k.get(\"alias\", \"N/A\")}')
print(f'Key:        {k.get(\"key_name\", \"N/A\")}')
print(f'Models:     {\", \".join(k.get(\"models\", [])) or \"all\"}')
spend = k.get(\"spend\", 0) or 0
if spend == 0:    spend_str = \"\\u00240.00\"
elif spend < 0.01: spend_str = f\"\\u0024{spend:.8f}\"
elif spend < 1:   spend_str = f\"\\u0024{spend:.6f}\"
elif spend < 100: spend_str = f\"\\u0024{spend:.4f}\"
else:             spend_str = f\"\\u0024{spend:.2f}\"
print(f'Spend:      {spend_str}')
budget = k.get(\"max_budget\")
budget_str = \"unlimited\"
if budget is not None:
    budget_str = \"\u0024\" + str(budget)
print(f'Budget:     {budget_str}')
print(f'RPM limit:  {k.get(\"rpm_limit\", \"unlimited\")}')
print(f'TPM limit:  {k.get(\"tpm_limit\", \"unlimited\")}')
print(f'Expires:    {k.get(\"expires\") or \"never\"}')
print(f'Blocked:    {\"yes\" if k.get(\"blocked\") else \"no\"}')
print(f'Created:    {k.get(\"created_at\", \"N/A\")}')
print(f'Last used:  {k.get(\"last_active\", \"N/A\") or \"never\"}')
" 2>/dev/null || { echo "Failed to parse." >&2; exit 1; }
}

# ── key update ──

_key_update() {
  local identifier="${1:?Usage: ./homelab.sh key update <key-or-alias-or-username> [options]}"
  shift
  local hash
  hash=$(_key_find_hash "${identifier}")
  if [[ "${hash}" == "NOT_FOUND" || -z "${hash}" ]]; then
    echo "❌ Key/user '${identifier}' not found." >&2
    exit 1
  fi

  local models="" budget="" rpm="" tpm="" duration=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --models)   models="$2";    shift 2 ;;
      --budget)   budget="$2";    shift 2 ;;
      --rpm)      rpm="$2";      shift 2 ;;
      --tpm)      tpm="$2";      shift 2 ;;
      --duration) duration="$2";  shift 2 ;;
      *)          echo "Unknown option: $1" >&2; exit 1 ;;
    esac
  done

  local payload
  payload=$(python3 -c "
import json, sys
d = {'key': sys.argv[1]}
models, budget, rpm, tpm, duration = sys.argv[2:7]
if models:   d['models'] = models.split(',')
if budget:   d['max_budget'] = float(budget)
if rpm:      d['rpm_limit'] = int(rpm)
if tpm:      d['tpm_limit'] = int(tpm)
if duration: d['duration'] = duration
print(json.dumps(d))
" "${hash}" "${models}" "${budget}" "${rpm}" "${tpm}" "${duration}")

  local resp
  resp=$(curl -s -X POST -H "Authorization: Bearer ${LITELLM_MASTER}" \
    -H "Content-Type: application/json" \
    "${LITELLM_PROXY}/key/update" \
    -d "${payload}")

  local ok
  ok=$(echo "${resp}" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print('ok' if 'key' in d or 'key_name' in d or 'token' in d else 'error')
" 2>/dev/null)

  if [[ "${ok}" == "ok" ]]; then
    echo "✅ Key updated for '${identifier}'"
  else
    echo "❌ Failed to update key. Response: ${resp}" >&2
    exit 1
  fi
}

# ── key delete ──

_key_delete() {
  local identifier="${1:?Usage: ./homelab.sh key delete <key-or-alias-or-username>}"
  local hash
  hash=$(_key_find_hash "${identifier}")
  if [[ "${hash}" == "NOT_FOUND" || -z "${hash}" ]]; then
    echo "❌ Key/user '${identifier}' not found." >&2
    exit 1
  fi

  local payload
  payload=$(python3 -c "import json,sys; print(json.dumps({'keys': [sys.argv[1]]}))" "${hash}")

  local resp
  resp=$(curl -s -X POST -H "Authorization: Bearer ${LITELLM_MASTER}" \
    -H "Content-Type: application/json" \
    "${LITELLM_PROXY}/key/delete" \
    -d "${payload}")

  local ok
  ok=$(echo "${resp}" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print('ok' if d.get('deleted_keys') else 'error')
" 2>/dev/null)

  if [[ "${ok}" == "ok" ]]; then
    echo "✅ Key deleted for '${identifier}'"
  else
    echo "❌ Failed to delete key. Response: ${resp}" >&2
    exit 1
  fi
}

# ── key block ──

_key_block() {
  local identifier="${1:?Usage: ./homelab.sh key block <key-or-alias-or-username>}"
  local hash
  hash=$(_key_find_hash "${identifier}")
  if [[ "${hash}" == "NOT_FOUND" || -z "${hash}" ]]; then
    echo "❌ Key/user '${identifier}' not found." >&2
    exit 1
  fi

  local payload
  payload=$(python3 -c "import json,sys; print(json.dumps({'key': sys.argv[1]}))" "${hash}")

  local resp
  resp=$(curl -s -X POST -H "Authorization: Bearer ${LITELLM_MASTER}" \
    -H "Content-Type: application/json" \
    "${LITELLM_PROXY}/key/block" \
    -d "${payload}")

  local ok
  ok=$(echo "${resp}" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print('ok' if d.get('blocked') or 'key_name' in d else 'error')
" 2>/dev/null)

  if [[ "${ok}" == "ok" ]]; then
    echo "✅ Key blocked for '${identifier}'"
  else
    echo "❌ Failed to block key. Response: ${resp}" >&2
    exit 1
  fi
}

# ── key unblock ──

_key_unblock() {
  local identifier="${1:?Usage: ./homelab.sh key unblock <key-or-alias-or-username>}"
  local hash
  hash=$(_key_find_hash "${identifier}")
  if [[ "${hash}" == "NOT_FOUND" || -z "${hash}" ]]; then
    echo "❌ Key/user '${identifier}' not found." >&2
    exit 1
  fi

  local payload
  payload=$(python3 -c "import json,sys; print(json.dumps({'key': sys.argv[1]}))" "${hash}")

  local resp
  resp=$(curl -s -X POST -H "Authorization: Bearer ${LITELLM_MASTER}" \
    -H "Content-Type: application/json" \
    "${LITELLM_PROXY}/key/unblock" \
    -d "${payload}")

  local ok
  ok=$(echo "${resp}" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print('ok' if 'blocked' in d or 'key_name' in d else 'error')
" 2>/dev/null)

  if [[ "${ok}" == "ok" ]]; then
    echo "✅ Key unblocked for '${identifier}'"
  else
    echo "❌ Failed to unblock key. Response: ${resp}" >&2
    exit 1
  fi
}
