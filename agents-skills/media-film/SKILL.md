---
name: media-film
description: "Orchestrate a multi-shot short film through the mcp_media GPU pipeline — keyframes (Qwen-Image 2.1), I2V clips (Wan 2.2 / LTXV), TTS/music/SFX, assembly, vision QC, and publish. Crash-proof by design: on-disk state file written after every submit, retried MCP calls, timeboxed codemode chunks, and a resume protocol built on the durable job ledger (media_list_jobs)."
---

# media-film — multi-shot film orchestration

Orchestrate a multi-shot film (keyframes → I2V clips → audio → assembly → QC →
publish) through the `mcp_media` tools, the way the 2026-11-02 "A Peanut Risky
Business" run (20 shots, ~5 h) should have been run. Everything in this skill is
encoded from that incident: 4 orchestration-script deaths, 10 lost job IDs, ~1 h
of log archaeology, 6 duplicate I2V jobs. Extended 2026-11-19 with the
2026-11-16/17 SW Holiday Spoof production lessons (36 shots, ~16 h, 30
attempts — 11 children died on 524s, one 44.5 s-short cut cost a 4.5 h
upscale render): items C1–C14, A2, D1 below.

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
| MCP gateway | `https://llm.choukalos.com` (litellm proxy). Tool names in the `tools` object are pi-codemode names, and they differ per pi/host version (verified 2026-11-19): **thor pi 1.3.0** = `mcp__litellm__mcp_media_<tool>` (underscore), **Mac (2026-11-17)** = `mcp_media-<tool>` (dash). Raw gateway names (`/v1/mcp/tools`) are dash-form. The chunk/resume templates auto-detect the working form with a cheap `media_list_jobs` call before the first real call — do the same in ad-hoc scripts. |
| Public routes | `https://siri.choukalos.com/media/pipeline/upload` (X-Api-Key = chuck/dylan LiteLLM key) and `/media/pipeline/dl/<token>` (signed URL, token is the credential). Everything else under `/media/pipeline/*` is 404 off-LAN. |
| Queue capacity | 1 running + 5 queued = **6 pending max**; submit returns **HTTP 503 + `retry_after_seconds`** when full |
| MCP tool-call timeout | **60 s hard timeout** at the gateway ("MCP request timed out after 60000ms") — transient and expected on long orchestrations; the job is unaffected, retry the call |
| Shot models | `wan14b` (Wan 2.2 14B I2V Q8_0 GGUF — promoted 2026-11-22 — 832×480 ~10–12 min/clip **or 1280×720 ~55 min/clip** (CPU offload), 81f/16fps recommended, ~5 s clip; 129f (~8 s clip) accepted but experimental — quality degrades vs 81f, ~115 min/720p clip; production default) · `ltxv2b` (LTXV 2B — 768×512 ~4 s clip ~8 s/clip, or **1280×720 for 720p-class drafts** ~4 s clip ~18 s/clip → 1280×704 out; fast draft / dry runs) |
| Keyframes | `qwen21` (Qwen-Image-2.1, ~30–120 s at 1280×720 — best keyframe model, vision-verified 2026-11-22) · `legacy` (fast Lightning path, steps=4 — 2512 Q4_0 default, Q6_K staged as a marginal upgrade) |
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
preceding verdicts). `name` is the full tool name — resolved prefix + tool
(`M + "media_*"`, `V + "vision_*"`). **The prefix differs per pi/host version**
(verified 2026-11-19: thor pi 1.3.0 = `mcp__litellm__mcp_media_` underscore form;
Mac 2026-11-17 = `mcp_media-` dash form) — resolve it once with a cheap call
before the first real call, trying both forms:

```js
let M = null, V = null;
const ensurePrefixes = async () => {
  if (M) return;
  const forms = [
    ["mcp__litellm__mcp_media_", "mcp__litellm__mcp_vision_"],
    ["mcp_media-", "mcp_vision-"],
  ];
  for (const [m, v] of forms) {
    try { await tools[m + "media_list_jobs"]({ status: "running", limit: 1 }); M = m; V = v; return; } catch (_) {}
  }
  throw new Error("media tool prefix unresolved — both name forms failed");
};

const mcall = async (name, args, tries = 4) => {
  let last;
  for (let i = 0; i < tries; i++) {
    try { return JSON.parse((await tools[name](args)).content[0].text); }
    catch (e) { last = e; }
    // Backoff WITHOUT timers — the codemode QuickJS sandbox has no setTimeout.
    // A cheap blocking call stands in (spec: media_job_result on a known-done
    // job with wait_seconds 25; media_list_jobs is the always-available variant).
    try { await tools[M + "media_list_jobs"]({ status: "running", limit: 1 }); } catch (_) {}
  }
  throw last;
};
await ensurePrefixes(); // run before the first MCP call
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

## Shot-director fan-out conventions (A2, D1)

The 2026-11-17 run fanned out 36 shot-director children in one wave; 11 died
on 524s (Cloudflare origin read timeout) and production started with missing
cards.

- **A2 — cap fan-out at 8–12 concurrent**, batched into 3–4 waves. The GPU
  queue is the real bottleneck downstream anyway — more concurrent children
  does not speed up the pipeline, it just multiplies 524s.
- **D1 — per-shot auto-retry:** 1 retry on `!ok` (child died / card missing),
  with a 120 s backoff for 524s (the timeout is retryable; the first turn
  often writes the card before dying — check disk before resubmitting).
- **D1 — preflight gate before production:** verify all shot cards exist on
  disk (P0 step 4) — never start production with missing cards.

## State file schema

Proven in the peanut run's `state.json`; extended with `client`, `kf*`,
`audio_jobs`. **C1 — single source of truth:** the per-shot records
(`shots.<id>.{kf,i2v,qc,vo}` and the `kf`/`i2v`/`audio_jobs` tables) are the
single source of truth; the `*_pending` lists are **derived at read time**
(or recomputed on every write) — never the source of truth. `shots.*_job`/
`*_path` are convenience mirrors the chunk keeps in sync. State drift
(pending lists disagreeing with records) cost the 2026-11-17 run hours of
manual reconciliation — run `tools/validate_state.py` as preflight (children
refuse to proceed on mismatch; `--fix` repairs lists/mirrors from records).

**C11 — one canonical state key per audio item:** `tts_<shot>` (e.g.
`tts_S1`), `sfx_<name>`, `music_cue_<x>` in `audio_jobs` — written once at
submit, updated in place on completion. No parallel key families (a stale
`submitted` key in a second family over-reports pending audio). `audio` holds
final mix inputs for assemble (paths only — e.g. the combined uploaded VO
track — no job/status keys).

**C12 — prompts are raw text end-to-end:** prompt fields in state are plain
strings (the template's `rawPrompt` getter asserts this). Never
`JSON.stringify` a prompt into state, and never paste JSON-encoded values
into MCP prompt fields — bash submits build args with `jq -n --arg`. Preflight
diff: the submitted prompt must equal the card's `i2v_prompt` exactly
(validate_state.py rejects double-encoded prompts).

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
  "audio": { "vo": "<combined uploaded track>", "music": "<path>", "sfx": "<path>" },
  "audio_jobs": { "tts_S1": { "job_id": "...", "path": "...", "status": "done" }, "music_cue_main": { "job_id": "...", "status": "submitted" } },
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
4. **D1 — card preflight gate:** verify every shot card exists on disk
   (`<project>/shots/<id>.json`, one per shot id in `state.shots`) and run
   `python3 <skill>/tools/validate_state.py state.json --cards shots/` —
   production never starts with missing cards (the 2026-11-17 run started
   with 11 cards missing after 524 deaths).
5. Run `tools/validate_state.py state.json` (C1) — lists vs records, mirrors
   vs tables, C11 audio keys, C12 raw-text prompts. Refuse to proceed on
   mismatch.

### P1 — Storyboard / beats

`media_storyboard(brief, n_shots)` (or hand-write beats — fine for short
films). Store the shot list in `state.shots`: `beat`, `kf_prompt` (full scene
description + the character's canonical identity text), `i2v_prompt`,
`vo_text` if the shot carries VO.

**C2 — shot cards are schema'd.** One card per shot in
`<project>/shots/<id>.json`, copied from `templates/_card_template.json`
(canonical shape: string `vo_text`, canonical `voice`, numeric `duration_s`).
The parent runs the validator before production (`validate_state.py
--cards shots/`) — three different `vo_text` shapes appeared in one run, and
each one cost a rework.

**C3 — `i2v_prompt` identity re-anchor.** Template:
`[one-line identity re-anchor per character in frame] + [gentle motion spec]
+ [1978 TV look]`. The keyframe only anchors frame 0 — over 5 s the model
drifts back toward its priors (S4 drifted tuxedo bicolor → brown tabby).
Re-state each character's identity in the prompt itself. Keep **gentle
motion only** — fast-motion prompts cause I2V warble.

**C4 — implied gags.** Feasibility rule at plan stage: if a gag depends on a
complex object state (broken, headless, torn, melted), make it **implied** —
SFX + caption + reaction shots — not rendered. I2V models cannot hold
complex object-state changes; a rendered attempt is a wasted clip +
fix-forward.

**C5 — ≤3 characters per frame.** Count characters in each frame from the
identity refs; enforce ≤3 (or flag for the reviewer) — more identity
references degrades consistency.

**C14 — never plan durations by estimate.** Per-shot durations MUST be
derived from the actual clip length (`media_info` after I2V) — the assembler
concatenates at natural clip length (`shots[].duration` has no effect, see
the pipeline contract), so the plan's total is Σ of the measured clip
lengths, not the creative estimate.

### P2 — Keyframes + QC

Run `templates/chunk.js` with `phase: "kf"` (submit `media_generate_image`,
1280×720, `qwen21`). **QC every keyframe before spending I2V time** — a bad
keyframe costs ~1 min to regen vs ~11 min of I2V (R6 below). For cross-shot
character consistency, compose keyframes with `media_edit_image` using the
character sheet / a previous keyframe as `references`.

**C6 — bounded fix-forward:** kf = 3 attempts, then `ACCEPTED-WITH-NOTE` or
the `shots.json` (storyboard) fallback — a fourth attempt is a scope decision
for the owner, not the worker.

### P3 — I2V + QC

Run `chunk.js` with `phase: "i2v"` — this is the long phase (wan14b: ~11 min
per clip, serial queue → 20 shots ≈ 4+ h; expect many chunks). QC 2–3 action
frames per clip post-I2V (see R6). A failed clip: fix the `i2v_prompt` (or
seed) and resubmit — the shot stays in `i2v_pending`.

**C6 — bounded fix-forward:** I2V clip = 2 attempts, then accept the best
clip (record why in `qc`).

### P4 — Audio

- **VO:** `media_text_to_speech` per segment (pick the voice with
  `media_list_voices`). Multi-segment timing pattern: generate each segment,
  mix locally with ffmpeg (`adelay` + `amix`, see **Audio timing** below),
  upload the combined track via the public route
  (`curl -X POST -H "X-Api-Key: <chuck litellm key>" -F file=@vo_combined.wav
  https://siri.choukalos.com/media/pipeline/upload` → `{path}`), then pass a
  **single `vo` path with `vo_start: 0`** to assemble.
- **Music:** `media_generate_music(prompt, duration≈final cut)` — state key
  `music_cue_<x>`.
- **SFX:** `media_sfx(video, description)` per clip if needed; assemble
  accepts `sfx` as a list `[{path, at}]` for timestamped placement — state
  key `sfx_<name>`.
- **C11 — canonical audio keys:** one `audio_jobs` key per audio item —
  `tts_<shot>` / `sfx_<name>` / `music_cue_<x>` — written once at submit,
  updated in place; no parallel key families (a stale `submitted` key in a
  second family over-reports pending audio).
- **C9 — TTS is 22050 Hz mono.** Probe the actual sample rate before any
  `asetrate` (see **Audio timing** below) — the 2026-11-17 plan assumed
  44100 and would have doubled every pitch shift (silent landmine).

### P5 — Assembly

`media_assemble` (non_blocking, client `<project>/assemble`):

- `shots`: **GPU-host paths** (from state) — never locally downloaded paths.
  Entries may be objects `{path, in?, out?, duration?}` for trims/stills.
  **C14 — `duration` does NOT frame-hold:** the assembler concatenates each
  clip at its **natural length**; the `duration` field is accepted but has no
  effect (verified in the 2026-11-17 run: 36 × 5.042 s → 181.5 s output vs a
  226 s plan). Plan on measured lengths only.
- `vo` / `music` / `sfx`: GPU-host paths; `vo_start` for lead-in silence;
  `loudnorm: true` for EBU R128.
- `text_overlays`: crisp titles (`{text, start?, end?, position?, size?, color?}`)
  — **never** bake text into I2V (both models warp it).
- **C8 — assemble preflight:** `media_info` on **every** shot path and every
  audio path before submitting; abort with the precise missing list (a
  44.5 s-short cut must never reach the render queue). `chunk.js` does this
  automatically for `phase: "assemble"`.
- **C13 — draft assemble before you pay for the final.** Assemble a draft
  (`upscale_each: false`, ~90 s for 36 shots), run the full P6 QC on the
  draft, and only submit the final upscaled render if the draft passes — the
  2026-11-17 run paid a 4.5 h upscale render before discovering a 44.5 s-short
  cut. Expected wall-clock per config is in the pipeline contract
  (~12.5 min/shot upscale under shared-queue contention — NOT the ~5 min
  estimate).
- 1080p quality: `upscale_each: true` (SeedVR2 — plan ~12.5 min/shot under
  contention, see the pipeline contract) — or upscale each shot with
  `media_upscale_video(pipeline="b")` first.

### P6 — Final QC

1. `media_info(final path)` — duration inside `target_duration_s`, video codec
   sane, **audio present** (`audio_codecs` non-empty). **C14 — the numeric
   gate is not enough:** also verify the **last VO start + VO duration** and
   the **last overlay end fit inside the cut** (`last_vo_start +
   vo_duration ≤ cut_duration`, `max(overlay.end) ≤ cut_duration`). The
   numeric gate alone let a 44.5 s-short film (missing closing VO + end card)
   pass after a 4.5 h upscale render.
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
5. **When running under the kanban orchestrator (mcp_kanban container):**
   the orchestrator re-runs a deploy stage after QA that re-publishes from
   `publish_targets[0]` of the task spec. The blog's public file area is a
   **directory, not a git repo** — in the kanban container it is mounted at
   `/publish` (= host `/home/chuck/data/media/public` =
   `https://choukalos.com/files/`). Write `publish_targets` entries as
   **machine-readable absolute container paths, path first, no prose around
   the path**:
   - NAS archive: `/media-store/<project>/<task>/` (container mount of the
     lego media share; thor equivalent `/mnt/lego-media-store/...`)
   - Public drop: `/publish/video/<slug>.mp4`
   Prose entries ("NAS 'media' share: /media-store/...") crashed the deploy
   stage on 2026-11-23 (task 3, PWV2 F2-B) — the stage now extracts embedded
   paths, but clean paths are the convention and the only safe form.
6. **Task inputs must be reachable from the executor (2026-11-23, PWV2
   lesson):** the `mcp_kanban` container cannot see the authoring machine's
   filesystem — client-local paths (`~/Code/...`) in a spec are unreachable
   and the task stops at the P0 preflight gate (PWV2 tasks 1–2, 2026-11-22/23;
   the inputs had to be `scp`'d in by hand). Use the file-intake conventions:
   - **Small inputs** (scripts, configs, text — ≤ ~100 MB): the `stage_file`
     MCP tool (or `POST /api/projects/<id>/files`) pushes the content into the
     project's durable store; cite the returned `/files/<project_id>/<path>`
     in the spec. Staged files live for the life of the project (icebox-safe).
   - **Media inputs** (stills, reference video, audio): place them where media
     already lives — the NAS (`/media-store/...`) or the public drop
     (`/publish/...` = `https://choukalos.com/files/...`) — and cite the
     container path or public URL in the spec (optionally register with
     `stage_ref`, which validates reachability at registration). Never tunnel
     media through MCP.
   `move_to_backlog`/`start_task` run a spec-path preflight that warns about
   unreachable references (advisory by default) — fail fast at task creation,
   not after two QA rounds.

## R6 — QC gates (vision)

Vision-check at every expensive boundary:

| Gate | When | Cost of skipping |
|---|---|---|
| Every keyframe | before I2V submit | ~11 min I2V per bad keyframe |
| 2–3 action frames per clip | after I2V, before assembly | re-cut the whole film |
| Final cut, 6–8 timeline points | before publish | shipping a bad film |

**Verdicts:** `PASS` / `FAIL: reason` / **`ACCEPTED-WITH-NOTE`** (C4) — a
first-class outcome, not a cop-out: the defect is real but the beat survives
because **the VO or a neighbor shot carries it**. Record
`ACCEPTED-WITH-NOTE: <what's wrong> + <where the beat lives>` in
`state.shots.<id>.qc`. It never excuses identity drift that breaks the story.

**C7 — batch vision QC:** if the vision tool accepts multiple images, judge
the 3 action frames in **one call** (one verdict per clip) instead of three
separate calls.

**C6 — bounded fix-forward budgets:** kf = 3 (then accept-with-note or
`shots.json` fallback), I2V clip = 2 (then accept best), audio = 2. Budgets
are hard stops — a fourth attempt is a scope decision for the owner.

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
3. **C9 — probe the actual sample rate before any `asetrate`.** TTS output
   is **22050 Hz mono** (music is 48000 Hz stereo — see the pipeline
   contract). `SR=$(ffprobe -v error -select_streams a:0 -show_entries
   stream=sample_rate -of csv=p=0 seg.wav)`; pitch-shift with
   `asetrate=SR*P,aresample=44100` (P = pitch factor, **SR from the probe —
   never from plan text**; a 44100-based formula on 22050 Hz audio doubles
   every pitch shift — a silent landmine).
4. **C10 — mix with `amix=normalize=0`, always.** The default normalize
   divides by the input count: a 19-input mix lands ~25 dB too quiet —
   effectively silent.
5. **C10 — post-mix level check before upload:** `ffmpeg -i vo_combined.wav
   -af volumedetect -f null -` → sanity-gate `mean_volume` / `max_volume`
   (expect mean ≈ -20…-12 dB, max < 0 dB; a mean near -30 dB means the mix
   is silent — do not upload).
6. Mix locally (ffmpeg): `adelay=<ms>|<ms>` per segment +
   `amix=inputs=N:normalize=0`, one combined `vo.wav` whose t=0 aligns with
   the cut's t=0.
7. Upload combined track (public upload route, X-Api-Key) → single `vo` path,
   `vo_start: 0`.

## Templates & tools

Both templates are codemode scripts: **pi adapts the `CFG` block** (state path,
client tag, phase, prompts already live in state) and runs the whole file.
They persist state through `tools.bash` heredocs after every submit/completion.

- `templates/chunk.js` — submit pending units + poll to completion, up to
  `max_completions` per run. Re-run until `pending` is empty. Enforces the
  C12 raw-text prompt getter, the C8 assemble preflight, and C11 canonical
  audio keys.
- `templates/resume.js` — the R4 protocol: re-poll known IDs, ledger sweep for
  lost IDs, adopt-or-resubmit, report pending. Run it **first** after any
  crash, timeout, or session reset — before submitting anything new.
- `templates/_card_template.json` — the canonical shot card (C2); copy to
  `<project>/shots/_card_template.json` and emit one card per shot.
- `tools/validate_state.py` — C1 state validator: cross-checks `*_pending`
  lists vs records, mirrors vs tables, job ids, C11 audio keys, C12 raw-text
  prompts; `--cards shots/` validates shot cards (C2); `--fix` repairs
  lists/mirrors from the records (records win). Run as preflight (P0 steps
  4–5) and after every chunk; exit 1 = refuse to proceed.

## Verification plan

- **Dry run:** 3-shot test film (`ltxv2b` drafts) through P0–P7.
- **Kill test:** mid-run, deliberately drop one just-submitted job ID from the
  state file (simulating the incident-#1 crash), then run `resume.js`; confirm
  the ledger sweep recovers the ID and the shot is **not** resubmitted
  (ledger shows exactly one `shots` job for that client tag).
- **State validator:** `validate_state.py` on a real project state (+
  `--cards`) exits 0; inject a drift (a done id left in `i2v_pending`, a
  stale mirror) → exit 1; `--fix` repairs lists/mirrors from the records.

## Known upstream gaps (pi codemode — not fixable from the skill)

1. `store()` should persist per-call, not only on script success — a crashed
   script loses all stored state (the exact failure that cascaded in the
   peanut run). Mitigation here: R1 (on-disk state via `tools.bash`).
2. No `sleep(ms)` — `setTimeout` is undefined in the QuickJS sandbox
   (ReferenceError after the script had already submitted 5 GPU jobs).
   Mitigation here: R2's blocking-call backoff.