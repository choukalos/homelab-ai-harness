# mcp_media pipeline contract (self-contained summary, verified 2026-11-04)

The canonical contract lives on the GPU host (`docs/matrix_media_pipeline_api.md`
+ `docs/thor_media_mcp_handoff.md`) — unreachable off-LAN. This file is the
self-contained summary the skill needs. Tool names below are the MCP names
(`mcp__litellm__mcp_media_*` via the litellm gateway); the underlying pipeline
endpoints are on `matrix:8189` (LAN-only).

## Job model

- Every generation flow is a **job**: `queued → running → done|error`.
- **Queue:** 1 running + 5 queued = 6 in-flight max (global, shared by all
  clients). Full queue → **HTTP 503 + `retry_after_seconds`**.
- **Durable ledger:** finished jobs survive pipeline restarts; live in-flight
  jobs are included. 14-day retention on result files.
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
| `media_assemble` | final cut | `shots:[gpu path \| {path,in?,out?,duration?}], vo?, music?, sfx?: path\|[{path,at}], vo_start=0, loudnorm=false, text_overlays:[{text,start?,end?,position?,size?,color?}], upscale_each=false, width=1920, height=1080, fps=24, *_volume` | `{path}` |
| `media_upscale_video` | SeedVR2 / fast | `video, pipeline="b"\|"a2", resolution=1080` | `{path}` |
| `media_trim` / `media_freeze` / `media_caption` | ffmpeg post | source (gpu or staging path) | `{path}` |
| `media_info` | ffprobe (sync) | `path` | `{duration_s,width,height,fps,video_codec,audio_codecs[],size_bytes,bitrate_bps}` |
| `media_job_result` | poll a job | `job_id, wait_seconds=20 (max 25)` | final result `{path,...}` or `{status:"running"}` or `{status:"error",error}` |
| `media_list_jobs` | **durable ledger** | `status="running"\|"done"\|"error"\|"timeout" (default running), client?, user?, flow?, since? (ISO-8601 ONLY), limit=50 (max 200)` | `{count, jobs:[{job_id,flow,status,client,user,created,done,model,duration_s,cost_usd,error,output,outputs}]}` newest-first |
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

## Paths & retention

- GPU-host artifacts: `/home/chuck/data/comfyui/run/media_jobs/<job_id>/mp_<job_id>_00001.{mp4,png,wav,…}` — **14-day retention**.
- `media_fetch` local dir (thor): `/home/chuck/data/media/generated/pipeline` — the **approved publish root** for `publish_file`.
- Public routes (off-LAN): `https://siri.choukalos.com/media/pipeline/dl/<token>` (signed, public) and `/media/pipeline/upload` (X-Api-Key = chuck/dylan LiteLLM key; multipart; 500 MB cap). Everything else under `/media/pipeline/*` is 404 off-LAN.

## Quality rules (tuned on the GPU host)

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