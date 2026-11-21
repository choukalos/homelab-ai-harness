# mcp_media pipeline contract (self-contained summary, updated 2026-11-21)

The canonical contract lives on the GPU host (`docs/matrix_media_pipeline_api.md`)
— unreachable off-LAN. This file is the
self-contained summary the skill needs. Tool names below are the MCP names
(dash-form at the gateway, e.g. `mcp_media-media_list_jobs` per `/v1/mcp/tools`;
in the pi codemode `tools` object they carry a version-dependent prefix — see
SKILL.md "MCP gateway" row); the underlying pipeline
endpoints are on `matrix:8189` (LAN-only).

## Job model

- Every generation flow is a **job**: `queued → running → done|error` (or
  `killed` — a queued job aborted via `media_kill_job`; terminal, ledger-
  recorded).
- **Queue:** 1 running + 5 queued = 6 in-flight max (global, shared by all
  clients). Full queue → **HTTP 503 + `retry_after_seconds`**.
- **Queue visibility:** `media_queue_status()` (M3, 2026-11-19) — running/
  queued job IDs, per-job `waited_s` (FIFO), `oldest_queued`, and the
  pipeline's `features` list. Check it before submitting; estimate wait from
  `oldest_queued.waited_s` + the wall-clocks below.
- **Kill:** `media_kill_job(job_id, client?)` (M2, 2026-11-19) — queued-only
  (frees the FIFO slot); running → refused (GPU work is never killed);
  terminal → idempotent no-op. Use it for superseded/orphaned queued jobs.
- **Durable ledger:** finished jobs (incl. `killed`) survive pipeline
  restarts; live in-flight jobs are included. 14-day retention on result files.
- **Job ID validity:** `media_job_result` works while the job is in the
  pipeline's registry (live) or the durable ledger (finished).
- **MCP gateway timeout:** 60 s hard per tool call — transient
  "MCP request timed out after 60000ms" is EXPECTED on long orchestrations.
  The GPU job is unaffected; retry the call.
- **`client` tag:** every job accepts `client` (convention
  `<project>/<shot>`, e.g. `peanut-movie/S1`) — recorded in the ledger; query
  with `media_list_jobs(client=...)`.
- **`non_blocking`:** every generation tool accepts `non_blocking: true` →
  returns `{job_id}` in ~1 s; poll `media_job_result(job_id)`.

## The tools the film flow uses

| Tool | Purpose | Key params | Returns |
|---|---|---|---|
| `media_storyboard` | LLM shot list | `brief, n_shots=5, aspect="16:9"` | `{shots:[{id,visual,vo}]}` |
| `media_generate_image` | keyframe (Qwen-Image 2.1) | `prompt, width=1280, height=720, seed=42, steps=25, model="qwen21"\|"legacy"` | `{path, location}` |
| `media_edit_image` | compose keyframe w/ identity refs | `image, prompt, references≤9 (qwen21), seed, steps` | `{path}` |
| `media_generate_shot` | I2V clip | `keyframe, prompt, model="wan14b"\|"ltxv2b" (omit=server default), width/height/frames/fps (omit=model defaults), seed=42, strength=0.7 (ltxv2b only)` | `{path}` |
| `media_text_to_speech` | VO | `text, voice="trailer"\|library name\|ref wav path` | `{path}` |
| `media_generate_music` | ACE-Step | `prompt, lyrics="", duration=30, seed=42` | `{path}` |
| `media_sfx` | MMAudio SFX bed | `video, description, duration=8.0` | `{path}` |
| `media_assemble` | final cut | `shots:[gpu path \| {path,in?,out?,duration? (ENFORCED since 2026-11-19 — see "Assemble semantics")}], vo?, music?, sfx?: path\|[{path,at}], vo_start=0, loudnorm=false, text_overlays:[{text,start?,end?,position?,size?,color?}], upscale_each=false, width=1920, height=1080, fps=24, *_volume` | `{path}` (+ `duration_adjustments` in the job output when any shot requested a duration) |
| `media_upscale_video` | SeedVR2 / fast | `video, pipeline="b"\|"a2", resolution=1080` | `{path}` |
| `media_trim` / `media_freeze` / `media_caption` | ffmpeg post | source (gpu or staging path) | `{path}` |
| `media_info` | ffprobe (sync) | `path` | `{duration_s,width,height,fps,video_codec,audio_codecs[],size_bytes,bitrate_bps}` |
| `media_job_result` | poll a job | `job_id, wait_seconds=20 (max 25)` | final result `{path,...}` or `{status:"running"}` (+ `progress: {stage, completed, total, label}` while an assemble is in flight — M5) or `{status:"error",error}` |
| `media_list_jobs` | **durable ledger** | `status="queued"\|"running"\|"done"\|"error"\|"timeout"\|"killed" (default running), client?, user?, flow?, since? (ISO-8601 ONLY), limit=50 (max 200)` | `{count, jobs:[{job_id,flow,status,client,user,created,done,model,duration_s,cost_usd,error,output,outputs}]}` newest-first |
| `media_kill_job` | kill a queued job | `job_id, client? (tag you submitted with; mismatch → refused)` | `{job_id, killed, status, queue_position_freed?}` — queued-only (running → error; terminal → no-op) |
| `media_queue_status` | queue summary (sync) | — | `{ok, pending, running, queued, max_concurrent, max_queue_depth, queue: {counts, queued_jobs (FIFO: job_id/flow/client/created/waited_s), oldest_queued}, features}` |
| `media_pull` | signed public URL | `path (abs gpu path \| media_jobs/<job>/<file> \| job_id), ttl_hours=24 (max 168), local_dir? (thor-local copy)` | `{url, expires_at, ...}` — `https://siri.choukalos.com/media/pipeline/dl/<token>` |
| `media_fetch` | → local media library (thor) | `host_path, subdirectory?` | local path under `/home/chuck/data/media/generated/pipeline` (basename collisions get `_2` suffix; never overwrites) |
| `media_put` / `media_download` / `media_upload` | stage inputs | `media_put` = thor-local file under `/home/chuck/workspace/media`; `media_download` = http(s) URL; `media_upload` = matrix ComfyUI basedir file | `{path}` (media_jobs) |
| `media_list_voices` | TTS library (sync) | — | `{voices:[{name,description,gender,style,...}]}` |

## Models

| Model | Flow | Specs | Speed |
|---|---|---|---|
| `wan14b` | I2V (default) | Wan 2.2 14B, **832×480 only** (720p → 400 VRAM gate), 81f (4n+1), 16fps, ~5 s clip | ~10–12 min/clip |
| `ltxv2b` | I2V (draft) | LTXV 2B, 768×512, 97f, 25fps, ~4 s clip; `strength=0.7` anchors the keyframe | ~8 s/clip |
| `qwen21` | keyframes (default) | Qwen-Image-2.1, 25 steps, steps clamped [10,50] | ~30–120 s @1280×720 |
| `legacy` | keyframes (fast) | Qwen-Image-2512 GGUF + Lightning, steps=4 | seconds |

> **VRAM gate note (2026-11-21):** the pipeline host is 2-GPU since 2026-11-14 —
> the media pipeline runs on the dedicated **RTX PRO 4000 24GB** (GPU 1,
> `device_ids: ['1']`, XOR the Ollama copywriter); GPU 0 (RTX PRO 5000 72GB)
> is the vLLM daily-LLM card. The resolution ceilings above (e.g. wan14b
> 720p → 400, measured 2026-10-25) predate the 2nd card — re-verify against
> the 24GB card before relaxing them.

## Paths & retention

- GPU-host artifacts: `/home/chuck/data/comfyui/run/media_jobs/<job_id>/mp_<job_id>_00001.{mp4,png,wav,…}` — **14-day retention**.
- `media_fetch` local dir (thor): `/home/chuck/data/media/generated/pipeline` — the **approved publish root** for `publish_file`.
- Public routes (off-LAN): `https://siri.choukalos.com/media/pipeline/dl/<token>` (signed, public) and `/media/pipeline/upload` (X-Api-Key = chuck/dylan LiteLLM key; multipart; 500 MB cap). Everything else under `/media/pipeline/*` is 404 off-LAN.

## Quality rules (tuned on the GPU host)

- **C14 — Assemble semantics: `shots[].duration` IS enforced (fixed
  2026-11-19, M1).** The assembler now frame-holds (last frame, `tpad
  stop_mode=clone`) or trims each object shot to its requested `duration`
  (±0.1 s tolerance = no-op), applied after `in`/`out` and before
  `upscale_each`. Every adjustment is reported in the job's
  `duration_adjustments` (`applied: hold|trim|none`) — visible via
  `media_list_jobs` `output`; **check it after a film assemble** instead of
  assuming the plan total. (Pre-fix history: the field was silently ignored
  — 2026-11-17 production: 36 × 5.042 s clips → 181.5 s output vs a 226 s
  plan. For pre-2026-11-19 jobs, plan totals from measured clip lengths
  (`media_info` after I2V), never from `duration` or creative estimates.)
- I2V `prompt`: **visual style + gentle motion only** — fast-motion prompts
  cause warble.
- Don't bake text into I2V (both models warp it) — use `media_assemble`
  `text_overlays` (ffmpeg drawtext, crisp).
- Character consistency: character sheet (T2I) → `media_edit_image`
  `references` (up to 9; canvas follows the edited image, references steer
  identity) → I2V from those keyframes. Expect 1–3 retries/shot.
- 1080p: assemble from SeedVR2-upscaled shots (`upscale_each: true` or
  `media_upscale_video(pipeline="b")` per shot) — never raw 832×480.
- `media_assemble` `shots` MUST be GPU-host paths (auto-fetched) — never
  locally downloaded paths.
- Assemble `sfx`/`text_overlays` `at`/`start`/`end` = **absolute timeline
  seconds** from t=0 of the final cut.

## Audio formats (verified 2026-11-17)

- **TTS output: 22050 Hz mono.** Probe the actual sample rate before any
  `asetrate` (`ffmpeg -i` / `media_info`); pitch-shift with
  `asetrate=SR*P,aresample=44100` using the probed SR. A 44100-based formula
  would double every pitch shift (silent landmine).
- **Music (ACE-Step): 48000 Hz stereo.**
- **`amix` mixes with `normalize=0`** — the default divides by the input
  count (19 inputs ≈ 25 dB too quiet, effectively silent). Level-check the
  mix (`volumedetect`/`astats` mean/max dB) before upload.

## Assemble wall-clock (observed 2026-11-17 — 36-shot film)

Range-based, under shared-queue contention — plan with the top of the range:

| Config | Observed |
|---|---|
| Draft assemble (`upscale_each: false`) | **~90 s for 36 shots** |
| Upscaled assemble (`upscale_each: true`, SeedVR2) | **~12.5 min/shot** (~7+ h for 36 shots) — the ~5 min/shot estimate is optimistic |

**Draft-then-final (C13):** assemble the draft, run full final QC on it, and
only pay for the upscaled render if the draft passes.