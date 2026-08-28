#!/usr/bin/env python3
"""MCP Media Server — GPU-host media pipeline + legacy image tools.

Pipeline tools (GPU-host media-pipeline service, MEDIA_PIPELINE_URL, :8189):
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

Legacy tools (kept until the old ComfyUI/HF flows are decommissioned):
  - generate_image(prompt, model, size, n)        Generate image(s) via HF/ComfyUI
  - edit_image(image_path, prompt, mask_path)     Edit image via LiteLLM proxy (stub)
  - image_info(path)                              Get image metadata via Pillow
  - list_images(directory)                        List image files in a directory

Path model (Thor has NO shared filesystem with the GPU host):
  - pipeline tools return GPU-HOST paths (required so media_assemble can chain)
  - media_fetch downloads any result to MEDIA_PIPELINE_FETCH_DIR (local)
  - tools taking local-file inputs auto-fetch GPU-host paths before uploading

Transport: streamable-http (HTTP, default 0.0.0.0:8000)
"""

import asyncio
import os
import json
import logging
import tempfile
import urllib.error
from pathlib import Path
from typing import Optional, List

import httpx
from mcp.server import FastMCP

from media_pipeline_client import MediaPipelineClient, _JOB_PREFIX

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

LITELLM_BASE_URL: str = os.environ.get(
    "LITELLM_BASE_URL", "http://litellm-proxy:4000"
)
LITELLM_API_KEY: str = os.environ.get("LITELLM_API_KEY", "")
LITELLM_HTTP_TIMEOUT: float = float(os.environ.get("LITELLM_TIMEOUT", "120"))

# Hugging Face Inference API
HF_API_BASE: str = os.environ.get(
    "HF_API_BASE", "https://api-inference.huggingface.co"
)
HF_TOKEN: str = os.environ.get("HF_TOKEN", "")
HF_MODEL_ID: str = os.environ.get(
    "HF_MODEL_ID", "stabilityai/stable-diffusion-3-medium"
)
HF_HTTP_TIMEOUT: float = float(os.environ.get("HF_TIMEOUT", "120"))

# ComfyUI (fallback when HF rate-limits)
COMFYUI_BASE_URL: str = os.environ.get(
    "COMFYUI_BASE_URL", "http://192.168.4.55:8188"
)
COMFYUI_HTTP_TIMEOUT: float = float(os.environ.get("COMFYUI_TIMEOUT", "180"))

# GPU-host media-pipeline (2026-08-28): ComfyUI + VLLM + TTS/music/SFX workers.
# Thin HTTP client — all GPU work happens on the pipeline host.
PIPELINE = MediaPipelineClient()
# Where media_fetch downloads results (local media library).
PIPELINE_FETCH_DIR: str = os.environ.get(
    "MEDIA_PIPELINE_FETCH_DIR", "/home/chuck/data/media/generated/pipeline"
)

MEDIA_OUTPUT_DIR: str = os.environ.get(
    "MEDIA_OUTPUT_DIR", "/home/chuck/data/media/generated"
)
# Image formats to recognize for list_images
IMAGE_EXTENSIONS: set[str] = {
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tiff", ".tif",
}

logger = logging.getLogger("mcp_media")


# ---------------------------------------------------------------------------
# Image generation — HF Inference API (primary)
# ---------------------------------------------------------------------------


async def _call_hf_generate(prompt: str) -> dict:
    """Call Hugging Face Inference API for image generation.

    Returns a dict with b64_json key for compatibility with _save_generated_image.
    """
    import base64

    url = f"{HF_API_BASE}/models/{HF_MODEL_ID}"
    headers = {
        "Authorization": f"Bearer {HF_TOKEN}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=HF_HTTP_TIMEOUT) as client:
        resp = await client.post(url, json={"inputs": prompt}, headers=headers)
        if resp.status_code == 429:
            raise RuntimeError(
                "Hugging Face rate limit hit (429). "
                "Try again later or spin up ComfyUI for continued use."
            )
        resp.raise_for_status()
        # HF returns binary PNG by default
        b64_json = base64.b64encode(resp.content).decode("utf-8")
        saved_paths = _save_generated_image_from_bytes(resp.content, prompt)
        return {
            "data": [{"b64_json": b64_json}],
            "model": HF_MODEL_ID,
            "prompt": prompt,
            "saved_paths": saved_paths,
        }


# ---------------------------------------------------------------------------
# Image generation — ComfyUI (fallback)
# ---------------------------------------------------------------------------


async def _call_comfyui_generate(prompt: str) -> dict:
    """Call ComfyUI API for image generation (fallback when HF is rate-limited).

    Uses a minimal text-to-image workflow. Adjust workflow as needed.
    """
    import base64
    import uuid

    client_id = str(uuid.uuid4())

    workflow = {
        "3": {
            "class_type": "KSampler",
            "inputs": {
                "seed": 42,
                "steps": 20,
                "cfg": 7.0,
                "sampler_name": "euler",
                "scheduler": "normal",
                "denoise": 1.0,
                "model": ["4", 0],
                "positive": ["5", 0],
                "negative": ["6", 0],
                "latent_image": ["7", 0],
            },
        },
        "4": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "sd_xl_base_1.0.safetensors"},
        },
        "5": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": prompt, "clip": ["4", 1]},
        },
        "6": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": "blurry, bad quality", "clip": ["4", 1]},
        },
        "7": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": 1024, "height": 1024, "batch_size": 1},
        },
        "8": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["3", 0], "vae": ["4", 2]},
        },
        "9": {
            "class_type": "SaveImage",
            "inputs": {"images": ["8", 0], "filename_prefix": "comfyui"},
        },
    }

    headers = {"Content-Type": "application/json"}

    async with httpx.AsyncClient(timeout=COMFYUI_HTTP_TIMEOUT) as client:
        queue_resp = await client.post(
            f"{COMFYUI_BASE_URL}/prompt",
            json={"prompt": workflow, "client_id": client_id},
            headers=headers,
        )
        queue_resp.raise_for_status()
        prompt_id = queue_resp.json().get("prompt_id")

        # Poll history until complete (60s max)
        for _ in range(60):
            await asyncio.sleep(1)
            history_resp = await client.get(
                f"{COMFYUI_BASE_URL}/history/{prompt_id}", headers=headers
            )
            if history_resp.status_code == 200 and prompt_id in history_resp.json():
                history = history_resp.json()[prompt_id]
                outputs = history.get("outputs", {})
                for node_output in outputs.values():
                    if "images" in node_output:
                        img_info = node_output["images"][0]
                        img_url = (
                            f"{COMFYUI_BASE_URL}/view?"
                            f"filename={img_info['filename']}"
                            f"&subfolder={img_info.get('subfolder', '')}"
                            f"&type=output"
                        )
                        img_resp = await client.get(img_url)
                        img_resp.raise_for_status()
                        b64_json = base64.b64encode(img_resp.content).decode("utf-8")
                        saved_paths = _save_generated_image_from_bytes(
                            img_resp.content, prompt
                        )
                        return {
                            "data": [{"b64_json": b64_json}],
                            "model": "comfyui",
                            "prompt": prompt,
                            "saved_paths": saved_paths,
                        }
        raise RuntimeError("ComfyUI generation timed out")


# ---------------------------------------------------------------------------
# Image generation — LiteLLM proxy (legacy, DALL-E only)
# ---------------------------------------------------------------------------


def _build_litellm_headers() -> dict[str, str]:
    """Build headers for LiteLLM API requests."""
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if LITELLM_API_KEY:
        headers["Authorization"] = f"Bearer {LITELLM_API_KEY}"
    return headers


async def _call_litellm_generate(payload: dict) -> dict:
    """Call LiteLLM's /v1/images/generate endpoint.

    NOTE: This only works for OpenAI DALL-E models configured in LiteLLM.
    """
    url = f"{LITELLM_BASE_URL}/v1/images/generate"
    headers = _build_litellm_headers()

    async with httpx.AsyncClient(timeout=LITELLM_HTTP_TIMEOUT) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        return resp.json()


# ---------------------------------------------------------------------------
# Image saving
# ---------------------------------------------------------------------------


def _save_generated_image_from_bytes(image_bytes: bytes, prompt: str) -> list[str]:
    """Save generated image bytes to disk.

    Returns list of saved file paths.
    """
    os.makedirs(MEDIA_OUTPUT_DIR, exist_ok=True)
    safe_prompt = "".join(
        c if c.isalnum() or c in " -_" else "_" for c in prompt
    )[:50]
    filename = f"gen_{safe_prompt}.png"
    filepath = os.path.join(MEDIA_OUTPUT_DIR, filename)

    try:
        with open(filepath, "wb") as f:
            f.write(image_bytes)
        return [filepath]
    except Exception as exc:
        logger.error("Failed to save generated image: %s", exc)
        return [f"ERROR: {exc}"]


def _save_generated_image(data: dict, prompt: str) -> list[str]:
    """Save generated image(s) from response dict to disk.

    Handles both b64_json responses and pre-saved paths from direct backend calls.
    """
    # If already saved by the backend caller
    if "saved_paths" in data:
        return data["saved_paths"]

    os.makedirs(MEDIA_OUTPUT_DIR, exist_ok=True)
    saved: list[str] = []

    responses = data.get("data", [data])

    for idx, item in enumerate(responses):
        b64_json = item.get("b64_json")
        url = item.get("url")

        if b64_json:
            import base64

            safe_prompt = "".join(
                c if c.isalnum() or c in " -_" else "_" for c in prompt
            )[:50]
            filename = (
                f"gen_{safe_prompt}_{idx}.png"
                if idx > 0
                else f"gen_{safe_prompt}.png"
            )
            filepath = os.path.join(MEDIA_OUTPUT_DIR, filename)

            try:
                image_bytes = base64.b64decode(b64_json)
                with open(filepath, "wb") as f:
                    f.write(image_bytes)
                saved.append(filepath)
            except Exception as exc:
                logger.error("Failed to save generated image: %s", exc)
                saved.append(f"ERROR: {exc}")
        elif url:
            saved.append(url)

    return saved


# ---------------------------------------------------------------------------
# Image info (Pillow)
# ---------------------------------------------------------------------------


def _get_image_info(filepath: str) -> dict:
    """Get image metadata using Pillow."""
    from PIL import Image

    if not os.path.isfile(filepath):
        raise FileNotFoundError(f"Image file not found: '{filepath}'")

    try:
        with Image.open(filepath) as img:
            info = {
                "file": filepath,
                "filename": os.path.basename(filepath),
                "format": img.format or "unknown",
                "mode": img.mode,
                "size": list(img.size),
                "width": img.width,
                "height": img.height,
                "color_space": img.mode,
            }
            info["file_size_bytes"] = os.path.getsize(filepath)

            try:
                exif_data = img._getexif()
                if exif_data:
                    info["exif"] = {str(k): str(v) for k, v in exif_data.items()}
            except (AttributeError, Exception):
                pass

            return info
    except Exception as exc:
        raise RuntimeError(
            f"Cannot read image metadata for '{filepath}': {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------

MCPS_HOST: str = os.environ.get("MCPS_HOST", "0.0.0.0")

mcp = FastMCP(
    name="mcp_media",
    instructions=(
        "Media operations. Two families of tools:\n"
        "1) Pipeline (preferred for new work — GPU-host media-pipeline, blocking): "
        "media_storyboard, media_generate_image, media_edit_image, media_generate_shot, "
        "media_text_to_speech, media_generate_music, media_sfx, media_upscale_video, "
        "media_assemble, media_fetch. Typical flow: storyboard -> per-shot "
        "generate_image + generate_shot -> text_to_speech + generate_music -> "
        "upscale_video (pipeline='b') -> assemble -> media_fetch the final mp4.\n"
        "2) Legacy (old ComfyUI/HF flows, being decommissioned): generate_image, "
        "edit_image, image_info, list_images.\n"
        "PATH MODEL: pipeline tools return GPU-HOST paths. Pass them straight to "
        "media_assemble or other pipeline tools (inputs are auto-fetched); call "
        "media_fetch to download a result to the local media library "
        f"({PIPELINE_FETCH_DIR})."
    ),
    host=MCPS_HOST,
)


@mcp.tool(
    name="generate_image",
    description=(
        "Generate an image from a text prompt. "
        "Use 'comfyui' for ComfyUI (primary, local GPU), "
        "'hf-sd3' for Hugging Face (if accessible), "
        "or 'dall-e-3' for DALL-E via LiteLLM. "
        "Supported parameters: prompt, model, size, n."
    ),
)
async def generate_image(
    prompt: str,
    model: str = "comfyui",
    size: str = "1024x1024",
    n: int = 1,
) -> dict:
    """Generate image(s) from a text prompt.

    Routes to the appropriate backend based on model name:
      - comfyui* → ComfyUI (primary, local GPU on Matrix)
      - hf-* → Hugging Face Inference API (if accessible)
      - other → LiteLLM proxy (DALL-E only)
    """
    try:
        if model.startswith("comfyui"):
            data = await _call_comfyui_generate(prompt)
        elif model.startswith("hf-"):
            data = await _call_hf_generate(prompt)
        else:
            # LiteLLM proxy (legacy)
            payload = {
                "prompt": prompt,
                "model": model,
                "size": size,
                "n": n,
                "response_format": "b64_json",
            }
            data = await _call_litellm_generate(payload)

        saved_paths = _save_generated_image(data, prompt)
        return {
            "prompt": prompt,
            "model": model,
            "size": size,
            "n": n,
            "saved_paths": saved_paths,
            "response": data,
        }
    except RuntimeError as exc:
        # Check if this is an HF rate-limit error — try ComfyUI fallback
        if "rate limit" in str(exc).lower() and model.startswith("hf-"):
            logger.info("HF rate-limited, falling back to ComfyUI...")
            try:
                data = await _call_comfyui_generate(prompt)
                saved_paths = _save_generated_image(data, prompt)
                return {
                    "prompt": prompt,
                    "model": "comfyui",
                    "size": size,
                    "n": n,
                    "saved_paths": saved_paths,
                    "response": data,
                    "note": "Fallback to ComfyUI due to HF rate limit",
                }
            except Exception as fallback_exc:
                return {
                    "prompt": prompt,
                    "model": model,
                    "size": size,
                    "n": n,
                    "error": str(exc),
                    "fallback_error": str(fallback_exc),
                }
        return {
            "prompt": prompt,
            "model": model,
            "size": size,
            "n": n,
            "error": str(exc),
        }


@mcp.tool(
    name="edit_image",
    description=(
        "Edit an existing image based on a text prompt via LiteLLM proxy. "
        "STUB: implements /v1/images/edits call but actual support depends "
        "on the backend model. Requires an image file path and optional mask."
    ),
)
async def edit_image(
    image_path: str,
    prompt: str,
    mask_path: Optional[str] = None,
    model: str = "dall-e-2",
    size: str = "1024x1024",
    n: int = 1,
) -> dict:
    """Edit an existing image via LiteLLM proxy.

    This is a stub implementation. Actual editing support depends on the
    backend model configured in LiteLLM.
    """
    if not os.path.isfile(image_path):
        raise FileNotFoundError(f"Image file not found: '{image_path}'")

    if mask_path and not os.path.isfile(mask_path):
        raise FileNotFoundError(f"Mask file not found: '{mask_path}'")

    url = f"{LITELLM_BASE_URL}/v1/images/edits"
    headers = _build_litellm_headers()

    try:
        async with httpx.AsyncClient(timeout=LITELLM_HTTP_TIMEOUT) as client:
            with open(image_path, "rb") as f:
                image_data = f.read()

            files = {
                "image": (os.path.basename(image_path), image_data, "image/png"),
            }

            if mask_path:
                with open(mask_path, "rb") as f:
                    mask_data = f.read()
                files["mask"] = (os.path.basename(mask_path), mask_data, "image/png")

            data = {
                "prompt": prompt,
                "model": model,
                "size": size,
                "n": n,
            }

            resp = await client.post(url, files=files, data=data, headers=headers)
            resp.raise_for_status()
            result = resp.json()

            saved_paths = _save_generated_image(result, prompt)
            return {
                "image_path": image_path,
                "mask_path": mask_path,
                "prompt": prompt,
                "model": model,
                "saved_paths": saved_paths,
                "response": result,
            }
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "Image edits endpoint returned %d — backend may not support edits: %s",
            exc.response.status_code,
            exc.response.text,
        )
        return {
            "image_path": image_path,
            "prompt": prompt,
            "status": "stub",
            "message": (
                "Image editing via /v1/images/edits is a stub. "
                f"Backend returned {exc.response.status_code}. "
                "Actual editing support depends on the model configured in LiteLLM."
            ),
        }
    except Exception as exc:
        return {
            "image_path": image_path,
            "prompt": prompt,
            "status": "stub",
            "message": (
                "Image editing via /v1/images/edits is a stub. "
                f"Request failed: {exc}. "
                "Actual editing support depends on the model configured in LiteLLM."
            ),
        }


@mcp.tool(
    name="image_info",
    description="Get image metadata (format, dimensions, color space, file size) using Pillow.",
)
def image_info(path: str) -> dict:
    """Get metadata for an image file using Pillow."""
    return _get_image_info(path)


@mcp.tool(
    name="list_images",
    description="List image files in a directory. Scans for common image extensions.",
)
def list_images(directory: str = "") -> list[dict]:
    """List image files in a directory."""
    search_dir = directory if directory else MEDIA_OUTPUT_DIR

    if not os.path.isdir(search_dir):
        return []

    results = []
    try:
        from PIL import Image

        for entry in sorted(os.listdir(search_dir)):
            full_path = os.path.join(search_dir, entry)

            if not os.path.isfile(full_path):
                continue

            if os.path.splitext(entry)[1].lower() not in IMAGE_EXTENSIONS:
                continue

            try:
                with Image.open(full_path) as img:
                    results.append({
                        "filename": entry,
                        "path": full_path,
                        "format": img.format or "unknown",
                        "size": [img.width, img.height],
                        "width": img.width,
                        "height": img.height,
                        "file_size_bytes": os.path.getsize(full_path),
                    })
            except Exception:
                results.append({
                    "filename": entry,
                    "path": full_path,
                    "format": "unknown",
                    "size": [0, 0],
                    "width": 0,
                    "height": 0,
                    "file_size_bytes": os.path.getsize(full_path),
                    "error": "Could not read image",
                })

    except PermissionError as exc:
        raise PermissionError(
            f"Cannot read directory '{search_dir}': {exc}"
        ) from exc

    return results


# ---------------------------------------------------------------------------
# Media pipeline (GPU host) — new flows (2026-08-28)
# ---------------------------------------------------------------------------
# The pipeline client is stdlib-only and BLOCKS until the GPU job finishes.
# We run it in worker threads so the async event loop stays free, and surface
# failures as structured dicts (the LLM gets a useful error, not a crash).


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


@mcp.tool(
    name="media_storyboard",
    description=(
        "Generate a cinematic shot list (JSON) for a commercial/video from a brief, "
        "via the GPU-host media pipeline. Returns {\"shots\": [{id, visual, vo}, ...]}."
    ),
)
async def media_storyboard(brief: str, n_shots: int = 5, aspect: str = "16:9") -> dict:
    """LLM shot list from a brief (GPU-host VLLM)."""
    try:
        return await asyncio.to_thread(PIPELINE.storyboard, brief, n_shots, aspect)
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
) -> dict:
    """Text -> keyframe image (GPU host)."""
    try:
        path = await asyncio.to_thread(
            PIPELINE.generate_image, prompt, width, height, seed, steps
        )
    except Exception as exc:
        return _pipeline_error(exc, {"prompt": prompt})
    return {"path": path, "location": "gpu_host", "note": _HOST_PATH_NOTE}


@mcp.tool(
    name="media_edit_image",
    description=(
        "Edit an image (e.g. compose a consistent keyframe from a character sheet) "
        "via the GPU-host media pipeline. `image` may be a local path OR a GPU-host "
        "path (auto-fetched). Returns {path, location='gpu_host'}."
    ),
)
async def media_edit_image(
    image: str,
    prompt: str,
    seed: int = 42,
    steps: int = 8,
) -> dict:
    """Image + text -> edited image (GPU host)."""
    try:
        local_image = await _ensure_local(image)
        if not os.path.isfile(local_image):
            return {"error": f"Image not found (local or on GPU host): {image}"}
        path = await asyncio.to_thread(PIPELINE.edit_image, local_image, prompt, seed, steps)
    except Exception as exc:
        return _pipeline_error(exc, {"image": image, "prompt": prompt})
    return {"path": path, "location": "gpu_host", "note": _HOST_PATH_NOTE}


@mcp.tool(
    name="media_generate_shot",
    description=(
        "Animate a keyframe into a ~4s video clip (LTXV I2V) via the GPU-host media "
        "pipeline. `keyframe` may be a local path OR a GPU-host path (auto-fetched). "
        "`prompt` should describe VISUAL STYLE (not fast motion) to minimize warble. "
        "`strength` = how strongly the keyframe anchors the clip (lower = less "
        "warble; 0.7 is the tuned default). Returns {path, location='gpu_host'}."
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
) -> dict:
    """Keyframe + style prompt -> ~4s I2V clip (GPU host)."""
    try:
        local_kf = await _ensure_local(keyframe)
        if not os.path.isfile(local_kf):
            return {"error": f"Keyframe not found (local or on GPU host): {keyframe}"}
        path = await asyncio.to_thread(
            PIPELINE.generate_shot, local_kf, prompt, width, height, frames, fps, seed, strength
        )
    except Exception as exc:
        return _pipeline_error(exc, {"keyframe": keyframe, "prompt": prompt})
    return {"path": path, "location": "gpu_host", "note": _HOST_PATH_NOTE}


@mcp.tool(
    name="media_text_to_speech",
    description=(
        "Generate voice-over speech via the GPU-host media pipeline (movie-trailer "
        "voice by default). Returns {path, location='gpu_host'} (wav)."
    ),
)
async def media_text_to_speech(text: str, voice: str = "trailer") -> dict:
    """Script -> voice-over wav (GPU host)."""
    try:
        path = await asyncio.to_thread(PIPELINE.text_to_speech, text, voice)
    except Exception as exc:
        return _pipeline_error(exc, {"voice": voice})
    return {"path": path, "location": "gpu_host", "note": _HOST_PATH_NOTE}


@mcp.tool(
    name="media_generate_music",
    description=(
        "Generate music or a song (ACE-Step) via the GPU-host media pipeline. "
        "`lyrics` optional. Returns {path, location='gpu_host'} (wav)."
    ),
)
async def media_generate_music(
    prompt: str, lyrics: str = "", duration: int = 30, seed: int = 42
) -> dict:
    """Prompt(+lyrics) -> song/instrumental wav (GPU host)."""
    try:
        path = await asyncio.to_thread(PIPELINE.generate_music, prompt, lyrics, duration, seed)
    except Exception as exc:
        return _pipeline_error(exc, {"prompt": prompt})
    return {"path": path, "location": "gpu_host", "note": _HOST_PATH_NOTE}


@mcp.tool(
    name="media_sfx",
    description=(
        "Generate an SFX bed synced to a video clip (MMAudio) via the GPU-host media "
        "pipeline. `video` may be a local path OR a GPU-host path (auto-fetched). "
        "Returns {path, location='gpu_host'} (audio)."
    ),
)
async def media_sfx(video: str, description: str = "", duration: float = 8.0) -> dict:
    """Video -> synced SFX bed (GPU host)."""
    try:
        local_video = await _ensure_local(video)
        if not os.path.isfile(local_video):
            return {"error": f"Video not found (local or on GPU host): {video}"}
        path = await asyncio.to_thread(PIPELINE.sfx, local_video, description, duration)
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
) -> dict:
    """Video -> upscaled (GPU host)."""
    try:
        local_video = await _ensure_local(video)
        if not os.path.isfile(local_video):
            return {"error": f"Video not found (local or on GPU host): {video}"}
        path = await asyncio.to_thread(
            PIPELINE.upscale, local_video, pipeline, resolution, noise_scale, seed
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
) -> dict:
    """Concat shots + mix audio -> final mp4 (GPU host)."""
    try:
        path = await asyncio.to_thread(
            PIPELINE.assemble, shots, vo or None, music or None, sfx or None,
            width, height, fps, vo_volume, music_volume, sfx_volume,
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
    logger.info("HF model: %s", HF_MODEL_ID)
    logger.info("ComfyUI URL: %s", COMFYUI_BASE_URL)
    logger.info("Media output directory: %s", MEDIA_OUTPUT_DIR)
    logger.info("Media pipeline URL: %s", PIPELINE.base)
    logger.info("Pipeline fetch directory: %s", PIPELINE_FETCH_DIR)
    try:
        health = asyncio.run(asyncio.to_thread(PIPELINE.health))
        logger.info("Pipeline health: %s", health)
    except Exception as exc:
        logger.warning("Pipeline not reachable at startup: %s", exc)
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()