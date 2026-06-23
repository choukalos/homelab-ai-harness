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

from harness_base import HarnessBase


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
