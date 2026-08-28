# mcp_vision — Image/Video Analysis MCP Tool

> Planning doc for the vision (image/video analysis) MCP server.
> **Ordered BEFORE the KB rebuild (owner, 2026-08-28)** — it validates the
> `matrix-coder` vision path end-to-end and de-risks KB K4's page-render
> fallback.
> Owner: chuck. Last updated: 2026-08-28 (A0 — skill reviewed, spec drafted).

---

## 1. S0 — Discovered state

### 1.1 Source: owner's `video-analyze` pi skill (dropped at `ai-kb/raw/video-analyze/`)

- **`SKILL.md`** — workflow spec: strategy selection by video length,
  analysis categories (mechanics / timing / visual design / UI-HUD /
  level design / transitions), batching rules, tips (thresholds, 640px,
  skip intro/outro).
- **Scripts (bash + ffmpeg, 1152 lines total):**
  | Script | Purpose |
  |---|---|
  | `extract-frames.sh` (238) | single-pass scene detection, short videos (<5 min): `select='gt(scene,T)+eq(n,0)'`, auto threshold tuning, uniform-sampling fallback |
  | `extract-chunks.sh` (385) | **workhorse** — long videos: time-chunks, scene detection per chunk, uniform fallback, midpoint fallback; scene mode + `--raw` full-FPS mode; emits `summary.md` + `chapters.json` + `frame_metadata.jsonl` |
  | `extract-raw.sh` (338) | frame-accurate timing analysis: full-FPS extraction, chapter subdirs (5–10s), precise per-frame timestamps |
  | `fetch-youtube.sh` (98) | yt-dlp: metadata pass (title/duration/chapters → `video.meta.json`) + download; "read meta before analyzing" pattern |
  | `probe-image-limit.sh` (93) | probes model image cap (1×1 PNGs, parses K from the 400 error) |
- **Key extraction mechanics (to port):** ffprobe-style duration/native-FPS
  readout; `-ss` after `-i` for frame-accurate seeking; lanczos scaling to
  640px; `format=yuv420p` + `-fps_mode cfr` in raw mode; per-chunk
  fallbacks (too many → uniform resample; zero scenes → midpoint frame).
- **Probed model limit (2026-08-27, in the skill):** `litellm/matrix-coder`
  = **5 images per request**. The skill's elaborate subagent/session-budget
  dance exists because a pi agent's *conversation* accumulates images.
  **An MCP server has no such constraint: every LLM call is a fresh
  request → 5 images/call, unlimited calls.** The server itself
  orchestrates the batches — the pi-subagent pattern is replaced by a
  server-side loop. This is the main structural simplification of the
  conversion.

### 1.2 MCP server pattern (from the live stack)

- `python:3.12-slim` + `pyproject.toml` + `server.py`, SSE on `:8000`,
  `mcp` pinned `<2`, `ai-net`, LiteLLM reaches it by service name
  (`http://mcp_vision:8000/mcp`), registered in `litellm/config.yml`
  (`allow_all_keys: true`).
- ffmpeg is NOT in the base image → Dockerfile `apt-get install ffmpeg`
  (~100 MB). yt-dlp via pip.
- LLM calls: raw `httpx` POST to the LiteLLM proxy
  (`/v1/chat/completions`, `matrix-coder`, image content parts as
  `data:` base64) — no litellm python client dep (keep the image lean);
  small retry wrapper. (Alternative: litellm client — decide at A1.)

### 1.3 Vision model (owner-confirmed, KB Q1)

- `matrix-coder` (Qwen3.6-27B via vLLM on Matrix, via LiteLLM) — vision
  capable, **≤5 images and/or 1 video per turn/request**.
- A0 verifies empirically via LiteLLM (the skill's probe, re-pointed at
  the LiteLLM endpoint) — exact cap, latency, token cost per 640px frame.

---

## 2. Requirements (owner, 2026-08-28)

1. **`mcp_vision`** — named for what it is: a *vision* tool (owner).
2. Analyze **images and videos** — port the owner's `video-analyze` skill
   (all three extraction strategies: single-pass scene, chunked scene,
   raw full-FPS timing mode).
3. **Local files** from Thor (media/, workspace/, `ai-kb/raw/`).
4. **Remote files: `.mp4` / `.mov` / `.gif` from websites — not just
   YouTube** (owner). YouTube via yt-dlp stays (skill already has it).
5. Built **before** the KB MCP update; KB K4 reuses the verified
   vision-call pattern.
6. Available to any AI via LiteLLM (`allow_all_keys: true`), consistent
   with the other MCP servers.

---

## 3. Proposed architecture

### 3.1 Server

- `mcp/servers/vision/` → container **`mcp_vision`** (ai-net, SSE :8000).
- Deps: `mcp[cli]` (<2), `httpx`, `yt-dlp`, system `ffmpeg`.
- Env: `LITELLM_URL` (default `http://litellm:4000`), `LITELLM_API_KEY`,
  `VISION_MODEL` (default `matrix-coder`), `VISION_MAX_IMAGES` (default 5,
  from A0 probe), `VISION_OUTPUT_ROOT` (default `/data/media/generated/vision`).
- ro mounts: `/home/chuck/data/media` (generated output + source files),
  `/home/chuck/data/workspace`, `/home/chuck/data/ai-kb/raw`.
- **Local path allowlist:** only paths under the mounted roots (same
  pattern as mcp_media/publish_file). No shell strings — `subprocess`
  arg lists only.
- Downloads (remote URLs) → ephemeral `/app/tmp/<uuid>/` (cleaned on
  exit); size cap **2 GB** (Q2); http/https only.

### 3.2 Tools (v1 — 4)

| Tool | Notes |
|---|---|
| `vision_analyze_image(source, prompt?)` | image (png/jpg/webp/gif/…) → one vision call → structured markdown (description + on-screen text verbatim). `source` = local path or http(s) URL. |
| `vision_analyze_video(source, prompt?, mode?, chunk_secs?, frames_per_chunk?, fps?, scale_width?, skip_intro?, skip_outro?, focus?)` | the skill's workflow, server-side. `mode`: `scene` (default; auto-picks single-pass vs chunked by duration — <5 min single-pass, else chunked) or `raw` (full-FPS timing). `focus`: optional analysis lens (`gameplay`, `tutorial`, `general` — selects the prompt template from the skill's categories). Returns report + artifact paths. |
| `vision_extract_frames(source, out_dir?, fps?, max_frames?, scale_width?, chunk_secs?, skip_intro?, skip_outro?)` | extraction only (no LLM): frames + `summary.md` + `chapters.json` + `frame_metadata.jsonl` to `media/generated/vision/<slug>/` (pairs with `publish_file` for blog artifacts). |
| `vision_probe(n?)` | the skill's image-limit probe, re-pointed at LiteLLM: verifies the current cap + measures latency/cost. Ops tool; also run at A0. |

All tools return structured JSON: `{status, source, duration, frames,
batches, report_markdown?, artifacts_dir?, warnings[]}`.

### 3.3 Pipeline (video)

```
source (path | URL | youtube)
  │  URL: httpx stream → /app/tmp (2 GB cap)   |  youtube: yt-dlp (meta + video)
  ▼
probe: duration, native fps, size
  ▼
extract (ffmpeg, ported from the skill's scripts):
  scene mode : per-chunk select='gt(scene,T)+eq(n,0)' → uniform fallback
               → midpoint fallback            (extract-chunks.sh logic)
  raw mode   : fps=N, cfr, chapter subdirs    (extract-raw.sh logic)
  → frames (640px lanczos) + chapters.json + frame_metadata.jsonl
  ▼
batch: groups of ≤ VISION_MAX_IMAGES (5)
  ▼
per-batch vision call (FRESH context each call — no session budget):
  prompt = template(focus, chunk timestamps, "transcribe on-screen text
  verbatim, describe what changed from the previous frame")
  → per-batch markdown
  ▼
consolidate: final LLM call (TEXT ONLY — batch summaries + chapter map)
  → single report (structure, timeline, key moments, per skill categories)
  ▼
artifacts: media/generated/vision/<slug>/{frames, summary.md,
  chapters.json, frame_metadata.jsonl, report.md}
```

- **Raw-mode scale guard:** raw extraction of a long video is huge
  (60 fps × 10 min = 36k frames). v1 rule: `mode=raw` requires
  `chunk_secs` + a frame budget (`max_frames`, default 3000) — the tool
  returns a structured error suggesting scene mode or a narrower range
  if the budget is exceeded (no silent 5 GB frame dumps).
- **GIFs:** ffmpeg decodes them as video (per-frame delay honored);
  treated as short videos (scene mode, native fps).
- **Long videos:** chunked scene mode covers every segment (the skill's
  core insight — the intro doesn't eat the frame budget).

### 3.4 Prompts

- Port the skill's analysis workflow into prompt templates:
  - `general`: describe each frame, transcribe on-screen text verbatim,
    note what changed between frames, map structure/progression.
  - `gameplay`: the skill's categories (mechanics, timing, visual design,
    UI/HUD, level design, transitions & polish).
  - `tutorial`: steps, UI actions, code/on-screen text verbatim.
- `prompt` param = free-form override appended to the template.
- Per-batch calls are stateless (timestamps passed in the prompt); the
  consolidation call sees only text (cheap, fits context).

### 3.5 LiteLLM registration

- `mcp_vision` in `litellm/config.yml`, `allow_all_keys: true` (any AI).
- MCP tool timeout: video analysis is long-running → 7200 (same as
  mcp_media/mcp_knowledge).

### 3.6 Relationship to the KB

- KB K4 (page-render vision fallback) reuses the **verified pattern**
  (batch ≤5 images, fresh call, base64 data-URLs) — a ~50-line internal
  helper in mcp_knowledge, not a dependency on mcp_vision (MCP servers
  don't call each other).
- Natural synergy for the owner: `vision_analyze_video` → LLM stores the
  report via `kb_add_fact`/`kb_ingest_file` (KB-side, later).

---

## 4. Phased plan

### A0. Spec lock + vision probe — **this doc**
- [x] Read the skill (SKILL.md + 5 scripts)
- [x] Draft tool spec (this doc)
- [ ] `vision_probe` equivalent via LiteLLM: confirm the 5-image cap,
      latency + token cost per 640px frame (numbers inform defaults)
- [ ] Owner answers Q1–Q6 (§5)

### A1. Server + images
- [ ] `mcp/servers/vision/` skeleton (Dockerfile with ffmpeg, pyproject,
      compose block in `compose.mcp.yml`)
- [ ] `vision_analyze_image` (local + URL + gif) + path/URL validation
- [ ] E2E via LiteLLM MCP (raw JSON-RPC probe): analyze a real image

### A2. Video
- [ ] `vision_analyze_video` — scene mode (single-pass + chunked) ported
      from `extract-frames.sh`/`extract-chunks.sh` (python + ffmpeg
      subprocess)
- [ ] `mode=raw` ported from `extract-raw.sh` (+ frame-budget guard)
- [ ] `vision_extract_frames`
- [ ] YouTube via yt-dlp (meta-first pattern from `fetch-youtube.sh`)
- [ ] E2E: (a) a local mp4 from media/, (b) a website mp4/mov/gif URL,
      (c) a YouTube video, (d) a gif — verify report quality + artifact
      layout + timing on a 10+ min video

### A3. Integration + handoff
- [ ] LiteLLM registration + timeout 7200
- [ ] `vision_probe` tool (ops)
- [ ] Docs: `mcp/servers/vision/README.md`, root README,
      `thor_mcp_architecture.md`, `thor_ai_inventory.md` (41 → ~45 tools)
- [ ] Commit + handoff → **KB K1 starts**

---

## 5. Questions for the owner

| # | Question | Proposal |
|---|---|---|
| Q1 | **Tool names:** `vision_analyze_image` / `vision_analyze_video` / `vision_extract_frames` / `vision_probe` — OK? | As listed |
| Q2 | **Remote URL scope:** any http(s) URL (LAN + internet), 2 GB download cap — OK? Or an allowlist of hosts? | Any http/https + cap |
| Q3 | **Artifacts:** write frames + `report.md` to `media/generated/vision/<slug>/` (publishable to the blog later via `publish_file`) — OK? | Yes |
| Q4 | **YouTube:** include yt-dlp in the image (skill already uses it)? | Yes |
| Q5 | **Raw full-FPS mode in v1?** (gameplay timing analysis — the skill's third strategy) — port now, or v2? | Port now, explicit opt-in + frame-budget guard |
| Q6 | **`focus` prompt templates:** `general` / `gameplay` / `tutorial` (from the skill's categories) — right set? | As listed |

---

## 6. Rollback & failure modes

- **Server is additive** — removing the compose block + LiteLLM entry
  reverts everything; no shared state (artifacts are just files).
- **Vision model absent/broken:** tools return a structured error;
  `vision_extract_frames` still works (no LLM needed).
- **Bad/corrupt media:** ffmpeg errors → structured error, no partial
  artifacts (temp dir cleaned).
- **Huge raw extraction:** frame-budget guard refuses before extraction.
- **Download bombs:** 2 GB stream cap + ephemeral temp dir.
- **No memory/KB interaction** — nothing to isolate from (no Qdrant, no
  mem0); the only shared resource is the LiteLLM proxy (read-only use).

---

## 7. Explicitly NOT in scope

- Audio analysis (the skill discards audio; whisper/etc. = future).
- Real-time/streaming analysis (files only).
- Video *generation* (that's mcp_media / the GPU pipeline).
- KB ingestion (mcp_knowledge's job; synergy only).
- Per-key MCP restrictions (LiteLLM Phase 14).
- The pi skill itself (stays on the laptop; the MCP tool supersedes it
  for Thor-side use — the skill stays as the reference spec).