---
name: debugging
description: Systematic debugging playbook for when a task hits a wall in the homelab — reproduce first (a fix without a reproduction command is a claim, not a fix), then the check→read-output→fix→re-run loop with a hard budget of 3 fix cycles, then escalate. Covers the homelab log-reading paths (docker logs, journalctl, kanban task_status event stream, workspace logs) and the classic homelab failure modes. Use when a test fails, a build breaks, a deploy misbehaves, a container won't start, or the same fix has been tried twice without working. Infra health checks are the homelab-report skill; this is the code debugging loop.
---

# Debugging (S8) — the systematic loop

Grounded in R3 (`docs/research/R3-agent-self-verification.md`, Q4 —
debugging loops: reproduction-first, time-boxing, escalation). The anti-pattern
is shotgun debugging: retrying without reading the output, changing several
things at once, or re-prompting the same failed context. The answer is not
"loop harder" — it's **make the loop measurable**: a reproduction command, a
pass/fail check, and a budget.

## The loop

### 0. Reproduce (always first)
Produce a **command that reproduces the failure and print its output**. A fix
without a reproduction command is a claim, not a fix. If you can't reproduce
it, say so — "intermittent, reproduced N of M tries" is a real finding;
"can't reproduce" ends the loop with an escalation note, not a guess.

### 1. Isolate
- **Code change?** Bisect: `git log --oneline -10` on the relevant path,
  `git stash` / `git checkout <sha>` to bound the breaking commit.
- **Config change?** Diff the mounted file host-vs-container
  (`md5sum /path/to/file` vs `docker exec <c> md5sum /container/path`) —
  **mounted configs do not hot-reload** (Caddyfile, `litellm/config.yml`,
  skill files): an edit that "did nothing" usually means the container still
  runs the old config. The fix is `up -d --force-recreate`, not a bigger edit.
- **Environment?** `docker exec <c> env | grep <VAR>` — the container's actual
  env, not what the compose file says it should be (key drift: run
  `./scripts/key-sync-check.sh`).

### 2. Read the output (the step shotgun debuggers skip)
Homelab log paths, in order of usefulness:

| Source | Command |
|---|---|
| Container logs | `docker logs <container> --since 10m 2>&1 \| tail -50` (add `\| grep -iE 'error\|fail\|exception'` for long logs) |
| Host services (systemd) | `journalctl -u <unit> -n 50 --no-pager` |
| Kanban task event stream | `task_status` MCP tool (the task's events: session errors, QA verdicts, deploy steps) |
| Kanban HTTP surface | `curl -s http://172.18.0.23:3000/health` (owner-model map, tool count) |
| App logs in the workspace | the task workspace dir (kanban workspaces are swept after 7 days — read them while they exist) |
| Caddy access logs | `docker logs caddy --since 1h \| grep 'http.log.access'` (JSON; 401s on gated routes) |
| LiteLLM proxy | `docker logs litellm-proxy --since 10m` (403 key-model denials, 401s, model errors) |
| Security alerts | `/home/chuck/data/security/alerts.log` (401 spikes, spend breaches, key drift) |

**Read the actual error text.** The first line of a stack trace names the
file and line; the error *message* usually names the cause. The classic
homelab traps that hide in error text:
- `ONLY_FULL_GROUP_BY` — `ORDER BY col` after `GROUP BY` needs `ORDER BY
  SUM(col)` (MySQL on the kanban DB runs strict mode)
- `can't subtract offset-naive and offset-aware datetimes` — API timestamps
  are `+00:00`; normalize before date math
- `Expecting value: line 1 column 1` on a JSON parse — the pipe/heredoc stdin
  race: `echo data | python3 - <<heredoc` makes the heredoc win; use a temp
  file + `sys.argv[1]`
- `403 key_model_access_denied` — the key lacks the model (agent keys need
  work-type + pipeline model)
- `status 200 with empty content` — reasoning ate the `max_tokens` budget
  (matrix-copywriter with small `max_tokens`)

### 3. Fix ONE thing, re-run the reproduction
One change per cycle. If the reproduction output is identical, the change
didn't touch the cause — revert and pick another hypothesis.

### 4. Verify (S3)
The reproduction command passes AND the project's normal checks pass (test
suite, the real endpoint). "The error is gone" without the reproduction
command passing is not done.

## The budget (hard rules)

- **3 fix cycles max** against a stable reproduction command. Reliability
  decays with horizon (R3/S7: ~100% on sub-4-minute tasks, <10% beyond ~4
  hours) — a third failed cycle means the hypothesis space is wrong, not that
  the loop needs more turns.
- **Corrected twice, still wrong → reset.** A third correction in the same
  context mostly adds to a conversation with two failed attempts. Start fresh
  with one brief that folds in what was learned (what was tried, what the
  output said, what that rules out).
- **Budget exhausted → escalate, don't loop longer.** The escalation note
  carries: the reproduction command, the loop transcript (tried → output →
  ruled out), and the budget state. Share the traces, not just the summary.

## When to escalate immediately (skip the budget)

- The fix needs an **irreversible or high-risk action** (data migration,
  key rotation, `main` merge, public-surface change) — that's a deploy gate,
  not a debug step.
- **The evidence itself is suspect** — a test that rejects a correct solution
  means the loop is fighting the harness, not the bug (R3/S6). Fix the check
  first, or escalate.
- **Spending is the constraint** — a debug loop is LLM spend; check
  `spend-awareness` (S7) before a long one.
