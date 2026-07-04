#!/usr/bin/env python3
"""
family_kb_ingest skill — thin wrapper for the AI Harness knowledge ingestion endpoint.

Purpose:
  Takes a file path, validates it exists, and sends ingestion metadata to the
  AI Harness knowledge/ingest endpoint. The Harness handles text extraction,
  chunking, embedding, and storage in Qdrant.

Workflow:
  1. Validate the file_path parameter exists and is readable.
  2. POST to HARNESS_URL/knowledge/ingest with file info (path, name, size, collection).
  3. Return the harness ingestion result as-is.

Constraints:
  - Max runtime: 300 seconds (5 minutes).
  - No MCP tools — direct HTTP call to the AI Harness.
  - Stateless: no rollback needed.

FUTURE TODO:
  - Add OCR support for image files (requires vision model or pytesseract).
  - Add table extraction for PDFs with tabular data (requires pdfplumber or tabula-py).
  - Add support for multi-file batch ingestion.

See skill.yml for the full manifest and README.md for usage.
"""

import json
import logging
import os
import signal
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MAX_RUNTIME_SECS = int(os.environ.get("FAMILY_KB_INGEST_MAX_RUNTIME", "300"))
HARNESS_URL = os.environ.get("FAMILY_KB_INGEST_HARNESS_URL", "http://ai-harness:8090")

logger = logging.getLogger("skill.family_kb_ingest")

# ---------------------------------------------------------------------------
# Timeout enforcement
# ---------------------------------------------------------------------------


class TimeoutError(Exception):
    """Raised when the skill exceeds its maximum runtime."""


def _timeout_handler(signum, frame):
    raise TimeoutError(f"family_kb_ingest exceeded {MAX_RUNTIME_SECS}s max runtime")


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
# Input validation
# ---------------------------------------------------------------------------


def _validate_file(file_path: str) -> dict[str, Any]:
    """
    Validate that the file exists and is readable.

    Returns a dict with file metadata (path, name, extension, size).
    Raises ValueError if validation fails.
    """
    path = Path(file_path)

    if not path.exists():
        raise ValueError(f"File not found: {file_path}")

    if not path.is_file():
        raise ValueError(f"Path is not a regular file: {file_path}")

    if not os.access(str(path), os.R_OK):
        raise ValueError(f"File is not readable: {file_path}")

    size = path.stat().st_size

    # Warn on very large files (> 100MB) but don't reject — the harness decides
    if size > 100 * 1024 * 1024:
        logger.warning("Large file (%.1f MB) — ingestion may take time", size / (1024 * 1024))

    return {
        "file_path": str(path),
        "file_name": path.name,
        "file_extension": path.suffix.lower().lstrip(".") or "none",
        "file_size": size,
    }


# ---------------------------------------------------------------------------
# Harness HTTP call
# ---------------------------------------------------------------------------


def _call_harness_ingest(file_info: dict[str, Any], collection: str) -> dict[str, Any]:
    """
    POST to the AI Harness knowledge ingestion endpoint with file info and target collection.

    Returns the harness response dict.
    """
    import urllib.request
    import urllib.error

    payload = {
        "file_path": file_info["file_path"],
        "file_name": file_info["file_name"],
        "file_extension": file_info["file_extension"],
        "file_size": file_info["file_size"],
        "collection": collection,
    }
    data = json.dumps(payload).encode("utf-8")

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    req = urllib.request.Request(
        f"{HARNESS_URL}/knowledge/ingest",
        data=data,
        headers=headers,
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=MAX_RUNTIME_SECS) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            return body
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace") if exc.fp else str(exc)
        raise RuntimeError(f"Harness HTTP error {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Cannot reach AI Harness at {HARNESS_URL}: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid JSON from AI Harness: {exc}") from exc


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------


def run(params: dict[str, Any], job) -> dict[str, Any]:
    """
    Execute the family_kb_ingest skill.

    Thin wrapper: validates file exists, POSTs to AI Harness /knowledge/ingest,
    returns the harness response.

    Args:
        params: Skill parameters (file_path, collection).
        job: The runner Job object for logging.

    Returns:
        Dict with harness response fields plus input parameters.
    """
    # Validate inputs
    file_path = params.get("file_path")
    if not file_path or not str(file_path).strip():
        result = {"error": "Missing required 'file_path' parameter"}
        if hasattr(job, "add_log"):
            job.add_log("Validation failed: missing file_path")
        return result

    file_path = str(file_path).strip()
    collection = str(params.get("collection", "family_kb")).strip() or "family_kb"

    # Log the invocation
    if hasattr(job, "add_log"):
        job.add_log(f"Executing family_kb_ingest: file='{file_path}', collection='{collection}'")
        job.add_log(f"Harness URL: {HARNESS_URL}")
        job.add_log(f"Max runtime: {MAX_RUNTIME_SECS}s")

    # Install timeout
    _install_timeout()

    try:
        # Validate the file exists and gather metadata
        if hasattr(job, "add_log"):
            job.add_log(f"Validating file: {file_path}")

        file_info = _validate_file(file_path)

        if hasattr(job, "add_log"):
            job.add_log(
                f"File OK: name={file_info['file_name']}, "
                f"ext={file_info['file_extension']}, "
                f"size={file_info['file_size']} bytes"
            )

        # Call the AI Harness knowledge ingestion endpoint
        if hasattr(job, "add_log"):
            job.add_log(f"Calling AI Harness /knowledge/ingest for collection '{collection}'...")

        response = _call_harness_ingest(file_info, collection)

        if hasattr(job, "add_log"):
            job.add_log(f"Harness responded: {json.dumps(response)[:300]}")

        # Build result from harness response
        result: dict[str, Any] = dict(response)
        result["file_path"] = file_path
        result["file_name"] = file_info["file_name"]
        result["collection"] = collection

        if hasattr(job, "add_log"):
            job.add_log("family_kb_ingest completed successfully")

        return result

    except TimeoutError as exc:
        msg = str(exc)
        if hasattr(job, "add_log"):
            job.add_log(f"Timeout: {msg}")
        return {
            "error": msg,
            "file_path": file_path,
            "collection": collection,
            "status": "timeout",
        }

    except ValueError as exc:
        msg = str(exc)
        if hasattr(job, "add_log"):
            job.add_log(f"Validation error: {msg}")
        return {
            "error": msg,
            "file_path": file_path,
            "collection": collection,
            "status": "validation_error",
        }

    except RuntimeError as exc:
        msg = str(exc)
        if hasattr(job, "add_log"):
            job.add_log(f"Runtime error: {msg}")
        return {
            "error": msg,
            "file_path": file_path,
            "collection": collection,
            "status": "error",
        }

    except Exception as exc:
        msg = f"Unexpected error: {exc}"
        if hasattr(job, "add_log"):
            job.add_log(msg)
        return {
            "error": msg,
            "file_path": file_path,
            "collection": collection,
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
        python skill.py --file-path /path/to/document.pdf
        python skill.py --file-path /path/to/notes.txt --collection family_kb
        python skill.py --file-path /path/to/notes.txt --dry-run
        python skill.py --file-path /path/to/notes.txt --harness-url http://localhost:8090
    """
    import argparse

    parser = argparse.ArgumentParser(description="family_kb_ingest standalone test")
    parser.add_argument("--file-path", required=True, help="Path to the file to ingest")
    parser.add_argument(
        "--collection", default="family_kb", help="Target Qdrant collection (default: family_kb)"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Print parameters without calling the harness"
    )
    parser.add_argument(
        "--harness-url",
        default=HARNESS_URL,
        help=f"AI Harness URL (default: {HARNESS_URL})",
    )
    args = parser.parse_args()

    if args.dry_run:
        print("=== DRY RUN ===")
        print(f"  File: {args.file_path}")
        file_exists = Path(args.file_path).exists()
        print(f"  File exists: {file_exists}")
        if file_exists:
            p = Path(args.file_path)
            print(f"  File name: {p.name}")
            print(f"  Extension: {p.suffix.lower().lstrip('.') or 'none'}")
            print(f"  Size: {p.stat().st_size} bytes")
        print(f"  Collection: {args.collection}")
        print(f"  Harness URL: {args.harness_url}")
        print(f"  Endpoint: {args.harness_url}/knowledge/ingest")
        print(f"  Max runtime: {MAX_RUNTIME_SECS}s")
        print()
        print(
            "  Payload: {"
            '"file_path": "...", "file_name": "...", '
            '"file_extension": "...", "file_size": ..., "collection": "..."'
            "}"
        )
        print("  Expected response: {collection, file_name, chunks, status, ...}")

        # FUTURE TODO: OCR for images, table extraction for PDFs
        print()
        print("  FUTURE TODO:")
        print("    - Add OCR support for image files (requires vision model or pytesseract)")
        print("    - Add table extraction for PDFs (requires pdfplumber or tabula-py)")
        print("    - Add multi-file batch ingestion support")
        return

    # Override harness URL for CLI usage
    global HARNESS_URL
    HARNESS_URL = args.harness_url

    params = {"file_path": args.file_path, "collection": args.collection}
    result = run(params, _MockJob())

    print(f"\n--- family_kb_ingest response ---")
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
