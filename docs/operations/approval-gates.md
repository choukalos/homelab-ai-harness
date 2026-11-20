# Approval Gates — Thor Host Reboots and Docker Stack Shutdowns

_Ops policy extending the standing rule (memory `0b2ff954`): never restart
litellm-proxy / session-carrying services without Chuck's explicit request.
This doc extends that rule to the host and the whole stack.
(Proposal `tier3-housekeeping` H2, applied 2026-11-20.)_

## Rule

**No thor host reboot and no whole-Docker-stack shutdown without Chuck's
explicit request.** This covers:

- `reboot` / `shutdown` / `poweroff` on thor (or any systemd target that
  triggers them),
- stopping the whole ai-core / media stack (`docker compose down` at the
  stack level, stopping the Docker daemon, `systemctl stop docker`),
- any update/patch flow that implies a host reboot (e.g. applying a kernel
  update and rebooting).

It extends the standing rule that already covers individual services:
litellm-proxy and any session-carrying service (skill-runner, pi sessions,
MCP servers with in-memory state) are never restarted without Chuck's
explicit request.

## Why

A thor reboot at 19:57 on 2026-11-01 interrupted in-flight tab production
and destroyed the agent's session context — the work had to be redone from
scratch. The durable job index survives a reboot; session context does not.

## Mitigation — job checkpoints

The in-flight job checkpoint mechanism (`docs/operations/job-checkpoints.md`,
proposal `add-inflight-job-checkpoint`, applied 2026-11-13) is the
mitigation that makes an approved reboot cheap:

- long-running jobs write a checkpoint at every stage boundary
  (`stage` + `next_step` + resume `data`),
- on startup the runner marks in-flight jobs `interrupted` **with the
  checkpoint intact**,
- recovery is a resume from `checkpoint.next_step`, not a redo.

So even when Chuck approves a reboot, long-running media/tab jobs should
have a current checkpoint first (write one if missing), and the post-reboot
recovery follows the "Recovery after a host reboot" section of
`docs/operations/job-checkpoints.md`.

## How a reboot/shutdown gets authorized

Chuck requests it explicitly (chat/CLI). The agent then:

1. confirms the explicit request is on record,
2. checks in-flight long-running jobs and writes/refreshes their
   checkpoints,
3. performs the reboot/shutdown,
4. on startup, lists `interrupted` jobs and resumes them from their
   checkpoints.

Agents and scheduled/automated flows must not initiate a reboot or
whole-stack shutdown on their own judgment ("the kernel update is
pending", "the host is unstable") — they surface the need and wait for
Chuck's explicit go-ahead.
