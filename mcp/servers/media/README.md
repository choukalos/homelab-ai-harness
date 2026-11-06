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
| `media_generate_image` | `/images` | Text → keyframe image (Qwen-Image-2.1 default, 25 steps; `model`: `qwen21` \| `legacy` old Qwen-Image-2512) |
| `media_edit_image` | `/images/edit` | Image + text → edited image (unified Qwen-Image-2.1 editing; `model` + `references` up to 9 identity/consistency images for cross-shot consistency) |
| `media_generate_shot` | `/shots` | Keyframe → I2V clip (upload). `model`: `wan14b` (quality, Wan 2.2 14B, ~5s clip, ~10–12 min, 832×480 only) \| `ltxv2b` (fast draft, LTXV 2B, ~4s clip, ~8s); omitted = server default (wan14b as of 2026-10-31). Dims/frames/fps omitted = model-native defaults. `strength` is ltxv2b-only (ignored for wan14b) |
| `media_text_to_speech` | `/tts` | Script → voice-over wav (`voice` = library name — `trailer` default, `default`, `narrator_f`, `deep_m`, ... — or a reference wav path on the GPU host) |
| `media_list_voices` | `/voices` (sync) | TTS voice library: name, description, gender, style, audition sample path |
| `media_add_voice` | `/voices` (job) | Register a voice from a 3–15 s reference wav (QC'd, normalized 16 kHz mono, audition sample generated on the GPU) |
| `media_delete_voice` | `/voices/{name}` (sync) | Remove a voice (ref + sample + manifest entry); `trailer`/`default` protected |
| `media_generate_music` | `/music` | Prompt(+lyrics) → song/instrumental wav (ACE-Step) |
| `media_transcribe_song` | `/transcribe` (job) | Song → **guitar tab + timestamped lyrics** (deterministic DSP + ASR + LLM polish; `source` = YouTube URL / http(s) URL / GPU-host path / staging file; v1 `instrument="guitar"`, `tuning="standard"` only; `stems` default true = demucs vocal stem for cleaner lyrics; `full_notes` = full note events; `whisper_model` override). **Chord/key/fingering surface** (deterministic post-processing, 2026-10-31 — the LLM never touches it): `transpose_semitones` (−12..12) / `target_key` (tonic like `E`/`Bb`/`F#m`, offset from the detected key, wins over transpose) re-render tab + MIDI in the new key; `chord_style` = `as_detected` (default) / `triads` / `power` (root+5th, metal-friendly); `capo=true` suggests the smallest capo (0–5) when the key has no open shapes (chords shown as finger shapes); `shape_hints` (default true) annotates every chord with its easiest fingering (open / E- or A-shape barre / power) |
| `media_sfx` | `/sfx` | Video → synced SFX bed (MMAudio, upload) |
| `media_upscale_video` | `/upscale` | Video → 1080p (`b`=SeedVR2 quality, `a2`=fast, upload) |
| `media_assemble` | `/assemble` | Concat shots + mix VO/music/SFX → final mp4 (M4: object shots `{path, in?, out?, duration?}`, timestamped `sfx: [{path, at}]`, `vo_start`, `loudnorm`; quality: `upscale_each` SeedVR2 per-shot → true 1080p, `text_overlays` burned-in titles — string forms still work) |
| `media_fetch` | `/files/{name}` | Download a pipeline result to the local media library |
| `media_render_tab_pdf` | local (WeasyPrint) | Transcribe job → **styled PDF song sheet** (deterministic — no LLM; `tab_pdf.py` renders the job's `tab.md` verbatim with Playfair Display / Inter / JetBrains Mono). **Layout (2026-11-01 part 5): CHORDS — a grid of fixed-size chord fingering diagrams (name + shape + starting-fret annotation; power/barre shapes generated from the pipeline's `shape` hint, open chords from a standard-shape library); then SCORE — a measure-aligned score per section so you can sing & play at once (with a friend): VOCALS lane (word-timed lyrics with a mini chord diagram above the measure where each change lands, from ASR word timestamps + chord event times), RHYTHM lane (chord diagrams, instrumental sections), SOLO lane (per-measure fretboard boards — same visual language as the CHORDS diagrams: dot size + duration tail = hold time, number = play order, h/p = hammer-on/pull-off, arrow = slide, wave = hold/vibrato; decoded by the SOLO KEY panel at the top of the SCORE part; over-dense measures fall back to the compact 6-line text tab; 2026-11-06 Phase 3).** Fetches `tab.md` / `lyrics.txt` / `analysis.json` from the GPU host, renders locally to `MEDIA_PIPELINE_FETCH_DIR/<slug>/<slug>-tab.pdf`. `title`/`artist` override the LLM-guessed header (pass the real identity); `slug` names the output dir (default: job_id); `solo_style` = 'board' (default) or 'text' (legacy compact tab). Returns `{local_path, size_bytes, pages, title, artist, sections, missing_shapes, synthesized_shapes, solo_style, solo_fallbacks}` (shape-coverage warnings + solo-lane reporting, 2026-11-06). Publish with the `publish_file` skill (subdirectory `tabs`) for a public URL |
| `media_job_result` | `GET /jobs/{id}` (long-poll) | Poll a submitted job to its final result (≤25 s per poll — kept under the ~30 s client tool-call timeout). Returns the final result (same shape as the blocking tool) or `{status: 'running'}` to poll again |
| `media_list_jobs` | `GET /jobs` (sync) | List jobs from the durable ledger (filters: `status`/`client`/`user`/`flow`/`since`/`limit`; newest-first) — the recovery path for lost `job_id`s; finished jobs survive pipeline restarts (2026-11-04) |

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
  ledger** (`GET /jobs`): `status` (`running`|`done`|`error`|`timeout`,
  default `running`; comma-separated for multiple), `client`, `user`,
  `flow`, `since` (ISO timestamp or epoch seconds), `limit` (default 50,
  max 200) → `{count, jobs: [{job_id, flow, status, client, user, created,
  done, model, duration_s, cost_usd, error, output, outputs}]}` newest-
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

2026-11-04: client-facing job recovery + reliability (thor handoff T1–T4,
per `thor_media_mcp_handoff.md` — pipeline-side `/jobs` durable ledger +
404 hints shipped on Matrix 2026-11-04):
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
rework (Phase 1–3)** (per `enhance_tab_tool.md`, triggered by 4 tabs
published 2026-11-05 that rendered several chords as "NO SHAPE / n/a"):
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
`/transcribe` job flow on the GPU host, per
`docs/song_transcribe_matrix_handoff.md`). `source` = YouTube URL (yt-dlp
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