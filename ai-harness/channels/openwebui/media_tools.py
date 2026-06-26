"""
title: AI Harness Media Tools
author: Chuck
version: 0.1.0
description: Image generation, image editing, and video clip generation via the AI Harness media pipeline.
"""

import os
import requests
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Inlined HarnessBase — self-contained so this file works standalone in Open WebUI
# ---------------------------------------------------------------------------

class HarnessBase:
    class Valves(BaseModel):
        harness_url: str = Field(
            default=os.getenv("HARNESS_URL", "http://ai-harness:8090"),
            description="Internal API URL for the AI Harness",
        )
        harness_api_key: str = Field(
            default=os.getenv("HARNESS_API_KEY", ""),
            description="AI Harness API key",
        )
        harness_display_url: str = Field(
            default=os.getenv("HARNESS_DISPLAY_URL", "http://192.168.4.54:8090"),
            description="Browser-accessible URL for media files",
        )

    def __init__(self):
        self.valves = self.Valves()
        self.citation = True

    def _headers(self, content_type: bool = True) -> dict:
        headers = {}
        if content_type:
            headers["Content-Type"] = "application/json"
        if self.valves.harness_api_key:
            headers["X-API-Key"] = self.valves.harness_api_key
            headers["Authorization"] = f"Bearer {self.valves.harness_api_key}"
        return headers

    def _absolute_url(self, url: str) -> str:
        if not url:
            return ""
        display = self.valves.harness_display_url.rstrip("/")
        if url.startswith(("http://", "https://")):
            harness = self.valves.harness_url.rstrip("/")
            # Rewrite Docker internal hostname → display URL
            if url.startswith(harness):
                return f"{display}/{url[len(harness):].lstrip('/')}"
            # Rewrite any http:// internal URL that isn't already the display URL
            # This covers thor.local, localhost, and other LAN hostnames
            if url.startswith("http://") and not url.startswith(display):
                # Extract path portion after hostname[:port]
                rest = url[len("http://"):]
                slash_idx = rest.find("/")
                if slash_idx >= 0:
                    path = rest[slash_idx:]
                    return f"{display}{path}"
            # https:// URLs or display URL as-is (already browser-accessible)
            return url
        # Relative path — prepend display URL
        return f"{display}/{url.lstrip('/')}"

    def _post(self, path: str, payload: dict, timeout: int = 180) -> dict:
        r = requests.post(
            f"{self.valves.harness_url}{path}",
            headers=self._headers(),
            json=payload,
            timeout=timeout,
        )
        r.raise_for_status()
        return r.json()

    def _get_with_params(self, path: str, params: dict) -> dict:
        r = requests.get(
            f"{self.valves.harness_url}{path}",
            headers=self._headers(content_type=False),
            params=params,
            timeout=30,
        )
        r.raise_for_status()
        return r.json()


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

class Tools(HarnessBase):
    def generate_image(
        self,
        prompt: str,
        negative_prompt: str = "",
        width: int = 1024,
        height: int = 1024,
        seed: int = -1,
        upscale: bool = False,
    ) -> str:
        """
        Generate an image using the AI Harness media pipeline.
        Use this for concept art, illustrations, wallpapers, product ideas,
        photorealistic scenes, fantasy art, sci-fi art, or visual ideation.
        """

        payload = {
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            "width": width,
            "height": height,
            "seed": seed,
            "upscale": upscale,
        }

        data = self._post(
            "/media/image",
            payload,
            timeout=600,
        )

        lines = [
            "Image generated successfully.",
            "",
        ]

        if data.get("job_id"):
            lines.append(f"Job ID: {data['job_id']}")

        files = data.get("files", [])

        if not files:
            lines.append("No output files returned.")
            return "\n".join(lines)

        lines.append("")
        lines.append("Generated files:")

        for item in files:
            url = self._absolute_url(item.get("url") or "")
            file_type = item.get("type") or "unknown"

            lines.append(f"- {file_type}: {url}")

            if url:
                lines.append(f"![Generated image]({url})")

        return "\n".join(lines)

    def edit_image(
        self,
        image_path_or_url: str,
        prompt: str,
        negative_prompt: str = "",
        denoise: float = 0.55,
    ) -> str:
        """
        Edit or transform an existing image using the AI Harness img2img pipeline.

        Supports:
        - A generated AI Harness image URL
        - A public http/https image URL
        - A local file path visible inside the Open WebUI container
        """

        if image_path_or_url.startswith(("http://", "https://")):
            response = self._post(
                "/media/image/edit/url",
                {
                    "image_url": image_path_or_url,
                    "prompt": prompt,
                    "negative_prompt": negative_prompt,
                    "denoise": denoise,
                },
                timeout=600,
            )
        else:
            if not os.path.exists(image_path_or_url):
                return (
                    "Image path does not exist inside the Open WebUI container.\n\n"
                    "Use a full http/https image URL instead, such as a generated "
                    "AI Harness image URL."
                )

            url = f"{self.valves.harness_url}/media/image/edit"
            headers = self._headers(content_type=False)

            with open(image_path_or_url, "rb") as image_file:
                r = requests.post(
                    url,
                    headers=headers,
                    files={"image": image_file},
                    data={
                        "prompt": prompt,
                        "negative_prompt": negative_prompt,
                        "denoise": denoise,
                    },
                    timeout=600,
                )

            r.raise_for_status()
            response = r.json()

        lines = ["Image edit completed successfully.", ""]

        if response.get("job_id"):
            lines.append(f"Job ID: {response['job_id']}")

        files = response.get("files", [])

        if not files:
            lines.append("No output files returned.")
            return "\n".join(lines)

        lines.append("")
        lines.append("Generated files:")

        for item in files:
            file_url = self._absolute_url(item.get("url") or "")
            file_type = item.get("type") or "unknown"

            lines.append(f"- {file_type}: {file_url}")

            if file_url:
                lines.append(f"![Edited image]({file_url})")

        return "\n".join(lines)

    def generate_clip(
        self,
        prompt: str,
        negative_prompt: str = "",
        width: int = 1024,
        height: int = 576,
        seed: int = -1,
        video_frames: int = 25,
        fps: int = 6,
        motion_bucket_id: int = 127,
    ) -> str:
        """
        Generate a short video clip from a text prompt using the AI Harness media pipeline.
        The pipeline first generates an image from the prompt, then animates it into a clip.
        Use this for concept videos, short animations, cinematic scenes,
        motion visualization, or any prompt-to-clip request.
        """

        payload = {
            "prompt": prompt,
            "negative_prompt": negative_prompt or "text, watermark",
            "width": width,
            "height": height,
            "seed": seed,
            "steps": 15,
            "cfg": 8.0,
            "video_frames": video_frames,
            "fps": fps,
            "motion_bucket_id": motion_bucket_id,
        }

        data = self._post(
            "/media/clip",
            payload,
            timeout=600,
        )

        lines = [
            "Clip generated successfully.",
            "",
        ]

        if data.get("job_id"):
            lines.append(f"Job ID: {data['job_id']}")

        files = data.get("files", [])

        if not files:
            lines.append("No output files returned.")
            return "\n".join(lines)

        lines.append("")
        lines.append("Generated files:")

        for item in files:
            url = self._absolute_url(item.get("url") or "")
            file_type = item.get("type") or "unknown"

            lines.append(f"- {file_type}: {url}")

            if url:
                lines.append(f"![Generated clip]({url})")

        return "\n".join(lines)
