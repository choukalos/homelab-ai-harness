"""
title: AI Harness Knowledge Tools
author: Chuck
version: 0.1.0
description: Family knowledge base search, ask, and ingestion via the AI Harness.
"""

from harness_base import HarnessBase


class Tools(HarnessBase):
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
