#!/usr/bin/env python3
"""
demo_browse skill — scan demos directory and keyword-match demos.

Purpose:
  Scans a configurable demos directory (default /home/chuck/data/media/demos/)
  for workflow directories containing metadata.json and flat .html files.
  Matches results against a keyword query across title, description, and tags.

Workflow:
  1. Validate the query parameter.
  2. Walk the demos directory for workflow dirs and .html files.
  3. For workflow dirs: read metadata.json to extract title, description, tags.
  4. For flat .html files: derive title from filename, parse minimal metadata.
  5. Keyword-match each demo against the query (case-insensitive).
  6. Return ranked results with metadata.

Constraints:
  - Max runtime: 30 seconds (local file scanning only).
  - No MCP tools — local filesystem access only.
  - Stateless: no side effects.

See skill.yml for the full manifest and README.md for usage.
"""

import json
import logging
import os
import re
import signal
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_DEMO_DIR = Path(
    os.environ.get("DEMO_BROWSE_DEMO_DIR", "/home/chuck/data/media/demos")
)
DEFAULT_LIMIT = int(os.environ.get("DEMO_BROWSE_DEFAULT_LIMIT", "20"))
MAX_RUNTIME_SECS = int(os.environ.get("DEMO_BROWSE_MAX_RUNTIME", "30"))

logger = logging.getLogger("skill.demo_browse")

# ---------------------------------------------------------------------------
# Timeout enforcement
# ---------------------------------------------------------------------------


class TimeoutError(Exception):
    """Raised when the skill exceeds its maximum runtime."""


def _timeout_handler(signum, frame):
    raise TimeoutError(f"demo_browse exceeded {MAX_RUNTIME_SECS}s max runtime")


def _install_timeout():
    """Install a signal-based timeout (Unix only)."""
    if sys.platform != "win32":
        signal.signal(signal.SIGALRM, _timeout_handler)
        signal.alarm(MAX_RUNTIME_SECS)


def _cancel_timeout():
    """Cancel the pending alarm."""
    if sys.platform != "win32":
        signal.alarm(0)


# ---------------------------------------------------------------------------
# Demo metadata extraction
# ---------------------------------------------------------------------------


def _read_metadata_json(demo_dir: Path) -> dict[str, Any]:
    """
    Read metadata.json from a workflow directory.

    Returns a dict with at minimum: title, description, tags, path, type.
    """
    metadata_path = demo_dir / "metadata.json"

    if not metadata_path.is_file():
        # Try to find any .html file in the directory for a fallback
        html_files = list(demo_dir.glob("*.html"))
        if not html_files:
            return {}

        # Build minimal metadata from the directory name and html file
        title = demo_dir.name.replace("-", " ").replace("_", " ").title()
        return {
            "title": title,
            "description": f"Demo in directory: {demo_dir.name}",
            "tags": [],
            "path": str(demo_dir),
            "type": "workflow_dir",
            "html_file": str(html_files[0]),
            "has_metadata": False,
        }

    try:
        with open(metadata_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to read %s: %s", metadata_path, exc)
        return {}

    return {
        "title": data.get("title", demo_dir.name.title()),
        "description": data.get("description", ""),
        "tags": data.get("tags", []),
        "path": str(demo_dir),
        "type": "workflow_dir",
        "created_at": data.get("created_at", ""),
        "slug": data.get("slug", demo_dir.name),
        "local_url": data.get("local_url", ""),
        "public_url": data.get("public_url", ""),
        "code_quality_score": data.get("code_quality_score", None),
        "complexity_score": data.get("complexity_score", None),
        "html_files": [
            str(f) for f in demo_dir.glob("*.html")
        ],
        "has_metadata": True,
    }


def _read_flat_html(html_path: Path) -> dict[str, Any]:
    """
    Extract metadata from a flat .html file (no workflow directory).

    Tries to extract title from <title> tag or meta tags, then falls back
    to the filename.
    """
    stem = html_path.stem

    # Default title from filename
    title = stem.replace("-", " ").replace("_", " ").title()
    description = ""
    tags: list[str] = []

    # Try to parse <title> and <meta> tags from the HTML
    try:
        content = html_path.read_text(encoding="utf-8", errors="replace")

        # Extract <title>...</title>
        title_match = re.search(r"<title[^>]*>(.*?)</title>", content, re.IGNORECASE)
        if title_match:
            title = title_match.group(1).strip()

        # Extract <meta name="description" content="...">
        desc_match = re.search(
            r'<meta\s+name="description"\s+content="(.*?)"', content, re.IGNORECASE
        )
        if desc_match:
            description = desc_match.group(1).strip()

        # Extract <meta name="tags" content="..."> or content="tags: ..."
        tags_match = re.search(
            r'<meta\s+name="(?:tags|keywords)"\s+content="(.*?)"',
            content,
            re.IGNORECASE,
        )
        if tags_match:
            raw_tags = tags_match.group(1)
            tags = [t.strip() for t in raw_tags.split(",") if t.strip()]
    except OSError as exc:
        logger.warning("Failed to read %s: %s", html_path, exc)

    return {
        "title": title,
        "description": description,
        "tags": tags,
        "path": str(html_path),
        "type": "flat_html",
        "slug": stem,
        "html_file": str(html_path),
        "has_metadata": False,
    }


# ---------------------------------------------------------------------------
# Directory scanning
# ---------------------------------------------------------------------------


def _scan_demos(demo_dir: Path) -> list[dict[str, Any]]:
    """
    Walk the demo directory and extract metadata from all demos.

    Returns a list of demo metadata dicts.
    """
    demos = []

    if not demo_dir.is_dir():
        logger.error("Demo directory does not exist: %s", demo_dir)
        return demos

    for entry in sorted(demo_dir.iterdir()):
        if entry.is_dir():
            # Workflow directory — look for metadata.json
            meta = _read_metadata_json(entry)
            if meta:
                demos.append(meta)
        elif entry.is_file() and entry.suffix == ".html":
            # Flat HTML file
            meta = _read_flat_html(entry)
            if meta:
                demos.append(meta)

    return demos


# ---------------------------------------------------------------------------
# Keyword matching
# ---------------------------------------------------------------------------


def _score_demo(demo: dict[str, Any], keywords: list[str]) -> float:
    """
    Score a demo against a list of keywords (case-insensitive).

    Higher score = better match.
    Scoring weights:
      - Title match: 10 points per keyword
      - Tag match: 8 points per keyword
      - Description match: 4 points per keyword
    """
    if not keywords:
        return 0

    title_lower = demo.get("title", "").lower()
    description_lower = demo.get("description", "").lower()
    tags_lower = [t.lower() for t in demo.get("tags", [])]

    score = 0.0
    for kw in keywords:
        kw_lower = kw.lower()

        # Title match (highest weight)
        if kw_lower in title_lower:
            score += 10.0

        # Tag match (high weight)
        if kw_lower in tags_lower:
            score += 8.0

        # Description match (medium weight)
        if kw_lower in description_lower:
            score += 4.0

    return score


def _match_demos(demos: list[dict[str, Any]], query: str, limit: int) -> list[dict[str, Any]]:
    """
    Match demos against a keyword query and return ranked results.

    Each word in the query is treated as a keyword.
    Results are sorted by score (highest first) and truncated to `limit`.
    """
    # Tokenize the query into keywords
    keywords = re.findall(r"[\w]+", query.lower())
    if not keywords:
        return []

    scored = []
    for demo in demos:
        score = _score_demo(demo, keywords)
        if score > 0:
            result = dict(demo)
            result["match_score"] = score
            result["matched_keywords"] = [
                kw for kw in keywords if _score_demo(demo, [kw]) > 0
            ]
            scored.append(result)

    # Sort by score descending
    scored.sort(key=lambda d: d["match_score"], reverse=True)

    return scored[:limit]


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------


def run(params: dict[str, Any], job) -> dict[str, Any]:
    """
    Execute the demo_browse skill.

    Scans the demos directory, extracts metadata, keyword-matches against
    the query, and returns ranked results.

    Args:
        params: Skill parameters (query, demo_dir, limit).
        job: The runner Job object for logging.

    Returns:
        Dict with query, total_found, results, and metadata.
    """
    # Validate inputs
    query = params.get("query")
    if not query or not str(query).strip():
        result = {"error": "Missing required 'query' parameter"}
        if hasattr(job, "add_log"):
            job.add_log("Validation failed: missing query")
        return result

    query = str(query).strip()

    demo_dir = Path(params.get("demo_dir", DEFAULT_DEMO_DIR))
    limit = int(params.get("limit", DEFAULT_LIMIT))

    if hasattr(job, "add_log"):
        job.add_log(f"Executing demo_browse: query='{query}'")
        job.add_log(f"Demo directory: {demo_dir}")
        job.add_log(f"Limit: {limit}")

    # Install timeout
    _install_timeout()

    try:
        # Scan the demos directory
        if hasattr(job, "add_log"):
            job.add_log("Scanning demos directory...")

        all_demos = _scan_demos(demo_dir)

        if hasattr(job, "add_log"):
            job.add_log(f"Found {len(all_demos)} total demos")

        # Match against the query
        if hasattr(job, "add_log"):
            job.add_log(f"Matching against query: '{query}'")

        matched = _match_demos(all_demos, query, limit)

        if hasattr(job, "add_log"):
            job.add_log(f"Found {len(matched)} matching demos")
            for i, demo in enumerate(matched):
                job.add_log(f"  [{i+1}] {demo['title']} (score: {demo['match_score']})")

        # Build result
        result: dict[str, Any] = {
            "query": query,
            "demo_dir": str(demo_dir),
            "total_demos": len(all_demos),
            "matched_count": len(matched),
            "limit": limit,
            "results": matched,
        }

        if hasattr(job, "add_log"):
            job.add_log("demo_browse completed successfully")

        return result

    except TimeoutError as exc:
        msg = str(exc)
        if hasattr(job, "add_log"):
            job.add_log(f"Timeout: {msg}")
        return {
            "error": msg,
            "query": query,
            "status": "timeout",
        }

    except Exception as exc:
        msg = f"Unexpected error: {exc}"
        if hasattr(job, "add_log"):
            job.add_log(msg)
        return {
            "error": msg,
            "query": query,
            "status": "error",
        }

    finally:
        _cancel_timeout()


# ---------------------------------------------------------------------------
# CLI entrypoint (for standalone testing)
# ---------------------------------------------------------------------------


class _MockJob:
    """Dummy job object for standalone testing."""

    def __init__(self):
        self.logs: list[str] = []

    def add_log(self, msg: str) -> None:
        self.logs.append(msg)
        print(f"  [LOG] {msg}")


def main():
    """Standalone test entrypoint.

    Usage:
        python skill.py --query "todo"
        python skill.py --query "interactive form" --demo-dir /home/chuck/data/media/demos/
        python skill.py --query "demo" --limit 5
    """
    import argparse

    parser = argparse.ArgumentParser(description="demo_browse standalone test")
    parser.add_argument("--query", required=True, help="Search keywords")
    parser.add_argument(
        "--demo-dir", default=str(DEFAULT_DEMO_DIR), help=f"Demos root (default: {DEFAULT_DEMO_DIR})"
    )
    parser.add_argument(
        "--limit", type=int, default=DEFAULT_LIMIT, help=f"Max results (default: {DEFAULT_LIMIT})"
    )
    args = parser.parse_args()

    params = {"query": args.query, "demo_dir": args.demo_dir, "limit": args.limit}
    result = run(params, _MockJob())

    print(f"\n--- demo_browse response ---")
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()