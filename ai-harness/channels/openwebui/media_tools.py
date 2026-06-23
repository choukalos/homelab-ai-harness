"""
title: AI Harness Media Tools
author: Chuck
version: 0.1.0
description: Image generation, image editing, and video clip generation via the AI Harness media pipeline.
"""

import os
import requests
from pydantic import BaseModel, Field

from harness_base import HarnessBase


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
