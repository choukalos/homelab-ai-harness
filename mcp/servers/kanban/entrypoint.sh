#!/usr/bin/env bash
#
# ai-kanban container entrypoint (PLAN.md §1, Slice 0):
#   1. prepare the /data and /workspace volumes
#   2. clone/pull the homelab-ai-harness skills repo into /data/harness
#      (refresh = startup/rebuild only; auto-pull if already present)
#   3. validate MODEL against the LiteLLM proxy (fail fast)
#   4. start the app — migrations are versioned + idempotent and run at
#      app startup (src/db), so no separate migration step is needed
#
set -euo pipefail

log() { printf '[entrypoint] %s\n' "$*"; }
warn() { printf '[entrypoint] WARNING: %s\n' "$*" >&2; }
die() { printf '[entrypoint] ERROR: %s\n' "$*" >&2; exit 1; }

# --- 1. volumes -------------------------------------------------------------
# Data dir root (DB, sessions, agent dir, harness). Defaults to /data (the
# container volume); override via AI_KANBAN_DATA_DIR for local dev or
# non-standard deployments. The agent layer reads the same var, so keep them
# in sync — the entrypoint exports it after defaulting.
DATA_DIR="${AI_KANBAN_DATA_DIR:-/data}"
export AI_KANBAN_DATA_DIR="${DATA_DIR}"
mkdir -p "${DATA_DIR}" /workspace

# --- 2. harness skills -------------------------------------------------------
HARNESS_REPO_URL="${HARNESS_REPO_URL:-https://github.com/choukalos/homelab-ai-harness}"
HARNESS_DIR="${DATA_DIR}/harness"

if [ -d "${HARNESS_DIR}/.git" ]; then
  log "harness repo present at ${HARNESS_DIR} — pulling latest"
  if ! git -C "${HARNESS_DIR}" pull --ff-only --quiet; then
    warn "harness pull failed — continuing with the existing clone (skills may be stale)"
  fi
else
  if [ -e "${HARNESS_DIR}" ]; then
    warn "${HARNESS_DIR} exists but is not a git repo — removing and re-cloning"
    rm -rf "${HARNESS_DIR}"
  fi
  log "cloning harness repo ${HARNESS_REPO_URL} into ${HARNESS_DIR}"
  if ! git clone --quiet "${HARNESS_REPO_URL}" "${HARNESS_DIR}"; then
    warn "harness clone failed — sessions will run without harness skills"
  fi
fi

# --- 3. model validation (fail fast) -----------------------------------------
: "${LITELLM_BASE_URL:?LITELLM_BASE_URL is required (LiteLLM proxy endpoint)}"
: "${LITELLM_API_KEY:?LITELLM_API_KEY is required (kanban-user access key)}"
: "${MODEL:?MODEL is required (model ID in the LiteLLM config)}"

log "validating MODEL=${MODEL} against LiteLLM proxy at ${LITELLM_BASE_URL}"
node -e '
  const baseUrl = process.env.LITELLM_BASE_URL.replace(/\/+$/, "");
  const model = process.env.MODEL;
  const url = `${baseUrl}/models`;
  fetch(url, {
    headers: { Authorization: `Bearer ${process.env.LITELLM_API_KEY}` },
    signal: AbortSignal.timeout(15000),
  })
    .then(async (res) => {
      if (!res.ok) {
        const body = (await res.text().catch(() => "")).slice(0, 300);
        throw new Error(`LiteLLM proxy rejected validation (HTTP ${res.status} ${res.statusText}) at ${url}: ${body || "(no body)"}`);
      }
      const payload = await res.json();
      const ids = Array.isArray(payload?.data)
        ? payload.data.map((m) => m?.id).filter((id) => typeof id === "string")
        : [];
      if (!ids.includes(model)) {
        throw new Error(`MODEL=${model} is not served by the proxy at ${url}. Available models: ${ids.slice(0, 20).join(", ") || "(none)"}`);
      }
      console.log(`[entrypoint] model ${model} OK (${ids.length} models served by the proxy)`);
    })
    .catch((err) => {
      console.error(`[entrypoint] model validation failed: ${err.message}`);
      console.error("[entrypoint] the app cannot start — check LITELLM_BASE_URL / LITELLM_API_KEY / MODEL and retry.");
      process.exit(1);
    });
'

# --- 4. start -----------------------------------------------------------------
[ -f dist/main.js ] || die "app not built (dist/main.js missing) — rebuild the image"
log "starting ai-kanban (node dist/main.js)"
exec node dist/main.js
