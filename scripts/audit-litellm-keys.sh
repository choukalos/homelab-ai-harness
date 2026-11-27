#!/usr/bin/env bash
# =====================================================================
# audit-litellm-keys.sh — SEC Phase 6: LiteLLM key inventory audit.
#
# Live inventory (via lib/litellm-keys.sh _key_fetch_all + MCP access
# group resolution) diffed against a machine-readable snapshot
# (Phase 10 baseline-diff pattern):
#   /home/chuck/data/security/key-inventory-snapshot.json
#
# Checks:
#   drift        keys added / removed / changed (user, models, MCP
#                groups, budget, rpm/tpm, blocked) vs the snapshot
#   rotation-due key created_at older than ROTATION_DUE_DAYS (default
#                90 — the quarterly cadence; flow: ./homelab.sh key rotate)
#   blocked      any blocked key (verify it was intentional)
#   spend        per-key totals (informational — the spend watch
#                handles the 24h alerts)
#
# Cadence: monthly (systemd timer) + after any key change.
#   ./homelab.sh key audit                 # run the audit
#   ./homelab.sh key audit --update-snapshot   # refresh the baseline
#                                              # AFTER reviewing drift
# Config: scripts/key-watch.conf.
# =====================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=key-watch.conf
source "$SCRIPT_DIR/key-watch.conf"
# shellcheck source=../lib/litellm-keys.sh
source "$REPO_ROOT/lib/litellm-keys.sh"

UPDATE_SNAPSHOT=0
JSON_ONLY=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --update-snapshot) UPDATE_SNAPSHOT=1; shift ;;
    --json)            JSON_ONLY=1;     shift ;;
    *) echo "Usage: $0 [--update-snapshot] [--json]" >&2; exit 2 ;;
  esac
done

if [[ -z "${LITELLM_MASTER:-}" ]]; then
  ENV_FILE="$REPO_ROOT/.env"
  [[ -f "$ENV_FILE" ]] || { echo "audit: LITELLM_MASTER_KEY not set and no .env at $ENV_FILE" >&2; exit 1; }
  set -a; source "$ENV_FILE"; set +a
  LITELLM_MASTER="${LITELLM_MASTER_KEY:-${LITELLM_MASTER:-}}"
fi
[[ -n "${LITELLM_MASTER}" ]] || { echo "audit: LITELLM_MASTER_KEY not set" >&2; exit 1; }

NOW_TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
TODAY="$(date -u +%F)"
REPORT_FILE="$KEYWATCH_REPORTS_DIR/key-audit-$TODAY.md"
mkdir -p "$KEYWATCH_REPORTS_DIR" "$KEYWATCH_STATE_DIR"

# --- live inventory (keys + MCP group names) --------------------------
RAW_KEYS="$(_key_fetch_all)"
LIVE_JSON="$(ALL_JSON="$RAW_KEYS" \
  LITELLM_MASTER="$LITELLM_MASTER" LITELLM_PROXY="$LITELLM_PROXY" python3 - <<'PY'
import os, json, urllib.request

keys = json.loads(os.environ["ALL_JSON"])
ids = sorted({g for k in keys for g in (k.get("access_group_ids") or [])})
groups = {}
for gid in ids:
    try:
        req = urllib.request.Request(
            os.environ["LITELLM_PROXY"] + "/v1/access_group/" + gid,
            headers={"Authorization": "Bearer " + os.environ["LITELLM_MASTER"]})
        with urllib.request.urlopen(req, timeout=10) as r:
            d = json.load(r)
        groups[gid] = d.get("access_group_name", gid)
    except Exception:
        groups[gid] = gid

for k in keys:
    k["access_groups"] = sorted(groups.get(g, g) for g in (k.get("access_group_ids") or []))
print(json.dumps(keys))
PY
)"

if (( JSON_ONLY )); then
  echo "$LIVE_JSON"
  exit 0
fi

# --- audit (drift vs snapshot + rotation-due + blocked + spend) ------
AUDIT_OUT="$(LIVE_JSON="$LIVE_JSON" \
  SNAPSHOT_FILE="$KEYWATCH_AUDIT_SNAPSHOT_FILE" \
  ROTATION_DAYS="$ROTATION_DUE_DAYS" \
  NOW_TS="$NOW_TS" python3 - <<'PY'
import os, sys, json, datetime

live = json.loads(os.environ["LIVE_JSON"])
snap_file = os.environ["SNAPSHOT_FILE"]
rot_days = int(os.environ["ROTATION_DAYS"])
now_ts = os.environ["NOW_TS"]

snap = []
if os.path.exists(snap_file):
    try:
        with open(snap_file) as f:
            snap = json.load(f)
    except Exception:
        snap = []

def key_id(k):
    return k.get("alias") or k.get("key_name") or k.get("hash", "?")[:12]

live_by_id = {key_id(k): k for k in live}
snap_by_id = {key_id(k): k for k in snap}

findings = []   # (severity, check, detail)

# drift
for kid in sorted(set(live_by_id) - set(snap_by_id)):
    findings.append(("alert", "key-drift", f"NEW key not in snapshot: {kid} (user={live_by_id[kid].get('user_id') or '—'})"))
for kid in sorted(set(snap_by_id) - set(live_by_id)):
    findings.append(("alert", "key-drift", f"key in snapshot but MISSING live: {kid}"))
for kid in sorted(set(live_by_id) & set(snap_by_id)):
    l, s = live_by_id[kid], snap_by_id[kid]
    changed = []
    for field, label in (("user_id", "user"), ("models", "models"),
                         ("access_groups", "MCP groups"), ("max_budget", "budget"),
                         ("rpm_limit", "rpm"), ("tpm_limit", "tpm"), ("blocked", "blocked")):
        lv = l.get(field)
        sv = s.get(field)
        if isinstance(lv, list):
            lv, sv = sorted(map(str, lv or [])), sorted(map(str, sv or []))
        if lv != sv:
            changed.append(f"{label}: {sv!r} -> {lv!r}")
    if changed:
        findings.append(("alert", "key-drift", f"key {kid} CHANGED: " + "; ".join(changed)))

# rotation due
# NOTE: /key/info returns +00:00-suffixed (aware) timestamps while
# now_ts is naive — normalize both to aware UTC before subtracting.
def parse_dt(s):
    d = datetime.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    if d.tzinfo is None:
        d = d.replace(tzinfo=datetime.timezone.utc)
    return d

now = parse_dt(now_ts)
for k in live:
    created = k.get("created_at")
    if not created:
        continue
    try:
        c = parse_dt(created)
    except Exception:
        continue
    age_days = (now - c).days
    if age_days > rot_days:
        findings.append(("note", "rotation-due",
            f"key {key_id(k)} is {age_days}d old (created {str(created)[:10]}) — quarterly rotation due (./homelab.sh key rotate {key_id(k)})"))

# blocked
for k in live:
    if k.get("blocked"):
        findings.append(("note", "blocked-key", f"key {key_id(k)} is BLOCKED — verify intentional"))

print(json.dumps({
    "live": live,
    "snapshot_exists": bool(snap),
    "findings": [list(f) for f in findings],
}, indent=2))
PY
)"

# --- --update-snapshot -------------------------------------------------
if (( UPDATE_SNAPSHOT )); then
  echo "$LIVE_JSON" > "$KEYWATCH_AUDIT_SNAPSHOT_FILE"
  echo "snapshot updated: $KEYWATCH_AUDIT_SNAPSHOT_FILE"
fi

# --- report ------------------------------------------------------------
FINDINGS_JSON="$(echo "$AUDIT_OUT" | python3 -c "import sys,json; print(json.dumps(json.load(sys.stdin)['findings']))")"
N_FINDINGS="$(echo "$FINDINGS_JSON" | python3 -c "import sys,json; print(len(json.load(sys.stdin)))")"
N_ALERTS="$(echo "$FINDINGS_JSON" | python3 -c "import sys,json; print(sum(1 for f in json.load(sys.stdin) if f[0]=='alert'))")"
N_NOTES="$(echo "$FINDINGS_JSON" | python3 -c "import sys,json; print(sum(1 for f in json.load(sys.stdin) if f[0]=='note'))")"

# alerts.log (drift findings only — rotation/blocked are cadence notes,
# they go in the report, not the alert feed)
SEV="alert"
(( OBSERVATION_MODE == 1 )) && SEV="note"
while IFS= read -r line; do
  [[ -n "$line" ]] || continue
  printf '%s | %s | key-audit | %s\n' "$NOW_TS" "$SEV" "$line" >> "$KEYWATCH_ALERTS_LOG"
done < <(echo "$FINDINGS_JSON" | python3 -c "
import sys, json
for sev, check, detail in json.load(sys.stdin):
    if sev == 'alert':
        print(detail)
")

# --- pre-compute markdown tables (env-fed heredocs — safe from bash
# expansion AND the heredoc-vs-pipe stdin race; see key-auth-watch note)
TABLE_ROWS="$(LIVE_JSON="$LIVE_JSON" python3 - <<'PY'
import os, json, datetime
for k in json.loads(os.environ["LIVE_JSON"]):
    alias = k.get('alias') or '*(no alias)*'
    def d(v):
        try:
            return datetime.datetime.fromisoformat(str(v).replace('Z', '+00:00')).strftime('%Y-%m-%d')
        except Exception:
            return str(v)[:10] if v else '—'
    models = ', '.join(k.get('models') or []) or 'all'
    groups = ', '.join(k.get('access_groups') or []) or 'none'
    budget = k.get('max_budget')
    budget_s = ('$' + format(budget, 'g')) if budget is not None else 'none'
    rpm, tpm = k.get('rpm_limit'), k.get('tpm_limit')
    rate = '{}/{}'.format(rpm, tpm) if (rpm or tpm) else 'none'
    print('| `{}` | {} | {} | {} | {} | {} | ${:.2f} | {} | {} | {} |'.format(
        alias, k.get('user_id') or '—', models, groups, budget_s, rate,
        k.get('spend') or 0, d(k.get('created_at')), d(k.get('last_active')),
        'YES' if k.get('blocked') else ''))
PY
)"

FINDINGS_ROWS="$(FINDINGS_JSON="$FINDINGS_JSON" python3 - <<'PY'
import os, json
for sev, check, detail in json.loads(os.environ["FINDINGS_JSON"]):
    print('| {} | {} | {} |'.format(sev, check, detail))
PY
)"

{
  echo "# Key Audit — $TODAY"
  echo
  echo "- generated: $NOW_TS"
  echo "- snapshot: $KEYWATCH_AUDIT_SNAPSHOT_FILE"
  echo "  ($([[ -f "$KEYWATCH_AUDIT_SNAPSHOT_FILE" ]] && echo "present" || echo "MISSING — first run: review then --update-snapshot"))"
  echo "- findings: $N_FINDINGS ($N_ALERTS drift/alert, $N_NOTES notes)"
  echo
  echo "verdict: $N_ALERTS drift finding(s), $N_NOTES note(s)"
  echo
  echo "## Live inventory"
  echo
  echo "| key_alias | user | models | MCP groups | budget | rpm/tpm | spend | created | last active | blocked |"
  echo "|---|---|---|---|---|---|---|---|---|---|"
  echo "$TABLE_ROWS"
  echo
  echo "## Findings"
  echo
  if (( N_FINDINGS == 0 )); then
    echo "(none — live inventory matches snapshot, no rotation due, nothing blocked)"
  else
    echo "| severity | check | detail |"
    echo "|---|---|---|"
    echo "$FINDINGS_ROWS"
  fi
} > "$REPORT_FILE"

echo "audit complete: $N_FINDINGS finding(s) ($N_ALERTS drift, $N_NOTES notes)"
echo "  report: $REPORT_FILE"
(( N_ALERTS > 0 )) && exit 1
exit 0
