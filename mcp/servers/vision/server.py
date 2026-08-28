#!/usr/bin/env python3
"""MCP Vision Server — image/video analysis via matrix-coder vision.

Tools:
  - vision_analyze_image(source, prompt?, focus?)      image -> structured markdown
  - vision_analyze_video(source, prompt?, mode?, ...)  video -> storyboard report
  - vision_extract_frames(source, ...)                 frames only (no LLM)
  - vision_cleanup(slug?, older_than_days?)            artifact housekeeping
  - vision_probe(n?)                                   image-cap probe (ops)

source = local path (under an allowed root) or http(s) URL (any host,
2 GB cap). YouTube URLs go through yt-dlp (metadata first).

Pipeline (ported from the owner's video-analyze pi skill):
  probe (ffprobe) -> extract (ffmpeg scene/raw) -> batch (<=5 images)
  -> per-batch vision call (matrix-coder via LiteLLM, thinking OFF)
  -> text-only consolidation -> report + artifacts.

Artifacts: VISION_OUTPUT_ROOT/<slug>/ (NOT public; cleaned via
vision_cleanup / scripts/cleanup-vision.sh).

Transport: streamable-http (HTTP, default 0.0.0.0:8000)
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.parse
from pathlib import Path
from typing import Optional

import httpx
from mcp.server import FastMCP

logger = logging.getLogger("mcp_vision")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MCPS_HOST: str = os.environ.get("MCPS_HOST", "0.0.0.0")
LITELLM_API_BASE: str = os.environ.get(
    "LITELLM_API_BASE", "http://litellm-proxy:4000").rstrip("/")
LITELLM_API_KEY: str = os.environ.get("LITELLM_API_KEY", "")
# REST API takes the alias as-is (no provider prefix — A0 probe).
VISION_MODEL: str = os.environ.get("VISION_MODEL", "matrix-coder")
VISION_MAX_IMAGES: int = int(os.environ.get("VISION_MAX_IMAGES", "5"))
VISION_OUTPUT_ROOT: Path = Path(
    os.environ.get("VISION_OUTPUT_ROOT", "/data/workspace/vision"))
VISION_ALLOWED_ROOTS: list[Path] = [
    Path(p) for p in os.environ.get(
        "VISION_ALLOWED_ROOTS",
        "/data/media,/data/workspace,/data/ai-kb/raw",
    ).split(",") if p.strip()
]
VISION_DOWNLOAD_CAP: int = int(
    os.environ.get("VISION_DOWNLOAD_CAP_BYTES", str(2 * 1024 ** 3)))
VISION_MAX_FRAMES_RAW: int = int(os.environ.get("VISION_MAX_FRAMES_RAW", "3000"))
VISION_MAX_FRAMES_SCENE: int = int(os.environ.get("VISION_MAX_FRAMES_SCENE", "200"))
VISION_TIMEOUT: float = float(os.environ.get("VISION_TIMEOUT", "300"))

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif",
              ".gif", ".heic"}
VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".gif", ".ogv"}

YOUTUBE_RE = re.compile(
    r"(youtube\.com/(watch\?v=|shorts/|embed/)|youtu\.be/)", re.I)


# ---------------------------------------------------------------------------
# Source resolution
# ---------------------------------------------------------------------------

def slugify(source: str) -> str:
    """Deterministic artifact slug from a source (path or URL)."""
    if YOUTUBE_RE.search(source):
        m = re.search(r"(?:v=|/shorts/|/embed/|youtu\.be/)([\w-]{6,})", source)
        if m:
            return "yt-" + m.group(1)
    if source.startswith(("http://", "https://")):
        name = os.path.basename(urllib.parse.urlparse(source).path)
    else:
        name = os.path.basename(source)
    base = re.sub(r"\.[A-Za-z0-9]{1,5}$", "", name or "media")
    slug = re.sub(r"[^a-z0-9_-]+", "-", base.lower()).strip("-")
    return slug[:60] or "media"


def _validate_local_path(path: str) -> Path:
    """Local path must resolve under an allowed root (no ../ / symlink escape)."""
    p = Path(path).expanduser()
    if not p.is_absolute():
        raise ValueError(f"path must be absolute: {path}")
    rp = p.resolve()
    for root in VISION_ALLOWED_ROOTS:
        rr = root.resolve()
        if rp == rr or rr in rp.parents:
            return rp
    raise ValueError(
        f"path {path} is outside the allowed roots: "
        f"{[str(r) for r in VISION_ALLOWED_ROOTS]}")


def _download_url(url: str, tmpdir: Path) -> tuple[Path, dict]:
    """Stream an http(s) file into tmpdir (size-capped). Returns (path, meta)."""
    parsed = urllib.parse.urlparse(url)
    name = os.path.basename(parsed.path) or "download"
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name)[:120]
    dest = tmpdir / name
    meta: dict = {"url": url}
    with httpx.stream(
        "GET", url, follow_redirects=True, timeout=600,
        headers={"User-Agent": "mcp_vision/0.1"},
    ) as r:
        r.raise_for_status()
        meta["content_type"] = r.headers.get("content-type", "")
        total = 0
        with open(dest, "wb") as f:
            for chunk in r.iter_bytes(chunk_size=1024 * 1024):
                total += len(chunk)
                if total > VISION_DOWNLOAD_CAP:
                    f.close()
                    dest.unlink(missing_ok=True)
                    raise ValueError(
                        f"download exceeds {VISION_DOWNLOAD_CAP // (1024 ** 3)} GB cap")
                f.write(chunk)
    meta["bytes"] = total
    return dest, meta


def _youtube_id(url: str) -> Optional[str]:
    m = re.search(r"(?:v=|/shorts/|/embed/|youtu\.be/)([\w-]{6,})", url)
    return m.group(1) if m else None


def _download_youtube(url: str, tmpdir: Path) -> tuple[Path, dict]:
    """yt-dlp: metadata first (title/duration/chapters), then the video."""
    vid = _youtube_id(url)
    if not vid:
        raise ValueError(f"not a recognizable YouTube URL: {url}")
    meta_path = tmpdir / "video.meta.json"
    r = subprocess.run(
        ["yt-dlp", "--no-warnings", "--no-playlist", "-J", url,
         "-o", str(meta_path)],
        check=True, capture_output=True, timeout=120,
    )
    meta = json.loads(r.stdout or meta_path.read_text())
    out_tpl = str(tmpdir / "%(title).80s [%(id)s].%(ext)s")
    subprocess.run(
        ["yt-dlp", "--no-warnings", "--no-playlist",
         "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
         "--merge-output-format", "mp4", "-o", out_tpl, url],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        timeout=3600,
    )
    video = tmpdir / f"{(meta.get('title') or vid)[:80]} [{vid}].mp4"
    if not video.exists():
        cands = [p for p in tmpdir.iterdir() if p.suffix in VIDEO_EXTS]
        if not cands:
            raise RuntimeError("yt-dlp produced no video file")
        video = cands[0]
    meta["youtube"] = {
        "id": vid,
        "title": meta.get("title"),
        "description": (meta.get("description") or "")[:2000],
        "duration": meta.get("duration"),
        "chapters": meta.get("chapters") or [],
    }
    return video, meta


def resolve_source(source: str) -> tuple[Path, dict, Optional[Path]]:
    """Resolve a tool `source` to a local file.

    Returns (local_path, meta, tmpdir-or-None). Caller must clean tmpdir.
    """
    if source.startswith(("http://", "https://")):
        tmpdir = Path(tempfile.mkdtemp(prefix="mcp_vision_"))
        if YOUTUBE_RE.search(source):
            path, meta = _download_youtube(source, tmpdir)
        else:
            path, meta = _download_url(source, tmpdir)
        return path, meta, tmpdir
    p = _validate_local_path(source)
    if not p.exists():
        raise FileNotFoundError(f"source not found: {source}")
    return p, {"local": source}, None# ---------------------------------------------------------------------------
# ffmpeg helpers (ported from the video-analyze skill's bash scripts)
# ---------------------------------------------------------------------------

def _run(cmd: list, timeout: float = 1800) -> subprocess.CompletedProcess:
    """Run a subprocess (arg list, never a shell string)."""
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def probe_media(path: Path) -> dict:
    """ffprobe: duration, native fps, dimensions."""
    r = _run([
        "ffprobe", "-v", "error", "-print_format", "json",
        "-show_format", "-show_streams", str(path),
    ], timeout=120)
    if r.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {r.stderr[:300]}")
    j = json.loads(r.stdout)
    fmt = j.get("format", {})
    vstream = next(
        (s for s in j.get("streams", []) if s.get("codec_type") == "video"), {})
    duration = float(fmt.get("duration") or 0)
    fps = 30.0
    for key in ("avg_frame_rate", "r_frame_rate"):
        fr = vstream.get(key, "")
        if "/" in fr:
            num, den = fr.split("/")
            if float(den or 0) > 0:
                fps = float(num) / float(den)
                break
        elif fr:
            try:
                fps = float(fr)
                break
            except ValueError:
                pass
    return {
        "duration_s": duration,
        "native_fps": round(fps, 3),
        "width": int(vstream.get("width") or 0),
        "height": int(vstream.get("height") or 0),
    }


def _extract_chunk_scene(video: Path, start: int, length: int, out_dir: Path,
                         scale_w: int, thresh: float, max_frames: int) -> list:
    """One chunk: scene detection + uniform fallback + midpoint fallback."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("frame_*.png"):
        old.unlink()
    _run([
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-i", str(video), "-ss", str(start), "-t", str(length), "-an",
        "-vf", f"select='gt(scene,{thresh})+eq(n,0)',scale={scale_w}:-1:flags=lanczos",
        "-fps_mode", "vfr", "-q:v", "2",
        str(out_dir / "frame_%04d.png"),
    ], timeout=1800)
    frames = sorted(out_dir.glob("frame_*.png"))
    if len(frames) > max_frames:
        # too many scene changes -> uniform resample (skill fallback)
        for f in frames:
            f.unlink()
        interval = length / max_frames
        _run([
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-i", str(video), "-ss", str(start), "-t", str(length), "-an",
            "-vf", f"fps=1/{interval:.4f},scale={scale_w}:-1:flags=lanczos",
            "-fps_mode", "vfr", "-q:v", "2",
            str(out_dir / "frame_%04d.png"),
        ], timeout=1800)
        frames = sorted(out_dir.glob("frame_*.png"))
    if not frames:
        # no scene changes -> one frame from the midpoint (skill fallback)
        mid = start + length // 2
        _run([
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-i", str(video), "-ss", str(mid), "-an",
            "-vf", f"scale={scale_w}:-1:flags=lanczos",
            "-frames:v", "1", "-q:v", "2",
            str(out_dir / "frame_0001.png"),
        ], timeout=300)
        frames = sorted(out_dir.glob("frame_*.png"))
    return frames


def extract_scene(video: Path, out_dir: Path, *, chunk_secs: int = 120,
                  frames_per_chunk: int = 10, scale_w: int = 640,
                  scene_thresh: float = 0.2, skip_intro: int = 0,
                  skip_outro: int = 0,
                  max_frames: int = VISION_MAX_FRAMES_SCENE) -> dict:
    """Chunk-based scene extraction (extract-chunks.sh, scene mode).

    Every segment gets coverage; total capped at max_frames.
    Returns {frames, chapters, total, duration_s, native_fps}.
    """
    info = probe_media(video)
    total = int(info["duration_s"])
    start, end = skip_intro, max(skip_intro + 1, total - skip_outro)
    effective = end - start
    if effective <= 0:
        raise ValueError("skip values exceed video duration")
    num_chunks = (effective + chunk_secs - 1) // chunk_secs

    frames: list = []
    chapters: list = []
    offset = 0
    for c in range(num_chunks):
        c_start = start + c * chunk_secs
        c_end = min(c_start + chunk_secs, end)
        c_len = c_end - c_start
        cdir = out_dir / "chunks" / f"chunk_{c:03d}"
        got = _extract_chunk_scene(video, c_start, c_len, cdir, scale_w,
                                   scene_thresh, frames_per_chunk)
        room = max_frames - len(frames)
        if len(got) > room:
            got = got[: max(0, room)]
        for i, f in enumerate(got):
            # timestamps are estimates (skill: chunk-based approximation)
            ts = c_start + (i + 0.5) * c_len / max(len(got), 1)
            dest = out_dir / f"frame_{offset + 1:04d}.png"
            shutil.copy2(f, dest)
            frames.append({"file": dest.name, "timestamp": round(ts, 3),
                           "chunk": c + 1})
            offset += 1
        chapters.append({
            "chunk": c + 1, "start": c_start, "end": c_end,
            "frames": len(got),
            "first_frame": (offset - len(got) + 1) if got else 0,
            "last_frame": offset,
        })
        if offset >= max_frames:
            break
    return {"frames": frames, "chapters": chapters, "total": len(frames),
            "duration_s": total, "native_fps": info["native_fps"]}


def extract_raw(video: Path, out_dir: Path, *, fps: str = "full",
                scale_w: int = 640, chapter_secs: int = 10,
                skip_intro: int = 0, skip_outro: int = 0,
                max_frames: int = VISION_MAX_FRAMES_RAW) -> dict:
    """Full-FPS extraction with chapters (extract-raw.sh) — frame-accurate.

    Frame-budget guarded: refuses before extracting when the estimate
    exceeds max_frames.
    """
    info = probe_media(video)
    total = int(info["duration_s"])
    start, end = skip_intro, max(skip_intro + 1, total - skip_outro)
    effective = end - start
    if effective <= 0:
        raise ValueError("skip values exceed video duration")
    actual_fps = info["native_fps"] if fps == "full" else float(fps)
    est = int(effective * actual_fps)
    if est > max_frames:
        raise ValueError(
            f"raw extraction would produce ~{est} frames (budget {max_frames}). "
            f"Narrow the range (skip_intro/skip_outro), lower fps, "
            f"or use mode=scene.")
    num_ch = (effective + chapter_secs - 1) // chapter_secs
    frames: list = []
    chapters: list = []
    offset = 0
    for c in range(num_ch):
        c_start = start + c * chapter_secs
        c_len = min(chapter_secs, end - c_start)
        cdir = out_dir / "chapters" / f"chapter_{c + 1:02d}"
        cdir.mkdir(parents=True, exist_ok=True)
        _run([
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-ss", str(c_start), "-i", str(video), "-t", str(c_len), "-an",
            "-vf", f"fps={actual_fps},scale={scale_w}:-1:flags=lanczos,format=yuv420p",
            "-fps_mode", "cfr", "-q:v", "2",
            str(cdir / "frame_%04d.png"),
        ], timeout=3600)
        got = sorted(cdir.glob("frame_*.png"))
        for i, f in enumerate(got):
            ts = c_start + i / actual_fps  # precise (frame_metadata.jsonl)
            dest = out_dir / f"frame_{offset + 1:04d}.png"
            shutil.copy2(f, dest)
            frames.append({"file": dest.name, "timestamp": round(ts, 3),
                           "chunk": c + 1, "precise": True})
            offset += 1
        chapters.append({"chunk": c + 1, "start": c_start,
                         "end": c_start + c_len, "frames": len(got)})
    return {"frames": frames, "chapters": chapters, "total": len(frames),
            "duration_s": total, "native_fps": info["native_fps"],
            "extract_fps": actual_fps}


def extract_single_pass(video: Path, out_dir: Path, *, max_frames: int = 50,
                        scale_w: int = 640, scene_thresh: float = 0.1) -> dict:
    """Single-pass scene extraction (extract-frames.sh) — short videos."""
    info = probe_media(video)
    total = int(info["duration_s"])
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("frame_*.png"):
        old.unlink()
    _run([
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-i", str(video), "-an",
        "-vf", f"select='gt(scene,{scene_thresh})+eq(n,0)',scale={scale_w}:-1:flags=lanczos",
        "-fps_mode", "vfr", "-q:v", "2",
        str(out_dir / "frame_%04d.png"),
    ], timeout=1800)
    frames = sorted(out_dir.glob("frame_*.png"))
    if len(frames) > max_frames:
        for f in frames:
            f.unlink()
        interval = total / max_frames
        _run([
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-i", str(video), "-an",
            "-vf", f"fps=1/{interval:.4f},scale={scale_w}:-1:flags=lanczos",
            "-fps_mode", "vfr", "-q:v", "2",
            str(out_dir / "frame_%04d.png"),
        ], timeout=1800)
        frames = sorted(out_dir.glob("frame_*.png"))
    if not frames:
        _run([
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-i", str(video), "-ss", str(total // 2), "-an",
            "-vf", f"scale={scale_w}:-1:flags=lanczos",
            "-frames:v", "1", "-q:v", "2",
            str(out_dir / "frame_0001.png"),
        ], timeout=300)
        frames = sorted(out_dir.glob("frame_0001.png"))
    out = []
    for i, f in enumerate(frames):
        ts = (i + 0.5) * total / max(len(frames), 1)
        out.append({"file": f.name, "timestamp": round(ts, 3), "chunk": 1})
    return {"frames": out,
            "chapters": [{"chunk": 1, "start": 0, "end": total,
                          "frames": len(out)}],
            "total": len(out), "duration_s": total,
            "native_fps": info["native_fps"]}


def extract_gif_frames(gif: Path, out_dir: Path, max_frames: int,
                       scale_w: int) -> list:
    """GIF -> PNG frames at native fps (capped)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("frame_*.png"):
        old.unlink()
    _run([
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-i", str(gif),
        "-vf", f"scale={scale_w}:-1:flags=lanczos",
        "-q:v", "2", str(out_dir / "frame_%04d.png"),
    ], timeout=600)
    return sorted(out_dir.glob("frame_*.png"))[:max_frames]# ---------------------------------------------------------------------------
# Vision client (matrix-coder via LiteLLM REST)
# ---------------------------------------------------------------------------

def _vision_call_sync(frames: list, prompt: str, max_tokens: int = 2000) -> str:
    """One vision call: <= VISION_MAX_IMAGES frames, thinking OFF (A0 probe)."""
    content: list = [{"type": "text", "text": prompt}]
    for f in frames[:VISION_MAX_IMAGES]:
        b64 = base64.b64encode(f.read_bytes()).decode()
        content.append({"type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{b64}"}})
    body = {
        "model": VISION_MODEL,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": content}],
        # Qwen3 thinking burns the completion budget -> content=None (A0).
        "extra_body": {"chat_template_kwargs": {"enable_thinking": False}},
    }
    last_err: Optional[Exception] = None
    for attempt in range(3):
        try:
            with httpx.Client(timeout=VISION_TIMEOUT) as client:
                r = client.post(
                    f"{LITELLM_API_BASE}/chat/completions",
                    headers={"Authorization": f"Bearer {LITELLM_API_KEY}",
                             "Content-Type": "application/json"},
                    json=body,
                )
            if r.status_code == 200:
                j = r.json()
                msg = j["choices"][0]["message"]
                text = msg.get("content")
                if not text:
                    raise RuntimeError(
                        "model returned empty content (check thinking leak: "
                        f"{str(msg.get('reasoning_content'))[:120]})")
                return text
            if r.status_code in (429, 500, 502, 503, 504):
                last_err = RuntimeError(
                    f"LiteLLM HTTP {r.status_code}: {r.text[:200]}")
                time.sleep(5 * (attempt + 1))
                continue
            raise RuntimeError(f"LiteLLM HTTP {r.status_code}: {r.text[:300]}")
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            last_err = exc
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"vision call failed after 3 attempts: {last_err}")


async def vision_call(frames: list, prompt: str, max_tokens: int = 2000) -> str:
    return await asyncio.to_thread(_vision_call_sync, frames, prompt, max_tokens)


# ---------------------------------------------------------------------------
# Prompt templates (focus) — ported from the video-analyze skill
# ---------------------------------------------------------------------------

BATCH_INTRO = (
    "You are analyzing frames extracted from a video. The frames are in "
    "chronological order. For EACH frame: (1) describe what is visible, "
    "(2) transcribe ALL on-screen text/subtitles/captions VERBATIM in "
    "quotes, (3) note what changed from the previous frame. Be specific "
    "and factual. End with a 2-4 sentence summary of the segment."
)

FOCUS_TEMPLATES = {
    "general": BATCH_INTRO,
    "gameplay": BATCH_INTRO + (
        "\nStructure each frame around: mechanics (input/response), timing "
        "(frame-accurate events where visible), visual design (art style, "
        "composition, feedback), UI/HUD (what is displayed, screen "
        "real-estate), level design (layout, hazards, pacing), and "
        "transitions/polish."
    ),
    "tutorial": BATCH_INTRO + (
        "\nThis is a tutorial/instructional video. Track: the steps being "
        "demonstrated in order, every UI action (clicks, menus, keys), and "
        "ALL code/commands/config shown on screen VERBATIM (in code blocks)."
    ),
    "commercial": BATCH_INTRO + (
        "\nThis is QA of AI-GENERATED media (the frames were produced by a "
        "media-generation pipeline, not filmed). Evaluate: (1) PROMPT "
        "FIDELITY — does the content match the generation brief given "
        "below? (2) VISUAL QUALITY — lighting, texture, coherence; "
        "(3) ARTIFACTS/DEFECTS — warping, duplicated limbs/objects, melted "
        "geometry, inconsistent motion across frames, flicker; "
        "(4) COMPOSITION — framing, focal points; (5) TEXT RENDERING — any "
        "on-screen text: legible and unbroken? End with a structured "
        "verdict: PASS / FAIL per criterion, then concrete fix suggestions "
        "(prompt adjustments, regeneration params)."
    ),
}

CONSOLIDATE_PROMPT = """You are consolidating per-batch frame analyses of a video into a single report.

Video: {title}
Duration: {duration}
Source: {source}
{chapters}

Per-batch analyses (in order):
{batches}

Write ONE consolidated markdown report:
1. **Overview** — what the video is, in 3-6 sentences.
2. **Timeline** — a table: time range | what happens (one row per segment).
3. **Key moments** — the most important/notable moments (timestamps).
4. **On-screen text** — all verbatim text/captions/code collected (grouped).
5. {focus_extra}
Be specific; use timestamps (mm:ss). Do not invent content that is not in the batch analyses.
"""


def _fmt_ts(s: float) -> str:
    return f"{int(s // 60):02d}:{int(s % 60):02d}"


def _write_extraction_artifacts(out_root: Path, source: str, info: dict,
                                ext: dict, meta: dict) -> None:
    """summary.md + chapters.json + frame_metadata.jsonl (skill's layout)."""
    (out_root / "chapters.json").write_text(
        json.dumps(ext["chapters"], indent=2))
    with (out_root / "frame_metadata.jsonl").open("w") as f:
        for fr in ext["frames"]:
            f.write(json.dumps(fr) + "\n")
    lines = [
        f"# Video Analysis: {source}",
        "",
        f"**Duration:** {info['duration_s']:.0f}s | "
        f"**Native FPS:** {info['native_fps']}",
        f"**Total frames extracted:** {ext['total']}",
        "",
        "## Chapters",
        "",
        "| Chunk | Time Range | Frames |",
        "|-------|-----------|--------|",
    ]
    for c in ext["chapters"]:
        lines.append(
            f"| {c['chunk']} | {_fmt_ts(c['start'])}-{_fmt_ts(c['end'])} "
            f"| {c['frames']} |")
    if meta.get("youtube"):
        y = meta["youtube"]
        lines += ["", "## YouTube metadata",
                  f"- Title: {y.get('title')}",
                  f"- Chapters in metadata: {len(y.get('chapters') or [])}"]
    (out_root / "summary.md").write_text("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# MCP server + tools
# ---------------------------------------------------------------------------

mcp = FastMCP(
    name="mcp_vision",
    instructions=(
        "Vision analysis of images and videos (matrix-coder via LiteLLM; "
        f"<= {VISION_MAX_IMAGES} images per model call — the server batches "
        "automatically). `source` = local path under an allowed root "
        "(media/, workspace/, ai-kb/raw) OR any http(s) URL (mp4/mov/gif/"
        "jpg/png/...; 2 GB cap) OR a YouTube URL (yt-dlp). Artifacts "
        "(frames + report.md) land in a NON-public workspace dir "
        f"({VISION_OUTPUT_ROOT}/<slug>/) — clean up with vision_cleanup "
        "when done. focus=commercial = QA of mcp_media-generated media "
        "(pass the generation brief in `prompt`)."
    ),
    host=MCPS_HOST,
)


@mcp.tool(
    name="vision_analyze_image",
    description=(
        "Analyze a single image (or gif) with the vision model. source = "
        "local path (media/, workspace/, ai-kb/raw) or http(s) URL. "
        "Returns a structured markdown description incl. verbatim "
        "on-screen text. focus=commercial QA's mcp_media-generated "
        "images (pass the generation brief in prompt)."
    ),
)
async def vision_analyze_image(
    source: str,
    prompt: str = "",
    focus: str = "general",
) -> dict:
    if focus not in FOCUS_TEMPLATES:
        return {"status": "error",
                "error": f"unknown focus '{focus}'; "
                         f"use one of {sorted(FOCUS_TEMPLATES)}"}
    tmpdir = None
    try:
        path, meta, tmpdir = await asyncio.to_thread(resolve_source, source)
        slug = slugify(source)
        out_root = VISION_OUTPUT_ROOT / slug
        out_root.mkdir(parents=True, exist_ok=True)
        ext = path.suffix.lower()

        if ext in IMAGE_EXTS and ext != ".gif":
            frames = [path]
            frame_names = [path.name]
        else:
            # gif (or mislabeled image): extract frames, analyze as batch
            fdir = out_root / "frames"
            got = await asyncio.to_thread(
                extract_gif_frames, path, fdir, 50, 640)
            if not got:
                return {"status": "error", "source": source,
                        "error": "no frames extracted (invalid gif?)"}
            frames = got
            frame_names = [f.name for f in got]

        tpl = FOCUS_TEMPLATES[focus]
        if prompt:
            tpl = f"{tpl}\n\nGeneration brief / extra instruction: {prompt}"
        text = await vision_call(frames, tpl)
        report = (f"# Vision analysis: {slug}\n\nSource: {source}\n\n"
                  f"{text}\n")
        (out_root / "report.md").write_text(report)
        return {
            "status": "ok",
            "source": source,
            "slug": slug,
            "artifacts_dir": str(out_root),
            "frames": len(frames),
            "frame_files": frame_names,
            "report_markdown": text,
            "warnings": [],
        }
    except Exception as exc:
        return {"status": "error", "source": source, "error": str(exc)}
    finally:
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)


@mcp.tool(
    name="vision_analyze_video",
    description=(
        "Analyze a video as a storyboard: scene-detected (or raw full-FPS) "
        "frame extraction, batched vision analysis, consolidated markdown "
        "report. source = local path / http(s) URL / YouTube URL. "
        "mode=scene (default; single-pass <5 min, else chunked) or raw "
        "(frame-accurate timing; frame-budget guarded). "
        "focus=commercial QA's mcp_media-generated clips (pass the "
        "generation brief in prompt). Long-running: minutes for long "
        "videos."
    ),
)
async def vision_analyze_video(
    source: str,
    prompt: str = "",
    mode: str = "scene",
    chunk_secs: int = 120,
    frames_per_chunk: int = 10,
    fps: str = "full",
    scale_width: int = 640,
    skip_intro: int = 0,
    skip_outro: int = 0,
    focus: str = "general",
    max_frames: int = 0,
) -> dict:
    if focus not in FOCUS_TEMPLATES:
        return {"status": "error",
                "error": f"unknown focus '{focus}'; "
                         f"use one of {sorted(FOCUS_TEMPLATES)}"}
    if mode not in ("scene", "raw"):
        return {"status": "error", "error": "mode must be 'scene' or 'raw'"}
    tmpdir = None
    try:
        path, meta, tmpdir = await asyncio.to_thread(resolve_source, source)
        slug = slugify(source)
        out_root = VISION_OUTPUT_ROOT / slug
        shutil.rmtree(out_root, ignore_errors=True)  # re-run overwrites
        out_root.mkdir(parents=True, exist_ok=True)

        info = await asyncio.to_thread(probe_media, path)
        duration = info["duration_s"]

        if mode == "scene":
            if duration < 300:
                cap = max_frames or 50
                ext = await asyncio.to_thread(
                    extract_single_pass, path, out_root,
                    max_frames=cap, scale_w=scale_width, scene_thresh=0.1)
            else:
                cap = max_frames or VISION_MAX_FRAMES_SCENE
                ext = await asyncio.to_thread(
                    extract_scene, path, out_root,
                    chunk_secs=chunk_secs,
                    frames_per_chunk=frames_per_chunk, scale_w=scale_width,
                    skip_intro=skip_intro, skip_outro=skip_outro,
                    max_frames=cap)
        else:
            cap = max_frames or VISION_MAX_FRAMES_RAW
            ext = await asyncio.to_thread(
                extract_raw, path, out_root, fps=fps, scale_w=scale_width,
                chapter_secs=min(chunk_secs, 10) if chunk_secs else 10,
                skip_intro=skip_intro, skip_outro=skip_outro, max_frames=cap)

        frames = ext["frames"]
        if not frames:
            return {"status": "error", "source": source,
                    "error": "no frames extracted (corrupt/empty media?)"}
        _write_extraction_artifacts(out_root, source, info, ext, meta)

        tpl = FOCUS_TEMPLATES[focus]
        if prompt:
            tpl = f"{tpl}\n\nGeneration brief / extra instruction: {prompt}"
        n_batches = (len(frames) + VISION_MAX_IMAGES - 1) // VISION_MAX_IMAGES
        batch_summaries = []
        for i in range(0, len(frames), VISION_MAX_IMAGES):
            batch = frames[i:i + VISION_MAX_IMAGES]
            t0, t1 = batch[0]["timestamp"], batch[-1]["timestamp"]
            bpath = [out_root / f["file"] for f in batch]
            bprompt = (
                f"{tpl}\n\nSegment: {_fmt_ts(t0)}-{_fmt_ts(t1)} "
                f"(frames {i + 1}-{i + len(batch)} of {len(frames)}).")
            summary = await vision_call(bpath, bprompt)
            batch_summaries.append(
                f"### Segment {_fmt_ts(t0)}-{_fmt_ts(t1)} "
                f"(frames {i + 1}-{i + len(batch)})\n{summary}")
            logger.info("batch %d/%d done (%d frames)",
                        len(batch_summaries), n_batches, len(batch))

        title = (meta.get("youtube") or {}).get("title") or path.name
        chapters_txt = "\n".join(
            f"  - chunk {c['chunk']}: {_fmt_ts(c['start'])}-"
            f"{_fmt_ts(c['end'])} ({c['frames']} frames)"
            for c in ext["chapters"])
        focus_extra = {
            "commercial": (
                "5. **QA verdict** — PASS/FAIL table per criterion (prompt "
                "fidelity, visual quality, artifacts/defects, composition, "
                "text rendering) + concrete fix suggestions."),
        }.get(focus, "5. **Notes** — anything else worth knowing.")
        report = await vision_call(
            [],
            CONSOLIDATE_PROMPT.format(
                title=title,
                duration=f"{int(duration // 60)}m {int(duration % 60)}s",
                source=source,
                chapters=chapters_txt,
                batches="\n\n".join(batch_summaries),
                focus_extra=focus_extra,
            ),
            max_tokens=4000,
        )
        (out_root / "report.md").write_text(
            f"# Video analysis: {title}\n\nSource: {source}\n"
            f"Duration: {duration:.0f}s\n\n{report}\n")
        return {
            "status": "ok",
            "source": source,
            "slug": slug,
            "duration_s": int(duration),
            "frames_extracted": len(frames),
            "batches": len(batch_summaries),
            "artifacts_dir": str(out_root),
            "report_markdown": report,
            "warnings": [],
        }
    except Exception as exc:
        return {"status": "error", "source": source, "error": str(exc)}
    finally:
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)


@mcp.tool(
    name="vision_extract_frames",
    description=(
        "Extract frames from a video (NO LLM analysis): scene-detected or "
        "full-FPS. Writes frames + summary.md + chapters.json + "
        "frame_metadata.jsonl to the artifact dir. source = local path / "
        "http(s) URL / YouTube URL. Pairs with publish_file for blog "
        "artifacts."
    ),
)
async def vision_extract_frames(
    source: str,
    fps: str = "full",
    max_frames: int = 50,
    scale_width: int = 640,
    chunk_secs: int = 120,
    skip_intro: int = 0,
    skip_outro: int = 0,
) -> dict:
    tmpdir = None
    try:
        path, meta, tmpdir = await asyncio.to_thread(resolve_source, source)
        slug = slugify(source)
        out_root = VISION_OUTPUT_ROOT / slug
        shutil.rmtree(out_root, ignore_errors=True)
        out_root.mkdir(parents=True, exist_ok=True)
        info = await asyncio.to_thread(probe_media, path)
        if fps != "full":
            ext = await asyncio.to_thread(
                extract_raw, path, out_root, fps=fps, scale_w=scale_width,
                chapter_secs=min(chunk_secs, 30), skip_intro=skip_intro,
                skip_outro=skip_outro,
                max_frames=max(max_frames, VISION_MAX_FRAMES_RAW))
        elif info["duration_s"] < 300:
            ext = await asyncio.to_thread(
                extract_single_pass, path, out_root, max_frames=max_frames,
                scale_w=scale_width)
        else:
            ext = await asyncio.to_thread(
                extract_scene, path, out_root, chunk_secs=chunk_secs,
                frames_per_chunk=max(8, max_frames // 10),
                scale_w=scale_width, skip_intro=skip_intro,
                skip_outro=skip_outro, max_frames=max_frames)
        _write_extraction_artifacts(out_root, source, info, ext, meta)
        return {
            "status": "ok",
            "source": source,
            "slug": slug,
            "artifacts_dir": str(out_root),
            "frames_extracted": ext["total"],
            "chapters": ext["chapters"],
        }
    except Exception as exc:
        return {"status": "error", "source": source, "error": str(exc)}
    finally:
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)


@mcp.tool(
    name="vision_cleanup",
    description=(
        "Delete vision artifacts (frames + reports) to free disk. "
        "slug=... deletes one artifact dir; otherwise deletes all artifact "
        "dirs older than older_than_days (default 7). Artifacts are "
        "ephemeral (non-public workspace data)."
    ),
)
async def vision_cleanup(slug: str = "", older_than_days: int = 7) -> dict:
    if not VISION_OUTPUT_ROOT.exists():
        return {"status": "ok", "deleted": [], "freed_bytes": 0,
                "note": "no artifact root yet"}
    deleted, freed = [], 0
    for d in sorted(VISION_OUTPUT_ROOT.iterdir()):
        if not d.is_dir():
            continue
        if slug and d.name != slug:
            continue
        if not slug and (time.time() - d.stat().st_mtime) < older_than_days * 86400:
            continue
        size = sum(p.stat().st_size for p in d.rglob("*") if p.is_file())
        shutil.rmtree(d, ignore_errors=True)
        deleted.append(d.name)
        freed += size
    return {"status": "ok", "deleted": deleted, "freed_bytes": freed}


@mcp.tool(
    name="vision_probe",
    description=(
        "Ops: probe the vision model's image cap + latency via LiteLLM "
        "(sends n tiny images; the 400 error reveals the cap). Use after "
        "model/provider changes."
    ),
)
async def vision_probe(n: int = 6) -> dict:
    import struct
    import zlib

    def png1x1() -> str:
        ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)

        def chunk(tag: bytes, data: bytes) -> bytes:
            return (struct.pack(">I", len(data)) + tag + data
                    + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

        raw = b"\x00" + bytes((255, 0, 0))
        png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
               + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
        return base64.b64encode(png).decode()

    content = [{"type": "text", "text": "Reply with the single word OK."}]
    for _ in range(n):
        content.append({"type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,"
                                              f"{png1x1()}"}})
    body = {"model": VISION_MODEL, "max_tokens": 5,
            "messages": [{"role": "user", "content": content}]}
    t0 = time.monotonic()
    try:
        with httpx.Client(timeout=60) as client:
            r = client.post(
                f"{LITELLM_API_BASE}/chat/completions",
                headers={"Authorization": f"Bearer {LITELLM_API_KEY}",
                         "Content-Type": "application/json"},
                json=body,
            )
        dt = time.monotonic() - t0
        if r.status_code == 400:
            m = re.search(r"At most (\d+) image", r.text)
            return {"status": "ok", "model": VISION_MODEL,
                    "cap": int(m.group(1)) if m else None,
                    "latency_s": round(dt, 2), "raw": r.text[:200]}
        return {"status": "ok", "model": VISION_MODEL, "cap": f">= {n}",
                "latency_s": round(dt, 2),
                "note": "accepted n images; raise n to find the exact cap"}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


def main() -> None:
    """Run the MCP vision server over streamable-http transport."""
    logging.basicConfig(level=logging.INFO)
    logger.info("Starting mcp_vision")
    logger.info("LiteLLM: %s model=%s max_images=%d",
                LITELLM_API_BASE, VISION_MODEL, VISION_MAX_IMAGES)
    logger.info("Output root: %s (allowed roots: %s)",
                VISION_OUTPUT_ROOT, [str(r) for r in VISION_ALLOWED_ROOTS])
    if shutil.which("ffmpeg") is None:
        logger.error("ffmpeg not found in PATH — extraction will fail")
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()