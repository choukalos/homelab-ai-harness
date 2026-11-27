#!/usr/bin/env bash
# =====================================================================
# security-digest-weekly.sh — weekly digest of the last 7 daily scans.
#
# SEC Phase 10: summarizes the last 7 daily reports (security-scan.sh)
# into /home/chuck/data/security/reports/security-weekly-YYYY-Www.md:
# per-day verdicts, totals, recurring notes (>=2 days), and auth.log
# trends (failed logins from known IPs, this week vs last week when
# 14 days of reports exist).
#
# Usage:
#   scripts/security-digest-weekly.sh                (paths from conf)
#   scripts/security-digest-weekly.sh --data-dir D   use D
#
# Designed to run Sunday ~04:30 UTC via security-digest-weekly.timer
# (installed by scripts/security-install-timers.sh at deploy).
# =====================================================================
set -euo pipefail
export LC_ALL=C

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONF="$SCRIPT_DIR/security-scan.conf"
SEC_DATA_DIR=""
if [[ -f "$CONF" ]]; then
  # shellcheck source=/dev/null
  . "$CONF"
fi
DATA_DIR="${SEC_DATA_DIR:-/home/chuck/data/security}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --data-dir) DATA_DIR="${2:?--data-dir needs a path}"; shift 2 ;;
    -h|--help) sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown arg: $1 (see --help)" >&2; exit 2 ;;
  esac
done

REPORTS_DIR="$DATA_DIR/reports"
NOW_TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
WEEK="$(date -u +%G-W%V)"
OUT="$REPORTS_DIR/security-weekly-$WEEK.md"
mkdir -p -m 755 "$REPORTS_DIR"

# Last 7 daily reports, oldest first (filename date sorts).
mapfile -t REPORTS < <(ls -1 "$REPORTS_DIR"/security-report-*.md 2>/dev/null | sort | tail -7 || true)
# Previous 7 (for the week-over-week auth trend), oldest first.
mapfile -t PREV_REPORTS < <(ls -1 "$REPORTS_DIR"/security-report-*.md 2>/dev/null | sort | tail -14 | head -7 || true)

report_date() { basename "$1" | sed -E 's/^security-report-([0-9-]+)\.md$/\1/'; }
report_verdict() { grep -m1 '^verdict: ' "$1" 2>/dev/null | sed 's/^verdict: //' || true; }
report_anoms() { grep -cE '^### \[(anomaly|critical)\]' "$1" 2>/dev/null || true; }
report_notes() { grep -cE '^### \[note\]' "$1" 2>/dev/null || true; }

# Sum auth-known counts (ip=count pairs) across a set of reports.
auth_totals() { # $@ = report files
  local -A totals=()
  local r line ip cnt
  for r in "$@"; do
    [[ -f "$r" ]] || continue
    line="$(grep -m1 '^auth-known: ' "$r" 2>/dev/null | sed 's/^auth-known: //' || true)"
    for tok in $line; do
      [[ "$tok" == *=* ]] || continue
      ip="${tok%%=*}"; cnt="${tok#*=}"
      totals["$ip"]=$(( ${totals["$ip"]:-0} + cnt ))
    done
  done
  printf '%s\n' "${!totals[@]}" 2>/dev/null | sort | while IFS= read -r ip; do
    [[ -n "$ip" ]] || continue
    echo "$ip ${totals[$ip]}"
  done
}

# Recurring notes: note check-names appearing on >=2 distinct days.
recurring_notes() { # $@ = report files
  local r
  for r in "$@"; do
    [[ -f "$r" ]] || continue
    grep -E '^### \[note\] ' "$r" 2>/dev/null | sed -E 's/^### \[note\] ([^:]+):.*/\1/'
  done | sort | uniq -c | awk '$1 >= 2 { printf "%s %s\n", $1, $2 }' | sort -rn
}

{
  echo "# Security Weekly Digest — $WEEK"
  echo
  echo "- generated: $NOW_TS"
  echo "- reports covered: ${#REPORTS[@]} (daily scans, last 7 by date)"
  echo
  if (( ${#REPORTS[@]} == 0 )); then
    echo "_No daily reports found in $REPORTS_DIR — run scripts/security-scan.sh first._"
    exit 0
  fi

  echo "## Daily verdicts"
  echo
  echo "| date | verdict | anomalies | notes |"
  echo "|---|---|---|---|"
  total_anom=0
  total_note=0
  for r in "${REPORTS[@]}"; do
    d="$(report_date "$r")"
    v="$(report_verdict "$r")"
    a="$(report_anoms "$r")"
    n="$(report_notes "$r")"
    total_anom=$(( total_anom + a ))
    total_note=$(( total_note + n ))
    echo "| $d | ${v:-?} | $a | $n |"
  done
  echo
  echo "## Totals (last 7 days)"
  echo
  echo "- anomalies: $total_anom"
  echo "- notes: $total_note"
  echo
  echo "## Recurring notes (seen on >=2 days)"
  echo
  rec="$(recurring_notes "${REPORTS[@]}")"
  if [[ -n "$rec" ]]; then
    while IFS= read -r line; do
      [[ -n "$line" ]] || continue
      echo "- ${line#* }: ${line%% *} day(s)"
    done < <(printf '%s\n' "$rec")
  else
    echo "(none)"
  fi
  echo
  echo "## auth.log trends (failed logins from known IPs)"
  echo
  this_week="$(auth_totals "${REPORTS[@]}")"
  if [[ -n "$this_week" ]]; then
    prev_totals="$(auth_totals "${PREV_REPORTS[@]}")"
    while IFS= read -r line; do
      [[ -n "$line" ]] || continue
      ip="${line%% *}"; cnt="${line#* }"
      p="$(printf '%s\n' "$prev_totals" | awk -v i="$ip" '$1 == i { print $2 }')"
      if [[ -n "$p" ]]; then
        echo "- $ip: $cnt this week ($p last week)"
      else
        echo "- $ip: $cnt this week (0 last week)"
      fi
    done < <(printf '%s\n' "$this_week")
  else
    echo "(none)"
  fi
} > "$OUT"

echo "weekly digest written: $OUT (${#REPORTS[@]} daily reports covered)"
