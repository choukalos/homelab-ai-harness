#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# Siri Shortcut — Debug Script
#
# Interactive CLI to test Siri harness functions and inspect
# JSON payloads. Helps figure out dictionary structure for
# the Shortcuts app.
#
# Usage:
#   ./siri-script.sh                     # interactive mode
#   ./siri-script.sh chat                # quick-run a specific intent
#   ./siri-script.sh chat "hello"        # quick-run with custom text
#   ./siri-script.sh chat "hello" local  # force local endpoint
#
# Requires SIRI_API_KEY in .env (sourced automatically) or as env var.
# ─────────────────────────────────────────────────────────────

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Load environment ────────────────────────────────────────
if [[ -f "${SCRIPT_DIR}/.env" ]]; then
    set -a
    source "${SCRIPT_DIR}/.env"
    set +a
fi

SIRI_API_KEY="${SIRI_API_KEY:?SIRI_API_KEY is not set (needs .env or env var)}"
BASE_LOCAL="${BASE_LOCAL:-http://${THOR_IP:-192.168.4.54}:8090}"
BASE_PUBLIC="https://siri.choukalos.com"

# ── Color helpers ────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
BOLD='\033[1m'
NC='\033[0m'

# ── Intent definitions ──────────────────────────────────────
# Format: name|example text|intent override|timeout|description
#   name         — CLI shorthand for quick-run mode
#   example text — default text sent to Siri (user can override)
#   intent       — explicit intent override sent in JSON body
#   timeout      — curl timeout in seconds
#   description  — shown in interactive menu
declare -a INTENTS=(
    "chat|Say hello from Siri|chat|60|🧠 General Chat — default conversation"
    "research|Research best local embedding models|research|120|🔍 Research Brief (~10-30 sec)"
    "deep-research|Deep research autonomous vehicle safety|deep-research|180|🕵️ Deep Research (~180 sec, blocking)"
    "image|Generate image of a futuristic server room|image|120|🎨 Image Generation via ComfyUI (~30-60 sec)"
    "html-demo|Create a one page HTML demo of my family wiki|html-demo|60|📄 One-Page HTML Demo (instant)"
    "create-demo|Build a demo for a pet adoption app|create-demo|30|🚀 Create Demo (async, returns task_id)"
    "list-demos|List my demos|list-demos|30|📊 List Demos"
    "find-demo|Find demo about pets|find-demo|30|🔎 Find Demo by keyword"
    "demo-quality|How well does the pet adoption demo work?|demo-quality|30|📈 Demo Quality Score"
    "demo-complexity|How complex is the pet adoption demo?|demo-complexity|30|🧩 Demo Complexity"
    "create-presentation|Create a presentation about our AI homelab|create-presentation|30|📽️ Create Presentation (async)"
    "update-presentation|Update the AI homelab presentation to be more casual|update-presentation|30|✏️ Update Presentation (async)"
    "list-presentations|List my presentations|list-presentations|30|📋 List Presentations"
    "find-presentation|Find presentation about homelab|find-presentation|30|🔍 Find Presentation by keyword"
    "health|Health check|health|10|💚 Health Check (GET /health, no auth needed)"
    "custom|Enter your own text...|custom|120|✏️ Custom — build your own payload"
)

PAYLOAD_FILE=""
RESP_FILE=""
DICT_FILE=""
PY_SCRIPT=""
# ── Temp file management ────────────────────────────────────
_cleanup_files() {
    [[ -n "$PAYLOAD_FILE" ]] && rm -f "$PAYLOAD_FILE" 2>/dev/null
    [[ -n "$RESP_FILE" ]] && rm -f "$RESP_FILE" 2>/dev/null
    [[ -n "$DICT_FILE" ]] && rm -f "$DICT_FILE" 2>/dev/null
    [[ -n "$PY_SCRIPT" ]] && rm -f "$PY_SCRIPT" 2>/dev/null
}
trap _cleanup_files EXIT

# ── Pretty-print JSON ───────────────────────────────────────
pretty_json() {
    local file="$1"
    if command -v python3 &>/dev/null; then
        python3 -m json.tool "$file" 2>/dev/null || cat "$file"
    elif command -v jq &>/dev/null; then
        jq . "$file" 2>/dev/null || cat "$file"
    else
        cat "$file"
    fi
}

# ── Show Shortcut dictionary keys from a JSON response file ─
show_dict_keys() {
    local json_file="$1"
    PY_SCRIPT=$(mktemp --suffix=.py)
    cat > "$PY_SCRIPT" << 'PYEOF'
import json, sys
try:
    with open(sys.argv[1]) as f:
        data = json.load(f)
    for key in ['speak', 'display', 'session_id']:
        val = data.get(key)
        if val is not None:
            if isinstance(val, str) and len(val) > 120:
                val = val[:117] + '...'
            print(f'  {key}: {val}')
    if 'links' in data and data['links']:
        print(f'  links: (list of {len(data["links"])})')
        for i, link in enumerate(data['links']):
            print(f'    [{i}].title = {link.get("title", "")}')
            print(f'    [{i}].url   = {link.get("url", "")}')
    if 'media' in data and data['media']:
        print(f'  media: (list of {len(data["media"])})')
        for i, m in enumerate(data['media']):
            print(f'    [{i}].type = {m.get("type", "")}')
            print(f'    [{i}].url  = {m.get("url", "")}')
    if 'data' in data and data['data']:
        print(f'  data: (dict with {len(data["data"])} keys)')
        for k, v in data['data'].items():
            if isinstance(v, str) and len(v) > 120:
                v = v[:117] + '...'
            print(f'    data.{k} = {v}')
except Exception as e:
    print(f'  ⚠ Could not parse response: {e}')
PYEOF
    if command -v python3 &>/dev/null; then
        python3 "$PY_SCRIPT" "$json_file" 2>&1
    fi
}

# ── Build and execute a Siri request ─────────────────────────
siri_request() {
    local text="$1"
    local intent="${2:-chat}"
    local endpoint="${3:-public}"
    local session_id="${4:-}"
    local model="${5:-}"

    # Determine base URL
    local BASE_URL
    if [[ "$endpoint" == "local" ]]; then
        BASE_URL="$BASE_LOCAL"
    else
        BASE_URL="$BASE_PUBLIC"
    fi

    PAYLOAD_FILE=$(mktemp)
    RESP_FILE=$(mktemp)
    DICT_FILE=$(mktemp)

    # ── Health check (GET, no auth) ──────────────────────────
    if [[ "$intent" == "health" ]]; then
        echo -e "\n${CYAN}━━━ REQUEST ━━━${NC}"
        echo -e "${BLUE}GET  ${BASE_URL}/health${NC}"
        echo -e "Headers: (none — no auth required)"
        echo ""

        local HTTP_CODE
        HTTP_CODE=$(curl -sS -o "${RESP_FILE}" -w "%{http_code}" \
            --max-time 10 \
            "${BASE_URL}/health" 2>/dev/null) || HTTP_CODE="000"

        if [[ "$HTTP_CODE" == "200" ]]; then
            echo -e "${GREEN}━━━ RESPONSE (HTTP ${HTTP_CODE}) ━━━${NC}"
        else
            echo -e "${RED}━━━ RESPONSE (HTTP ${HTTP_CODE}) ━━━${NC}"
        fi
        pretty_json "$RESP_FILE"
        echo ""
        return
    fi

    # ── Build JSON payload via python3 for proper escaping ──
    python3 -c "
import json, sys
payload = {
    'text': sys.argv[1],
    'mode': 'voice',
    'return_media': True
}
intent = sys.argv[2]
if intent and intent not in ('chat', 'custom'):
    payload['intent'] = intent
session_id = sys.argv[3]
if session_id:
    payload['session_id'] = session_id
model = sys.argv[4]
if model:
    payload['model'] = model
json.dump(payload, sys.stdout)
" "$text" "$intent" "$session_id" "$model" > "$PAYLOAD_FILE"

    # ── Display request ──────────────────────────────────────
    echo -e "\n${CYAN}━━━ REQUEST ━━━${NC}"
    echo -e "${BOLD}${BLUE}POST ${BASE_URL}/siri/chat${NC}"
    echo -e "${BOLD}Headers:${NC}"
    echo -e "  Content-Type: application/json"
    echo -e "  X-API-Key: ${SIRI_API_KEY:0:8}****"
    echo ""
    echo -e "${BOLD}Body:${NC}"
    pretty_json "$PAYLOAD_FILE"

    # ── Determine timeout based on intent type ───────────────
    local timeout=120
    case "$intent" in
        deep-research) timeout=180 ;;
        image) timeout=120 ;;
        health) timeout=10 ;;
        create-demo|create-presentation|update-presentation) timeout=30 ;;
        *) timeout=60 ;;
    esac

    # ── Execute request ──────────────────────────────────────
    echo ""
    echo -n "  ${YELLOW}⏳ Sending request (timeout: ${timeout}s)...${NC} "
    local HTTP_CODE
    HTTP_CODE=$(curl -sS -o "${RESP_FILE}" -w "%{http_code}" \
        -X POST "${BASE_URL}/siri/chat" \
        -H "Content-Type: application/json" \
        -H "X-API-Key: ${SIRI_API_KEY}" \
        -d "@${PAYLOAD_FILE}" \
        --max-time "${timeout}" 2>/dev/null) || HTTP_CODE="000"

    if [[ "$HTTP_CODE" == "200" ]]; then
        echo -e "${GREEN}done${NC}"
    else
        echo -e "${RED}failed${NC}"
    fi

    if [[ "$HTTP_CODE" == "200" ]]; then
        echo -e "\n${GREEN}━━━ RESPONSE (HTTP ${HTTP_CODE}) ━━━${NC}"
    else
        echo -e "\n${RED}━━━ RESPONSE (HTTP ${HTTP_CODE}) ━━━${NC}"
    fi
    pretty_json "$RESP_FILE"

    # ── Extract dictionary keys for Shortcut app reference ──
    echo ""
    echo -e "${MAGENTA}━━━ SHORTCUT DICTIONARY KEYS ━━━${NC}"
    # Copy response to dict file for python helper
    cp "$RESP_FILE" "$DICT_FILE"
    show_dict_keys "$DICT_FILE"
    echo ""
}

# ── Interactive menu ─────────────────────────────────────────
interactive_mode() {
    while true; do
        echo ""
        echo -e "${BOLD}╔══════════════════════════════════════════════════════╗${NC}"
        echo -e "${BOLD}║${NC}     ${YELLOW}Siri Shortcut Debug Script${NC}                 ${BOLD}║${NC}"
        echo -e "${BOLD}║${NC}     ${CYAN}Base: ${NC}  ${BASE_LOCAL}         ${BOLD}║${NC}"
        echo -e "${BOLD}║${NC}     ${CYAN}Public: ${NC}${BASE_PUBLIC}          ${BOLD}║${NC}"
        echo -e "${BOLD}║${NC}     ${CYAN}Key:  ${NC}  ${SIRI_API_KEY:0:12}...              ${BOLD}║${NC}"
        echo -e "${BOLD}╚══════════════════════════════════════════════════════╝${NC}"
        echo ""
        echo -e "${BOLD}  Intent Menu:${NC}"
        echo -e "  ${YELLOW}00${NC}  exit"
        echo ""
        for i in "${!INTENTS[@]}"; do
            IFS='|' read -r name example intent_override timeout desc <<< "${INTENTS[$i]}"
            printf "  ${CYAN}%02d${NC}  %s\n" "$((i+1))" "$desc"
        done
        echo ""
        echo -n "  Select intent [1-$((${#INTENTS[@]}))]: "
        read -r choice

        if [[ "$choice" == "00" ]]; then
            echo "Bye!"
            exit 0
        fi

        local idx=$((choice - 1))
        if [[ $idx -lt 0 ]] || [[ $idx -ge ${#INTENTS[@]} ]]; then
            echo -e "  ${RED}Invalid selection${NC}"
            continue
        fi

        IFS='|' read -r name example intent_override timeout desc <<< "${INTENTS[$idx]}"

        # Confirm/edit text
        echo -e "\n  ${BOLD}Text:${NC} $example"
        echo -n "  (Press Enter to use above, or type new text): "
        read -r text_input
        local text="${text_input:-$example}"

        # Ask for endpoint
        echo -e "\n  Endpoint: ${CYAN}1${NC} Public (${BASE_PUBLIC})  ${CYAN}2${NC} Local (${BASE_LOCAL})"
        echo -n "  [1]: "
        read -r endpoint_input
        local endpoint="${endpoint_input:-1}"
        if [[ "$endpoint" == "2" ]]; then
            endpoint="local"
        else
            endpoint="public"
        fi

        # Ask for optional session_id
        echo -n "  Session ID (Enter to skip): "
        read -r session_id

        # Ask for optional model override
        echo -n "  Model override (Enter to skip): "
        read -r model

        siri_request "$text" "$intent_override" "$endpoint" "$session_id" "$model"

        # Ask to continue
        echo -n "  Press Enter to continue, or 'q' to quit: "
        read -r cont
        if [[ "$cont" == "q" ]]; then
            exit 0
        fi
    done
}

# ── Quick-run mode (CLI args) ────────────────────────────────
quick_run() {
    local intent="$1"
    shift
    local text="${1:-}"
    local endpoint="${2:-public}"

    # Look up the intent
    local found=0
    for entry in "${INTENTS[@]}"; do
        IFS='|' read -r name example intent_override timeout desc <<< "$entry"
        if [[ "$name" == "$intent" ]]; then
            found=1
            if [[ -z "$text" ]]; then
                text="$example"
            fi
            break
        fi
    done

    if [[ $found -eq 0 ]]; then
        echo -e "${RED}Unknown intent: ${intent}${NC}"
        echo "Available intents:"
        for entry in "${INTENTS[@]}"; do
            IFS='|' read -r name example intent_override timeout desc <<< "$entry"
            echo "  ${CYAN}${name}${NC} — ${desc}"
        done
        exit 1
    fi

    siri_request "$text" "$intent_override" "$endpoint"
}

# ── Usage ────────────────────────────────────────────────────
usage() {
    echo -e "${BOLD}Siri Shortcut Debug Script${NC}"
    echo ""
    echo "Usage:"
    echo "  ${CYAN}./siri-script.sh${NC}                      Interactive menu mode"
    echo "  ${CYAN}./siri-script.sh <intent>${NC}             Quick-run with default text"
    echo "  ${CYAN}./siri-script.sh <intent> 'text'${NC}      Quick-run with custom text"
    echo "  ${CYAN}./siri-script.sh <intent> 'text' local${NC}  Quick-run on local endpoint"
    echo ""
    echo "Available intents:"
    for entry in "${INTENTS[@]}"; do
        IFS='|' read -r name example intent_override timeout desc <<< "$entry"
        echo "  ${CYAN}${name}${NC} — ${desc}"
    done
    echo ""
    echo "Environment: SIRI_API_KEY (sourced from .env automatically)"
}

# ── Main ─────────────────────────────────────────────────────
case "${1:-}" in
    --help|-h)
        usage
        ;;
    "")
        interactive_mode
        ;;
    *)
        quick_run "$1" "${2:-}" "${3:-public}"
        ;;
esac
