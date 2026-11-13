---
name: media-film
description: Orchestrate a multi-shot short film through the mcp_media GPU pipeline — keyframes (Qwen-Image 2.1), I2V clips (Wan 2.2 / LTXV), TTS/music/SFX, assembly, vision QC, and publish. Crash-proof by design: on-disk state file written after every submit, retried MCP calls, timeboxed codemode chunks, and a resume protocol built on the durable job ledger (media_list_jobs).
---

# media-film — multi-shot film orchestration

Orchestrate a multi-shot film (keyframes → I2V clips → audio → assembly → QC →
publish) through the `mcp_media` tools, the way the 2026-11-02 "A Peanut Risky
Business" run (20 shots, ~5 h) should have been run. Everything in this skill is
encoded from that incident: 4 orchestration-script deaths, 10 lost job IDs, ~1 h
of log archaeology, 6 duplicate I2V jobs.

**Audience:** any LLM client orchestrating via `mcp_media` (pi on the Mac, Siri,
n8n). The Mac is **off-LAN** — all pipeline access goes through the MCP gateway
(`https://llm.choukalos.com`) and the public siri routes. There is no direct
`curl http://matrix:8189` from the Mac; `media_list_jobs` replaces `GET /health`
+ `GET /jobs` for queue/ledger visibility.

## When to use

- Multi-shot film/commercial: storyboard → keyframes → I2V → audio → assemble → publish.
- Any long mcp_media orchestration where a dead client must not lose job IDs.
- Resuming a crashed film run (jump straight to the **Resume protocol**).

Not for: single-image or single-clip jobs (call the tool directly), song
transcription (use the `song-transcribe` skill).

## Environment map (verified 2026-11-04)

| Thing | Value |
|---|---|
| GPU host (matrix) | `192.168.4.55`, pipeline API `http://matrix:8189` — **LAN-only** |
| Pipeline artifacts | `/home/chuck/data/comfyui/run/media_jobs/<job_id>/mp_<job_id>_00001.{mp4,png,wav,…}` — 14-day retention |
| mcp_media container | thor `192.168.4.54`, proxies to `matrix:8189`, fetch dir `/home/chuck/data/media/generated/pipeline` |
| MCP gateway | `https://llm.choukalos.com` (litellm proxy; MCP tools `mcp__litellm__mcp_media_*`) |
| Public routes | `https://siri.choukalos.com/media/pipeline/upload` (X-Api-Key = chuck/dylan LiteLLM key) and `/media/pipeline/dl/<token>` (signed URL, token is the credential). Everything else under `/media/pipeline/*` is 404 off-LAN. |
| Queue capacity | 1 running + 5 queued = **6 pending max**; submit returns **HTTP 503 + `retry_after_seconds`** when full |
| MCP tool-call timeout | **60 s hard timeout** at the gateway ("MCP request timed out after 60000ms") — transient and expected on long orchestrations; the job is unaffected, retry the call |
| Shot models | `wan14b` (Wan 2.2 14B I2V — 832×480 only, 81f/16fps, ~5 s clip, **~10–12 min/clip**; production default) · `ltxv2b` (LTXV 2B — 768×512, ~4 s clip, ~8 s/clip; fast draft / dry runs) |
| Keyframes | `qwen21` (Qwen-Image-2.1, ~30–120 s at 1280×720) · `legacy` (fast Lightning path, steps=4) |
| Audio | ACE-Step music, MMAudio SFX, TTS voice library (`trailer`, `narrator_f`, `deep_m`, … — see `media_list_voices`) |
| Vision QC | `mcp_vision_vision_analyze_image` (source = thor-local path under the allowed roots `/data/media`, `/workspace`, `/data/ai-kb/raw` — **GPU-host media_jobs paths are NOT visible to the vision container** — or an http(s) URL). For GPU-host images: `media_pull` signed URL → vision. For Mac-local frames: public upload route → `media_pull` → signed URL → vision (verified 2026-11-04). Fallback: `POST https://llm.choukalos.com/v1/chat/completions` with model `matrix-coder` and `image_url` content parts (base64 data URLs work) — **slow (~3–5 min/call) and flaky** (can return `None` content or error bodies; retry with rephrased prompt) |
| Job visibility | `media_list_jobs` — **durable ledger**: finished jobs survive pipeline restarts, live in-flight jobs included. Filters: `status` (running\|done\|error\|timeout, default running), `client` (**EXACT match** — jobs are tagged `<project>/<unit>`, so query per unit; the bare project prefix returns nothing — verified 2026-11-04), `user`, `flow`, `since` (**ISO-8601 only — `'2h'` is rejected**), `limit` (default 50, max 200). Returns `{count, jobs:[{job_id, flow, status, client, user, created, done, model, duration_s, cost_usd, error, output, outputs}]}` newest-first |
| Local tools (Mac) | `ffmpeg` at `/Users/chuck/bin/ffmpeg` (frame extraction, audio mixing) |

## The five survival rules

These are non-negotiable. Each one maps to a real failure in the peanut run.

### R1 — State file on disk, written immediately after every submit

Not codemode `store()` (lost when the script fails), not in-memory. Location:

```
~/Code/media-film/<project>/state.json
```

The codemode sandbox has no filesystem, so the chunk template writes it through
`tools.bash` with a quoted-delimiter heredoc (unique random delimiter per write).
**Every submit and every completion is followed by a state write before any
other work.** A job ID that is not on disk is a job ID that will be lost.

### R2 — Retry wrapper on every MCP call (4 attempts)

**Every** MCP call — media, vision, skills — goes through the wrapper. A
single un-retried 60 s gateway timeout kills the whole chunk (verified in the
2026-11-04 dry run: one un-wrapped vision call died the QC script and lost the
preceding verdicts). `name` is the full tool name
(`mcp__litellm__mcp_media_*`, `mcp__litellm__mcp_vision_*`, …):

```js
const mcall = async (name, args, tries = 4) => {
  let last;
  for (let i = 0; i < tries; i++) {
    try { return JSON.parse((await tools[name](args)).content[0].text); }
    catch (e) { last = e; }
    // Backoff WITHOUT timers — the codemode QuickJS sandbox has no setTimeout.
    // A cheap blocking call stands in (spec: media_job_result on a known-done
    // job with wait_seconds 25; media_list_jobs is the always-available variant).
    try { await tools.mcp__litellm__mcp_media_media_list_jobs({ status: "running", limit: 1 }); } catch (_) {}
  }
  throw last;
};
```

Two failure shapes to handle differently:
- **Transport timeout** ("MCP request timed out after 60000ms") → exception →
  `mcall` retries. The GPU job is unaffected (it keeps running).
- **503 queue full** → returned as an *error body*, not an exception:
  `{status:"error", error:"Pipeline HTTP 503: ... retry_after_seconds: N"}` →
  **stop submitting, keep polling** (R5). Never spin-submit.

### R3 — Timeboxed chunks

One codemode call per **4–8 job completions** (~45–90 min wall clock max).
Codemode's `timeout_ms` is unset by default, so a chunk may run long — but long
means fragile (context, gateway hiccups, model changes). The chunk template
carries `budget_ms`, `max_completions`, `max_passes`; when any trips it returns
the state summary and **pi starts a fresh chunk** from the on-disk state.
`Date.now()` works in the sandbox (only timers are missing).

### R4 — Resume protocol (on any crash)

1. **Read the state file.**
2. **Re-poll all known `job_id`s** (`media_job_result`, `wait_seconds: 20`) —
   live jobs stay in the registry while in flight.
3. **Ledger sweep** — `media_list_jobs(client=<project>/<unit>, status=running|done|error,
   since=<project created ISO>, limit=200)` **per unit id** (the client filter is
   exact-match — the bare project tag matches nothing) to recover IDs that
   never made it into the state file (crash between submit and persist —
   incident #1).
   **Adopt, don't resubmit:** a job found in the ledger that belongs to a shot
   gets recorded in state. Orphaned duplicates are harmless (14 d retention) but
   waste GPU time — the whole point is to avoid them.
4. **Resubmit only units with no recoverable job** (no ID in state AND nothing
   matching in the ledger).
5. **Continue from the pending lists** (`kf_pending`, `i2v_pending`, …).

`templates/resume.js` implements all five steps.

### R5 — Queue management

- Keep **≤5 in-flight submits** of your own (the queue is global: 1 running +
  5 queued = 6; other clients share it).
- Check in-flight count with `media_list_jobs(status="running")` → `.count`.
- On 503: stop submitting, poll until a slot frees, then resume submitting.
  Honor `retry_after_seconds` (it is the only signal you get).

## State file schema

Proven in the peanut run's `state.json`; extended with `client`, `kf*`,
`audio_jobs` (single source of truth per unit: the `kf`/`i2v`/`audio_jobs`
tables; `shots.*_job`/`*_path` are convenience mirrors the chunk keeps in sync).

```json
{
  "title": "...",
  "created": "2026-11-04T03:00:00Z",
  "client": "peanut-movie",
  "model": "wan14b",
  "target_duration_s": [90, 150],
  "assets": { "gpu_uploads": { "name": "<media_jobs path>" } },
  "identity": { "peanut": "<canonical identity prompt>" },
  "shots": {
    "S1": {
      "beat": "...",
      "kf_prompt": "...",
      "kf_job": "abc123",
      "kf_path": "/home/chuck/data/comfyui/run/media_jobs/abc123/....png",
      "i2v_prompt": "<visual style, gentle motion only>",
      "i2v_job": "def456",
      "i2v_path": "/home/chuck/data/comfyui/run/media_jobs/def456/....mp4",
      "qc": { "kf": "PASS", "clip": "PASS" }
    }
  },
  "kf":       { "S1": { "job_id": "abc123", "path": "...", "status": "done" } },
  "kf_pending": ["S2"],
  "i2v":      { "S1": { "job_id": "def456", "path": "...", "status": "done" } },
  "i2v_pending": ["S13"],
  "audio": { "music": "<path>", "vo": "<path>", "sfx": "<path>" },
  "audio_jobs": { "music": { "job_id": "...", "status": "done" }, "vo": { "job_id": "...", "status": "submitted" } },
  "assemble": { "job_id": "...", "path": "...", "shots": ["<gpu path>", ...], "text_overlays": [{ "text": "...", "start": 0, "end": 3 }] }
}
```

## Workflow

### P0 — Preflight

1. `media_list_jobs(status="running")` — pipeline up? (a response = the
   pipeline is alive; this replaces `GET /health` off-LAN). Note queue depth.
2. Create `~/Code/media-film/<project>/state.json` with `title`, `created`
   (ISO-8601 UTC — used as the ledger-sweep `since`), `client` (project tag,
   e.g. `peanut-movie`), `model` (`wan14b` production / `ltxv2b` dry run),
   `target_duration_s`, `identity` (one canonical identity prompt per
   character — reuse verbatim in every keyframe prompt).
3. Per-job client tags follow the convention **`<project>/<shot>`**
   (e.g. `peanut-movie/S1`) — this is what the resume sweep matches on.

### P1 — Storyboard / beats

`media_storyboard(brief, n_shots)` (or hand-write beats — fine for short
films). Store the shot list in `state.shots`: `beat`, `kf_prompt` (full scene
description + the character's canonical identity text), `i2v_prompt`
(**visual style + gentle motion only** — fast-motion prompts cause I2V
warble), `vo_text` if the shot carries VO.

### P2 — Keyframes + QC

Run `templates/chunk.js` with `phase: "kf"` (submit `media_generate_image`,
1280×720, `qwen21`). **QC every keyframe before spending I2V time** — a bad
keyframe costs ~1 min to regen vs ~11 min of I2V (R6 below). For cross-shot
character consistency, compose keyframes with `media_edit_image` using the
character sheet / a previous keyframe as `references`.

### P3 — I2V + QC

Run `chunk.js` with `phase: "i2v"` — this is the long phase (wan14b: ~11 min
per clip, serial queue → 20 shots ≈ 4+ h; expect many chunks). QC 2–3 action
frames per clip post-I2V (see R6). A failed clip: fix the `i2v_prompt` (or
seed) and resubmit — the shot stays in `i2v_pending`.

### P4 — Audio

- **VO:** `media_text_to_speech` per segment (pick the voice with
  `media_list_voices`). Multi-segment timing pattern: generate each segment,
  mix locally with ffmpeg (`adelay` + `amix`, see **Audio timing** below),
  upload the combined track via the public route
  (`curl -X POST -H "X-Api-Key: <chuck litellm key>" -F file=@vo_combined.wav
  https://siri.choukalos.com/media/pipeline/upload` → `{path}`), then pass a
  **single `vo` path with `vo_start: 0`** to assemble.
- **Music:** `media_generate_music(prompt, duration≈final cut)`.
- **SFX:** `media_sfx(video, description)` per clip if needed; assemble
  accepts `sfx` as a list `[{path, at}]` for timestamped placement.

### P5 — Assembly

`media_assemble` (non_blocking, client `<project>/assemble`):

- `shots`: **GPU-host paths** (from state) — never locally downloaded paths.
  Entries may be objects `{path, in?, out?, duration?}` for trims/stills.
- `vo` / `music` / `sfx`: GPU-host paths; `vo_start` for lead-in silence;
  `loudnorm: true` for EBU R128.
- `text_overlays`: crisp titles (`{text, start?, end?, position?, size?, color?}`)
  — **never** bake text into I2V (both models warp it).
- 1080p quality: `upscale_each: true` (SeedVR2, ~5 min/shot) — or upscale each
  shot with `media_upscale_video(pipeline="b")` first.

### P6 — Final QC

1. `media_info(final path)` — duration inside `target_duration_s`, video codec
   sane, **audio present** (`audio_codecs` non-empty).
2. Vision-check the final cut at **6–8 timeline points** (title card, each key
   beat, end card): pull the cut locally (signed URL from `media_pull`),
   extract frames with ffmpeg, vision each frame (see R6).
3. Fix-forward: a bad beat → trim/caption/replace the shot, re-assemble.

### P7 — Publish

1. `media_fetch(host_path=<final cut>)` → lands in
   `/home/chuck/data/media/generated/pipeline/` (the approved publish root;
   basename collisions get a `_2` suffix — use the returned **`local_path`**
   field verbatim).
2. `mcp_skills_run_skill(name="publish_file", params={source_path: <fetched
   path>, subdirectory: "video", destination_name: "<slug>.mp4"})`.
3. Verify: `curl -sIL https://choukalos.com/files/video/<slug>.mp4` → 200.
4. Record the public URL in `state.json`.

## R6 — QC gates (vision)

Vision-check at every expensive boundary:

| Gate | When | Cost of skipping |
|---|---|---|
| Every keyframe | before I2V submit | ~11 min I2V per bad keyframe |
| 2–3 action frames per clip | after I2V, before assembly | re-cut the whole film |
| Final cut, 6–8 timeline points | before publish | shipping a bad film |

**GPU-host image** (keyframe): `media_pull(path)` → signed URL →
`mcp_vision_vision_analyze_image(source=<url>, focus="commercial",
prompt="<brief + identity prompt + PASS/FAIL criteria>")` — **through
`mcall`** (vision calls regularly exceed the 60 s gateway timeout; the first
attempt can also be slow while the vision model loads). Response shape:
`{status, source, slug, artifacts_dir, frames, frame_files, report_markdown}`
— the verdict is in `report_markdown`.

**Video frames** (clip / final cut): mcp_vision can't see Mac-local files or
GPU-host media_jobs paths — stage the frame on the GPU host, then use a
signed URL (verified 2026-11-04):

```bash
# 1) extract frames locally (ffmpeg)
curl -sL -o /tmp/cut.mp4 "<signed URL from media_pull>"
for t in 1 15 30 45 60; do ffmpeg -y -ss $t -i /tmp/cut.mp4 -frames:v 1 /tmp/cut_$t.png; done
# 2) stage frames on the GPU host (public upload route; X-Api-Key = chuck litellm key,
#    from ~/.pi/agent/auth.json — verified working from the Mac)
KEY=$(python3 -c "import json; print(json.load(open('$HOME/.pi/agent/auth.json'))['litellm']['key'])")
curl -s -X POST -H "X-Api-Key: $KEY" -F "file=@/tmp/cut_15.png" \
  https://siri.choukalos.com/media/pipeline/upload   # -> {"path":".../media_jobs/uploads/<name>.png"}
# 3) vision via signed URL: media_pull(<uploaded path>) -> vision_analyze_image(source=url)
```

Fallback if the upload route or mcp_vision is down: `POST
https://llm.choukalos.com/v1/chat/completions` (model `matrix-coder`,
`image_url` content parts, base64 data URLs) — slow and flaky; a `None`
content or missing `choices` = retry once with rephrased prompt, then fall
back to the upload route.

Record verdicts in `state.shots.<id>.qc` (`PASS` / `FAIL: reason`).

## Audio timing pattern

Assemble's `sfx`/`text_overlays` `at`/`start`/`end` values are **absolute
timeline seconds** (from t=0 of the final cut), not per-shot offsets. VO is a
single track:

1. TTS each VO segment separately (`media_text_to_speech`).
2. `media_info` each segment → durations.
3. Mix locally (ffmpeg): `adelay=<ms>|<ms>` per segment + `amix`, one combined
   `vo.wav` whose t=0 aligns with the cut's t=0.
4. Upload combined track (public upload route, X-Api-Key) → single `vo` path,
   `vo_start: 0`.

## Templates

Both templates are codemode scripts: **pi adapts the `CFG` block** (state path,
client tag, phase, prompts already live in state) and runs the whole file.
They persist state through `tools.bash` heredocs after every submit/completion.

- `templates/chunk.js` — submit pending units + poll to completion, up to
  `max_completions` per run. Re-run until `pending` is empty.
- `templates/resume.js` — the R4 protocol: re-poll known IDs, ledger sweep for
  lost IDs, adopt-or-resubmit, report pending. Run it **first** after any
  crash, timeout, or session reset — before submitting anything new.

## Verification plan

- **Dry run:** 3-shot test film (`ltxv2b` drafts) through P0–P7.
- **Kill test:** mid-run, deliberately drop one just-submitted job ID from the
  state file (simulating the incident-#1 crash), then run `resume.js`; confirm
  the ledger sweep recovers the ID and the shot is **not** resubmitted
  (ledger shows exactly one `shots` job for that client tag).

## Known upstream gaps (pi codemode — not fixable from the skill)

1. `store()` should persist per-call, not only on script success — a crashed
   script loses all stored state (the exact failure that cascaded in the
   peanut run). Mitigation here: R1 (on-disk state via `tools.bash`).
2. No `sleep(ms)` — `setTimeout` is undefined in the QuickJS sandbox
   (ReferenceError after the script had already submitted 5 GPU jobs).
   Mitigation here: R2's blocking-call backoff.