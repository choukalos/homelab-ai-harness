#!/usr/bin/env bash
# =====================================================================
# security-surface-weekly.sh — weekly public-surface check (SEC Phase 11).
#
# Two parts:
#   1. InvestHub DB schema-diff (spec 11.3, weekly): snapshot
#      information_schema of `investorhub` (tables, columns) + the app
#      DB user's privilege surface (schema_privileges) -> diff vs the
#      previous snapshot. ANY change = critical (P0: schema or
#      privilege change — catches malicious DDL and accidental drift
#      alike). First run captures the baseline (note, no diff).
#   2. Digest of the last 7 daily surface scans (same pattern as
#      scripts/security-digest-weekly.sh): per-day verdicts, totals,
#      recurring notes.
#
# Usage:
#   scripts/security-surface-weekly.sh                (paths from conf)
#   scripts/security-surface-weekly.sh --data-dir D   use D
#
# Writes (under the data dir, default /home/chuck/data/security-surface):
#   reports/security-surface-weekly-YYYY-Www.md
#   db-snapshots/investorhub-YYYY-MM-DD.txt
#   alerts.log  (schema-diff P0s appended, same line format as the daily)
#
# DB access: the app's own credential from ENV_FILE (INVEST_DATABASE_URL
# = mysql://user:pass@host:port/db). All queries are read-only
# (information_schema SELECTs). The password is passed via MYSQL_PWD
# (never on the command line, never in reports).
#
# Designed to run Sunday ~04:40 UTC (after the daily scan window) via a
# systemd timer at deploy.
# =====================================================================
set -euo pipefail
export LC_ALL=C

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONF="$SCRIPT_DIR/security-surface-scan.conf"
SEC_SURFACE_DATA_DIR=""
OBSERVATION_MODE=""
INVEST_DB_NAME=""
DB_HOST_FALLBACK=""
ENV_FILE=""
RETENTION_DAILY_DAYS=""
RETENTION_WEEKLY_WEEKS=""
DB_SNAPSHOT_RETENTION_WEEKS=""
if [[ -f "$CONF" ]]; then
  # shellcheck source=/dev/null
  . "$CONF"
fi
SEC_SURFACE_DATA_DIR="${SEC_SURFACE_DATA_DIR:-/home/chuck/data/security-surface}"
OBSERVATION_MODE="${OBSERVATION_MODE:-1}"
INVEST_DB_NAME="${INVEST_DB_NAME:-investorhub}"
DB_HOST_FALLBACK="${DB_HOST_FALLBACK:-}"
ENV_FILE="${ENV_FILE:-/home/chuck/homelab/.env}"
RETENTION_DAILY_DAYS="${RETENTION_DAILY_DAYS:-90}"
RETENTION_WEEKLY_WEEKS="${RETENTION_WEEKLY_WEEKS:-52}"
DB_SNAPSHOT_RETENTION_WEEKS="${DB_SNAPSHOT_RETENTION_WEEKS:-52}"

DATA_DIR="$SEC_SURFACE_DATA_DIR"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --data-dir) DATA_DIR="${2:?--data-dir needs a path}"; shift 2 ;;
    -h|--help) sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown arg: $1 (see --help)" >&2; exit 2 ;;
  esac
done

REPORTS_DIR="$DATA_DIR/reports"
SNAP_DIR="$DATA_DIR/db-snapshots"
ALERTS_LOG="$DATA_DIR/alerts.log"
NOW_TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
TODAY="$(date -u +%Y-%m-%d)"
WEEK="$(date -u +%G-W%V)"
OUT="$REPORTS_DIR/security-surface-weekly-$WEEK.md"
SNAP_FILE="$SNAP_DIR/investorhub-$TODAY.txt"
mkdir -p -m 755 "$REPORTS_DIR" "$SNAP_DIR"

# --- Findings (schema-diff P0s go to alerts.log) -------------------------
FINDINGS_DIR="$(mktemp -d /tmp/security-surface-weekly.XXXXXX)"
ANOMALIES="$FINDINGS_DIR/anomalies"
NOTES="$FINDINGS_DIR/notes"
: > "$ANOMALIES"; : > "$NOTES"
EVIDENCE_N=0
cleanup() { rm -rf "$FINDINGS_DIR"; }
trap cleanup EXIT

add_finding() {
  local sev="$1" check="$2" detail="$3"
  local evidence="${4:-}"
  EVIDENCE_N=$((EVIDENCE_N + 1))
  local evfile="$FINDINGS_DIR/evidence_$EVIDENCE_N.txt"
  if [[ -n "$evidence" ]]; then
    printf '%s\n' "$evidence" > "$evfile"
  fi
  printf '%s\t%s\t%s\t%s\n' "$sev" "$check" "$detail" "$EVIDENCE_N" >> \
    "$([[ $sev == critical || $sev == anomaly ]] && echo "$ANOMALIES" || echo "$NOTES")"
}

# --- DB connection (app credential from ENV_FILE) -------------------------
# INVEST_DATABASE_URL = mysql://user:pass@host:port/db
# The .env may hold a docker-compose template with unexpanded ${NAME}
# references (compose interpolates them when the container starts, so
# the running container sees the literal URL). Resolve any ${NAME} ref
# against ENV_FILE so the script works from either form; an unresolvable
# ref is left in place and the connection fails loudly (honest, never
# silent).
env_val() { # $1 = NAME -> value of NAME= in ENV_FILE (empty if absent)
  local line
  line="$(grep -m1 -E "^$1=" "$ENV_FILE" 2>/dev/null || true)"
  [[ -n "$line" ]] && printf '%s' "${line#*=}"
  return 0
}

DB_URL=""
if [[ -r "$ENV_FILE" ]]; then
  DB_URL="$(env_val INVEST_DATABASE_URL)"
  while [[ "$DB_URL" == *'${'*'}' ]]; do
    prefix="${DB_URL%%\$\{*}"
    rest="${DB_URL#"$prefix"}"
    name="${rest#\$\{}"
    name="${name%%\}*}"
    val="$(env_val "$name")"
    [[ -n "$val" ]] || break
    DB_URL="${DB_URL//\$\{$name\}/$val}"
  done
fi
DB_USER=""; DB_PASS=""; DB_HOST=""; DB_PORT="3306"; DB_NAME="$INVEST_DB_NAME"
if [[ "$DB_URL" == mysql://* ]]; then
  rest="${DB_URL#mysql://}"
  # Split on the LAST '@' so a password containing '@' still parses.
  cred="${rest%@*}"; hostpart="${rest##*@}"
  DB_USER="${cred%%:*}"; DB_PASS="${cred#*:}"
  DB_HOST="${hostpart%%:*}"
  if [[ "$hostpart" == *:* ]]; then
    DB_PORT="${hostpart#*:}"
    DB_PORT="${DB_PORT%%/*}"
  fi
  DB_NAME="${hostpart##*/}"
  [[ "$DB_NAME" == "$hostpart" ]] && DB_NAME="$INVEST_DB_NAME"
fi

db_query() { # $1 = SQL -> stdout (read-only)
  MYSQL_PWD="$DB_PASS" mysql -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" \
    -N -B -e "$1" 2>&1
}

# --- Part 1: schema-diff ---------------------------------------------------
SCHEMA_STATUS="SKIPPED"
SCHEMA_DETAIL=""
DIFF_TEXT=""

take_snapshot() {
  local sql="
SELECT CONCAT('TABLE:', table_name)
  FROM information_schema.tables
 WHERE table_schema = '$DB_NAME'
UNION ALL
SELECT CONCAT('COLUMN:', table_name, ':', column_name, ':', column_type, ':nullable=', is_nullable)
  FROM information_schema.columns
 WHERE table_schema = '$DB_NAME'
UNION ALL
SELECT CONCAT('PRIV:', grantee, ':', privilege_type)
  FROM information_schema.schema_privileges
ORDER BY 1;"
  local body
  if ! body="$(db_query "$sql")"; then
    printf '%s\n' "$body" >&2
    return 1
  fi
  {
    echo "# captured: $NOW_TS"
    echo "# db: $DB_NAME @ $DB_HOST:$DB_PORT (app user $DB_USER)"
    printf '%s\n' "$body"
  }
}

# Previous snapshot: newest file strictly older than today's (or any
# other file if today's already exists from a re-run).
prev_snapshot() {
  local f
  f="$(ls -1 "$SNAP_DIR"/investorhub-*.txt 2>/dev/null | grep -v "investorhub-$TODAY.txt" | sort | tail -n 1 || true)"
  [[ -n "$f" ]] && printf '%s' "$f"
  return 0
}

check_schema_diff() {
  if [[ -z "$DB_USER" || -z "$DB_HOST" ]]; then
    add_finding anomaly db-schema-diff "INVEST_DATABASE_URL missing/unreadable in $ENV_FILE — schema-diff skipped"
    SCHEMA_STATUS="SKIPPED"
    return 0
  fi
  local body
  if ! body="$(db_query "SELECT 1;")" 2>/dev/null; then
    # Host-side fallback: thor.local is IPv6-only on the host while MySQL
    # binds the LAN IPv4 (see conf DB_HOST_FALLBACK). Retry once with the
    # fallback; report both attempts if it also fails.
    if [[ -n "$DB_HOST_FALLBACK" && "$DB_HOST_FALLBACK" != "$DB_HOST" ]]; then
      local primary_err="$body"
      DB_HOST="$DB_HOST_FALLBACK"
      if body="$(db_query "SELECT 1;")" 2>/dev/null; then
        add_finding note db-schema-diff "connected via fallback host $DB_HOST (primary host unreachable from the host — expected: thor.local resolves IPv6-only on the host)"
      else
        add_finding anomaly db-schema-diff "cannot connect to $DB_NAME @ $DB_HOST:$DB_PORT (app user $DB_USER) — schema-diff skipped" "db probe (fallback $DB_HOST): $body; primary: $primary_err"
        SCHEMA_STATUS="UNREACHABLE"
        return 0
      fi
    else
      add_finding anomaly db-schema-diff "cannot connect to $DB_NAME @ $DB_HOST:$DB_PORT (app user $DB_USER) — schema-diff skipped" "db probe: $body"
      SCHEMA_STATUS="UNREACHABLE"
      return 0
    fi
  fi
  take_snapshot > "$SNAP_FILE" 2>"$FINDINGS_DIR/snap.err" || {
    add_finding anomaly db-schema-diff "snapshot query failed — schema-diff incomplete" "$(cat "$FINDINGS_DIR/snap.err" 2>/dev/null || true)"
    rm -f "$SNAP_FILE"
    SCHEMA_STATUS="FAILED"
    return 0
  }
  local prev
  prev="$(prev_snapshot)"
  if [[ -z "$prev" ]]; then
    add_finding note db-schema-diff "baseline captured (first snapshot) — no diff yet; next run diffs against $SNAP_FILE" "snapshot: $SNAP_FILE ($(wc -l < "$SNAP_FILE") lines)"
    SCHEMA_STATUS="BASELINE CAPTURED"
    SCHEMA_DETAIL="$SNAP_FILE"
    return 0
  fi
  # Diff the data lines (skip the two '# ' header lines on each side).
  DIFF_TEXT="$(diff -u \
      <(grep -v '^# ' "$prev" | sort) \
      <(grep -v '^# ' "$SNAP_FILE" | sort) || true)"
  if [[ -n "$DIFF_TEXT" ]]; then
    local n
    n="$(printf '%s\n' "$DIFF_TEXT" | grep -cE '^[+-][^+-]' || true)"
    add_finding critical db-schema-diff "SCHEMA/PRIVILEGE CHANGE on $DB_NAME: $n line(s) differ vs $prev (P0 — malicious DDL or accidental drift)" "$DIFF_TEXT"
    SCHEMA_STATUS="CHANGED ($n lines)"
    SCHEMA_DETAIL="$prev"
  else
    SCHEMA_STATUS="UNCHANGED"
    SCHEMA_DETAIL="$prev"
  fi
  return 0
}

# --- Part 2: digest of the last 7 daily surface scans ----------------------
mapfile -t REPORTS < <(ls -1 "$REPORTS_DIR"/security-surface-report-*.md 2>/dev/null | sort | tail -7 || true)

report_date() { basename "$1" | sed -E 's/^security-surface-report-([0-9-]+)\.md$/\1/'; }
report_verdict() { grep -m1 '^verdict: ' "$1" 2>/dev/null | sed 's/^verdict: //' || true; }
report_anoms() { grep -cE '^### \[(anomaly|critical)\]' "$1" 2>/dev/null || true; }
report_notes() { grep -cE '^### \[note\]' "$1" 2>/dev/null || true; }

recurring_notes() { # $@ = report files
  local r
  for r in "$@"; do
    [[ -f "$r" ]] || continue
    grep -E '^### \[note\] ' "$r" 2>/dev/null | sed -E 's/^### \[note\] ([^:]+):.*/\1/'
  done | sort | uniq -c | awk '$1 >= 2 { printf "%s %s\n", $1, $2 }' | sort -rn
}

main() {
  check_schema_diff

  local n_anom n_note
  n_anom="$(wc -l < "$ANOMALIES")"
  n_note="$(wc -l < "$NOTES")"
  local verdict
  if [[ $n_anom -eq 0 && $n_note -eq 0 ]]; then
    verdict="CLEAN"
  elif [[ $n_note -eq 0 ]]; then
    verdict="$n_anom anomalies"
  elif [[ $n_anom -eq 0 ]]; then
    verdict="$n_note notes"
  else
    verdict="$n_anom anomalies, $n_note notes"
  fi

  # alerts.log (anomalies only, same line format as the daily scan)
  local sev check detail evn
  while IFS=$'\t' read -r sev check detail evn; do
    [[ -n "$sev" ]] || continue
    printf '%s | %s | %s | %s\n' "$NOW_TS" "$sev" "$check" "$detail" >> "$ALERTS_LOG"
  done < "$ANOMALIES"

  {
    echo "# Public Surface Weekly Digest — $WEEK"
    echo
    echo "- generated: $NOW_TS"
    echo "- mode: $([[ $OBSERVATION_MODE == 1 ]] && echo "observation (report only, nothing escalated)" || echo "active")"
    echo "- daily reports covered: ${#REPORTS[@]} (last 7 by date)"
    echo "- verdict: $verdict"
    echo
    echo "verdict: $verdict"
    echo
    echo "## InvestHub DB schema-diff ($DB_NAME)"
    echo
    echo "- status: $SCHEMA_STATUS"
    if [[ -n "$SCHEMA_DETAIL" ]]; then
      echo "- reference: $SCHEMA_DETAIL"
    fi
    if [[ "$SCHEMA_STATUS" == CHANGED* ]]; then
      echo
      echo '```'
      printf '%s\n' "$DIFF_TEXT"
      echo '```'
    fi
    echo
    echo "## Anomalies ($n_anom)"
    echo
    if [[ $n_anom -eq 0 ]]; then
      echo "(none)"
      echo
    else
      local sev2 check2 detail2 evn2
      while IFS=$'\t' read -r sev2 check2 detail2 evn2; do
        [[ -n "$sev2" ]] || continue
        printf '### [%s] %s: %s\n\n' "$sev2" "$check2" "$detail2"
        if [[ -n "$evn2" && -f "$FINDINGS_DIR/evidence_$evn2.txt" ]]; then
          printf '```\n%s\n```\n\n' "$(cat "$FINDINGS_DIR/evidence_$evn2.txt")"
        else
          printf '\n'
        fi
      done < "$ANOMALIES"
    fi
    echo "## Notes ($n_note)"
    echo
    if [[ $n_note -eq 0 ]]; then
      echo "(none)"
      echo
    else
      local sev2 check2 detail2 evn2
      while IFS=$'\t' read -r sev2 check2 detail2 evn2; do
        [[ -n "$sev2" ]] || continue
        printf '### [%s] %s: %s\n\n' "$sev2" "$check2" "$detail2"
        if [[ -n "$evn2" && -f "$FINDINGS_DIR/evidence_$evn2.txt" ]]; then
          printf '```\n%s\n```\n\n' "$(cat "$FINDINGS_DIR/evidence_$evn2.txt")"
        else
          printf '\n'
        fi
      done < "$NOTES"
    fi
    echo "## Daily verdicts (last 7)"
    echo
    echo "| date | verdict | anomalies | notes |"
    echo "|---|---|---|---|"
    if [[ ${#REPORTS[@]} -eq 0 ]]; then
      echo "| (none yet) | - | - | - |"
    else
      local r d v a t
      for r in "${REPORTS[@]}"; do
        d="$(report_date "$r")"
        v="$(report_verdict "$r")"
        a="$(report_anoms "$r")"
        t="$(report_notes "$r")"
        echo "| $d | ${v:-?} | $a | $t |"
      done
    fi
    echo
    if [[ ${#REPORTS[@]} -gt 0 ]]; then
      echo "## Recurring notes (seen on >=2 days)"
      echo
      local rec
      rec="$(recurring_notes "${REPORTS[@]}")"
      if [[ -n "$rec" ]]; then
        local line
        while IFS= read -r line; do
          [[ -n "$line" ]] || continue
          echo "- ${line#* }: ${line%% *} day(s)"
        done < <(printf '%s\n' "$rec")
      else
        echo "(none)"
      fi
      echo
    fi
  } > "$OUT"

  # retention (same policy as the daily scan)
  find "$REPORTS_DIR" -name 'security-surface-report-*.md' -mtime +"$RETENTION_DAILY_DAYS" -delete 2>/dev/null || true
  find "$REPORTS_DIR" -name 'security-surface-weekly-*.md' -mtime +"$((RETENTION_WEEKLY_WEEKS * 7))" -delete 2>/dev/null || true
  local -a old_snaps=()
  mapfile -t old_snaps < <(find "$SNAP_DIR" -name 'investorhub-*.txt' -mtime +"$((DB_SNAPSHOT_RETENTION_WEEKS * 7))" 2>/dev/null | sort || true)
  local newest s
  newest="$(ls -1t "$SNAP_DIR" 2>/dev/null | head -n 1 || true)"
  for s in "${old_snaps[@]:-}"; do
    [[ -z "$s" ]] && continue
    [[ "$s" == "$SNAP_DIR/$newest" ]] && continue
    rm -f "$s"
  done

  echo "weekly check complete: verdict=$verdict (schema-diff: $SCHEMA_STATUS)"
  echo "  digest:   $OUT"
  echo "  snapshot: $SNAP_FILE"
  echo "  alerts:   $ALERTS_LOG (+$n_anom)"
}

main
