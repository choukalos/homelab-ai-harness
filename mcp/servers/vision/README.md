# mcp_vision

MCP server for **image and video analysis** using the `matrix-coder` vision
model (Qwen3.6-27B via vLLM) through LiteLLM. Ported from the owner's
`video-analyze` pi skill (`/home/chuck/data/ai-kb/raw/video-analyze/`) — the
skill's per-subagent session-budget pattern is replaced by **server-side
batching**: ≤5 images per fresh LLM call, unlimited calls, no session budget.

## Tools

| Tool | Purpose |
|------|---------|
| `vision_analyze_image` | Single image (or gif) → structured markdown incl. verbatim on-screen text |
| `vision_analyze_video` | Video → storyboard: extract (scene/raw) → batched vision → consolidated report |
| `vision_extract_frames` | Frame extraction only (no LLM) — pairs with `publish_file` for blog artifacts |
| `vision_cleanup` | Delete artifact dirs (by slug or age) — artifacts are ephemeral |
| `vision_probe` | Ops: image cap + latency probe via LiteLLM (use after model changes) |

**`source`** accepts a local path under an allowed root (`/data/media`,
`/data/workspace`, `/data/ai-kb/raw` — symlink/`../` escape rejected), any
`http(s)` URL (2 GB download cap), or a YouTube URL (yt-dlp, metadata first:
title/duration/chapters feed the report).

### `vision_analyze_video` modes

- **`scene`** (default): scene-change detection per segment. Single-pass for
  <5 min videos (≤50 frames); chunked for longer (auto chunk table:
  5-10 min → 60 s/8, 10-20 → 120 s/10, 20-30 → 180 s/10, 30-60 → 300 s/12).
  Every segment gets coverage; total capped at 200 frames.
- **`raw`**: full native FPS (or `fps=N`) with **precise per-frame
  timestamps** (`frame_metadata.jsonl`) — for frame-accurate timing analysis.
  **Frame-budget guarded** (default 3000): refuses before extracting when
  the estimate exceeds the budget, with a concrete suggestion.

### `focus` templates

`general` · `gameplay` (mechanics/timing/visuals/UI/level design) ·
`tutorial` (steps, UI actions, verbatim code) · **`commercial`** — QA of
`mcp_media`-generated media: prompt fidelity, visual quality,
artifacts/defects, composition, text rendering → PASS/FAIL verdict + fix
suggestions. Pass the generation brief in `prompt`.

## Pipeline

```
source (path/URL/YouTube)
  → ffprobe (duration, native fps, dims)
  → ffmpeg extract (scene select / fps filter; 640px lanczos; audio dropped)
  → batches of ≤5 frames (base64 data-URLs)
  → per-batch vision call (matrix-coder, thinking OFF, 3 retries)
  → text-only consolidation → report.md
```

### Artifacts

`/home/chuck/data/workspace/vision/<slug>/` (rw mount nested in the ro
workspace mount):

```
<slug>/
├── frame_NNNN.png        # global sequential numbering
├── summary.md            # overview + chapter table
├── chapters.json         # chunk/chapter map
├── frame_metadata.jsonl  # {file, timestamp, chunk[, precise]}
└── report.md             # consolidated analysis
```

**Artifacts are NOT public** (no Caddy route; never under `media/public/`).
They are ephemeral — clean up via `vision_cleanup` (LLM) or
`scripts/cleanup-vision.sh` (host; manual, no cron per house convention).

## Environment

| Var | Default | Purpose |
|-----|---------|---------|
| `LITELLM_API_BASE` | `http://litellm-proxy:4000` | LiteLLM REST |
| `LITELLM_API_KEY` | — | master key (container) |
| `VISION_MODEL` | `matrix-coder` | alias as-is (REST takes no provider prefix) |
| `VISION_MAX_IMAGES` | `5` | images per LLM call (probed 2026-08-27) |
| `VISION_OUTPUT_ROOT` | `/data/workspace/vision` | artifact root |
| `VISION_ALLOWED_ROOTS` | `/data/media,/data/workspace,/data/ai-kb/raw` | local-path allowlist |
| `VISION_DOWNLOAD_CAP_BYTES` | `2147483648` | URL download cap |
| `VISION_MAX_FRAMES_RAW` | `3000` | raw-mode frame budget |
| `VISION_MAX_FRAMES_SCENE` | `200` | scene-mode total cap |
| `VISION_TIMEOUT` | `300` | per vision-call timeout (s) |

## Notes

- **Thinking OFF**: Qwen3 thinking models burn the completion budget
  (`content=None` otherwise) — `chat_template_kwargs.enable_thinking=false`
  on every call (A0 probe, 2026-08-27).
- **Cap 5 images/request** is a provider limit (vLLM `--limit-mm-per-prompt`),
  not a session budget — the server makes fresh requests, so total frames
  are unbounded.
- **Timestamps**: scene mode = chunk-based estimates; raw mode = precise
  (`chapter_start + i/fps`).
- **Subprocess safety**: ffmpeg/ffprobe/yt-dlp run as arg lists (no shell
  strings); local paths validated against the allowlist via `resolve()`.
- **Long-running**: `vision_analyze_video` on long videos takes minutes
  (144 frames ≈ 29 LLM calls). LiteLLM `timeout: 7200` (A3 registration).

## Registration (A3)

LiteLLM `litellm/config.yml` (owner reload — batched with KB K3's
`mcp_knowledge` timeout change):

```yaml
  - name: mcp_vision
    url: http://mcp_vision:8000/mcp
    timeout: 7200
    allow_all_keys: true
    display_tools_to_model: true
```
## State / future work

> The vision plan file (`mcp-vision-todo.md`, A0–A3, all complete
> 2026-08-28) was deleted 2026-08-29; this README is the mcp_vision state
> doc.

- **All phases complete** — server live (5 tools), E2E verified (local mp4,
  GIF, remote URL, YouTube, raw mode, budget guard, cleanup).
- **Artifacts**: ephemeral + NON-public; `scripts/cleanup-vision.sh` (manual,
  no cron — house convention).
- **Possible future work** (none currently scheduled):
  - Per-user artifact attribution (today: single household).
  - Frame-budget auto-tuning per video length (today: fixed guard).
  - `focus` template expansion (today: general / gameplay / tutorial /
    commercial).
