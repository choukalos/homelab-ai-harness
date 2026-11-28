# mcp_media

MCP server for media operations via the **GPU-host media-pipeline**.

Thin HTTP client for the GPU-host `media-pipeline` service
(`MEDIA_PIPELINE_URL`, `http://192.168.4.55:8189` on Matrix). All GPU work
(ComfyUI + VLLM + TTS/music/SFX workers) happens on the GPU host; this
container only POSTs jobs, polls, and downloads results. Jobs block until
done (per-flow timeouts up to 2h; LiteLLM `timeout: 7200` set for this server).

## Tools

**Generation (GPU-host jobs):**

| Tool | Pipeline endpoint | Purpose |
|---|---|---|
| `media_storyboard` | `/storyboard` | Brief → shot list JSON (VLLM) |
| `media_generate_image` | `/images` | Text → keyframe image (Qwen-Image-2.1 default, 25 steps — best keyframe model, vision-verified 2026-11-22; `model`: `qwen21` \| `legacy` old Qwen-Image-2512 — Q4_0 default, Q6_K staged as a marginal upgrade) |
| `media_edit_image` | `/images/edit` | Image + text → edited image (unified Qwen-Image-2.1 editing; `model` + `references` up to 9 identity/consistency images for cross-shot consistency) |
| `media_generate_shot` | `/shots` | Keyframe → I2V clip (upload). `model`: `wan14b` (quality, Wan 2.2 14B Q8_0 GGUF — promoted 2026-11-22, was Q5_K_M, ~5s clip at 81f, 832×480 ~10–12 min or 1280×720 ~55 min (CPU offload); frames 4k+1 — 81f recommended, 129f (~8s clip) experimental: quality degrades, ~115 min/720p clip) \| `ltxv2b` (fast draft, LTXV 2B, ~4s clip, 768×512 ~8s or 1280×720 ~18s → 1280×704 out); omitted = server default (wan14b as of 2026-10-31). Dims/frames/fps omitted = model-native defaults. `strength` is ltxv2b-only (ignored for wan14b). **Films B2 (2026-11-27): `end_keyframe`** — optional SECOND keyframe (same local/GPU-host path semantics) → first-last-frame **FLF2V**: the clip interpolates from `keyframe` (start pose) to `end_keyframe` (exact end-pose control; 720p admitted). wan14b-only — a clean 400 with `ltxv2b`; metered like a wan14b shot |
| `media_text_to_speech` | `/tts` | Script → voice-over wav (`voice` = library name — `trailer` default, `default`, `narrator_f`, `deep_m`, ... — or a reference wav path on the GPU host) |
| `media_list_voices` | `/voices` (sync) | TTS voice library: name, description, gender, style, audition sample path |
| `media_add_voice` | `/voices` (job) | Register a voice from a 3–15 s reference wav (QC'd, normalized 16 kHz mono, audition sample generated on the GPU) |
| `media_delete_voice` | `/voices/{name}` (sync) | Remove a voice (ref + sample + manifest entry); `trailer`/`default` protected |
| `media_generate_music` | `/music` | Prompt(+lyrics) → song/instrumental wav (ACE-Step) |
| `media_transcribe_song` | `/transcribe` (job) | Song → **guitar tab + timestamped lyrics** (deterministic DSP + ASR + LLM polish; `source` = YouTube URL / http(s) URL / GPU-host path / staging file; v1 `instrument="guitar"`, `tuning="standard"` only; `stems` default true = demucs vocal stem for cleaner lyrics; `full_notes` = full note events; `whisper_model` override). **Chord/key/fingering surface** (deterministic post-processing, 2026-10-31 — the LLM never touches it): `transpose_semitones` (−12..12) / `target_key` (tonic like `E`/`Bb`/`F#m`, offset from the detected key, wins over transpose) re-render tab + MIDI in the new key; `chord_style` = `as_detected` (default) / `triads` / `power` (root+5th, metal-friendly); `capo=true` suggests the smallest capo (0–5) when the key has no open shapes (chords shown as finger shapes); `shape_hints` (default true) annotates every chord with its easiest fingering (open / E- or A-shape barre / power) |
| `media_sfx` | `/sfx` | Video → synced SFX bed (MMAudio, upload) |
| `media_upscale_video` | `/upscale` | Video → 1080p (`b`=SeedVR2 quality, `a2`=fast, upload) |
| `media_assemble` | `/assemble` | Concat shots + mix VO/music/SFX → final mp4 (M4: object shots `{path, in?, out?, duration?}`, timestamped `sfx: [{path, at}]`, `vo_start`, `loudnorm`; **M1 (2026-11-19): `duration` on an object shot is enforced — frame-hold (last frame) or trim to the requested length, ±0.1 s tolerance = no-op, applied after in/out and before upscale_each; every adjustment reported in the job's `duration_adjustments`**; quality: `upscale_each` SeedVR2 per-shot → true 1080p, `text_overlays` burned-in titles — string forms still work; **Films B2 (2026-11-27): grade — `lut` (.cube 3D LUT on the final concat in the same re-encode pass: bundled name `cinematic_teal_amber` / `warm_neutral` / `cool_noir`, a run-dir-relative path, or an absolute path; unresolvable → clean 400 at submit) + `grain` (0.0–1.0 subtle temporal film grain; out of range → clean 400); both absent = no grade**) |
| `media_animatic` | `/animatic` (job) | **Tier-0 pacing gate** (Films B2, 2026-11-27 — ffmpeg only, no GPU): `manifest` = storyboard keyframes as `[{image, duration, move}]` → preview cut with simulated zoompan camera moves + shot labels + optional `audio` (muxed `-shortest`), so a whole scene can be watched in ~20 s before burning video-diffusion time. `image`/`audio` = absolute GPU-host path or run-dir-relative path (project keyframes under `media_projects/` pass through) OR a local staging file (auto-uploaded); `duration` default 2.0 s; `move` in `push_in`/`pull_out`/`pan_left`/`pan_right`/`shake`/`static` (default `static`; unknown → clean 400 at submit). `width`/`height`/`fps` default 1280×720@24. Returns `{path, location, shots, duration_s, width, height, fps}` |
| `media_extract_frame` | `/extract_frame` (job) | Extract frame(s) from a video (Films B2 — ffmpeg only) for frame-chaining (last clean frame → the next shot's start keyframe) + QC. `video` = GPU-host/run-dir-relative path OR local staging file (auto-uploaded). **EXACTLY ONE of** `frame` (int index, 0-based) / `time` (s) / `positions` (list of `first`/`middle`/`last`) / `n` (int → n frames evenly spaced) — else a clean 400 at submit. Last frame clamped 100 ms before the end. Returns `{frames: [abs .png], count, location}` |
| `media_qc_montage` | `/qc_montage` (job) | Clip QC montage (Films B3 — ffmpeg only): n even-spaced frames (first/middle/last for n=3) → a **SINGLE hstack PNG** with index+timestamp labels — one image → one vision call (the QC pattern: vision-check 2–3 frames per clip post-I2V; spatial/anatomy fail → re-seed ≤3× then flag to user). `n` 2..12 (default 3); `label` default true. Returns `{path, location, frames, timestamps}` |
| `media_montage` | `/montage` (job) | Generic video → montage **grid** (Films B5 — ffmpeg only): n even-spaced frames (inclusive ends; last clamped 100 ms before the end) → grid PNG of `cols=ceil(sqrt(n)) × rows=ceil(n/cols)` cells (default 9 = 3×3; last row padded with black cells), each cell scaled to `width`×`height` (default 480×270) with an optional index+timestamp label. `n` 2..36 (default 9); `label` default true. Returns `{path, location, frames, grid, timestamps}` |
| `media_lipsync` | `/lipsync` (job) | **MuseTalk v1.5 lip-sync** (Films B4 — GPU 1, dedicated musetalk worker): `video` + `audio` (wav — must carry an audio stream; a TTS wav from `media_text_to_speech`) → clip with the **LOWER face** re-animated to the audio (upper face untouched; the source audio is muxed in unchanged). Use post-render on `lip_sync_required` shots (dialogue motion prompts keep mouths closed). `face_box` optional `[x1,y1,x2,y2]` pixel ints (absent = auto-detect; malformed → clean 400 at submit); `save_coord=true` also returns the per-frame face boxes (pkl). Output duration ≈ audio length — keep the line shorter than the shot. ~90 s for an 8 s clip. Returns `{path, location, duration_s, width, height, audio_codecs, face_boxes?}` |
| `media_fetch` | `/files/{name}` | Download a pipeline result to the local media library |
| `media_render_tab_pdf` | local (WeasyPrint) | Transcribe job → **styled PDF song sheet** (deterministic — no LLM; `tab_pdf.py` renders the job's `tab.md` verbatim with Playfair Display / Inter / JetBrains Mono). **Layout (2026-11-01 part 5): CHORDS — a grid of fixed-size chord fingering diagrams (name + shape + starting-fret annotation; power/barre shapes generated from the pipeline's `shape` hint, open chords from a standard-shape library); then SCORE — a measure-aligned score per section so you can sing & play at once (with a friend): VOCALS lane (word-timed lyrics with a mini chord diagram above the measure where each change lands, from ASR word timestamps + chord event times), RHYTHM lane (chord diagrams, instrumental sections), SOLO lane (per-measure fretboard boards — same visual language as the CHORDS diagrams: dot size + duration tail = hold time, number = play order, h/p = hammer-on/pull-off, arrow = slide, wave = hold/vibrato; decoded by the SOLO KEY panel at the top of the SCORE part; over-dense measures fall back to the compact 6-line text tab; 2026-11-06 Phase 3).** Fetches `tab.md` / `lyrics.txt` / `analysis.json` from the GPU host, renders locally to `MEDIA_PIPELINE_FETCH_DIR/<slug>/<slug>-tab.pdf`. `title`/`artist` override the LLM-guessed header (pass the real identity); `slug` names the output dir (default: job_id); `solo_style` = 'board' (default) or 'text' (legacy compact tab). Returns `{local_path, size_bytes, pages, title, artist, sections, missing_shapes, synthesized_shapes, solo_style, solo_fallbacks}` (shape-coverage warnings + solo-lane reporting, 2026-11-06). Publish with the `publish_file` skill (subdirectory `tabs`) for a public URL |
| `media_job_result` | `GET /jobs/{id}` (long-poll) | Poll a submitted job to its final result (≤25 s per poll — kept under the ~30 s client tool-call timeout). Returns the final result (same shape as the blocking tool) or `{status: 'running'}` to poll again (with `progress: {stage, completed, total, label}` while an assemble is in flight — M5, 2026-11-19) |
| `media_list_jobs` | `GET /jobs` (sync) | List jobs from the durable ledger (filters: `status`/`client`/`user`/`flow`/`since`/`limit`; newest-first) — the recovery path for lost `job_id`s; finished jobs survive pipeline restarts (2026-11-04). Status taxonomy: `queued|running|done|error|timeout|killed` |
| `media_kill_job` | `DELETE /jobs/{id}` (sync) | Kill a **queued** job — frees its FIFO slot so the next queued job starts (M2, 2026-11-19). Running → refused (409, GPU work is never killed); terminal → idempotent no-op. Optional `client` tag scope (mismatch → 403). Returns `{job_id, killed, status, queue_position_freed?}` |
| `media_queue_status` | `GET /health` (sync) | Queue summary (M3, 2026-11-19): `{ok, pending, running, queued, max_concurrent, max_queue_depth, queue: {counts, queued_jobs (FIFO: job_id/flow/client/created/waited_s), oldest_queued}, features}` — check before submitting (full queue → 503) and to estimate wait |

**Film project store (Films B1, 2026-11-27 — `thor_films_handoff_nov27.md`):** NAS-durable film projects on the GPU host — a **sync** surface (no `job_id`, no queue, no `non_blocking`): the durable source of truth for film pre-production (assets, two-tier shotplan, storyboard pages, approval state), mirrored **append-only** to the NAS after every mutation (a NAS failure never fails a mutation — `nas_sync.pending` + hourly retry). Slugs: `^[a-z0-9_]{1,64}$` (400 otherwise; 409 if it exists). Project files live under `media_projects/<slug>/` on the GPU host (OUTSIDE the 14-day media_jobs sweep — the retention sweeper never touches them).

| Tool | Pipeline endpoint | Purpose |
|---|---|---|
| `media_project_create(slug, title?)` | `POST /projects` (sync) | Create a film project (the project-bible dir + `project.json`) → `{slug, project (abs dir), status: 'draft', nas_sync}`. Start every film here — the store survives session resets |
| `media_project_list()` | `GET /projects` (sync) | List projects → `{projects: [{slug, title, status, updated, nas_pending}], root, nas_root}` — the slug-recovery path after a session reset |
| `media_project_get(slug)` | `GET /projects/{slug}` (sync) | Full project state (404 unknown): `{slug, title, status ('draft' → 'storyboard_approved'), created, updated, approval {storyboard: ISO\|null, by, note}, nas_sync {last, ok, pending, files, reason?}, assets {path: {size, added}}, tree {bible, storyboard, production} (file counts), takes}`. **Project-first**: start every film workflow here; check `approval.storyboard` before spending on I2V (the approve gate) and `nas_sync.pending` before publishing |
| `media_project_asset(slug, path, file)` | `POST /projects/{slug}/assets` (sync) | Register an asset (char sheet / env plate / keyframe / voice ref / script): `path` = project-relative destination (e.g. `bible/characters/hero/turnaround.png`, `storyboard/script.md`; 400 on `..`/absolute); `file` = a local staging file OR a GPU-host `media_jobs` path (auto-fetched first — generate keyframes with `media_generate_image`, fetch with `media_fetch`, register here) → `{path (abs), size, location}` |
| `media_project_shotplan(slug, shotplan?)` | `POST`/`GET /projects/{slug}/shotplan` (sync) | Get or save the two-tier shotplan (Scene → Beats → Micro-shots) — **pure pass-through**: `shotplan` omitted → GET the saved doc (404 when none saved) + server-managed `saved` + `schema_warnings` (non-fatal, e.g. motion verbs in a `keyframe_prompt`); given → POST/replace. The pipeline validates server-side (enums, `duration_frames` 4k+1 ≤129, `action_impact` ≤49f, unique `shot_id`, `end_keyframe_prompt` when `use_end_frame_anchor`) — 400s carry the exact field errors (`detail: 'shotplan validation failed: <field> …'`) and are surfaced verbatim. Save → `{shotplan (abs path), warnings}` |
| `media_project_storyboard_pages(slug, per_page=6, page_size='640x360')` | `POST /projects/{slug}/storyboard_pages` (sync — **ffmpeg-only, NOT a pipeline job** — returns directly) | Render the shotplan's keyframes into labeled review grid pages (missing keyframes → placeholder cells). `per_page` 1..24 (default 6); `page_size` WxH (64..2048 each; default `640x360`); 400 on bad params or a missing shotplan → `{pages: [abs page_NN.png], n_shots, n_pages, page_size, per_page}` — `media_fetch` the pages for the human review loop (present → accept/revise → regenerate only changed keyframes → re-render) |
| `media_project_approve(slug, what='storyboard', note?)` | `POST /projects/{slug}/approve` (sync) | The review/**APPROVE GATE** (idempotent; v1: `what='storyboard'` only, 400 on anything else) → `{slug, status, approval {storyboard: ISO, by, note}}`. **HARD RULE: no I2V/draft spend before this lands** (anti-suck-atude gate — potato-wars incident). Call it after the user explicitly accepts the storyboard pages, then `media_project_sync` (the NAS copy is permanent) |
| `media_project_sync(slug)` | `POST /projects/{slug}/sync` (sync) | Force the NAS mirror now (the CIFS mount probe always runs). Success: `{ok: true, pending: false, files, local_files, dest}`; failure: `{ok: false, pending: true, reason, files: 0}` — **not an error** (the project is intact on the GPU host; hourly retry). Use after `media_project_approve` and before publishing |

No DELETE endpoint (`DELETE /projects/{slug}` → 405) — projects persist until the 14-day retention sweep.

**Films handoff status** (`thor_films_handoff_nov27.md`, 2026-11-27): the handoff's
"BLOCKED on matrix" header is **stale** — all matrix batches B1–B5 are live
(pipeline `/health` `features`: `projects`, `storyboard-pages`, `animatic`,
`extract-frame`, `assemble-grade`, `qc-montage`, `montage`, `lipsync`; the
films plan `media-pipeline/films_plan_matrix.md` is CLOSED — B1 QA 35/35, B2
24/24 CPU + FLF2V GPU, B3 19/19, B4 gate PASS 9079 MiB + QA 23/23, B5 22/22,
final regression 26/26). **§1 mcp_media: ALL films-§1 tools implemented
2026-11-28** (B1 ×8 sync project-store tools, B2 `media_generate_shot`
`end_keyframe` + `media_animatic` + `media_extract_frame` + `media_assemble`
`lut`/`grain`, B3 `media_qc_montage`, B5 `media_montage`, B4 `media_lipsync` —
see the tables above + the 2026-11-28 history entry). §2 skills (thor
gateway): `media-storyboard` (new — interactive pre-production with the
approve gate) + `media-film` (upgrade — project-first production) — see
`agents-skills/media-storyboard/` + `agents-skills/media-film/`.

**Submit-and-poll (2026-09-25):** every job tool above accepts
`non_blocking: bool = False`. With `non_blocking=true` the tool returns
`{job_id, status: "running"}` in ~1 s instead of blocking until the job
finishes; then poll `media_job_result(job_id, wait_seconds=20)` until
`status` is `done`/`error`. Default (`false`) keeps the original blocking
behavior (skill-runner / direct SSE callers unchanged). Why: pi's
`pi-provider-litellm` aborts tool calls at a hardcoded 30 s while the job
keeps running server-side — submit-and-poll keeps every tool call under the
abort window without touching litellm/pi.

**Job recovery + client tags (2026-11-04, thor handoff T1–T4):**

- **`media_list_jobs`** (new) — lists jobs from the pipeline's **durable
  ledger** (`GET /jobs`): `status` (`queued`|`running`|`done`|`error`|
  `timeout`|`killed`, default `running`; comma-separated for multiple),
  `client`, `user`, `flow`, `since` (ISO timestamp or epoch seconds),
  `limit` (default 50, max 200) → `{count, jobs: [{job_id, flow, status,
  client, user, created, done, model, duration_s, cost_usd, error, output,
  outputs}]}` newest-
  first. **Finished jobs
  survive pipeline restarts** (the `jobs.jsonl` ledger), and live in-flight
  jobs are included — this is the recovery path when a `job_id` is lost to
  a session reset, a timeout, or a crashed client. Find the `job_id`, then
  `media_job_result(job_id)` for the result or `media_fetch(host_path)` for
  the artifact. `media_job_result` on an unknown/evicted id returns a clean
  error pointing here.
- **`client` tag on every job tool** (new, optional, default `MEDIA_CLIENT`
  = `pi`) — forwarded to the pipeline and recorded on the job. Use a stable
  per-project tag (e.g. `client="my-project/shot3"`) so
  `media_list_jobs(client="my-project")` finds all of a project's jobs even
  after a restart. The tag is also logged (below).
- **Container-log recovery (T1)** — `mcp_media` logs one line per submit
  and one per terminal result, so `docker logs ai-mcp-mcp-mcp_media` is a
  recovery path even before `media_list_jobs` is queried:
  `SUBMIT kind=<tool> tag=<client> job_id=<id>` and
  `DONE job_id=<id> status=<done|error|timeout> path=<path|->`.
- **MCP gateway timeout + retry (T3)** — the MCP gateway has a **60 s hard
  timeout**. Long orchestrations can legitimately exceed it; a transient
  `MCP request timed out` is **expected** and the job is **unaffected**
  (it keeps running on the GPU host). **Retry the call** (the job is
  idempotent-safe to re-poll); wrap all calls in retry logic (≥3 attempts).
  Submits return `503` + `retry_after_seconds` when the queue is full
  (1 running + 5 queued) — **stop submitting and poll** instead of
  retrying the submit. This text is also embedded in every job tool's
  description + `media_job_result` + `media_list_jobs` so clients see it in
  the tool schema.
- **`media_fetch` collision-safety (T4)** — on a basename collision in
  `MEDIA_PIPELINE_FETCH_DIR` the file is saved under a suffixed name
  (`vo.wav` → `vo_2.wav`, `vo_3.wav`, …); **existing files are never
  overwritten**. The tool returns `renamed: true` + a `note` when this
  happens, and logs a `FETCH` line with the local path.

**Queue control (2026-11-19, pipeline M1–M5 — `media_pipeline_m1_m5_handoff.md`):**

- **`media_kill_job(job_id, client?)`** (new) — `DELETE /jobs/{id}` (M2):
  kills a **queued** job and frees its FIFO slot (the next queued job
  starts). Running jobs are refused (409 — GPU work is never killed
  mid-flight); terminal jobs (`done`/`error`/`timeout`/`killed`) are an
  idempotent 200 no-op. Optional `client` tag scope: if the job has a tag
  and it doesn't match, 403 (pass the tag you submitted with; omit for
  untagged jobs). Returns `{job_id, killed, status}` + `queue_position_freed`
  on a real kill. Killed jobs get a durable ledger row (`status=killed` —
  findable via `media_list_jobs(status="killed")` after a restart). Logs a
  `KILL job_id=... client=... -> killed=... status=...` line.
- **`media_queue_status()`** (new) — `GET /health` (M3): the queue summary —
  `{ok, pending, running, queued, max_concurrent, max_queue_depth, queue:
  {counts: {running, queued}, queued_jobs: [{job_id, flow, client, created,
  waited_s}] (FIFO, oldest first), oldest_queued}, features}`. Check it
  before submitting (full queue → 503 + `retry_after_seconds`) and to
  estimate wait (`oldest_queued.waited_s` + per-flow wall-clocks). The
  `features` list (`["assemble-duration-hold", "job-kill", "queue-summary",
  "job-progress"]`) is the pipeline's feature-detection surface. Logs a
  `QUEUE_STATUS ok=... pending=... running=N queued=N` line.
- **`media_assemble` `shots[].duration` is enforced (M1)** — the C14 root
  cause is fixed: an object shot's `duration` now frame-holds (last frame,
  `tpad stop_mode=clone`) or trims the clip to the requested length (±0.1 s
  tolerance = no-op), applied after `in`/`out` and **before** `upscale_each`.
  Every adjustment is reported in the job's `duration_adjustments`
  (`[{shot, natural_s, requested_s, applied: hold|trim|none, held_s?/trimmed_s?}]`)
  — visible via `media_list_jobs` `output`. Film plans can now pass the
  planned per-shot durations instead of re-planning from measured lengths.
- **`media_job_result` in-flight progress (M5)** — while an assemble job is
  running, the poll response carries `progress: {stage, completed, total,
  label}` (per-shot stage counts); terminal progress is in the job result
  and ledger row.

**Post-gen edit + file movement (2026-09-07, media_pipeline_gaps.md M1–M8):**

| Tool | Pipeline endpoint | Purpose |
|---|---|---|
| `media_trim` | `/trim` (job) | Cut a clip to a time range — ffmpeg, always re-encodes (libx264 crf 18). Exactly one of `end`/`duration`; optional `fps`/`width`/`height`. Local files auto-uploaded |
| `media_freeze` | `/freeze` (job) | Image/video-frame → pixel-static N-s clip (ffmpeg — NO generative model, so faces/text don't warp). `frame` = frame index for video sources |
| `media_caption` | `/caption` (job) | Burn text into a clip (ffmpeg drawtext, textfile-based; multiline OK). No `background_bar` (not in the verified contract) |
| `media_info` | `/info` (sync) | ffprobe metadata: `{duration_s, width, height, fps, video_codec, audio_codecs[], size_bytes, bitrate_bps}` |
| `media_upload` | `/upload_local` (sync) | Copy a file from the MATRIX host into media_jobs — source MUST be under the ComfyUI basedir (400 otherwise) |
| `media_download` | `/download` (sync) | Fetch a URL into media_jobs on the GPU host |
| `media_put` | `/upload` (sync) | Push a **thor-local staging file** to `media_jobs/uploads/` (multipart, 500MB cap). GPU-host paths pass through unchanged |
| `media_pull` | `/dl_token` (sync) | Mint a **signed public URL** for a media_jobs path or job_id → `https://siri.choukalos.com/media/pipeline/dl/<token>` (TTL 1–168h, default 24). Optional `local_dir` also copies it to the local media library (LAN fetch) |

**TTS voice library (2026-09-25, matrix pipeline update):**

| Tool | Pipeline endpoint | Purpose |
|---|---|---|
| `media_list_voices` | `GET /voices` (sync) | Voice portfolio: `trailer` (deep male, **default**, protected), `default` (stock male XTTS, protected), `deep_m` (warm deep male clone), `narrator_f` (female narrator clone, F0 ~212 Hz) + anything registered via `media_add_voice` |
| `media_add_voice` | `POST /voices` (job) | Register a voice from a 3–15 s reference wav on the GPU host (stage with `media_put`/`media_download` first → `media_jobs/uploads/`). Re-registering a name replaces it; protected names → 400. Returns `{voice, ref, sample, ref_duration_s}` |
| `media_delete_voice` | `DELETE /voices/{name}` (sync) | Remove a voice (ref + sample + manifest entry). `trailer`/`default` protected (400); unknown → 404 |

`/tts` `voice` semantics (server-side resolution): `trailer`/`default` → legacy
`--voice` pass-through; a library name → `--reference-audio <resolved ref>`;
a path (contains `/` or ends `.wav`) → `--reference-audio <path>` (previously
documented but broken — now working); anything else → 400 with the available
list. Voice files live under
`/home/chuck/data/comfyui/basedir/models/tts/voices/` on the GPU host (outside
the 14-day media_jobs sweep — registered voices are permanent until deleted).

**Path model** (Thor has no shared filesystem with the GPU host):
- Pipeline tools return **GPU-host paths** — required so `media_assemble`
  (JSON, host paths only) can chain on the host.
- `media_fetch` downloads any result to `MEDIA_PIPELINE_FETCH_DIR`
  (default `/home/chuck/data/media/generated/pipeline`) and returns the local path.
- Input tools that take local files (`media_edit_image`, `media_generate_shot`,
  `media_sfx`, `media_upscale_video`) **auto-fetch** GPU-host paths to a temp
  dir before uploading — flows chain without manual fetch steps.
- `media_put` (and local sources for `media_trim`/`media_freeze`/`media_caption`)
  read **thor-local files from the staging dir** `MEDIA_STAGING_DIR`
  (default `/home/chuck/workspace/media`, rw-mounted) and auto-upload them.
  Local files outside staging are rejected with a clear error (the staging
  mount is the only thor-local input root this container can read).
  Staging is scratch space — cleaned by `scripts/cleanup-media-staging.sh`
  (`MEDIA_STAGING_MAX_AGE_DAYS` in `.env`, default 7d; manual, no cron).
- **Films B2–B5 inputs** (`media_animatic` / `media_extract_frame` /
  `media_qc_montage` / `media_montage` / `media_lipsync`): absolute GPU-host
  paths and run-dir-relative paths (`media_jobs/…`) **pass through** — the
  pipeline resolves them on the host, so project files under `media_projects/`
  (OUTSIDE `media_jobs/`) are accepted directly, no `media_jobs` round-trip
  needed (an unresolvable host path is a clean 400/404 from the pipeline).
  LOCAL files must be under the staging dir (auto-uploaded via `/upload`).
- `media_pull` is the **off-LAN retrieval path**: the signed URL is usable
  from anywhere (token IS the credential; Range requests supported) — no
  homelab access, no website publishing. Off-LAN clients that can't stage a
  file here can still push via the raw public route
  `https://siri.choukalos.com/media/pipeline/upload` (`X-Api-Key`).
- Queue back-pressure: the GPU host runs 1 concurrent job + 5 queued; when
  full, tools return `{"error": "...503...", "retry_after_seconds": N}`.

Typical commercial flow: `media_storyboard` → per shot
`media_generate_image` + `media_generate_shot` → `media_text_to_speech` +
`media_generate_music` → `media_upscale_video(pipeline="b")` →
`media_assemble` → `media_fetch` the final mp4.

**Multi-shot film orchestration:** for crash-proof multi-shot runs
(keyframes → I2V → audio → assembly → QC → publish) use the `media-film`
pi skill (`agents-skills/media-film/SKILL.md`) — on-disk state file written
after every submit, retried MCP calls, timeboxed chunks, and a resume
protocol built on `media_list_jobs`. For film projects, start at the
`media-storyboard` skill (`agents-skills/media-storyboard/SKILL.md`) —
interactive pre-production on the project store with the approve gate
(**no I2V/draft spend before `media_project_approve` lands**); `media-film`
picks up from the approved project store (`media_project_get` first).

## Config

| Env | Default | Meaning |
|---|---|---|
| `MEDIA_PIPELINE_URL` | `http://127.0.0.1:8189` | GPU-host pipeline base URL |
| `MEDIA_PIPELINE_FETCH_DIR` | `/home/chuck/data/media/generated/pipeline` | `media_fetch` download dir |
| `MEDIA_STAGING_DIR` | `/home/chuck/workspace/media` | Local-file input root for `media_put` / trim / freeze / caption (rw-mounted; scratch, cleaned by `scripts/cleanup-media-staging.sh`) |
| `MEDIA_PUBLIC_URL` | `https://siri.choukalos.com/media/pipeline` | Public base for `media_pull` signed URLs (Caddy route → matrix `:8189`) |
| `LITELLM_PROXY_URL` | `http://litellm-proxy:4000` | Proxy used to resolve caller key → user |
| `MEDIA_USER` | `unknown` | Fallback user when no Authorization header (Thor: `chuck`) |
| `MEDIA_CLIENT` | `pi` | Calling-app label stamped on jobs |

Transport: SSE on `0.0.0.0:8000` (`/sse`).

## Public route (2026-09-07)

`media_pull` URLs are served by the Caddy public route
(`caddy/Caddyfile`, `@siri_pipeline`) — option C: under
`siri.choukalos.com`, no new Cloudflare DNS record. The route proxies to
matrix `:8189` and exposes exactly two paths:

| Public path | Auth | Proxied to |
|---|---|---|
| `GET /media/pipeline/dl/<token>` | none (token IS the credential) | `GET /dl/<token>` |
| `POST /media/pipeline/upload` | `X-Api-Key` (chuck/dylan LiteLLM key) | `POST /upload` |

Everything else under `/media/pipeline/*` → 404. In particular
`/dl_token` (token minting) and the rest of the pipeline API stay
**LAN-only**. Cloudflare cache rule for `/media/pipeline/dl/*` is in place
(2026-09-07, dashboard): the edge does not cache (`cf-cache-status:
DYNAMIC` — bypass); downloads are served from origin. See
`docs/thor_manual_tasks.md` Phase 15.

## Identity threading (per-user cost attribution)

Every job POST (except `media_fetch`, which downloads only) is stamped with
`user` + `client` so the GPU-host pipeline can attribute work and cost per
user (metered in the pipeline's `/metrics` + `jobs.jsonl`):

1. When the call routes through LiteLLM (pi → `/mcp-rest/tools/call` →
   mcp_media), the caller's LiteLLM API key is forwarded in the
   `Authorization` header (same pattern as `mcp_memory`).
2. `server.py` resolves key → user via `GET {LITELLM_PROXY_URL}/key/info`
   (`info.user_id`), cached in-process; falls back to `MEDIA_USER` on any
   failure (a job is never blocked by identity resolution).
3. JSON endpoints carry `user`/`client` in the body; multipart endpoints
   (`/images/edit`, `/shots`, `/sfx`) carry them as form fields.

Verified end-to-end 2026-09-09: pipeline job payloads on Matrix now show
`"user": "chuck", "client": "pi"` (e.g. `GET /jobs/{id}` → `payload.user`).

## History

2026-11-28: **Films B1–B5 mcp_media tools** (`thor_films_handoff_nov27.md` —
all matrix batches live; the handoff's "BLOCKED on matrix" header is stale —
the films plan `media-pipeline/films_plan_matrix.md` is CLOSED: B1 QA 35/35,
B2 24/24 CPU + FLF2V GPU, B3 19/19, B4 gate PASS 9079 MiB + QA 23/23, B5
22/22, final regression 26/26; contracts per the live pipeline + the shipped
`media-pipeline/projects.py` validation):
- **B1 — film project store (8 new SYNC tools)**: `media_project_create` /
  `media_project_list` / `media_project_get` / `media_project_asset` /
  `media_project_shotplan` / `media_project_storyboard_pages` /
  `media_project_approve` / `media_project_sync` — the NAS-durable project
  store over the `/projects*` endpoints (sync — no `job_id`/queue/`non_blocking`;
  no `user`/`client` — the pipeline's sync endpoints take plain JSON): assets
  (multipart, project-relative `path`), the two-tier shotplan (pure
  pass-through — server-side validation 400s surfaced verbatim), storyboard
  grid pages (sync ffmpeg — NOT a pipeline job), the approve gate (v1
  `what='storyboard'` only, idempotent), and the forced NAS mirror (a NAS
  failure never fails a mutation). Client: `project_create/list/get/asset/
  shotplan/storyboard_pages/approve/sync` + the sync HTTP helpers
  (`_get_json` / `_post_json_sync`).
- **B2 — `media_generate_shot` `end_keyframe`** (optional second keyframe →
  FLF2V; wan14b-only — clean 400 with `ltxv2b`; 720p admitted): the client
  gained `_post_multipart_files` (multi-file multipart — `file` +
  `end_keyframe`). **`media_animatic`** (Tier-0 pacing gate — storyboard
  keyframes → preview cut with zoompan moves + labels + optional audio;
  manifest `[{image, duration, move}]`). **`media_extract_frame`**
  (frame-chaining + QC — exactly one of `frame`/`time`/`positions`/`n`).
  **`media_assemble` `lut`/`grain`** (3D LUT grade + temporal film grain on
  the final concat; bundled LUT names `cinematic_teal_amber` /
  `warm_neutral` / `cool_noir` or a .cube path; `grain` 0.0–1.0; clean 400s
  at submit).
- **B3 `media_qc_montage`** (n even-spaced frames → one labeled hstack PNG;
  n 2..12, default 3), **B5 `media_montage`** (n → grid PNG; n 2..36,
  default 9 = 3×3), **B4 `media_lipsync`** (MuseTalk v1.5 — lower face
  re-animated to the audio; `face_box` optional `[x1,y1,x2,y2]` pixel ints;
  `save_coord`; output duration ≈ audio length).
- **Conventions**: the five new job tools follow the existing job-tool
  contract — `non_blocking` + `media_job_result` polling (`finalize_job`
  carry-through now passes the sibling metadata — `frames` / `timestamps` /
  `grid` / `count` / `shots` / `duration_s` — through to the poll result),
  `user`/`client` identity, `{path, location}` results, 503/60 s notes.
  Inputs (new `_resolve_input`): absolute GPU-host paths + run-dir-relative
  paths pass through (project files under `media_projects/` resolve on the
  host); local files must be under the staging dir (auto-uploaded). Client-
  side pre-validation (slugs, exactly-one selectors, n ranges, face_box
  shape, manifest shape, grain range) gives clean errors before the
  round-trip; the pipeline re-validates as a backstop.
- Verified (in-container, live pipeline untouched): import + FastMCP
  registration (40 tools — all 13 new + `end_keyframe` on
  `media_generate_shot` + `lut`/`grain` on `media_assemble`; param schemas
  checked) + validation unit tests (slug/path/selector/n-range/face_box/
  manifest/grain error paths, `_resolve_input` pass-throughs, `finalize_job`
  carry-through). Live rebuild/restart + per-tool smokes: the long-task
  deploy step (see the films long-task report).

2026-11-22: **Phase 7 media QoL — LTXV 720p drafts promoted, wan14b 129f
experimental, Qwen-Image-2512 Q6_K staged** (matrix add_card_plan Phase 7 —
`phase7_qol_todo.md`; all three §4.3 QoL items QA'd on the 24 GB GPU 1 with
vision-subagent compares). **(1) `ltxv2b` at 1280×720 promoted**: any dims
were already API-legal; measured 18 s/clip, peak 18,335 MiB (fits); output
1280×704 (LTXV snaps height to ×32); vision: sharper than the 768×512 draft,
no new artifacts → documented as a supported 720p-class draft option (768×512
stays the default). **(2) wan14b 129f (~8.1 s) rejected as recommended,
documented as experimental**: 129f is 4k+1-legal (no cap added); QA
(`qa_wan_phase1.py 720 WAN_QA_LENGTH=129`, Q8_0): 115.1 min, peak 14,720 MiB
/ 13,457 delta — *lower* than the 81f 19,577 (ComfyUI offloads more on the
longer latent); vision compare vs the 81f baseline (same keyframe/prompt/seed,
2 montage frames): quality degrades (softer detail, texture noise, dark-bg
banding) → 81f stays the recommended max. **(3) Qwen-Image-2512 Q6_K staged**:
17.95 GB GGUF (unsloth) on the host; `QWEN_IMAGE_2512_MODEL` env override
(defaults = shipped Q4_0 pair). 3-way keyframe QA @1280×720 (same
prompt/seed): qwen21 48 s / 16,929 MiB, 2512-Q4 28 s / 20,513, 2512-Q6 22 s /
21,601 — all fit; vision ranking **qwen21 > Q6_K > Q4_0** → qwen21 stays the
production keyframe default (`MEDIA_IMAGE_MODEL` unchanged); Q6_K is a
marginal legacy upgrade via the env. Tool descriptions + media-film contract
updated to match.

2026-11-22: **wan14b quant promoted: Q5_K_M → Q8_0** (matrix add_card_plan
Phase 6 quant decision — `phase6_quant_todo.md`). All three 720p candidates
passed the VRAM gate (Q6_K 19,769 MiB / Q8_0 19,577 MiB / FP8 17,579 MiB +
fastest at 43.9 min); vision-subagent quality compare vs the Q5_K_M baseline
had Q8_0 best (sharper face/fur, cleaner edges, no artifacts), Q6_K close
behind, FP8 mixed (dark-bg banding) → Q8_0 promoted on quality. Pipeline-side:
`WAN_HIGHNOISE_MODEL`/`WAN_LOWNOISE_MODEL` = Q8_0 GGUF pair +
`WAN_METERING_LABEL=wan2.2-14b-i2v-gguf-q8` in `compose/comfyui.yml` (env-only,
`media_pipeline` recreated). No API/param change — `media_generate_shot` is
unchanged; only the client docstring + tool-table row note the new quant.
Loser models (Q6_K/FP8) deleted post-decision; Q5_K_M kept as fallback.

2026-11-21: **wan14b 720p cap lifted** (matrix add_card_plan Phase 6 — the
720p VRAM gate passed on the dedicated 24 GB GPU 1 card: peak 19,641 MiB,
4.8 GB headroom, `qa_wan_phase1.py 720 --gpu 1`). `media_generate_shot`
`model=wan14b` now accepts **832×480 (~10–12 min/clip) or 1280×720
(~55 min/clip — ComfyUI auto-offloads ~1.8 GB of weights to CPU, hence the
~5× slowdown)**; other dims still 400. Descriptions updated (tool + client
docstring); the pipeline-side change (matrix repo) is live in the
`media_pipeline` container — this server picks up the new description on its
next rebuild/restart. The 2026-10-31 entry's "720p rejected" line is
historical (it was the GPU-0 co-location ceiling).

2026-11-21: **pipeline M1–M5 client layer** (`media_pipeline_m1_m5_handoff.md` —
the pipeline-side changes shipped 2026-11-19/21, image `media-pipeline:latest`
`aa802b6e60b5`; client layer accepted live: `test_m1m5_client.py` 24/24 PASS): the two new queue-control tools + the M1/M5 semantics in the
existing tool descriptions (full notes in the "Queue control" section above):
- **`media_kill_job(job_id, client?)`** (M2) — `DELETE /jobs/{id}`: queued-only
  kill, frees the FIFO slot; running → 409, terminal → idempotent no-op,
  unknown → 404 (hint → `media_list_jobs`), client-tag mismatch → 403.
- **`media_queue_status()`** (M3) — `GET /health` queue summary
  (`queue.counts` / `queued_jobs` FIFO with `waited_s` / `oldest_queued` /
  `features`).
- **`media_assemble`**: `shots[].duration` is now ENFORCED (M1 — frame-hold /
  trim, the C14 root cause); adjustments reported in the job's
  `duration_adjustments` (via `media_list_jobs` `output`).
- **`media_job_result`**: in-flight `progress: {stage, completed, total,
  label}` on assemble polls (M5). **`media_list_jobs`**: status taxonomy now
  `queued|running|done|error|timeout|killed` (M4).
Client methods added to `media_pipeline_client.py`: `kill_job()`,
`queue_status()`. Live acceptance: `test_m1m5_client.py` (run on matrix
2026-11-21 against :8189 — all checks PASS).

2026-11-14: closed out `improve_mediapipeline_todo.md` (2026-11-02, after
the "A Peanut Risky Business" run — 4 orchestration-script deaths, 10 lost
job IDs, ~1 h of log archaeology) — every item shipped:
- **P0** — `media-film` orchestration skill (`agents-skills/media-film/`,
  9d2b145): on-disk state file after every submit, retry wrapper on every
  MCP call, timeboxed chunks, resume protocol, queue management, QC gates,
  assemble + publish checklist.
- **P1-1/P1-2/P1-3 + P2** — job recovery (T1–T4, cfb9407, 2026-11-04):
  `media_list_jobs` over the durable `jobs.jsonl` ledger (finished jobs
  survive pipeline restarts), `client` tag on all 14 job tools,
  SUBMIT/DONE/FETCH container-log lines, 60 s timeout + retry guidance
  (see the 2026-11-04 entry).
- **P4-1** — collision-safe `media_fetch` (T4). **P4-2** —
  `media_job_result` 404 recovery hint pointing at `media_list_jobs`.
  **P4-3** — mcp_vision workspace ownership (T5: root:root 755 →
  1000:1000; the 2026-11-02 permission-denied root cause).
- **P4-4** — `media_assemble` description now states that `sfx[].at` /
  `text_overlays` `start`/`end` / `vo_start` are absolute timeline seconds
  in the final cut (compute from per-shot durations via `media_info`).
- **P3** (pi-level codemode hardening: per-call `store()` persistence,
  `sleep(ms)`, documented failed-script summary) — deferred, optional; the
  `media-film` skill's on-disk state file is the working mitigation.
The todo file was removed with this entry.

2026-11-08: `media_render_tab_pdf` **Phase 4 — pitch-contour b/v marks** — the
transcribe pipeline now ships a per-note `pitch_contour` (5 samples across the
note's duration; pitch deviation from the note's nominal pitch in semitones,
⅓-quantized). `tab_pdf.py` renders the marks in the SOLO lane: bend = arc
through the dot (direction = pitch travel) + `b` badge (`_contour_mark`:
≤1 reversal + onset→offset rise ≥ `SOLO_BEND_RISE` = 1.0 semitone), vibrato =
wave glyph (≥2 reversals + total dev ≥ `SOLO_VIB_DEV` = 0.5). Text-tab
fallback appends `b`/`v` to the fret digit; SOLO KEY panel gained a bend demo
+ legend rows; a PDF note line appears under the CHORDS grid when marks are
present. `render()` result gains `bend_marks` / `vibrato_marks` (0 for jobs
predating the contour-enabled pipeline — backward compatible). Conservative
thresholds on purpose: on dense distorted mixes the contour is tracking
noise. `test_solo_marks.py` (5 suites); `mcp_media` rebuilt + restarted;
Back in Black re-rendered with 13 bends + 18 vibrato marks; all 4 published
tabs re-rendered + republished 16:46 UTC, public sha256 verified
(`docs/thor_validation_log.md` part 11).

2026-11-06: `media_render_tab_pdf` **SOLO board readability** (the per-measure
boards were too small to read at 1× inside the 7-measure rows):
- SCORE bands now render **4 measures per row** (was 7) — `MEASURES_PER_ROW`
  7 → 4 — giving each measure ~120pt of horizontal room.
- Solo boards render at **2× scale** (`SOLO_BOARD_SCALE = 2.0`): the SVG keeps
  the base viewBox geometry but is emitted at width×2 × height×2, so the dots,
  duration tails, play-order badges, h/p/slide/vibrato connectors, and the 4/4
  beat ruler all scale up uniformly — much easier to read. (The SOLO KEY
  legend panel is unchanged — it's a compact reference, not a solo lane.)
- Net effect: bigger, more legible solo boards; sections take more pages
  (e.g. Sweet Child O' Mine 8 → 13 pages). `test_chord_shapes.py` 6/6
  (unchanged); all 4 QA tabs re-rendered + republished (`overwrite=true`).

2026-11-04: client-facing job recovery + reliability (thor handoff T1–T4 —
pipeline-side `/jobs` durable ledger + 404 hints shipped on Matrix 2026-11-04;
handoff doc removed 2026-11-21, all items shipped):
- **T2** — new `media_list_jobs` tool (durable `GET /jobs` with
  status/client/user/flow/since/limit filters; finished jobs survive
  pipeline restarts, live in-flight jobs included) + optional `client`
  tag parameter on all 14 job tools (default `MEDIA_CLIENT`; recommended
  convention `<project>/<shot>`) forwarded to the pipeline and logged.
  `media_job_result` 404 errors now point to `media_list_jobs`.
- **T1** — container-log recovery: `SUBMIT kind=<tool> tag=<client>
  job_id=<id>` on every non-blocking submit + `DONE job_id=<id>
  status=<...> path=<...>` on every terminal result in
  `media_job_result` (one line per submit/terminal, greppable in
  `docker logs ai-mcp-mcp-mcp_media`).
- **T3** — 60 s MCP-gateway timeout + retry guidance embedded in the
  server instructions, every job tool's description, `media_job_result`,
  and `media_list_jobs` (transient `MCP request timed out` is expected on
  long orchestrations; the job is unaffected; retry the call; 503 +
  `retry_after_seconds` on a full queue means stop submitting and poll).
- **T4** — `fetch()` is collision-safe: a basename collision in
  `MEDIA_PIPELINE_FETCH_DIR` saves under a suffixed name
  (`vo.wav` → `vo_2.wav`), never overwrites; `media_fetch` returns
  `renamed: true` + a `note` and logs a `FETCH` line.
Verified: 26/26 mock-pipeline handoff checks (`test_handoff.py` — local
stdlib mock with the durable `/jobs` ledger, live pipeline untouched) +
57/57 `test_transcribe.py` regression (unchanged) + live verification
2026-11-04 (mcp_media rebuilt + restarted, mcp_vision rebuilt + restarted):
- schema over the wire: 25 tools; `client` param on all 14 job tools;
  `media_list_jobs` filters (status/client/user/flow/since/limit);
  60 s timeout + retry text in `media_job_result`/job-tool descriptions;
  collision note in `media_fetch` description.
- T1: `SUBMIT kind=media_generate_image tag=handoff-check job_id=…` +
  `DONE job_id=… status=done path=…` in `docker logs mcp_media` (image job
  + no-client storyboard regression job, both live).
- T2: `media_list_jobs(status=done)` returned live ledger jobs
  (`{job_id, flow, status, client, user, created, done, model, duration_s,
  cost_usd, error, output, outputs}`); `client=handoff-check` filter found
  the tagged job; unknown job_id → clean error pointing to
  `media_list_jobs`.
- T4: live `media_fetch` of the same file twice → `mp_….png` then
  `mp_…_2.png` (`renamed: true` + note; `FETCH … (basename collision —
  suffixed, nothing overwritten)` in the log).
- T5: `chown -R 1000:1000 /home/chuck/workspace/vision` (was root:root 755
  — the 2026-11-02 permission-denied root cause); mcp_vision startup probe
  logs `Output root /workspace/vision is writable (uid 1000)`; live
  `vision_analyze_image` on a signed-URL source AND a local-path source
  both succeeded with artifacts written to `/workspace/vision/<slug>/`.
- regression: old call signatures (no `client`) unchanged — live storyboard
  submit→poll→done with the default `pi` tag.

2026-11-06: `media_render_tab_pdf` **chord-shape coverage + SOLO lane
rework (Phase 1–3)** (triggered by 4 tabs published 2026-11-05 that rendered
several chords as "NO SHAPE / n/a" — planning doc removed 2026-11-21, all
phases shipped):
- **Shape library** (`tab_pdf.py` `OPEN_CHORDS`): added the 6th/9th family
  the QA tabs hit (B6/F6/G6) plus D6/E6/A9/D9/G9/Am9 — every entry
  interval-verified. Also corrected 5 pre-existing entries the checker
  caught: Csus4/Gsus4 carried wrong notes (x33020 had C# = b7; 332003 had
  B = 6th), and F#m/F#m7/F#maj7 were non-standard voicings missing core
  tones (now the standard 244222 / 242222 / 244362 E-shape barres @2).
  Note: D6 is xx0202 (D A B F#) — xx0212 is the D7 voicing.
- **Synthesized-barre fallback**: unknown symbols with an open-position
  hint no longer render "n/a" — the generator synthesizes a movable barre
  (root on the lower of the 6th/5th string; 7th chords add the 7th,
  maj7 adds 7th+11th — the exact E7/A7/Emaj7/Amaj7 patterns), labeled
  "barre @ N (synthesized)".
- **Coverage reporting**: `render()` now returns `missing_shapes` (fell
  through to n/a) and `synthesized_shapes` (fallback used), and the PDF
  header gets a visible note line when any shape is missing — no more
  silently shipped "n/a" pages.
- **Unit test** (`test_chord_shapes.py`): deterministic interval check of
  every library entry (root present + no tone outside the chord's tones
  and documented extensions), the rejected-candidates regression list
  (G9 353533 = G7sus4, E9 025100 = E6, Bm9 x23210 = b5, Emaj9 020100 =
  Emaj7, D6 xx0212 = D7), and the synthesized fallback. 55 entries pass.
- QA: all four 2026-11-05 tabs re-rendered in the `mcp_media` image —
  zero "n/a"/"NO SHAPE" entries; B6/F6/G6 render as proper diagrams.
- **Phase 3 — SOLO lane rework** (`tab_pdf.py`): the SOLO lane now renders
  per-measure **fretboard boards** (inline SVG, same visual language as the
  CHORDS diagrams) instead of the compact text tab: dot size + duration
  tail ∝ note hold time (from the note events' `end_s`, previously unused),
  time-order badges (1, 2, 3…), technique connectors inferred from
  timing/fret patterns (h/p for overlapping hammer-ons/pull-offs, arrow
  icon for slides < ¼ beat, wavy-line icon for same-fret overlap =
  hold/vibrato), fret window per measure with a starting-fret label
  (e.g. `4f`), wide spans split into side-by-side boards, a 4/4 beat
  ruler, and a **SOLO KEY** panel (example board + mark table) at the top
  of the SCORE part. Over-dense measures (>12 lead notes or >5 on one
  (string, fret)) fall back to the legacy text tab for that measure only.
  `render()` gained `solo_style` ('board' default | 'text') and reports
  `solo_fallbacks` (dense-measure count); the MCP tool exposes `solo_style`
  and both new result fields. Techniques are inferred — medium confidence,
  verify against the recording (bends need pipeline-side pitch contours —
  Phase 4, separate GPU-host work item).

2026-11-01 (part 8): `media_render_tab_pdf` **word-timing sanitization** —
fixed cramped/garbled lyrics when the ASR word timestamps in
`analysis.json` are broken (a known whisper + LLM-polish failure mode:
pile-ups of 8–20 words on one timestamp, words spilling 10s+ past their
section). `parse_analysis_sections` now detects broken lines (pile-up,
non-monotonic, impossible rate, >3 s spill) and re-times the whole section
evenly (section window split across lines by word count). Mild spills
(≤3 s) are left alone. Fixed Submission's cramped verses; Back in Black's
8 ASR-hallucinated lines now spread across the section (its lyrics are
still missing — the ASR failed on the distorted audio; see validation log
part 8).

2026-11-01 (part 5): `media_render_tab_pdf` **measure-aligned SCORE layout** —
replaced the CHART (chords over lyrics) + TAB (fretboard reference) parts
with a single SCORE section per song part: a measure-aligned table (7
measures/row) with three lanes — **VOCALS** (word-timed lyrics; a mini chord
diagram floats above the measure where each chord change lands, so the shape
is visible at the exact word you're singing), **RHYTHM** (chord diagrams for
instrumental sections), and **SOLO** (compact 6-string tab of the lead notes,
measure-aligned so you can see where the solo sits relative to the
vocals/rhythm — a friend can play the SOLO lane while you sing). Measure
boundaries come from the detected BPM (4/4 assumed; `bar_length = 240/bpm`).
Also fixed chord-shape correctness: A-shape power chords now render on
strings 5+4 (was 4+3), and the open-shape library was corrected (B7, Emaj7,
Am7, C6, Gm, Gm7, Dsus4, F#m, F#m7, Fmaj7, Bmaj7, Bbmaj7, C9, F9, F#maj7 —
verified by a MIDI-based note-set audit of all 46 library entries + all
shapes in the four published tabs).

2026-11-01 (part 4): `media_render_tab_pdf` **chord fingering grid** —
the PDF now opens (after the header) with a CHORDS part: a grid of
fixed-size chord diagram tokens (6 strings × 4 fret spaces, finger dots,
X/O markers), one per unique chord in first-appearance order, each
annotated with its starting fret ("3rd fret" / "open"). Shapes are
deterministic: `power`/`barre` generated from the pipeline's `shape`
hint (`base` E/A + `fret`, major/minor from the symbol), `open` chords
from a ~45-shape standard open-shape library; unknown shapes render
name-only. Rendered as HTML/CSS (crisp, no images). Bug fix: `is_minor`
now strips numeric quality suffixes (`C#m7` → minor).

2026-11-01 (part 3): `media_render_tab_pdf` **chord-over-lyrics layout** —
the PDF now opens with a CHART part: lyrics in reading order with chord
symbols floating above the exact word where each chord change lands
(lead-sheet style, so you can play and sing at the same time). Placement
uses the ASR **word-level timestamps** in `analysis.json`
(`sections[].lyrics[].words[].start_s`) against the chord event times
(`sections[].chords[].time_s`) — a chord at time t lands on the last word
that started at or before t; chords before the first word attach to the
first word; multiple changes on one word list together. Sections with
chords but no lyrics (intros/outros) get a timed chord strip. The
fretboard tab moves to a second TAB part (page break). Fallbacks: lines
without word timestamps get words interpolated evenly across the line's
time window; sections missing from `analysis.json` keep the tab.md
`Lyrics:` lines as plain chart lines. The standalone lyrics page is gone
(lyrics now live in the chart).

2026-11-01 (part 2): `media_render_tab_pdf` — transcribe job → styled PDF
song sheet, in the MCP server (any client on any machine can call it;
no local docker run needed). The deterministic generator
(`tab_pdf.py`, canonical source; also wrapped by the standalone
`homelab-tab-pdf` container in `scripts/tab-pdf/`) now runs in-process:
WeasyPrint 70 + the song-sheet fonts (Playfair Display / Inter /
JetBrains Mono variable TTFs) are baked into the `mcp_media` image.
Fetches the job's artifacts from the GPU host, renders to
`MEDIA_PIPELINE_FETCH_DIR/<slug>/<slug>-tab.pdf`, returns the local path
(publish via the `publish_file` skill, subdirectory `tabs`, for a public
URL).

2026-11-01: `media_transcribe_song` chord/key/fingering surface (matrix
pipeline update, per `transcribe_thor_spec.md` — the spec file was consumed
and removed with this change). The `/transcribe` API gained the
**deterministic chord/key/fingering surface** (worker stage 5.5; the LLM
never sees or touches it — binding design principle: tab data is
deterministic from the audio): `tuning` (v1 `standard` only), `stems`
default flipped **false → true** (vocal-stem ASR is now the faithful
default; demucs failure falls back to full mix + caveat), `full_notes`
(full note events), `whisper_model` (ASR model override),
`transpose_semitones` (int −12..12, bool rejected — shifts note events,
chord symbols and the key label; `notes.json` + `song.mid` re-rendered from
the shifted events), `target_key` (tonic `^[A-G][#b]?m?$` — offset computed
from the **detected** key, shortest direction ±6, wins over
`transpose_semitones`), `chord_style` (`as_detected` | `triads` |
`power`, case-insensitive — power = root+5th, a correction for metal where
the CQT major/minor guess is arbitrary), `capo` (suggest smallest capo 0–5
when the (transposed) key has no open shapes; chords shown as the finger
shapes, like a capo tab site), `shape_hints` (default true — per-chord
easiest fingering on the **final finger chord**, after transpose + capo).
Client: `transcribe()` forwards the full surface (null-default fields
`whisper_model`/`target_key` omitted when unset); MCP tool pre-validates
with clean errors (v1 instrument/tuning, bool-only flags, transpose range
+ bool-as-int, chord_style enum normalized to lowercase, target_key tonic
regex) — the pipeline re-validates with a 400 at submit as a backstop.
Output schema: `analysis.json` echoes `transpose_semitones` /
`chord_style` / `capo` / `shape_hints` + `capo_suggestion` (non-null only
when a capo was actually applied) + human-readable `caveats`; chord events
carry `shape` only when `shape_hints: true` (`{type: open|barre|power,
base, fret}`); `tab.md` gains header lines (`Transposed ±n semitones…` /
`Capo: n — chords shown as X finger shapes (sounding key Y)` / power /
triad notes) and renders shapes on the `Chords:` line (`open` / `E-shape
barre @ 4` / `open A5` / `power @ 3 (E-shape)`). Verified 2026-11-01:
57/57 mock-pipeline checks (`test_transcribe.py` — mock now mirrors the
submit-time 400 contract and echoes the new analysis fields; live pipeline
untouched) + live smoke (8/8 pipeline 400 paths; MCP schema via SSE +
LiteLLM `/mcp-rest/tools/list`; Riptide end-to-end with `chord_style=power`
+ `capo=true` via LiteLLM `/mcp-rest/tools/call` — see
`docs/thor_validation_log.md`).

2026-10-31: `media_transcribe_song` — song → guitar tab + lyrics (new
`/transcribe` job flow on the GPU host — contract in
`docs/media-mcp-handoff.md`). `source` = YouTube URL (yt-dlp
audio in-container, then `/upload` — `yt-dlp` added to the Dockerfile,
`mcp_vision` pattern) | direct http(s) URL (pipeline `/download`) | GPU-host
media_jobs path | staging file (auto-`/upload`). `instrument` v1 = `guitar`
only (clean error otherwise); `lyrics` (ASR on/off), `stems` (demucs vocal
stem, +1–2 min). Returns the job output paths
`{analysis, tab, lyrics, midi, audio}` (+ `source` echo when blocking) —
`media_fetch` / `media_pull` each one; `media_job_result` polls it
(`finalize_job` gained a transcribe branch — output has `tab` → all 5 paths
+ `location`). Identity threading automatic (user/client on the POST).
Verified 2026-10-31: 27/27 mock-pipeline checks (`test_transcribe.py` —
local stdlib stub, live pipeline untouched) + tool schema via MCP
`tools/list` (23 tools).

2026-10-31: shot-model update (matrix pipeline update, per
`thor_mcp_shot_model_snippet.md`) — `media_generate_shot` gains `model`
(`wan14b` quality = Wan 2.2 14B I2V GGUF Q5 — 832×480 ONLY, 81f (4n+1),
16fps, ~10–12 min/clip; 720p rejected with a clean 400, VRAM OOM gate
2026-10-25 \| `ltxv2b` fast draft = LTXV 2B 0.9.6 distilled — 768×512,
97f, 25fps, ~8s/clip). `width`/`height`/`frames`/`fps` are now optional —
omitted = the selected model's native defaults (the tool no longer sends
the old hardcoded 768×512/97f/24fps, which 400 against wan14b). `strength`
stays in the signature (ltxv2b-only; forwarded for both, ignored by the
server for wan14b). **Breaking for old callers:** the pipeline default
flipped to `MEDIA_SHOT_MODEL=wan14b` (QA passed 2026-10-31), so pre-update
calls with the old hardcoded dims 400 — this update is required, not
optional. Client: `generate_shot` rewritten (optional dims, `model` field
forwarded only when set). Verified: tool schema (model optional, dims
optional) + smoke tests (ltxv2b non-blocking shot ≈4s; no-model/no-dims →
wan14b 832×480 ≈5.1s; wan14b + 1280×720 → clean 400).

2026-09-25: submit-and-poll for long jobs (fixes the 30 s client abort) —
all 13 job tools (`media_storyboard`, `media_generate_image`,
`media_edit_image`, `media_generate_shot`, `media_text_to_speech`,
`media_add_voice`, `media_generate_music`, `media_sfx`,
`media_upscale_video`, `media_assemble`, `media_trim`, `media_freeze`,
`media_caption`) accept `non_blocking: bool = False`: when true the tool
returns `{job_id, status: "running"}` in ~1 s. New `media_job_result`
tool long-polls `GET /jobs/{id}` up to `wait_seconds` (default 20, capped
25 s — under pi-provider-litellm's hardcoded 30 s `CALL_TIMEOUT_MS`)
and returns the final result (same shape as the blocking tool, via
`finalize_job` on the job's `output` keys) or `status: 'running'` to poll
again. Client: `job_status` / `poll_job` / `finalize_job` (output-key
based — `video`/`image`/`audio`/`storyboard` — not flow-name based). No
pipeline (Matrix) changes required: `POST /<flow>` → `{job_id}` and
`GET /jobs/{id}` already existed. Backward compatible: default blocking
path unchanged for skill-runner / direct SSE. Verified: MCP-layer e2e
(10/10 — tools/list schema, TTS + storyboard submit→poll→done, bogus-id
clean 404, blocking regression).

2026-09-25: `media_pull` relative-path fix — `pull()`/`_resolve_path()` now
normalize a relative `media_jobs/<job_id>/<file>` ref to the absolute job
root (`/home/chuck/data/comfyui/run/`) before POSTing `/dl_token` (the
pipeline's `/dl_token` only accepts absolute paths; relative refs were
misrouted to `GET /jobs/{id}` and 404'd). Absolute paths and bare job_ids
unchanged. Verified: 7/7 MCP-layer checks (relative / absolute / bare
job_id → same resolved path + signed URL) + public fetch of a
relative-path-minted token through `siri.choukalos.com` (200).

2026-09-25: TTS voice library (matrix pipeline update, per
`voices_thor_handoff.md`) — 3 new tools: `media_list_voices` (`GET /voices`,
sync), `media_add_voice` (`POST /voices`, job — register a voice from a 3–15 s
reference wav; QC + 16 kHz mono normalization + audition sample generated on
the GPU), `media_delete_voice` (`DELETE /voices/{name}`, sync; `trailer`/
`default` protected). `media_text_to_speech` `voice` now accepts a **library
name** (`narrator_f` = female narrator, `deep_m`, ...) or a **reference wav
path** (the raw-path contract was previously documented but broken on the
server — now working); `trailer`/`default` behavior unchanged. Client:
`list_voices`/`add_voice`/`delete_voice` + updated `text_to_speech` docstring.
All changes additive and backwards compatible.

2026-09-24: full MCP client e2e of the Qwen-Image-2.1 upgrade (T0–T6,
`/tmp/qwen21_e2e/run.py` — raw MCP JSON-RPC over SSE, one phase per
invocation): tool-schema preflight (steps default 25, `model` +
`references` present) → qwen21 keyframe (45 s) → `model=legacy`
regression (125 s) → qwen21 edit sign OPEN→CLOSED (55 s; grid snap
1376×768) → barista portrait (40 s) → edit with `references` (50 s; job
output `references=1`, doorway figure resembles the portrait) → LTXV I2V
shot (15 s; 768×512 24 fps 4.04 s) → upscale `a2` 1080 (140 s) → TTS
trailer VO (15 s; 4.74 s) → assemble `vo_start=0.5` + `loudnorm` (5 s) →
`media_info` + `media_fetch` final 1920×1080 h264 24 fps AAC (2.5 MB).
All 11 phases PASS + vision QA ("OPEN"/"CLOSED" signs legible and
correctly spelled; references edit matches portrait; final cut clean
1080p, no artifacts). Notes: legacy-model subject drift (bakery→
bookstore) is model behavior, not a client bug; a2 upscale reports 42 fps
metadata (duration preserved; assemble normalizes to 24 fps); pipeline job
registry is ephemeral — `GET /jobs/{id}` + `media_info` 404 on stale jobs,
but file fetch / `media_pull` still work.
2026-09-24: `media_assemble` quality extensions — added `upscale_each` (runs
SeedVR2 (B) on every shot before concat → true 1080p output; tune with
`upscale_resolution` / `upscale_noise_scale` / `upscale_fps` / `upscale_seed`)
and `text_overlays` (burns crisp titles into shots post-I2V — list of
`{text, start?, end?, position?, size?, color?}`; LTXV warps text baked into
the I2V prompt, so titles composite in post). Both are assemble-stage video
features (orthogonal to the image model) and backward-compatible (default
off). Verified: 16/16 client payload checks + live end-to-end (qwen21 keyframe
→ I2V shot → `upscale_each`+`text_overlays` assemble → 1920×1080 h264,
SeedVR2 ~12 min) + vision QA (title "THE FOX" crisp bottom-center, no warp)
+ live MCP wire schema (6 new params) + real MCP `tools/call` (title "MCP
TEST" crisp).
2026-09-23: Qwen-Image-2.1 upgrade (matrix pipeline update) — `/images` +
`/images/edit` now default to **Qwen-Image-2.1** (unified create+edit; 25
steps, ~30–120 s at 1280×720; server clamps qwen21 steps to [10, 50]).
`media_generate_image` + `media_edit_image` gain `model` (`qwen21` default |
`legacy` = old Qwen-Image-2512/2511 GGUF+Lightning, steps=4/8) and
`media_edit_image` gains `references` (up to 9 identity/consistency images —
pass a previous shot's keyframe for cross-shot character/product
consistency; qwen21 only). Steps defaults updated 4/8 → 25. Edit output
snaps to the model's native grid (e.g. 1376×768 for a 1280×720 canvas).
Verified: 27/27 client + live pipeline checks (qwen21 t2i/edit, legacy
rollback t2i/edit, references, identity) + 9/9 MCP SSE end-to-end checks
(`test_qwen21_upgrade.py`, `test_mcp_e2e.py`).
2026-09-07: post-gen edit + file movement (media_pipeline_gaps.md Part 2,
T2/T3) — 8 new tools (`media_trim`, `media_freeze`, `media_caption`,
`media_info`, `media_upload`, `media_download`, `media_put`, `media_pull`);
`media_assemble` M4 extensions (object shots, timestamped sfx, `vo_start`,
`loudnorm` — backward compatible); staging dir
`/home/chuck/workspace/media` (`MEDIA_STAGING_DIR`) for local inputs +
`scripts/cleanup-media-staging.sh` (`MEDIA_STAGING_MAX_AGE_DAYS`, default
7d); public signed-URL route `siri.choukalos.com/media/pipeline/*` (Caddy →
matrix `:8189`, `/dl/*` public, `/upload` key-auth, `/dl_token` LAN-only).
Verified end-to-end: 18/18 client checks + 7/7 public-route checks
(LAN + through Cloudflare); off-LAN device check pending (manual).
2026-09-09: identity threading — `user`/`client` stamped on every job POST
(caller's LiteLLM key → `/key/info` → user; `MEDIA_USER` fallback). Enables
per-user media cost attribution in the pipeline metering — **live
end-to-end 2026-09-09**: pipeline v2 `/metrics` + `jobs.jsonl` on Matrix,
scraped by VictoriaMetrics, surfaced in the Grafana "AI Work & Spend"
dashboard (see `/home/chuck/homelab/METRICS.md`, "Media Work Metering
(v2)").
2026-08-28: legacy ComfyUI/HF tools (`generate_image`, `edit_image`,
`image_info`, `list_images`) removed — old ComfyUI flows decommissioned.
The `media-generate` skill now uses `media_generate_image` + `media_fetch`.