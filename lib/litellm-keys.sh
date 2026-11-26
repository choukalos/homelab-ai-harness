# ─── LiteLLM Key Management ──────────────────────────────────────────
# Sourced by homelab.sh — do not run standalone.
#
# LiteLLM Proxy API uses SHA256 hashes internally. All CRUD operations
# accept the hash as the "key" field. The actual sk-... token is only
# returned on creation and is not retrievable afterwards.

LITELLM_PROXY="${LITELLM_PROXY:-http://192.168.4.54:4000}"
LITELLM_MASTER="${LITELLM_MASTER_KEY:-${LITELLM_MASTER:-}}"
LAN_BASE="http://192.168.4.54:4000/v1"
EXT_BASE="https://llm.choukalos.com/v1"

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

  ./homelab.sh key add-agent <slug> [options]
      Stand up an agent key end-to-end (Phase 13.5, framework step 6):
      mint with the per-work-type model default, then wire .env in one
      atomic pass — LITELLM_KEY_<SLUG>, MEMORY_USER_KEYS entry,
      KANBAN_MCP_KEY_CAPABILITIES entry (alias-keyed, 13.3) — recreate
      skill-runner + mcp_kanban, run scripts/key-sync-check.sh.

      Options:
        --work-type T      coding (default: matrix-coder) or writing
                           (matrix-copywriter)
        --capability C     kanban capability set: read|control (default)
                           |admin

  ./homelab.sh key list
      List all keys with user, models, spend, and status.

  ./homelab.sh key info <key-or-alias-or-username>
      Show full details for a specific key.

  ./homelab.sh key update <key-or-alias-or-username> [options]
      Update an existing key (same options as add, plus --alias to rename
      the key's alias).

  ./homelab.sh key delete <key-or-alias-or-username>
      Delete a key.

  ./homelab.sh key block <key-or-alias-or-username>
      Block a key (soft disable — can be unblocked).

  ./homelab.sh key unblock <key-or-alias-or-username>
      Unblock a previously blocked key.

  ./homelab.sh key inventory [--json]
      Generate the security_todo.md §1 key inventory table from the live
      proxy (/key/list + /key/info + MCP access groups) so the table is
      never hand-maintained (Phase 13.4). --json for machine output
      (scripts/audit-litellm-keys.sh).

  ./homelab.sh key rotate <key-or-alias-or-username> [options]
      Rotate a key end-to-end (Phase 13.2): back up .env, mint a new key
      with identical attributes (alias, user, models, limits, MCP access
      groups), atomically update the .env var, regenerate derived maps,
      restart affected containers, BLOCK the old key, reload Caddy when
      rotating the family keys, run scripts/key-sync-check.sh.

      Options:
        --env-var VAR        .env variable holding the key (default:
                             LITELLM_KEY_<NAME> for family keys)
        --observe-days N     Observation window before deleting the old
                             blocked key (default: 30)

      Examples:
        ./homelab.sh key rotate chuck
        ./homelab.sh key rotate strategist --env-var LITELLM_KEY_STRATEGIST
HELP
      ;;

    add)     shift; _key_add "$@" ;;
    add-agent) shift; _key_add_agent "$@" ;;
    list)    shift; _key_list "$@" ;;
    info)    shift; _key_info "$@" ;;
    update)  shift; _key_update "$@" ;;
    delete)  shift; _key_delete "$@" ;;
    block)   shift; _key_block "$@" ;;
    unblock) shift; _key_unblock "$@" ;;
    inventory) shift; _key_inventory "$@" ;;
    rotate)  shift; _key_rotate "$@" ;;
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
    'last_active': info.get('last_active'),
    'access_group_ids': info.get('access_group_ids') or []
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
# Exact match on hash, user_id, alias, or key_name
for k in keys:
    h = (k.get('hash') or '').lower()
    uid = (k.get('user_id') or '').lower()
    alias = (k.get('alias') or '').lower()
    name = (k.get('key_name') or '').lower()
    if target in (h, uid, alias, name):
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
  echo "  │  API Key:   ${key}"
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

  local models="" budget="" rpm="" tpm="" duration="" new_alias=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --models)   models="$2";    shift 2 ;;
      --budget)   budget="$2";    shift 2 ;;
      --rpm)      rpm="$2";      shift 2 ;;
      --tpm)      tpm="$2";      shift 2 ;;
      --duration) duration="$2";  shift 2 ;;
      --alias)    new_alias="$2"; shift 2 ;;
      *)          echo "Unknown option: $1" >&2; exit 1 ;;
    esac
  done

  local payload
  payload=$(python3 -c "
import json, sys
d = {'key': sys.argv[1]}
models, budget, rpm, tpm, duration, new_alias = sys.argv[2:8]
if models:   d['models'] = models.split(',')
if budget:   d['max_budget'] = float(budget)
if rpm:      d['rpm_limit'] = int(rpm)
if tpm:      d['tpm_limit'] = int(tpm)
if duration: d['duration'] = duration
if new_alias: d['key_alias'] = new_alias
print(json.dumps(d))
" "${hash}" "${models}" "${budget}" "${rpm}" "${tpm}" "${duration}" "${new_alias}")

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

# ── key inventory (Phase 13.4) ──
# Generates the security_todo.md §1 key inventory table from the live
# proxy so the table is never hand-maintained. Sources:
#   /key/list + /key/info (per hash)  → key attrs incl. access_group_ids
#   /v1/access_group/{id}             → MCP group name + server count
# Columns match the §1 format: | key_alias | user_id | scope | budget | rpm/tpm | notes |
# The master key is not in /key/list — it is appended as a static row.

_key_inventory() {
  local format="table"
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --json) format="json"; shift ;;
      *) echo "Unknown option: $1 (usage: key inventory [--json])" >&2; exit 1 ;;
    esac
  done

  if [[ -z "${LITELLM_MASTER}" ]]; then
    echo "❌ LITELLM_MASTER_KEY not set (source .env first)." >&2
    exit 1
  fi

  local all_json
  all_json=$(_key_fetch_all)

  # Resolve access-group IDs → {name, server count} via the proxy API.
  local groups_json
  groups_json=$(echo "${all_json}" | ALL_JSON="${all_json}" LITELLM_MASTER="${LITELLM_MASTER}" LITELLM_PROXY="${LITELLM_PROXY}" python3 - <<'PY'
import os, json, urllib.request
keys = json.loads(os.environ["ALL_JSON"])
ids = sorted({g for k in keys for g in (k.get("access_group_ids") or [])})
groups = {}
for gid in ids:
    try:
        req = urllib.request.Request(
            os.environ["LITELLM_PROXY"] + "/v1/access_group/" + gid,
            headers={"Authorization": "Bearer " + os.environ["LITELLM_MASTER"]})
        with urllib.request.urlopen(req, timeout=10) as r:
            d = json.load(r)
        groups[gid] = {"name": d.get("access_group_name", ""),
                       "servers": len(d.get("access_mcp_server_ids") or [])}
    except Exception:
        groups[gid] = {"name": gid, "servers": 0}
print(json.dumps(groups))
PY
)

  if [[ "${format}" == "json" ]]; then
    echo "${all_json}" | ALL_JSON="${all_json}" GRP_JSON="${groups_json}" python3 - <<'PY'
import os, json
keys = json.loads(os.environ["ALL_JSON"])
groups = json.loads(os.environ["GRP_JSON"])
for k in keys:
    k["mcp_groups"] = [groups.get(g, {}).get("name", g)
                       for g in (k.get("access_group_ids") or [])]
print(json.dumps(keys, indent=2))
PY
    return
  fi

  echo "${all_json}" | ALL_JSON="${all_json}" GRP_JSON="${groups_json}" python3 - <<'PY'
import os, json, datetime
keys = json.loads(os.environ["ALL_JSON"])
groups = json.loads(os.environ["GRP_JSON"])

def fmt_date(v):
    if not v:
        return "—"
    try:
        return datetime.datetime.fromisoformat(str(v).replace("Z", "")).strftime("%Y-%m-%d")
    except Exception:
        return str(v)[:10]

def scope(k):
    models = k.get("models") or []
    m = ", ".join(models) if models else "all models"
    gids = k.get("access_group_ids") or []
    if gids:
        g = "; ".join(
            "{} ({} MCP)".format(groups.get(g, {}).get("name", g),
                                 groups.get(g, {}).get("servers", "?"))
            for g in gids)
        return m + " + MCP: " + g
    return m + " + MCP: none"

print("| key_alias | user_id | scope | budget | rpm/tpm | notes |")
print("|---|---|---|---|---|---|")
for k in keys:
    alias = k.get("alias") or "*(no alias)*"
    uid = k.get("user_id") or "—"
    rpm, tpm = k.get("rpm_limit"), k.get("tpm_limit")
    rate = "{}/{}".format(rpm, tpm) if (rpm or tpm) else "none"
    budget = k.get("max_budget")
    budget_str = ("$" + format(budget, "g")) if budget is not None else "none"
    notes = ["created {}".format(fmt_date(k.get("created_at")))]
    if k.get("last_active"):
        notes.append("last active {}".format(fmt_date(k.get("last_active"))))
    spend = k.get("spend") or 0
    if spend:
        notes.append("spend ${:.2f}".format(spend))
    if k.get("blocked"):
        notes.append("**BLOCKED**")
    print("| `{}` | {} | {} | {} | {} | {} |".format(
        alias, uid, scope(k), budget_str, rate, "; ".join(notes)))
PY

  # Master key row (not in /key/list — internal only, F6).
  local master_last4="${LITELLM_MASTER: -4}"
  echo "| master (\`sk-...${master_last4}\`) | — | admin, everything | — | — | internal only (F6) |"
}

# ── key rotate (Phase 13.2) ──
# One command: back up .env (Phase 0 pattern) → mint a new key with
# identical attributes (alias, user, models, limits, MCP access groups)
# → atomically update the .env var → regenerate derived maps (the kanban
# capability map while it is still suffix-keyed; 13.3 makes this a no-op)
# → restart affected containers (caddy is RECREATED for the family keys —
# its env is baked at container creation, so a plain reload would keep the
# old keys) → BLOCK the old key → run scripts/key-sync-check.sh.
# The old key is NOT deleted: block → observe N days → key delete <hash>
# (the F5/Phase 3 pattern). Subsumes the Phase 6 quarterly-rotation
# cadence for the family keys.

_key_rotate() {
  local identifier="${1:?Usage: ./homelab.sh key rotate <key-or-alias-or-username> [--env-var VAR] [--observe-days N] [--yes]}"
  shift
  local env_var="" observe_days=30 assume_yes=0
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --env-var)      env_var="$2";      shift 2 ;;
      --observe-days) observe_days="$2"; shift 2 ;;
      --yes)          assume_yes=1;     shift ;;
      *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
  done

  [[ -n "${LITELLM_MASTER}" ]] || { echo "❌ LITELLM_MASTER_KEY not set (source .env first)." >&2; exit 1; }

  local repo_root env_file
  repo_root=$(cd "$(dirname "${BASH_SOURCE[1]}")/.." && pwd)
  env_file="${repo_root}/.env"
  [[ -f "${env_file}" ]] || { echo "❌ .env not found at ${env_file}" >&2; exit 1; }

  # ── Resolve the current key ──
  local hash
  hash=$(_key_find_hash "${identifier}")
  [[ "${hash}" != "NOT_FOUND" && -n "${hash}" ]] || { echo "❌ Key '${identifier}' not found." >&2; exit 1; }

  local all_json entry
  all_json=$(_key_fetch_all)
  entry=$(_key_get_by_hash "${all_json}" "${hash}")
  [[ "${entry}" != "NOT_FOUND" ]] || { echo "❌ Internal key lookup failed." >&2; exit 1; }

  local user_id models_json max_budget rpm_limit tpm_limit groups_json alias key_name
  read -r user_id models_json max_budget rpm_limit tpm_limit groups_json alias key_name <<<"$(echo "${entry}" | python3 -c "
import sys, json
k = json.load(sys.stdin)
print('\t'.join([
    str(k.get('user_id') or ''),
    json.dumps(k.get('models') or []),
    'null' if k.get('max_budget') is None else str(k['max_budget']),
    'null' if k.get('rpm_limit') is None else str(k['rpm_limit']),
    'null' if k.get('tpm_limit') is None else str(k['tpm_limit']),
    json.dumps(k.get('access_group_ids') or []),
    str(k.get('alias') or ''),
    str(k.get('key_name') or ''),
]))
" 2>/dev/null)"

  # ── Resolve the .env var + verify it matches this key ──
  if [[ -z "${env_var}" ]]; then
    env_var="LITELLM_KEY_$(echo "${alias}" | tr '[:lower:]' '[:upper:]' | sed 's/[^A-Z0-9]/_/g')"
  fi
  local current_env_val
  current_env_val=$(grep -E "^${env_var}=" "${env_file}" | head -1 | cut -d= -f2-)
  [[ -n "${current_env_val}" ]] || { echo "❌ ${env_var} not found in .env (pass --env-var VAR)." >&2; exit 1; }

  # key_name is masked (sk-...szvw) — compare the last 4 chars.
  local masked_tail="${key_name: -4}"
  if [[ "${current_env_val: -4}" != "${masked_tail}" ]]; then
    echo "❌ ${env_var} in .env does not match key '${identifier}' (env …${current_env_val: -4} vs key …${masked_tail})." >&2
    echo "  Fix the mismatch first (scripts/key-sync-check.sh), then rotate." >&2
    exit 1
  fi

  # ── Confirm ──
  echo "Rotate plan for '${identifier}' (${key_name}):"
  echo "  .env var:       ${env_var}"
  echo "  user_id:        ${user_id:-—}"
  echo "  models:         ${models_json}"
  echo "  budget/rpm/tpm: ${max_budget}/${rpm_limit}/${tpm_limit}"
  echo "  MCP groups:     ${groups_json}"
  local stamp8
  stamp8=$(date +%Y%m%d-%H%M)
  echo "  old key:        alias → '${alias}-old-${stamp8}' + BLOCKED after consumers restart (observe ${observe_days} days, then delete)"
  if [[ "${assume_yes}" != "1" ]]; then
    local ans
    read -rp "Proceed? [y/N] " ans || { echo "Aborted (no confirmation)."; exit 1; }
    [[ "${ans}" == "y" || "${ans}" == "Y" ]] || { echo "Aborted."; exit 1; }
  fi

  # ── 1. Back up .env (Phase 0 pattern) ──
  local backup_dir="/home/chuck/data/backups" stamp
  stamp=$(date +%F-%H%M%S)
  mkdir -p "${backup_dir}"
  cp "${env_file}" "${backup_dir}/env-${stamp}.bak" && chmod 600 "${backup_dir}/env-${stamp}.bak"
  echo "✅ 1/8 .env backed up → ${backup_dir}/env-${stamp}.bak"

  # ── 2. Free the canonical alias ──
  # LiteLLM enforces unique key aliases across ALL keys (blocked included —
  # _enforce_unique_key_alias, v1.104.0), so the old key must move off the
  # alias before the new key can take it. The old key keeps its identity via
  # the -old-<stamp> alias during the observation window (visible in
  # 'key inventory', easy to delete after).
  local old_alias_new
  if [[ -n "${alias}" ]]; then
    old_alias_new="${alias}-old-${stamp8}"
    local resp_rename
    resp_rename=$(curl -s --max-time 15 -X POST -H "Authorization: Bearer ${LITELLM_MASTER}" \
      -H "Content-Type: application/json" "${LITELLM_PROXY}/key/update" \
      -d "$(python3 -c "import json,sys; print(json.dumps({'key': sys.argv[1], 'key_alias': sys.argv[2]}))" "${hash}" "${old_alias_new}")")
    if ! echo "${resp_rename}" | python3 -c "import sys,json; d=json.load(sys.stdin); exit(0 if ('key' in d or 'key_name' in d or 'token' in d) else 1)" 2>/dev/null; then
      echo "❌ Failed to rename old key's alias to '${old_alias_new}': ${resp_rename}" >&2
      echo "  Nothing else changed — the old key still works under '${alias}'." >&2
      exit 1
    fi
    echo "✅ 2/8 old key alias '${alias}' → '${old_alias_new}' (frees the canonical alias)"
  else
    old_alias_new=""
    echo "✅ 2/8 key has no alias — nothing to free"
  fi

  # ── 2. Mint the new key (identical attrs + MCP groups) ──
  local payload resp new_key
  payload=$(python3 -c "
import json, sys
d = {'key_alias': sys.argv[1]}
uid, models, budget, rpm, tpm, groups = sys.argv[2:8]
if uid: d['user_id'] = uid
models = json.loads(models)
if models: d['models'] = models
if budget != 'null': d['max_budget'] = float(budget)
if rpm != 'null':   d['rpm_limit'] = int(rpm)
if tpm != 'null':   d['tpm_limit'] = int(tpm)
groups = json.loads(groups)
if groups: d['access_group_ids'] = groups
print(json.dumps(d))
" "${alias}" "${user_id}" "${models_json}" "${max_budget}" "${rpm_limit}" "${tpm_limit}" "${groups_json}")

  resp=$(curl -s --max-time 30 -X POST "${LITELLM_PROXY}/key/generate" \
    -H "Authorization: Bearer ${LITELLM_MASTER}" \
    -H "Content-Type: application/json" \
    -d "${payload}")
  new_key=$(echo "${resp}" | python3 -c "import sys,json; print(json.load(sys.stdin).get('key',''))" 2>/dev/null)
  if [[ -z "${new_key}" || "${new_key}" == "null" ]]; then
    echo "❌ Failed to mint new key: ${resp}" >&2
    if [[ -n "${old_alias_new}" ]]; then
      echo "  NOTE: the old key was renamed to '${old_alias_new}' (still active, not blocked)." >&2
      echo "  To restore the original alias: ./homelab.sh key update ${old_alias_new} --alias ${alias}" >&2
      echo "  (or just keep using it — only the alias label changed, the key value is unchanged.)" >&2
    fi
    exit 1
  fi

  # Verify the new key works before touching anything else.
  local probe
  probe=$(curl -s --max-time 15 -o /dev/null -w "%{http_code}" \
    "${LITELLM_PROXY}/v1/models" -H "Authorization: Bearer ${new_key}")
  if [[ "${probe}" != "200" ]]; then
    echo "❌ New key failed the /v1/models probe (HTTP ${probe})." >&2
    echo "  Blocking the dangling new key and aborting — .env is untouched; the old key" >&2
    if [[ -n "${old_alias_new}" ]]; then
      echo "  still works (now aliased '${old_alias_new}'; restore with: key update ${old_alias_new} --alias ${alias})." >&2
    else
      echo "  still works." >&2
    fi
    local new_hash
    new_hash=$(_key_find_hash "${new_key: -4}")
    if [[ "${new_hash}" != "NOT_FOUND" ]]; then
      curl -s -X POST -H "Authorization: Bearer ${LITELLM_MASTER}" \
        -H "Content-Type: application/json" "${LITELLM_PROXY}/key/block" \
        -d "$(python3 -c "import json,sys; print(json.dumps({'key': sys.argv[1]}))" "${new_hash}")" >/dev/null 2>&1
    fi
    exit 1
  fi
  echo "✅ 3/8 new key minted (same user/models/limits/MCP groups, canonical alias) + /v1/models probe 200"

  # ── 3. Update .env atomically (same-dir temp + rename) ──
  local tmp
  tmp=$(mktemp "${env_file}.XXXX")
  sed "s|^${env_var}=.*|${env_var}=${new_key}|" "${env_file}" > "${tmp}"
  if ! grep -q "^${env_var}=${new_key}$" "${tmp}"; then
    echo "❌ .env update failed (line not replaced)." >&2
    rm -f "${tmp}"
    exit 1
  fi
  chmod 600 "${tmp}"
  mv "${tmp}" "${env_file}"
  echo "✅ 4/8 .env updated (${env_var})"

  # ── 4. Regenerate derived maps ──
  # KANBAN_MCP_KEY_CAPABILITIES is suffix-keyed until 13.3 lands; swap the
  # old 8-char suffix for the new one. Alias-keyed entries (post-13.3) are
  # stable across rotation — nothing to do.
  local kanban_var="KANBAN_MCP_KEY_CAPABILITIES"
  if grep -q "^${kanban_var}=" "${env_file}"; then
    local old_suffix="${current_env_val: -8}" new_suffix="${new_key: -8}"
    local kanban_val
    kanban_val=$(grep -E "^${kanban_var}=" "${env_file}" | head -1 | cut -d= -f2-)
    if [[ "${kanban_val}" == *"${old_suffix}"* ]]; then
      ENV_FILE="${env_file}" KANBAN_VAR="${kanban_var}" OLD_S="${old_suffix}" NEW_S="${new_suffix}" python3 - <<'PY'
import os, tempfile
path = os.environ["ENV_FILE"]
var, old, new = os.environ["KANBAN_VAR"], os.environ["OLD_S"], os.environ["NEW_S"]
lines = []
for ln in open(path).readlines():
    if ln.startswith(var + "="):
        ln = ln.replace(old, new)
    lines.append(ln)
fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".env.")
with os.fdopen(fd, "w") as f:
    f.writelines(lines)
os.chmod(tmp, 0o600)
os.replace(tmp, path)
PY
      echo "✅ 5/8 ${kanban_var}: suffix ${old_suffix} → ${new_suffix}"
    else
      echo "✅ 5/8 ${kanban_var}: no entry for this key's suffix (alias-keyed or absent) — unchanged"
    fi
  else
    echo "✅ 5/8 no ${kanban_var} in .env — nothing to regenerate"
  fi

  # ── 5. Restart affected containers ──
  # Services whose compose block references \${env_var} must be recreated to
  # pick up the new value. Caddy consumes the family keys via env_file
  # (no explicit ref) — recreate it too; a plain 'caddy reload' re-parses
  # with the container's baked env and would keep the OLD keys.
  local restart_cmds=() f svc
  for f in compose/*.yml; do
    grep -q "\${${env_var}}" "$f" || continue
    while IFS= read -r svc; do
      [[ -n "${svc}" ]] && restart_cmds+=("docker compose --env-file .env -f ${f} up -d ${svc}")
    done < <(python3 -c "
import sys
var, path = sys.argv[1], sys.argv[2]
lines = open(path).readlines()
services, cur = {}, None
for ln in lines:
    if len(ln) > 2 and ln.startswith('  ') and not ln.startswith('    ') and ln.rstrip().endswith(':'):
        cur = ln.strip()[:-1]
        services[cur] = []
    elif cur is not None:
        services[cur].append(ln)
for s, body in services.items():
    if any(('$' + '{' + var) in b for b in body):
        print(s)
" "$f" "${env_var}")
  done
  case "${env_var}" in
    LITELLM_KEY_CHUCK|LITELLM_KEY_DYLAN)
      restart_cmds+=("docker compose --env-file .env -f compose/compose.core.yml up -d caddy")
      ;;
  esac

  if [[ ${#restart_cmds[@]} -eq 0 ]]; then
    echo "✅ 6/8 no containers reference \${${env_var}} — nothing to restart"
  else
    cd "${repo_root}"
    local cmd
    for cmd in "${restart_cmds[@]}"; do
      echo "   → ${cmd}"
      eval "${cmd}" >/dev/null || { echo "❌ Restart failed: ${cmd}" >&2; exit 1; }
    done
    echo "✅ 6/8 ${#restart_cmds[@]} container(s) recreated"
  fi

  # ── 6. Block the old key ──
  local resp2
  resp2=$(curl -s --max-time 15 -X POST -H "Authorization: Bearer ${LITELLM_MASTER}" \
    -H "Content-Type: application/json" "${LITELLM_PROXY}/key/block" \
    -d "$(python3 -c "import json,sys; print(json.dumps({'key': sys.argv[1]}))" "${hash}")")
  if ! echo "${resp2}" | python3 -c "import sys,json; d=json.load(sys.stdin); exit(0 if (d.get('blocked') or 'key_name' in d) else 1)" 2>/dev/null; then
    echo "❌ Failed to block old key: ${resp2}" >&2
    echo "  .env already points at the new key — block manually: ./homelab.sh key block ${hash}" >&2
    exit 1
  fi
  echo "✅ 7/8 old key (${key_name}, alias '${old_alias_new:-—}') BLOCKED"

  # ── 8. key-sync-check ──
  # Gate semantics (same as scripts/rotate-github-tokens.sh): drift on the
  # ROTATED var = the rotation did not propagate → FAIL. Drift on OTHER
  # vars = pre-existing carrier drift (containers that carry the var via
  # whole-.env injection but don't use it — they refresh on their next
  # recreate) → informational, does not fail the rotation.
  echo "   → scripts/key-sync-check.sh"
  local sync_out sync_rc
  sync_out=$("${repo_root}/scripts/key-sync-check.sh" 2>&1)
  sync_rc=$?
  echo "${sync_out}"
  if grep -q "DRIFT.*${env_var}" <<<"${sync_out}"; then
    echo "❌ key-sync-check: drift on ${env_var} — the rotation did not fully propagate. Recreate the flagged container(s) per the output above, then re-run scripts/key-sync-check.sh" >&2
    exit 1
  fi
  if [[ ${sync_rc} -ne 0 ]]; then
    echo "⚠️  key-sync-check: pre-existing drift on OTHER vars (unrelated to this rotation — carrier containers awaiting their next recreate). See output above."
  else
    echo "✅ 8/8 key-sync-check: all in sync"
  fi

  echo ""
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "  ✅ Rotation complete for '${identifier}'"
  echo ""
  echo "  New key (update your clients now):"
  echo "  ${new_key}"
  echo ""
  echo "  Old key ${key_name} (alias now '${old_alias_new:-—}'): BLOCKED (not deleted)."
  echo "  Observe ${observe_days} days, then delete:"
  echo "    ./homelab.sh key delete ${hash}"
  echo ""
  echo "  .env backup:  ${backup_dir}/env-${stamp}.bak"
  echo "  Rollback:     restore the backup + ./homelab.sh key unblock ${hash}"
  echo "                 + recreate the containers from step 5"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
}

# ── key add-agent (Phase 13.5) ──
# One command to stand up an agent key (framework step 6): mint with the
# per-work-type model default, then wire the three .env surfaces in one
# atomic pass:
#   1. LITELLM_KEY_<SLUG>=<key>          (the key itself)
#   2. MEMORY_USER_KEYS += ,<slug>=LITELLM_KEY_<SLUG>   (identity/spend map —
#      env-var-name template, stable across rotation)
#   3. KANBAN_MCP_KEY_CAPABILITIES += ;<slug>:<capability>
#      (alias-keyed since 13.3 — stable across rotation)
# Then recreate the consumers (skill-runner: MEMORY_USER_KEYS;
# mcp_kanban: the capability map) and run scripts/key-sync-check.sh.
# Conventions (todo_agentic_framework.md step-6 checklist): alias = slug
# (product/analyst/strategist/marketing); model default by work type
# (coding → matrix-coder, writing → matrix-copywriter); default
# capability = control (board mutation without project admin).

_key_add_agent() {
  local slug="${1:?Usage: ./homelab.sh key add-agent <slug> [--work-type coding|writing] [--capability read|control|admin]}"
  shift
  local work_type="coding" capability="control"
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --work-type)  work_type="$2";  shift 2 ;;
      --capability) capability="$2"; shift 2 ;;
      *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
  done

  [[ -n "${LITELLM_MASTER}" ]] || { echo "❌ LITELLM_MASTER_KEY not set (source .env first)." >&2; exit 1; }
  [[ "${slug}" =~ ^[a-z][a-z0-9_-]*$ ]] || { echo "❌ slug must be lowercase (letters/digits/-/_), e.g. 'strategist'." >&2; exit 1; }
  case "${capability}" in read|control|admin) ;; *) echo "❌ --capability must be read|control|admin." >&2; exit 1 ;; esac
  local models
  case "${work_type}" in
    coding)  models="matrix-coder" ;;
    writing) models="matrix-copywriter" ;;
    *) echo "❌ --work-type must be coding|writing." >&2; exit 1 ;;
  esac

  local repo_root env_file env_var
  repo_root=$(cd "$(dirname "${BASH_SOURCE[1]}")/.." && pwd)
  env_file="${repo_root}/.env"
  env_var="LITELLM_KEY_$(echo "${slug}" | tr '[:lower:]' '[:upper:]' | sed 's/[^A-Z0-9]/_/g')"

  # Guards: slug and env var must be unused.
  local existing
  existing=$(_key_find_hash "${slug}")
  if [[ "${existing}" != "NOT_FOUND" && -n "${existing}" ]]; then
    echo "❌ A key matching '${slug}' already exists." >&2
    exit 1
  fi
  grep -q "^${env_var}=" "${env_file}" && { echo "❌ ${env_var} already present in .env." >&2; exit 1; }

  # 1. Mint (per-work-type model default).
  local payload resp new_key
  payload=$(python3 -c "
import json, sys
print(json.dumps({'user_id': sys.argv[1], 'key_alias': sys.argv[1], 'models': [sys.argv[2]]}))
" "${slug}" "${models}")
  resp=$(curl -s --max-time 30 -X POST "${LITELLM_PROXY}/key/generate" \
    -H "Authorization: Bearer ${LITELLM_MASTER}" \
    -H "Content-Type: application/json" \
    -d "${payload}")
  new_key=$(echo "${resp}" | python3 -c "import sys,json; print(json.load(sys.stdin).get('key',''))" 2>/dev/null)
  if [[ -z "${new_key}" || "${new_key}" == "null" ]]; then
    echo "❌ Failed to mint key for '${slug}': ${resp}" >&2
    exit 1
  fi
  local probe
  probe=$(curl -s --max-time 15 -o /dev/null -w "%{http_code}" \
    "${LITELLM_PROXY}/v1/models" -H "Authorization: Bearer ${new_key}")
  if [[ "${probe}" != "200" ]]; then
    echo "❌ New key failed the /v1/models probe (HTTP ${probe}) — aborting, nothing written." >&2
    local new_hash
    new_hash=$(_key_find_hash "${new_key: -4}")
    if [[ "${new_hash}" != "NOT_FOUND" ]]; then
      curl -s -X POST -H "Authorization: Bearer ${LITELLM_MASTER}" \
        -H "Content-Type: application/json" "${LITELLM_PROXY}/key/block" \
        -d "$(python3 -c "import json,sys; print(json.dumps({'key': sys.argv[1]}))" "${new_hash}")" >/dev/null 2>&1
    fi
    exit 1
  fi
  echo "✅ 1/4 key minted for agent '${slug}' (alias=${slug}, user=${slug}, models=${models}) + probe 200"

  # 2. Wire the three .env surfaces in one atomic pass.
  ENV_FILE="${env_file}" ENV_VAR="${env_var}" NEW_KEY="${new_key}" SLUG="${slug}" CAP="${capability}" python3 - <<'PY'
import os, tempfile
path = os.environ["ENV_FILE"]
env_var, new_key, slug, cap = (os.environ[k] for k in ("ENV_VAR", "NEW_KEY", "SLUG", "CAP"))
lines = open(path).readlines()
out, added_var, added_mem, added_kanban = [], False, False, False
for ln in lines:
    if ln.startswith("MEMORY_USER_KEYS="):
        val = ln.split("=", 1)[1].rstrip("\n")
        if f"{slug}=" not in val:
            ln = f"MEMORY_USER_KEYS={val},{slug}={env_var}\n"
        added_mem = True
    elif ln.startswith("KANBAN_MCP_KEY_CAPABILITIES="):
        val = ln.split("=", 1)[1].rstrip("\n")
        quoted = val.startswith('"') and val.endswith('"')
        inner = val[1:-1] if quoted else val
        if f"{slug}:" not in inner:
            inner = f"{inner};{slug}:{cap}"
        ln = f"KANBAN_MCP_KEY_CAPABILITIES={'\"' + inner + '\"' if quoted else inner}\n"
        added_kanban = True
    out.append(ln)
out.append(f"{env_var}={new_key}\n")
fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".env.")
with os.fdopen(fd, "w") as f:
    f.writelines(out)
os.chmod(tmp, 0o600)
os.replace(tmp, path)
missing = [n for n, ok in (("MEMORY_USER_KEYS", added_mem),
                            ("KANBAN_MCP_KEY_CAPABILITIES", added_kanban)) if not ok]
if missing:
    raise SystemExit("missing .env line(s): " + ", ".join(missing))
PY
  if [[ $? -ne 0 ]]; then
    echo "❌ .env wiring failed (MEMORY_USER_KEYS / KANBAN_MCP_KEY_CAPABILITIES line missing?). Key '${new_key:0:12}…' is minted but unwired — delete it: ./homelab.sh key delete ${slug}" >&2
    exit 1
  fi
  echo "✅ 2/4 .env wired: ${env_var} + MEMORY_USER_KEYS + KANBAN_MCP_KEY_CAPABILITIES (${slug}:${capability})"

  # 3. Recreate the consumers.
  cd "${repo_root}"
  local cmds=(
    "docker compose --env-file .env -f compose/compose.skill-runner.yml up -d skill-runner"
    "docker compose --env-file .env -f compose/compose.mcp.yml up -d mcp_kanban"
  )
  local cmd
  for cmd in "${cmds[@]}"; do
    echo "   → ${cmd}"
    eval "${cmd}" >/dev/null || { echo "❌ Restart failed: ${cmd}" >&2; exit 1; }
  done
  echo "✅ 3/4 skill-runner + mcp_kanban recreated"

  # 4. key-sync-check (gate: fail on drift of the new var; other drift = informational).
  echo "   → scripts/key-sync-check.sh"
  local sync_out sync_rc
  sync_out=$("${repo_root}/scripts/key-sync-check.sh" 2>&1)
  sync_rc=$?
  echo "${sync_out}" | tail -3
  if grep -q "DRIFT.*${env_var}" <<<"${sync_out}"; then
    echo "❌ key-sync-check: drift on ${env_var} — fix per the output above." >&2
    exit 1
  fi
  [[ ${sync_rc} -ne 0 ]] && echo "⚠️  key-sync-check: pre-existing drift on OTHER vars (unrelated — see full output)."
  echo "✅ 4/4 key-sync-check: ${env_var} in sync"

  echo ""
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "  ✅ Agent key ready: '${slug}'"
  echo ""
  echo "  API Key (hand to the agent's config):"
  echo "  ${new_key}"
  echo ""
  echo "  Model default:  ${models} (work type: ${work_type})"
  echo "  Kanban caps:    ${capability}"
  echo ""
  echo "  Next (framework step-6 checklist):"
  echo "    - pi-agent-${slug} workspace under data/ai-kanban/"
  echo "    - AGENT_CONCURRENT_TASKS slot + cron jobs"
  echo "    - record the key in security_todo.md §1 (key inventory)"
  echo "  Rotation: ./homelab.sh key rotate ${slug}"
  echo "  Rollback: ./homelab.sh key delete ${slug} + restore the .env backup"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
}
