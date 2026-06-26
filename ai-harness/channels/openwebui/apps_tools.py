"""
title: AI Harness App Tools
author: Chuck
version: 0.1.0
description: PM demo creation, workflow demos, and demo management via the AI Harness.
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
            description="Internal API URL for the AI Harness (Docker DNS name, e.g. http://ai-harness:8090)",
        )
        harness_api_key: str = Field(
            default=os.getenv("HARNESS_API_KEY", ""),
            description="AI Harness API key",
        )
        harness_display_url: str = Field(
            default=os.getenv("HARNESS_DISPLAY_URL", "http://192.168.4.54:8090"),
            description="Browser-accessible URL for media files (LAN IP, e.g. http://192.168.4.54:8090)",
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
    def create_quick_demo(
        self,
        title: str,
        prompt: str,
        save_name: str = "",
        model: str = "",
    ) -> str:
        """
        Create a **fast, simple** single-page HTML demo/prototype.

        Use this when you need a quick clickable mockup without deep research.
        Great for: rapid concept sketches, simple app flows, quick prototypes,
        feature pitches, or when the user says "quick demo" or "simple demo".
        Takes about 10-20 seconds.

        For a higher-quality, research-backed demo (with KB lookup, web research,
        verification, and polish), use `create_workflow_demo` instead.
        """

        payload = {
            "title": title,
            "prompt": prompt,
        }

        if save_name:
            payload["save_name"] = save_name

        if model:
            payload["model"] = model

        data = self._post("/pm/demo", payload, timeout=600)

        demo_title = data.get("title") or title
        filename = data.get("filename") or ""
        url = self._absolute_url(data.get("url") or "")

        lines = [
            "PM clickable demo created successfully.",
            "",
            f"Title: {demo_title}",
        ]

        if filename:
            lines.append(f"File: {filename}")

        if url:
            lines.append("")
            lines.append(f"Open demo: {url}")
            lines.append("")
            lines.append(f"[Open clickable demo]({url})")

        return "\n".join(lines)

    def create_workflow_demo(
        self,
        title: str,
        prompt: str,
        model: str = "",
    ) -> str:
        """
        Create a **high-quality, research-backed** one-page clickable HTML demo
        using the full deep-agents pipeline (KB lookup, web research, design spec,
        iterative build with validation, polish, and save).

        Use this when the user wants the best demo quality: product pitches,
        competitive mockups, polished prototypes, or any demo where research
        and verification matter. This is the **default choice** when the user
        asks to create or build a demo without specifying speed.

        Takes 2-5 minutes to complete (runs the full pipeline synchronously).

        For a quick, simple demo without research, use `create_quick_demo` instead.
        """

        payload = {
            "title": title,
            "prompt": prompt,
        }

        if model:
            payload["model"] = model

        data = self._post("/demos/run", payload, timeout=600)

        demo_title = data.get("title", title)
        slug = data.get("slug", "")
        status = data.get("status", "unknown")
        html_path = data.get("html_path", "")
        thread_id = data.get("thread_id", "")
        error = data.get("error")

        if error or status == "error":
            # Even on error, show any URL that was generated for inspection
            public_url = self._absolute_url(data.get("public_url", ""))
            lines = [
                f"Demo creation failed.",
                "",
                f"Title: {demo_title}",
                f"Error: {error}",
            ]
            if public_url:
                lines.extend([
                    "",
                    f"Partial result (if any): {public_url}",
                    f"[Inspect partial result]({public_url})",
                ])
            return "\n".join(lines)

        # Use public_url from the response (Phase 1 schema update),
        # falling back to local_url, then to slug-based construction.
        public_url = self._absolute_url(data.get("public_url", ""))
        local_url = self._absolute_url(data.get("local_url", ""))
        display_url = public_url or local_url or ""

        lines = [
            "Demo created successfully.",
            "",
            f"Title: {demo_title}",
        ]

        if slug:
            lines.append(f"Slug: {slug}")

        if thread_id:
            lines.append(f"Thread ID: {thread_id}")

        if display_url:
            lines.append("")
            lines.append(f"Open demo: {display_url}")
            lines.append("")
            lines.append(f"[Open clickable demo]({display_url})")

        return "\n".join(lines)

    def list_demos(
        self,
        tags: str = "",
        limit: int = 20,
    ) -> str:
        """
        List all created one-page clickable demos.

        Tags is an optional comma-separated filter (e.g. 'pet,adoption').
        Returns demos with titles, descriptions, and local URLs.
        """
        params = {}
        if tags:
            # Use first tag for filtering
            params["tag"] = tags.split(",")[0].strip()
        params["limit"] = limit

        data = self._get_with_params("/demos/", params)

        demos = data.get("demos", [])
        if not demos:
            return "No demos found."

        lines = [f"Found {len(demos)} demo(s):", ""]

        for d in demos:
            lines.append(f"- **{d.get('title', 'Untitled')}**")
            desc = d.get("description", "")
            if desc:
                lines.append(f"  Description: {desc[:200]}")
            created = d.get("created_at", "")
            if created:
                lines.append(f"  Created: {created[:10]}")
            local = d.get("local_url", "")
            if local:
                url = self._absolute_url(local)
                lines.append(f"  Open: [{url}]({url})")
            lines.append("")

        return "\n".join(lines)

    def find_demo(
        self,
        query: str,
        limit: int = 10,
    ) -> str:
        """
        Search for one-page clickable demos by title, description, or tags.

        Use this to find a previously created demo when you remember
        some detail about it but not its exact name.
        """
        params = {
            "q": query,
            "limit": limit,
            "local_urls": True,
        }

        data = self._get_with_params("/demos/search", params)

        matches = data.get("matches", [])
        if not matches:
            return (
                f"No demos found matching '{query}'.\n\n"
                f"Try asking 'list my demos' to see all available demos."
            )

        lines = [f"Found {len(matches)} demo(s) matching '{query}':", ""]

        for d in matches:
            lines.append(f"- **{d.get('title', 'Untitled')}**")
            desc = d.get("description", "")
            if desc:
                lines.append(f"  Description: {desc[:200]}")
            tags = d.get("tags", [])
            if tags:
                lines.append(f"  Tags: {', '.join(tags[:5])}")
            local = d.get("local_url", "")
            if local:
                url = self._absolute_url(local)
                lines.append(f"  Open: [{url}]({url})")
            lines.append("")

        return "\n".join(lines)
