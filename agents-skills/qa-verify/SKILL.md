---
name: qa-verify
description: Dynamically verify that generated code actually works — run the project's test suite, build and hit the real endpoint, exercise the changed behavior and its error paths, and check the live surface after a deploy. Every verification claim carries evidence (command + output); anything that cannot be verified is declared in a Could-not-verify section, never simulated or silently skipped. Use before claiming a task is done, when running the functionality half of the kanban QA stage over a task's diff, or when asked to verify that a change runs right (static does-it-look-right review is code-reviewer; the security pass is security-code-review).
---

# QA Verify

Scrutinize the **behavior** of generated code — does it work correctly, is it
doing something erroneous, or is it not working at all? This is dynamic
verification (does it *run* right); the complement is static scrutiny (does it
*look* right — code-reviewer). Consumed by the task agent (self-check before
claiming done) and the kanban QA stage (independent pass over the task's diff).

Grounding: `docs/research/R3-agent-self-verification.md` (evidence-based
completion, confident-but-wrong failure modes, loop discipline; all sources
fetched + verified 2026-11-23).

## Hard rules (honesty)

1. **Honest capability declaration.** When you don't have the tooling to QA
   something, you **must say you can't QA it.** Every QA report ends with a
   `## Could not verify` section — what wasn't verified, why (missing tooling),
   what would be needed. Examples: no browser → can't verify UI rendering; no
   GPU → can't verify model inference; no test database → can't verify a
   migration end-to-end; no access to an external service → can't verify the
   integration. **Never simulate a check, never silently skip one, never let
   "couldn't verify" be read as "verified fine."**
2. **No "should work" claims.** Every verification claim carries evidence — the
   command run + its output, the curl response, the before/after diff. "All
   tests pass" on its own tells you very little: which tests, and what they
   don't cover.
3. **Green ≠ correct.** A passing test run is evidence the tests passed, not
   that the work is correct — a documented share of real-world test suites
   reject functionally correct code (over-narrow or over-wide tests). State
   which tests ran and what they don't cover.

## Procedure (use everything available, in this order)

1. **The project's test suite.** Find the command via the recon note
   (codebase-recon; if there's no note, a quick recon). Run the full suite if
   fast, targeted if slow. If the project has no tests, say so explicitly and
   verify by other means. **Tests as story DoD (gap G5):** acceptance criteria
   get tests *during* implementation — if a story's acceptance criteria have no
   tests, that's a gap to flag (and fix during implementation), not something
   to paper over in QA.
2. **Build → run → hit the real endpoint.** Check the **response, not just the
   exit code** (a 200 with an empty body; an error JSON inside a 200). Use LAN
   URLs where applicable.
3. **Behavior checks for the specific change.** Does the new path do what the
   spec says? **Regression spot-checks** — do the old paths still work?
4. **"Not doing something erroneous."** No new errors in the logs after
   exercising the change; no data corruption (check the DB rows the change
   touches); no resource leaks on the paths exercised; error paths behave (feed
   bad input and observe the failure mode).
5. **Deploy verification.** After a deploy, verify the *live* surface changed
   (publish → wait → curl the public site). Then run the post-deploy watch
   below before closing the task.

## Post-deploy watch (gap G7)

After a deploy, **before closing the task**: watch logs/health for a short
window (10 minutes, or the project's convention) — no new errors, the service
is healthy, a smoke check of the changed surface. Record the window + what was
observed in the QA report. A deploy that "succeeded" (exit code 0) but errors
in the logs five minutes later is a failed deploy.

## Failure handling

- **"Verified failing"** — reproduce (a stable reproduction command), capture
  (output/logs), report. Don't silently retry forever.
- **Budgeted fix loop** — up to 3 fix-retry cycles against a stable
  reproduction: run the check → read the output → one targeted fix → re-run.
  Shotgun (retrying without reading output, changing several things at once) is
  the documented anti-pattern.
- **Escalate (stop and report) when**: the same thing was corrected twice and
  is still wrong; the evidence itself is suspect (tests that reject correct
  code — you're fighting the harness, not the bug); an irreversible or
  high-risk action is needed; the budget is exhausted. Escalate with the
  reproduction command, what was tried, and what the output said.
- **Never bypass a failing check to claim done** — no skip-verification flags;
  that's a documented incident pattern in production agents.

## QA report

```markdown
# QA: <task/change> — <date>
## Verdict: PASS / FAIL / PARTIAL (what's missing)
## Verified            <!-- each claim: command + observed output -->
- ...
## Regression spot-checks
- ...
## Post-deploy watch   <!-- if deployed: window + what was observed -->
- ...
## Could not verify    <!-- always present: what / why (missing tooling) / what would be needed -->
- ...
```

Rules: every "verified" line has evidence; `## Could not verify` is always
present (write "none" only when genuinely nothing was missing — otherwise list
it); **PARTIAL is a legitimate verdict** — it says exactly what's unverified
and what would be needed.

## Kanban QA stage (explicit section)

- The QA stage is a **separate session** after the task session completes — an
  independent pass over the task's diff, not the author rubber-stamping its own
  work. Self-approval bias is the default failure: the author is biased by its
  own reasoning, and a fresh session is the cheapest independent reviewer.
- Full QA = **qa-verify (functionality) + security-code-review (security — the
  hard gate) + code-reviewer (static quality)**. This skill produces the
  functionality evidence; the harness/gate decides what blocks (whether
  functionality is a gate or advisory is an open org decision — the skill's job
  is the evidence).
- The report is the artifact the QA stage consumes. "Verified failing" = the
  task goes back (needs-attention via restart with a resolution note — see
  kanban-board), not a silent retry.

## Gotchas

- **Check the response, not just the exit code** — the single most common
  false-pass.
- **Runtime logs the agent can read are evidence** — in debug mode, log to
  stdout; the agent reads the log as it works.
- **Self-checks grade the checks, not the reasoning** — in your own session you
  can't be the fresh reviewer; run the mechanical checks and report honestly,
  and let the QA stage (fresh session) be the independent pass.
- **Evidence is not infallible** — the report states what the evidence covers
  and what it doesn't.

## References

- `docs/research/R3-agent-self-verification.md` — the research grounding
  (evidence-based completion, failure modes, loop discipline, escalation).
- `codebase-recon` — test/build commands + the deploy path (consume the recon
  note; "no tests" is a recon finding).
- `git-flow` — when the verified work gets pushed (the deploy stage pushes).
- `security-code-review` / `code-reviewer` — the other two halves of the full
  QA pass.
- `kanban-board` — the QA stage, needs-attention, and restart semantics.
