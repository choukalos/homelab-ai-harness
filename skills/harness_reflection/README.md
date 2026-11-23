# harness_reflection — Weekly Closed-Loop Harness Reflection

The homelab's learning loop: **capture** what happened (memories, ingested
sessions, skill jobs, git) → **reflect** on it (memory maintenance +
lessons + harness change proposals) → **make it visible** (harness-learning
dashboard + morning-brief pointer). Proposals are **propose-only** —
humans drive the lifecycle.

> **Status (2026-11-14):** all four phases of the experience-improvement
> plan are built, deployed, and verified live (plan closed —
> `experience_improvement_todo.md` was removed with this note). Proposals
> table: open=1 (`recent-activity-slow-run-optimization`), applied=4,
> dismissed=3.

## The loop

| Piece | What | Where |
|---|---|---|
| **Capture — session ingest** | `POST /api/sessions/ingest` stores a pi session transcript **private to the caller** (caller's LiteLLM key → user_id; the admin key is rejected → 401; unknown key → 401). 2 MB cap per transcript (413 above; longer sessions split `session_id.partN`), sha256 dedup (re-sync → `{status: "duplicate"}`), stored `data/skill-runner-sessions/{user_id}/{YYYY-MM-DD}/{session_id}.jsonl` (0600), indexed in the `session_ingests` table. **User-initiated only** — the `session-sync` pi skill uploads at session closeout when the user agrees; never auto-upload. | skill-runner `:8091` (`skills/runner/sessions.py`) |
| **Capture — memory + jobs + git** | The reflection reads the last N days of memories (in-process interface, private + household), `skill_jobs` (failures, retries, durations, approvals/cancels), and the homelab git log — no new capture path. | skill-runner |
| **Reflection** | Weekly `harness_reflection` skill (Sun 23:00 UTC, `user=chuck`, `days=7`, `matrix-coder`, 600 s budget): **(A) memory maintenance** written as the target user — supersede statements for contradictions, correction preferences (`importance=high`, with provenance) when the user corrected the agent ≥2×, friction lessons (`"Lesson (<date>): <what happened> -> <what to do differently>"`). **Write-time dedupe/supersede:** the memory interface merges a near-duplicate or superseding `harness_reflection` fact into the existing entry in place (newer text wins, `updated_at` bumps; `MEMORY_DEDUPE_THRESHOLD`, default 0.85 raw cosine) — so the skill writes only the current truth, never "superseding earlier counts" variants; **(B) harness change proposals** — propose-only, ≤5/run, every proposal needs ≥1 real evidence ref (memory id / job id / session id / git sha / quoted user statement), deduped against open proposals (slug, title, same-day file, and ≥50% evidence overlap); **(C) review digest** (≤1 page) + a pointer pushed into the next `morning_brief`. | `skills/harness_reflection/` |
| **Proposals lifecycle** | `proposals/YYYY-MM-DD-<slug>.md` in the repo + a row in the `proposals` MySQL table. Statuses: `open → accepted\|dismissed → applied`. Humans drive it via `cli/proposals.sh` (admin key): `list [status] [--limit N]`, `accept <slug>`, `dismiss <slug>`, `mark-applied <slug>`. Proposals open >14 days are flagged in the digest — never auto-deleted. | `proposals/`, `cli/proposals.sh` |
| **Observability** | `harness-learning` Grafana dashboard fed by skill-runner `/metrics`: `harness_reflection_runs_total`, `harness_reflection_maintenance_total{kind}` (supersede/correction/lesson), `sessions_ingested_total{user_id,status}`, `proposals_total{status}`, jobs metrics. North stars: correction rate trending down, % jobs completing without retry, proposals applied/total (`accepted` is a transient review state — the panel counts the terminal `applied` state; fixed 2026-11-23). | `grafana/dashboards/harness-learning.json` |

## Invariants (locked by design)

- **Propose only.** The reflection never applies harness changes, never
  restarts/recreates containers, never touches `.env` / compose files /
  memory privacy scoping (Tier 2/3 actions are out of scope). The job
  writes only to `proposals/` + its own artifact dir (the repo mount is
  read-only in the container).
- **Identity (D10).** Scheduled jobs run under the `service` identity —
  the analysis is service-scoped, but every memory write lands on the
  target user via the in-process interface, which rejects
  service/unknown writers.
- **Privacy.** Transcripts are private to the caller (no household flag on
  the ingest path); raw transcripts are never indexed into Qdrant or
  stored in memory/KB — distilled facts only.
- **Manual steps.** Image rebuilds / container recreates are Tier 3 manual
  steps; `scripts/key-sync-check.sh` after any key/container change.

## Guardrails (enforced in code, `skill.yml`)

`max_proposals: 5` · `stale_days: 14` · `max_memories: 60` ·
`max_jobs: 50` · `max_git_commits: 40` · `max_sessions: 4` ·
`max_session_chars: 12000`

## History

- **2026-11-08 → 14:** built + deployed (Phase 1 `session-memory` +
  `session-sync` pi skills; Phase 2 ingest endpoint; Phase 3
  `harness_reflection` + proposals table/CLI; Phase 4
  `learning_metrics`/`jobs_metrics` + dashboard).
- **2026-11-12/13:** thor↔GitHub reconcile — the merge dropped the Mac
  hardening commit's code (F1 window guard + ported tests); re-landed on
  main 2026-11-13 (guard at all three launch sites; 60 unit / 40 endpoint
  tests green). The Mac's parallel Phase 3 lives on branch
  `mac-phase3-parallel` (preserved, NOT in main — main runs the thor
  version).
- **2026-11-13:** proposals dedup window guard + in-flight job checkpoint
  feature (`POST /skills/jobs/{id}/checkpoint`, `GET /api/jobs` list —
  ops doc `docs/operations/job-checkpoints.md`).
