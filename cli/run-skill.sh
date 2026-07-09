#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# run-skill.sh — CLI for testing the Thor Skill Runner
#
# Quick CLI to call the Chat Gateway (/api/chat) and poll
# async job results. Supports intent override as first arg.
#
# Usage:
#   ./run-skill.sh "your question"                  # auto-detect intent (chat default)
#   ./run-skill.sh deep-research "quantum computing" # explicit intent
#   ./run-skill.sh list-demos                        # sync intent
#   ./run-skill.sh --help                            # show usage
#
# Reads .env for SIRI_API_KEY and THOR_IP.
# ─────────────────────────────────────────────────────────────

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Load environment ────────────────────────────────────────
if [[ -f "${SCRIPT_DIR}/../.env" ]]; then
    set -a
    source "${SCRIPT_DIR}/../.env"
    set +a
elif [[ -f "${SCRIPT_DIR}/.env" ]]; then
    set -a
    source "${SCRIPT_DIR}/.env"
    set +a
fi

# Endpoint config — default to local, use --public for remote
SIRI_API_KEY="${SIRI_API_KEY:?SIRI_API_KEY is not set (needs .env or env var)}"
BASE_SKILL_RUNNER="${BASE_SKILL_RUNNER:-http://${THOR_IP:-192.168.4.54}:8091}"
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

# ── Temp file management ────────────────────────────────────
_cleanup_files() {
    [[ -n "${_PAYLOAD_FILE:-}" ]] && rm -f "$_PAYLOAD_FILE" 2>/dev/null
    [[ -n "${_RESP_FILE:-}" ]] && rm -f "$_RESP_FILE" 2>/dev/null
}
trap _cleanup_files EXIT

_PAYLOAD_FILE=""
_RESP_FILE=""

# ── Detect intent from text ─────────────────────────────────
detect_intent() {
    local text_lower
    text_lower=$(echo "$1" | tr '[:upper:]' '[:lower:]')

    # Media generation — match image/media creation keywords
    if [[ "$text_lower" == *"image"* ]] || [[ "$text_lower" == *"picture"* ]] || [[ "$text_lower" == *"photo"* ]] || \
       [[ "$text_lower" == *"draw"* ]] || [[ "$text_lower" == *"render"* ]] || [[ "$text_lower" == *"media generat"* ]] || \
       [[ "$text_lower" == *"generate image"* ]] || [[ "$text_lower" == *"create image"* ]] || [[ "$text_lower" == *"make image"* ]] || \
       [[ "$text_lower" == *"generate media"* ]] || [[ "$text_lower" == *"create media"* ]]; then
        echo "media-generate"
    elif [[ "$text_lower" == *"deep research"* ]] || [[ "$text_lower" == *"deep-research"* ]] || [[ "$text_lower" == *"deep research"* ]]; then
        echo "deep-research"
    elif [[ "$text_lower" == *"investment brief"* ]] || [[ "$text_lower" == *"investment-brief"* ]] || [[ "$text_lower" == *"stock brief"* ]] || [[ "$text_lower" == *"stock-brief"* ]]; then
        echo "investment-brief"
    elif [[ "$text_lower" == *"morning brief"* ]] || [[ "$text_lower" == *"morning-brief"* ]] || [[ "$text_lower" == *"daily brief"* ]] || [[ "$text_lower" == *"daily-brief"* ]] || [[ "$text_lower" == *"daily summary"* ]]; then
        echo "morning-brief"
    elif [[ "$text_lower" == *"research brief"* ]] || [[ "$text_lower" == *"research-brief"* ]] || [[ "$text_lower" == *"research summary"* ]]; then
        echo "research-brief"
    elif [[ "$text_lower" == *"create demo"* ]] || [[ "$text_lower" == *"create-demo"* ]] || [[ "$text_lower" == *"new demo"* ]]; then
        echo "create-demo"
    elif [[ "$text_lower" == *"create presentation"* ]] || [[ "$text_lower" == *"create-presentation"* ]]; then
        echo "create-presentation"
    elif [[ "$text_lower" == *"update presentation"* ]] || [[ "$text_lower" == *"update-presentation"* ]]; then
        echo "update-presentation"
    elif [[ "$text_lower" == *"list demo"* ]] || [[ "$text_lower" == *"list-demo"* ]] || [[ "$text_lower" == *"list demos"* ]] || [[ "$text_lower" == *"list-demos"* ]]; then
        echo "list-demos"
    elif [[ "$text_lower" == *"find demo"* ]] || [[ "$text_lower" == *"find-demo"* ]] || [[ "$text_lower" == *"search demo"* ]]; then
        echo "find-demo"
    elif [[ "$text_lower" == *"list presentation"* ]] || [[ "$text_lower" == *"list-presentation"* ]] || [[ "$text_lower" == *"list presentations"* ]]; then
        echo "list-presentations"
    elif [[ "$text_lower" == *"list image"* ]] || [[ "$text_lower" == *"list-image"* ]] || [[ "$text_lower" == *"list images"* ]] || [[ "$text_lower" == *"list my image"* ]] || [[ "$text_lower" == *"show image"* ]] || [[ "$text_lower" == *"show images"* ]] || [[ "$text_lower" == *"show my image"* ]]; then
        echo "list-images"
    elif [[ "$text_lower" == *"find presentation"* ]] || [[ "$text_lower" == *"find-presentation"* ]]; then
        echo "find-presentation"
    else
        echo "chat"
    fi
}

# ── Poll async job ──────────────────────────────────────────
# ── Check if intent is async ────────────────────────────────
is_async_intent() {
    # ALL non-chat intents now dispatch as background jobs and return job_id
    case "$1" in
        chat)
            return 1 ;;
        *)
            return 0 ;;
    esac
}

# ── Poll an async job ────────────────────────────────────────
poll_job() {
    local job_id="$1"
    local max_attempts="${2:-60}"
    local delay="${3:-5}"
    local attempts=0

    echo -e "\n${CYAN}━━━ POLLING JOB ━━━${NC}"
    echo -e "  ${BLUE}Job ID:${NC}   ${BOLD}${job_id}${NC}"
    echo -e "  ${BLUE}Endpoint:${NC} ${BASE_SKILL_RUNNER}/skills/jobs/${job_id}"
    echo ""

    while [[ $attempts -lt $max_attempts ]]; do
        attempts=$((attempts + 1))
        local poll_resp
        poll_resp=$(mktemp)
        local http_code
        http_code=$(curl -sS -o "${poll_resp}" -w "%{http_code}" \
            -X GET "${BASE_SKILL_RUNNER}/skills/jobs/${job_id}" \
            -H "X-API-Key: ${SIRI_API_KEY}" \
            --max-time 30 2>/dev/null) || http_code="000"

        if [[ "$http_code" != "200" ]]; then
            echo -e "  ${YELLOW}⏳ Attempt ${attempts}/${max_attempts} — HTTP ${http_code}${NC}"
            rm -f "$poll_resp"
            sleep "$delay"
            continue
        fi

        # Check status field from response
        local status
        status=$(python3 -c "import json; print(json.load(open('${poll_resp}')).get('status','unknown'))" 2>/dev/null) || status="unknown"

        if [[ "$status" == "completed" ]] || [[ "$status" == "done" ]]; then
            echo -e "  ${GREEN}✓ Job completed!${NC}"
            echo ""

            # Extract speak/display from top-level or from params for async dispatch
            local speak display data_json
            speak=$(python3 -c "
import json
d = json.load(open('${poll_resp}'))
s = d.get('speak', '')
if not s:
    s = d.get('summary', '')
    if s and isinstance(s, str) and len(s) > 200:
        s = s[:197] + '...'
print(s)
" 2>/dev/null) || speak=""

            # For async-dispatched jobs, results are in params['_result_data']
            data_json=$(python3 -c "
import json
d = json.load(open('${poll_resp}'))
params = d.get('params', {})
data = params.get('_result_data', None)
if data:
    print(json.dumps(data, indent=2, default=str))
else:
    speak_val = d.get('speak', '')
    display_val = d.get('display', '')
    if display_val and display_val != speak_val:
        print(json.dumps({'display': display_val}, indent=2))
" 2>/dev/null) || data_json=""

            display=$(python3 -c "
import json
d = json.load(open('${poll_resp}'))
params = d.get('params', {})
result_display = params.get('_result_display', '')
if not result_display:
    result_display = d.get('display', '')
if result_display and isinstance(result_display, str):
    if len(result_display) > 500:
        result_display = result_display[:497] + '...'
    print(result_display)
" 2>/dev/null) || display=""

            echo -e "${GREEN}━━━ RESULT ━━━${NC}"
            if [[ -n "$speak" ]]; then
                echo -e "  ${BOLD}Speak:${NC} ${speak}"
            fi
            if [[ -n "$display" ]] && [[ "$display" != "$speak" ]]; then
                echo ""
                echo -e "  ${BOLD}Display:${NC}"
                echo "$display" | sed 's/^/  /'
            fi
            if [[ -n "$data_json" ]]; then
                echo ""
                echo -e "  ${BOLD}Data:${NC}"
                echo "$data_json" | sed 's/^/  /'
            fi
            rm -f "$poll_resp"
            return 0

        elif [[ "$status" == "failed" ]] || [[ "$status" == "error" ]]; then
            echo -e "  ${RED}✗ Job failed.${NC}"
            local error_msg
            error_msg=$(python3 -c "import json; print(json.load(open('${poll_resp}')).get('error', 'Unknown error'))" 2>/dev/null) || error_msg="Unknown"
            echo -e "  ${RED}Error: ${error_msg}${NC}"
            rm -f "$poll_resp"
            return 1
        else
            local current_status="${status:-running}"
            echo -e "  ${YELLOW}⏳ Attempt ${attempts}/${max_attempts} — Status: ${current_status}${NC}"
            rm -f "$poll_resp"
            sleep "$delay"
        fi
    done

    echo -e "  ${RED}✗ Polling timed out after ${max_attempts} attempts.${NC}"
    return 1
}

# ── Chat request (POST /api/chat) ───────────────────────────
chat_request() {
    local text="$1"
    local intent="$2"

    # Build JSON payload
    _PAYLOAD_FILE=$(mktemp)
    python3 -c "
import json, sys
payload = {'text': sys.argv[1], 'intent': sys.argv[2]}
model = sys.argv[3]
if model:
    payload['model'] = model
json.dump(payload, sys.stdout)
" "$text" "$intent" "${3:-}" > "$_PAYLOAD_FILE"

    # Determine timeout based on intent
    local timeout=120
    case "$intent" in
        deep-research|research) timeout=180 ;;
        create-demo|create-presentation|update-presentation) timeout=60 ;;
        research-brief|investment-brief|morning-brief) timeout=60 ;;
        list-demos|find-demo|list-presentations|find-presentation|list-images) timeout=30 ;;
        media-generate) timeout=120 ;;
        chat) timeout=120 ;;
        *) timeout=60 ;;
    esac

    # Display request info
    echo -e "\n${CYAN}━━━ REQUEST ━━━${NC}"
    echo -e "  ${BOLD}${BLUE}POST${NC} ${BASE_SKILL_RUNNER}/api/chat"
    echo -e "  ${BOLD}Intent:${NC} ${intent}"
    echo -e "  ${BOLD}Key:${NC}  ${SIRI_API_KEY:0:12}..."

    # Send request
    echo -n "  ${YELLOW}⏳ Sending request (timeout: ${timeout}s)...${NC} "
    _RESP_FILE=$(mktemp)
    local http_code
    http_code=$(curl -sS -o "${_RESP_FILE}" -w "%{http_code}" \
        -X POST "${BASE_SKILL_RUNNER}/api/chat" \
        -H "Content-Type: application/json" \
        -H "X-API-Key: ${SIRI_API_KEY}" \
        -d "@${_PAYLOAD_FILE}" \
        --max-time "${timeout}" 2>/dev/null) || http_code="000"

    if [[ "$http_code" != "200" ]]; then
        echo -e "${RED}failed (HTTP ${http_code})${NC}"
        echo ""
        if [[ -f "$_RESP_FILE" ]]; then
            echo -e "${RED}━━━ ERROR RESPONSE ━━━${NC}"
            cat "$_RESP_FILE" | sed 's/^/  /'
        fi
        rm -f "$_PAYLOAD_FILE" "$_RESP_FILE"
        _PAYLOAD_FILE=""
        _RESP_FILE=""
        return 1
    fi

    echo -e "${GREEN}done (HTTP ${http_code})${NC}"

    # Parse response fields
    local speak display job_id
    speak=$(python3 -c "
import json
d = json.load(open('${_RESP_FILE}'))
s = d.get('speak', '')
if not s:
    s = d.get('display', '')
    if isinstance(s, str) and len(s) > 200:
        s = s[:197] + '...'
print(s)
" 2>/dev/null) || speak=""
    display=$(python3 -c "import json; print(json.load(open('${_RESP_FILE}')).get('display', ''))" 2>/dev/null) || display=""
    job_id=$(python3 -c "import json; print(json.load(open('${_RESP_FILE}')).get('job_id', '') or '')" 2>/dev/null) || job_id=""

    # Handle async job dispatch
    if [[ -n "$job_id" ]]; then
        echo -e "\n${GREEN}━━━ JOB DISPATCHED ━━━${NC}"
        echo -e "  ${BOLD}Job ID:${NC} ${BOLD}${job_id}${NC}"
        if [[ -n "$speak" ]]; then
            echo -e "  ${BOLD}Speak:${NC} ${speak}"
        fi
        rm -f "$_PAYLOAD_FILE" "$_RESP_FILE"
        _PAYLOAD_FILE=""
        _RESP_FILE=""
        poll_job "$job_id"
        return $?
    fi

    # Handle sync response
    echo -e "\n${GREEN}━━━ RESPONSE ━━━${NC}"
    if [[ -n "$speak" ]]; then
        echo -e "  ${BOLD}Speak:${NC} ${speak}"
    fi
    if [[ -n "$display" ]] && [[ "$display" != "$speak" ]]; then
        echo ""
        echo -e "  ${BOLD}Display:${NC}"
        echo "$display" | sed 's/^/  /'
    fi
    rm -f "$_PAYLOAD_FILE" "$_RESP_FILE"
    _PAYLOAD_FILE=""
    _RESP_FILE=""
    return 0
}

# ── Usage / help ─────────────────────────────────────────────
usage() {
    echo -e "${BOLD}run-skill.sh — Thor Skill Runner CLI${NC}"
    echo ""
    echo -e "Usage:"
    echo -e "  ${CYAN}./run-skill.sh 'your question'${NC}                    Auto-detect intent (default: chat)"
    echo -e "  ${CYAN}./run-skill.sh deep-research 'quantum computing'${NC}  Explicit intent + text"
    echo -e "  ${CYAN}./run-skill.sh list-demos${NC}                       Sync intent"
    echo -e "  ${CYAN}./run-skill.sh --public 'your question'${NC}         Use public endpoint (siri.choukalos.com)"
    echo ""
    echo -e "Intents:"
    echo -e "  ${CYAN}chat${NC}                    — General chat with MCP tools"
    echo -e "  ${CYAN}deep-research${NC}           — Async deep research"
    echo -e "  ${CYAN}create-demo${NC}             — Async demo creation"
    echo -e "  ${CYAN}create-presentation${NC}     — Async presentation build"
    echo -e "  ${CYAN}media-generate${NC}          — Image generation via ComfyUI"
    echo -e "  ${CYAN}list-demos${NC}              — Sync: list demos"
    echo -e "  ${CYAN}find-demo${NC}               — Sync: find demo"
    echo -e "  ${CYAN}list-presentations${NC}      — Sync: list presentations"
    echo -e "  ${CYAN}find-presentation${NC}       — Sync: find presentation"
    echo -e "  ${CYAN}list-images${NC}             — Sync: list generated images"
    echo -e "  ${CYAN}investment-brief${NC}        — Investment/market briefing"
    echo -e "  ${CYAN}morning-brief${NC}             — Daily morning briefing"
    echo -e "  ${CYAN}research-brief${NC}            — Research summary/analysis"
    echo ""
    echo -e "Environment: ${CYAN}SIRI_API_KEY${NC} (from .env), ${CYAN}BASE_SKILL_RUNNER${NC} (default: ${BASE_SKILL_RUNNER}), ${CYAN}BASE_PUBLIC${NC} (default: ${BASE_PUBLIC})"
}

# ── Main ─────────────────────────────────────────────────────

# Handle --public flag before the case (can't use fallthrough with comments)
if [[ "${1:-}" == "--public" ]]; then
    BASE_SKILL_RUNNER="$BASE_PUBLIC"
    shift
fi

case "${1:-}" in
    --help|-h)
        usage
        exit 0
        ;;
    "")
        echo -e "${RED}Error: No arguments provided.${NC}"
        echo ""
        usage
        exit 1
        ;;
    *)
        first_arg="$1"

        # Check if first arg is a known intent
        known_intent=""
        case "$first_arg" in
            deep-research|research|create-demo|create-presentation|update-presentation|list-demos|find-demo|list-presentations|find-presentation|list-images|investment-brief|morning-brief|research-brief|chat|media-generate)
                known_intent="$first_arg"
                ;;
            *)
                known_intent=""
                ;;
        esac

        if [[ -n "$known_intent" ]]; then
            # First arg is intent, second is text
            shift
            text="${1:-}"
            if [[ -z "$text" ]] && [[ "$known_intent" != "list-demos" ]] && [[ "$known_intent" != "list-presentations" ]] && [[ "$known_intent" != "list-images" ]] && [[ "$known_intent" != "investment-brief" ]] && [[ "$known_intent" != "morning-brief" ]]; then
                echo -e "${RED}Error: No text provided for intent '${known_intent}'.${NC}"
                echo "Usage: ./run-skill.sh ${known_intent} 'your text'"
                exit 1
            fi
            # For list-demos/list-presentations with no text, use a default
            if [[ -z "$text" ]]; then
                case "$known_intent" in
                    list-demos) text="list my demos" ;;
                    list-presentations) text="list my presentations" ;;
                    list-images) text="list my images" ;;
                    investment-brief) text="brief me on today's market" ;;
                    morning-brief) text="give me my morning briefing" ;;
                    research-brief) text="give me a research summary" ;;
                esac
            fi
            chat_request "$text" "$known_intent"
        else
            # First arg is the text, auto-detect intent
            text="$first_arg"
            detected_intent=$(detect_intent "$text")
            chat_request "$text" "$detected_intent"
        fi
        exit $?
        ;;
esac