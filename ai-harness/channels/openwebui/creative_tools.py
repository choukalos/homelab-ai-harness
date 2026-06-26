"""
title: AI Harness Creative Tools
author: Chuck
version: 0.1.0
description: Document creation, presentations, and visual content via the AI Harness.
"""

import os
import re
import json
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
    # ----------------------------------------------------------------
    # Documents (layout engine)
    # ----------------------------------------------------------------

    def create_document(
        self,
        title: str,
        template: str = "minimal",
        orientation: str = "portrait",
        zones: str = "",
        output_path: str = "",
        background_color: str = "#ffffff",
        text_color: str = "#1a1a1a",
        accent_color: str = "#3b82f6",
        export_pdf: bool = True,
        pdf_path: str = "",
        pdf_page_size: str = "Letter",
    ) -> str:
        """
        Create a complete formatted document with text, images (AI-generated),
        and tables using the AI Harness layout engine.

        Use this for reports, presentations, research summaries, articles,
        marketing materials, or any structured visual document.

        Zones is a JSON string defining the content for each zone.
        Content types: 'text', 'image' (existing URL), 'gen_image' (AI generate), 'table'
        """

        # Parse zones JSON
        try:
            zones_list = json.loads(zones) if zones else []
        except json.JSONDecodeError:
            return f"Error parsing zones JSON: {zones[:100]}... Ensure valid JSON."

        # Default output path
        if not output_path:
            safe_title = re.sub(r"[^a-zA-Z0-9]+", "-", title).lower().strip("-")
            output_path = f"documents/{safe_title}.html"

        payload: dict = {
            "orientation": orientation,
            "template": template,
            "title": title,
            "background_color": background_color,
            "text_color": text_color,
            "accent_color": accent_color,
            "zones": zones_list,
            "output_path": output_path,
            "export_pdf": export_pdf,
        }

        if export_pdf:
            if not pdf_path:
                safe_title = re.sub(r"[^a-zA-Z0-9]+", "-", title).lower().strip("-")
                pdf_path = f"documents/{safe_title}.pdf"
            payload["pdf_path"] = pdf_path
            payload["pdf_page_size"] = pdf_page_size

        data = self._post("/layout/build", payload, timeout=1200)

        html_url = self._absolute_url(f"/media/files/{data.get('html_path', '')}")

        lines = [
            "Document created successfully.",
            "",
            f"Title: {data.get('title') or title}",
            f"Layout ID: {data.get('layout_id', '')}",
            f"HTML file: {data.get('html_path', '')}",
            f"HTML size: {data.get('html_bytes', 0)} bytes",
        ]

        if data.get("generated_images"):
            lines.append("")
            lines.append(f"Generated {len(data['generated_images'])} image(s):")
            for img in data["generated_images"]:
                img_url = self._absolute_url(img.get("url", ""))
                lines.append(f"  - {img.get('filename', '')}")
                lines.append(f"    {img_url}")

        if data.get("pdf_path"):
            pdf_url = self._absolute_url(data["pdf_url"] or f"/media/files/{data['pdf_path']}")
            lines.append("")
            lines.append(f"PDF exported: {data['pdf_path']}")
            lines.append(f"PDF size: {data.get('pdf_bytes', 0)} bytes")
            lines.append("")
            lines.append(f"[Open PDF]({pdf_url})")

        lines.append("")
        lines.append(f"[Open HTML]({html_url})")

        return "\n".join(lines)

    # ----------------------------------------------------------------
    # Presentations (Presenton pipeline)
    # ----------------------------------------------------------------

    def create_presentation(
        self,
        title: str,
        content: str,
        n_slides: int = 8,
        template: str = "general",
        tone: str = "default",
        verbosity: str = "standard",
        language: str = "English",
        export_as: str = "pptx",
        research: bool = False,
        kb_search: bool = False,
        instructions: str = "",
    ) -> str:
        """
        Create a presentation using the AI Harness and Presenton.

        This runs the full pipeline: optional research/KB lookup, AI outline
        generation, Presenton slide generation, and file saving.

        Use this for slides, decks, reports, pitch decks, educational content,
        or any topic that needs a polished PPTX or PDF presentation.

        Typical runtime: 2-5 minutes.
        """

        payload = {
            "title": title,
            "content": content,
            "n_slides": n_slides,
            "template": template,
            "tone": tone,
            "verbosity": verbosity,
            "language": language,
            "export_as": export_as,
            "research": research,
            "kb_search": kb_search,
        }

        if instructions:
            payload["instructions"] = instructions

        data = self._post("/presentation/generate", payload, timeout=600)

        presentation_id = data.get("presentation_id", "")
        title_resp = data.get("title", title)
        slide_count = data.get("slide_count", 0)
        version = data.get("version", 1)
        download_url = self._absolute_url(data.get("download_url", ""))
        edit_url = data.get("edit_url", "")
        local_path = data.get("local_path", "")

        lines = [
            "Presentation created successfully.",
            "",
            f"Title: {title_resp}",
            f"Version: {version}",
            f"Slides: {slide_count}",
        ]

        if local_path:
            lines.append(f"File: {local_path}")

        if download_url:
            lines.append("")
            lines.append(f"Download: {download_url}")
            lines.append("")
            lines.append(f"[Download presentation]({download_url})")

        if edit_url:
            lines.append("")
            lines.append(f"Edit in Presenton: {edit_url}")

        return "\n".join(lines)

    def create_presentation_async(
        self,
        title: str,
        content: str,
        n_slides: int = 8,
        template: str = "general",
        tone: str = "default",
        verbosity: str = "standard",
        language: str = "English",
        export_as: str = "pptx",
        research: bool = False,
        kb_search: bool = False,
        instructions: str = "",
    ) -> str:
        """
        Start an async presentation generation job via Celery (fire-and-forget).

        Returns immediately with a task_id. Use check_task_status to poll for
        completion. Use this when you want to queue the presentation and check
        back later.

        Typical runtime: 2-5 minutes (background).
        """

        payload = {
            "title": title,
            "content": content,
            "n_slides": n_slides,
            "template": template,
            "tone": tone,
            "verbosity": verbosity,
            "language": language,
            "export_as": export_as,
            "research": research,
            "kb_search": kb_search,
        }

        if instructions:
            payload["instructions"] = instructions

        data = self._post("/presentation/generate/async", payload, timeout=30)

        task_id = data.get("task_id", "")
        title_resp = data.get("title", title)
        message = data.get("message", "")

        lines = [
            "Presentation generation started (background).",
            "",
            f"Title: {title_resp}",
            f"Task ID: {task_id}",
            "",
            f"{message}",
            "",
            f"Use check_task_status(task_id='{task_id}') to check progress.",
        ]

        return "\n".join(lines)

    def check_task_status(self, task_id: str) -> str:
        """
        Check the status of an async presentation generation task.

        Returns the current state: pending, started, completed, or failed.
        If completed, includes the full presentation result with download link.
        """
        data = self._get_with_params(f"/presentation/tasks/{task_id}", {})

        status = data.get("status", "unknown")
        result = data.get("result")
        error = data.get("error")

        lines = [f"Task {task_id} status: {status}", ""]

        if status == "completed" and result:
            title_resp = result.get("title", "")
            slide_count = result.get("slide_count", 0)
            download_url = self._absolute_url(result.get("download_url", ""))
            local_path = result.get("local_path", "")

            lines.append(f"Title: {title_resp}")
            lines.append(f"Slides: {slide_count}")

            if local_path:
                lines.append(f"File: {local_path}")

            if download_url:
                lines.append("")
                lines.append(f"Download: {download_url}")
                lines.append("")
                lines.append(f"[Download presentation]({download_url})")
        elif status == "failed" and error:
            lines.append(f"Error: {error[:500]}")
        elif status in ("pending", "started"):
            lines.append("Generation in progress. Check back in a minute or two.")

        return "\n".join(lines)

    def generate_outline(
        self,
        topic: str,
        instructions: str = "",
        research: bool = False,
        kb_search: bool = False,
    ) -> str:
        """
        Generate an AI-powered presentation outline for a topic.

        Use this to brainstorm or plan a presentation before generating it.
        The returned outline can be refined or passed to create_presentation
        via the outline parameter.
        """

        payload = {
            "topic": topic,
            "research": research,
            "kb_search": kb_search,
        }

        if instructions:
            payload["instructions"] = instructions

        data = self._post("/presentation/outline", payload, timeout=180)

        title = data.get("title", "")
        outline = data.get("outline", "")
        slide_count = data.get("slide_count", 0)
        sources = data.get("sources", [])

        lines = [f"Outline for: {title}", "", f"Estimated slides: {slide_count}", "", outline]

        if sources:
            lines.append("")
            lines.append("Research sources:")
            for i, s in enumerate(sources, start=1):
                src_title = s.get("title", s.get("source", "Unknown"))
                src_url = s.get("url", "")
                lines.append(f"  [{i}] {src_title}" + (f" - {src_url}" if src_url else ""))

        return "\n".join(lines)

    def list_presentations(
        self,
        limit: int = 20,
    ) -> str:
        """
        List all created presentations.

        Returns presentations with titles, slide counts, creation dates,
        and download URLs. Most recent first.
        """
        data = self._get_with_params("/presentation/list", {"limit": limit})

        presentations = data.get("presentations", [])
        total = data.get("total", len(presentations))

        if not presentations:
            return "No presentations found."

        lines = [f"Found {total} presentation(s):", ""]

        for p in presentations:
            lines.append(f"- **{p.get('title', 'Untitled')}**")
            lines.append(f"  Slides: {p.get('slide_count', 0)}")
            version = p.get("version", 1)
            lines.append(f"  Version: {version}")
            created = p.get("created_at", "")
            if created:
                lines.append(f"  Created: {created[:10]}")
            download_url = self._absolute_url(p.get("download_url", ""))
            if download_url:
                lines.append(f"  Download: [{download_url}]({download_url})")
            lines.append("")

        return "\n".join(lines)

    def regenerate_presentation(
        self,
        presentation_id: str,
        title: str = "",
        content: str = "",
        n_slides: int = 0,
        template: str = "",
        tone: str = "",
        verbosity: str = "",
        language: str = "",
        export_as: str = "",
        instructions: str = "",
        research: bool = False,
        kb_search: bool = False,
    ) -> str:
        """
        Regenerate a presentation with modified parameters, creating a new version.

        All fields are optional. Only the provided fields override the parent
        presentation's values. The parent's title is preserved (unless explicitly
        changed), and the version auto-increments.

        Use this to iterate on an existing presentation: change tone, add slides,
        switch template, etc.
        """

        payload: dict = {}

        if title:
            payload["title"] = title
        if content:
            payload["content"] = content
        if n_slides > 0:
            payload["n_slides"] = n_slides
        if template:
            payload["template"] = template
        if tone:
            payload["tone"] = tone
        if verbosity:
            payload["verbosity"] = verbosity
        if language:
            payload["language"] = language
        if export_as:
            payload["export_as"] = export_as
        if instructions:
            payload["instructions"] = instructions
        if research:
            payload["research"] = research
        if kb_search:
            payload["kb_search"] = kb_search

        data = self._post(f"/presentation/{presentation_id}", payload, timeout=600)

        presentation_id_resp = data.get("presentation_id", "")
        title_resp = data.get("title", "")
        slide_count = data.get("slide_count", 0)
        version = data.get("version", 1)
        download_url = self._absolute_url(data.get("download_url", ""))
        edit_url = data.get("edit_url", "")
        local_path = data.get("local_path", "")

        lines = [
            "Presentation regenerated successfully.",
            "",
            f"Title: {title_resp}",
            f"Version: {version}",
            f"Slides: {slide_count}",
        ]

        if local_path:
            lines.append(f"File: {local_path}")

        if download_url:
            lines.append("")
            lines.append(f"Download: {download_url}")
            lines.append("")
            lines.append(f"[Download presentation]({download_url})")

        if edit_url:
            lines.append("")
            lines.append(f"Edit in Presenton: {edit_url}")

        return "\n".join(lines)

    def update_presentation_async(
        self,
        presentation_id: str,
        title: str = "",
        content: str = "",
        n_slides: int = 0,
        template: str = "",
        tone: str = "",
        verbosity: str = "",
        language: str = "",
        export_as: str = "",
        instructions: str = "",
        research: bool = False,
        kb_search: bool = False,
    ) -> str:
        """
        Start an async update to an existing presentation (fire-and-forget).

        Returns immediately with a task_id. Use check_task_status to poll.
        Creates a new version with the specified changes.

        All fields are optional. Only the provided fields override the parent
        presentation's values.

        Typical runtime: 2-5 minutes (background).
        """

        payload: dict = {}

        if title:
            payload["title"] = title
        if content:
            payload["content"] = content
        if n_slides > 0:
            payload["n_slides"] = n_slides
        if template:
            payload["template"] = template
        if tone:
            payload["tone"] = tone
        if verbosity:
            payload["verbosity"] = verbosity
        if language:
            payload["language"] = language
        if export_as:
            payload["export_as"] = export_as
        if instructions:
            payload["instructions"] = instructions
        if research:
            payload["research"] = research
        if kb_search:
            payload["kb_search"] = kb_search

        data = self._post(
            f"/presentation/{presentation_id}/update/async", payload, timeout=30,
        )

        task_id = data.get("task_id", "")
        title_resp = data.get("title", "")
        message = data.get("message", "")

        lines = [
            "Presentation update started (background).",
            "",
            f"Title: {title_resp}",
            f"Task ID: {task_id}",
            "",
            f"{message}",
            "",
            f"Use check_task_status(task_id='{task_id}') to check progress.",
        ]

        return "\n".join(lines)

    def find_presentations(
        self,
        query: str,
        limit: int = 10,
    ) -> str:
        """
        Search for presentations by title or topic.

        Use this to find a previously created presentation when you remember
        some detail about it but not its exact name.
        """
        params = {
            "title": query,
            "limit": limit,
        }

        data = self._get_with_params("/presentation/search", params)

        results = data.get("presentations", [])
        total = data.get("total", len(results))

        if not results:
            return (
                f"No presentations found matching '{query}'.\n\n"
                "Try asking 'list my presentations' to see all available presentations."
            )

        lines = [f"Found {total} presentation(s) matching '{query}':", ""]

        for p in results:
            lines.append(f"- **{p.get('title', 'Untitled')}**")
            lines.append(f"  Slides: {p.get('slide_count', 0)}")
            version = p.get("version", 1)
            lines.append(f"  Version: {version}")
            download_url = self._absolute_url(p.get("download_url", ""))
            if download_url:
                lines.append(f"  Download: [{download_url}]({download_url})")
            lines.append("")

        return "\n".join(lines)
