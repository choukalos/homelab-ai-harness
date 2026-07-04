#!/usr/bin/env bash
#
# Thor Skill Runner — Laptop LAN Dev Quickstart
#
# Runs the skill runner directly on your laptop, pointing at the LiteLLM
# proxy on Thor (192.168.4.54:4000) over the LAN.  No Docker required.
#
# Usage:
#   ./dev.sh              # start the skill runner on port 8091
#   ./dev.sh --help       # show this help
#   LITELLM_API_KEY=xxx ./dev.sh   # override API key
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ---------------------------------------------------------------------------
# Defaults — override via environment or args
# ---------------------------------------------------------------------------
export LITELLM_BASE_URL="${LITELLM_BASE_URL:-http://192.168.4.54:4000}"
export SKILL_RUNNER_PORT="${SKILL_RUNNER_PORT:-8091}"
export SKILL_RUNNER_HOST="${SKILL_RUNNER_HOST:-0.0.0.0}"
export ARTIFACT_ROOT="${ARTIFACT_ROOT:-/home/chuck/data/media}"
export SKILL_RUNNER_LOG_DIR="${SKILL_RUNNER_LOG_DIR:-/home/chuck/homelab/logs/skill_runner}"
export PYTHONUNBUFFERED="${PYTHONUNBUFFERED:-1}"

# ---------------------------------------------------------------------------
# Help
# ---------------------------------------------------------------------------
show_help() {
  cat <<EOF
Thor Skill Runner — Laptop LAN Dev Quickstart

Starts the skill runner on your laptop, calling the LiteLLM proxy on
Thor over the LAN.

Defaults:
  LITELLM_BASE_URL   = ${LITELLM_BASE_URL}
  SKILL_RUNNER_PORT  = ${SKILL_RUNNER_PORT}
  SKILL_RUNNER_HOST  = ${SKILL_RUNNER_HOST}
  ARTIFACT_ROOT      = ${ARTIFACT_ROOT}
  SKILL_RUNNER_LOG_DIR = ${SKILL_RUNNER_LOG_DIR}

All defaults can be overridden by exporting the variable before calling
this script, e.g.:

  LITELLM_API_KEY=sk-xxx ./dev.sh

EOF
}

# ---------------------------------------------------------------------------
# Argument handling
# ---------------------------------------------------------------------------
if [[ "${1:-}" == "--help" ]] || [[ "${1:-}" == "-h" ]]; then
  show_help
  exit 0
fi

# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------
echo "=== Thor Skill Runner (laptop dev mode) ==="
echo "LITELLM_BASE_URL   = ${LITELLM_BASE_URL}"
echo "SKILL_RUNNER_PORT  = ${SKILL_RUNNER_PORT}"
echo "SKILL_RUNNER_HOST  = ${SKILL_RUNNER_HOST}"
echo "ARTIFACT_ROOT      = ${ARTIFACT_ROOT}"
echo "Log dir            = ${SKILL_RUNNER_LOG_DIR}"
echo ""

# Ensure log directory exists
mkdir -p "${SKILL_RUNNER_LOG_DIR}"

# Check if uv is available (preferred) or fall back to .venv
if command -v uv &>/dev/null; then
  # Use uv to create/manage venv and install dependencies
  if [[ ! -d "${SCRIPT_DIR}/.venv" ]]; then
    echo "Creating virtual environment with uv..."
    uv venv "${SCRIPT_DIR}/.venv"
    uv pip install -e "${SCRIPT_DIR}"
  fi
  VENV_ACTIVATE="${SCRIPT_DIR}/.venv/bin/activate"
elif [[ -f "${SCRIPT_DIR}/.venv/bin/activate" ]]; then
  VENV_ACTIVATE="${SCRIPT_DIR}/.venv/bin/activate"
else
  echo "ERROR: Neither 'uv' nor an existing .venv found."
  echo "Install uv (https://docs.astral.sh/uv/) or run 'python -m venv .venv && uv pip install -e .'"
  exit 1
fi

echo "Activating virtual environment..."
source "${VENV_ACTIVATE}"

echo ""
echo "Starting skill runner on http://${SKILL_RUNNER_HOST}:${SKILL_RUNNER_PORT} ..."
echo "Pointed at LiteLLM: ${LITELLM_BASE_URL}"
echo "Press Ctrl+C to stop."
echo ""

# ---------------------------------------------------------------------------
# Launch uvicorn
# ---------------------------------------------------------------------------
exec uvicorn main:app \
  --host "${SKILL_RUNNER_HOST}" \
  --port "${SKILL_RUNNER_PORT}" \
  --log-level info
