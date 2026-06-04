#!/usr/bin/bash

set -euo pipefail

cd "$(dirname "$0")"

set -a
source ../../.env
set +a

#BASE_URL="${HARNESS_URL:-http://thor.local:8090}"
BASE_URL="${BASE_LOCAL:-http://${THOR_IP}:8090}"
AUTH_HEADER="X-API-Key: ${HARNESS_API_KEY}"

RUN_MEDIA_TESTS="${RUN_MEDIA_TESTS:-0}"
MEDIA_TEST_IMAGE="${MEDIA_TEST_IMAGE:-test.jpg}"
CLEANUP_TEST_OUTPUTS="${CLEANUP_TEST_OUTPUTS:-1}"

GENERATED_URLS=()

echo
echo "AI Harness Smoke Test"
echo "Base URL: ${BASE_URL}"
echo "Run media tests: ${RUN_MEDIA_TESTS}"
echo "Cleanup outputs: ${CLEANUP_TEST_OUTPUTS}"
echo

cleanup_generated_files() {
  if [[ "${CLEANUP_TEST_OUTPUTS}" != "1" ]]; then
    return
  fi

  if [[ ${#GENERATED_URLS[@]} -eq 0 ]]; then
    return
  fi

  if [[ -z "${MEDIA_OUTPUT_DIR:-}" ]]; then
    echo "Cleanup skipped: MEDIA_OUTPUT_DIR is not set."
    return
  fi

  if [[ ! -d "${MEDIA_OUTPUT_DIR}" ]]; then
    echo "Cleanup skipped: MEDIA_OUTPUT_DIR is not available from this machine: ${MEDIA_OUTPUT_DIR}"
    return
  fi

  echo
  echo "============================================================"
  echo "Cleaning up generated test files"
  echo "============================================================"

  for url in "${GENERATED_URLS[@]}"; do
    relative="${url#*/media/files/}"
    file_path="${MEDIA_OUTPUT_DIR}/${relative}"

    if [[ -f "${file_path}" ]]; then
      rm -f "${file_path}"
      echo "Deleted: ${file_path}"
    else
      echo "Not found, skipping: ${file_path}"
    fi
  done

  echo
}

trap cleanup_generated_files EXIT

remember_generated_urls_from_json() {
  local json_file="$1"

  python3 - <<PY
import json

with open("${json_file}", "r", encoding="utf-8") as f:
    data = json.load(f)

urls = []

if isinstance(data, dict):
    if isinstance(data.get("url"), str):
        urls.append(data["url"])

    for item in data.get("files", []):
        if isinstance(item, dict) and isinstance(item.get("url"), str):
            urls.append(item["url"])

for url in urls:
    print(url)
PY
}

call_post() {
  local name="$1"
  local path="$2"
  local payload="$3"
  local capture="${4:-0}"
  local response_file

  response_file="$(mktemp)"

  echo "============================================================"
  echo "$name"
  echo "POST $path"
  echo "============================================================"

  curl -sS -f \
    -X POST "${BASE_URL}${path}" \
    -H "Content-Type: application/json" \
    -H "${AUTH_HEADER}" \
    -d "${payload}" | tee "${response_file}" | python3 -m json.tool

  echo

  if [[ "${capture}" == "1" ]]; then
    while IFS= read -r url; do
      [[ -n "${url}" ]] && GENERATED_URLS+=("${url}")
    done < <(remember_generated_urls_from_json "${response_file}")
  fi

  rm -f "${response_file}"
}

call_post_form() {
  local name="$1"
  local path="$2"
  shift 2

  local response_file
  response_file="$(mktemp)"

  echo "============================================================"
  echo "$name"
  echo "POST $path"
  echo "============================================================"

  curl -sS -f \
    -X POST "${BASE_URL}${path}" \
    -H "${AUTH_HEADER}" \
    "$@" | tee "${response_file}" | python3 -m json.tool

  echo

  while IFS= read -r url; do
    [[ -n "${url}" ]] && GENERATED_URLS+=("${url}")
  done < <(remember_generated_urls_from_json "${response_file}")

  rm -f "${response_file}"
}

call_get() {
  local name="$1"
  local path="$2"

  echo "============================================================"
  echo "$name"
  echo "GET $path"
  echo "============================================================"

  curl -sS -f \
    "${BASE_URL}${path}" \
    -H "${AUTH_HEADER}" | python3 -m json.tool

  echo
}

call_get "Harness Health" "/health"

call_post "Web Search" "/web/search" '{
  "query": "FastAPI health check best practices",
  "max_results": 5,
  "crawl_results": 0,
  "summarize": false,
  "mode": "sources"
}'

call_post "Summarized Web Search" "/web/search" '{
  "query": "FastAPI health check best practices",
  "max_results": 5,
  "crawl_results": 3,
  "summarize": true,
  "mode": "answer"
}'

call_post "Research Brief" "/web/research" '{
  "topic": "local first AI knowledge base architecture for a homelab",
  "max_queries": 3,
  "results_per_query": 4
}'

call_get "Family KB Health" "/kb/health"

call_post "Family KB Raw Ingest" "/kb/ingest/raw" '{}'

call_post "Family KB Index Markdown Repo" "/kb/ingest" '{}'

call_post "Family KB Search" "/kb/search" '{
  "query": "family knowledge base",
  "limit": 5
}'

call_post "Family KB Ask" "/kb/ask" '{
  "query": "What information is saved in the family knowledge base?",
  "limit": 5
}'

call_post "PM Demo Generation" "/pm/demo" '{
  "title": "Smoke Test Mobile PM Demo",
  "prompt": "Create a simple 3-screen clickable mobile product demo for a family task tracker. Include home, task detail, and add task screens. Make it single-file HTML with inline CSS and JavaScript.",
  "save_name": "smoke-test-pm-demo"
}' "1"

if [[ "${RUN_MEDIA_TESTS}" == "1" ]]; then
  IMAGE_RESPONSE_FILE="$(mktemp)"

  echo "============================================================"
  echo "Media Image Generation"
  echo "POST /media/image"
  echo "============================================================"

  curl -sS -f \
    -X POST "${BASE_URL}/media/image" \
    -H "Content-Type: application/json" \
    -H "${AUTH_HEADER}" \
    -d '{
      "prompt": "cinematic photo of a silver 1980s sports car at sunset, ultra detailed",
      "negative_prompt": "blurry, distorted, low quality",
      "width": 1024,
      "height": 576,
      "seed": -1,
      "steps": 20,
      "cfg": 7,
      "upscale": true
    }' | tee "${IMAGE_RESPONSE_FILE}" | python3 -m json.tool

  echo

  while IFS= read -r url; do
    [[ -n "${url}" ]] && GENERATED_URLS+=("${url}")
  done < <(remember_generated_urls_from_json "${IMAGE_RESPONSE_FILE}")

  GENERATED_IMAGE_URL="$(python3 - <<PY
import json
with open("${IMAGE_RESPONSE_FILE}", "r", encoding="utf-8") as f:
    data = json.load(f)
files = data.get("files", [])
print(files[0].get("url", "") if files else "")
PY
)"

  rm -f "${IMAGE_RESPONSE_FILE}"

  if [[ -n "${GENERATED_IMAGE_URL}" ]]; then
    echo "Generated image URL:"
    echo "${GENERATED_IMAGE_URL}"
    echo

    call_post "Media Image Edit From URL" "/media/image/edit/url" "{
      \"image_url\": \"${GENERATED_IMAGE_URL}\",
      \"prompt\": \"turn this into a rainy cyberpunk night scene with neon reflections\",
      \"negative_prompt\": \"blurry, distorted, low quality\",
      \"denoise\": 0.55,
      \"seed\": -1,
      \"steps\": 20,
      \"cfg\": 7
    }" "1"
  else
    echo "Skipping Media Image Edit From URL: no generated image URL returned."
    echo
  fi

  if [[ -n "${MEDIA_TEST_IMAGE}" && -f "${MEDIA_TEST_IMAGE}" ]]; then
    call_post_form "Media Image Edit From Upload" "/media/image/edit" \
      -F "image=@${MEDIA_TEST_IMAGE}" \
      -F "prompt=retro cyberpunk style, cinematic neon lighting" \
      -F "negative_prompt=blurry, distorted, low quality" \
      -F "denoise=0.55" \
      -F "seed=-1" \
      -F "steps=20" \
      -F "cfg=7"
  else
    echo "Skipping Media Image Edit From Upload: missing ${MEDIA_TEST_IMAGE}"
    echo
  fi

  call_post "Media Clip Generation" "/media/clip" '{
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
  }' "1"
else
  echo "Skipping media tests. Run with RUN_MEDIA_TESTS=1 to enable."
  echo
fi

echo "============================================================"
echo "Smoke test complete."
echo "============================================================"


