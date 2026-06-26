"""
title: AI Harness Research Tools
author: Chuck
version: 0.1.0
description: Web search, research briefs, and deep research via the AI Harness.
"""

import os
import re
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
    def web_search(self, query: str, max_results: int = 5) -> str:
        """
        Search the web and return source links without AI summarization.
        Use this when the user wants sources, links, references, or raw search results.
        """

        data = self._post(
            "/web/search",
            {
                "query": query,
                "max_results": max_results,
                "crawl_results": 0,
                "summarize": False,
                "mode": "sources",
            },
        )

        results = data.get("results", [])
        if not results:
            return "No web search results found."

        lines = [f"Web search results for: {query}", ""]

        for i, item in enumerate(results, start=1):
            title = item.get("title") or "Untitled"
            url = item.get("url") or ""
            snippet = item.get("content") or item.get("snippet") or ""

            lines.append(f"[{i}] {title}")
            lines.append(url)

            if snippet:
                lines.append(snippet)

            lines.append("")

        return "\n".join(lines)

    def summarize_web_search(self, query: str, max_results: int = 5) -> str:
        """
        Search the web, crawl top results, and return a summarized answer with citations.
        Use this when the user asks about current information, recent events, products,
        software docs, companies, travel, or anything likely to require up-to-date sources.
        """

        data = self._post(
            "/web/search",
            {
                "query": query,
                "max_results": max_results,
                "crawl_results": 3,
                "summarize": True,
                "mode": "answer",
            },
            timeout=240,
        )

        answer = data.get("answer") or "No summary generated."
        results = data.get("results", [])

        lines = [answer, "", "Sources:"]

        for i, item in enumerate(results, start=1):
            title = item.get("title") or "Untitled"
            url = item.get("url") or ""

            lines.append(f"[{i}] {title} - {url}")

        return "\n".join(lines)

    def research_brief_web_search(
        self,
        topic: str,
        max_queries: int = 4,
        results_per_query: int = 5,
    ) -> str:
        """
        Create a deeper research brief by generating multiple web searches,
        gathering sources, and summarizing findings.
        Use this for market research, competitive research, travel research,
        buying research, planning, comparisons, or complex current topics.
        """

        data = self._post(
            "/web/research",
            {
                "topic": topic,
                "max_queries": max_queries,
                "results_per_query": results_per_query,
            },
            timeout=420,
        )

        brief = data.get("brief") or "No research brief generated."
        queries = data.get("queries", [])
        sources = data.get("sources", [])

        lines = [brief, "", "Search queries used:"]

        for q in queries:
            lines.append(f"- {q}")

        lines.append("")
        lines.append("Sources:")

        for i, item in enumerate(sources, start=1):
            title = item.get("title") or "Untitled"
            url = item.get("url") or ""

            lines.append(f"[{i}] {title} - {url}")

        return "\n".join(lines)

    def deep_research(
        self,
        query: str,
    ) -> str:
        """
        Run a deep research query using the Deep Agents framework.
        The agent uses an LLM with web search capabilities to investigate
        the topic, synthesize findings, and provide a comprehensive answer
        with source references.

        Use this for in-depth research questions, complex topics requiring
        multi-step investigation, or when you want the AI to autonomously
        search, analyze, and synthesize information.
        """

        data = self._post(
            "/workflows/deep-research/run",
            {
                "query": query,
            },
            timeout=300,
        )

        answer = data.get("answer", "Research completed.")
        sources = data.get("sources", [])
        steps = data.get("steps", [])

        # Convert [N] citations in the answer into clickable links:
        #   [1] → [1](url "Title") — so the user can click through to verify
        if sources:
            def _make_citation_link(m):
                idx = int(m.group(1))
                if 1 <= idx <= len(sources):
                    src = sources[idx - 1]
                    url = src.get("url", "")
                    title = src.get("title", "Source")
                    if url:
                        return f'[{idx}]({url} "{title}")'
                return m.group(0)

            answer = re.sub(r'\[(\d+)\]', _make_citation_link, answer)

        lines = [answer, ""]

        if steps:
            lines.append("Research steps taken:")
            for i, step in enumerate(steps, start=1):
                action = step.get("action", step.get("result_preview", "Step"))
                lines.append(f"  {i}. {action}")
            lines.append("")

        if sources:
            lines.append("Sources:")
            for i, s in enumerate(sources, start=1):
                url = s.get("url", "")
                title = s.get("title", s.get("tool_result", "Source"))
                lines.append(f"  [{i}] [{title}]({url})")

        return "\n".join(lines)
