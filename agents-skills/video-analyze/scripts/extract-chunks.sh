#!/usr/bin/env bash
# extract-chunks.sh — Chunk-based keyframe extraction for long gameplay videos
#
# Divides a video into time-based chunks, extracts scene-detected frames from
# each chunk independently, and produces a structured summary with per-chapter
# frame lists. Ideal for 10-60 min gameplay videos.
#
# Two extraction modes:
#   Scene mode (default): scene detection to find key frames
#   Raw/FPS mode: extract at a specified frame rate for timing analysis
#
# Usage:
#   Scene mode:
#     extract-chunks.sh <video> [output_dir] [frames_per_chunk] [scale_width] [chunk_duration] [scene_threshold] [skip_intro] [skip_outro]
#   Raw FPS mode:
#     extract-chunks.sh --raw <video> [output_dir] [fps] [scale_width] [chapter_duration] [skip_intro] [skip_outro]
#
# Scene Mode Args:
#   video             — Path to the video file (required)
#   output_dir        — Where to write frames + summary.md (default: ./chunks)
#   frames_per_chunk  — Max frames per chunk (default: 10)
#   scale_width       — Max frame width in px (default: 640)
#   chunk_duration    — Duration of each chunk in seconds (default: 120 = 2min)
#   scene_threshold   — Scene change sensitivity 0.1-1.0 (default: 0.2)
#   skip_intro        — Seconds to skip from start (default: 0)
#   skip_outro       — Seconds to skip from end (default: 0)
#
# Raw FPS Mode Args (after --raw):
#   video             — Path to the video file (required)
#   output_dir        — Where to write frames + summary.md (default: ./raw-chunks)
#   fps               — Frame rate (default: "full" = native video FPS)
#   scale_width       — Max frame width in px (default: 640)
#   chapter_duration  — Seconds per chapter (default: 10s)
#   skip_intro        — Seconds to skip from start (default: 0)
#   skip_outro       — Seconds to skip from end (default: 0)

set -uo pipefail

# ── detect mode ─────────────────────────────────────────────────────────
RAW_MODE=false
if [[ "${1:-}" == "--raw" ]]; then
  RAW_MODE=true
  shift
fi

if [[ "$RAW_MODE" == true ]]; then
  VIDEO="${1:?Usage: extract-chunks.sh --raw <video> [output_dir] [fps] [scale_width] [chapter_duration] [skip_intro] [skip_outro]}"
  OUT_DIR="${2:-./raw-chunks}"
  EXTRACT_FPS="${3:-full}"
  SCALE_W="${4:-640}"
  CHUNK_SECS="${5:-10}"
  SKIP_INTRO="${6:-0}"
  SKIP_OUTRO="${7:-0}"
  FRAMES_PER_CHUNK=999999  # no cap in raw mode
  SCENE_THRESH=0           # unused in raw mode
else
  VIDEO="${1:?Usage: extract-chunks.sh <video> [output_dir] [frames_per_chunk] [scale_width] [chunk_duration] [threshold] [skip_intro] [skip_outro]}"
  OUT_DIR="${2:-./chunks}"
  FRAMES_PER_CHUNK="${3:-10}"
  SCALE_W="${4:-640}"
  CHUNK_SECS="${5:-120}"
  SCENE_THRESH="${6:-0.2}"
  SKIP_INTRO="${7:-0}"
  SKIP_OUTRO="${8:-0}"
  EXTRACT_FPS="full"
fi

if [[ ! -f "$VIDEO" ]]; then
  echo "Error: file not found: $VIDEO" >&2
  exit 1
fi

# ── resolve ffmpeg ────────────────────────────────────────────────────
FFMPEG=""
for candidate in ~/bin/ffmpeg /usr/local/bin/ffmpeg /opt/homebrew/bin/ffmpeg; do
  if [[ -x "$candidate" ]]; then
    FFMPEG="$candidate"
    break
  fi
done
if [[ -z "$FFMPEG" ]]; then
  FFMPEG=$(command -v ffmpeg 2>/dev/null || true)
fi
if [[ -z "$FFMPEG" || ! -x "$FFMPEG" ]]; then
  echo "Error: ffmpeg not found. Install with: brew install ffmpeg" >&2
  exit 1
fi

# ── prepare output ────────────────────────────────────────────────────
rm -f "$OUT_DIR"/frame_*.png 2>/dev/null || true
rm -f "$OUT_DIR"/chapters.json 2>/dev/null || true
rm -f "$OUT_DIR"/summary.md 2>/dev/null || true
rm -f "$OUT_DIR"/frame_metadata.jsonl 2>/dev/null || true
mkdir -p "$OUT_DIR"

# ── get video metadata ─────────────────────────────────────────────────
VIDEO_INFO=$($FFMPEG -i "$VIDEO" -f null - 2>&1)
DURATION=$(echo "$VIDEO_INFO" | grep -oE 'Duration: [^,]+' | sed 's/Duration: //' | head -1 || echo "unknown")
IFS=: read -r h m s <<< "$DURATION"
S_INT=${s%%.*}
TOTAL_SECS=$(( 10#${h:-0} * 3600 + 10#${m:-0} * 60 + 10#${S_INT:-0} ))

# Get native FPS
NATIVE_FPS=$(echo "$VIDEO_INFO" | grep -oE '[0-9]+(\.[0-9]+)? fps' | head -1 | grep -oE '[0-9]+(\.[0-9]+)?' || echo "30")

# Determine actual extraction FPS (only used in raw mode)
if [[ "$RAW_MODE" == true && "$EXTRACT_FPS" == "full" ]]; then
  ACTUAL_FPS="$NATIVE_FPS"
else
  ACTUAL_FPS="$EXTRACT_FPS"
fi

# Effective range after skip
START_SECS=$SKIP_INTRO
END_SECS=$(( TOTAL_SECS - SKIP_OUTRO ))
EFFECTIVE_SECS=$(( END_SECS - START_SECS ))

if (( EFFECTIVE_SECS <= 0 )); then
  echo "Error: skip values exceed video duration (${TOTAL_SECS}s)" >&2
  exit 1
fi

echo "Video: $(basename "$VIDEO")"
echo "Duration: $DURATION (${TOTAL_SECS}s)"
echo "Effective range: ${START_SECS}s - ${END_SECS}s (${EFFECTIVE_SECS}s)"
if [[ "$RAW_MODE" == true ]]; then
  echo "Mode: Raw FPS | Native: $NATIVE_FPS fps | Extract: $ACTUAL_FPS fps"
  echo "Chunk size: ${CHUNK_SECS}s | ~$(( ACTUAL_FPS * CHUNK_SECS )) frames/chunk"
else
  echo "Mode: Scene detection | Threshold: $SCENE_THRESH"
  echo "Chunk size: ${CHUNK_SECS}s | Max frames/chunk: $FRAMES_PER_CHUNK"
fi

# ── calculate chunks ──────────────────────────────────────────────────
NUM_CHUNKS=$(( (EFFECTIVE_SECS + CHUNK_SECS - 1) / CHUNK_SECS ))
echo "Chunks: $NUM_CHUNKS"
echo ""

# ── per-chunk extraction ───────────────────────────────────────────────
TEMP_DIR=$(mktemp -d)
trap 'rm -rf "$TEMP_DIR"' EXIT

FRAME_OFFSET=0
CHAPTER_FILE="$OUT_DIR/chapters.json"
echo "[" > "$CHAPTER_FILE"
FIRST_CHAPTER=true

for (( c=0; c<NUM_CHUNKS; c++ )); do
  CHUNK_START=$(( START_SECS + c * CHUNK_SECS ))
  CHUNK_END=$(( CHUNK_START + CHUNK_SECS ))
  if (( CHUNK_END > END_SECS )); then
    CHUNK_END=$END_SECS
  fi
  CHUNK_LEN=$(( CHUNK_END - CHUNK_START ))

  # Format start time as HH:MM:SS
  CH=$(( CHUNK_START / 3600 ))
  CM=$(( (CHUNK_START % 3600) / 60 ))
  CS=$(( CHUNK_START % 60 ))
  CE=$(( CHUNK_END / 3600 ))
  CEM=$(( (CHUNK_END % 3600) / 60 ))
  CES=$(( CHUNK_END % 60 ))
  LABEL=$(printf "Chunk %d: %02d:%02d:%02d - %02d:%02d:%02d" $((c+1)) "$CH" "$CM" "$CS" "$CE" "$CEM" "$CES")

  echo "--- $LABEL (${CHUNK_LEN}s) ---"

  CHUNK_DIR="$TEMP_DIR/chunk_$c"
  mkdir -p "$CHUNK_DIR"

  # NOTE: -ss AFTER -i for frame-accurate seeking (slower but correct)
  if [[ "$RAW_MODE" == true ]]; then
    # Raw FPS mode: extract at exact frame rate
    $FFMPEG -ss "$CHUNK_START" -i "$VIDEO" -t "$CHUNK_LEN" -an \
      -vf "fps=${ACTUAL_FPS},scale=${SCALE_W}:-1:flags=lanczos,format=yuv420p" \
      -fps_mode cfr -q:v 2 "$CHUNK_DIR/frame_%04d.png" 2>/dev/null || true
  else
    # Scene detection mode
    $FFMPEG -i "$VIDEO" -ss "$CHUNK_START" -t "$CHUNK_LEN" -an \
      -vf "select='gt(scene,$SCENE_THRESH)+eq(n,0)',scale=${SCALE_W}:-1:flags=lanczos" \
      -fps_mode vfr -q:v 2 "$CHUNK_DIR/frame_%04d.png" 2>/dev/null || true
  fi

  COUNT=0
  for f in "$CHUNK_DIR"/frame_*.png; do
    [[ -f "$f" ]] || continue
    COUNT=$((COUNT + 1))
  done

  # If too many frames for this chunk, do uniform sampling fallback (scene mode only)
  if [[ "$RAW_MODE" == false ]] && (( COUNT > FRAMES_PER_CHUNK )); then
    echo "  Too many frames ($COUNT > $FRAMES_PER_CHUNK). Re-sampling uniformly..."
    rm -f "$CHUNK_DIR"/frame_*.png
    INTERVAL=$(awk "BEGIN {printf \"%.2f\", $CHUNK_LEN / $FRAMES_PER_CHUNK}")
    $FFMPEG -i "$VIDEO" -ss "$CHUNK_START" -t "$CHUNK_LEN" -an \
      -vf "fps=1/${INTERVAL},scale=${SCALE_W}:-1:flags=lanczos" \
      -fps_mode vfr -q:v 2 "$CHUNK_DIR/frame_%04d.png" 2>/dev/null || true
    COUNT=0
    for f in "$CHUNK_DIR"/frame_*.png; do
      [[ -f "$f" ]] || continue
      COUNT=$((COUNT + 1))
    done
  fi

  # Fallback: if scene detection found nothing, grab 1 frame from the middle (scene mode only)
  if [[ "$RAW_MODE" == false ]] && (( COUNT == 0 )); then
    MID_SECS=$(( CHUNK_LEN / 2 ))
    echo "  No scene changes detected. Grabbing 1 frame from midpoint..."
    $FFMPEG -i "$VIDEO" -ss "$((CHUNK_START + MID_SECS))" -an \
      -vf "scale=${SCALE_W}:-1:flags=lanczos" \
      -frames:v 1 -q:v 2 "$CHUNK_DIR/frame_0001.png" 2>/dev/null || true
    for f in "$CHUNK_DIR"/frame_*.png; do
      [[ -f "$f" ]] || continue
      COUNT=$((COUNT + 1))
    done
  fi

# Record first frame number before copying (1-indexed)
  if (( COUNT > 0 )); then
    FIRST_FRAME=$((FRAME_OFFSET + 1))
  else
    FIRST_FRAME=0
  fi

  if [[ "$RAW_MODE" == true ]]; then
    echo "  Extracted $COUNT frames @ ${ACTUAL_FPS}fps (global: $FIRST_FRAME–$FRAME_OFFSET)"
  else
    echo "  Extracted $COUNT frames"
  fi

  # Copy to output with global numbering
  for f in "$CHUNK_DIR"/frame_*.png; do
    [[ -f "$f" ]] || continue
    FRAME_OFFSET=$((FRAME_OFFSET + 1))
    GLOBAL_NUM=$(printf "%04d" $FRAME_OFFSET)
    cp "$f" "$OUT_DIR/frame_${GLOBAL_NUM}.png"

    # In raw mode, write per-frame timestamp metadata
    if [[ "$RAW_MODE" == true ]]; then
      LOCAL_IDX=$(( FRAME_OFFSET - FIRST_FRAME ))
      ABS_TIME=$(awk "BEGIN {printf \"%.3f\", $CHUNK_START + $LOCAL_IDX / $ACTUAL_FPS}")
      printf '{"frame": %d, "chunk": %d, "timestamp": %.3f, "file": "frame_%04d.png"}\n' \
        "$FRAME_OFFSET" "$((c+1))" "$ABS_TIME" "$FRAME_OFFSET" >> "$OUT_DIR/frame_metadata.jsonl"
    fi
  done

  LAST_FRAME=$FRAME_OFFSET

  # Write chapter JSON entry
  if [ "$FIRST_CHAPTER" = true ]; then
    FIRST_CHAPTER=false
  else
    echo "," >> "$CHAPTER_FILE"
  fi
  printf '  {"chunk": %d, "start": %d, "end": %d, "frames": %d, "first_frame": %d, "last_frame": %d}' \
    $((c+1)) "$CHUNK_START" "$CHUNK_END" "$COUNT" "$FIRST_FRAME" "$LAST_FRAME" >> "$CHAPTER_FILE"
done

echo "" >> "$CHAPTER_FILE"
echo "]" >> "$CHAPTER_FILE"

TOTAL_EXTRACTED=$FRAME_OFFSET

# ── generate summary ────────────────────────────────────────────────────
SUMMARY="$OUT_DIR/summary.md"

cat > "$SUMMARY" << EOSUM
# Video Analysis: $(basename "$VIDEO")
$(if [[ "$RAW_MODE" == true ]]; then echo "— Raw FPS Extraction"; else echo "— Chunk-Based Extraction"; fi)

**Source:** $VIDEO
**Duration:** $DURATION (${TOTAL_SECS}s)
**Effective range:** ${START_SECS}s - ${END_SECS}s (${EFFECTIVE_SECS}s)
$(if [[ "$RAW_MODE" == true ]]; then echo "**Native FPS:** $NATIVE_FPS | **Extraction FPS:** $ACTUAL_FPS"; else echo "**Scene threshold:** $SCENE_THRESH"; fi)
**Chunk size:** ${CHUNK_SECS}s | **Chunks:** $NUM_CHUNKS
$(if [[ "$RAW_MODE" == true ]]; then echo "**Total frames extracted:** $TOTAL_EXTRACTED"; else echo "**Max frames per chunk:** $FRAMES_PER_CHUNK | **Total extracted:** $TOTAL_EXTRACTED"; fi)
**Frame size:** ${SCALE_W}px wide
$(if [[ "$RAW_MODE" == true ]]; then echo "**Frame metadata:** frame_metadata.jsonl (timestamp per frame)"; fi)

## Chapters

| Chunk | Time Range | Frames | Frame IDs |
|-------|-----------|--------|-----------|
EOSUM

for (( c=0; c<NUM_CHUNKS; c++ )); do
  CHUNK_START=$(( START_SECS + c * CHUNK_SECS ))
  CHUNK_END=$(( CHUNK_START + CHUNK_SECS ))
  if (( CHUNK_END > END_SECS )); then CHUNK_END=$END_SECS; fi

  CH=$(( CHUNK_START / 3600 ))
  CM=$(( (CHUNK_START % 3600) / 60 ))
  CS=$(( CHUNK_START % 60 ))
  CE=$(( CHUNK_END / 3600 ))
  CEM=$(( (CHUNK_END % 3600) / 60 ))
  CES=$(( CHUNK_END % 60 ))
  TIME_RANGE=$(printf "%02d:%02d:%02d - %02d:%02d:%02d" "$CH" "$CM" "$CS" "$CE" "$CEM" "$CES")

  # Parse chapter info from JSON
  CHUNK_JSON=$(awk -v c=$((c+1)) "/\"chunk\": $((c+1))/" "$CHAPTER_FILE")
  C_COUNT=$(echo "$CHUNK_JSON" | grep -oE '"frames": [0-9]+' | grep -oE '[0-9]+')
  C_FIRST=$(echo "$CHUNK_JSON" | grep -oE '"first_frame": [0-9]+' | grep -oE '[0-9]+')
  C_LAST=$(echo "$CHUNK_JSON" | grep -oE '"last_frame": [0-9]+' | grep -oE '[0-9]+')

  if (( C_COUNT > 0 )); then
    FRAME_IDS=$(printf "frame_%04d.png – frame_%04d.png" "$C_FIRST" "$C_LAST")
  else
    FRAME_IDS="(none)"
  fi

  printf "| %d | %s | %d | %s |\n" "$((c+1))" "$TIME_RANGE" "$C_COUNT" "$FRAME_IDS" >> "$SUMMARY"
done

cat >> "$SUMMARY" << 'EOF'

---

## How to Analyze by Chunk

### Scene Mode (Default)

1. **Scan the chapter table above** to understand the video structure
2. **Pick a chunk** — read frames from one chunk at a time
3. **Describe what you see** in each frame:
   - Gameplay action, UI elements, player state, enemy behavior
   - Level layout, visual style, camera/scrolling behavior
4. **Compare across chunks** to track progression, difficulty curves, new mechanics

### Raw FPS Mode

1. **Each frame has a precise timestamp** — see `frame_metadata.jsonl`
2. **Read one chunk at a time** — count frames between events for timing
3. **Frame-accurate timing analysis:**
   - Input delay: count frames from action to visual response
   - Animation length: count frames from start to end of animation
   - Projectile speed: count frames to cross screen width
   - Cooldown timing: count frames between consecutive uses

| Duration | @ 30fps | @ 60fps |
|----------|---------|---------|
| 0.1s | 3 frames | 6 frames |
| 0.25s | 8 frames | 15 frames |
| 0.5s | 15 frames | 30 frames |
| 1s | 30 frames | 60 frames |
| 2s | 60 frames | 120 frames |

## Analysis Strategy

| Pass | Purpose | Method |
|------|---------|--------|
| 1 — Structure | Map video segments | Read first frame of each chunk |
| 2 — Deep Dive | Analyze gameplay in detail | Read all frames in 1-2 chunks |
| 3 — Patterns | Cross-reference mechanics | Compare specific frames across chunks |

## Recommended Settings by Video Length

| Video Length | Chunk Size | Frames/Chunk | Total Est. |
|-------------|-----------|-------------|------------|
| 5-10 min | 60s | 8 | 50-100 |
| 10-20 min | 120s | 10 | 50-100 |
| 20-30 min | 180s | 10 | 70-100 |
| 30-60 min | 300s | 12 | 100-144 |

## Re-extract a Specific Chunk

To get higher detail in a specific segment, re-run with smaller chunks:

```bash
# Focus on minutes 5-8 with smaller chunks and more frames
extract-chunks.sh video.mp4 ./detail 15 640 60 0.1 300 0
```
EOF

echo ""
echo "Done! Output in: $OUT_DIR/"
if [[ "$RAW_MODE" == true ]]; then
  echo "  Frames: $TOTAL_EXTRACTED PNGs across $NUM_CHUNKS chunks @ ${ACTUAL_FPS}fps"
  echo "  Summary: $SUMMARY"
  echo "  Chapter map: $CHAPTER_FILE"
  echo "  Frame metadata: $OUT_DIR/frame_metadata.jsonl"
else
  echo "  Frames: $TOTAL_EXTRACTED PNGs across $NUM_CHUNKS chunks"
  echo "  Summary: $SUMMARY"
  echo "  Chapter map: $CHAPTER_FILE"
fi
echo ""
echo "Next: read $SUMMARY and analyze frames chunk-by-chunk"