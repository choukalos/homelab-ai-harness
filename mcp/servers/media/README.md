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
| `media_generate_image` | `/images` | Text → keyframe image |
| `media_edit_image` | `/images/edit` | Image + text → edited image (upload) |
| `media_generate_shot` | `/shots` | Keyframe → ~4s I2V clip (LTXV, upload) |
| `media_text_to_speech` | `/tts` | Script → voice-over wav |
| `media_generate_music` | `/music` | Prompt(+lyrics) → song/instrumental wav (ACE-Step) |
| `media_sfx` | `/sfx` | Video → synced SFX bed (MMAudio, upload) |
| `media_upscale_video` | `/upscale` | Video → 1080p (`b`=SeedVR2 quality, `a2`=fast, upload) |
| `media_assemble` | `/assemble` | Concat shots + mix VO/music/SFX → final mp4 (M4: object shots `{path, in?, out?, duration?}`, timestamped `sfx: [{path, at}]`, `vo_start`, `loudnorm` — string forms still work) |
| `media_fetch` | `/files/{name}` | Download a pipeline result to the local media library |

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

Transport: streamable-http on `0.0.0.0:8000` (`/mcp`).

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