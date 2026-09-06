# mcp_media

MCP server for media operations via the **GPU-host media-pipeline**.

Thin HTTP client for the GPU-host `media-pipeline` service
(`MEDIA_PIPELINE_URL`, `http://192.168.4.55:8189` on Matrix). All GPU work
(ComfyUI + VLLM + TTS/music/SFX workers) happens on the GPU host; this
container only POSTs jobs, polls, and downloads results. Jobs block until
done (per-flow timeouts up to 2h; LiteLLM `timeout: 7200` set for this server).

## Tools

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
| `media_assemble` | `/assemble` | Concat shots + mix VO/music/SFX → final mp4 |
| `media_fetch` | `/files/{name}` | Download a pipeline result to the local media library |

**Path model** (Thor has no shared filesystem with the GPU host):
- Pipeline tools return **GPU-host paths** — required so `media_assemble`
  (JSON, host paths only) can chain on the host.
- `media_fetch` downloads any result to `MEDIA_PIPELINE_FETCH_DIR`
  (default `/home/chuck/data/media/generated/pipeline`) and returns the local path.
- Input tools that take local files (`media_edit_image`, `media_generate_shot`,
  `media_sfx`, `media_upscale_video`) **auto-fetch** GPU-host paths to a temp
  dir before uploading — flows chain without manual fetch steps.
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
| `LITELLM_PROXY_URL` | `http://litellm-proxy:4000` | Proxy used to resolve caller key → user |
| `MEDIA_USER` | `unknown` | Fallback user when no Authorization header (Thor: `chuck`) |
| `MEDIA_CLIENT` | `pi` | Calling-app label stamped on jobs |

Transport: streamable-http on `0.0.0.0:8000` (`/mcp`).

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