#!/usr/bin/env bash
# extract-raw.sh — Full FPS frame extraction with automatic chapter splitting
#
# Extracts frames at the specified (or native) frame rate for detailed gameplay
# analysis. Automatically divides output into time-based chapters to manage
# context window size. Each frame includes an accurate timestamp.
#
# Ideal for:
# - Fast-paced gameplay where timing matters (shooters, rhythm games, fighting)
# - Analyzing frame-accurate response timing and animation sequences
# - Understanding projectile trajectories, hitboxes, frame data
#
# Usage:
#   extract-raw.sh <video> [output_dir] [fps] [scale_width] [chapter_duration] [skip_intro] [skip_outro]
#
# Args:
#   video            — Path to the video file (required)
#   output_dir       — Where to write frames + summary.md (default: ./raw-frames)
#   fps              — Extraction rate (default: "full" = native video FPS;
#                     set a number like 30 or 60 to cap extraction)
#   scale_width      — Max frame width in px; height auto-scaled (default: 640)
#   chapter_duration — Seconds per chapter/chunk (default: 10s)
#                     For 60fps, 10s = 600 frames/chapter. Adjust based on
#                     context budget: 5s = 300 frames @ 60fps, 15s = 900 frames @ 60fps
#   skip_intro       — Seconds to skip from start (default: 0)
#   skip_outro      — Seconds to skip from end (default: 0)

set -euo pipefail

# ── args ────────────────────────────────────────────────────────────────
VIDEO="${1:?Usage: extract-raw.sh <video> [output_dir] [fps] [scale_width] [chapter_duration] [skip_intro] [skip_outro]}"
OUT_DIR="${2:-./raw-frames}"
EXTRACT_FPS="${3:-full}"
SCALE_W="${4:-640}"
CHAPTER_SECS="${5:-10}"
SKIP_INTRO="${6:-0}"
SKIP_OUTRO="${7:-0}"

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
rm -f "$OUT_DIR"/summary.md 2>/dev/null || true
rm -f "$OUT_DIR"/chapters.json 2>/dev/null || true
rm -f "$OUT_DIR"/frame_metadata.jsonl 2>/dev/null || true
rm -rf "$OUT_DIR"/chapters 2>/dev/null || true
mkdir -p "$OUT_DIR/chapters"

# ── get video metadata ─────────────────────────────────────────────────
VIDEO_INFO=$($FFMPEG -i "$VIDEO" -f null - 2>&1)
DURATION=$(echo "$VIDEO_INFO" | grep -oE 'Duration: [^,]+' | sed 's/Duration: //' | head -1 || echo "unknown")
IFS=: read -r h m s <<< "$DURATION"
S_INT=${s%%.*}
TOTAL_SECS=$(( 10#${h:-0} * 3600 + 10#${m:-0} * 60 + 10#${S_INT:-0} ))

# Get native FPS from video stream
NATIVE_FPS=$(echo "$VIDEO_INFO" | grep -oE '[0-9]+(\.[0-9]+)? fps' | head -1 | grep -oE '[0-9]+(\.[0-9]+)?' || echo "30")

# Determine actual extraction FPS
if [[ "$EXTRACT_FPS" == "full" ]]; then
  ACTUAL_FPS="$NATIVE_FPS"
else
  ACTUAL_FPS="$EXTRACT_FPS"
fi

# Calculate effective range
START_SECS=$SKIP_INTRO
END_SECS=$(( TOTAL_SECS - SKIP_OUTRO ))
EFFECTIVE_SECS=$(( END_SECS - START_SECS ))

if (( EFFECTIVE_SECS <= 0 )); then
  echo "Error: skip values exceed video duration (${TOTAL_SECS}s)" >&2
  exit 1
fi

# ── calculate chapters ──────────────────────────────────────────────────
NUM_CHAPTERS=$(( (EFFECTIVE_SECS + CHAPTER_SECS - 1) / CHAPTER_SECS ))
EST_FRAMES_PER_CHAPTER=$(awk "BEGIN {printf \"%d\", $ACTUAL_FPS * $CHAPTER_SECS}")
EST_TOTAL_FRAMES=$(awk "BEGIN {printf \"%d\", $ACTUAL_FPS * $EFFECTIVE_SECS}")

echo "=== Raw FPS Extraction ==="
echo "Video: $(basename "$VIDEO")"
echo "Duration: $DURATION (${TOTAL_SECS}s)"
echo "Native FPS: $NATIVE_FPS | Extraction FPS: $ACTUAL_FPS"
echo "Effective range: ${START_SECS}s - ${END_SECS}s (${EFFECTIVE_SECS}s)"
echo "Chapter size: ${CHAPTER_SECS}s (~${EST_FRAMES_PER_CHAPTER} frames/chapter @ ${ACTUAL_FPS}fps)"
echo "Chapters: $NUM_CHAPTERS"
echo "Estimated total frames: ~${EST_TOTAL_FRAMES}"
echo ""

# Warning if large extraction
if (( EST_TOTAL_FRAMES > 2000 )); then
  echo "⚠ Large extraction (~${EST_TOTAL_FRAMES} frames). This will take time and produce many files."
  echo "  Consider:"
  echo "  - Reducing chapter_duration for smaller analysis chunks"
  echo "  - Using lower FPS (e.g., 30 instead of 60)"
  echo "  - Skipping intro/outro with skip_intro/skip_outro"
  echo ""
fi

# ── per-chapter extraction ─────────────────────────────────────────────
TEMP_DIR=$(mktemp -d)
trap 'rm -rf "$TEMP_DIR"' EXIT

GLOBAL_FRAME_NUM=0
CHAPTER_FILE="$OUT_DIR/chapters.json"
FRAME_META="$OUT_DIR/frame_metadata.jsonl"

echo "[" > "$CHAPTER_FILE"
> "$FRAME_META"
FIRST_CHAPTER=true

for (( ch=0; ch<NUM_CHAPTERS; ch++ )); do
  CH_START=$(( START_SECS + ch * CHAPTER_SECS ))
  CH_END=$(( CH_START + CHAPTER_SECS ))
  if (( CH_END > END_SECS )); then
    CH_END=$END_SECS
  fi
  CH_LEN=$(( CH_END - CH_START ))

  # Format time labels
  CH_H=$(( CH_START / 3600 ))
  CH_M=$(( (CH_START % 3600) / 60 ))
  CH_S=$(( CH_START % 60 ))
  CE_H=$(( CH_END / 3600 ))
  CE_M=$(( (CH_END % 3600) / 60 ))
  CE_S=$(( CH_END % 60 ))
  LABEL=$(printf "Chapter %d: %02d:%02d:%02d - %02d:%02d:%02d" $((ch+1)) "$CH_H" "$CH_M" "$CH_S" "$CE_H" "$CE_M" "$CE_S")

  echo "--- $LABEL (${CH_LEN}s) ---"

  CH_DIR="$TEMP_DIR/ch_$ch"
  mkdir -p "$CH_DIR" "$OUT_DIR/chapters/chapter_$(printf '%02d' $((ch+1)))"

  # Extract at specified FPS with frame-accurate timestamps using metadata
  # Use -ss before -i for faster seeking, then fps filter for extraction
  $FFMPEG -ss "$CH_START" -i "$VIDEO" -t "$CH_LEN" -an \
    -vf "fps=${ACTUAL_FPS},scale=${SCALE_W}:-1:flags=lanczos,format=yuv420p" \
    -q:v 2 "$CH_DIR/frame_%04d.png" 2>/dev/null || true

  COUNT=0
  for f in "$CH_DIR"/frame_*.png; do
    [[ -f "$f" ]] || continue
    COUNT=$((COUNT + 1))
  done

  # Record first frame number before copying
  if (( COUNT > 0 )); then
    FIRST_FRAME=$((GLOBAL_FRAME_NUM + 1))
  else
    FIRST_FRAME=0
  fi

  # Copy to output with global numbering + write per-chapter copies
  for f in "$CH_DIR"/frame_*.png; do
    [[ -f "$f" ]] || continue
    GLOBAL_FRAME_NUM=$((GLOBAL_FRAME_NUM + 1))
    GLOBAL_NUM=$(printf "%04d" $GLOBAL_FRAME_NUM)

    # Estimate actual timestamp for this frame
    # Frame offset within chapter (0-indexed)
    LOCAL_IDX=$(( GLOBAL_FRAME_NUM - FIRST_FRAME ))
    # Time offset from chapter start
    TIME_OFFSET=$(awk "BEGIN {printf \"%.3f\", $LOCAL_IDX / $ACTUAL_FPS}")
    ABS_TIME=$(awk "BEGIN {printf \"%.3f\", $CH_START + $TIME_OFFSET}")

    # Copy to global output
    cp "$f" "$OUT_DIR/frame_${GLOBAL_NUM}.png"

    # Copy to chapter subdirectory
    cp "$f" "$OUT_DIR/chapters/chapter_$(printf '%02d' $((ch+1)))/frame_${GLOBAL_NUM}.png"

    # Write frame metadata (JSONL — one line per frame for machine readability)
    printf '{"frame": %d, "chapter": %d, "timestamp": %.3f, "file": "frame_%04d.png"}\n' \
      "$GLOBAL_FRAME_NUM" "$((ch+1))" "$ABS_TIME" "$GLOBAL_FRAME_NUM" >> "$FRAME_META"
  done

  LAST_FRAME=$GLOBAL_FRAME_NUM

  # Write chapter JSON entry
  if [ "$FIRST_CHAPTER" = true ]; then
    FIRST_CHAPTER=false
  else
    echo "," >> "$CHAPTER_FILE"
  fi
  printf '  {"chapter": %d, "start": %d, "end": %d, "frames": %d, "first_frame": %d, "last_frame": %d, "dir": "chapters/chapter_%02d"}' \
    "$((ch+1))" "$CH_START" "$CH_END" "$COUNT" "$FIRST_FRAME" "$LAST_FRAME" "$((ch+1))" >> "$CHAPTER_FILE"

  echo "  Extracted $COUNT frames (global: $FIRST_FRAME-$LAST_FRAME)"
done

echo "" >> "$CHAPTER_FILE"
echo "]" >> "$CHAPTER_FILE"

TOTAL_EXTRACTED=$GLOBAL_FRAME_NUM

# ── generate summary ────────────────────────────────────────────────────
SUMMARY="$OUT_DIR/summary.md"

cat > "$SUMMARY" << EOSUM
# Video Analysis: $(basename "$VIDEO") — Raw FPS Extraction

**Source:** $VIDEO
**Duration:** $DURATION (${TOTAL_SECS}s)
**Native FPS:** $NATIVE_FPS | **Extraction FPS:** $ACTUAL_FPS
**Effective range:** ${START_SECS}s - ${END_SECS}s (${EFFECTIVE_SECS}s)
**Chapter size:** ${CHAPTER_SECS}s | **Chapters:** $NUM_CHAPTERS
**Total frames extracted:** $TOTAL_EXTRACTED
**Frame size:** ${SCALE_W}px wide

## Chapters

| Chapter | Time Range | Frames | Frame IDs | Directory |
|---------|-----------|--------|-----------|-----------|
EOSUM

for (( ch=0; ch<NUM_CHAPTERS; ch++ )); do
  CH_START=$(( START_SECS + ch * CHAPTER_SECS ))
  CH_END=$(( CH_START + CHAPTER_SECS ))
  if (( CH_END > END_SECS )); then CH_END=$END_SECS; fi

  CH_H=$(( CH_START / 3600 ))
  CH_M=$(( (CH_START % 3600) / 60 ))
  CH_S=$(( CH_START % 60 ))
  CE_H=$(( CH_END / 3600 ))
  CE_M=$(( (CH_END % 3600) / 60 ))
  CE_S=$(( CH_END % 60 ))
  TIME_RANGE=$(printf "%02d:%02d:%02d - %02d:%02d:%02d" "$CH_H" "$CH_M" "$CH_S" "$CE_H" "$CE_M" "$CE_S")

  # Parse chapter info from JSON
  CH_JSON=$(awk -v c=$((ch+1)) "/\"chapter\": $((ch+1))/" "$CHAPTER_FILE")
  C_COUNT=$(echo "$CH_JSON" | grep -oE '"frames": [0-9]+' | grep -oE '[0-9]+')
  C_FIRST=$(echo "$CH_JSON" | grep -oE '"first_frame": [0-9]+' | grep -oE '[0-9]+')
  C_LAST=$(echo "$CH_JSON" | grep -oE '"last_frame": [0-9]+' | grep -oE '[0-9]+')

  if (( C_COUNT > 0 )); then
    FRAME_IDS=$(printf "frame_%04d.png – frame_%04d.png" "$C_FIRST" "$C_LAST")
  else
    FRAME_IDS="(none)"
  fi

  printf "| %d | %s | %d | %s | chapters/chapter_%02d/ |\n" \
    "$((ch+1))" "$TIME_RANGE" "$C_COUNT" "$FRAME_IDS" "$((ch+1))" >> "$SUMMARY"
done

cat >> "$SUMMARY" << 'EOF'

---

## How to Analyze Raw FPS Frames

### Approach 1: Chapter-By-Chapter Reading

1. **Scan chapter thumbnails** — read the first frame of each chapter
2. **Pick a chapter** — read all frames from one chapter directory at a time
3. **For each frame, note:**
   - What changed from the previous frame (even subtle changes matter)
   - Sprite animation state, UI changes, projectile positions
   - Frame number and timestamp for timing calculations

### Approach 2: Event-Focused Deep Dive

1. **Find an event** — use chapter thumbnails to locate interesting moments
2. **Read the surrounding chapter** in full detail
3. **Count frames between events:**
   - "Player fires at frame 45, projectile visible at frame 46 = 1 frame delay"
   - "Enemy appears at frame 120, first attack at frame 135 = 15 frame gap"
4. **Reference frame_metadata.jsonl** for exact timestamps

### Approach 3: Comparative Frame Analysis

1. **Pick 2-3 chapters** representing different gameplay phases
2. **Read frames side-by-side** to compare mechanics
3. **Look for timing patterns:**
   - Consistent cooldowns, varying attack windows
   - Animation timing differences between states

## Frame Count Reference

| Duration | @ 30fps | @ 60fps | @ 120fps |
|----------|---------|---------|----------|
| 0.1s | 3 frames | 6 frames | 12 frames |
| 0.25s | 8 frames | 15 frames | 30 frames |
| 0.5s | 15 frames | 30 frames | 60 frames |
| 1s | 30 frames | 60 frames | 120 frames |
| 2s | 60 frames | 120 frames | 240 frames |
| 5s | 150 frames | 300 frames | 600 frames |

## Output Files

| File | Purpose |
|------|---------|
| `frame_NNNN.png` | All frames in global sequential order |
| `chapters/chapter_NN/frame_NNNN.png` | Frames organized by chapter |
| `chapters.json` | Machine-readable chapter map (start/end/frame ranges) |
| `frame_metadata.jsonl` | Per-frame metadata with exact timestamps (one JSON per line) |
| `summary.md` | This file — human-readable overview |

## Re-extract with Different Settings

```bash
# Higher FPS for more detail
extract-raw.sh video.mp4 ./raw-60fps 60 640 10

# Lower FPS for overview
extract-raw.sh video.mp4 ./raw-30fps 30 640 15

# Focus on a specific segment (skip first 5min, skip last 1min, 5s chapters)
extract-raw.sh video.mp4 ./boss-fight full 640 5 300 60
```
EOF

echo ""
echo "Done! Output in: $OUT_DIR/"
echo "  Frames: $TOTAL_EXTRACTED PNGs across $NUM_CHAPTERS chapters"
echo "  Summary: $SUMMARY"
echo "  Chapter map: $CHAPTER_FILE"
echo "  Frame metadata: $FRAME_META"
echo ""
echo "Next: read $SUMMARY and analyze frames chapter-by-chapter"