#!/usr/bin/env bash
# =====================================================================
# security-baseline.sh — capture the host's known-good security state.
#
# SEC Phase 10 (security_todo.md §Phase 10): the daily scan
# (scripts/security-scan.sh) diffs live host state against the baseline
# this script writes. Drift IS the signal, so the baseline is refreshed
# ONLY by an explicit --update after an intentional change — a plain run
# never rewrites the file (auto-refresh would defeat the diff).
#
# Usage:
#   scripts/security-baseline.sh            status: report the current
#                                             baseline (read-only)
#   scripts/security-baseline.sh --update   capture + (re)write baseline
#   scripts/security-baseline.sh --show     print the current baseline
#   scripts/security-baseline.sh --file P   use P instead of the default
#
# Best run as root: /var/spool/cron/crontabs is root-only; a non-root
# capture marks those entries UNREADABLE (honest, never silent).
#
# Writes: only the baseline file (default
# /home/chuck/data/security/baseline.txt; parent dir created 755).
# Everything else is read-only (ss, getent, sha256sum, systemctl
# list-timers, docker ps -a, command -v).
#
# Baseline format (v1): header + 7 sections, stable line-oriented
# blocks for easy diffing:
#   header          capture timestamp (UTC) + host + uid
#   == LISTENERS == proto local-addr:port process (normalized from
#                   ss -tlnp; PIDs stripped — they churn on restarts)
#   == USERS ==     passwd lines, UID >= 1000 (the nobody pseudo-account,
#                   uid 65534, is excluded: system account, not a login)
#   == CRON ==      FILE <path> <sha256> | UNREADABLE <path> | MISSING/EMPTY
#   == TIMERS ==    timer unit names (systemctl list-timers --all)
#   == CONTAINERS == name<TAB>image (docker ps -a)
#   == MAIL_TOOLS == FOUND/ABSENT per watchlist binary (watchlist comes
#                    from security-scan.conf; expected: none present)
# =====================================================================
set -euo pipefail

DEFAULT_BASELINE="/home/chuck/data/security/baseline.txt"
BASELINE_FILE="$DEFAULT_BASELINE"
MODE="status"
TMP_FILE=""

cleanup() {
  if [[ -n "$TMP_FILE" ]]; then
    rm -f "$TMP_FILE"
  fi
}
trap cleanup EXIT

usage() {
  sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --update) MODE="update"; shift ;;
    --show)   MODE="show"; shift ;;
    --file)
      shift
      BASELINE_FILE="${1:?--file needs a path}"
      shift
      ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown arg: $1 (see --help)" >&2; exit 2 ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONF="$SCRIPT_DIR/security-scan.conf"
if [[ -f "$CONF" ]]; then
  # shellcheck source=/dev/null
  . "$CONF"
fi
# Mail-tool watchlist (spec default if the conf is absent or empty).
if [[ -z "${MAIL_TOOLS[*]:-}" ]]; then
  MAIL_TOOLS=(sendmail msmtp ssmtp mail mutt swaks postfix)
fi

status() {
  if [[ ! -f "$BASELINE_FILE" ]]; then
    echo "no baseline at $BASELINE_FILE"
    echo "capture one: scripts/security-baseline.sh --update"
    return 1
  fi
  local ts
  ts="$(sed -nE 's/^# captured: //p' "$BASELINE_FILE" | head -n 1)"
  echo "baseline: $BASELINE_FILE"
  echo "captured: ${ts:-unknown}"
  echo "modified: $(date -u -r "$BASELINE_FILE" +%Y-%m-%dT%H:%M:%SZ)"
  echo "size:     $(wc -c < "$BASELINE_FILE") bytes"
  echo "refresh:  only via --update (after an intentional change)"
}

# Emit one CRON line for a single file: FILE/UNREADABLE/MISSING.
cron_file() {
  if [[ -r "$1" ]]; then
    echo "FILE $1 $(sha256sum "$1" | awk '{print $1}')"
  elif [[ -e "$1" ]]; then
    echo "UNREADABLE $1"
  else
    echo "MISSING $1"
  fi
}

# Emit one CRON line per file in a directory (or MISSING/EMPTY/UNREADABLE).
cron_dir() {
  local f n=0
  if [[ ! -d "$1" ]]; then
    echo "MISSING $1"
    return 0
  fi
  # A directory we cannot read (e.g. /var/spool/cron/crontabs as non-root)
  # must be marked UNREADABLE, not EMPTY — an empty-but-unreadable dir would
  # hide crontabs from the diff (honest, never silent).
  if [[ ! -r "$1" ]]; then
    echo "UNREADABLE $1"
    return 0
  fi
  for f in "$1"/*; do
    [[ -e "$f" ]] || continue
    n=1
    cron_file "$f"
  done
  if [[ $n -eq 0 ]]; then
    echo "EMPTY $1"
  fi
}

capture() {
  local dir
  dir="$(dirname "$BASELINE_FILE")"
  mkdir -p -m 755 "$dir"
  TMP_FILE="$(mktemp "$dir/.baseline.XXXXXX")"

  {
    echo "# security-baseline v1"
    echo "# host: $(hostname)"
    echo "# captured: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "# captured-as: uid=$(id -u) ($(id -un))"
    echo "# source: scripts/security-baseline.sh --update"
    echo "# note: LISTENERS normalized from 'ss -tlnp' (PIDs stripped);"
    echo "#       USERS excludes the nobody pseudo-account (uid 65534)."
    echo
    echo "== LISTENERS =="
    local listeners
    if listeners="$(ss -tlnp 2>/dev/null)"; then
      printf '%s\n' "$listeners" | awk 'NR > 1 {
        proc = "-"
        if (match($0, /users:\(\("/)) {
          s = substr($0, RSTART + 8)
          q = index(substr(s, 2), "\"")
          proc = (q > 0) ? substr(s, 2, q - 1) : substr(s, 2)
        }
        print $1, $4, proc
      }'
    else
      echo "UNAVAILABLE ss"
    fi
    echo
    echo "== USERS =="
    # UID >= 1000, excluding the nobody pseudo-account (65534, nologin).
    getent passwd | awk -F: '$3 >= 1000 && $1 != "nobody"'
    echo
    echo "== CRON =="
    cron_file /etc/crontab
    cron_dir /etc/cron.d
    cron_dir /var/spool/cron/crontabs
    echo
    echo "== TIMERS =="
    local timers
    timers="$(systemctl list-timers --all --no-pager --no-legend --plain 2>/dev/null || true)"
    if [[ -n "$timers" ]]; then
      printf '%s\n' "$timers" | awk '{ print $(NF - 1) }' | sort -u
    else
      echo "UNAVAILABLE systemctl list-timers"
    fi
    echo
    echo "== CONTAINERS =="
    local containers
    if containers="$(docker ps -a --format '{{.Names}}\t{{.Image}}' 2>/dev/null)"; then
      printf '%s\n' "$containers" | sort
    else
      echo "UNAVAILABLE docker"
    fi
    echo
    echo "== MAIL_TOOLS =="
    local t p
    for t in "${MAIL_TOOLS[@]}"; do
      if p="$(command -v "$t" 2>/dev/null)"; then
        echo "FOUND $t $p"
      else
        echo "ABSENT $t"
      fi
    done
  } > "$TMP_FILE"

  chmod 644 "$TMP_FILE"
  mv "$TMP_FILE" "$BASELINE_FILE"
  TMP_FILE=""
  echo "baseline written: $BASELINE_FILE ($(wc -c < "$BASELINE_FILE") bytes, captured $(sed -nE 's/^# captured: //p' "$BASELINE_FILE")))"
}

case "$MODE" in
  status)
    status
    ;;
  update)
    capture
    ;;
  show)
    if [[ ! -f "$BASELINE_FILE" ]]; then
      echo "no baseline at $BASELINE_FILE (run --update first)" >&2
      exit 1
    fi
    cat "$BASELINE_FILE"
    ;;
esac
