#!/usr/bin/env python3
"""MCP Filesystem Readonly Server — Safe, read-only file system access.

Provides three read-only tools for accessing files on allowed paths:
  - read_file(path)             Read a file's contents (max 1 MB)
  - list_directory(path)        List directory contents
  - search_files(pattern, path) Glob-based file search in allowed dirs

Security:
  - Only paths under allowed roots are accessible
  - Path traversal (..) is blocked
  - Files larger than 1 MB are rejected
  - No writes, deletes, or modifications of any kind

Allowed roots (configurable via ALLOWED_PATHS env var, comma-separated):
  /home/chuck/workspace
  /home/chuck/data/media

Transport: SSE (HTTP, default 0.0.0.0:8000)
"""

import os
import re
import glob
import logging
from pathlib import Path
from typing import Optional

from mcp.server import FastMCP

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

ALLOWED_PATHS_RAW: str = os.environ.get(
    "ALLOWED_PATHS",
    "/home/chuck/workspace,/home/chuck/data/media",
)
ALLOWED_PATHS: list[str] = [
    os.path.realpath(p.strip())
    for p in ALLOWED_PATHS_RAW.split(",")
    if p.strip()
]

MAX_FILE_SIZE: int = int(os.environ.get("MAX_FILE_SIZE", "1048576"))  # 1 MB default
MAX_SEARCH_RESULTS: int = int(os.environ.get("MAX_SEARCH_RESULTS", "200"))
SEARCH_GLOB_LIMIT: int = int(os.environ.get("SEARCH_GLOB_LIMIT", "1000"))

logger = logging.getLogger("mcp_filesystem_readonly")


# ---------------------------------------------------------------------------
# Path safety helpers
# ---------------------------------------------------------------------------


def _resolve_path(path_str: str) -> str:
    """Resolve a path string to its real absolute path."""
    return os.path.realpath(os.path.abspath(path_str))


def _validate_path(path_str: str) -> str:
    """Validate that the resolved path is under an allowed root.

    Returns the resolved absolute path.
    Raises ValueError if the path escapes allowed directories.
    """
    # Reject paths that contain '..' segments (defense in depth)
    if ".." in path_str.split(os.sep):
        raise ValueError(
            f"Path contains '..' segment which is not allowed: '{path_str}'"
        )

    resolved = _resolve_path(path_str)

    # Check if the resolved path is under any allowed root
    for allowed in ALLOWED_PATHS:
        # Ensure the allowed root has a trailing separator to prevent prefix tricks
        allowed_with_sep = allowed + os.sep
        if resolved == allowed or resolved.startswith(allowed_with_sep):
            return resolved

    allowed_list = ", ".join(ALLOWED_PATHS)
    raise ValueError(
        f"Path '{path_str}' (resolved: '{resolved}') is not under an allowed "
        f"directory. Allowed paths: {allowed_list}"
    )


def _check_file_size(filepath: str, max_size: int = MAX_FILE_SIZE) -> None:
    """Check file size and raise ValueError if it exceeds the limit."""
    try:
        size = os.path.getsize(filepath)
    except OSError as exc:
        raise FileNotFoundError(f"Cannot stat file '{filepath}': {exc}") from exc

    if size > max_size:
        max_size_mb = max_size / (1024 * 1024)
        file_size_mb = size / (1024 * 1024)
        raise ValueError(
            f"File '{filepath}' is {file_size_mb:.2f} MB which exceeds the "
            f"{max_size_mb:.0f} MB limit."
        )


# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------

MCPS_HOST: str = os.environ.get("MCPS_HOST", "0.0.0.0")

allowed_list_str = ", ".join(ALLOWED_PATHS)

mcp = FastMCP(
    name="mcp_filesystem_readonly",
    instructions=(
        f"Read-only file system access. "
        f"Only paths under these directories are accessible: "
        f"{allowed_list_str}. "
        f"Files are limited to {MAX_FILE_SIZE / (1024 * 1024):.0f} MB. "
        f"No writes or modifications."
    ),
    host=MCPS_HOST,
)


@mcp.tool(
    name="read_file",
    description=(
        "Read the contents of a file. "
        f"Only paths under {allowed_list_str} are accessible. "
        f"Files must be at most {MAX_FILE_SIZE / (1024 * 1024):.0f} MB."
    ),
)
def read_file(path: str) -> str:
    """Read a file and return its text contents.

    Args:
        path: File path relative to or within allowed directories.
              Use absolute paths like /home/chuck/workspace/file.txt
              or relative paths like workspace/file.txt

    Returns:
        The text content of the file.

    Raises:
        ValueError: If path is outside allowed directories or file exceeds size limit.
        FileNotFoundError: If the file does not exist.
    """
    validated = _validate_path(path)

    if not os.path.isfile(validated):
        raise FileNotFoundError(f"Path is not a file: '{validated}'")

    _check_file_size(validated)

    try:
        with open(validated, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except UnicodeDecodeError:
        raise ValueError(f"File '{validated}' contains non-text data.")
    except OSError as exc:
        raise FileNotFoundError(f"Cannot read file '{validated}': {exc}") from exc

    return content


@mcp.tool(
    name="list_directory",
    description=(
        "List the contents of a directory. "
        f"Only paths under {allowed_list_str} are accessible."
    ),
)
def list_directory(path: str) -> list[dict]:
    """List directory contents with metadata.

    Args:
        path: Directory path within allowed directories.

    Returns:
        List of dicts with keys: name, type ('file' or 'directory'), size (bytes, 0 for dirs).
    """
    validated = _validate_path(path)

    if not os.path.isdir(validated):
        raise NotADirectoryError(f"Path is not a directory: '{validated}'")

    try:
        entries = os.listdir(validated)
    except PermissionError as exc:
        raise PermissionError(
            f"Permission denied reading directory '{validated}': {exc}"
        ) from exc
    except OSError as exc:
        raise RuntimeError(f"Cannot read directory '{validated}': {exc}") from exc

    result = []
    for entry in sorted(entries):
        full_path = os.path.join(validated, entry)
        try:
            stat = os.stat(full_path)
            is_dir = os.path.isdir(full_path)
            result.append({
                "name": entry,
                "type": "directory" if is_dir else "file",
                "size": stat.st_size if not is_dir else 0,
                "path": full_path,
            })
        except OSError:
            # Skip entries we can't stat (e.g., broken symlinks)
            result.append({
                "name": entry,
                "type": "unknown",
                "size": 0,
                "path": full_path,
            })

    return result


@mcp.tool(
    name="search_files",
    description=(
        "Search for files matching a glob pattern. "
        f"Only searches within {allowed_list_str}."
    ),
)
def search_files(pattern: str, path: Optional[str] = None) -> list[dict]:
    """Search for files matching a glob pattern within allowed directories.

    Args:
        pattern: Glob pattern to match (e.g., '*.py', 'doc*.md', '**/*.json').
                 Supports standard glob wildcards (*, ?, **).
        path: Optional directory to search within. If omitted, searches all
              allowed paths. Must be under an allowed directory.

    Returns:
        List of dicts with keys: name, path, size, type.
        Results are limited to MAX_SEARCH_RESULTS.
    """
    # Reject patterns that try to escape with ..
    if ".." in pattern:
        raise ValueError("Search pattern contains '..' which is not allowed.")

    # If a specific path is given, validate it
    if path:
        search_root = _validate_path(path)
        if not os.path.isdir(search_root):
            raise NotADirectoryError(f"Path is not a directory: '{search_root}'")
        search_roots = [search_root]
    else:
        # Validate all allowed paths exist
        search_roots = []
        for allowed in ALLOWED_PATHS:
            if os.path.isdir(allowed):
                search_roots.append(allowed)
            else:
                logger.warning("Allowed path does not exist or is not a directory: %s", allowed)

    if not search_roots:
        return []

    # For recursive search (**), use glob.glob; for simple, use glob.glob
    use_recursive = "**" in pattern

    results: list[dict] = []
    seen_paths: set[str] = set()

    for root in search_roots:
        search_pattern = os.path.join(root, pattern)

        try:
            matches = glob.glob(search_pattern, recursive=use_recursive)
        except (ValueError, OSError) as exc:
            logger.error("Glob error for pattern '%s': %s", search_pattern, exc)
            continue

        # Limit individual root matches to prevent excessive memory usage
        for match in matches[:SEARCH_GLOB_LIMIT]:
            resolved = _resolve_path(match)

            # Safety check: ensure matched path is still under an allowed root
            allowed = False
            for allowed_path in ALLOWED_PATHS:
                if resolved == allowed_path or resolved.startswith(allowed_path + os.sep):
                    allowed = True
                    break
            if not allowed:
                continue

            if resolved in seen_paths:
                continue
            seen_paths.add(resolved)

            try:
                stat = os.stat(resolved)
                is_dir = os.path.isdir(resolved)
                results.append({
                    "name": os.path.basename(resolved),
                    "path": resolved,
                    "size": stat.st_size if not is_dir else 0,
                    "type": "directory" if is_dir else "file",
                })
            except OSError:
                continue

            if len(results) >= MAX_SEARCH_RESULTS:
                break

        if len(results) >= MAX_SEARCH_RESULTS:
            break

    return results


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Run the MCP filesystem readonly server over SSE transport (0.0.0.0:8000)."""
    logging.basicConfig(level=logging.INFO)
    logger.info("Starting mcp_filesystem_readonly")
    logger.info("Allowed paths: %s", ", ".join(ALLOWED_PATHS))
    logger.info("Max file size: %d bytes (%.0f MB)", MAX_FILE_SIZE, MAX_FILE_SIZE / (1024 * 1024))
    mcp.run(transport="sse")  # SSE defaults to 0.0.0.0:8000


if __name__ == "__main__":
    main()
