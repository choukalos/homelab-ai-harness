#!/usr/bin/env bash
# =====================================================================
# security-scan.sh — daily baseline-diff security scan (SEC Phase 10).
#
# Diffs live host state against the baseline written by
# scripts/security-baseline.sh and reports deviations. Drift IS the
# signal: a new listener, a new UID>=1000 user, a new crontab, a new
# container, a mail binary appearing, outbound SMTP — each is a finding.
#
# Usage:
#   scripts/security-scan.sh                full scan (paths from conf)
#   scripts/security-scan.sh --data-dir D   use D (baseline at D/baseline.txt,
#                                           reports/alerts/metrics under D)
#   scripts/security-scan.sh --baseline F   use baseline file F
#   scripts/security-scan.sh --no-prune     skip retention pruning (testing)
#
# Writes (under the data dir, default /home/chuck/data/security):
#   reports/security-report-YYYY-MM-DD.md   daily report (overwrites today's)
#   alerts.log                              one line per ANOMALY, appended:
#                                           ts | severity | check | detail
#   metrics/security_scan.prom              Prometheus textfile metrics
# Everything else is read-only. Best run as root (auth.log, cron spool,
# full ss process info); a non-root run marks unreadable sources
# UNREADABLE and skips them — honest, never silent.
#
# Observation mode (OBSERVATION_MODE=1 in security-scan.conf, first 2
# weeks): findings are reported but nothing is escalated. Flipping to 0
# is a config edit, not a code change.
# =====================================================================
set -euo pipefail

# Byte-order collation for sort/comm/grep: locale collation breaks comm's
# "sorted input" assumption and makes diff results locale-dependent.
# All output here is machine-oriented (reports, logs, metrics).
export LC_ALL=C

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONF="$SCRIPT_DIR/security-scan.conf"
# Pre-declare the conf arrays so ${#arr[@]} is safe under set -u whether or
# not the conf exists / sets them.
KNOWN_IPS=()
SMTP_PORTS=()
MAIL_TOOLS=()
CDN_CIDRS=()
NOISE_PATTERNS=()
if [[ -f "$CONF" ]]; then
  # shellcheck source=/dev/null
  . "$CONF"
fi

SEC_DATA_DIR="${SEC_DATA_DIR:-/home/chuck/data/security}"
DATA_DIR="$SEC_DATA_DIR"
BASELINE_FILE=""
PRUNE=1
OBSERVATION_MODE="${OBSERVATION_MODE:-1}"
BASELINE_STALE_DAYS="${BASELINE_STALE_DAYS:-30}"
# Defaults if the conf is absent (or omits them).
if [[ ${#KNOWN_IPS[@]} -eq 0 ]]; then
  KNOWN_IPS=(10.8.0.2 192.168.4.0/24 192.168.5.0/24)
fi
if [[ ${#SMTP_PORTS[@]} -eq 0 ]]; then
  SMTP_PORTS=(25 465 587)
fi
if [[ ${#MAIL_TOOLS[@]} -eq 0 ]]; then
  MAIL_TOOLS=(sendmail msmtp ssmtp mail mutt swaks postfix)
fi
if [[ ${#CDN_CIDRS[@]} -eq 0 ]]; then
  CDN_CIDRS=()
fi
if [[ ${#NOISE_PATTERNS[@]} -eq 0 ]]; then
  NOISE_PATTERNS=()
fi
RETENTION_DAILY_DAYS="${RETENTION_DAILY_DAYS:-90}"
RETENTION_WEEKLY_WEEKS="${RETENTION_WEEKLY_WEEKS:-52}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --data-dir) DATA_DIR="${2:?--data-dir needs a path}"; shift 2 ;;
    --baseline) BASELINE_FILE="${2:?--baseline needs a path}"; shift 2 ;;
    --no-prune) PRUNE=0; shift ;;
    -h|--help) sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown arg: $1 (see --help)" >&2; exit 2 ;;
  esac
done
[[ -n "$BASELINE_FILE" ]] || BASELINE_FILE="$DATA_DIR/baseline.txt"

REPORTS_DIR="$DATA_DIR/reports"
ALERTS_LOG="$DATA_DIR/alerts.log"
METRICS_DIR="$DATA_DIR/metrics"
METRICS_FILE="$METRICS_DIR/security_scan.prom"
TODAY="$(date -u +%Y-%m-%d)"
NOW_TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
NOW_EPOCH="$(date -u +%s)"
REPORT_FILE="$REPORTS_DIR/security-report-$TODAY.md"

# --- Findings bookkeeping ---------------------------------------------
# Each finding: severity<TAB>check<TAB>detail in ANOMALIES/NOTES,
# evidence in $FINDINGS_DIR/evidence_NN.txt (referenced by index).
FINDINGS_DIR="$(mktemp -d /tmp/security-scan.XXXXXX)"
ANOMALIES="$FINDINGS_DIR/anomalies"
NOTES="$FINDINGS_DIR/notes"
: > "$ANOMALIES"; : > "$NOTES"
EVIDENCE_N=0
SUPPRESSED=0

cleanup() { rm -rf "$FINDINGS_DIR"; }
trap cleanup EXIT

# add_finding SEVERITY CHECK DETAIL [EVIDENCE...]
add_finding() {
  local sev="$1" check="$2" detail="$3"; shift 3
  local evidence="${*:-}"
  # Noise suppression (post-observation tuning is a conf edit).
  local pat
  for pat in "${NOISE_PATTERNS[@]:-}"; do
    [[ -z "$pat" ]] && continue
    if printf '%s\n%s' "$detail" "$evidence" | grep -qE "$pat"; then
      SUPPRESSED=$((SUPPRESSED + 1))
      return 0
    fi
  done
  EVIDENCE_N=$((EVIDENCE_N + 1))
  local evfile="$FINDINGS_DIR/evidence_$EVIDENCE_N.txt"
  if [[ -n "$evidence" ]]; then
    printf '%s\n' "$evidence" > "$evfile"
  fi
  printf '%s\t%s\t%s\t%s\n' "$sev" "$check" "$detail" "$EVIDENCE_N" >> \
    "$([[ $sev == critical || $sev == anomaly ]] && echo "$ANOMALIES" || echo "$NOTES")"
}

# --- IP helpers ---------------------------------------------------------
ip2int() { local IFS=. ; local -a o=($1); echo $(( (o[0] << 24) + (o[1] << 16) + (o[2] << 8) + o[3] )); }

in_cidr() { # $1=ip $2=cidr-or-ip
  local ip="$1" cidr="$2"
  if [[ "$cidr" == */* ]]; then
    local net="${cidr%/*}" mask="${cidr#*/}" shift
    shift=$((32 - mask))
    (( ( $(ip2int "$ip") >> shift ) == ( $(ip2int "$net") >> shift ) ))
  else
    [[ "$ip" == "$cidr" ]]
  fi
}

ip_known() { local ip="$1" k; for k in "${KNOWN_IPS[@]}"; do in_cidr "$ip" "$k" && return 0; done; return 1; }

ip_internal() { # loopback / RFC1918 / link-local / ULA — not "external"
  local ip="$1"
  [[ "$ip" == 127.* || "$ip" == 10.* || "$ip" == 169.254.* || "$ip" == 192.168.* ]] && return 0
  if [[ "$ip" == 172.* ]]; then
    # 172.16.0.0/12: the SECOND octet is 16..31
    local rest
    rest="${ip#*.}"
    local o2
    o2="${rest%%.*}"
    if (( o2 >= 16 && o2 <= 31 )); then return 0; fi
  fi
  # IPv6 loopback / link-local / ULA
  [[ "$ip" == "::1" || "$ip" == fe80* || "$ip" == fc* || "$ip" == fd* ]] && return 0
  return 1
}

ip_cdn() { local ip="$1" c; for c in "${CDN_CIDRS[@]:-}"; do [[ -z "$c" ]] && continue; in_cidr "$ip" "$c" && return 0; done; return 1; }

# --- Baseline section reader -------------------------------------------
# baseline_section NAME -> prints the lines of the "== NAME ==" section
baseline_section() {
  awk -v sec="$1" '$0 == "== " sec " ==" { f=1; next } /^== / { f=0 } f' "$BASELINE_FILE"
}

# --- Live-state helpers (same normalization as the baseline script) -----
live_listeners() {
  ss -tln 2>/dev/null | awk 'NR > 1 { print $1, $4 }' || true
}

live_users() {
  getent passwd | awk -F: '$3 >= 1000 && $1 != "nobody" { print $1 }'
}

live_containers() {
  docker ps -a --format '{{.Names}}\t{{.Image}}' 2>/dev/null | sort || true
}

live_timers() {
  systemctl list-timers --all --no-pager --no-legend --plain 2>/dev/null \
    | awk 'NF >= 5 { print $(NF - 1) }' | sort -u || true
}

cron_file() {
  if [[ -r "$1" ]]; then
    echo "FILE $1 $(sha256sum "$1" | awk '{print $1}')"
  elif [[ -e "$1" ]]; then
    echo "UNREADABLE $1"
  else
    echo "MISSING $1"
  fi
}

cron_dir() {
  local f n=0
  if [[ ! -d "$1" ]]; then echo "MISSING $1"; return 0; fi
  if [[ ! -r "$1" ]]; then echo "UNREADABLE $1"; return 0; fi
  for f in "$1"/*; do
    [[ -e "$f" ]] || continue
    n=1
    cron_file "$f"
  done
  [[ $n -eq 0 ]] && echo "EMPTY $1"
  return 0
}

live_cron() {
  cron_file /etc/crontab
  cron_dir /etc/cron.d
  cron_dir /var/spool/cron/crontabs
}

# --- Checks --------------------------------------------------------------

check_authlog() {
  local auth_log="/var/log/auth.log"
  local cutoff
  cutoff="$(date -u -d '24 hours ago' +%Y-%m-%dT%H:%M:%S)"
  if [[ ! -r "$auth_log" ]]; then
    add_finding note authlog "auth.log unreadable (run as root for the auth check)"
    return 0
  fi
  # ISO timestamps sort lexicographically — a 24h window is a prefix compare.
  local lines
  lines="$(grep -E 'Failed password|Invalid user' "$auth_log" 2>/dev/null \
    | awk -v c="$cutoff" '{ ts = substr($0, 1, 19); if (ts >= c) print }' || true)"
  local total=0 unknown=0
  local -A known_counts=()
  local ip
  if [[ -n "$lines" ]]; then
    total="$(printf '%s\n' "$lines" | wc -l)"
    while IFS= read -r line; do
      ip="$(printf '%s' "$line" | awk '{ for (i = 1; i <= NF; i++) if ($i == "from") print $(i + 1) }')"
      if ip_known "${ip:-}"; then
        known_counts["${ip:-unknown}"]=$(( ${known_counts["${ip:-unknown}"]:-0} + 1 ))
      else
        unknown=$((unknown + 1))
        add_finding anomaly authlog "failed/invalid login from UNKNOWN ip ${ip:-?} (last 24h)" "$line"
      fi
    done < <(printf '%s\n' "$lines")
  fi
  AUTH_TOTAL="$total"
  AUTH_UNKNOWN="$unknown"
  AUTH_KNOWN_LINE=""
  local k
  for k in "${!known_counts[@]}"; do
    AUTH_KNOWN_LINE+="$k=${known_counts[$k]} "
  done
  return 0
}

check_port_diff() {
  (( HAS_BASELINE )) || return 0
  local base live
  base="$(baseline_section LISTENERS | awk '$1 == "LISTEN" { print $2 }' | sort -u)"
  if [[ -z "$base" ]]; then
    add_finding note port-diff "baseline has no LISTENERS data (ss UNAVAILABLE at capture) — port diff skipped"
    return 0
  fi
  live="$(live_listeners | awk '{ print $2 }' | sort -u)"
  local item
  while IFS= read -r item; do
    [[ -n "$item" ]] || continue
    add_finding anomaly port-diff "new listener $item (not in baseline)" "live ss -tln: $item"
  done < <(comm -13 <(printf '%s\n' "$base") <(printf '%s\n' "$live"))
  while IFS= read -r item; do
    [[ -n "$item" ]] || continue
    add_finding anomaly port-diff "removed listener $item (in baseline, gone from live)" "baseline: $item"
  done < <(comm -23 <(printf '%s\n' "$base") <(printf '%s\n' "$live"))
  return 0
}

check_outbound() {
  local out
  if ! out="$(ss -tn state established 2>/dev/null)"; then
    add_finding note outbound "ss -tn unavailable — outbound check skipped"
    return 0
  fi
  local peer port
  # SMTP outbound = immediate anomaly (this host must never send mail).
  local smtp_lines=""
  while IFS= read -r peer; do
    [[ -n "$peer" ]] || continue
    port="${peer##*:}"
    local p
    for p in "${SMTP_PORTS[@]}"; do
      if [[ "$port" == "$p" ]]; then
        smtp_lines+="$peer
"
      fi
    done
  done < <(printf '%s\n' "$out" | awk 'NR > 1 { print $4 }')
  if [[ -n "$smtp_lines" ]]; then
    add_finding critical outbound-smtp "ESTAB connections on SMTP port(s) ${SMTP_PORTS[*]} — this host must never send mail" "$smtp_lines"
  fi
  # External (public) peers not in the CDN/CF allowlist -> note.
  local -A ext=()
  while IFS= read -r peer; do
    local host="${peer%:*}"
    [[ -n "$host" ]] || continue
    [[ "$host" == \[* ]] && host="${host:1:${#host}-2}"
    ip_internal "$host" && continue
    ip_cdn "$host" && continue
    ext["$host"]=$(( ${ext["$host"]:-0} + 1 ))
  done < <(printf '%s\n' "$out" | awk 'NR > 1 { print $4 }')
  local h
  for h in $(printf '%s\n' "${!ext[@]}" | sort); do
    add_finding note outbound "external peer $h (${ext[$h]} established conn(s)) — not LAN/CDN"
  done
  return 0
}

check_account_cron_timer_drift() {
  (( HAS_BASELINE )) || return 0
  local base_users base_cron base_timers
  base_users="$(baseline_section USERS | cut -d: -f1 | sort -u)"
  local lu lc lt u
  lu="$(live_users | sort -u)"
  while IFS= read -r u; do
    [[ -n "$u" ]] || continue
    add_finding anomaly account-drift "new UID>=1000 user: $u (not in baseline)" "getent passwd: $u"
  done < <(comm -13 <(printf '%s\n' "$base_users") <(printf '%s\n' "$lu"))

  base_cron="$(baseline_section CRON | sort)"
  lc="$(live_cron | sort)"
  local line
  while IFS= read -r line; do
    [[ -n "$line" ]] || continue
    add_finding anomaly cron-drift "cron state changed: $line" "live cron state vs baseline"
  done < <(comm -13 <(printf '%s\n' "$base_cron") <(printf '%s\n' "$lc"))
  while IFS= read -r line; do
    [[ -n "$line" ]] || continue
    add_finding note cron-drift "cron entry gone from live: $line"
  done < <(comm -23 <(printf '%s\n' "$base_cron") <(printf '%s\n' "$lc"))

  base_timers="$(baseline_section TIMERS | sort -u)"
  lt="$(live_timers)"
  local t
  while IFS= read -r t; do
    [[ -n "$t" ]] || continue
    add_finding anomaly timer-drift "new systemd timer: $t (not in baseline)" "systemctl list-timers: $t"
  done < <(comm -13 <(printf '%s\n' "$base_timers") <(printf '%s\n' "$lt"))
  return 0
}

check_container_drift() {
  (( HAS_BASELINE )) || return 0
  local base live name
  base="$(baseline_section CONTAINERS | sort)"
  live="$(live_containers)"
  while IFS= read -r line; do
    [[ -n "$line" ]] || continue
    name="$(printf '%s' "$line" | cut -f1)"
    add_finding anomaly container-drift "new/renamed container: $name (not in baseline)" "docker ps -a: $line"
  done < <(comm -13 <(printf '%s\n' "$base") <(printf '%s\n' "$live") | cut -f1)
  while IFS= read -r name; do
    [[ -n "$name" ]] || continue
    add_finding anomaly container-drift "container gone: $name (in baseline, not in docker ps -a)"
  done < <(comm -23 <(printf '%s\n' "$base") <(printf '%s\n' "$live") | cut -f1)
  # Same name, different image -> note (rebuilds do this; typosquats don't).
  local bimg limg
  while IFS=$'\t' read -r name bimg; do
    [[ -n "$name" ]] || continue
    limg="$(printf '%s\n' "$live" | awk -F'\t' -v n="$name" '$1 == n { print $2 }')"
    if [[ -n "$limg" && "$limg" != "$bimg" ]]; then
      add_finding note container-drift "image changed for container $name: $bimg -> $limg"
    fi
  done < <(printf '%s\n' "$base" | awk -F'\t' '{ print $1 "\t" $2 }')
  return 0
}

check_mail_tools() {
  local t p
  for t in "${MAIL_TOOLS[@]}"; do
    if p="$(command -v "$t" 2>/dev/null)"; then
      add_finding critical mail-tool "mail tool present: $t at $p (this host should never send mail)" "command -v $t -> $p"
    fi
  done
  return 0
}

check_sensitive_files() {
  local changed
  changed="$(find /etc /usr/bin /usr/local/bin -type f -mmin -1440 2>/dev/null | head -50 || true)"
  if [[ -n "$changed" ]]; then
    local n
    n="$(printf '%s\n' "$changed" | wc -l)"
    add_finding note sensitive-files "$n file(s) under /etc,/usr/bin,/usr/local/bin modified in the last 24h" "$changed"
    if [[ -r /var/log/dpkg.log ]] && grep -q "$(date -u -d '24 hours ago' +%Y-%m-%d)" /var/log/dpkg.log 2>/dev/null; then
      add_finding note sensitive-files "dpkg activity in the last 24h — /etc changes may be package-driven (filtered context)"
    fi
  fi
  return 0
}

check_processes() {
  # Long-running (>24h) host processes not attributable to a container or a
  # running systemd service -> note. Containerized processes are attributed
  # via the cgroup docker id (container drift covers them); kernel threads
  # have cgroup "-".
  local units
  units="$(systemctl list-units --type=service --state=running --no-legend --plain 2>/dev/null | awk '{ print $1 }' || true)"
  local -A unit_set=()
  local u
  while IFS= read -r u; do
    [[ -n "$u" ]] || continue
    unit_set["$u"]=1
    unit_set["${u%.service}"]=1
  done < <(printf '%s\n' "$units")
  local line pid etimes comm cgroup
  while IFS= read -r line; do
    pid="$(printf '%s' "$line" | awk '{ print $1 }')"
    etimes="$(printf '%s' "$line" | awk '{ print $2 }')"
    comm="$(printf '%s' "$line" | awk '{ print $3 }')"
    cgroup="$(printf '%s' "$line" | awk '{ print $4 }')"
    (( etimes > 86400 )) || continue
    [[ "$pid" == "$$" || "$pid" == "$PPID" ]] && continue
    [[ "$cgroup" == "-" ]] && continue        # kernel thread
    [[ "$cgroup" == *docker* ]] && continue   # containerized
    if [[ -n "${unit_set[$comm]:-}" ]]; then continue; fi
    add_finding note processes "long-running host process not attributable to a container or running service: $comm (pid $pid, up $((etimes / 3600))h)" "$line"
  done < <(ps -eo pid=,etimes=,comm=,cgroup= --no-headers 2>/dev/null || true)
  return 0
}

check_baseline_age() {
  local age_days
  age_days=$(( (NOW_EPOCH - $(date -u -r "$BASELINE_FILE" +%s)) / 86400 ))
  if (( age_days > BASELINE_STALE_DAYS )); then
    add_finding note baseline-age "baseline is $age_days days old (stale > $BASELINE_STALE_DAYS d — drift detection is only as good as the baseline)"
  fi
  return 0
}

# --- Baseline diff table -------------------------------------------------
# render_diff BASE LIVE: full baseline-vs-live table for the report.
# The caller normalizes BOTH sides to the same item format (e.g. LISTENERS
# to addr:port, USERS to username). Items may contain spaces/tabs (cron
# lines, container name\timage) — line-oriented throughout, no word splitting.
render_diff() {
  local base="$1" live="$2"
  local item status rows=""
  local -A base_map=() live_map=()
  while IFS= read -r item; do
    [[ -n "$item" ]] || continue
    base_map["$item"]=1
  done < <(printf '%s\n' "$base")
  while IFS= read -r item; do
    [[ -n "$item" ]] || continue
    live_map["$item"]=1
  done < <(printf '%s\n' "$live")
  while IFS= read -r item; do
    [[ -n "$item" ]] || continue
    if [[ -n "${base_map[$item]:-}" && -n "${live_map[$item]:-}" ]]; then
      status="OK"
    elif [[ -n "${base_map[$item]:-}" ]]; then
      status="REMOVED"
    else
      status="ADDED"
    fi
    rows+="| $item | $status |"
    rows+=$'\n'
  done < <(printf '%s\n' "${!base_map[@]}" "${!live_map[@]}" | sort -u)
  printf '%s' "$rows"
}

# --- Report rendering ----------------------------------------------------
render_findings() {
  local file="$1" sev_label="$2"
  local sev check detail evn
  while IFS=$'\t' read -r sev check detail evn; do
    [[ -n "$sev" ]] || continue
    printf '### [%s] %s: %s\n\n' "$sev" "$check" "$detail"
    if [[ -n "$evn" && -f "$FINDINGS_DIR/evidence_$evn.txt" ]]; then
      printf '```\n%s\n```\n\n' "$(cat "$FINDINGS_DIR/evidence_$evn.txt")"
    else
      printf '\n'
    fi
  done < "$file"
}

main() {
  mkdir -p -m 755 "$REPORTS_DIR" "$METRICS_DIR"

  if [[ -f "$BASELINE_FILE" ]]; then
    HAS_BASELINE=1
  else
    HAS_BASELINE=0
    add_finding anomaly baseline-missing "baseline file missing: $BASELINE_FILE — run scripts/security-baseline.sh --update"
  fi

  check_authlog
  check_port_diff
  check_outbound
  check_account_cron_timer_drift
  check_container_drift
  check_mail_tools
  check_sensitive_files
  check_processes
  if (( HAS_BASELINE )); then
    check_baseline_age
  fi

  local n_anom n_note
  n_anom="$(wc -l < "$ANOMALIES")"
  n_note="$(wc -l < "$NOTES")"
  local verdict
  if (( n_anom == 0 && n_note == 0 )); then
    verdict="CLEAN"
  elif (( n_note == 0 )); then
    verdict="$n_anom anomalies"
  elif (( n_anom == 0 )); then
    verdict="$n_note notes"
  else
    verdict="$n_anom anomalies, $n_note notes"
  fi

  # --- alerts.log (anomalies only, appended) ---
  local sev check detail evn
  while IFS=$'\t' read -r sev check detail evn; do
    [[ -n "$sev" ]] || continue
    printf '%s | %s | %s | %s\n' "$NOW_TS" "$sev" "$check" "$detail" >> "$ALERTS_LOG"
  done < "$ANOMALIES"

  # --- daily report ---
  {
    echo "# Security Scan — $TODAY"
    echo
    echo "- host: $(hostname)"
    echo "- generated: $NOW_TS"
    echo "- baseline: $BASELINE_FILE"
    if [[ -f "$BASELINE_FILE" ]]; then
      echo "  (captured $(sed -nE 's/^# captured: //p' "$BASELINE_FILE" | head -n 1), age $(( (NOW_EPOCH - $(date -u -r "$BASELINE_FILE" +%s)) / 86400 ))d)"
    fi
    echo "- mode: $([[ $OBSERVATION_MODE == 1 ]] && echo "observation (report only, nothing escalated)" || echo "active")"
    echo "- verdict: $verdict"
    echo
    echo "verdict: $verdict"
    echo
    echo "## Anomalies ($n_anom)"
    echo
    if (( n_anom == 0 )); then
      echo "(none)"
      echo
    else
      render_findings "$ANOMALIES" anomaly
    fi
    echo "## Notes ($n_note)"
    echo
    if (( n_note == 0 )); then
      echo "(none)"
      echo
    else
      render_findings "$NOTES" note
    fi
    echo "## Baseline diff"
    echo
    echo "### LISTENERS"
    echo
    echo "| item (addr:port) | status |"
    echo "|---|---|"
    if (( HAS_BASELINE )); then
      render_diff "$(baseline_section LISTENERS | awk '$1 == "LISTEN" { print $2 }' | sort -u)" "$(live_listeners | awk '{ print $2 }' | sort -u)"
    else
      echo "| (no baseline) | SKIPPED |"
    fi
    echo
    echo "### USERS"
    echo
    echo "| user | status |"
    echo "|---|---|"
    if (( HAS_BASELINE )); then
      render_diff "$(baseline_section USERS | cut -d: -f1 | sort -u)" "$(live_users | sort -u)"
    else
      echo "| (no baseline) | SKIPPED |"
    fi
    echo
    echo "### CRON"
    echo
    echo "| entry | status |"
    echo "|---|---|"
    if (( HAS_BASELINE )); then
      render_diff "$(baseline_section CRON | sort -u)" "$(live_cron | sort -u)"
    else
      echo "| (no baseline) | SKIPPED |"
    fi
    echo
    echo "### TIMERS"
    echo
    echo "| timer unit | status |"
    echo "|---|---|"
    if (( HAS_BASELINE )); then
      render_diff "$(baseline_section TIMERS | sort -u)" "$(live_timers)"
    else
      echo "| (no baseline) | SKIPPED |"
    fi
    echo
    echo "### CONTAINERS"
    echo
    echo "| container (name<TAB>image) | status |"
    echo "|---|---|"
    if (( HAS_BASELINE )); then
      render_diff "$(baseline_section CONTAINERS | sort -u)" "$(live_containers)"
    else
      echo "| (no baseline) | SKIPPED |"
    fi
    echo
    echo "## auth.log (last 24h)"
    echo
    echo "auth-total: ${AUTH_TOTAL:-0}"
    echo "auth-unknown: ${AUTH_UNKNOWN:-0}"
    echo "auth-known: ${AUTH_KNOWN_LINE:-none}"
    echo
    if (( SUPPRESSED > 0 )); then
      echo "_suppressed by NOISE_PATTERNS: $SUPPRESSED_"
      echo
    fi
  } > "$REPORT_FILE"

  # --- Prometheus textfile metrics ---
  {
    echo "# HELP security_scan_anomalies_total Anomalies found by the latest security scan."
    echo "# TYPE security_scan_anomalies_total gauge"
    echo "security_scan_anomalies_total $n_anom"
    echo "# HELP security_scan_notes_total Notes found by the latest security scan."
    echo "# TYPE security_scan_notes_total gauge"
    echo "security_scan_notes_total $n_note"
    echo "# HELP security_scan_last_run_timestamp_seconds Unix timestamp of the last security scan run."
    echo "# TYPE security_scan_last_run_timestamp_seconds gauge"
    echo "security_scan_last_run_timestamp_seconds $NOW_EPOCH"
  } > "$METRICS_FILE"

  # --- retention ---
  if (( PRUNE )); then
    find "$REPORTS_DIR" -name 'security-report-*.md' -mtime +"$RETENTION_DAILY_DAYS" -delete 2>/dev/null || true
    find "$REPORTS_DIR" -name 'security-weekly-*.md' -mtime +"$((RETENTION_WEEKLY_WEEKS * 7))" -delete 2>/dev/null || true
  fi

  echo "scan complete: verdict=$verdict"
  echo "  report:  $REPORT_FILE"
  echo "  alerts:  $ALERTS_LOG (+$n_anom)"
  echo "  metrics: $METRICS_FILE"
}

main
