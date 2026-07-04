#!/usr/bin/env bash
set -euo pipefail

BASE_DIR="/home/chuck/homelab"
COMPOSE_DIR="${BASE_DIR}/compose"

CORE="${COMPOSE_DIR}/compose.core.yml"
EDGE="${COMPOSE_DIR}/compose.edge.yml"
GHOST="${COMPOSE_DIR}/compose.ghost.yml"
AI_CORE="${COMPOSE_DIR}/compose.ai-core.yml"
HARNESS="${COMPOSE_DIR}/compose.ai-harness.yml"
INVEST="${COMPOSE_DIR}/compose.invest-hub.yml"
N8N="${COMPOSE_DIR}/compose.n8n.yml"
MONITORING="${COMPOSE_DIR}/compose.monitoring.yml"
MCP="${COMPOSE_DIR}/compose.mcp.yml"
SKILL_RUNNER="${COMPOSE_DIR}/compose.skill-runner.yml"

cd "${BASE_DIR}"

# Source LiteLLM key management helpers
source "${BASE_DIR}/lib/litellm-keys.sh"

usage() {
  cat <<EOF
Usage:
  ./homelab.sh <command> <stack> [extra docker compose args]

Commands:
  up          Bring stack up in detached mode
  down        Bring stack down
  restart     Restart stack
  rebuild     Rebuild containers for stack
  pull        Pull images for stack
  logs        Show logs for stack
  ps          Show containers for stack
  config      Render merged compose config

  key add     Create a new LiteLLM user key
               (no --budget = unlimited; see: ./homelab.sh key help)
  key list    List all LiteLLM keys
  key info    Show details for a key
  key update  Update key settings (models, budget, limits, etc.)
  key delete  Delete a key
  key block   Block a key (soft disable)
  key unblock Unblock a key
  key help    Show key management help

Stacks:
  core        Caddy only
  edge        Caddy + Cloudflare Tunnel
  ghost       Caddy + Cloudflare Tunnel + Ghost
  ai          AI core (litellm, open-webui, etc.) + MCP + Skill Runner
  invest      Caddy + Cloudflare Tunnel + Invest Hub
  public      Caddy + Cloudflare Tunnel + Ghost + Invest Hub
  n8n         Caddy + n8n
  monitoring  Monitoring (node-exporter, cadvisor, prometheus, grafana)
  all         Everything except n8n
  all-n8n     Everything including n8n

  core-only
  edge-only
  ghost-only     Ghost only (Caddy + cloudflared kept running)
  ai-only        AI core only (litellm, open-webui, qdrant, redis, searxng, etc.)
  harness-only   Harness only (FastAPI, workers, beat, kb-watcher)
  mcp-only       MCP servers only
  skill-only     Skill Runner only (MCP and AI core kept running)
  invest-only    Invest only (Caddy + cloudflared kept running)
  n8n-only
  monitoring-only

Notes:
  The ai stack comprises three separate Docker Compose projects sharing
  the ai-net bridge network: ai-core (litellm, open-webui, etc.),
  ai-mcp (MCP servers), and ai-skill-runner (skill runner). Rebuilding
  mcp-only or skill-only will NOT restart litellm or other ai-core
  services, so your LLM connection stays alive.

  harness is also a separate project. Rebuilding harness-only will NOT
  restart litellm or other ai-core services.

  ghost and invest are also separate projects. Rebuilding ghost-only or
  invest-only will NOT restart Caddy or Cloudflare Tunnel.

  monitoring is a standalone stack. Prometheus scrapes local services,
  matrix (node-exporter + dcgm), and athena (node-exporter + cadvisor).
EOF
}

compose_files() {
  local stack="$1"
  case "${stack}" in
    core|core-only) echo "-f ${CORE}" ;;
    edge)           echo "-f ${CORE} -f ${EDGE}" ;;
    edge-only)      echo "-f ${EDGE}" ;;
    ghost)          echo "-f ${CORE} -f ${EDGE} -f ${GHOST}" ;;
    ghost-only)     echo "-f ${GHOST}" ;;
    ai-only)        echo "-f ${AI_CORE}" ;;
    harness-only)   echo "-f ${HARNESS}" ;;
    invest)         echo "-f ${CORE} -f ${EDGE} -f ${INVEST}" ;;
    invest-only)    echo "-f ${INVEST}" ;;
    public)         echo "-f ${CORE} -f ${EDGE} -f ${GHOST} -f ${INVEST}" ;;
    n8n)            echo "-f ${CORE} -f ${N8N}" ;;
    n8n-only)       echo "-f ${N8N}" ;;
    monitoring|monitoring-only) echo "-f ${MONITORING}" ;;
    *)
      echo "Unknown stack: ${stack}" >&2
      usage
      exit 1
      ;;
  esac
}

run_compose_single() {
  local command="$1"
  local files="$2"
  shift 2
  # shellcheck disable=SC2086
  docker compose --env-file "${BASE_DIR}/.env" ${files} ${command} "$@"
}

run_ai_stack() {
  local command="$1"
  shift

  case "${command}" in
    up)
      run_compose_single up "-f ${AI_CORE}" -d "$@"
      run_compose_single up "-f ${MCP}" -d "$@"
      run_compose_single up "-f ${SKILL_RUNNER}" -d "$@"
      ;;
    down)
      run_compose_single down "-f ${SKILL_RUNNER}" "$@"
      run_compose_single down "-f ${MCP}" "$@"
      run_compose_single down "-f ${AI_CORE}" "$@"
      ;;
    restart)
      run_compose_single down "-f ${SKILL_RUNNER}" "$@"
      run_compose_single down "-f ${MCP}" "$@"
      run_compose_single down "-f ${AI_CORE}" "$@"
      run_compose_single up "-f ${AI_CORE}" -d
      run_compose_single up "-f ${MCP}" -d
      run_compose_single up "-f ${SKILL_RUNNER}" -d
      ;;
    rebuild)
      run_compose_single down "-f ${SKILL_RUNNER}" "$@"
      run_compose_single down "-f ${MCP}" "$@"
      run_compose_single down "-f ${AI_CORE}" "$@"
      run_compose_single up "-f ${AI_CORE}" -d --force-recreate --remove-orphans "$@"
      run_compose_single up "-f ${MCP}" -d --build --force-recreate --remove-orphans "$@"
      run_compose_single up "-f ${SKILL_RUNNER}" -d --build --force-recreate --remove-orphans "$@"
      ;;
    pull)
      run_compose_single pull "-f ${AI_CORE}" "$@"
      run_compose_single pull "-f ${MCP}" "$@"
      run_compose_single pull "-f ${SKILL_RUNNER}" "$@"
      ;;
    logs)
      run_compose_single logs "-f ${AI_CORE}" "$@"
      run_compose_single logs "-f ${MCP}" "$@"
      run_compose_single logs "-f ${SKILL_RUNNER}" "$@"
      ;;
    ps|config)
      echo "=== ai-core project ==="
      run_compose_single "${command}" "-f ${AI_CORE}" "$@"
      echo -e "\n=== ai-mcp project ==="
      run_compose_single "${command}" "-f ${MCP}" "$@"
      echo -e "\n=== ai-skill-runner project ==="
      run_compose_single "${command}" "-f ${SKILL_RUNNER}" "$@"
      ;;
    *)
      echo "Unknown command: ${command}" >&2
      usage
      exit 1
      ;;
  esac
}

run_ghost_stack() {
  local command="$1"
  shift

  # Ghost runs as its own project (homelab-ghost).
  # Caddy + cloudflared live in a separate project (homelab) and are NOT touched.
  case "${command}" in
    up)
      run_compose_single up "-f ${GHOST}" -d "$@"
      ;;
    down|restart|rebuild)
      run_compose_single down "-f ${GHOST}" "$@"
      if [[ "${command}" == "restart" || "${command}" == "rebuild" ]]; then
        run_compose_single up "-f ${GHOST}" -d --force-recreate --remove-orphans "$@"
      fi
      ;;
    pull)
      run_compose_single pull "-f ${GHOST}" "$@"
      ;;
    logs|ps|config)
      run_compose_single "${command}" "-f ${GHOST}" "$@"
      ;;
    *)
      echo "Unknown command: ${command}" >&2
      usage
      exit 1
      ;;
  esac
}

run_invest_stack() {
  local command="$1"
  shift

  # Invest runs as its own project (homelab-invest).
  # Caddy + cloudflared live in a separate project (homelab) and are NOT touched.
  case "${command}" in
    up)
      run_compose_single up "-f ${INVEST}" -d "$@"
      ;;
    down|restart|rebuild)
      run_compose_single down "-f ${INVEST}" "$@"
      if [[ "${command}" == "restart" || "${command}" == "rebuild" ]]; then
        run_compose_single up "-f ${INVEST}" -d --force-recreate --remove-orphans "$@"
      fi
      ;;
    pull)
      run_compose_single pull "-f ${INVEST}" "$@"
      ;;
    logs|ps|config)
      run_compose_single "${command}" "-f ${INVEST}" "$@"
      ;;
    *)
      echo "Unknown command: ${command}" >&2
      usage
      exit 1
      ;;
  esac
}

run_public_stack() {
  local command="$1"
  shift

  # Public = ghost + invest together. Both are separate projects.
  case "${command}" in
    up)
      run_compose_single up "-f ${GHOST}" -d "$@"
      run_compose_single up "-f ${INVEST}" -d "$@"
      ;;
    down|restart|rebuild)
      run_compose_single down "-f ${INVEST}" "$@"
      run_compose_single down "-f ${GHOST}" "$@"
      if [[ "${command}" == "restart" || "${command}" == "rebuild" ]]; then
        run_compose_single up "-f ${GHOST}" -d --force-recreate --remove-orphans "$@"
        run_compose_single up "-f ${INVEST}" -d --force-recreate --remove-orphans "$@"
      fi
      ;;
    pull)
      run_compose_single pull "-f ${GHOST}" "$@"
      run_compose_single pull "-f ${INVEST}" "$@"
      ;;
    logs|ps|config)
      echo "=== ghost project ==="
      run_compose_single "${command}" "-f ${GHOST}" "$@"
      echo -e "\n=== invest project ==="
      run_compose_single "${command}" "-f ${INVEST}" "$@"
      ;;
    *)
      echo "Unknown command: ${command}" >&2
      usage
      exit 1
      ;;
  esac
}

# Handle key management subcommand (doesn't follow the <command> <stack> pattern)
if [[ "${1:-}" == "key" ]]; then
  _litellm "${@:2}"
  exit $?
fi

if [[ $# -lt 2 ]]; then
  usage
  exit 1
fi

COMMAND="$1"
STACK="$2"
shift 2

do_dispatch() {
  local cmd="$COMMAND"
  local stk="$STACK"
  local files

  case "${stk}" in
    ai)
      run_ai_stack "${cmd}" "$@"
      ;;
    ghost|ghost-only)
      run_ghost_stack "${cmd}" "$@"
      ;;
    invest|invest-only)
      run_invest_stack "${cmd}" "$@"
      ;;
    public)
      run_public_stack "${cmd}" "$@"
      ;;
    monitoring|monitoring-only)
      # Monitoring is a standalone single-file project.
      case "${cmd}" in
        up)
          run_compose_single up "-f ${MONITORING}" -d "$@"
          ;;
        down|restart|rebuild)
          run_compose_single down "-f ${MONITORING}" "$@"
          if [[ "${cmd}" == "restart" || "${cmd}" == "rebuild" ]]; then
            run_compose_single up "-f ${MONITORING}" -d --force-recreate --remove-orphans "$@"
          fi
          ;;
        pull)
          run_compose_single pull "-f ${MONITORING}" "$@"
          ;;
        logs|ps|config)
          run_compose_single "${cmd}" "-f ${MONITORING}" "$@"
          ;;
        *)
          echo "Unknown command: ${cmd}" >&2
          usage
          exit 1
          ;;
      esac
      ;;
    mcp-only)
      case "${cmd}" in
        up)
          run_compose_single up "-f ${MCP}" -d "$@"
          ;;
        down|restart|rebuild)
          run_compose_single down "-f ${MCP}" "$@"
          if [[ "${cmd}" == "restart" || "${cmd}" == "rebuild" ]]; then
            run_compose_single up "-f ${MCP}" -d --build --force-recreate --remove-orphans "$@"
          fi
          ;;
        pull)
          run_compose_single pull "-f ${MCP}" "$@"
          ;;
        logs|ps|config)
          run_compose_single "${cmd}" "-f ${MCP}" "$@"
          ;;
        *)
          echo "Unknown command: ${cmd}" >&2
          usage
          exit 1
          ;;
      esac
      ;;
    skill-only)
      case "${cmd}" in
        up)
          run_compose_single up "-f ${SKILL_RUNNER}" -d "$@"
          ;;
        down|restart|rebuild)
          run_compose_single down "-f ${SKILL_RUNNER}" "$@"
          if [[ "${cmd}" == "restart" || "${cmd}" == "rebuild" ]]; then
            run_compose_single up "-f ${SKILL_RUNNER}" -d --build --force-recreate --remove-orphans "$@"
          fi
          ;;
        pull)
          run_compose_single pull "-f ${SKILL_RUNNER}" "$@"
          ;;
        logs|ps|config)
          run_compose_single "${cmd}" "-f ${SKILL_RUNNER}" "$@"
          ;;
        *)
          echo "Unknown command: ${cmd}" >&2
          usage
          exit 1
          ;;
      esac
      ;;
    all)
      case "${cmd}" in
        up)
          run_compose_single up "-f ${CORE}" -d "$@"
          run_compose_single up "-f ${EDGE}" -d "$@"
          run_compose_single up "-f ${GHOST}" -d "$@"
          run_compose_single up "-f ${INVEST}" -d "$@"
          run_compose_single up "-f ${AI_CORE}" -d "$@"
          run_compose_single up "-f ${MCP}" -d "$@"
          run_compose_single up "-f ${SKILL_RUNNER}" -d "$@"
          run_compose_single up "-f ${MONITORING}" -d "$@"
          ;;
        down|restart|rebuild)
          run_compose_single down "-f ${MONITORING}" "$@"
          run_compose_single down "-f ${SKILL_RUNNER}" "$@"
          run_compose_single down "-f ${MCP}" "$@"
          run_compose_single down "-f ${AI_CORE}" "$@"
          run_compose_single down "-f ${INVEST}" "$@"
          run_compose_single down "-f ${GHOST}" "$@"
          run_compose_single down "-f ${EDGE}" "$@"
          run_compose_single down "-f ${CORE}" "$@"
          if [[ "${cmd}" == "restart" ]]; then
            run_compose_single up "-f ${CORE}" -d; run_compose_single up "-f ${EDGE}" -d
            run_compose_single up "-f ${GHOST}" -d; run_compose_single up "-f ${INVEST}" -d
            run_compose_single up "-f ${AI_CORE}" -d; run_compose_single up "-f ${MCP}" -d
            run_compose_single up "-f ${SKILL_RUNNER}" -d
            run_compose_single up "-f ${MONITORING}" -d
          elif [[ "${cmd}" == "rebuild" ]]; then
            run_compose_single up "-f ${CORE}" -d --force-recreate --remove-orphans "$@"
            run_compose_single up "-f ${EDGE}" -d --force-recreate --remove-orphans "$@"
            run_compose_single up "-f ${GHOST}" -d --force-recreate --remove-orphans "$@"
            run_compose_single up "-f ${INVEST}" -d --force-recreate --remove-orphans "$@"
            run_compose_single up "-f ${AI_CORE}" -d --force-recreate --remove-orphans "$@"
            run_compose_single up "-f ${MCP}" -d --build --force-recreate --remove-orphans "$@"
            run_compose_single up "-f ${SKILL_RUNNER}" -d --build --force-recreate --remove-orphans "$@"
            run_compose_single up "-f ${MONITORING}" -d --force-recreate --remove-orphans "$@"
          fi
          ;;
        pull)
          for f in "${MONITORING}" "${SKILL_RUNNER}" "${MCP}" "${AI_CORE}" "${INVEST}" "${GHOST}" "${EDGE}" "${CORE}"; do
            run_compose_single pull "-f $f" "$@"
          done
          ;;
        logs|ps|config)
          for f in core edge ghost invest ai-core mcp skill-runner monitoring; do
            echo "=== $f ==="
            var_name=$(echo "$f" | tr '[:lower:]' '[:upper:]' | tr '-' '_')
            run_compose_single "${cmd}" "-f ${!var_name}" "$@"
          done
          ;;
      esac
      ;;
    all-n8n)
      case "${cmd}" in
        up)
          run_compose_single up "-f ${CORE}" -d "$@"
          run_compose_single up "-f ${EDGE}" -d "$@"
          run_compose_single up "-f ${GHOST}" -d "$@"
          run_compose_single up "-f ${INVEST}" -d "$@"
          run_compose_single up "-f ${AI_CORE}" -d "$@"
          run_compose_single up "-f ${MCP}" -d "$@"
          run_compose_single up "-f ${SKILL_RUNNER}" -d "$@"
          run_compose_single up "-f ${N8N}" -d "$@"
          run_compose_single up "-f ${MONITORING}" -d "$@"
          ;;
        down|restart|rebuild)
          run_compose_single down "-f ${MONITORING}" "$@"
          run_compose_single down "-f ${N8N}" "$@"
          run_compose_single down "-f ${SKILL_RUNNER}" "$@"
          run_compose_single down "-f ${MCP}" "$@"
          run_compose_single down "-f ${AI_CORE}" "$@"
          run_compose_single down "-f ${INVEST}" "$@"
          run_compose_single down "-f ${GHOST}" "$@"
          run_compose_single down "-f ${EDGE}" "$@"
          run_compose_single down "-f ${CORE}" "$@"
          if [[ "${cmd}" == "restart" ]]; then
            run_compose_single up "-f ${CORE}" -d; run_compose_single up "-f ${EDGE}" -d
            run_compose_single up "-f ${GHOST}" -d; run_compose_single up "-f ${INVEST}" -d
            run_compose_single up "-f ${AI_CORE}" -d; run_compose_single up "-f ${MCP}" -d
            run_compose_single up "-f ${SKILL_RUNNER}" -d
            run_compose_single up "-f ${N8N}" -d
            run_compose_single up "-f ${MONITORING}" -d
          elif [[ "${cmd}" == "rebuild" ]]; then
            run_compose_single up "-f ${CORE}" -d --force-recreate --remove-orphans "$@"
            run_compose_single up "-f ${EDGE}" -d --force-recreate --remove-orphans "$@"
            run_compose_single up "-f ${GHOST}" -d --force-recreate --remove-orphans "$@"
            run_compose_single up "-f ${INVEST}" -d --force-recreate --remove-orphans "$@"
            run_compose_single up "-f ${AI_CORE}" -d --force-recreate --remove-orphans "$@"
            run_compose_single up "-f ${MCP}" -d --build --force-recreate --remove-orphans "$@"
            run_compose_single up "-f ${SKILL_RUNNER}" -d --build --force-recreate --remove-orphans "$@"
            run_compose_single up "-f ${N8N}" -d --build --force-recreate --remove-orphans "$@"
            run_compose_single up "-f ${MONITORING}" -d --force-recreate --remove-orphans "$@"
          fi
          ;;
        pull)
          for f in "${MONITORING}" "${N8N}" "${SKILL_RUNNER}" "${MCP}" "${AI_CORE}" "${INVEST}" "${GHOST}" "${EDGE}" "${CORE}"; do
            run_compose_single pull "-f $f" "$@"
          done
          ;;
        logs|ps|config)
          for f in core edge ghost invest ai-core mcp skill-runner n8n monitoring; do
            echo "=== $f ==="
            var_name=$(echo "$f" | tr '[:lower:]' '[:upper:]' | tr '-' '_')
            run_compose_single "${cmd}" "-f ${!var_name}" "$@"
          done
          ;;
      esac
      ;;
    *)
      files="$(compose_files "${stk}")"
      if [[ "${cmd}" == "up" ]]; then
        # shellcheck disable=SC2086
        docker compose --env-file "${BASE_DIR}/.env" ${files} up -d "$@"
      elif [[ "${cmd}" == "rebuild" ]]; then
        # shellcheck disable=SC2086
        docker compose --env-file "${BASE_DIR}/.env" ${files} up -d --build --force-recreate --remove-orphans "$@"
      else
        # shellcheck disable=SC2086
        docker compose --env-file "${BASE_DIR}/.env" ${files} ${cmd} "$@"
      fi
      ;;
  esac
}

do_dispatch "$@"
