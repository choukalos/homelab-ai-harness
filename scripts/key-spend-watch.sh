#!/usr/bin/env bash
# =====================================================================
# key-spend-watch.sh — SEC Phase 6: per-LiteLLM-key spend watch.
#
# Source: LiteLLM admin /spend/keys (master key) — exposes per-key
# TOTAL spend only (no windowed view via API, per the weekly review
# skill's finding), so the 24h rolling window is built from deltas
# against a state file (Phase 10 baseline-diff pattern). First run
# establishes the baseline; the window is fully populated after 24h.
#
# Outputs (Phase 10 pattern):
#   metrics/key_spend.prom  litellm_key_spend_24h_usd / _limit_usd /
#                           _total_usd{alias=...} gauges
#   alerts.log              one line per spend-breach EPISODE
#
# Cadence: systemd timer, every 5 min (scripts/systemd/key-watch.timer,
# shared with key-auth-watch.sh via scripts/key-watch.sh).
# Config:  scripts/key-watch.conf (per-key limits, window hours).
# =====================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=key-watch.conf
source "$SCRIPT_DIR/key-watch.conf"

# LiteLLM credentials: from the environment (systemd EnvironmentFile or
# the caller's shell) or the repo .env (single source of keys, Phase 13).
if [[ -z "${LITELLM_MASTER_KEY:-}" ]]; then
  ENV_FILE="$(cd "$SCRIPT_DIR/.." && pwd)/.env"
  [[ -f "$ENV_FILE" ]] || { echo "key-spend-watch: LITELLM_MASTER_KEY not set and no .env at $ENV_FILE" >&2; exit 1; }
  set -a; source "$ENV_FILE"; set +a
fi
LITELLM_PROXY="${LITELLM_PROXY:-http://192.168.4.54:4000}"

NOW_TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
NOW_EPOCH="$(date -u +%s)"
METRICS_FILE="$KEYWATCH_METRICS_DIR/key_spend.prom"
STATE_FILE="$KEYWATCH_SPEND_STATE_FILE"

mkdir -p "$KEYWATCH_METRICS_DIR" "$KEYWATCH_STATE_DIR"

SPEND_JSON="$(curl -sf -H "Authorization: Bearer ${LITELLM_MASTER_KEY}" \
  "${LITELLM_PROXY}/spend/keys")" || {
  echo "key-spend-watch: FAILED to fetch /spend/keys from $LITELLM_PROXY" >&2
  {
    echo "# HELP litellm_key_spend_watch_healthy 1 if the spend watch ran successfully, 0 if it failed."
    echo "# TYPE litellm_key_spend_watch_healthy gauge"
    echo "litellm_key_spend_watch_healthy 0"
    echo "# HELP litellm_key_spend_last_check_timestamp_seconds Unix timestamp of the last spend watch run."
    echo "# TYPE litellm_key_spend_last_check_timestamp_seconds gauge"
    echo "litellm_key_spend_last_check_timestamp_seconds $NOW_EPOCH"
  } > "$METRICS_FILE"
  exit 1
}

# --- deltas, rolling window, episode state ----------------------------
# Emits tab-separated lines: alias<TAB>spend_24h<TAB>total<TAB>limit<TAB>breached(0/1)
# plus alert lines prefixed "ALERT\t" for episode transitions into breach.
# NOTE: data via temp file + argv (heredoc-vs-pipe stdin race — see
# key-auth-watch.sh note).
SPEND_TMP="$(mktemp)"
trap 'rm -f "$SPEND_TMP"' EXIT
echo "$SPEND_JSON" > "$SPEND_TMP"
WATCH_OUT="$(NOW_EPOCH="$NOW_EPOCH" \
  STATE_FILE="$STATE_FILE" WINDOW_HOURS="$SPEND_WINDOW_HOURS" \
  DEFAULT_LIMIT="$SPEND_LIMIT_DEFAULT" \
  OVERRIDES="$(printf '%s\n' "${SPEND_LIMIT_OVERRIDES[@]}")" \
  python3 - "$SPEND_TMP" <<'PY'
import os, sys, json, time

now = int(os.environ["NOW_EPOCH"])
state_file = os.environ["STATE_FILE"]
window = int(os.environ["WINDOW_HOURS"]) * 3600
default_limit = float(os.environ["DEFAULT_LIMIT"])
overrides = {}
for line in os.environ.get("OVERRIDES", "").splitlines():
    if "=" in line:
        alias, val = line.split("=", 1)
        try:
            overrides[alias.strip()] = float(val)
        except ValueError:
            pass

try:
    with open(sys.argv[1]) as f:
        data = json.load(f)
except Exception as e:
    print(f"ERROR\tnon-JSON /spend/keys response: {e}", file=sys.stderr)
    sys.exit(1)

rows = data if isinstance(data, list) else data.get("data", data.get("keys", []))

prev = {}
if os.path.exists(state_file):
    try:
        with open(state_file) as f:
            prev = json.load(f)
    except Exception:
        prev = {}

cutoff = now - window
new_state = {}
lines = []
for r in rows:
    # /spend/keys exposes the hash as `token` (not `key_hash`); unaliased
    # keys (e.g. the memory-service key) are labeled by token prefix.
    alias = r.get("key_alias") or (r.get("token") or r.get("key_hash") or "?")[:12]
    total = float(r.get("spend") or 0)
    limit = overrides.get(alias, default_limit)

    p = prev.get(alias)
    if p is None:
        delta = 0.0          # baseline run: no window data yet
        deltas = []
    else:
        delta = total - float(p.get("total", 0))
        if delta < 0:        # totals never decrease; treat as a reset
            delta = 0.0
        deltas = [d for d in p.get("deltas", []) if d[0] >= cutoff]
        deltas.append([now, round(delta, 6)])

    spend_window = round(sum(d[1] for d in deltas), 6)
    breached = spend_window > limit

    new_state[alias] = {"total": total, "ts": now, "deltas": deltas}
    lines.append(f"{alias}\t{spend_window}\t{total:.2f}\t{limit:g}\t{int(breached)}")
    if breached and not prev.get(alias, {}).get("breached", False):
        lines.append(f"ALERT\t{alias}\t{spend_window:.2f}\t{limit:g}")

    # remember breach state for episode detection
    new_state[alias]["breached"] = breached

with open(state_file, "w") as f:
    json.dump(new_state, f)

for l in lines:
    print(l)
PY
)" || {
  echo "key-spend-watch: spend computation failed" >&2
  exit 1
}

# --- write metrics (always) -------------------------------------------
{
  echo "# HELP litellm_key_spend_24h_usd LiteLLM key spend in the rolling window (USD)."
  echo "# TYPE litellm_key_spend_24h_usd gauge"
  echo "# HELP litellm_key_spend_limit_usd Per-key spend limit for the rolling window (USD)."
  echo "# TYPE litellm_key_spend_limit_usd gauge"
  echo "# HELP litellm_key_spend_total_usd LiteLLM key total spend since creation (USD)."
  echo "# TYPE litellm_key_spend_total_usd gauge"
  while IFS=$'\t' read -r alias s24 total limit br; do
    case "$alias" in ALERT) continue ;; esac
    echo "litellm_key_spend_24h_usd{alias=\"${alias}\"} ${s24}"
    echo "litellm_key_spend_limit_usd{alias=\"${alias}\"} ${limit}"
    echo "litellm_key_spend_total_usd{alias=\"${alias}\"} ${total}"
  done <<< "$WATCH_OUT"
  echo "# HELP litellm_key_spend_watch_healthy 1 if the spend watch ran successfully, 0 if it failed."
  echo "# TYPE litellm_key_spend_watch_healthy gauge"
  echo "litellm_key_spend_watch_healthy 1"
  echo "# HELP litellm_key_spend_last_check_timestamp_seconds Unix timestamp of the last spend watch run."
  echo "# TYPE litellm_key_spend_last_check_timestamp_seconds gauge"
  echo "litellm_key_spend_last_check_timestamp_seconds $NOW_EPOCH"
} > "$METRICS_FILE"

# --- alerts.log (episode transitions only) ----------------------------
SEV="alert"
(( OBSERVATION_MODE == 1 )) && SEV="note"
ALERTED=0
while IFS=$'\t' read -r tag alias s24 limit; do
  [[ "$tag" == "ALERT" ]] || continue
  printf '%s | %s | key-spend | %s: $%s in last %sh (limit $%s) — check Grafana "Key & Auth — Phase 6"\n' \
    "$NOW_TS" "$SEV" "$alias" "$s24" "$SPEND_WINDOW_HOURS" "$limit" \
    >> "$KEYWATCH_ALERTS_LOG"
  ALERTED=1
done <<< "$WATCH_OUT"

if (( ALERTED )); then
  echo "key-spend-watch: spend breach detected (see $KEYWATCH_ALERTS_LOG)"
else
  echo "key-spend-watch: ok ($(echo "$WATCH_OUT" | grep -vc '^ALERT' || true) key(s) tracked)"
fi
