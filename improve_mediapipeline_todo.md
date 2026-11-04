# Media Pipeline — Improvement TODO

**Date:** 2026-11-02
**Origin:** Produced after the "A Peanut Risky Business" short-film generation run (20 shots, ~5h wall clock), where a chain of client-side crashes cost ~1 hour of GPU time and ~1 hour of recovery work. The film itself shipped fine: https://choukalos.com/files/video/a-peanut-risky-business.mp4
**Session artifacts:** `/Users/chuck/Code/test-pi/peanut-movie/` (state.json has the full job registry, prompts, and paths from that run)

---

## 1. Incident summary

While generating 19 I2V clips (Wan 2.2, ~11 min each, serial queue), the orchestration (long codemode scripts on the Mac) failed 4 times:

| # | Failure | Cause | Consequence |
|---|---------|-------|-------------|
| 1 | 32-min orchestration script died | One `media_job_result` poll hit the 60s MCP transport timeout; no retry wrapper | 4 just-submitted job IDs (S1, S6, S12, S7) lost — in-memory only |
| 2 | Recovery script died on first poll | Used `setTimeout` (not available in codemode QuickJS sandbox) | 5 more job IDs lost (S1, S6, S12, S7, S8 resubmits) |
| 3 | Chunk script died after 5.5 min | Called undefined `persist()` helper (my bug) | 1 job ID lost (S13) |
| 4 | Final poll script died after 28 min | Same undefined `persist()` bug | No new loss (jobs were known) |

**Recovery cost:** ~1h of log archaeology (mcp_media, litellm-proxy container logs — job IDs are logged *nowhere*), 6 duplicate I2V jobs (~1h GPU time, orphaned clips retained 14d on the GPU host), and 4 extra resubmit cycles.

**Root causes (three independent gaps):**

1. **Transient MCP timeouts are fatal to long scripts** — the litellm-proxy → mcp_media hop intermittently hangs past the 60s tool-call timeout. Nothing in the tool docs warns about this or prescribes retries.
2. **The job registry is ephemeral and unlistable** — job IDs live only in the pipeline's in-memory registry and in the *caller's* memory. There is no `media_list_jobs` tool, no client tagging, and no log line containing job IDs. When the client died, the IDs were unrecoverable even though the artifacts existed on disk.
3. **Client-side state is fragile** — codemode `store()` only persists if the script *succeeds*; timers don't exist in the sandbox; `media_fetch` silently overwrote 5 same-basename files (see P4).

---

## 2. Environment map (for reference)

| Thing | Location / value |
|---|---|
| GPU host (matrix) | `192.168.4.55`, pipeline API `http://192.168.4.55:8189` (LAN-only except below) |
| Pipeline artifacts | `/home/chuck/data/comfyui/run/media_jobs/<job_id>/mp_<job_id>_00001.{mp4,png}` — 14-day retention |
| mcp_media container | thor `192.168.4.54`, image `ai-mcp-mcp-mcp_media:latest`, proxies to `192.168.4.55:8189`, fetch dir `/home/chuck/data/media/generated/pipeline` |
| Public Caddy routes | `https://siri.choukalos.com/media/pipeline/upload` (X-Api-Key) and `/media/pipeline/dl/<token>` (signed URL). Everything else under `/media/pipeline/*` is LAN-only (jobs, /files/*, /dl_token, health) |
| Pipeline health shape | `{ok, gpu_locked, jobs, max_concurrent: 1, max_queue_depth: 5, max_pending: 6, pending, running, queued, retention_days: 14}` — `running`/`queued` would list job IDs if exposed |
| Queue capacity | 1 running + 5 queued = 6 pending max; submit returns HTTP 503 when full |
| Models | `wan14b` (Wan 2.2 14B I2V, 832×480, ~5s clip, ~10–12 min), `ltxv2b` (LTXV 2B, fast draft), `qwen21` (Qwen-Image-2.1 keyframes/edits), ACE-Step (music), MMAudio (SFX), TTS voice library (`trailer`, `narrator_f`, `deep_m`, …) |
| MCP tool-call timeout | 60s hard timeout at the litellm-proxy MCP gateway (observed: "MCP request timed out after 60000ms") |
| Media MCP tools | edit_image, generate_image, generate_music, generate_sfx, generate_shot, job_result, upscale_video, fetch, freeze, pull, trim, add_voice, assemble, sfx, put, download, upload, info, caption, storyboard, list_voices, delete_voice, text_to_speech, render_tab_pdf, transcribe_song |
| Vision workaround | mcp_vision is broken (`/workspace/vision` permission denied) — worked around via `https://llm.choukalos.com/v1/chat/completions` with model `matrix-coder` and image_url content parts (see P4-3) |
| Source locations | **TBD — verify:** pipeline server source on matrix (under `/home/chuck/data/comfyui/`); mcp_media source on thor (docker build context for `ai-mcp-mcp-mcp_media:latest`, likely `/opt/mcp-servers/` or similar) |

---

## 3. Prioritized TODO

### P0 — `media-film` orchestration skill *(no infra changes; shippable from the Mac)*

**Why:** Encodes the battle-tested orchestration pattern so any LLM client (pi, Siri, n8n) survives the same failure modes. Would have prevented ~80% of the incident pain.

**Where:** `/Users/chuck/Code/skills/media-film/SKILL.md` (pattern: `publish-file/SKILL.md`). Optionally register in the family skills gateway (`mcp_skills`) so `run_skill` can invoke it.

**Must encode (all learned the hard way this session):**

1. **State file on disk, written immediately after every submit** — not codemode `store()` (which is lost on script failure). Schema (proven in `peanut-movie/state.json`):
   ```json
   {
     "title": "...", "created": "...", "target_duration_s": [90, 150],
     "assets": { "gpu_uploads": { "name": "<media_jobs path>" } },
     "identity": { "<character>": "<canonical identity prompt>" },
     "shots": { "S1": { "beat": "...", "kf_path": "...", "i2v_job": "<id>", "i2v_path": "...", "qc": "..." } },
     "i2v": { "S1": { "job_id": "...", "path": "...", "status": "done" } },
     "i2v_pending": ["S13", ...],
     "audio": { "music": "...", "vo": "...", "sfx": "..." },
     "assemble_job": "<id>"
   }
   ```
2. **Retry wrapper on every MCP call** (4 attempts):
   ```js
   const mcall = async (name, args, tries = 4) => {
     for (let i = 0; i < tries; i++) {
       try { const r = await tools[name](args); return JSON.parse(r.content[0].text); }
       catch (e) { if (i === tries - 1) throw e; }
     }
     throw new Error("retries exhausted: " + name);
   };
   ```
   (No `setTimeout` in the sandbox — back off by issuing a cheap blocking call, e.g. `media_job_result` on a known-done job with `wait_seconds: 25`.)
3. **Timeboxed chunks** — one codemode call per 4–8 job completions (~45–90 min max). Persist state after each completion.
4. **Resume protocol** — on any crash: (a) read state file, (b) re-poll all known `job_id`s (they stay in the registry while jobs are live), (c) for shots with a job but no result, resubmit (orphaned duplicates are harmless — 14d retention), (d) continue from `i2v_pending`.
5. **Queue management** — keep ≤5 in-flight submissions (queue = 1 running + 5 queued); on 503 "queue full", stop submitting and poll instead of spinning.
6. **QC gates** — vision-check every keyframe before spending I2V time (keyframe regen is ~1 min vs I2V ~11 min); vision-check 2–3 action frames per clip post-I2V; vision-check the final cut at 6–8 timeline points (title cards, key beats, end card).
7. **Assembly + publish checklist** — `media_info` on the final cut (duration in target range, codec, audio present) → `media_fetch` to `/home/chuck/data/media/generated/pipeline/...` (approved publish root) → `run_skill publish_file` with `subdirectory: "video"` → verify public URL with `curl -sIL`.
8. **Audio timing pattern** — TTS segments generated separately, placed with `adelay` + `amix` in ffmpeg, combined track uploaded via the public `/media/pipeline/upload` route, single `vo` path with `vo_start: 0`.

**Effort:** 1–2h (mostly writing; all patterns already exist in this session's history).
**Verify:** dry-run the skill against a 3-shot test film; kill the orchestrating script mid-run and confirm the resume protocol recovers.

---

### P1 — Small pipeline API additions *(biggest leverage; needs LAN access to matrix + thor)*

#### P1-1. `media_list_jobs` tool + `GET /jobs` endpoint  ⭐ highest value

**Problem:** Lost job IDs were unrecoverable despite artifacts existing on disk.

**Change:**
- Pipeline (matrix): add `GET /jobs?status={running,queued,done,all}&since=<iso>&limit=100` returning `[{job_id, kind, status, client_tag, created, path, error}]` from the registry (and, post-P2, SQLite).
- mcp_media (thor): add `media_list_jobs` tool proxying it.
- Document: "If you lost a job_id, list recent jobs and match by kind/time."

**Effort:** ~2–4h (endpoint + tool + docs).
**Verify:** submit a job, kill the client, call `media_list_jobs`, recover the ID.

#### P1-2. `client_tag` param on all submit tools

**Problem:** Even with `media_list_jobs`, a multi-project client can't tell which jobs are its own.

**Change:** Accept optional `client_tag` (e.g. `"peanut-movie/S1"`) on `generate_shot`, `edit_image`, `generate_image`, `generate_music`, `generate_sfx`, `text_to_speech`, `trim`, `freeze`, `assemble`, `upscale_video`, `caption`, `transcribe_song`. Store in registry; return in `media_list_jobs` and filterable via `?tag=`.

**Effort:** ~2h (plumbing through submit handlers).

#### P1-3. Log job IDs to the mcp_media container log

**Problem:** Container-log archaeology failed because submit responses were never logged.

**Change:** In the mcp_media server, log one line per submit: `SUBMIT kind=generate_shot tag=<client_tag> job_id=<id>`. Also log `DONE job_id=<id> path=<path>` when `job_result` returns a final result. (15 min change; gives `container_logs` a recovery path even before P1-1.)

**Effort:** ~15 min.

#### P1-4. Document the 60s MCP timeout in tool descriptions

**Change:** In mcp_media tool descriptions (and the litellm proxy config if it surfaces them): "Polls block up to `wait_seconds` (max 25). The MCP gateway has a 60s hard timeout — transient 'MCP request timed out' errors are expected; retry the call. Long orchestrations should wrap all calls in retry logic."

**Effort:** ~30 min.

---

### P2 — Durable job registry (SQLite)

**Problem:** Artifacts are retained 14 days but their metadata (job_id ↔ path ↔ kind ↔ submit params) dies with the pipeline process. The registry is strictly shorter-lived than the artifacts it describes.

**Change:**
- Pipeline (matrix): persist every job to SQLite (e.g. `/home/chuck/data/comfyui/run/media_jobs/jobs.db`) on submit; update on completion. Schema: `jobs(job_id TEXT PRIMARY KEY, kind TEXT, status TEXT, client_tag TEXT, created TEXT, done TEXT, path TEXT, error TEXT, params_json TEXT)`.
- The existing 14-day retention sweeper deletes rows alongside files.
- `GET /jobs` (P1-1) reads from SQLite → survives restarts.
- Backfill: one-time scan of `media_jobs/*/` to seed the DB from existing artifact dirs.

**Effort:** ~half a day.
**Verify:** submit a job, restart the pipeline container, confirm `media_list_jobs` still returns it.

---

### P3 — Codemode runtime hardening (pi level)

**Where:** pi-coding-agent codemode (local install `/Users/chuck/.npm-global/lib/node_modules/@earendil-works/pi-coding-agent/`; upstream issue if you want it fixed for everyone).

1. **`store()` should persist per-call**, not only when the script succeeds. Today a crashed script loses all stored state — the exact failure that cascaded here. (If per-call persistence is too costly, at minimum flush on each `store()` call and document it.)
2. **Provide `sleep(ms)`** (or document loudly that timers don't exist). `setTimeout` is undefined in the QuickJS sandbox and produced a ReferenceError after the script had already submitted 5 GPU jobs.
3. **Surface a "script failed, N tool calls were made (not undone)" summary with the tool names** — this already appears in the error output and was the *only* way to reconstruct what had happened. Make it part of the documented contract.

**Effort:** 1–2h local patch; upstream PR optional.

---

### P4 — Small fixes

#### P4-1. `media_fetch` basename collision
**Problem:** Fetching 5 files named `vo.wav` into one subdirectory silently overwrote each other (all 5 "succeeded" to the same path).
**Change:** Preserve the source basename; on collision, suffix (`vo_2.wav`) or fail loudly. Alternatively accept a `dest_name` param.
**Effort:** ~30 min.

#### P4-2. `media_job_result` on unknown/expired job_id
**Change:** Return a structured error that suggests `media_list_jobs` (post-P1-1) instead of a bare "not found".
**Effort:** ~15 min.

#### P4-3. mcp_vision permission bug
**Problem:** `vision_analyze_image` fails with `/workspace/vision` permission denied (observed 2026-11-02). Workaround used: `POST https://llm.choukalos.com/v1/chat/completions` with model `matrix-coder` and `image_url` content parts (base64 data URLs work).
**Change:** Fix the mcp_vision container's volume mount / workspace permissions; verify with a URL and a local-path image. Until fixed, document the workaround in the skill (P0) and in mcp_vision's description.
**Effort:** ~30 min once on thor.

#### P4-4. `media_assemble` timing docs
**Change:** Document that `text_overlays`/`sfx[].at` are absolute timeline seconds, and how to compute them from per-shot durations (`media_info` on each shot). (This session's cut used: S12 at 11×5.0625 = 55.7s; end card at 18×5.0625+4.5 = 95.6s.)
**Effort:** ~15 min.

---

## 4. Suggested order of attack

1. **P0 skill** (Mac-only, 1–2h) — immediate protection for all future runs.
2. **P1-3 log lines** (15 min, next time you're on thor) — cheapest recovery path.
3. **P1-1 + P1-2 `media_list_jobs` + `client_tag`** (half day) — makes lost IDs recoverable by design.
4. **P2 SQLite registry** (half day) — makes it survive restarts too.
5. **P4 items** (an hour total, opportunistically).
6. **P3 codemode** (when convenient; upstream PR optional).

## 5. Open questions

- Where exactly does the pipeline server source live on matrix, and where is the mcp_media build context on thor? (Verify before P1/P2.)
- Is there an existing jobs table in the litellm-db (postgres) or MySQL that already captures MCP tool calls? (Checked container logs on 2026-11-02: no job IDs logged anywhere. A DB check would confirm.)
- Should `media_list_jobs` be exposed publicly (via Caddy) or stay LAN-only? (LAN-only is fine — the Mac can't reach the LAN anyway, which is exactly why the public `/dl` route exists.)
- Retention: 14 days is fine for artifacts; the SQLite registry could keep rows longer (metadata is cheap) — e.g. 90 days — to aid post-hoc forensics.