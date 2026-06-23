#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# Media Smoke Test — Image generation, image editing, clips
# ─────────────────────────────────────────────────────────────

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

set -a
source "${SCRIPT_DIR}/../../../.env"
set +a

BASE_URL="${BASE_LOCAL:-http://${THOR_IP:-192.168.4.54}:8090}"
API_KEY="${HARNESS_API_KEY:-}"
TMP_FILE=$(mktemp)

trap 'rm -f "${TMP_FILE}"' EXIT

echo "=========================================================="
echo "  Media Smoke Test"
echo "  Base URL: ${BASE_URL}"
echo "=========================================================="

# ── Helpers ──────────────────────────────────────────────────

call_post() {
  local name="$1" path="$2" payload="$3" timeout="${4:-600}"
  local resp
  resp="$(mktemp)"

  echo ""
  echo "==== ${name} ===>"
  echo "  POST ${path}"

  HTTP_CODE=$(curl -sS -o "${resp}" -w "%{http_code}" \
    -X POST "${BASE_URL}${path}" \
    -H "Content-Type: application/json" \
    -H "X-API-Key: ${API_KEY}" \
    -d "${payload}" \
    --max-time "${timeout}" 2>/dev/null) || HTTP_CODE="000"

  if [ "${HTTP_CODE}" = "200" ]; then
    echo "  ✅ ${name} (HTTP 200)"
  else
    echo "  ❌ ${name} (HTTP ${HTTP_CODE})"
    head -10 "${resp}"
  fi
  rm -f "${resp}"
}

# ── Health check ─────────────────────────────────────────────
echo -n "Health check... "
HC=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "${BASE_URL}/health" 2>/dev/null) || HC="000"
if [ "${HC}" = "200" ]; then
    echo "✅ OK"
else
    echo "❌ FAILED (HTTP ${HC}) — aborting"
    exit 1
fi

# ── Tests ────────────────────────────────────────────────────

call_post "Image Generation (text-to-image)" "/media/image" '{
  "prompt": "cinematic photo of a silver 1980s sports car at sunset",
  "negative_prompt": "blurry, distorted, low quality",
  "width": 1024,
  "height": 576,
  "seed": -1,
  "steps": 20,
  "cfg": 7,
  "upscale": true
}' 600

# Image edit from URL — extract image URL from previous response and use it
call_post "Clip Generation (text-to-clip)" "/media/clip" '{
  "prompt": "cinematic drone shot of a serene mountain lake at golden hour",
  "negative_prompt": "text, watermark",
  "width": 1024,
  "height": 576,
  "seed": -1,
  "steps": 15,
  "cfg": 8.0,
  "video_frames": 25,
  "fps": 6,
  "motion_bucket_id": 127
}' 600

echo
echo "=========================================================="
echo "  Media smoke tests complete"
echo "=========================================================="
echo
