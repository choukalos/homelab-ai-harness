#!/usr/bin/env python3
"""MCP Media Server — GPU-host media-pipeline flows.

Tools (GPU-host media-pipeline service, MEDIA_PIPELINE_URL, :8189 on Matrix):
  - media_storyboard(brief, n_shots, aspect)       LLM shot list (JSON)
  - media_generate_image(prompt, ...)              Text -> keyframe image
  - media_edit_image(image, prompt, ...)           Image + text -> edited image
  - media_generate_shot(keyframe, prompt, ...)     Keyframe -> ~4s I2V clip
  - media_text_to_speech(text, voice)              Script -> voice-over wav
  - media_generate_music(prompt, lyrics, ...)      Prompt -> song/instrumental
  - media_sfx(video, description, duration)        Video -> synced SFX bed
  - media_upscale_video(video, pipeline, ...)      Video -> upscaled (SeedVR2 / 4xUltrasharp)
  - media_assemble(shots, vo, music, sfx, ...)     Concat + mix -> final mp4
  - media_fetch(host_path, subdirectory)          Download a pipeline result locally

All GPU work happens on the pipeline host (ComfyUI + VLLM + TTS/music/SFX
workers); this container only POSTs jobs, polls, and downloads results.
Jobs block until done (per-flow timeouts up to 2h).

Path model (Thor has NO shared filesystem with the GPU host):
  - pipeline tools return GPU-HOST paths (required so media_assemble can chain)
  - media_fetch downloads any result to MEDIA_PIPELINE_FETCH_DIR (local)
  - tools taking local-file inputs auto-fetch GPU-host paths before uploading

Transport: streamable-http (HTTP, default 0.0.0.0:8000)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import List, Optional

from mcp.server import FastMCP
from mcp.server.fastmcp import Context

from media_pipeline_client import MediaPipelineClient, _JOB_PREFIX

logger = logging.getLogger("mcp_media")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MCPS_HOST: str = os.environ.get("MCPS_HOST", "0.0.0.0")

# GPU-host media-pipeline (2026-08-28): ComfyUI + VLLM + TTS/music/SFX workers.
# Thin HTTP client — all GPU work happens on the pipeline host.
PIPELINE = MediaPipelineClient()
# Where media_fetch downloads results (local media library).
PIPELINE_FETCH_DIR: str = os.environ.get(
    "MEDIA_PIPELINE_FETCH_DIR", "/home/chuck/data/media/generated/pipeline"
)

# ---------------------------------------------------------------------------
# Identity threading (same pattern as mcp_memory)
# ---------------------------------------------------------------------------
# When a call routes through LiteLLM (pi -> /mcp-rest/tools/call -> mcp_media),
# the caller's LiteLLM API key is forwarded in the Authorization header.
# We resolve key -> user via the proxy's /key/info and stamp the job with it,
# so the GPU-host pipeline can attribute work + cost per user.
LITELLM_PROXY_URL: str = os.environ.get(
    "LITELLM_PROXY_URL", "http://litellm-proxy:4000").rstrip("/")
# Fallback identity when no Authorization header is present (e.g. pi connecting
# directly). Single value — this deployment serves Chuck.
MEDIA_USER: str = os.environ.get("MEDIA_USER", "unknown")
# Calling-app label stamped on jobs (pipeline defaults to "mcp" if absent).
MEDIA_CLIENT: str = os.environ.get("MEDIA_CLIENT", "pi")
_USER_CACHE: dict[str, str] = {}


def _caller_key(ctx: Optional[Context]) -> Optional[str]:
    """Extract the caller's API key from the forwarded Authorization header."""
    try:
        request = ctx.request_context.request
        auth = request.headers.get("authorization")
        if not auth:
            return None
        if auth.lower().startswith("bearer "):
            return auth[7:].strip()
        return auth.strip()
    except Exception:  # no request context / not an HTTP request
        return None


def _resolve_user(ctx: Optional[Context]) -> str:
    """key -> user via LiteLLM /key/info (cached); fallback MEDIA_USER."""
    key = _caller_key(ctx)
    if not key:
        return MEDIA_USER
    if key in _USER_CACHE:
        return _USER_CACHE[key]
    try:
        req = urllib.request.Request(
            f"{LITELLM_PROXY_URL}/key/info",
            headers={"Authorization": f"Bearer {key}"})
        with urllib.request.urlopen(req, timeout=5) as r:
            info = json.loads(r.read()).get("info", {})
        user = (info.get("user_id") or "").strip()
        if user:
            _USER_CACHE[key] = user
            return user
        logger.warning("key/info returned no user_id; falling back to %r", MEDIA_USER)
    except Exception as exc:
        logger.warning("key->user resolution failed (%s); falling back to %r",
                       exc, MEDIA_USER)
    return MEDIA_USER

# ---------------------------------------------------------------------------
# FastMCP instance
# ---------------------------------------------------------------------------

mcp = FastMCP(
    name="mcp_media",
    instructions=(
        "Media operations via the GPU-host media-pipeline (blocking; jobs run "
        "serially on the GPU host). Typical flow: media_storyboard -> per-shot "
        "media_generate_image + media_generate_shot -> media_text_to_speech + "
        "media_generate_music -> media_upscale_video (pipeline='b') -> "
        "media_assemble -> media_fetch the final mp4.\n"
        "PATH MODEL: tools return GPU-HOST paths. Pass them straight to "
        "media_assemble or other pipeline tools (inputs are auto-fetched); call "
        f"media_fetch to download a result to the local media library "
        f"({PIPELINE_FETCH_DIR})."
    ),
    host=MCPS_HOST,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_HOST_PATH_NOTE = (
    "GPU-HOST path (Matrix). Pass it directly to media_assemble or other "
    "pipeline tools (inputs are auto-fetched), or call media_fetch to "
    "download it to the local media library."
)


def _is_host_path(path: str) -> bool:
    """True if path points into the GPU host's pipeline job dir."""
    return path.startswith(_JOB_PREFIX)


async def _ensure_local(path: str) -> str:
    """Return a locally-readable path: download GPU-host paths to a temp dir."""
    if _is_host_path(path):
        tmpdir = tempfile.mkdtemp(prefix="mcp_media_in_")
        return await asyncio.to_thread(PIPELINE.fetch, path, tmpdir)
    return path


def _pipeline_error(exc: Exception, context: dict) -> dict:
    """Structured error dict for pipeline failures."""
    out = dict(context)
    if isinstance(exc, urllib.error.HTTPError):
        try:
            body = json.loads(exc.read().decode("utf-8", "replace"))
        except Exception:
            body = {}
        if exc.code == 503:
            out["error"] = "Pipeline queue full (HTTP 503) — GPU host is busy."
            if body.get("retry_after_seconds") is not None:
                out["retry_after_seconds"] = body["retry_after_seconds"]
            out["hint"] = "Wait retry_after_seconds, then retry the same call."
            return out
        out["error"] = f"Pipeline HTTP {exc.code}: {body or exc.reason}"
        return out
    out["error"] = str(exc)
    return out


# ---------------------------------------------------------------------------
# Pipeline tools
# ---------------------------------------------------------------------------


@mcp.tool(
    name="media_storyboard",
    description=(
        "Generate a cinematic shot list (JSON) for a commercial/video from a brief, "
        "via the GPU-host media pipeline. Returns {\"shots\": [{id, visual, vo}, ...]}."
    ),
)
async def media_storyboard(brief: str, n_shots: int = 5, aspect: str = "16:9",
                           ctx: Context = None) -> dict:
    """LLM shot list from a brief (GPU-host VLLM)."""
    user = await asyncio.to_thread(_resolve_user, ctx)
    try:
        return await asyncio.to_thread(PIPELINE.storyboard, brief, n_shots, aspect,
                                       user=user, client=MEDIA_CLIENT)
    except Exception as exc:
        return _pipeline_error(exc, {"brief": brief})


@mcp.tool(
    name="media_generate_image",
    description=(
        "Generate an image (keyframe) from a text prompt via the GPU-host media "
        "pipeline. Returns {path, location='gpu_host'}: the path is ON THE GPU HOST — "
        "pass it directly to media_generate_shot/media_assemble (auto-fetched) or "
        "call media_fetch to download it locally."
    ),
)
async def media_generate_image(
    prompt: str,
    width: int = 1280,
    height: int = 720,
    seed: int = 42,
    steps: int = 4,
    ctx: Context = None,
) -> dict:
    """Text -> keyframe image (GPU host)."""
    user = await asyncio.to_thread(_resolve_user, ctx)
    try:
        path = await asyncio.to_thread(
            PIPELINE.generate_image, prompt, width, height, seed, steps,
            user=user, client=MEDIA_CLIENT
        )
    except Exception as exc:
        return _pipeline_error(exc, {"prompt": prompt})
    return {"path": path, "location": "gpu_host", "note": _HOST_PATH_NOTE}


@mcp.tool(
    name="media_edit_image",
    description=(
        "Edit an image (e.g. compose a consistent keyframe) via the GPU-host media "
        "pipeline. `image` may be a local path OR a GPU-host path (auto-fetched). "
        "Returns {path, location='gpu_host'}."
    ),
)
async def media_edit_image(image: str, prompt: str, seed: int = 42, steps: int = 8,
                           ctx: Context = None) -> dict:
    """Image + text -> edited image (GPU host)."""
    user = await asyncio.to_thread(_resolve_user, ctx)
    try:
        local_image = await _ensure_local(image)
        if not os.path.isfile(local_image):
            return {"error": f"Image not found (local or on GPU host): {image}"}
        path = await asyncio.to_thread(PIPELINE.edit_image, local_image, prompt, seed, steps,
                                       user=user, client=MEDIA_CLIENT)
    except Exception as exc:
        return _pipeline_error(exc, {"image": image, "prompt": prompt})
    return {"path": path, "location": "gpu_host", "note": _HOST_PATH_NOTE}


@mcp.tool(
    name="media_generate_shot",
    description=(
        "Animate a keyframe into a ~4s video clip (LTXV I2V) via the GPU-host media "
        "pipeline. `keyframe` may be a local image path OR a GPU-host path (auto-"
        "fetched). `prompt` should describe VISUAL STYLE (not fast motion) to "
        "minimize warble. `strength` = how strongly the keyframe anchors the clip "
        "(lower = less warble; 0.7 is the tuned default). Returns {path, "
        "location='gpu_host'}."
    ),
)
async def media_generate_shot(
    keyframe: str,
    prompt: str,
    width: int = 768,
    height: int = 512,
    frames: int = 97,
    fps: float = 24.0,
    seed: int = 42,
    strength: float = 0.7,
    ctx: Context = None,
) -> dict:
    """Keyframe -> ~4s I2V clip (GPU host)."""
    user = await asyncio.to_thread(_resolve_user, ctx)
    try:
        local_kf = await _ensure_local(keyframe)
        if not os.path.isfile(local_kf):
            return {"error": f"Keyframe not found (local or on GPU host): {keyframe}"}
        path = await asyncio.to_thread(
            PIPELINE.generate_shot, local_kf, prompt, width, height, frames, fps,
            seed, strength, user=user, client=MEDIA_CLIENT,
        )
    except Exception as exc:
        return _pipeline_error(exc, {"keyframe": keyframe, "prompt": prompt})
    return {"path": path, "location": "gpu_host", "note": _HOST_PATH_NOTE}


@mcp.tool(
    name="media_text_to_speech",
    description=(
        "Generate voice-over speech via the GPU-host media pipeline (movie-trailer "
        "voice by default; `voice` can also be a path to a custom reference wav on "
        "the GPU host). Returns {path, location='gpu_host'}."
    ),
)
async def media_text_to_speech(text: str, voice: str = "trailer",
                               ctx: Context = None) -> dict:
    """Script -> voice-over wav (GPU host)."""
    user = await asyncio.to_thread(_resolve_user, ctx)
    try:
        path = await asyncio.to_thread(PIPELINE.text_to_speech, text, voice,
                                       user=user, client=MEDIA_CLIENT)
    except Exception as exc:
        return _pipeline_error(exc, {"text": text[:80], "voice": voice})
    return {"path": path, "location": "gpu_host", "note": _HOST_PATH_NOTE}


@mcp.tool(
    name="media_generate_music",
    description=(
        "Generate music or a song (ACE-Step) via the GPU-host media pipeline. "
        "`lyrics` optional. Returns {path, location='gpu_host'}."
    ),
)
async def media_generate_music(prompt: str, lyrics: str = "", duration: int = 30, seed: int = 42,
                               ctx: Context = None) -> dict:
    """Prompt (+lyrics) -> song/instrumental wav (GPU host)."""
    user = await asyncio.to_thread(_resolve_user, ctx)
    try:
        path = await asyncio.to_thread(PIPELINE.generate_music, prompt, lyrics, duration, seed,
                                       user=user, client=MEDIA_CLIENT)
    except Exception as exc:
        return _pipeline_error(exc, {"prompt": prompt})
    return {"path": path, "location": "gpu_host", "note": _HOST_PATH_NOTE}


@mcp.tool(
    name="media_sfx",
    description=(
        "Generate an SFX bed synced to a video clip (MMAudio) via the GPU-host media "
        "pipeline. `video` may be a local path OR a GPU-host path (auto-fetched). "
        "Returns {path, location='gpu_host'}."
    ),
)
async def media_sfx(video: str, description: str = "", duration: float = 8.0,
                    ctx: Context = None) -> dict:
    """Video -> synced SFX bed (GPU host)."""
    user = await asyncio.to_thread(_resolve_user, ctx)
    try:
        local_video = await _ensure_local(video)
        if not os.path.isfile(local_video):
            return {"error": f"Video not found (local or on GPU host): {video}"}
        path = await asyncio.to_thread(PIPELINE.sfx, local_video, description, duration,
                                       user=user, client=MEDIA_CLIENT)
    except Exception as exc:
        return _pipeline_error(exc, {"video": video})
    return {"path": path, "location": "gpu_host", "note": _HOST_PATH_NOTE}


@mcp.tool(
    name="media_upscale_video",
    description=(
        "Upscale a video to 1080p via the GPU-host media pipeline. `video` may be a "
        "local path OR a GPU-host path (auto-fetched). pipeline: 'b' = SeedVR2 "
        "(quality, ~5 min), 'a2' = 4xUltrasharp (fast, ~1 min). Returns "
        "{path, location='gpu_host'}."
    ),
)
async def media_upscale_video(
    video: str,
    pipeline: str = "b",
    resolution: int = 1080,
    noise_scale: float = 0.0,
    seed: int = 42,
    ctx: Context = None,
) -> dict:
    """Video -> upscaled (GPU host)."""
    user = await asyncio.to_thread(_resolve_user, ctx)
    try:
        local_video = await _ensure_local(video)
        if not os.path.isfile(local_video):
            return {"error": f"Video not found (local or on GPU host): {video}"}
        path = await asyncio.to_thread(
            PIPELINE.upscale, local_video, pipeline, resolution, noise_scale, seed,
            user=user, client=MEDIA_CLIENT
        )
    except Exception as exc:
        return _pipeline_error(exc, {"video": video, "pipeline": pipeline})
    return {"path": path, "location": "gpu_host", "note": _HOST_PATH_NOTE}


@mcp.tool(
    name="media_assemble",
    description=(
        "Concat video shots and mix VO + music + SFX into a final mp4 via the "
        "GPU-host media pipeline. `shots` MUST be GPU-host paths (as returned by "
        "media_generate_shot / media_upscale_video) — do NOT pass locally downloaded "
        "paths. vo/music/sfx are optional GPU-host paths. For 1080p quality, B-upscale "
        "each shot first. Returns {path, location='gpu_host'}; call media_fetch to "
        "download the final mp4."
    ),
)
async def media_assemble(
    shots: List[str],
    vo: str = "",
    music: str = "",
    sfx: str = "",
    width: int = 1920,
    height: int = 1080,
    fps: int = 24,
    vo_volume: float = 1.0,
    music_volume: float = 0.35,
    sfx_volume: float = 0.9,
    ctx: Context = None,
) -> dict:
    """Concat shots + mix audio -> final mp4 (GPU host)."""
    user = await asyncio.to_thread(_resolve_user, ctx)
    try:
        path = await asyncio.to_thread(
            PIPELINE.assemble, shots, vo or None, music or None, sfx or None,
            width, height, fps, vo_volume, music_volume, sfx_volume,
            user=user, client=MEDIA_CLIENT,
        )
    except Exception as exc:
        return _pipeline_error(exc, {"shots": shots})
    return {"path": path, "location": "gpu_host", "note": _HOST_PATH_NOTE}


@mcp.tool(
    name="media_fetch",
    description=(
        "Download a media-pipeline result from the GPU host to the local media "
        "library (MEDIA_PIPELINE_FETCH_DIR, default "
        f"{PIPELINE_FETCH_DIR}) and return the local path. Use this to deliver the "
        "final artifact (or any intermediate) to the user / other local tools."
    ),
)
async def media_fetch(host_path: str, subdirectory: str = "") -> dict:
    """GPU-host path -> local file."""
    if not _is_host_path(host_path):
        return {
            "error": (
                f"Not a GPU-host pipeline path: {host_path}. "
                "media_fetch downloads pipeline results (paths starting with "
                f"{_JOB_PREFIX})."
            )
        }
    dest = PIPELINE_FETCH_DIR if not subdirectory else os.path.join(
        PIPELINE_FETCH_DIR, subdirectory
    )
    try:
        local = await asyncio.to_thread(PIPELINE.fetch, host_path, dest)
        return {
            "local_path": local,
            "host_path": host_path,
            "size_bytes": os.path.getsize(local),
        }
    except Exception as exc:
        return _pipeline_error(exc, {"host_path": host_path})


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Run the MCP media server over streamable-http transport."""
    logging.basicConfig(level=logging.INFO)
    logger.info("Starting mcp_media")
    logger.info("Media pipeline URL: %s", PIPELINE.base)
    logger.info("Pipeline fetch directory: %s", PIPELINE_FETCH_DIR)
    logger.info("Identity: LITELLM_PROXY_URL=%s MEDIA_USER=%s MEDIA_CLIENT=%s",
                LITELLM_PROXY_URL, MEDIA_USER, MEDIA_CLIENT)
    try:
        health = asyncio.run(asyncio.to_thread(PIPELINE.health))
        logger.info("Pipeline health: %s", health)
    except Exception as exc:
        logger.warning("Pipeline not reachable at startup: %s", exc)
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()