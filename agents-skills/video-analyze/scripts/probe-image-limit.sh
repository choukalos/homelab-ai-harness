#!/usr/bin/env bash
# probe-image-limit.sh — Discover how many images the current model accepts
# per API request, BEFORE analyzing a batch of frames.
#
# Why this matters:
#   The limit is per API *request*, and every request carries the whole
#   conversation. An agent that reads images one at a time therefore has a
#   budget of N images TOTAL for its session (turns accumulate). Reading the
#   (N+1)-th image fails with:
#     400 ... "At most K image(s) may be provided in one prompt."
#   This script sends one probe request with N tiny images and reads K from
#   the error (or reports ">= N" if it succeeds).
#
# Usage:
#   probe-image-limit.sh [model] [--n N] [--provider P]
#     model     model id (default: $PI_MODEL, else matrix-coder)
#     --n N     images to send in the probe (default 12 — pick above the
#               expected limit so the error reveals the exact cap)
#     --provider provider key in models.json (default: $PI_PROVIDER, else litellm)
#
# Endpoint + key are read from ~/.pi/agent/models.json (nothing secret on CLI).
# Exit: 0 = limit determined (see stdout), 2 = could not determine.
set -uo pipefail

N=12
MODEL="${PI_MODEL:-}"
PROVIDER="${PI_PROVIDER:-}"

while [ $# -gt 0 ]; do
  case "$1" in
    --n)        N="$2"; shift 2 ;;
    --model)    MODEL="$2"; shift 2 ;;
    --provider) PROVIDER="$2"; shift 2 ;;
    -h|--help)  grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *)          MODEL="$1"; shift ;;
  esac
done
PROVIDER="${PROVIDER:-litellm}"
MODEL="${MODEL:-matrix-coder}"

# Endpoint + key: prefer $HOME/.pi/agent/models.json (providers.<P>:
# baseUrl/apiKey); fall back to $HOME/.pi/agent/auth.json (the key pi itself
# uses: <provider>.key + env.LITELLM_BASE_URL).
CONFIG="$HOME/.pi/agent/models.json"
AUTH="$HOME/.pi/agent/auth.json"

CRED=""
if [ -f "$CONFIG" ]; then
  CRED=$(python3 - "$CONFIG" "$PROVIDER" <<'EOF'
import json, sys
cfg = json.load(open(sys.argv[1]))
p = cfg.get("providers", {}).get(sys.argv[2], {})
base = (p.get("baseUrl") or "").rstrip("/")
key = p.get("apiKey") or ""
if not base or not key:
    sys.exit(1)
print(base + "\n" + key)
EOF
  ) || CRED=""
fi
if [ -z "$CRED" ] && [ -f "$AUTH" ]; then
  CRED=$(python3 - "$AUTH" "$PROVIDER" <<'EOF'
import json, sys
cfg = json.load(open(sys.argv[1]))
p = cfg.get(sys.argv[2]) or cfg.get("litellm") or {}
base = ((p.get("env") or {}).get("LITELLM_BASE_URL") or "").rstrip("/")
key = p.get("key") or ""
if not base or not key:
    sys.exit(1)
print(base + "\n" + key)
EOF
  ) || CRED=""
fi
if [ -z "$CRED" ]; then
  echo "ERROR: no endpoint to probe (checked $CONFIG and $AUTH)" >&2
  exit 2
fi
BASEURL=$(printf '%s\n' "$CRED" | head -1)
APIKEY=$(printf '%s\n' "$CRED" | tail -1)

# 1x1 red pixel PNG (tiny, so the probe costs ~nothing)
PNG_B64="iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="

BODY=$(python3 - "$MODEL" "$N" "$PNG_B64" <<'EOF'
import json, sys
model, n, png = sys.argv[1], int(sys.argv[2]), sys.argv[3]
content = [{"type": "text", "text": "Reply with the single word OK."}]
for _ in range(n):
    content.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{png}"}})
print(json.dumps({"model": model, "max_tokens": 5,
                  "messages": [{"role": "user", "content": content}]}))
EOF
) || { echo "ERROR: failed to build probe request" >&2; exit 2; }

RESP=$(curl -sS -m 90 -X POST "$BASEURL/chat/completions" \
  -H "Authorization: Bearer $APIKEY" \
  -H "Content-Type: application/json" \
  -d "$BODY" 2>&1)

if printf '%s' "$RESP" | grep -q '"choices"'; then
  echo "OK: $MODEL accepted $N images in one request (limit >= $N; raise --n to find the exact cap)"
  exit 0
fi

LIMIT=$(printf '%s' "$RESP" | grep -oE 'At most [0-9]+ image' | grep -oE '[0-9]+' | head -1)
if [ -n "$LIMIT" ]; then
  echo "LIMIT: $MODEL accepts at most $LIMIT images per request"
  echo "      -> batch frame analysis into groups of <= $LIMIT images per agent session"
  exit 0
fi

echo "ERROR: could not determine image limit; raw response:" >&2
printf '%s\n' "$RESP" | head -5 >&2
exit 2