# pi-subagents: honor timeoutMs and deliver child timeouts as script results

- slug: tier2-pi-subagents-timeout-handling
- date: 2026-11-19
- status: dismissed
- dismissed: 2026-11-21 (chuck) — pi-subagents is a **third-party extension**
  loaded into the owner's own pi client (pi.dev); chasing timeout fixes
  upstream is a PITA, not worth the maintenance. Revisit only if the
  extension's author lands the fixes or a fork becomes the de-facto runtime.
- tier: 2
- target user: chuck
- source: workspace/ideas/2026-11-17-media-pipeline-improvements.md (B1–B5)

## What
Fixes in the **pi-subagents runtime** (the B items from the film run). ⚠️ **Source location first:** the extension is not installed on thor (`~/.pi/agent/npm` has only pi-long-task / pi-loop-police / pi-provider-litellm); it was used from the Mac, with artifacts also under `workspace/code/invest-hub/.pi-subagents/`. Locate the extension's source repo before starting.

**P0**
- **B1 — honor requested `timeoutMs`.** The runtime enforced 1800000 ms (30 min) and killed children with "Subagent timed out after 1800000ms" despite `timeoutMs: 10800000` — with no hint that the requested value was capped. Honor the requested value, or document + warn when capping ("requested 10800000, capped to 1800000"); if the cap is a safety rail, expose a config to raise it for trusted long jobs.
- **B2 — child timeout must not kill the workflow run.** When a child timed out, the entire workflow run failed (`Run 'production' failed: Subagent timed out…`) and the script's `for (attempt 1..4)` retry loop never ran — the retry loop was dead code. Child timeout/failure should resolve the `runs.run` promise with `{ok:false, error}` (as 524s did) so the script's loop can retry.

**P1**
- **B3 — watchdog noise.** Raise the no-activity threshold (60 s → 120–180 s), suppress pings for runs that recently completed (S30–S36 were re-pinged *after* completion), and mark long-tool (bash/codemode) activity as "observed activity." Each ping costs a parent turn.
- **B4 — durable output on timeout.** `output: "production/report-N.md"` lands in the per-run artifact dir, not the project, and timed-out children lose the final output entirely. (Belt) task convention: write durable artifacts to the project via the `write` tool. (Suspenders) on timeout, persist the child's last assistant message to the declared output path.

**P2**
- **B5 — children inherit the parent's thinking level by default.** The research child inherited high thinking and died with `stopReason "length"` (32k output budget burned on thinking). Workflow children should default to `:off` (or the agent's configured default) unless explicitly overridden; document in the pi-subagents skill.

## Why (evidence)
- SW Holiday Spoof run: every production attempt (1–5) died at exactly 1800000 ms; the in-script retry loop never executed; dozens of stale watchdog pings; handoff-chain pattern (5–10 min re-read overhead per handoff + parent attention) was the only workaround. With B1+B2 fixed, the in-script attempt loop becomes real: one long-lived production child, parent involvement only at completion/final failure.

## Risk + rollback
Low–medium (runtime change). Test with a script containing a retry loop + a job that exceeds the old cap; verify the promise resolves with `{ok:false}` and the loop retries. Rollback = revert the extension version.

## Files touched
- pi-subagents extension source (Mac-side repo — locate first)
- pi-subagents skill docs (B5 default + B1 cap documentation)

---
_Drafted 2026-11-19 (pi, thor) from the workspace/ideas review. Review with `cli/proposals.sh`; applying is a human decision._
