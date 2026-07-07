#!/usr/bin/env python3
"""MCP Filesystem Server — Read/write file system access scoped to /home/chuck/workspace.

Provides five tools for file system operations:
  - read_file(path)           Read a file's contents (max 1 MB)
  - write_file(path, content) Write content to a file (creates or overwrites)
  - create_directory(path)    Create a directory (parents created if needed)
  - delete_file(path)         Delete a file
  - list_directory(path)      List directory contents with metadata

Security:
  - Only paths under /home/chuck/workspace are accessible
  - Path traversal (..) is blocked on all operations
  - Files read are limited to 1 MB
  - Write operations validate the resolved path stays within scope
  - Delete operations refuse to delete directories

Scoped path (configurable via SCOPE_PATH env var):
  /home/chuck/workspace

Transport: streamable-http (HTTP, default 0.0.0.0:8000)
"""

import os
import logging
from pathlib import Path
from typing import Optional

from mcp.server import FastMCP

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SCOPE_PATH: str = os.environ.get("SCOPE_PATH", "/home/chuck/workspace")
# Resolve to absolute real path so symlink tricks don't bypass scoping
SCOPE_PATH = os.path.realpath(SCOPE_PATH)

MAX_FILE_SIZE: int = int(os.environ.get("MAX_FILE_SIZE", "1048576"))  # 1 MB default
MAX_WRITE_SIZE: int = int(os.environ.get("MAX_WRITE_SIZE", "5242880"))  # 5 MB default

logger = logging.getLogger("mcp_filesystem")


# ---------------------------------------------------------------------------
# Path safety helpers
# ---------------------------------------------------------------------------


def _resolve_path(path_str: str) -> str:
    """Resolve a path string to its real absolute path."""
    return os.path.realpath(os.path.abspath(path_str))


def _validate_path(path_str: str) -> str:
    """Validate that the resolved path is under the scope directory.

    Returns the resolved absolute path.
    Raises ValueError if the path escapes the scope.
    """
    # Reject paths that contain '..' segments (defense in depth)
    if ".." in path_str.split(os.sep):
        raise ValueError(
            f"Path contains '..' segment which is not allowed: '{path_str}'"
        )

    resolved = _resolve_path(path_str)

    # Check that resolved path is exactly the scope or under it
    scope_sep = SCOPE_PATH + os.sep
    if resolved == SCOPE_PATH or resolved.startswith(scope_sep):
        return resolved

    raise ValueError(
        f"Path '{path_str}' (resolved: '{resolved}') is outside the scoped "
        f"directory '{SCOPE_PATH}'."
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

mcp = FastMCP(
    name="mcp_filesystem",
    instructions=(
        f"File system access scoped to {SCOPE_PATH}. "
        f"Read files up to {MAX_FILE_SIZE / (1024 * 1024):.0f} MB. "
        f"Write files up to {MAX_WRITE_SIZE / (1024 * 1024):.0f} MB. "
        f"All operations are restricted to the scoped directory."
    ),
    host=MCPS_HOST,
)


@mcp.tool(
    name="read_file",
    description=(
        f"Read the contents of a file. Only paths under {SCOPE_PATH} are accessible. "
        f"Files must be at most {MAX_FILE_SIZE / (1024 * 1024):.0f} MB."
    ),
)
def read_file(path: str) -> str:
    """Read a file and return its text contents.

    Args:
        path: File path within the scoped directory.
              Use absolute paths like /home/chuck/workspace/file.txt
              or relative paths like workspace/file.txt

    Returns:
        The text content of the file.

    Raises:
        ValueError: If path is outside the scoped directory or file exceeds size limit.
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
    name="write_file",
    description=(
        f"Write content to a file. Only paths under {SCOPE_PATH} are accessible. "
        f"Files must be at most {MAX_WRITE_SIZE / (1024 * 1024):.0f} MB. "
        f"Creates parent directories if needed. Overwrites existing files."
    ),
)
def write_file(path: str, content: str) -> str:
    """Write content to a file, creating parent directories if needed.

    Args:
        path: File path within the scoped directory.
        content: Text content to write to the file.

    Returns:
        Confirmation message with the file path and byte count.

    Raises:
        ValueError: If path is outside the scoped directory or content exceeds size limit.
    """
    if len(content.encode("utf-8")) > MAX_WRITE_SIZE:
        max_mb = MAX_WRITE_SIZE / (1024 * 1024)
        raise ValueError(
            f"Content is {len(content.encode('utf-8')) / (1024 * 1024):.2f} MB which "
            f"exceeds the {max_mb:.0f} MB write limit."
        )

    validated = _validate_path(path)

    # Ensure parent directory exists
    parent = os.path.dirname(validated)
    if parent:
        os.makedirs(parent, exist_ok=True)

    try:
        with open(validated, "w", encoding="utf-8") as f:
            f.write(content)
    except OSError as exc:
        raise RuntimeError(f"Cannot write file '{validated}': {exc}") from exc

    bytes_written = len(content.encode("utf-8"))
    return f"Successfully wrote {bytes_written} bytes to '{validated}'."


@mcp.tool(
    name="create_directory",
    description=(
        f"Create a directory (and parents if needed). Only under {SCOPE_PATH}."
    ),
)
def create_directory(path: str) -> str:
    """Create a directory, creating parent directories if they don't exist.

    Args:
        path: Directory path within the scoped directory.

    Returns:
        Confirmation message with the created directory path.

    Raises:
        ValueError: If path is outside the scoped directory.
    """
    validated = _validate_path(path)

    try:
        os.makedirs(validated, exist_ok=True)
    except OSError as exc:
        raise RuntimeError(f"Cannot create directory '{validated}': {exc}") from exc

    return f"Directory created (or already exists): '{validated}'."


@mcp.tool(
    name="delete_file",
    description=(
        f"Delete a file. Only files under {SCOPE_PATH}. Directories cannot be deleted."
    ),
)
def delete_file(path: str) -> str:
    """Delete a single file. Directories are not deleted.

    Args:
        path: File path within the scoped directory.

    Returns:
        Confirmation message.

    Raises:
        ValueError: If path is outside the scoped directory or is a directory.
        FileNotFoundError: If the file does not exist.
    """
    validated = _validate_path(path)

    if os.path.isdir(validated):
        raise ValueError(
            f"Path is a directory: '{validated}'. delete_file only deletes files. "
            f"Use a directory-aware tool for removing directories."
        )

    if not os.path.isfile(validated):
        raise FileNotFoundError(f"File not found: '{validated}'")

    try:
        os.remove(validated)
    except OSError as exc:
        raise RuntimeError(f"Cannot delete file '{validated}': {exc}") from exc

    return f"Deleted file: '{validated}'."


@mcp.tool(
    name="list_directory",
    description=f"List the contents of a directory. Only under {SCOPE_PATH}.",
)
def list_directory(path: str) -> list[dict]:
    """List directory contents with metadata.

    Args:
        path: Directory path within the scoped directory.

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


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Run the MCP filesystem server over streamable-http transport (0.0.0.0:8000)."""
    logging.basicConfig(level=logging.INFO)
    logger.info("Starting mcp_filesystem")
    logger.info("Scope path: %s", SCOPE_PATH)
    logger.info("Max read size: %d bytes (%.0f MB)", MAX_FILE_SIZE, MAX_FILE_SIZE / (1024 * 1024))
    logger.info("Max write size: %d bytes (%.0f MB)", MAX_WRITE_SIZE, MAX_WRITE_SIZE / (1024 * 1024))
    mcp.run(transport="streamable-http")  # defaults to 0.0.0.0:8000


if __name__ == "__main__":
    main()