"""
title: AI Harness App Tools
author: Chuck
version: 0.1.0
description: PM demo creation, workflow demos, and demo management via the AI Harness.
"""

from harness_base import HarnessBase


class Tools(HarnessBase):
    def create_pm_demo(
        self,
        title: str,
        prompt: str,
        save_name: str = "",
        model: str = "",
    ) -> str:
        """
        Create a single-file clickable HTML product demo/prototype using the AI Harness.
        Use this for product management demos, clickable mockups, app flows,
        concept prototypes, mobile demos, onboarding flows, dashboards, or feature pitches.

        The output is a one-page HTML file with inline CSS and JavaScript.
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

    def create_demo(
        self,
        title: str,
        prompt: str,
        model: str = "",
    ) -> str:
        """
        Create a high-quality one-page clickable HTML demo using the full
        research-and-build pipeline (KB lookup, web research, design spec,
        iterative build with validation, polish, and save).

        Use this for demos that need research-backed quality: product pitches,
        concept prototypes, competitive mockups, or any demo where you want
        the system to research the domain first.

        This runs the deep-agents demo pipeline synchronously. It typically
        takes 2-5 minutes to complete.
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
