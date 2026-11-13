#!/usr/bin/env bash
# extract-frames.sh — Smart keyframe extraction for video analysis
#
# Uses ffmpeg scene detection to find natural break points,
# then adjusts threshold to stay within a configurable frame cap.
# Outputs PNG frames + a summary markdown file.
#
# Usage:
#   extract-frames.sh <video> [output_dir] [max_frames] [scale_width] [scene_threshold]
#
# Args:
#   video            — Path to the video file (required)
#   output_dir       — Where to write frames + summary.md (default: ./frames)
#   max_frames       — Max frames to extract (default: 30)
#   scale_width      — Max frame width in px; height auto-scaled (default: 768)
#   scene_threshold  — Scene change sensitivity 0.1-1.0 (default: 0.3)

set -euo pipefail

# ── defaults ──────────────────────────────────────────────────────────
VIDEO="${1:?Usage: extract-frames.sh <video> [output_dir] [max_frames] [scale_width] [threshold]}"
OUT_DIR="${2:-frames}"
MAX_FRAMES="${3:-50}"
SCALE_W="${4:-640}"
SCENE_THRESH="${5:-0.1}"

if [[ ! -f "$VIDEO" ]]; then
  echo "Error: file not found: $VIDEO" >&2
  exit 1
fi

SUMMARY="$OUT_DIR/summary.md"

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
  echo "Error: ffmpeg not found. Install it (brew install ffmpeg or place in ~/bin/)." >&2
  exit 1
fi

# ── prepare output dir ────────────────────────────────────────────────
rm -f "$OUT_DIR"/frame_*.png
mkdir -p "$OUT_DIR"

# ── get video metadata ────────────────────────────────────────────────
# Use -f null to suppress "at least one output" error
VIDEO_INFO=$($FFMPEG -i "$VIDEO" -f null - 2>&1)
# macOS grep doesn't support -P (PCRE); use -E + sed instead
DURATION=$(echo "$VIDEO_INFO" | grep -oE 'Duration: [^,]+' | sed 's/Duration: //' | head -1 || echo "unknown")

# Convert duration to total seconds
TOTAL_SECS=0
if [[ "$DURATION" != "unknown" ]]; then
  IFS=: read -r h m s <<< "$DURATION"
  # Handle decimal seconds
  S_INT=${s%%.*}
  TOTAL_SECS=$(( 10#${h:-0} * 3600 + 10#${m:-0} * 60 + 10#${S_INT:-0} ))
fi
echo "Video duration: $DURATION (${TOTAL_SECS}s)"

# ── phase 1: scene detection — extract keyframes ──────────────────────
echo "Extracting keyframes (scene threshold: $SCENE_THRESH)..."

# Extract frames at scene changes + ensure the first frame is included
# eq(n,0) = first frame, gt(scene,THRESH) = scene changes
$FFMPEG -i "$VIDEO" -an \
  -vf "select='gt(scene,$SCENE_THRESH)+eq(n,0)',scale=${SCALE_W}:-1:flags=lanczos" \
  -fps_mode vfr -q:v 2 "$OUT_DIR/frame_%04d.png" 2>/dev/null || true

EXTRACTED=$(ls "$OUT_DIR"/frame_*.png 2>/dev/null | wc -l | tr -d ' ')
echo "Extracted $EXTRACTED frames at threshold $SCENE_THRESH"

# ── phase 2: if too many, re-run with higher threshold ────────────────
if [[ "$EXTRACTED" -gt "$MAX_FRAMES" ]]; then
  echo "Too many frames ($EXTRACTED > $MAX_FRAMES). Searching for better threshold..."

  # Binary search for a threshold that gives us <= max frames
  LO=0.1
  HI=1.0
  BEST_THRESH=$SCENE_THRESH
  BEST_COUNT=$EXTRACTED

  TEMP_DIR=$(mktemp -d)
  trap 'rm -rf "$TEMP_DIR"' EXIT

  for _ in $(seq 1 5); do
    MID=$(awk "BEGIN {printf \"%.2f\", ($LO + $HI) / 2}")
    rm -f "$TEMP_DIR"/frame_*.png
    $FFMPEG -i "$VIDEO" -an \
      -vf "select='gt(scene,$MID)+eq(n,0)',scale=${SCALE_W}:-1:flags=lanczos" \
      -fps_mode vfr -q:v 2 "$TEMP_DIR/frame_%04d.png" 2>/dev/null || true
    COUNT=$(ls "$TEMP_DIR"/frame_*.png 2>/dev/null | wc -l | tr -d ' ')

    if [[ "$COUNT" -le "$MAX_FRAMES" && "$COUNT" -gt 0 ]]; then
      if [[ "$COUNT" -gt "$BEST_COUNT" ]]; then
        BEST_THRESH=$MID
        BEST_COUNT=$COUNT
      fi
      LO=$MID  # try lower threshold to get more frames (up to max)
    else
      HI=$MID  # threshold too low, need higher
    fi

    if (( COUNT <= MAX_FRAMES && BEST_COUNT > 0 )); then
      break
    fi
  done

  echo "Using threshold $BEST_THRESH ($BEST_COUNT frames)"
  rm -f "$OUT_DIR"/frame_*.png
  $FFMPEG -i "$VIDEO" -an \
    -vf "select='gt(scene,$BEST_THRESH)+eq(n,0)',scale=${SCALE_W}:-1:flags=lanczos" \
    -fps_mode vfr -q:v 2 "$OUT_DIR/frame_%04d.png" 2>/dev/null || true
  EXTRACTED=$BEST_COUNT
  SCENE_THRESH=$BEST_THRESH

  # If still over cap after scene detection, do uniform sampling as fallback
  if [[ "$EXTRACTED" -gt "$MAX_FRAMES" ]]; then
    echo "Scene detection still over cap. Falling back to uniform time-based sampling..."
    rm -f "$OUT_DIR"/frame_*.png
    INTERVAL=$(awk "BEGIN {printf \"%.2f\", $TOTAL_SECS / $MAX_FRAMES}")
    $FFMPEG -i "$VIDEO" -an \
      -vf "fps=1/${INTERVAL},scale=${SCALE_W}:-1:flags=lanczos" \
      -fps_mode vfr -q:v 2 "$OUT_DIR/frame_%04d.png" 2>/dev/null || true
    EXTRACTED=$(ls "$OUT_DIR"/frame_*.png 2>/dev/null | wc -l | tr -d ' ')
    SCENE_THRESH="uniform"
  fi
fi

# ── phase 3: generate summary markdown ────────────────────────────────
echo "Generating summary..."

cat > "$SUMMARY" << EOSUM
# Video Analysis: $(basename "$VIDEO")

**Source:** $VIDEO
**Duration:** $DURATION
**Scene threshold used:** $SCENE_THRESH
**Frames extracted:** $EXTRACTED
**Frame size:** ${SCALE_W}px wide (auto-height, Lanczos scaling)

## Frames

| # | Frame | Timestamp |
|---|-------|-----------|
EOSUM

for f in "$OUT_DIR"/frame_*.png; do
  [[ -f "$f" ]] || continue
  FN=$(basename "$f")

  # Parse frame number from filename (frame_0001.png -> 1)
  FRAME_NUM=${FN#frame_}
  FRAME_NUM=${FRAME_NUM%.png}
  FRAME_NUM=$((10#$FRAME_NUM))  # remove leading zeros

  # Estimate timestamp based on position in the sequence
  if [[ "$TOTAL_SECS" -gt 0 && "$EXTRACTED" -gt 1 ]]; then
    EST_SEC=$(awk "BEGIN {printf \"%.1f\", ($FRAME_NUM - 1) * $TOTAL_SECS / ($EXTRACTED + 1)}")
  else
    EST_SEC="?"
  fi

  if [[ "$EST_SEC" != "?" ]]; then
    H=$(( ${EST_SEC%.*} / 3600 ))
    M=$(( (${EST_SEC%.*} % 3600) / 60 ))
    S=$(( ${EST_SEC%.*} % 60 ))
    TS_FMT=$(printf '%02d:%02d:%02d' "$H" "$M" "$S")
  else
    TS_FMT="?"
  fi

  echo "| $FRAME_NUM | \`$FN\` | ~$TS_FMT ($EST_SEC s) |" >> "$SUMMARY"
done

cat >> "$SUMMARY" << 'EOF'

---

## How to Analyze

1. **Read frames** using the `read` tool (they are PNG images Pi can process)
2. **Group by segment** — opening, core gameplay, boss fight, transitions, etc.
3. **Analyze in batches** of 5-10 frames per pass to stay within context limits
4. **Document findings** about mechanics, visuals, UI, animations, level design

## Analysis Prompt Template

When analyzing a batch of frames, use a prompt like:

```
Analyze these gameplay video frames as a storyboard. They are sequential captures
from a game session at the timestamps noted in summary.md. For each frame, describe:
- What is happening on screen
- UI elements visible (HUD, menus, indicators, health bars, score, etc.)
- Player actions and state
- Enemy/NPC behavior and patterns
- Level/environment design and layout
- Visual style, art direction, color palette

Then summarize:
- Core gameplay loop and mechanics
- Difficulty/progression patterns
- Screen layout and information hierarchy
- Animation and feedback patterns (how does the game communicate with the player?)
- Any unique or notable design choices worth emulating or improving on
```

## Multi-Pass Strategy for Long Videos (12-15 min)

For longer videos with distinct segments (multiple boards, boss fights):

1. **Pass 1 — Overview:** Read all frames in order to map the structure
   - Identify segment boundaries (level starts, boss transitions, etc.)
   - Note which frame numbers belong to which segment

2. **Pass 2 — Deep Dive:** Re-extract frames for specific segments at higher density
   - Rerun with a narrower time range: use ffmpeg -ss and -t to extract
   - Example: `extract-frames.sh video.mp4 boss-phase 15 768 0.2`
   - Then analyze just those frames in detail

3. **Pass 3 — Specific Questions:** Targeted analysis of mechanics, UI, or patterns
EOF

echo ""
echo "Done! Output in: $OUT_DIR/"
echo "  Frames: $EXTRACTED PNGs"
echo "  Summary: $SUMMARY"
echo ""
echo "Next: read $SUMMARY and analyze frames in batches using the read tool"