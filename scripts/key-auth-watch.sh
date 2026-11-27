#!/usr/bin/env bash
# =====================================================================
# key-auth-watch.sh — SEC Phase 6: 401 spike watch on the gated public
# routes (llm.choukalos.com, siri.choukalos.com).
#
# Source: Caddy access logs (JSON, stdout) — enabled 2026-11-27 by the
# `log @llm` / `log @siri` directives in caddy/Caddyfile (the log
# handler must sit BEFORE the handle block: a log inside the handle
# misses gate 401s because `respond` runs first in the subroute chain).
#
# Outputs (Phase 10 pattern — D7 decision: metrics + file alerts,
# push later):
#   metrics/key_auth.prom   caddy_unauthorized_total{host=...} gauges,
#                           picked up by the node-exporter textfile
#                           collector -> Victoria Metrics -> Grafana
#   alerts.log              one line per 401-spike EPISODE (state
#                           transition, not every 5-min run)
#
# Cadence: systemd timer, every 5 min (scripts/systemd/key-watch.timer).
# Config:  scripts/key-watch.conf (thresholds, hosts, window).
# =====================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=key-watch.conf
source "$SCRIPT_DIR/key-watch.conf"

NOW_TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
NOW_EPOCH="$(date -u +%s)"
METRICS_FILE="$KEYWATCH_METRICS_DIR/key_auth.prom"
STATE_FILE="$KEYWATCH_STATE_DIR/key-auth-state.json"

mkdir -p "$KEYWATCH_METRICS_DIR" "$KEYWATCH_STATE_DIR"

# --- read the docker log window --------------------------------------
# --since covers the window with overlap (timer fires every 5 min,
# window is 6 min) so a boundary 401 is never missed; the per-host
# counts are a gauge ("401s in the last window"), not a cumulative
# counter, so overlap double-counting is not a concern.
LOGS="$(docker logs --since "${KEYWATCH_401_WINDOW_MIN}m" \
  "$KEYWATCH_CADDY_CONTAINER" 2>&1)" || {
  echo "key-auth-watch: FAILED to read docker logs for $KEYWATCH_CADDY_CONTAINER" >&2
  {
    echo "# HELP caddy_unauthorized_watch_healthy 1 if the 401 watch ran successfully, 0 if it failed."
    echo "# TYPE caddy_unauthorized_watch_healthy gauge"
    echo "caddy_unauthorized_watch_healthy 0"
    echo "# HELP caddy_unauthorized_last_check_timestamp_seconds Unix timestamp of the last 401 watch run."
    echo "# TYPE caddy_unauthorized_last_check_timestamp_seconds gauge"
    echo "caddy_unauthorized_last_check_timestamp_seconds $NOW_EPOCH"
  } > "$METRICS_FILE"
  exit 1
}

# --- count 401s per gated host + episode state ------------------------
# Emits one line per host (host<TAB>count — always, so metrics get the
# real count) plus "ALERT\t<TAB>count" lines for episode transitions
# into breach (alerts.log only).
# NOTE: data goes via a temp file + argv — a `echo data | python3 -
# <<heredoc` mix makes the heredoc win the stdin race and python never
# sees the data (silent zero-count bug, caught in testing 2026-11-27).
LOGS_TMP="$(mktemp)"
trap 'rm -f "$LOGS_TMP"' EXIT
echo "$LOGS" > "$LOGS_TMP"
COUNT_OUT="$(HOSTS="$(printf '%s\n' "${KEYWATCH_GATED_HOSTS[@]}")" \
  THRESHOLD="$KEYWATCH_401_THRESHOLD" \
  STATE_FILE="$STATE_FILE" python3 - "$LOGS_TMP" <<'PY'
import os, sys, json

hosts = [h for h in os.environ["HOSTS"].splitlines() if h]
threshold = int(os.environ["THRESHOLD"])
state_file = os.environ["STATE_FILE"]

# previous episode state: {"llm.choukalos.com": true, ...}
prev = {}
if os.path.exists(state_file):
    try:
        with open(state_file) as f:
            prev = json.load(f)
    except Exception:
        prev = {}

counts = {h: 0 for h in hosts}
with open(sys.argv[1]) as f:
    for line in f:
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            d = json.loads(line)
        except Exception:
            continue
        if not str(d.get("logger", "")).startswith("http.log.access"):
            continue
        if d.get("status") != 401:
            continue
        host = (d.get("request") or {}).get("host", "")
        if host in counts:
            counts[host] += 1

# one line per host (metrics always get the real count) + ALERT lines
# for episode transitions into breach (alerts.log only)
cur = {}
for h in hosts:
    breached = counts[h] > threshold
    cur[h] = breached
    print(f"{h}\t{counts[h]}")
    if breached and not prev.get(h, False):
        print(f"ALERT\t{h}\t{counts[h]}")

with open(state_file, "w") as f:
    json.dump(cur, f)
PY
)"

# --- write metrics (always) -------------------------------------------
{
  echo "# HELP caddy_unauthorized_total 401 responses on a gated public route in the last check window."
  echo "# TYPE caddy_unauthorized_total gauge"
  for h in "${KEYWATCH_GATED_HOSTS[@]}"; do
    n="$(echo "$COUNT_OUT" | awk -F'\t' -v h="$h" '$1 == h { print $2; exit }')"
    echo "caddy_unauthorized_total{host=\"${h}\"} ${n:-0}"
  done
  echo "# HELP caddy_unauthorized_watch_healthy 1 if the 401 watch ran successfully, 0 if it failed."
  echo "# TYPE caddy_unauthorized_watch_healthy gauge"
  echo "caddy_unauthorized_watch_healthy 1"
  echo "# HELP caddy_unauthorized_last_check_timestamp_seconds Unix timestamp of the last 401 watch run."
  echo "# TYPE caddy_unauthorized_last_check_timestamp_seconds gauge"
  echo "caddy_unauthorized_last_check_timestamp_seconds $NOW_EPOCH"
} > "$METRICS_FILE"

# --- alerts.log (episode transitions only) ----------------------------
SEV="alert"
(( OBSERVATION_MODE == 1 )) && SEV="note"
ALERTED=0
while IFS=$'\t' read -r tag host count; do
  [[ "$tag" == "ALERT" ]] || continue
  printf '%s | %s | key-auth-401 | %s: %s 401s in last %sm (threshold >%s) — possible brute force or leaked key; check Grafana "Key & Auth — Phase 6"\n' \
    "$NOW_TS" "$SEV" "$host" "$count" "$KEYWATCH_401_WINDOW_MIN" "$KEYWATCH_401_THRESHOLD" \
    >> "$KEYWATCH_ALERTS_LOG"
  ALERTED=1
done <<< "$COUNT_OUT"

if (( ALERTED )); then
  echo "key-auth-watch: 401 spike detected (see $KEYWATCH_ALERTS_LOG)"
else
  total="$(echo "$COUNT_OUT" | awk -F'\t' '$1 != "ALERT" { s += $2 } END { print s + 0 }')"
  echo "key-auth-watch: ok ($total 401(s) in window)"
fi
