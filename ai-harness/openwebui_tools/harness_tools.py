"""
title: AI Harness Tools
author: Chuck
version: 0.4.0
description: Web search, research briefs, family knowledge base, media generation, and PM clickable demo tools using Chuck's local AI Harness.
"""

import os
import requests
from pydantic import BaseModel, Field


class Tools:
    class Valves(BaseModel):
        harness_url: str = Field(
            default=os.getenv("HARNESS_URL", "http://ai-harness:8090"),
            description="Base URL for the AI Harness",
        )
        harness_api_key: str = Field(
            default=os.getenv("HARNESS_API_KEY", ""),
            description="AI Harness API key",
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

        if url.startswith(("http://", "https://")):
            return url

        return f"{self.valves.harness_url.rstrip('/')}/{url.lstrip('/')}"

    def _post(self, path: str, payload: dict, timeout: int = 180) -> dict:
        r = requests.post(
            f"{self.valves.harness_url}{path}",
            headers=self._headers(),
            json=payload,
            timeout=timeout,
        )
        r.raise_for_status()
        return r.json()

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

    def family_kb_search(
        self,
        query: str,
        category: str = "",
        limit: int = 5,
    ) -> str:
        """
        Search Chuck's family knowledge base and return matching source chunks.
        Use this for saved family documents, house info, vehicles, travel notes,
        finances, games, guitar notes, research notes, and local markdown docs.
        """

        payload = {
            "query": query,
            "limit": limit,
        }

        if category:
            payload["category"] = category

        data = self._post("/kb/search", payload)

        results = data.get("results", [])

        if not results:
            return "I could not find that in the family knowledge base."

        lines = [
            f"Family KB results for: {query}",
            "",
            data.get(
                "instruction",
                "Answer only from these results. If the answer is not present, say you could not find it in the family knowledge base.",
            ),
            "",
        ]

        for i, item in enumerate(results, start=1):
            source = item.get("source") or "Unknown source"
            category_value = item.get("category") or "Unknown category"
            score = item.get("score")
            text = item.get("text") or ""

            lines.append(f"[{i}] {source}")
            lines.append(f"Category: {category_value}")

            if score is not None:
                lines.append(f"Score: {score:.4f}")

            lines.append(text)
            lines.append("")

        return "\n".join(lines)

    def family_kb_ask(
        self,
        question: str,
        category: str = "",
        limit: int = 5,
    ) -> str:
        """
        Ask a question against Chuck's family knowledge base.
        Use this when the user expects an answer from saved local/family documents.
        """

        payload = {
            "query": question,
            "limit": limit,
        }

        if category:
            payload["category"] = category

        data = self._post("/kb/ask", payload)

        results = data.get("results", [])

        if not results:
            return "I could not find an answer in the family knowledge base."

        lines = [
            "Use the following family KB results to answer the question.",
            "",
            f"Question: {question}",
            "",
        ]

        for i, item in enumerate(results, start=1):
            source = item.get("source") or "Unknown source"
            text = item.get("text") or ""

            lines.append(f"[{i}] Source: {source}")
            lines.append(text)
            lines.append("")

        lines.append(
            "Instruction: Answer only from these results. If the answer is not present, say you could not find it in the family knowledge base."
        )

        return "\n".join(lines)

    def family_kb_ingest(self) -> str:
        """
        Re-index the markdown family knowledge base into Qdrant.
        Use this after new markdown files have been added or changed.
        """

        data = self._post("/kb/ingest", {}, timeout=600)

        return (
            "Family KB indexed.\n"
            f"Files indexed: {data.get('indexed_files', 0)}\n"
            f"Chunks indexed: {data.get('indexed_chunks', 0)}"
        )

    def family_kb_ingest_raw(self) -> str:
        """
        Convert files from the raw family KB folder into markdown.
        Use this after new PDFs, text files, images, or markdown files are placed in the raw KB folder.
        """

        data = self._post("/kb/ingest/raw", {}, timeout=600)

        if not data:
            return "No raw files were processed."

        lines = ["Raw family KB ingestion results:", ""]

        for item in data:
            source = item.get("source")
            status = item.get("status")
            output = item.get("output")
            message = item.get("message")

            lines.append(f"- {source}: {status}")

            if output:
                lines.append(f"  Output: {output}")

            if message:
                lines.append(f"  Message: {message}")

        return "\n".join(lines)

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

        
