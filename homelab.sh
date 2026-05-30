#!/usr/bin/env bash
set -euo pipefail

BASE_DIR="/home/chuck/homelab"
COMPOSE_DIR="${BASE_DIR}/compose"

CORE="${COMPOSE_DIR}/compose.core.yml"
EDGE="${COMPOSE_DIR}/compose.edge.yml"
GHOST="${COMPOSE_DIR}/compose.ghost.yml"
AI="${COMPOSE_DIR}/compose.ai-core.yml"
HARNESS="${COMPOSE_DIR}/compose.ai-harness.yml"
INVEST="${COMPOSE_DIR}/compose.invest-hub.yml"
N8N="${COMPOSE_DIR}/compose.n8n.yml"

cd "${BASE_DIR}"

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

Stacks:
  core        Caddy only
  edge        Caddy + Cloudflare Tunnel
  ghost       Caddy + Cloudflare Tunnel + Ghost
  ai          Caddy + AI stack + Harness
  invest      Caddy + Cloudflare Tunnel + Invest Hub
  public      Caddy + Cloudflare Tunnel + Ghost + Invest Hub
  n8n         Caddy + n8n
  all         Everything except n8n
  all-n8n     Everything including n8n

  core-only
  edge-only
  ghost-only
  harness-only
  ai-only
  invest-only
  n8n-only

Examples:
  ./homelab.sh up ai
  ./homelab.sh down ai
  ./homelab.sh restart invest
  ./homelab.sh logs ai -f
  ./homelab.sh pull invest
  ./homelab.sh up invest --pull always
  ./homelab.sh config public
  ./homelab.sh rebuild harness-only
EOF
}

compose_files() {
  local stack="$1"

  case "${stack}" in
    core)
      echo "-f ${CORE}"
      ;;

    edge)
      echo "-f ${CORE} -f ${EDGE}"
      ;;

    ghost)
      echo "-f ${CORE} -f ${EDGE} -f ${GHOST}"
      ;;

    ai)
      echo "-f ${CORE} -f ${AI} -f ${HARNESS}"
      ;;

    invest)
      echo "-f ${CORE} -f ${EDGE} -f ${INVEST}"
      ;;

    public)
      echo "-f ${CORE} -f ${EDGE} -f ${GHOST} -f ${INVEST}"
      ;;

    n8n)
      echo "-f ${CORE} -f ${N8N}"
      ;;

    all)
      echo "-f ${CORE} -f ${EDGE} -f ${GHOST} -f ${INVEST} -f ${AI} -f ${HARNESS}"
      ;;

    all-n8n)
      echo "-f ${CORE} -f ${EDGE} -f ${GHOST} -f ${INVEST} -f ${AI} -f ${HARNESS} -f ${N8N}"
      ;;

    core-only)
      echo "-f ${CORE}"
      ;;

    edge-only)
      echo "-f ${EDGE}"
      ;;

    ghost-only)
      echo "-f ${GHOST}"
      ;;

    ai-only)
      echo "-f ${AI}"
      ;;

    harness-only)
      echo "-f ${HARNESS}"
      ;;

    invest-only)
      echo "-f ${INVEST}"
      ;;

    n8n-only)
      echo "-f ${N8N}"
      ;;

    *)
      echo "Unknown stack: ${stack}" >&2
      usage
      exit 1
      ;;
  esac
}

run_compose() {
  local command="$1"
  local stack="$2"
  shift 2

  local files
  files="$(compose_files "${stack}")"

  echo "Running: docker compose ${files} ${command} $*"

  # shellcheck disable=SC2086
  docker compose --env-file "${BASE_DIR}/.env" ${files} ${command} "$@"
}

if [[ $# -lt 2 ]]; then
  usage
  exit 1
fi

COMMAND="$1"
STACK="$2"
shift 2

case "${COMMAND}" in
  up)
    run_compose up "${STACK}" -d "$@"
    ;;

  down)
    run_compose down "${STACK}" "$@"
    ;;

  restart)
    run_compose down "${STACK}" "$@"
    run_compose up "${STACK}" -d
    ;;

  rebuild)
    run_compose up "${STACK}" -d --build --force-recreate --remove-orphans "$@"
    ;;

  pull)
    run_compose pull "${STACK}" "$@"
    ;;

  logs)
    run_compose logs "${STACK}" "$@"
    ;;

  ps)
    run_compose ps "${STACK}" "$@"
    ;;

  config)
    run_compose config "${STACK}" "$@"
    ;;

  *)
    echo "Unknown command: ${COMMAND}" >&2
    usage
    exit 1
    ;;
esac


