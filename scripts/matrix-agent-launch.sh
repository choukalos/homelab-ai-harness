#!/usr/bin/env bash
# matrix-agent-launch.sh — launch a Matrix agent job (pi session) with the
# CALLER's LiteLLM virtual key (agent-job key pass-through).
#
# Contracts:
#   - Matrix contract of record: docs/matrix_key_passthrough.md (Matrix repo)
#   - Handoff: thor_key_passthrough_handoff.md (T1 transport, T2 hygiene, T3 intake)
#   - Thor-side contract doc: docs/thor_key_passthrough.md
#
# T2 key hygiene (hard rules):
#   * The key is taken from the MATRIX_CALLER_KEY env var or from stdin (line 1)
#     — NEVER from argv. It never appears in any command line (ps), shell
#     history, or log on thor.
#   * The key is never written to disk by this script; it lives only in this
#     process's transient state and the ssh stdin channel (T2 rule 3: ephemeral).
#   * All output — including the remote job's stdout/stderr — is passed through
#     redact() before it reaches stdout/stderr, masking sk-… patterns (T2 rule 2).
#   * The caller's key is used as-is; this script never substitutes chuck's or
#     thor's key (T2 rule 4).
#
# T3 intake validation:
#   * The key must be non-empty and shaped like a LiteLLM virtual key (sk-…).
#   * Malformed/empty keys are rejected (exit 2) before any ssh attempt.
#   * Nothing is stored beyond this process's lifetime.
#
# Transport (T1):
#   ssh to the dedicated `matrix-agent` alias (chuck@192.168.4.55). The Matrix
#   authorized_keys line forces command="/home/chuck/homelab/scripts/run-with-key.sh"
#   (no arguments), so the job envelope rides ssh stdin — never argv:
#     line 1 = the caller's LiteLLM virtual key
#     line 2 = the pi args as a JSON array, e.g. ["-p","Reply OK"]
#   The Matrix wrapper reads this envelope when invoked with no argv (stdin
#   mode); its argv[1] contract is unchanged for local/interactive use.
#
# Usage:
#   matrix-agent-launch.sh -- <pi args...>
#   Key source: $MATRIX_CALLER_KEY (env) or stdin line 1 (env wins).
#
#   MATRIX_CALLER_KEY=sk-… scripts/matrix-agent-launch.sh -- -p "Reply OK"
#   printf '%s\n' "$CALLER_KEY" | scripts/matrix-agent-launch.sh -- -p "..."
#
# Exit codes:
#   0   job ran and pi exited 0
#   2   intake/usage error (malformed/empty key, no pi args) — no ssh attempt
#   N   otherwise the remote job's (ssh) exit code
set -euo pipefail

SSH_TARGET="matrix-agent"
REMOTE_ENTRY="/home/chuck/homelab/scripts/run-with-key.sh"

log() { printf 'matrix-agent-launch: %s\n' "$*" >&2; }
die() { log "ERROR: $*"; exit 2; }

# T2: mask sk-… patterns in anything that reaches a log path.
redact() {
  sed -E 's/sk-[A-Za-z0-9_-]{6,}/sk-***REDACTED***/g'
}

# ---------------------------------------------------------------- usage ----
# pi args must follow `--`. The key is NEVER an argument (T2 rule 1) — unknown
# leading options are rejected so a key can never be passed as an argument.
pi_args=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --) shift; pi_args=("$@"); break ;;
    -h|--help) sed -n '2,/^set -euo pipefail$/p' "$0" | sed 's/^# \{0,1\}//' | redact; exit 0 ;;
    *) die "unknown option '$1' — pi args must follow '--' (the key is never an argument; set MATRIX_CALLER_KEY or pipe it on stdin)" ;;
  esac
done

[[ ${#pi_args[@]} -ge 1 ]] || die "no pi args (usage: matrix-agent-launch.sh -- <pi args...>, e.g. -- -p \"Reply OK\")"

# ------------------------------------------------- T3 intake validation ----
key="${MATRIX_CALLER_KEY:-}"
if [[ -z "$key" && ! -t 0 ]]; then
  IFS= read -r key || key=""
fi

if [[ -z "$key" ]]; then
  die "no caller key — set MATRIX_CALLER_KEY or pipe the key on stdin (keyless launches are rejected; T3)"
fi
if [[ ! "$key" =~ ^sk-[A-Za-z0-9_-]{6,}$ ]]; then
  # Never print the key itself — report length/shape only.
  die "caller key has an invalid shape (expected a LiteLLM virtual key 'sk-…'; got ${#key} chars) — rejected (T3)"
fi

# ------------------------------------------------------------- envelope ----
args_json="$(python3 -c 'import json, sys; print(json.dumps(sys.argv[1:]))' "${pi_args[@]}")"

log "launching agent job on $SSH_TARGET ($REMOTE_ENTRY)"
log "pi args (redacted): $(printf '%s\n' "${pi_args[@]}" | redact | tr '\n' ' ')"
log "key: via stdin only (env/stdin, never argv); not stored; all output redacted"

# T2: the key rides ssh stdin as line 1 of a here-string — never argv, never
# disk. Remote output (stdout+stderr) is redacted before it is printed.
rc=0
set +e
ssh -o BatchMode=yes -o ConnectTimeout=10 -o ServerAliveInterval=30 \
    "$SSH_TARGET" "$REMOTE_ENTRY" <<<"$key"$'\n'"$args_json" 2>&1 | redact
rc=${PIPESTATUS[0]}
set -e

if [[ $rc -ne 0 ]]; then
  log "job ended with exit code $rc (output above is redacted)"
  exit "$rc"
fi
log "job completed (exit 0)"
