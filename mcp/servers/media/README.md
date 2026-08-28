# mcp_media

MCP server for media operations: the **GPU-host media-pipeline** (preferred,
new flows) plus legacy ComfyUI/HF image tools (being decommissioned).

## Pipeline tools (2026-08-28)

Thin HTTP client for the GPU-host `media-pipeline` service
(`MEDIA_PIPELINE_URL`, default `http://192.168.4.55:8189` on Matrix). All GPU
work (ComfyUI + VLLM + TTS/music/SFX workers) happens on the GPU host; this
container only POSTs jobs, polls, and downloads results. Jobs block until
done (per-flow timeouts up to 2h; LiteLLM `timeout: 7200` set for this server).

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
`media_generate_music` → `media_upscale_video(pipeline="b")` per shot →
`media_assemble` → `media_fetch` the final mp4.

## Legacy tools (kept until old ComfyUI/HF flows are decommissioned)

| Tool | Backend |
|---|---|
| `generate_image` | HF Inference API (primary) / ComfyUI `192.168.4.55:8188` (fallback) / LiteLLM DALL-E (legacy) |
| `edit_image` | LiteLLM `/v1/images/edits` (stub) |
| `image_info` | Pillow metadata |
| `list_images` | Directory listing |

## Config

| Env | Default | Meaning |
|---|---|---|
| `MEDIA_PIPELINE_URL` | `http://127.0.0.1:8189` | GPU-host pipeline base URL |
| `MEDIA_PIPELINE_FETCH_DIR` | `/home/chuck/data/media/generated/pipeline` | `media_fetch` download dir |
| `COMFYUI_BASE_URL` | `http://192.168.4.55:8188` | Legacy ComfyUI |
| `MEDIA_OUTPUT_DIR` | `/home/chuck/data/media/generated` | Legacy image output |

Transport: streamable-http on `0.0.0.0:8000` (`/mcp`).