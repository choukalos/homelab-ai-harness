# mcp_media pipeline contract (self-contained summary, updated 2026-11-28 — films handoff B1–B5 tools added)

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
| `media_generate_image` | keyframe (Qwen-Image 2.1 — best keyframe model, vision-verified 2026-11-22) | `prompt, width=1280, height=720, seed=42, steps=25, model="qwen21"\|"legacy" (legacy = 2512 Q4_0 default; Q6_K staged as a marginal upgrade)` | `{path, location}` |
| `media_edit_image` | compose keyframe w/ identity refs | `image, prompt, references≤9 (qwen21), seed, steps` | `{path}` |
| `media_generate_shot` | I2V clip | `keyframe, prompt, model="wan14b"\|"ltxv2b" (omit=server default), width/height/frames/fps (omit=model defaults — ltxv2b 1280×720 drafts supported → 1280×704 out; wan14b 81f recommended, 129f experimental), seed=42, strength=0.7 (ltxv2b only), end_keyframe? (Films B2 — optional SECOND keyframe → FLF2V, the clip interpolates start→end; wan14b-only: clean 400 with ltxv2b; 720p admitted)` | `{path}` (job output carries `end_keyframe: true`) |
| `media_text_to_speech` | VO | `text, voice="trailer"\|library name\|ref wav path` | `{path}` |
| `media_generate_music` | ACE-Step | `prompt, lyrics="", duration=30, seed=42` | `{path}` |
| `media_sfx` | MMAudio SFX bed | `video, description, duration=8.0` | `{path}` |
| `media_assemble` | final cut | `shots:[gpu path \| {path,in?,out?,duration? (ENFORCED since 2026-11-19 — see "Assemble semantics")}], vo?, music?, sfx?: path\|[{path,at}], vo_start=0, loudnorm=false, text_overlays:[{text,start?,end?,position?,size?,color?}], upscale_each=false, width=1920, height=1080, fps=24, *_volume, lut? (Films B2 — .cube 3D LUT on the final concat: bundled name `cinematic_teal_amber`/`warm_neutral`/`cool_noir`, run-dir-relative path, or absolute path; unresolvable → clean 400 at submit), grain? (Films B2 — 0.0–1.0 temporal film grain; out of range → clean 400; both absent = no grade)` | `{path}` (+ `duration_adjustments` in the job output when any shot requested a duration) |
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
| `media_project_create(slug, title?)` | film project store (sync) | `POST /projects` | `{slug, project (abs dir), status: 'draft', nas_sync}` — slug `^[a-z0-9_]{1,64}$` (400 otherwise; 409 exists) |
| `media_project_list()` | film project store (sync) | `GET /projects` | `{projects: [{slug, title, status, updated, nas_pending}], root, nas_root}` — slug recovery after a session reset |
| `media_project_get(slug)` | film project store (sync) | `GET /projects/{slug}` | full state (404 unknown): `{slug, title, status ('draft' → 'storyboard_approved'), created, updated, approval {storyboard: ISO\|null, by, note}, nas_sync {last, ok, pending, files, reason?}, assets {path: {size, added}}, tree {bible, storyboard, production}, takes}` — **project-first: the durable source of truth (F1); check `approval.storyboard` before rendering (F2)** |
| `media_project_asset(slug, path, file)` | film project store (sync) | `POST /projects/{slug}/assets` | register an asset (char sheet / env plate / keyframe / voice ref / script / `takes.json`): `path` project-relative (400 on `..`/absolute), `file` = staging file or GPU-host `media_jobs` path (auto-fetched) → `{path (abs), size, location}` |
| `media_project_shotplan(slug, shotplan?)` | film project store (sync) | `POST`/`GET /projects/{slug}/shotplan` | two-tier shotplan (Scene → Beats → Micro-shots) — pure pass-through; omitted → GET (404 when none saved) + `saved` + `schema_warnings`; given → save → `{shotplan (abs path), warnings}`; 400s carry the exact field errors (schema: `agents-skills/media-storyboard/references/shotplan-schema.md`) |
| `media_project_storyboard_pages(slug, per_page=6, page_size='640x360')` | film project store (sync — ffmpeg-only, NOT a pipeline job) | `POST /projects/{slug}/storyboard_pages` | render the shotplan's keyframes into labeled review grid pages (missing keyframes → placeholder cells); `per_page` 1..24, `page_size` WxH (64..2048 each) → `{pages: [abs page_NN.png], n_shots, n_pages, page_size, per_page}` |
| `media_project_approve(slug, what='storyboard', note?)` | film project store (sync) | `POST /projects/{slug}/approve` | the review/approve gate (idempotent; v1: `what='storyboard'` only, 400 otherwise) → `{slug, status, approval {storyboard: ISO, by, note}}` — **the anti-suck-atude gate (F2)** |
| `media_project_sync(slug)` | film project store (sync) | `POST /projects/{slug}/sync` | force the NAS mirror now → success `{ok: true, pending: false, files, local_files, dest}`; failure `{ok: false, pending: true, reason, files: 0}` (not an error — hourly retry) |
| `media_animatic(manifest, audio?, width=1280, height=720, fps=24)` | Tier-0 pacing gate (job, ffmpeg only — no GPU) | `POST /animatic` | `manifest` = `[{image, duration, move}]` (image = GPU-host/run-dir-relative path or staging file; `move` in `push_in`/`pull_out`/`pan_left`/`pan_right`/`shake`/`static`, default `static`; unknown → clean 400 at submit) → preview cut with zoompan moves + shot labels + optional audio (`-shortest`) → `{path, location, shots, duration_s, width, height, fps}` — **F3 step 2: user watch/review before any video diffusion** |
| `media_extract_frame(video, frame?/time?/positions?/n?)` | frame chaining + QC (job, ffmpeg only) | `POST /extract_frame` | **exactly one of** `frame` (int index) / `time` (s) / `positions` (list of `first`/`middle`/`last`) / `n` (int even-spacing) — else clean 400; last frame clamped 100 ms before the end → `{frames: [abs .png], count, location}` — **F3 step 4: last clean frame → next shot's `start` when `chain_from_prev_shot`** |
| `media_qc_montage(video, n=3, label=true)` | clip QC montage (job, ffmpeg only) | `POST /qc_montage` | n even-spaced frames (first/middle/last for n=3) → a SINGLE hstack PNG with index+timestamp labels — one image → one vision call; `n` 2..12 → `{path, location, frames, timestamps}` — **F6: 2–3 frames per clip post-I2V; F7: final cut at 6–8 points** |
| `media_montage(video, n=9, label=true, width=480, height=270)` | video → montage grid (job, ffmpeg only) | `POST /montage` | n even-spaced frames → grid PNG (`cols=ceil(sqrt(n)) × rows=ceil(n/cols)`; default 9 = 3×3; last row padded black); `n` 2..36 → `{path, location, frames, grid, timestamps}` |
| `media_lipsync(video, audio, face_box?, save_coord=false)` | MuseTalk v1.5 lip-sync (job, GPU 1) | `POST /lipsync` | `video` + `audio` (wav — must carry an audio stream; a TTS wav) → clip with the LOWER face re-animated to the audio (upper face untouched; source audio muxed in unchanged); `face_box` optional `[x1,y1,x2,y2]` pixel ints (absent = auto-detect; malformed → clean 400 at submit); `save_coord` → per-frame face boxes (pkl). Output duration ≈ audio length (keep the line shorter than the shot — F4). ~90 s for an 8 s clip → `{path, location, duration_s, width, height, audio_codecs, face_boxes?}` — **F8: post-render on `lip_sync_required` shots** |

## Film project store + films tools (2026-11-27, films handoff)

**The project store is a SYNC surface** — no `job_id`, no queue, no
`non_blocking`, no `user`/`client` (the pipeline's sync endpoints take plain
JSON). NAS-durable film projects on the GPU host:
`media_projects/<slug>/` (`project.json`, `shotplan.json`, `bible/`,
`storyboard/` + `pages/`, `production/` with an append-only `takes.json`),
mirrored **append-only** to the NAS after every mutation — a NAS failure
never fails a mutation (`nas_sync.pending` + hourly retry). Project files
live OUTSIDE the 14-day media_jobs sweep (the retention sweeper never
touches them). No DELETE endpoint (405) — projects persist until the 14-day
retention sweep.

**Films B2–B5 input path semantics** (`media_animatic` /
`media_extract_frame` / `media_qc_montage` / `media_montage` /
`media_lipsync`): absolute GPU-host paths and run-dir-relative paths
(`media_jobs/…`) **pass through** — the pipeline resolves them on the host,
so project files under `media_projects/` are accepted directly (no
`media_jobs` round-trip; an unresolvable host path is a clean 400/404).
LOCAL files must be under the staging dir (auto-uploaded via `/upload`).

**Takes (F5):** the project store's `takes.json` format is
`{shot_id: [{take, job_id, seed, prompt, model, path, active, created}]}` —
takes are never overwritten (the newest take is `active`); clips are copied
to `production/clips/<shot_id>_<take>.mp4`. The store's own auto-registration
(fired by `/shots` `project`/`shot_id` form fields) is **not exposed through
the MCP `media_generate_shot` tool** — the skill keeps the `takes` table in
the state file (R1) and syncs the durable mirror via
`media_project_asset(slug, "takes.json", <local file>)`.

**Bundled LUTs (B2 grade):** `cinematic_teal_amber`, `warm_neutral`,
`cool_noir` (33×33 .cubes under the pipeline's `luts/` — starting points,
not masters) — `media_assemble` `lut` accepts the name, a run-dir-relative
path, or an absolute path; `grain` 0.0–1.0 (subtle temporal film grain).

**Model notes (films):** FLF2V (`end_keyframe`) is **wan14b-only** (clean
400 with `ltxv2b`); 720p FLF2V admitted (B2 GPU QA). `media_lipsync` runs
on GPU 1 (dedicated musetalk worker container — MuseTalk v1.5, gate PASS
9079 MiB peak). The pipeline's `/health` `features` list carries
`projects`, `storyboard-pages`, `animatic`, `extract-frame`,
`assemble-grade`, `qc-montage`, `montage`, `lipsync` when all films batches
are live.

## Models

| Model | Flow | Specs | Speed |
|---|---|---|---|
| `wan14b` | I2V (default) | Wan 2.2 14B Q8_0 GGUF (promoted 2026-11-22 — was Q5_K_M), **832×480 (~10–12 min/clip) or 1280×720 (~55 min/clip at 81f — CPU offload)** (2026-11-22 Q8_0 720p peak 19,577 MiB on the 24 GB card), 81f (4n+1) recommended — 129f (~8 s clip) experimental: fits (13.5 GB delta) but quality degrades vs 81f (vision 2026-11-22), ~115 min/720p clip, 16fps, ~5 s clip | ~10–12 min (480p) / ~55 min (720p/81f) |
| `ltxv2b` | I2V (draft) | LTXV 2B, 768×512 default or **1280×720 for 720p-class drafts** (→ 1280×704 out — height snapped to ×32; 18 s/clip, peak 18,335 MiB, QA 2026-11-22), 97f, 25fps, ~4 s clip; `strength=0.7` anchors the keyframe | ~8 s/clip (512p) / ~18 s (720p) |
| `qwen21` | keyframes (default) | Qwen-Image-2.1, 25 steps, steps clamped [10,50] | ~30–120 s @1280×720 |
| `legacy` | keyframes (fast) | Qwen-Image-2512 GGUF + Lightning, steps=4 — Q4_0 default (20,513 MiB @720p); Q6_K staged 2026-11-22 (21,601 MiB, marginal upgrade — qwen21 still ranks best) | seconds |

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
  `media_upscale_video(pipeline="b")` per shot) — never raw 480p/720p.
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