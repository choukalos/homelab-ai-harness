#!/usr/bin/env bash
# =====================================================================
# security-surface-scan.sh — daily public-surface scan (SEC Phase 11).
#
# Registry-driven black-box probes of the internet-facing surface
# (the Caddy hostnames behind the Cloudflare Tunnel). The registry
# (security/public-surface.yml) is the single source of truth: every
# domain, expected status, and auth context comes from it — adding a
# public site = adding one registry entry (spec 11.6 runbook).
#
# Checks (per registry domain unless noted):
#   probes        registry `probes` — expected status per auth state
#                 (none / chuck-key / wrong-key / expired-jwt). A
#                 negative canary (expected 401/404) answering 2xx is
#                 an AUTH REGRESSION / LEAK -> critical (P0 semantics,
#                 spec 11.2/11.6).
#   tls           protocol floor >= TLSv1.2, cert expiry thresholds
#   headers       conf EXPECT_HEADERS on https://<domain>/ + no
#                 version disclosure in the Server header
#   cve           registry stack/db_stack versions vs conf KNOWN_CVES
#   registry-lint Caddyfile host matchers + (if CF_API_TOKEN available)
#                 CF tunnel ingress hostnames vs registry — unknown on
#                 either side = anomaly (spec 11.0)
#
# Usage:
#   scripts/security-surface-scan.sh                (paths from conf)
#   scripts/security-surface-scan.sh --data-dir D   use D (reports/alerts/
#                                                   metrics under D)
#   scripts/security-surface-scan.sh --no-prune     skip retention pruning
#
# Writes (under the data dir, default /home/chuck/data/security-surface):
#   reports/security-surface-report-YYYY-MM-DD.md   daily report
#   alerts.log                                      anomalies only, appended:
#                                                   ts | severity | check | detail
#   metrics/security_surface.prom                   Prometheus textfile metrics
# Everything else is READ-ONLY (GET/HEAD probes, openssl s_client,
# Caddyfile read, registry read). No mutating requests, no auth bypass
# beyond the spec's negative tests (wrong-key / expired-jwt canaries).
#
# Observation mode (OBSERVATION_MODE=1 in security-surface-scan.conf,
# first 2 weeks): findings are reported but nothing is escalated.
# Flipping to 0 is a config edit, not a code change.
# =====================================================================
set -euo pipefail

# Byte-order collation for sort/comm: locale collation breaks comm's
# "sorted input" assumption. All output here is machine-oriented.
export LC_ALL=C

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONF="$SCRIPT_DIR/security-surface-scan.conf"
# Pre-declare the conf arrays so ${#arr[@]} is safe under set -u whether
# or not the conf exists / sets them.
EXPECT_HEADERS=()
KNOWN_CVES=()
NOISE_PATTERNS=()
if [[ -f "$CONF" ]]; then
  # shellcheck source=/dev/null
  . "$CONF"
fi

# Defaults if the conf is absent (or omits them).
SEC_SURFACE_DATA_DIR="${SEC_SURFACE_DATA_DIR:-/home/chuck/data/security-surface}"
CADDYFILE_PATH="${CADDYFILE_PATH:-/home/chuck/homelab/caddy/Caddyfile}"
ENV_FILE="${ENV_FILE:-/home/chuck/homelab/.env}"
OBSERVATION_MODE="${OBSERVATION_MODE:-1}"
PROBE_TIMEOUT="${PROBE_TIMEOUT:-30}"
PROBE_USER_AGENT="${PROBE_USER_AGENT:-homelab-security-scan/1.0 (read-only)}"
CERT_EXPIRY_ALERT_DAYS="${CERT_EXPIRY_ALERT_DAYS:-14}"
CERT_EXPIRY_WARN_DAYS="${CERT_EXPIRY_WARN_DAYS:-30}"
RETENTION_DAILY_DAYS="${RETENTION_DAILY_DAYS:-90}"
RETENTION_WEEKLY_WEEKS="${RETENTION_WEEKLY_WEEKS:-52}"
DB_SNAPSHOT_RETENTION_WEEKS="${DB_SNAPSHOT_RETENTION_WEEKS:-52}"
if [[ ${#EXPECT_HEADERS[@]} -eq 0 ]]; then
  EXPECT_HEADERS=("Strict-Transport-Security:note" "X-Content-Type-Options:anomaly")
fi
if [[ ${#KNOWN_CVES[@]} -eq 0 ]]; then
  KNOWN_CVES=()
fi
if [[ ${#NOISE_PATTERNS[@]} -eq 0 ]]; then
  NOISE_PATTERNS=()
fi

DATA_DIR="$SEC_SURFACE_DATA_DIR"
PRUNE=1
REGISTRY="${REGISTRY:-$SCRIPT_DIR/../security/public-surface.yml}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --data-dir) DATA_DIR="${2:?--data-dir needs a path}"; shift 2 ;;
    --registry) REGISTRY="${2:?--registry needs a path}"; shift 2 ;;
    --no-prune) PRUNE=0; shift ;;
    -h|--help) sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown arg: $1 (see --help)" >&2; exit 2 ;;
  esac
done

REPORTS_DIR="$DATA_DIR/reports"
ALERTS_LOG="$DATA_DIR/alerts.log"
METRICS_DIR="$DATA_DIR/metrics"
METRICS_FILE="$METRICS_DIR/security_surface.prom"
SNAP_DIR="$DATA_DIR/db-snapshots"
TODAY="$(date -u +%Y-%m-%d)"
NOW_TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
NOW_EPOCH="$(date -u +%s)"
REPORT_FILE="$REPORTS_DIR/security-surface-report-$TODAY.md"

# --- Findings bookkeeping (same pattern as scripts/security-scan.sh) ----
# Each finding: severity<TAB>check<TAB>detail<TAB>evidence-index in
# ANOMALIES/NOTES, evidence in $FINDINGS_DIR/evidence_NN.txt.
FINDINGS_DIR="$(mktemp -d /tmp/security-surface-scan.XXXXXX)"
ANOMALIES="$FINDINGS_DIR/anomalies"
NOTES="$FINDINGS_DIR/notes"
: > "$ANOMALIES"; : > "$NOTES"
EVIDENCE_N=0
SUPPRESSED=0
REGISTRY_OK=0
DOMAINS=()
RESERVED_DOMAINS=()
declare -A PROBE_FAILS=()
LINT_CADDY=""
LINT_REGISTRY=""
LINT_CF=""

cleanup() { rm -rf "$FINDINGS_DIR"; }
trap cleanup EXIT

# add_finding SEVERITY CHECK DETAIL [EVIDENCE]
add_finding() {
  local sev="$1" check="$2" detail="$3"
  local evidence="${4:-}"
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

# --- Registry parse (python3 + PyYAML; the registry is YAML) ------------
# Emits TSV lines:
#   DOMAIN <tab> domain
#   RESERVED <tab> domain          (domain marked `reserved: true`)
#   PROBE  <tab> domain <tab> path <tab> expect <tab> with <tab> redirect_to
#   STACK  <tab> domain <tab> component <tab> version   (stack + db_stack)
parse_registry() {
  command -v python3 >/dev/null 2>&1 || {
    echo "python3 not available" > "$FINDINGS_DIR/registry.err"
    return 1
  }
  python3 - "$REGISTRY" > "$FINDINGS_DIR/registry.tsv" 2>"$FINDINGS_DIR/registry.err" <<'PY'
import sys, yaml
with open(sys.argv[1]) as f:
    doc = yaml.safe_load(f) or {}
doms = doc.get("domains") or {}
for name in doms:
    e = doms[name] or {}
    print("DOMAIN\t%s" % name)
    if e.get("reserved"):
        print("RESERVED\t%s" % name)
    for p in (e.get("probes") or []):
        print("PROBE\t%s\t%s\t%s\t%s\t%s" % (
            name, p.get("path"), p.get("expect"),
            p.get("with", "none"), p.get("redirect_to") or ""))
    for m in ("stack", "db_stack"):
        for k, v in ((e.get(m) or {})).items():
            print("STACK\t%s\t%s\t%s" % (name, k, v))
PY
}

# --- Key / env helpers ---------------------------------------------------
# Chuck's LiteLLM key (for `with: chuck-key` probes) comes from the
# environment or ENV_FILE. Never printed in reports/alerts.
load_key() {
  LITELLM_KEY_CHUCK="${LITELLM_KEY_CHUCK:-}"
  if [[ -z "$LITELLM_KEY_CHUCK" && -r "$ENV_FILE" ]]; then
    local line
    line="$(grep -m1 -E '^LITELLM_KEY_CHUCK=' "$ENV_FILE" 2>/dev/null || true)"
    [[ -n "$line" ]] && LITELLM_KEY_CHUCK="${line#LITELLM_KEY_CHUCK=}"
  fi
  HAVE_KEY=0
  if [[ -n "$LITELLM_KEY_CHUCK" ]]; then HAVE_KEY=1; fi
}

# env_val NAME -> value of NAME= in ENV_FILE (empty if absent/unreadable)
env_val() {
  local line
  line="$(grep -m1 -E "^$1=" "$ENV_FILE" 2>/dev/null || true)"
  [[ -n "$line" ]] && printf '%s' "${line#*=}"
  return 0
}

# --- Per-domain probes ----------------------------------------------------
check_probes() {
  local domain="$1"
  local f="$FINDINGS_DIR/rows_$domain"
  : > "$f"
  local path expect with rto url out code loc
  local hdrs=()
  while IFS=$'\t' read -r path expect with rto; do
    [[ -n "$path" ]] || continue
    rto="${rto:-}"
    hdrs=()
    if [[ "$with" == "chuck-key" ]]; then
      if [[ $HAVE_KEY -eq 0 ]]; then
        add_finding note "probe:$domain" "probe skipped (LITELLM_KEY_CHUCK unavailable): $path"
        printf '| %s (with=chuck-key) | %s | SKIPPED | key unavailable |\n' "$path" "$expect" >> "$f"
        continue
      fi
      hdrs+=(-H "X-Api-Key: $LITELLM_KEY_CHUCK")
    elif [[ "$with" == "wrong-key" ]]; then
      hdrs+=(-H "X-Api-Key: wrong-key-canary")
    elif [[ "$with" == "expired-jwt" ]]; then
      hdrs+=(-H "Authorization: Bearer canary.invalid.expired")
    fi
    url="https://$domain$path"
    # Read-only GET; -w captures the status, stderr is folded into $out
    # on failure so the error text becomes the evidence.
    if ! out="$(curl -sS -o /dev/null -w '%{http_code}' --max-time "$PROBE_TIMEOUT" \
        -A "$PROBE_USER_AGENT" ${hdrs[@]+"${hdrs[@]}"} "$url" 2>&1)"; then
      out="${out:-curl exited non-zero}"
    fi
    if [[ ! "$out" =~ ^[0-9]{3}$ ]]; then
      PROBE_FAILS["$domain"]=$(( ${PROBE_FAILS["$domain"]:-0} + 1 ))
      add_finding anomaly "probe:$domain" "probe failed (network/upstream): $path (with=$with) expected=$expect" "$url -> $out"
      printf '| %s (with=%s) | %s | FAIL | %s |\n' "$path" "$with" "$expect" "$out" >> "$f"
      continue
    fi
    code="$out"
    if [[ -n "$rto" ]]; then
      loc="$(curl -sS -o /dev/null -D - --max-time "$PROBE_TIMEOUT" -A "$PROBE_USER_AGENT" \
        ${hdrs[@]+"${hdrs[@]}"} "$url" 2>/dev/null \
        | tr -d '\r' | awk 'tolower($1) == "location:" { print $2; exit }')"
      if [[ "$loc" != *"$rto"* ]]; then
        PROBE_FAILS["$domain"]=$(( ${PROBE_FAILS["$domain"]:-0} + 1 ))
        add_finding anomaly "probe:$domain" "redirect target wrong: $path (with=$with) Location=${loc:-<none>} (expected to contain $rto)" "$url"
        printf '| %s (with=%s) | %s -> %s | FAIL | redirect target |\n' "$path" "$with" "$code" "$rto" >> "$f"
        continue
      fi
    fi
    if [[ ",$expect," == *",$code,"* ]]; then
      printf '| %s (with=%s) | %s | %s | OK |\n' "$path" "$with" "$expect" "$code" >> "$f"
      continue
    fi
    PROBE_FAILS["$domain"]=$(( ${PROBE_FAILS["$domain"]:-0} + 1 ))
    # Negative canary: every expected code is 4xx and the actual is 2xx
    # -> an auth-required route is answering unauthenticated = P0 leak.
    local neg=1 e old_ifs="$IFS"
    IFS=','
    for e in $expect; do [[ "$e" =~ ^4 ]] || neg=0; done
    IFS="$old_ifs"
    if [[ $neg -eq 1 ]] && [[ "$code" =~ ^2 ]]; then
      add_finding critical "probe:$domain" "NEGATIVE CANARY FAILED: $path (with=$with) expected $expect, got $code — the expected 401/404 is not holding (auth regression or route change; P0 per spec 11.2)" "$url"
    else
      add_finding anomaly "probe:$domain" "unexpected status: $path (with=$with) expected $expect, got $code" "$url"
    fi
    printf '| %s (with=%s) | %s | %s | FAIL |\n' "$path" "$with" "$expect" "$code" >> "$f"
  done < <(awk -F'\t' -v d="$domain" '$1 == "PROBE" && $2 == d { print $3 "\t" $4 "\t" $5 "\t" $6 }' "$FINDINGS_DIR/registry.tsv")
  return 0
}

# --- Per-domain TLS -------------------------------------------------------
check_tls() {
  local domain="$1"
  command -v openssl >/dev/null 2>&1 || {
    add_finding note "tls:$domain" "openssl unavailable — TLS check skipped"
    return 0
  }
  local out
  out="$(openssl s_client -connect "$domain:443" -servername "$domain" </dev/null 2>/dev/null || true)"
  if [[ -z "$out" ]]; then
    PROBE_FAILS["$domain"]=$(( ${PROBE_FAILS["$domain"]:-0} + 1 ))
    add_finding anomaly "tls:$domain" "TLS handshake failed on $domain:443" "openssl s_client: no output"
    printf '| %s | FAIL | - | - | handshake failed |\n' "$domain" >> "$FINDINGS_DIR/tls-rows"
    return 0
  fi
  local proto notafter exp_epoch days
  proto="$(printf '%s\n' "$out" | awk '/Protocol/ { for (i = 1; i <= NF; i++) if ($i ~ /^TLSv/) { print $i; exit } }')"
  notafter="$(printf '%s\n' "$out" | grep -m1 'NotAfter' | sed -E 's/.*NotAfter:[[:space:]]*//')"
  exp_epoch=0
  if [[ -n "$notafter" ]]; then
    # "Feb  5 09:47:50 2027 GMT" -> "Feb 5 2027"
    exp_epoch="$(date -u -d "$(printf '%s' "$notafter" | awk '{ print $1, $2, $4 }')" +%s 2>/dev/null || echo 0)"
  fi
  local status="OK" sev=""
  if [[ "$proto" != "TLSv1.2" && "$proto" != "TLSv1.3" && "$proto" != "TLSv1.4" ]]; then
    status="FAIL"; sev="anomaly"
    add_finding anomaly "tls:$domain" "TLS protocol below floor: $proto (floor TLSv1.2)" "openssl s_client: $proto"
  fi
  if [[ $exp_epoch -gt 0 ]]; then
    days=$(( (exp_epoch - NOW_EPOCH) / 86400 ))
    if (( days < CERT_EXPIRY_ALERT_DAYS )); then
      status="FAIL"; sev="anomaly"
      add_finding anomaly "tls:$domain" "cert expires in $days days (< $CERT_EXPIRY_ALERT_DAYS)" "NotAfter: $notafter"
    elif (( days < CERT_EXPIRY_WARN_DAYS )); then
      status="WARN"; sev="note"
      add_finding note "tls:$domain" "cert expires in $days days (< $CERT_EXPIRY_WARN_DAYS)" "NotAfter: $notafter"
    fi
    printf '| %s | %s | %s | %s | %s |\n' "$domain" "${proto:-?}" "$notafter" "$days" "$status" >> "$FINDINGS_DIR/tls-rows"
  else
    status="UNREADABLE"
    add_finding note "tls:$domain" "cert expiry unreadable from s_client output" "NotAfter: ${notafter:-<none>}"
    printf '| %s | %s | UNREADABLE | - | %s |\n' "$domain" "${proto:-?}" "$status" >> "$FINDINGS_DIR/tls-rows"
  fi
  return 0
}

# --- Per-domain security headers ------------------------------------------
check_headers() {
  local domain="$1"
  local hdrtext
  hdrtext="$(curl -sS -o /dev/null -D - --max-time "$PROBE_TIMEOUT" -A "$PROBE_USER_AGENT" "https://$domain/" 2>/dev/null || true)"
  if [[ -z "$hdrtext" ]]; then
    add_finding anomaly "headers:$domain" "no response for the header check on /" "curl: no output"
    return 0
  fi
  local spec name sev
  for spec in "${EXPECT_HEADERS[@]:-}"; do
    [[ -z "$spec" ]] && continue
    name="${spec%%:*}"; sev="${spec##*:}"
    if ! printf '%s\n' "$hdrtext" | grep -qi "^${name}:"; then
      add_finding "$sev" "headers:$domain" "response header $name missing on / (expected per conf)" "checked: $name (absent)"
    fi
  done
  # No version disclosure in the Server header.
  local server
  server="$(printf '%s\n' "$hdrtext" | tr -d '\r' | awk 'tolower($1) == "server:" { sub(/^[^:]*:[[:space:]]*/, ""); print; exit }')"
  if [[ "$server" =~ [0-9] ]]; then
    add_finding note "headers:$domain" "Server header discloses a version: $server" "Server: $server"
  fi
  return 0
}

# --- CVE cross-check (registry stack vs conf KNOWN_CVES) ------------------
check_cves() {
  local line domain comp ver entry c rest rest2 vreg cve sev match
  while IFS=$'\t' read -r _ domain comp ver; do
    [[ -n "$domain" ]] || continue
    match=0
    for entry in "${KNOWN_CVES[@]:-}"; do
      [[ -z "$entry" ]] && continue
      c="${entry%%|*}"; rest="${entry#*|}"
      vreg="${rest%%|*}"; rest2="${rest#*|}"
      cve="${rest2%%|*}"; sev="${rest2#*|}"
      if [[ "$comp" == "$c" ]] && [[ "$ver" =~ $vreg ]]; then
        match=1
        add_finding "$sev" "cve:$domain" "stack $comp=$ver matches known-CVE $cve" "registry stack: $domain $comp=$ver; conf entry: $entry"
      fi
    done
    if [[ $match -eq 1 ]]; then
      printf '| %s | %s | %s | MATCH |\n' "$domain" "$comp" "$ver" >> "$FINDINGS_DIR/cve-rows"
    else
      printf '| %s | %s | %s | clean |\n' "$domain" "$comp" "$ver" >> "$FINDINGS_DIR/cve-rows"
    fi
  done < <(awk -F'\t' '$1 == "STACK" { print $1 "\t" $2 "\t" $3 "\t" $4 }' "$FINDINGS_DIR/registry.tsv")
  return 0
}

# --- Registry lint (Caddyfile + optional CF ingress vs registry) ----------
check_registry_lint() {
  local caddy_hosts reg_domains
  if [[ -r "$CADDYFILE_PATH" ]]; then
    caddy_hosts="$(grep -oE 'host [A-Za-z0-9.-]+' "$CADDYFILE_PATH" 2>/dev/null | awk '{ print $2 }' | sort -u)"
  else
    caddy_hosts=""
    add_finding note registry-lint "Caddyfile unreadable ($CADDYFILE_PATH) — Caddyfile side of the lint skipped"
  fi
  reg_domains="$(awk -F'\t' '$1 == "DOMAIN" { print $2 }' "$FINDINGS_DIR/registry.tsv" | sort -u)"
  LINT_CADDY="$caddy_hosts"
  LINT_REGISTRY="$reg_domains"
  local h d
  while IFS= read -r h; do
    [[ -n "$h" ]] || continue
    add_finding anomaly registry-lint "public hostname in Caddyfile not in registry: $h" "Caddyfile host matcher: $h"
  done < <(comm -23 <(printf '%s\n' "$caddy_hosts") <(printf '%s\n' "$reg_domains"))
  while IFS= read -r d; do
    [[ -n "$d" ]] || continue
    add_finding anomaly registry-lint "registry domain not in Caddyfile: $d" "registry: $d"
  done < <(comm -13 <(printf '%s\n' "$caddy_hosts") <(printf '%s\n' "$reg_domains"))

  # CF tunnel ingress side (optional — needs CF_API_TOKEN, same contract
  # as scripts/rotate-cf-tunnel.sh: env first, .env fallback).
  local token="${CF_API_TOKEN:-}"
  if [[ -z "$token" && -r "$ENV_FILE" ]]; then
    local line
    line="$(grep -m1 -E '^CF_API_TOKEN=' "$ENV_FILE" 2>/dev/null || true)"
    [[ -n "$line" ]] && token="${line#CF_API_TOKEN=}"
  fi
  if [[ -z "$token" ]]; then
    add_finding note cf-ingress-lint "CF_API_TOKEN not set (env or $ENV_FILE) — CF ingress side of the lint skipped (Caddyfile side checked)"
    return 0
  fi
  local acct tid body
  acct="$(env_val CF_ACCOUNT_ID)"
  tid="$(env_val CF_TUNNEL_ID)"
  if [[ -z "$acct" || -z "$tid" ]]; then
    add_finding note cf-ingress-lint "CF_ACCOUNT_ID/CF_TUNNEL_ID missing in $ENV_FILE — CF ingress side of the lint skipped"
    return 0
  fi
  body="$(curl -sS --max-time "$PROBE_TIMEOUT" -H "Authorization: Bearer $token" \
    "https://api.cloudflare.com/client/v4/accounts/$acct/cfd_tunnel/$tid" 2>/dev/null || true)"
  if [[ "$body" != *'"success":true'* ]]; then
    add_finding note cf-ingress-lint "CF tunnel fetch failed — ingress side of the lint skipped" "CF API response (abridged): ${body:0:200}"
    return 0
  fi
  # Ingress hostnames carry a trailing /* path; strip it for the diff.
  local cf_hosts
  cf_hosts="$(printf '%s' "$body" | grep -oE '"hostname": *"[^"]+"' | sed -E 's/"hostname": *"//; s/"$//; s#/\*$##' | sort -u)"
  LINT_CF="$cf_hosts"
  while IFS= read -r h; do
    [[ -n "$h" ]] || continue
    add_finding critical cf-ingress-lint "unknown public hostname on the CF tunnel (not in registry): $h" "CF tunnel ingress: $h"
  done < <(comm -23 <(printf '%s\n' "$cf_hosts") <(printf '%s\n' "$reg_domains"))
  return 0
}

# --- Report rendering ------------------------------------------------------
render_findings() {
  local file="$1"
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
  mkdir -p -m 755 "$REPORTS_DIR" "$METRICS_DIR" "$SNAP_DIR"
  : > "$FINDINGS_DIR/tls-rows"; : > "$FINDINGS_DIR/cve-rows"

  if ! parse_registry; then
    REGISTRY_OK=0
    add_finding critical registry "registry unreadable: $REGISTRY — probe/TLS/CVE/lint checks skipped" "$(cat "$FINDINGS_DIR/registry.err" 2>/dev/null || true)"
  else
    REGISTRY_OK=1
    mapfile -t DOMAINS < <(awk -F'\t' '$1 == "DOMAIN" { print $2 }' "$FINDINGS_DIR/registry.tsv" | sort -u)
  fi

  load_key
  local d
  if [[ $REGISTRY_OK -eq 1 ]]; then
    mapfile -t RESERVED_DOMAINS < <(awk -F'\t' '$1 == "RESERVED" { print $2 }' "$FINDINGS_DIR/registry.tsv" | sort -u)
    for d in "${DOMAINS[@]:-}"; do
      [[ -z "$d" ]] && continue
      check_probes "$d"
      check_tls "$d"
      # Reserved domains have no backend on purpose (502 expected): the
      # header check would only flag the CF error page — skip it.
      if ! printf '%s\n' "${RESERVED_DOMAINS[@]:-}" | grep -qxF "$d"; then
        check_headers "$d"
      fi
    done
    check_cves
  fi
  check_registry_lint

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

  # --- alerts.log (anomalies only, appended) ---
  local sev check detail evn
  while IFS=$'\t' read -r sev check detail evn; do
    [[ -n "$sev" ]] || continue
    printf '%s | %s | %s | %s\n' "$NOW_TS" "$sev" "$check" "$detail" >> "$ALERTS_LOG"
  done < "$ANOMALIES"

  # --- daily report ---
  {
    echo "# Public Surface Scan — $TODAY"
    echo
    echo "- host: $(hostname)"
    echo "- generated: $NOW_TS"
    echo "- registry: $REGISTRY"
    if [[ $REGISTRY_OK -eq 1 ]]; then
      echo "- domains: ${#DOMAINS[@]} (${DOMAINS[*]})"
    else
      echo "- domains: UNREADABLE (see registry finding)"
    fi
    echo "- mode: $([[ $OBSERVATION_MODE == 1 ]] && echo "observation (report only, nothing escalated)" || echo "active")"
    echo "- vantage: host (thor) via public DNS — full public chain (CF edge → tunnel → Caddy) except external resolver; D8 off-LAN vantage is a separate follow-up"
    echo "- verdict: $verdict"
    echo
    echo "verdict: $verdict"
    echo
    echo "## Anomalies ($n_anom)"
    echo
    if [[ $n_anom -eq 0 ]]; then
      echo "(none)"
      echo
    else
      render_findings "$ANOMALIES"
    fi
    echo "## Notes ($n_note)"
    echo
    if [[ $n_note -eq 0 ]]; then
      echo "(none)"
      echo
    else
      render_findings "$NOTES"
    fi
    echo "## Per-domain probes"
    echo
    if [[ $REGISTRY_OK -eq 1 ]]; then
      for d in "${DOMAINS[@]:-}"; do
        [[ -z "$d" ]] && continue
        echo "### $d"
        echo
        echo "| probe | expected | got | status |"
        echo "|---|---|---|---|"
        cat "$FINDINGS_DIR/rows_$d"
        echo
      done
    else
      echo "(skipped — registry unreadable)"
      echo
    fi
    echo "## TLS"
    echo
    echo "| domain | protocol | cert expires | days left | status |"
    echo "|---|---|---|---|---|"
    if [[ $REGISTRY_OK -eq 1 ]]; then
      cat "$FINDINGS_DIR/tls-rows"
    else
      echo "| (skipped) | | | | |"
    fi
    echo
    echo "## CVE cross-check (registry stack vs conf KNOWN_CVES)"
    echo
    echo "| domain | component | version | known-CVE match |"
    echo "|---|---|---|---|"
    if [[ $REGISTRY_OK -eq 1 ]]; then
      cat "$FINDINGS_DIR/cve-rows"
    else
      echo "| (skipped) | | | |"
    fi
    echo
    echo "## Registry lint"
    echo
    echo "- Caddyfile hosts ($(printf '%s\n' "$LINT_CADDY" | grep -c . || true)): $(printf '%s' "$LINT_CADDY" | tr '\n' ' ')"
    echo "- registry domains ($(printf '%s\n' "$LINT_REGISTRY" | grep -c . || true)): $(printf '%s' "$LINT_REGISTRY" | tr '\n' ' ')"
    if [[ -n "$LINT_CF" ]]; then
      echo "- CF tunnel ingress ($(printf '%s\n' "$LINT_CF" | grep -c . || true)): $(printf '%s' "$LINT_CF" | tr '\n' ' ')"
    else
      echo "- CF tunnel ingress: not checked (see findings)"
    fi
    echo
    if [[ $SUPPRESSED -gt 0 ]]; then
      echo "_suppressed by NOISE_PATTERNS: $SUPPRESSED_"
      echo
    fi
  } > "$REPORT_FILE"

  # --- Prometheus textfile metrics ---
  {
    echo "# HELP security_probe_failures_total Failed registry probes per domain (latest scan)."
    echo "# TYPE security_probe_failures_total gauge"
    for d in "${DOMAINS[@]:-}"; do
      [[ -z "$d" ]] && continue
      echo "security_probe_failures_total{domain=\"$d\"} ${PROBE_FAILS[$d]:-0}"
    done
    echo "# HELP security_surface_anomalies_total Anomalies found by the latest public-surface scan."
    echo "# TYPE security_surface_anomalies_total gauge"
    echo "security_surface_anomalies_total $n_anom"
    echo "# HELP security_surface_notes_total Notes found by the latest public-surface scan."
    echo "# TYPE security_surface_notes_total gauge"
    echo "security_surface_notes_total $n_note"
    echo "# HELP security_surface_last_run_timestamp_seconds Unix timestamp of the last public-surface scan."
    echo "# TYPE security_surface_last_run_timestamp_seconds gauge"
    echo "security_surface_last_run_timestamp_seconds $NOW_EPOCH"
  } > "$METRICS_FILE"

  # --- retention (90d daily / 52w weekly; snapshots keep the newest) ---
  if [[ $PRUNE -eq 1 ]]; then
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
  fi

  echo "surface scan complete: verdict=$verdict"
  echo "  report:  $REPORT_FILE"
  echo "  alerts:  $ALERTS_LOG (+$n_anom)"
  echo "  metrics: $METRICS_FILE"
}

main
