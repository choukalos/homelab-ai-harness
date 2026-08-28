#!/usr/bin/env python3
"""
publish_file skill — publish a file to the blog's public drop zone.

Purpose:
  Copy a file from an approved source root into
  /home/chuck/data/media/public/{subdirectory}/, where the portal container
  serves it at https://choukalos.com/files/{subdirectory}/{name}.

Security (blog-todo.md B5 / §2.3):
  - Source must be a regular file under an approved root
    (/home/chuck/data/media/ or /home/chuck/workspace/) — no traversal,
    no symlinks, no special files.
  - Destination is always inside the public drop zone (subdirectory
    allowlist + sanitized filename).
  - Size cap (default 500MB, env PUBLISH_FILE_MAX_BYTES).
  - Atomic write: copy to a temp file in the destination directory,
    sha256 while copying, then os.replace. No partial files ever visible.
  - No network access, no LLM, no other side effects.

Result:
  {summary, artifact_path, report: {path, url, size_bytes, sha256,
   destination_name, subdirectory}}
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger("skill.publish_file")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PUBLISH_ROOT = Path(os.environ.get("PUBLISH_FILE_ROOT", "/home/chuck/data/media/public"))
SOURCE_ROOTS = [
    Path("/home/chuck/data/media"),
    Path("/home/chuck/workspace"),
]
SUBDIRS = ("ai", "files", "images", "audio", "video")
MAX_BYTES = int(os.environ.get("PUBLISH_FILE_MAX_BYTES", str(500 * 1024 * 1024)))
PUBLIC_BASE = os.environ.get("PUBLISH_FILE_PUBLIC_BASE", "https://choukalos.com/files")
MAX_NAME_LEN = 150
_CHUNK = 4 * 1024 * 1024

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class PublishError(ValueError):
    """Validation or publish failure (message is safe to surface)."""


def _validate_source(source_path: str) -> Path:
    """Resolve and validate the source file. Returns the resolved Path."""
    if not source_path or "\x00" in source_path:
        raise PublishError("source_path is required and must not contain NUL bytes")
    p = Path(source_path)
    if not p.is_absolute():
        raise PublishError("source_path must be absolute")
    resolved = p.resolve()
    # Symlinks: resolve() follows them; reject if the *given* path was a
    # symlink (policy: no symlinks in the publish path).
    if p.is_symlink():
        raise PublishError("source must not be a symlink")
    if not resolved.is_file():
        raise PublishError(f"source is not a regular file: {source_path}")
    if resolved.is_symlink():
        raise PublishError("source must not be a symlink")
    # Special files (fifo/socket/device) — is_file() is False for those, but
    # be explicit.
    import stat
    if not stat.S_ISREG(resolved.stat().st_mode):
        raise PublishError("source must be a regular file (no fifos/sockets/devices)")
    # Containment: must be under an approved source root.
    for root in SOURCE_ROOTS:
        root_resolved = root.resolve()
        if resolved == root_resolved or resolved.is_relative_to(root_resolved):
            return resolved
    raise PublishError(
        "source is outside the approved roots "
        f"({', '.join(str(r) for r in SOURCE_ROOTS)})"
    )


def _validate_destination(subdirectory: str, destination_name: str) -> Path:
    """Validate and build the destination path (always inside PUBLISH_ROOT)."""
    if subdirectory not in SUBDIRS:
        raise PublishError(f"subdirectory must be one of {list(SUBDIRS)}")
    if "/" in destination_name or "\\" in destination_name:
        raise PublishError("destination_name must be a plain filename (no path separators)")
    name = destination_name
    if not name or len(name) > MAX_NAME_LEN:
        raise PublishError(f"destination_name must be 1..{MAX_NAME_LEN} chars")
    if name.startswith((".", "-")) or name in ("~",):
        raise PublishError("destination_name must not start with '.' or '-'")
    if not _NAME_RE.match(name):
        raise PublishError(
            "destination_name may contain only letters, digits, '.', '_', '-'"
            " (must start with a letter or digit)"
        )
    dest_dir = PUBLISH_ROOT / subdirectory
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / name
    # Final containment check (defence in depth).
    dest_resolved = dest.resolve()
    if not dest_resolved.is_relative_to(PUBLISH_ROOT.resolve()):
        raise PublishError("destination escaped the public root (should be impossible)")
    return dest


def _human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024  # type: ignore[assignment]
    return f"{n:.1f} GB"


def _copy_atomic(src: Path, dest: Path) -> tuple[int, str]:
    """Copy src → dest atomically (temp + os.replace), hashing en route.

    Returns (size_bytes, sha256_hex)."""
    size = src.stat().st_size
    if size > MAX_BYTES:
        raise PublishError(
            f"file is {_human(size)} — exceeds the {_human(MAX_BYTES)} cap"
        )
    fd, tmp_name = tempfile.mkstemp(prefix=".publish_", dir=str(dest.parent))
    try:
        sha = hashlib.sha256()
        with os.fdopen(fd, "wb") as out, open(src, "rb") as fsrc:
            while True:
                chunk = fsrc.read(_CHUNK)
                if not chunk:
                    break
                out.write(chunk)
                sha.update(chunk)
        os.chmod(tmp_name, 0o644)  # world-readable, non-executable
        os.replace(tmp_name, dest)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return size, sha.hexdigest()


# ---------------------------------------------------------------------------
# Entry point (skill runner contract)
# ---------------------------------------------------------------------------


def run(params: dict[str, Any], job: Any) -> dict[str, Any]:
    """Execute the publish. See module docstring for the contract."""
    source_path = str(params.get("source_path") or "").strip()
    destination_name = str(params.get("destination_name") or "").strip()
    subdirectory = str(params.get("subdirectory") or "ai").strip()
    overwrite = bool(params.get("overwrite", False))

    if not source_path:
        return {"error": "source_path is required"}

    job.add_log(f"publish_file: source={source_path} subdir={subdirectory} overwrite={overwrite}")

    try:
        src = _validate_source(source_path)
        name = destination_name or src.name
        dest = _validate_destination(subdirectory, name)

        if dest.exists() and not overwrite:
            return {
                "error": (
                    f"destination already exists: {dest} "
                    "(pass overwrite=true to replace it)"
                )
            }

        job.add_log(f"publish_file: copying {src} → {dest}")
        size, digest = _copy_atomic(src, dest)
    except PublishError as exc:
        job.add_log(f"publish_file: rejected — {exc}")
        return {"error": str(exc)}

    rel = f"{subdirectory}/{dest.name}"
    url = f"{PUBLIC_BASE}/{rel}"
    report = {
        "path": str(dest),
        "url": url,
        "size_bytes": size,
        "sha256": digest,
        "destination_name": dest.name,
        "subdirectory": subdirectory,
    }
    job.add_log(f"publish_file: done — {size} bytes, sha256={digest[:12]}… → {url}")
    return {
        "summary": f"published {dest.name} ({_human(size)}) → {url}",
        "artifact_path": str(dest),
        "report": report,
    }