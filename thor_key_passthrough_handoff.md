# Thor handoff — agent-job key pass-through (caller key → Matrix pi)

> **For:** the Thor agent (owner of the LiteLLM proxy + client-facing services,
> `192.168.4.54`)
> **From:** Matrix (GPU host) — 2026-11-27
> **Status:** Matrix side READY (step 1 live, step 2 cutover scripted + gated).
> Thor side: **T1–T3 DONE 2026-11-28** (commit `505f417` — restricted
> Thor→Matrix SSH transport + `scripts/matrix-agent-launch.sh` + intake
> validation; Thor-side contract doc: `docs/thor_key_passthrough.md`).
> **T4 VERIFIED 2026-11-28 (partial)** — transport + keyless rejection +
> revoked-key fail-fast all PASS; the happy path is blocked on **2
> Matrix-side wrapper fixes** (see T4 below + `docs/thor_validation_log.md`
> part 15): (1) `pi` not in the forced-command PATH (exit 127 — add
> `export PATH="$HOME/.pi/agent/bin:$PATH"` before `exec pi`), (2) the
> wrapper pins the public proxy URL but caller keys only traverse the LAN
> (switch `LITELLM_BASE_URL` to `http://192.168.4.54:4000`). Re-run T4 once
> the fixes are live on Matrix.
> **Contract of record:** `docs/matrix_key_passthrough.md` (Matrix repo — pull
> current main). Cross-ref: `docs/matrix_thor_contract.md` v1.6.

---

## 1. Context (why this exists)

Client work that runs as **agent jobs on Matrix** (pi sessions, incl.
pi-long-task worker subagents) consumes LLM capacity through the Thor LiteLLM
proxy — the only auth boundary (Matrix endpoints are keyless LAN-only).

Before this change, all Matrix agent work billed to **chuck's key hard-copied in
Matrix's `~/.pi/agent/auth.json`**. The contract now: **the caller passes its own
LiteLLM virtual key with the job; the Matrix session (coordinator + worker
subagents) runs under that key.** Jobs launched without a key fail loudly
(`No API key found`) instead of silently billing chuck's key.

## 2. What's ready on Matrix (do not rebuild)

- **`scripts/run-with-key.sh <litellm-key> <pi args...>`** — the entry point.
  Exports `LITELLM_API_KEY` + `LITELLM_BASE_URL` and `exec`s `pi`. The env is
  inherited by all in-process worker subagents (pi-long-task workers resolve the
  key from `~/.pi/agent/models.json` `$ENV` interpolation — extensions are
  disabled in workers, verified 2026-11-27).
- **Verified mechanics** (contract doc §3): `pi --api-key` does NOT reach
  extension providers — the env var is the only reliable hook. Stored
  `auth.json` credentials beat the env var, so the step-2 scrub is what makes
  pass-through mandatory.
- **Step-2 cutover:** `scripts/enable-key-passthrough.sh` (removes chuck's
  hard copy; idempotent; aborts while a `pi -p` session runs). **Pending** —
  gated on the active films long task finishing. Until it runs, a keyless launch
  on Matrix still falls back to chuck's key.
- **No media-pipeline change:** `matrix:8189` makes no LLM calls (GPU work is
  ledger-metered) — `mcp_media` and the film skills are unaffected.

## 3. Thor-side work

> **T1–T3 DONE 2026-11-28** (commit `505f417`): the recommended SSH transport
> was implemented — restricted Thor→Matrix keypair
> (`~/.ssh/id_ed25519_matrix`, ssh alias `matrix-agent`), the forced-command
> `authorized_keys` line (run `run-with-key.sh` only, source-restricted to
> thor's IP), the stdin envelope protocol (line 1 = key, line 2 = pi args JSON
> — the key never appears in argv on either host),
> `scripts/matrix-agent-launch.sh` (intake validation: key shape check,
> never-logged hygiene), and the Thor-side contract doc
> `docs/thor_key_passthrough.md`. **Matrix install LIVE** — the T4 run
> (2026-11-28) exercised the restricted transport end-to-end (checks 3/4
> passed: keyless launch rejected, revoked key 401), so the `authorized_keys`
> line is installed and the forced command executes. The sections below are the original handoff spec, kept for reference.

### T1 — Transport (Thor → Matrix job launch) ✅ DONE 2026-11-28

There is **no Thor→Matrix SSH today** (no key installed; Matrix is reachable at
`192.168.4.55`, hostname `matrix`). Pick one:

- **Recommended:** install a restricted Thor→Matrix SSH key (dedicated user or
  command-restricted `authorized_keys` line limited to
  `/home/chuck/homelab/scripts/run-with-key.sh`), then launch:

  ```bash
  ssh chuck@matrix '/home/chuck/homelab/scripts/run-with-key.sh' \
    <<< "$CALLER_KEY"   # key via stdin — see T2
  ```

  (wrap so the key rides stdin/env, never argv — see T2)
- **Alternative:** reuse an existing Thor→Matrix relay (e.g. the filebridge
  pattern, `docs/thor_manual_tasks.md`) if one is extended to carry a
  job+key envelope.

Record the chosen transport in `docs/matrix_thor_contract.md` (new § or §10 note)
once live.

### T2 — Key hygiene (hard rules, both sides) ✅ DONE 2026-11-28 (enforced by the launch wrapper)

1. **Never in argv:** the key must not appear in a command line (visible in
   `ps` on both hosts, in shell history, in job logs). Pass via stdin or env:
   `ssh ... 'read -r k; exec /home/chuck/homelab/scripts/run-with-key.sh "$k" ...' <<< "$KEY"`.
2. **Never logged/persisted:** no key in MCP tool args, run logs, kanban cards,
   or session transcripts. Redact `sk-…` patterns in any log pipeline that sees
   job payloads.
3. **Ephemeral:** the key lives only in the launched process tree's env on
   Matrix and in the caller's transient job state on Thor.
4. **Caller's key only:** Thor must not substitute its own or chuck's key when
   the caller supplied one. (Fallback to chuck's key is a Matrix-side,
   pre-step-2 behavior only — see §2.)

### T3 — Caller side ✅ DONE 2026-11-28 (intake validation in `scripts/matrix-agent-launch.sh`)

- Clients submit agent jobs with a **LiteLLM virtual key** (per-caller
  budget/rate/spend enforced at the proxy — that is the policy point; Matrix
  enforces nothing).
- Validate key shape at intake (`sk-…`, non-empty); reject otherwise. Do not
  store it beyond the job's lifetime.

### T4 — Verification (after Matrix step 2 runs) — **RAN 2026-11-28 (partial)**

Ran 2026-11-28 with a minted-and-revoked test key (`t4-test-20261128`,
$1.00 budget) — evidence in `docs/thor_validation_log.md` part 15:

| # | Check | Result |
|---|---|---|
| 1 | Trivial job with the test key | ❌ BLOCKED (Matrix wrapper) — exit 127: `exec: pi: not found` (PATH, fix 1 below) |
| 2 | Success + spend on the TEST key, not chuck's | ⚠️ PARTIAL (proxy-side) — no LLM call reached; attribution unverified until check 1 passes |
| 3 | Keyless launch fails with no fallback | ✅ PASS — exit 2, `no key on stdin (keyless launches are rejected)`; Thor intake also rejects |
| 4 | Revoked key fails fast, no fallback | ⚠️ PARTIAL (proxy-side PASS) — revoked key → HTTP 401 in 0.048 s (`token_not_found_in_db`); session-level launch blocked by fix 1 |
| 5 | Evidence in both validation logs | ✅ PASS — Thor part 15 + Matrix `docs/matrix_validation_log.md` Run 2026-11-28 |

**Blockers (Matrix-side wrapper fixes):**
1. `pi` not in the forced-command PATH — add
   `export PATH="$HOME/.pi/agent/bin:$PATH"` (or absolute-path exec) before
   the `exec pi` line.
2. Base URL must be the LAN proxy — the wrapper pins
   `https://llm.choukalos.com`, but the public route is Caddy key-gated to
   chuck's + dylan's keys (verified 2026-11-28: test key 401 public / 200
   LAN); caller keys only traverse the LAN → use
   `http://192.168.4.54:4000`.

**Note:** the live stdin-patched wrapper is ahead of the pushed Matrix repo
(as of `ca618d0` the repo still carries the argv-only `run-with-key.sh`) —
the stdin patch + the two fixes need to be committed from the Matrix working
tree. **Re-run checks 1–2 once the fixes are live.**

## 4. Timing

- T1–T3 done 2026-11-28 (commit `505f417`); T4 ran 2026-11-28 — transport +
  rejection paths verified, happy path blocked on the 2 Matrix wrapper fixes
  (T4 section).
- Matrix will announce step-2 completion in the films-plan closeout
  (`media-pipeline/films_plan_matrix.md` Status header) — or just run
  `scripts/enable-key-passthrough.sh` when the long task is done.
- Once the wrapper fixes are live on Matrix: re-run T4 checks 1–2, then
  revoke any test keys and close.

## 5. Out of scope

- Per-request or mid-session key switching (contract is per launched session).
- Any auth on Matrix endpoints (stays keyless LAN-only; LiteLLM proxy remains
  the sole boundary).
- Raising/relaxing the Qwen 27B 5-image limit (`docs/thor_litellm_image_budget_handoff.md`).
