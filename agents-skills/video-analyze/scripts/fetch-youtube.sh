#!/usr/bin/env bash
# fetch-youtube.sh — Download a YouTube video + metadata for video-analyze
#
# Usage:
#   fetch-youtube.sh <url-or-video-id> [output_dir] [format]
#
# Args:
#   url-or-video-id   YouTube URL or bare video ID (e.g., jNQXAC9IVRw)
#   output_dir        Directory for the download (default: ./youtube)
#   format            yt-dlp format spec
#                     (default: best mp4 video+audio, falls back to best)
#
# Outputs (in output_dir):
#   <Title>.mp4        merged video
#   <Title>.meta.json  full yt-dlp JSON: title, description, chapters, duration, ...
#
# The last line printed is the video path, so you can do:
#   VIDEO=$(./scripts/fetch-youtube.sh <url> ./analysis | tail -1)
#   ./scripts/extract-chunks.sh "$VIDEO" ./analysis/frames ...
#
# Requires: yt-dlp (brew install yt-dlp | pip3 install --user yt-dlp)
set -uo pipefail

if [ $# -lt 1 ]; then
  echo "Usage: $(basename "$0") <url-or-video-id> [output_dir] [format]" >&2
  exit 1
fi

URL="$1"
OUTDIR="${2:-./youtube}"
FORMAT="${3:-bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best}"

if ! command -v yt-dlp >/dev/null 2>&1; then
  echo "ERROR: yt-dlp not found. Install with one of:" >&2
  echo "  brew install yt-dlp" >&2
  echo "  pip3 install --user yt-dlp" >&2
  exit 1
fi

case "$URL" in
  http*) : ;;
  *) URL="https://www.youtube.com/watch?v=$URL" ;;
esac

mkdir -p "$OUTDIR"
cd "$OUTDIR"

# --- Pass 1: metadata (fast; no video download) ---
META_FILE="video.meta.json"
if ! yt-dlp --no-warnings --no-playlist -J "$URL" > "$META_FILE" 2>/dev/null; then
  echo "ERROR: could not fetch metadata for $URL" >&2
  rm -f "$META_FILE"
  exit 1
fi

TITLE=$(python3 -c "import json;print(json.load(open('$META_FILE')).get('title',''))" 2>/dev/null)
DURATION=$(python3 -c "import json;print(int(json.load(open('$META_FILE')).get('duration',0)))" 2>/dev/null)
[ -n "$TITLE" ] || { echo "ERROR: no title in metadata" >&2; exit 1; }

SAFE_TITLE=$(printf '%s' "$TITLE" | tr '/\\:*?"<>|' '________' | sed 's/  */ /g')
BASE="${SAFE_TITLE}"
VIDEO_FILE="${BASE}.mp4"

echo "Title:    $TITLE"
echo "Duration: ${DURATION}s"
echo "Meta:     $OUTDIR/$META_FILE"

# --- Pass 2: video (skip if already downloaded) ---
if [ -f "$VIDEO_FILE" ]; then
  echo "Video already exists: $OUTDIR/$VIDEO_FILE"
else
  echo "Downloading..."
  if ! yt-dlp --no-warnings --no-playlist -f "$FORMAT" --merge-output-format mp4 \
      -o "${BASE}.%(ext)s" "$URL" > /dev/null; then
    echo "ERROR: download failed for $URL" >&2
    exit 1
  fi
  # Normalize result: <base>.mp4 if mp4; otherwise keep the real extension
  RESULT=""
  for f in "${BASE}".*; do
    [ -f "$f" ] || continue
    case "$f" in *.meta.json) continue ;; esac
    RESULT="$f"; break
  done
  if [ -z "$RESULT" ]; then
    echo "ERROR: download produced no file" >&2
    exit 1
  fi
  if [ "$RESULT" != "$VIDEO_FILE" ]; then
    case "$RESULT" in
      *.mp4) mv -f "$RESULT" "$VIDEO_FILE" ;;
      *)     VIDEO_FILE="$RESULT" ;;
    esac
  fi
fi

echo "Video:    $OUTDIR/$VIDEO_FILE"
# Last line = video path (for command substitution)
echo "$OUTDIR/$VIDEO_FILE"