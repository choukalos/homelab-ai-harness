# Thor — Agent-Job Key Pass-Through (Thor-side contract)

> Created: 2026-11-28 · **Status:** Thor side implemented (T1–T3, commit
> `505f417`); Matrix install LIVE (T4 run proved the forced command); Matrix
> step 2 HAS run (chuck confirmed 2026-11-28). **T4 ran 2026-11-28 (partial):**
> transport + keyless rejection + revoked-key fail-fast PASS; happy path
> blocked on 2 Matrix wrapper fixes (`pi` PATH + LAN base URL — see
> `docs/thor_validation_log.md` part 15).
> Contract of record (Matrix repo): `docs/matrix_key_passthrough.md`
> Handoff: `thor_key_passthrough_handoff.md` (T1 transport, T2 key hygiene,
> T3 caller intake, T4 verification)
> Cross-ref: Matrix `docs/matrix_thor_contract.md` v1.6 (chosen transport is
> recorded there once live — TODO 6)

## 1. Purpose

Client work that runs as **agent jobs on Matrix** (pi sessions, incl.
pi-long-task worker subagents) consumes LLM capacity through the Thor LiteLLM
proxy — the only auth boundary. Contract: **the caller passes its own LiteLLM
virtual key with the job; the Matrix session (coordinator + workers) runs under
that key.** Jobs launched without a key fail loudly instead of silently billing
chuck's key. Matrix enforces nothing; the proxy enforces per-caller
budget/rate/spend (the policy point).

## 2. Chosen transport (T1)

Restricted Thor→Matrix SSH (the handoff's recommended option):

| Item | Value |
|---|---|
| Thor keypair | `~/.ssh/id_ed25519_matrix` (ed25519, no passphrase, comment `thor-matrix-agent-job`) |
| ssh alias | `matrix-agent` (`~/.ssh/config`) → `chuck@192.168.4.55`, `IdentitiesOnly yes`, `BatchMode yes`, `StrictHostKeyChecking accept-new` |
| Matrix `authorized_keys` line | `command="/home/chuck/homelab/scripts/run-with-key.sh",no-pty,no-agent-forwarding,no-port-forwarding,no-X11-forwarding,from="192.168.4.54" ssh-ed25519 AAAA… thor-matrix-agent-job` |
| Capability granted | Run `run-with-key.sh` only. No shell, no pty, no port/X/agent forwarding, source-restricted to thor's IP (192.168.4.54) |

Exact line + copy-paste install steps for chuck:
`tmp/pi-long-task/2026-11-27T23-49-37-457Z-d661e6dc/t1-ssh-install-instructions.md`

### 2.1 stdin envelope protocol

The forced command runs `run-with-key.sh` **with no arguments**, so the job
envelope rides ssh stdin (the key never appears in argv on either host):

- **line 1:** the caller's LiteLLM virtual key
- **line 2:** the pi args as a JSON array, e.g. `["-p","Reply OK"]`

The Matrix wrapper reads this envelope when invoked with no argv (stdin mode).
Its `argv[1]` contract (Matrix contract doc §4) is **unchanged** for local /
interactive use.

> **Why the wrapper needs a small stdin patch:** the shipped wrapper accepted
> the key only as `argv[1]` and exited 2 (usage) when invoked with no args —
> which is exactly how the forced command invokes it. The handoff's own T1
> example (`ssh chuck@matrix '…/run-with-key.sh' <<< "$CALLER_KEY"` — key via
> stdin) implies the stdin mode. The patch (in the install instructions, step 2)
> adds the stdin path only; it is required for the mandated authorized_keys
> line to work at all.

## 3. Launch path (T2 hygiene + T3 intake)

`scripts/matrix-agent-launch.sh` (thor):

- **Key source:** `$MATRIX_CALLER_KEY` env var or stdin line 1 (env wins) —
  **never argv**. Unknown leading options are rejected so a key can never be
  passed as an argument; pi args must follow `--`.
- **Intake validation (T3):** non-empty + LiteLLM virtual key shape
  (`sk-` + ≥6 of `[A-Za-z0-9_-]`); malformed/empty → **exit 2 before any ssh
  attempt**. The key itself is never echoed (length/shape only).
- **No storage (T3):** the key lives only in the launcher's transient process
  state and the ssh stdin channel; the script writes no files.
- **Redaction (T2):** all output — including the remote job's stdout/stderr —
  is piped through `redact()` before reaching stdout/stderr, masking
  `sk-[A-Za-z0-9_-]{6,}` → `sk-***REDACTED***`.
- **Caller's key only (T2 rule 4):** the script never substitutes chuck's or
  thor's key.
- **Exit codes:** `0` = job OK · `2` = intake/usage error (no ssh attempt) ·
  otherwise the remote job's exit code.

Usage:

```bash
MATRIX_CALLER_KEY=sk-… scripts/matrix-agent-launch.sh -- -p "Reply OK"
printf '%s\n' "$CALLER_KEY" | scripts/matrix-agent-launch.sh -- -p "..."
```

## 4. Status / next steps

- [x] T1 keypair + ssh alias on thor (2026-11-28)
- [x] T1 install instructions for chuck (exact `authorized_keys` line +
      wrapper stdin patch + verification steps + rollback)
- [x] T2/T3 launch path: `scripts/matrix-agent-launch.sh`
- [x] chuck installs the `authorized_keys` line + wrapper patch on Matrix
      (live — the T4 run 2026-11-28 exercised the forced command end-to-end)
- [x] T4 verification (TODO 6) — **ran 2026-11-28 (partial)**; Matrix step 2
      HAS run (chuck confirmed 2026-11-28); evidence → `docs/thor_validation_log.md`
      part 15 + Matrix `docs/matrix_validation_log.md` Run 2026-11-28. Happy
      path re-run pending the 2 Matrix wrapper fixes (PATH + LAN base URL)
- [ ] Record the chosen transport in Matrix `docs/matrix_thor_contract.md`
      (new § or §10 note) once live (TODO 6)

## 5. Out of scope (per handoff §5)

Per-request or mid-session key switching; any auth on Matrix endpoints (stays
keyless LAN-only — the LiteLLM proxy remains the sole auth boundary); raising/
relaxing the Qwen 27B 5-image limit.
