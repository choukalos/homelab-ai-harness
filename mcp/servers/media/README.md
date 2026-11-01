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
| `media_render_tab_pdf` | local (WeasyPrint) | Transcribe job → **styled PDF song sheet** (deterministic — no LLM; `tab_pdf.py` renders the job's `tab.md` verbatim with Playfair Display / Inter / JetBrains Mono). **Layout (2026-11-01 part 3): CHART first — chords over the word-timed lyrics so you can play & sing at once (chord symbols float above the exact word where each change lands, from ASR word timestamps + chord event times); then TAB — fretboard reference (per-section chords + shape hints, boxed monospace tab).** Fetches `tab.md` / `lyrics.txt` / `analysis.json` from the GPU host, renders locally to `MEDIA_PIPELINE_FETCH_DIR/<slug>/<slug>-tab.pdf`. `title`/`artist` override the LLM-guessed header (pass the real identity); `slug` names the output dir (default: job_id). Returns `{local_path, size_bytes, pages, title, artist, sections}`. Publish with the `publish_file` skill (subdirectory `tabs`) for a public URL |
| `media_job_result` | `GET /jobs/{id}` (long-poll) | Poll a submitted job to its final result (≤25 s per poll — kept under the ~30 s client tool-call timeout). Returns the final result (same shape as the blocking tool) or `{status: 'running'}` to poll again |

**Submit-and-poll (2026-09-25):** every job tool above accepts
`non_blocking: bool = False`. With `non_blocking=true` the tool returns
`{job_id, status: "running"}` in ~1 s instead of blocking until the job
finishes; then poll `media_job_result(job_id, wait_seconds=20)` until
`status` is `done`/`error`. Default (`false`) keeps the original blocking
behavior (skill-runner / direct SSE callers unchanged). Why: pi's
`pi-provider-litellm` aborts tool calls at a hardcoded 30 s while the job
keeps running server-side — submit-and-poll keeps every tool call under the
abort window without touching litellm/pi.

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