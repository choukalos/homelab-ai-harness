#!/usr/bin/env bash
# rotate-github-tokens.sh — rotate the homelab's GitHub PAT(s) in .env.
#
# GitHub REMOVED the classic-PAT creation API endpoint (POST /user/tokens
# -> 404, verified 2026-11-21), so the NEW PAT is minted in the GitHub UI
# and this script takes it, verifies it, and applies it deterministically:
#
#   1. Preflight: .env present, old token set + still valid (GET /user).
#   2. Discovery:
#      - DIRECT CONSUMERS: compose services whose `environment` references
#        ${GITHUB_ACCESS_TOKEN} / ${KANBAN_GITHUB_TOKEN} (parsed from
#        compose/*.yml — self-maintaining, no hardcoded list). Current set
#        (2026-11-21): github-runner, data-hub-runner, report-hub-runner
#        (via ACCESS_TOKEN) + mcp_kanban (via GITHUB_TOKEN).
#      - CARRIERS: every running container whose live env holds the old
#        VALUE (whole-.env injection: caddy, cloudflared, skill-runner,
#        searxng, plausible, the hubs, ...). They do not USE the token;
#        they are reported, not touched — they refresh on their next
#        recreate, and key-sync-check tracks them until then.
#   3. Kanban sync: if KANBAN_GITHUB_TOKEN holds the SAME value as the
#      target var, it is swapped too (current state 2026-11-21: both vars
#      share one PAT — the runners' token was reused for mcp_kanban).
#   4. New token: --new-token-file PATH (first line) or interactive hidden
#      paste. Verified against the API (GET /user) BEFORE anything is
#      touched — an invalid token aborts with zero side effects.
#   5. Backs up .env (.env.bak-<timestamp>), swaps the value(s) atomically.
#   6. Recreates the direct consumers via their compose labels
#      (com.docker.compose.project / .service / .project.config_files),
#      waits for running/healthy.
#   7. Verifies: each direct consumer holds the NEW value and no direct
#      consumer holds the old one; remaining carriers are reported;
#      scripts/key-sync-check.sh runs — drift limited to carriers is
#      expected (informational), drift on a direct consumer fails the run.
#   8. Reports: masked old token + manual revocation steps (the old PAT
#      stays valid until revoked in the UI — classic PATs cannot be
#      revoked via the API), and a note about GITHUB_RUNNER_TOKEN
#      (fine-grained PAT, currently unconsumed — revoke in the UI and drop
#      the .env line if you agree it's dead).
#
# Minting in the UI (do this BEFORE running the script):
#   https://github.com/settings/tokens  ->  "Generate new token (classic)"
#   - scopes:    `repo` (covers runner auth + kanban deploy pushes)
#   - expiration: 120–365 days (a 120-day expiry on a 90-day rotation
#     cadence makes a forgotten rotation fail closed)
#   - note:      "homelab GITHUB_ACCESS_TOKEN rotated <YYYY-MM-DD>"
#     (this is how you'll find it at the next revocation)
#   The script is token-type-agnostic (it verifies the new token works),
#   so a fine-grained PAT with the right repo permissions is acceptable
#   too — but runners currently expect classic `repo` scope.
#
# Safety:
#   - --dry-run shows the full plan and changes nothing.
#   - Confirmation prompt before any mutation (skip with --yes; --yes
#     requires --new-token-file).
#   - Tokens are never printed in full (masked to 12 chars); the paste
#     prompt is hidden (read -s).
#   - .env is backed up before any edit; the new token is verified BEFORE
#     the backup/swap, so a bad token leaves the system untouched.
#   - Only DIRECT consumers are recreated — session-carrying or public-edge
#     containers that merely carry the .env (skill-runner, caddy,
#     cloudflared, ...) are left running.
#   - Runner registrations survive rotation: the myoung34/github-runner
#     containers persist /runner/data with DISABLE_AUTOMATIC_DEREGISTRATION,
#     so only the API token changes — no re-registration needed.
#
# Usage:
#   scripts/rotate-github-tokens.sh [--dry-run] [--yes] [--var NAME]
#                                   [--new-token-file PATH] [--no-recreate]
#
#   --var NAME           env var holding the token to rotate
#                        (default GITHUB_ACCESS_TOKEN; use KANBAN_GITHUB_TOKEN
#                        if it ever diverges from the runners' token)
#   --new-token-file P   read the new token from file P (first line,
#                        whitespace-trimmed) — required with --yes; without
#                        it an interactive hidden paste is used
#   --no-recreate        swap .env only; skip container recreation
#
# Exit: 0 = rotated + verified · 1 = failed/aborted · 2 = preflight failure
#
# Run scripts/key-sync-check.sh after ANY key change (this script does it
# automatically at the end).
set -euo pipefail

cd "$(dirname "$0")/.."
REPO_ROOT="$(pwd)"
ENV_FILE="$REPO_ROOT/.env"

# ── Defaults / flags ───────────────────────────────────────────────────────
TARGET_VAR="GITHUB_ACCESS_TOKEN"
NEW_TOKEN_FILE=""
DRY_RUN=0
ASSUME_YES=0
NO_RECREATE=0

usage() { awk 'NR>1 && /^set -euo pipefail/{exit} NR>1{sub(/^# ?/,""); print}' "$0"; }

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY_RUN=1 ;;
    --yes|-y) ASSUME_YES=1 ;;
    --var) TARGET_VAR="${2:?--var needs a value}"; shift ;;
    --new-token-file) NEW_TOKEN_FILE="${2:?--new-token-file needs a path}"; shift ;;
    --no-recreate) NO_RECREATE=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown flag: $1 (see --help)" >&2; exit 2 ;;
  esac
  shift
done

mask() { local v="$1"; [ ${#v} -le 12 ] && { echo "(short)"; return; }; echo "${v:0:12}..."; }
step() { echo; echo "── $1"; }
die()  { echo; echo "ABORT: $*" >&2; exit 1; }
die2() { echo; echo "PREFLIGHT FAILURE: $*" >&2; exit 2; }

# ── 1. Preflight ───────────────────────────────────────────────────────────
step "Preflight"
[ -f "$ENV_FILE" ] || die2 "no .env at $ENV_FILE"
command -v curl >/dev/null || die2 "curl not found"
command -v python3 >/dev/null || die2 "python3 not found"

OLD_TOKEN="$(grep -E "^${TARGET_VAR}=" "$ENV_FILE" | head -1 | cut -d= -f2- || true)"
[ -n "$OLD_TOKEN" ] || die2 "$TARGET_VAR not set (or empty) in .env"
echo "target var:  $TARGET_VAR = $(mask "$OLD_TOKEN")"

# Kanban sync check
KANBAN_TOKEN="$(grep -E '^KANBAN_GITHUB_TOKEN=' "$ENV_FILE" | head -1 | cut -d= -f2- || true)"
KANBAN_SYNC=0
if [ -n "$KANBAN_TOKEN" ]; then
  if [ "$KANBAN_TOKEN" = "$OLD_TOKEN" ]; then
    KANBAN_SYNC=1
    echo "kanban sync: KANBAN_GITHUB_TOKEN holds the SAME token — it will be swapped too"
  elif [ "$TARGET_VAR" = "GITHUB_ACCESS_TOKEN" ]; then
    echo "note: KANBAN_GITHUB_TOKEN is a DIFFERENT token ($(mask "$KANBAN_TOKEN")) — NOT touched by this run"
  fi
fi

# Old token must still work (sanity: it's what consumers use today)
step "Old-token validity (GET /user)"
HTTP="$(curl -sS -o /tmp/rotate-gh-user.json -w '%{http_code}' \
  -H "Authorization: token $OLD_TOKEN" \
  -H "Accept: application/vnd.github+json" \
  https://api.github.com/user)" || die "cannot reach api.github.com"
LOGIN="$(python3 -c "import json;print(json.load(open('/tmp/rotate-gh-user.json')).get('login',''))" 2>/dev/null || true)"
[ "$HTTP" = "200" ] || die "old token rejected by GitHub (HTTP $HTTP) — it is already dead/invalid; set a working $TARGET_VAR in .env first"
echo "old token valid — github user: $LOGIN"
rm -f /tmp/rotate-gh-user.json

# ── 2. Discovery ───────────────────────────────────────────────────────────
step "Discovery: direct consumers (compose source parse)"
CONSUMERS="$(TARGET_VAR="$TARGET_VAR" KANBAN_SYNC="$KANBAN_SYNC" python3 <<'PYEOF'
import glob, os, re, subprocess, yaml
target = os.environ["TARGET_VAR"]
ksync = os.environ.get("KANBAN_SYNC") == "1"
varnames = [target] + (["KANBAN_GITHUB_TOKEN"] if ksync else [])
# Match ${VAR}, ${VAR:-default}, ${VAR-default}, ${VAR:+alt} forms
patterns = [re.compile(r"\$\{" + re.escape(v) + r"(?::[-+?][^}]*)?\}") for v in varnames]
running = set(subprocess.run(["docker","ps","--format","{{.Names}}"],
                             capture_output=True, text=True).stdout.split())
for f in sorted(glob.glob("compose/*.yml")):
    try:
        doc = yaml.safe_load(open(f)) or {}
    except Exception:
        continue
    for svc, s in (doc.get("services") or {}).items():
        if not isinstance(s, dict):
            continue
        env = s.get("environment") or []
        entries = [f"{k}={v}" for k, v in env.items()] if isinstance(env, dict) else list(env)
        if any(any(p.search(e) for p in patterns) for e in entries if isinstance(e, str)):
            cname = s.get("container_name") or svc
            print(f"{'RUNNING' if cname in running else 'STOPPED'}\t{f}\t{svc}\t{cname}")
PYEOF
)"
if [ -n "$CONSUMERS" ]; then
  echo "$CONSUMERS" | awk -F'\t' '{printf "  %-8s %-22s (%s)\n", $1, $4, $2}'
else
  echo "  (none found — .env swap only)"
fi

step "Discovery: carriers (live env holds the old value — reported, not touched)"
CARRIERS="$(python3 - "$OLD_TOKEN" <<'PYEOF'
import subprocess, sys
old = sys.argv[1]
names = subprocess.run(["docker","ps","--format","{{.Names}}"],
                       capture_output=True, text=True).stdout.split()
for n in names:
    out = subprocess.run(["docker","inspect","--format",
        "{{range .Config.Env}}{{println .}}{{end}}", n],
        capture_output=True, text=True).stdout
    if any(l.split("=",1)[1] == old for l in out.splitlines() if "=" in l):
        print(n)
PYEOF
)"
if [ -n "$CARRIERS" ]; then
  echo "$CARRIERS" | sed 's/^/  /' | tr '\n' ' '; echo
  echo "  (whole-.env injection; they don't use the token — refresh on next recreate)"
else
  echo "  (none)"
fi

# GITHUB_RUNNER_TOKEN advisory
RUNNER_TOKEN="$(grep -E '^GITHUB_RUNNER_TOKEN=' "$ENV_FILE" | head -1 | cut -d= -f2- || true)"
if [ -n "$RUNNER_TOKEN" ] && [ "$RUNNER_TOKEN" != "$OLD_TOKEN" ]; then
  echo "advisory: GITHUB_RUNNER_TOKEN is set ($(mask "$RUNNER_TOKEN"), fine-grained PAT)" \
       "but is consumed by NO compose file or container (leftover from the" \
       "original invest-hub runner setup). If you agree it is dead: revoke it" \
       "at https://github.com/settings/tokens and delete the line from .env."
fi

# ── 3. Plan + confirm ─────────────────────────────────────────────────────
step "Plan"
if [ -n "$NEW_TOKEN_FILE" ]; then
  echo "  new token: from $NEW_TOKEN_FILE (minted in the GitHub UI)"
else
  echo "  new token: interactive hidden paste (mint it in the GitHub UI first:"
  echo "    https://github.com/settings/tokens -> Generate new token (classic)"
  echo "    scopes=repo, expiry 120-365d, note 'homelab ${TARGET_VAR} rotated <date>')"
fi
echo "  .env: $TARGET_VAR <- new token"
[ "$KANBAN_SYNC" = "1" ] && echo "  .env: KANBAN_GITHUB_TOKEN <- new token (synced, same value)"
if [ "$NO_RECREATE" = "1" ]; then
  echo "  containers: --no-recreate (swap .env only; recreate manually later)"
else
  N_RUN="$(echo "$CONSUMERS" | grep -c '^RUNNING' || true)"
  N_STOP="$(echo "$CONSUMERS" | grep -c '^STOPPED' || true)"
  echo "  containers: recreate $N_RUN running direct consumers; $N_STOP stopped (left as-is)"
  echo "  carriers: left running (reported above; key-sync-check tracks them)"
fi
echo "  verify: consumers hold new value + scripts/key-sync-check.sh"

if [ "$DRY_RUN" = "1" ]; then
  step "Dry run — no changes made"
  exit 0
fi
if [ "$ASSUME_YES" = "0" ]; then
  printf "Proceed with rotation? [y/N] "
  read -r ans
  [ "$ans" = "y" ] || [ "$ans" = "Y" ] || { echo "aborted (no changes made)"; exit 1; }
fi

# ── 4. Provide + verify new token (BEFORE any side effect) ────────────────
step "Provide new token"
NEW_TOKEN=""
if [ -n "$NEW_TOKEN_FILE" ]; then
  [ -f "$NEW_TOKEN_FILE" ] || die "--new-token-file: no such file: $NEW_TOKEN_FILE"
  NEW_TOKEN="$(head -1 "$NEW_TOKEN_FILE" | tr -d '[:space:]')"
  [ -n "$NEW_TOKEN" ] || die "--new-token-file: file is empty: $NEW_TOKEN_FILE"
  echo "  new token read from $NEW_TOKEN_FILE: $(mask "$NEW_TOKEN")"
elif [ "$ASSUME_YES" = "1" ]; then
  die "--yes requires --new-token-file (no interactive paste possible)"
else
  printf "Paste the new token (hidden, Enter to submit): "
  read -r -s NEW_TOKEN || die "no token provided"
  echo
  [ -n "$NEW_TOKEN" ] || die "no token provided"
  echo "  new token: $(mask "$NEW_TOKEN")"
fi

step "Verify new token (GET /user)"
HTTP="$(curl -sS -o /dev/null -w '%{http_code}' \
  -H "Authorization: token $NEW_TOKEN" \
  -H "Accept: application/vnd.github+json" https://api.github.com/user)"
[ "$HTTP" = "200" ] || die "new token rejected by GitHub (HTTP $HTTP) — .env untouched; mint a working token in the UI and rerun"
echo "  new token valid"

# ── 5. Backup + swap ──────────────────────────────────────────────────────
step "Backup .env"
TS="$(date +%Y%m%d-%H%M%S)"
BACKUP="$ENV_FILE.bak-$TS"
cp "$ENV_FILE" "$BACKUP"
echo "  backup: $BACKUP"

step "Swap .env values (atomic)"
python3 - "$ENV_FILE" "$TARGET_VAR" "$OLD_TOKEN" "$NEW_TOKEN" "$KANBAN_SYNC" <<'PYEOF'
import os, sys
path, var, old, new, kanban_sync = sys.argv[1:6]
lines = open(path).read().splitlines(keepends=True)
out, swapped = [], 0
for line in lines:
    if line.startswith(var + "="):
        out.append(f"{var}={new}\n"); swapped += 1
    elif kanban_sync == "1" and line.startswith("KANBAN_GITHUB_TOKEN=") and line.strip() == f"KANBAN_GITHUB_TOKEN={old}":
        out.append(f"KANBAN_GITHUB_TOKEN={new}\n"); swapped += 1
    else:
        out.append(line)
assert swapped >= 1, "no .env line matched the target var"
tmp = path + ".tmp"
open(tmp, "w").writelines(out)
os.replace(tmp, path)
print(f"  swapped {swapped} line(s)")
PYEOF

# ── 6. Recreate direct consumers ───────────────────────────────────────────
if [ "$NO_RECREATE" = "1" ]; then
  step "Skipping container recreation (--no-recreate)"
else
  step "Recreate direct consumers"
  RECREATED=""
  while IFS=$'\t' read -r kind file service cname; do
    [ "$kind" = "RUNNING" ] || continue
    LABELS="$(docker inspect --format '{{index .Config.Labels "com.docker.compose.project"}}|{{index .Config.Labels "com.docker.compose.service"}}|{{index .Config.Labels "com.docker.compose.project.config_files"}}' "$cname" 2>/dev/null || true)"
    project="${LABELS%%|*}"; rest="${LABELS#*|}"; service_l="${rest%%|*}"; config="${rest#*|}"
    if [ -n "$project" ] && [ -n "$service_l" ] && [ -n "$config" ]; then
      echo "  $cname (compose -p $project -f $config up -d --force-recreate $service_l)"
      docker compose -p "$project" -f "$config" up -d --force-recreate "$service_l" >/dev/null \
        || die "recreate failed for $cname — .env is already swapped; fix (docker logs $cname) then rerun with --no-recreate to finish verification"
      RECREATED="$RECREATED $cname"
    else
      echo "  $cname: no compose labels — recreate manually via $file (docker restart will NOT refresh env)"
    fi
  done <<< "$CONSUMERS"

  if [ -n "$(echo "$RECREATED" | tr -d ' ')" ]; then
    step "Wait for containers (running/healthy, ≤180 s each)"
    for name in $RECREATED; do
      ok=""
      for i in $(seq 1 60); do
        STATE="$(docker inspect --format '{{.State.Status}}{{if .State.Health}}|{{.State.Health.Status}}{{end}}' "$name" 2>/dev/null || echo missing)"
        case "$STATE" in
          running|running\|healthy) ok=1; break ;;
        esac
        sleep 3
      done
      if [ -n "$ok" ]; then
        echo "  $name: $STATE"
      else
        echo "  $name: TIMEOUT at '$STATE' — check docker logs $name"
        exit 1
      fi
    done
  else
    step "No running direct consumers to recreate"
  fi
fi

# ── 7. Verify ──────────────────────────────────────────────────────────────
step "Verify: direct consumers hold the NEW value (and not the old)"
VERIFY="$(python3 - "$OLD_TOKEN" "$NEW_TOKEN" "$CONSUMERS" <<'PYEOF'
import subprocess, sys
old, new = sys.argv[1], sys.argv[2]
consumers = [l.split("\t")[3] for l in sys.argv[3].splitlines()
             if l and l.startswith("RUNNING")]
fail = 0
for n in consumers:
    out = subprocess.run(["docker","inspect","--format",
        "{{range .Config.Env}}{{println .}}{{end}}", n],
        capture_output=True, text=True).stdout
    lines = [l for l in out.splitlines() if "=" in l]
    has_new = any(l.split("=",1)[1] == new for l in lines)
    has_old = any(l.split("=",1)[1] == old for l in lines)
    if has_new and not has_old:
        print(f"  OK   {n}: new token")
    else:
        fail = 1
        print(f"  FAIL {n}: new={has_new} old={has_old}")
sys.exit(fail)
PYEOF
)" || VERIFY_RC=1
VERIFY_RC="${VERIFY_RC:-0}"
echo "$VERIFY"
if [ "$VERIFY_RC" != "0" ]; then
  if [ "$NO_RECREATE" = "1" ]; then
    echo "  note: --no-recreate — consumers still hold the old token; recreate them when ready, then rerun with --no-recreate to re-verify"
  else
    die "direct-consumer verification failed — inspect the containers above (docker logs <name>)"
  fi
fi

step "Verify: remaining carriers (informational — drift until next recreate)"
LEFTOVER="$(python3 - "$OLD_TOKEN" <<'PYEOF'
import subprocess, sys
old = sys.argv[1]
names = subprocess.run(["docker","ps","--format","{{.Names}}"],
                       capture_output=True, text=True).stdout.split()
for n in names:
    out = subprocess.run(["docker","inspect","--format",
        "{{range .Config.Env}}{{println .}}{{end}}", n],
        capture_output=True, text=True).stdout
    if any(l.split("=",1)[1] == old for l in out.splitlines() if "=" in l):
        print(n)
PYEOF
)"
if [ -n "$LEFTOVER" ]; then
  echo "$LEFTOVER" | sed 's/^/  /' | tr '\n' ' '; echo
  echo "  (expected: whole-.env carriers; key-sync-check will list them until their next recreate)"
else
  echo "  (none — old value present in zero containers)"
fi

step "Verify: key-sync-check.sh"
if [ -x scripts/key-sync-check.sh ]; then
  SYNC_OUT="$(scripts/key-sync-check.sh 2>&1 || true)"
  echo "$SYNC_OUT" | tail -4
  if echo "$SYNC_OUT" | grep -q "ALL IN SYNC"; then
    :
  else
    # Fail only if a DIRECT consumer drifted; carrier-only drift is expected.
    BAD=""
    for line in $(echo "$SYNC_OUT" | grep -oE 'DRIFT [a-zA-Z0-9_-]+' | awk '{print $2}' | sort -u); do
      if echo "$CONSUMERS" | awk -F'\t' '{print $4}' | grep -qx "$line"; then
        BAD="$BAD $line"
      fi
    done
    if [ -n "$BAD" ]; then
      if [ "$NO_RECREATE" = "1" ]; then
        echo "  note: --no-recreate — direct consumer(s) stale:$BAD (expected); recreate them when ready"
      else
        die "key-sync-check: direct consumer(s) drifted:$BAD — investigate (docker logs <name>)"
      fi
    else
      echo "  note: drift limited to carriers (expected until their next recreate)"
    fi
  fi
else
  echo "  (scripts/key-sync-check.sh not found — skipped)"
fi

# ── 8. Report ──────────────────────────────────────────────────────────────
step "Done — rotation complete"
cat <<EOF
  .env updated: $TARGET_VAR = $(mask "$NEW_TOKEN")
EOF
if [ "$KANBAN_SYNC" = "1" ]; then
  echo "  .env updated: KANBAN_GITHUB_TOKEN = $(mask "$NEW_TOKEN") (synced)"
fi
echo "  backup of pre-rotation .env: $BACKUP"
cat <<EOF

  ⚠  THE OLD TOKEN IS STILL VALID until you revoke it (manual — GitHub PATs
     cannot be revoked via the API):
       1. https://github.com/settings/tokens
       2. find the OLD token: $(mask "$OLD_TOKEN")  (its full value is in the
          backup above; if you gave the NEW token a note like
          "homelab ${TARGET_VAR} rotated ...", the other one is the old)
       3. delete it
  Revoke promptly: until then both old and new tokens work.
EOF
if [ -n "$RUNNER_TOKEN" ] && [ "$RUNNER_TOKEN" != "$OLD_TOKEN" ]; then
  echo "  reminder: GITHUB_RUNNER_TOKEN (unused fine-grained PAT) — revoke in the UI + drop the .env line if dead."
fi
exit 0
