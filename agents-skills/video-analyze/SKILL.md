---
name: video-analyze
description: >
  Extracts keyframes from video files using ffmpeg scene detection and generates
  a storyboard-style analysis. Use when you need to analyze gameplay videos, cutscenes,
  tutorials, or any video content. Three extraction strategies:
  - extract-frames.sh: Single-pass extraction (short videos < 5 min)
  - extract-chunks.sh: Chunk-based extraction for long videos (5-60+ min)
  - extract-raw.sh: Full FPS extraction for timing analysis (gameplay mechanics)
  Outputs PNG frames, frame metadata with timestamps, and summary markdown
  ready for visual analysis by LLMs.
---

# Video Analysis Skill

Extract keyframes from videos and analyze them as a storyboard. Designed for
gameplay analysis but works for any video content.

## Which Script to Use

| Video Length / Goal | Script | Why |
|-------------|--------|-----|
| < 5 min | `extract-frames.sh` | Simple single-pass is fine |
| 5-60+ min (overview) | `extract-chunks.sh` | Divides into chunks so every segment gets coverage |
| Any length (timing analysis) | `extract-raw.sh` | Full FPS extraction with precise timestamps |
| Any length (timing, integrated) | `extract-chunks.sh --raw` | Same as extract-raw.sh but using the chunk script |

## Getting the Video (YouTube)

If you only have a YouTube URL, download the video + metadata first:

```bash
./scripts/fetch-youtube.sh <url-or-video-id> [output_dir] [format]
```

- Requires `yt-dlp` (`brew install yt-dlp` or `pip3 install --user yt-dlp`); the script prints install instructions if it's missing.
- Outputs `<output_dir>/<Title>.mp4` and `<output_dir>video.meta.json` (title, description, chapters, duration).
- **Read `video.meta.json` before analyzing** — the description and chapter list tell you what the video covers and where the interesting parts are (use chapters to pick `skip_intro`/`skip_outro` or re-extraction ranges).
- The last line printed is the video path, so you can chain:
  ```bash
  VIDEO=$(./scripts/fetch-youtube.sh <url> ./analysis | tail -1)
  ./scripts/extract-chunks.sh "$VIDEO" ./analysis/frames 10 640 120 0.2
  ```

## extract-frames.sh — Single-Pass Extraction

```bash
# Extract keyframes (default: 50 max, 640px wide)
./scripts/extract-frames.sh /path/to/video.mp4

# Custom: 20 frames, smaller, higher sensitivity
./scripts/extract-frames.sh video.mp4 ./analysis 20 480 0.2
```

| Arg | Default | Description |
|-----|---------|-------------|
| `video` | *(required)* | Path to video file |
| `output_dir` | `./frames` | Output directory for PNGs + summary.md |
| `max_frames` | `50` | Maximum frames to extract |
| `scale_width` | `640` | Max frame width (height auto-scaled) |
| `scene_threshold` | `0.1` | Scene sensitivity: 0.1 (sensitive) to 1.0 (strict) |

**How it works:**
1. **Scene detection** — ffmpeg's `scene` filter detects significant pixel changes
2. **Threshold tuning** — auto-adjusts threshold to fit within `max_frames`
3. **Fallback** — uniform time-based sampling if scene detection overflows

## extract-chunks.sh — Chunk-Based Extraction (Long Videos)

For videos 5+ minutes, this divides the video into time-based chunks and
extracts frames independently per chunk. This ensures every segment gets
coverage rather than having the intro eat up your frame budget.

### Scene Mode (Default)

```bash
extract-chunks.sh <video> [output_dir] [frames_per_chunk] [scale_width] [chunk_duration] [scene_threshold] [skip_intro] [skip_outro]
```

| Arg | Default | Description |
|-----|---------|-------------|
| `video` | *(required)* | Path to video file |
| `output_dir` | `./chunks` | Output directory |
| `frames_per_chunk` | `10` | Max frames per chunk |
| `scale_width` | `640` | Frame width in px |
| `chunk_duration` | `120` | Chunk size in seconds (2 min) |
| `scene_threshold` | `0.2` | Scene sensitivity |
| `skip_intro` | `0` | Seconds to skip from start |
| `skip_outro` | `0` | Seconds to skip from end |

### Raw FPS Mode (`--raw` flag)

For frame-accurate timing analysis, prepend `--raw`:

```bash
extract-chunks.sh --raw <video> [output_dir] [fps] [scale_width] [chapter_duration] [skip_intro] [skip_outro]
```

| Arg | Default | Description |
|-----|---------|-------------|
| `video` | *(required)* | Path to video file |
| `output_dir` | `./raw-chunks` | Output directory |
| `fps` | `full` | Frame rate (or "full" = native video FPS) |
| `scale_width` | `640` | Frame width in px |
| `chapter_duration` | `10` | Seconds per chapter (default 10s) |
| `skip_intro` | `0` | Seconds to skip from start |
| `skip_outro` | `0` | Seconds to skip from end |

### How it works:

**Scene mode:**
1. Divides the video into equal-duration chunks
2. Runs scene detection independently per chunk
3. If a chunk has too many frames → falls back to uniform sampling
4. If a chunk has zero scene changes → grabs 1 frame from the midpoint
5. Produces `summary.md` with a chapter table mapping chunks → frame ranges
6. Produces `chapters.json` with machine-readable chunk metadata

**Raw FPS mode:**
1. Divides the video into equal-duration chapters
2. Extracts every frame at the specified FPS rate per chapter
3. Records precise timestamps for each frame in `frame_metadata.jsonl`
4. Produces `summary.md`, `chapters.json`, and `frame_metadata.jsonl`

**Recommended settings by video length (scene mode):**

| Video Length | Chunk Size | Frames/Chunk | Total Est. |
|-------------|-----------|-------------|------------|
| 5-10 min | 60s | 8 | 50-100 |
| 10-20 min | 120s | 10 | 50-100 |
| 20-30 min | 180s | 10 | 70-100 |
| 30-60 min | 300s | 12 | 100-144 |

**Recommended chapter sizes (raw FPS mode):**

| Extraction FPS | Chapter Size | Frames/Chapter | Notes |
|---------------|-------------|----------------|-------|
| 30fps | 10s | 300 | Good default |
| 60fps | 5s | 300 | Manageable context |
| 60fps | 10s | 600 | Larger but more complete |
| 120fps | 5s | 600 | Very detailed |

**Example — 15 min video, skipping 45s intro and 30s outro (scene mode):**
```bash
extract-chunks.sh gameplay.mp4 ./analysis 10 640 120 0.2 45 30
# 15 min = 900s, minus 45+30 = 825s effective
# 825s / 120s per chunk = 7 chunks × 10 frames = ~70 frames total
```

**Example — 3 min gameplay segment at full FPS (raw mode):**
```bash
extract-chunks.sh --raw gameplay.mp4 ./raw-frames full 640 10 30 15
# 3 min = 180s, minus 30+15 = 135s effective
# 135s / 10s per chapter = ~14 chapters
# At 60fps: ~14 × 600 = ~8400 frames total
# Analyze one chapter (600 frames) at a time
```

## extract-raw.sh — Full FPS Extraction with Chapters

Dedicated script for frame-accurate gameplay timing analysis. Automatically
divides output into chapter subdirectories for manageable analysis batches.

```bash
extract-raw.sh <video> [output_dir] [fps] [scale_width] [chapter_duration] [skip_intro] [skip_outro]
```

| Arg | Default | Description |
|-----|---------|-------------|
| `video` | *(required)* | Path to video file |
| `output_dir` | `./raw-frames` | Output directory |
| `fps` | `full` | Frame rate (or "full" = native video FPS) |
| `scale_width` | `640` | Max frame width (height auto-scaled) |
| `chapter_duration` | `10` | Seconds per chapter (default 10s) |
| `skip_intro` | `0` | Seconds to skip from start |
| `skip_outro` | `0` | Seconds to skip from end |

**Output structure:**
```
output_dir/
├── summary.md              # Overview with chapter table
├── chapters.json           # Machine-readable chapter map
├── frame_metadata.jsonl    # Per-frame timestamps (one JSON per line)
├── frame_0001.png          # All frames in global sequential order
├── frame_0002.png
├── ...
└── chapters/
    ├── chapter_01/         # Frames for chapter 1 only
    │   ├── frame_0001.png
    │   └── ...
    ├── chapter_02/
    └── ...
```

**Example — Depth Charge gameplay timing analysis:**
```bash
# Full FPS, 5-second chapters, skip title screen
extract-raw.sh depth-charge.mp4 ./depth-raw full 640 5 10

# 30fps capped, 10-second chapters
extract-raw.sh depth-charge.mp4 ./depth-30 30 640 10 10
```

## Image Limits and Model Probing (read before analyzing frames)

**Models cap images per API request, and the cap is on the WHOLE conversation.**
Every request carries the full history, so an agent that reads images one at a
time has a budget of N images *total for its session* (turns accumulate). The
(N+1)-th image read fails with:

```
400 ... "At most K image(s) may be provided in one prompt."
```

**Known limits (probe to verify — they change with model/provider):**

| Model | Limit | Probed |
|-------|-------|--------|
| `litellm/matrix-coder` | **5 images per session** | 2026-08-27 |

**Probe before a big analysis** (one cheap API call, reads endpoint/key from
`~/.pi/agent/models.json`, sends N tiny test images, parses K from the error):

```bash
./scripts/probe-image-limit.sh            # uses $PI_MODEL / $PI_PROVIDER
./scripts/probe-image-limit.sh --n 24     # probe with more images
```

Output: `LIMIT: matrix-coder accepts at most 5 images per request` (or
`OK: ... limit >= N` if the probe size was under the cap).

**Rules:**
1. Batch frame reads into groups of ≤ K frames (K = probed limit; 5 for matrix-coder).
2. Within a batch, read frames **one at a time** (single read call per turn) —
   never batch multiple image reads in one turn.
3. Don't re-read frames or read any extra images in the same session — every
   image counts against the same budget.
4. If a session must cover more than K frames, use a **new session** (new
   subagent) for the next batch.

## Analysis Workflow

### With extract-raw.sh (timing analysis)

1. **Run the extractor** with FPS and chapter size appropriate for your needs
2. **Read `summary.md`** — the chapter table tells you which frames belong to which chapter
3. **Read `frame_metadata.jsonl`** — precise timestamps for every frame
4. **Pick a chapter to analyze** — read frames from `chapters/chapter_NN/` in order
5. **For each frame, note what changed** from the previous frame:
   - Sprite animation state changes
   - UI updates (health bars, score, indicators)
   - Projectile movement, enemy behavior
6. **Count frames between events** for timing analysis:
   - "Player fires at frame 45, projectile appears at frame 46 = 1 frame delay"
   - "Hit animation starts at frame 100, ends at frame 108 = 8 frame animation"
7. **Compare across chapters** to verify consistent timing

### With extract-chunks.sh (recommended for long videos)

1. **Run the extractor** with appropriate chunk size and skip values
2. **Read `summary.md`** — the chapter table tells you which frames belong to which chunk
3. **Pick a chunk to analyze** — read frames from that chunk's range in order
4. **Describe what you see** in each frame:
   - Gameplay action, UI elements, player state, enemy behavior
   - Level layout, visual style, camera/scrolling behavior
5. **Compare across chunks** to track progression, difficulty curves, new mechanics
6. **For interesting segments**, re-run with smaller chunks or higher frame counts:
   ```bash
   # Focus on minutes 5-8 with finer granularity
   extract-chunks.sh gameplay.mp4 ./deep-dive 15 640 60 0.1 300 30
   ```

### With extract-frames.sh (simple videos)

1. Run the extractor and read `summary.md`
2. Read frames in order (frame_0001.png through frame_NNNN.png)
3. Map the video's structure: where levels start, boss fights, transitions
4. For deep dives on specific segments, use ffmpeg to clip then re-extract:
   ```bash
   ffmpeg -i gameplay.mp4 -ss 00:05:30 -t 00:04:00 -c copy boss-clip.mp4
   ./scripts/extract-frames.sh boss-clip.mp4 ./boss-analysis 25 768 0.2
   ```

### With many frames: subagent batches (20+ frames)

When the total frame count exceeds one image budget (see Image Limits above),
delegate per-batch analysis to subagents — each child gets its own fresh image
budget. Proven pattern (used for a 55-frame product video, 5-image model):

1. **Probe the limit first:** `./scripts/probe-image-limit.sh`
   (e.g. `matrix-coder: at most 5 images`).
2. **Batch frames** into groups of ≤ limit (5 for matrix-coder): frames 1-5,
   6-10, 11-15, ...
3. **One subagent per batch** (run them in parallel). The task must say:
   - read the batch's frames **one at a time** (single read call per turn),
   - transcribe all on-screen text/subtitles verbatim,
   - **write** the per-frame analysis to `analysis-batch-N.md` (the file is
     the deliverable — instruct it to write the file before its final reply),
   - return a compact 5-15 line summary.
4. **Verify files on disk, not run status.** A child can be reported
   *failed* because its final response turn hit the image limit, even though
   it already wrote a complete analysis file. Check each
   `analysis-batch-N.md` for the expected frame count; re-run only the
   batches with missing/incomplete files.
5. **The parent reads only the text files** (cheap) and consolidates into a
   single analysis + downstream deliverable (e.g. a PRD). The parent should
   avoid reading frames itself except a few spot-checks (1-2 frames).

## Frame Count Reference (for timing analysis)

| Duration | @ 30fps | @ 60fps | @ 120fps |
|----------|---------|---------|----------|
| 0.1s | 3 frames | 6 frames | 12 frames |
| 0.25s | 8 frames | 15 frames | 30 frames |
| 0.5s | 15 frames | 30 frames | 60 frames |
| 1s | 30 frames | 60 frames | 120 frames |
| 2s | 60 frames | 120 frames | 240 frames |
| 5s | 150 frames | 300 frames | 600 frames |

## Analysis Categories for Games

When analyzing gameplay frames, structure your analysis around:

### Mechanics
- Core input/response loop (what does the player do → what happens)
- Combo/system depth
- Win/loss conditions
- Risk/reward patterns

### Timing (raw FPS mode)
- Frame-accurate input delay measurement
- Animation frame counts and timing
- Projectile speed (frames per screen-width)
- Cooldown/invincibility frame counts
- Attack windows: windup + active + recovery frames

### Visual Design
- Art style and palette
- Screen composition and focal points
- Visual clarity (can the player quickly understand the situation?)
- Feedback (hit flashes, damage numbers, sound visualization)

### UI/HUD
- Information displayed (health, score, time, lives, etc.)
- Screen real estate used by UI vs gameplay
- Menu/navigation flow
- Onboarding/tutorial elements

### Level Design
- Pacing and difficulty curve
- Enemy placement and variety
- Environmental hazards
- Reward placement and spacing

### Transitions & Polish
- Scene transitions (fade, cut, scroll)
- Loading screens
- Start/end screens
- Visual/audio polish and consistency

## Tips

- **For fast action:** Use lower thresholds (0.1-0.2) to capture more moments
- **For cutscenes/narrative:** Use higher thresholds (0.4-0.6) — fewer frames needed
- **For timing analysis:** Use `extract-raw.sh` or `extract-chunks.sh --raw`
- **Skip intros/outros:** Use `skip_intro`/`skip_outro` to avoid wasting frame budget
- **Frame resolution:** 640px wide is a good balance of detail vs context tokens
- **Batch size:** Read ≤ 5 frames per agent session (see Image Limits and Model Probing)
- **YouTube:** download with `scripts/fetch-youtube.sh` before extracting
- **Chapter size for raw mode:** 5-10s chapters give 300-600 frames @ 60fps per batch
- **Timestamps are estimates:** Frame positions are approximations based on total duration
- **For raw mode:** Use `frame_metadata.jsonl` for precise per-frame timestamps

## Limitations

- **Temporal info is approximate:** Frames are static snapshots; exact timing
  between events requires the original video (raw mode improves this)
- **Motion is lost:** Animations, particle effects, and timing can't be fully
  captured from still frames (mitigated by raw FPS extraction)
- **Context window:** Many frames will use significant context tokens —
  analyze in focused batches, not all at once (use chapters for raw mode).
  Models also cap images per request (e.g. 5 for litellm/matrix-coder) and the
  cap is per whole conversation — see Image Limits and Model Probing and use
  `scripts/probe-image-limit.sh` to check the current model's cap.
- **Audio is discarded:** Sound design, music, and audio cues aren't captured
- **Scene detection isn't perfect:** Very subtle transitions may be missed;
  very noisy videos may trigger false positives