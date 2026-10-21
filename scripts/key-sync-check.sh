#!/usr/bin/env bash
# key-sync-check.sh — detect stale API keys in running containers.
#
# 2026-10-21 incident: mcp_skills presented a STALE LITELLM_KEY_CHUCK (the
# key was rotated in .env during the per-user-key workstream, but the
# container was never recreated). skill-runner does exact-match
# allow-listing against SKILL_RUNNER_API_KEY (chuck,dylan keys) → 403
# "Invalid API key" on every mcp_skills call (list_skills, run_skill).
#
# What it checks (security-critical vars only — not a blanket env diff):
#   1. Explicit key vars, wherever they appear in a container:
#      LITELLM_KEY_CHUCK, LITELLM_KEY_DYLAN, LITELLM_API_KEY,
#      MEMORY_USER_KEY, MEMORY_LITELLM_KEY, MEMORY_ADMIN_API_KEY,
#      GITHUB_ACCESS_TOKEN, GITHUB_RUNNER_TOKEN
#   2. Any .env var matching (_API_KEY|_TOKEN|_SECRET|_PASS|_PASSWORD)$
#      (catches future additions).
#   3. SKILL_RUNNER_API_KEY with per-container semantics:
#      - skill-runner: allow-list — must CONTAIN the current chuck+dylan keys
#      - any other container (mcp_skills, mcp_memory, ...): must EXACTLY
#        equal LITELLM_KEY_CHUCK (single-key presenter rule)
#   4. MEMORY_USER_KEYS (identity map): the container's resolved
#      user=KEY pairs must match the referenced .env key values.
#
# Excluded (intentional per-container differences / name collisions):
#   TZ, DATABASE_URL, and any .env var whose value is a ${...} template
#   (containers carry the resolved value).
#
# Run it after: (a) rotating any key in .env, (b) any docker compose
# up/recreate, (c) unattended-upgrades restarts of long-lived services.
#
# Usage:  scripts/key-sync-check.sh
# Exit:   0 = all in sync · 1 = drift detected (recreate the flagged
#         container: docker compose --env-file .env -f <file> up -d <ctr>)
set -uo pipefail

cd "$(dirname "$0")/.."
ENV_FILE=.env
[ -f "$ENV_FILE" ] || { echo "no $ENV_FILE at repo root" >&2; exit 1; }

# ── Load .env vars ───────────────────────────────────────────────────
declare -A ENVVARS
while IFS= read -r line; do
  [[ "$line" =~ ^[A-Z_][A-Z0-9_]*= ]] || continue
  ENVVARS["${line%%=*}"]="${line#*=}"
done < "$ENV_FILE"

mask() { echo "${1:0:12}..."; }

# ── Build the check set (security-critical vars only) ────────────────
declare -A CHECKVARS=()
for k in LITELLM_KEY_CHUCK LITELLM_KEY_DYLAN LITELLM_API_KEY \
         MEMORY_USER_KEY MEMORY_LITELLM_KEY MEMORY_ADMIN_API_KEY \
         GITHUB_ACCESS_TOKEN GITHUB_RUNNER_TOKEN \
         SKILL_RUNNER_API_KEY MEMORY_USER_KEYS; do
  CHECKVARS[$k]=1   # checked wherever it appears (SKILL_RUNNER_API_KEY is not in .env)
done
for k in "${!ENVVARS[@]}"; do
  case "$k" in
    *_API_KEY|*_TOKEN|*_SECRET|*_PASS|*_PASSWORD)
      v="${ENVVARS[$k]}"
      [[ "$v" == *'${'* ]] && continue   # template — containers hold resolved values
      CHECKVARS[$k]=1 ;;
  esac
done
nvars=${#CHECKVARS[@]}

drift=0
checked=0
containers=0
per_container=()
drift_lines=()
declare -A ctr_drift

compose_of() {
  local f
  f=$(grep -lE "container_name: $1\b" compose/*.yml 2>/dev/null | head -1)
  [ -n "$f" ] && echo "$f" || echo "<compose file>"
}

# ── Per-container scan (docker inspect — read-only, no exec) ─────────
for ctr in $(docker ps --format '{{.Names}}'); do
  containers=$((containers + 1))
  cenv=$(docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$ctr" 2>/dev/null || true)
  ctr_drift[$ctr]=0
  ctr_checked=0
  for k in "${!CHECKVARS[@]}"; do
    line=$(printf '%s\n' "$cenv" | grep -E "^${k}=" | head -1 || true)
    [ -n "$line" ] || continue
    cv="${line#*=}"
    checked=$((checked + 1))
    ctr_checked=$((ctr_checked + 1))

    if [ "$k" = "SKILL_RUNNER_API_KEY" ] && [ "$ctr" = "skill-runner" ]; then
      # Allow-list semantics: must contain BOTH current user keys.
      ok=1
      for keyvar in LITELLM_KEY_CHUCK LITELLM_KEY_DYLAN; do
        v="${ENVVARS[$keyvar]:-}"
        [ -n "$v" ] || continue
        printf ',%s,' "$cv" | grep -qF ",$v," || ok=0
      done
      if [ "$ok" -eq 1 ]; then continue; fi
      drift=$((drift + 1)); ctr_drift[$ctr]=$((ctr_drift[$ctr] + 1))
      drift_lines+=("DRIFT ${ctr}: SKILL_RUNNER_API_KEY allow-list is missing the current user key(s) — fix: docker compose --env-file .env -f $(compose_of "$ctr") up -d ${ctr}")
      continue
    fi
    if [ "$k" = "SKILL_RUNNER_API_KEY" ] || [ "$k" = "MEMORY_USER_KEY" ]; then
      # Presenter semantics: must EXACTLY equal the chuck key.
      # (SKILL_RUNNER_API_KEY: mcp_skills/mcp_memory present it to
      #  skill-runner; MEMORY_USER_KEY: mcp_memory's fallback identity key,
      #  compose-mapped from ${LITELLM_KEY_CHUCK}.)
      [ "$cv" = "${ENVVARS[LITELLM_KEY_CHUCK]}" ] && continue
      drift=$((drift + 1)); ctr_drift[$ctr]=$((ctr_drift[$ctr] + 1))
      drift_lines+=("DRIFT ${ctr}: SKILL_RUNNER_API_KEY is stale (container=$(mask "$cv") .env chuck key=$(mask "${ENVVARS[LITELLM_KEY_CHUCK]}")) — fix: docker compose --env-file .env -f $(compose_of "$ctr") up -d ${ctr}")
      continue
    fi
    if [ "$k" = "MEMORY_USER_KEYS" ]; then
      # Identity map template: values are ENV-VAR NAMES, resolved at runtime
      # (identity.py). The container must carry the same template as .env;
      # the referenced vars (LITELLM_KEY_CHUCK, ...) are checked individually.
      [ "$cv" = "${ENVVARS[MEMORY_USER_KEYS]}" ] && continue
      drift=$((drift + 1)); ctr_drift[$ctr]=$((ctr_drift[$ctr] + 1))
      drift_lines+=("DRIFT ${ctr}: MEMORY_USER_KEYS identity-map template differs from .env — fix: docker compose --env-file .env -f $(compose_of "$ctr") up -d ${ctr}")
      continue
    fi
    # Plain exact match (guard: check-set var may be absent from .env).
    ev="${ENVVARS[$k]:-}"
    if [ -z "$ev" ]; then
      drift=$((drift + 1)); ctr_drift[$ctr]=$((ctr_drift[$ctr] + 1))
      drift_lines+=("DRIFT ${ctr}: ${k} is set in the container but not defined in .env — review (stale/legacy key?)")
      continue
    fi
    [ "$cv" = "$ev" ] && continue
    drift=$((drift + 1)); ctr_drift[$ctr]=$((ctr_drift[$ctr] + 1))
    drift_lines+=("DRIFT ${ctr}: ${k} container=$(mask "$cv") .env=$(mask "$ev") — fix: docker compose --env-file .env -f $(compose_of "$ctr") up -d ${ctr}")
  done
  if [ "${ctr_drift[$ctr]}" -eq 0 ]; then
    per_container+=("  OK   ${ctr} (${ctr_checked} key vars compared)")
  else
    per_container+=("  FAIL ${ctr} (${ctr_drift[$ctr]}/${ctr_checked} key vars drifted)")
  fi
done

# ── Report ───────────────────────────────────────────────────────────
echo "key-sync-check: ${nvars} security-critical .env vars x ${containers} running containers (${checked} comparisons)"
for l in "${per_container[@]}"; do
  echo "$l"
done
if [ "$drift" -eq 0 ]; then
  echo "RESULT: ALL IN SYNC — no stale keys detected."
  exit 0
else
  echo
  for l in "${drift_lines[@]}"; do
    echo "  $l"
  done
  echo "RESULT: DRIFT DETECTED (${drift}) — recreate the flagged container(s), then re-run."
  exit 1
fi