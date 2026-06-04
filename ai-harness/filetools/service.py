"""Core business logic for filetools — workspace-constrained file operations."""

import os
import fnmatch
import difflib

from pathlib import Path
from typing import Optional

from fastapi import HTTPException, status

from core.config import WORKSPACE
from filetools.schemas import (
    FileEntry,
    ListDirRequest,
    ListDirResponse,
    SearchRequest,
    SearchResult,
    SearchResponse,
    ReadFileRequest,
    ReadFileResponse,
    WriteFileRequest,
    WriteFileResponse,
    UpdateFileRequest,
    UpdateFileResponse,
    DeleteFileRequest,
    DeleteFileResponse,
    DiffRequest,
    DiffResponse,
    PatchRequest,
    PatchResponse,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve(path_str: str) -> Path:
    """Resolve a user-supplied relative path safely within WORKSPACE.

    Prevents path traversal by resolving against the workspace root and
    verifying the final path stays inside it.
    """
    workspace = Path(WORKSPACE)
    if not workspace.is_dir():
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Workspace directory does not exist: {WORKSPACE}",
        )

    # Strip leading separators so "../.." at the start can't escape
    cleaned = path_str.lstrip("/")

    target = (workspace / cleaned).resolve()

    # Ensure the resolved target is still inside workspace
    try:
        target.relative_to(workspace.resolve())
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Path escapes workspace: {path_str}",
        )

    return target


def _relative(target: Path) -> str:
    """Return the relative portion of *target* from WORKSPACE."""
    return str(target.relative_to(Path(WORKSPACE).resolve()))


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------

def list_directory(req: ListDirRequest) -> ListDirResponse:
    target = _resolve(req.path)
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"Not found: {req.path}")
    if not target.is_dir():
        raise HTTPException(status_code=400, detail=f"Not a directory: {req.path}")

    entries: list[FileEntry] = []

    if req.recursive:
        for root, dirs, files in os.walk(target):
            depth = Path(root).relative_to(target).parts
            if len(depth) >= req.max_depth:
                dirs.clear()  # stop descending
                continue

            # Hidden filtering
            if not req.include_hidden:
                dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__pycache__"]
                files = [f for f in files if not f.startswith(".")]

            for d in sorted(dirs):
                full = Path(root) / d
                entries.append(FileEntry(name=d, path=_relative(full), is_dir=True))

            for f in sorted(files):
                full = Path(root) / f
                try:
                    stat = full.stat()
                    entries.append(FileEntry(name=f, path=_relative(full), is_dir=False, size=stat.st_size))
                except OSError:
                    entries.append(FileEntry(name=f, path=_relative(full), is_dir=False))
    else:
        try:
            items = sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except PermissionError:
            raise HTTPException(status_code=403, detail=f"Permission denied: {req.path}")

        for item in items:
            if not req.include_hidden and item.name.startswith("."):
                continue

            stat = item.stat(follow_symlinks=False)
            entries.append(
                FileEntry(
                    name=item.name,
                    path=_relative(item),
                    is_dir=item.is_dir(),
                    size=stat.st_size if not item.is_dir() else None,
                )
            )

    return ListDirResponse(path=req.path, entries=entries)


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

def search_files(req: SearchRequest) -> SearchResponse:
    search_root = _resolve(req.path)
    if not search_root.exists():
        raise HTTPException(status_code=404, detail=f"Not found: {req.path}")
    if not search_root.is_dir():
        raise HTTPException(status_code=400, detail=f"Not a directory: {req.path}")

    results: list[SearchResult] = []

    # --- Name-based search (glob pattern) ---
    if req.pattern:
        for root, _dirs, files in os.walk(search_root):
            for fname in files:
                if req.extensions:
                    ext = Path(fname).suffix.lower()
                    desired = {e.lower() if e.startswith(".") else f".{e.lower()}" for e in req.extensions}
                    if ext not in desired:
                        continue

                if fnmatch.fnmatch(
                    fname.lower() if not req.case_sensitive else fname,
                    req.pattern.lower() if not req.case_sensitive else req.pattern,
                ):
                    full = Path(root) / fname
                    results.append(SearchResult(path=_relative(full), match_type="name"))
                    if len(results) >= req.max_results:
                        break
            if len(results) >= req.max_results:
                break

    # --- Content-based search (grep-like) ---
    if req.content:
        content_lower = req.content.lower() if not req.case_sensitive else req.content

        for root, _dirs, files in os.walk(search_root):
            for fname in files:
                if req.extensions:
                    ext = Path(fname).suffix.lower()
                    desired = {e.lower() if e.startswith(".") else f".{e.lower()}" for e in req.extensions}
                    if ext not in desired:
                        continue

                full = Path(root) / fname

                # Skip binary-looking or huge files
                try:
                    if full.stat().st_size > 1_000_000:  # 1 MB skip
                        continue
                except OSError:
                    continue

                try:
                    with open(full, "r", encoding="utf-8", errors="ignore") as fh:
                        for line_no, line in enumerate(fh, start=1):
                            if not req.case_sensitive:
                                haystack = line.lower()
                            else:
                                haystack = line
                            if req.content in haystack:
                                preview = line.strip()[:200]
                                results.append(
                                    SearchResult(
                                        path=_relative(full),
                                        match_type="content",
                                        line_number=line_no,
                                        preview=preview,
                                    )
                                )
                                if len(results) >= req.max_results:
                                    break
                except (OSError, UnicodeDecodeError):
                    continue

            if len(results) >= req.max_results:
                break

    return SearchResponse(results=results[: req.max_results], total=len(results))


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

def read_file(req: ReadFileRequest) -> ReadFileResponse:
    target = _resolve(req.path)
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"Not found: {req.path}")
    if target.is_dir():
        raise HTTPException(status_code=400, detail=f"Is a directory, not a file: {req.path}")

    try:
        with open(target, "r", encoding="utf-8") as fh:
            lines = fh.readlines()
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail=f"Cannot read as text: {req.path}")

    # Apply line slicing
    if req.start_line:
        lines = lines[req.start_line - 1 :]
    if req.max_lines:
        lines = lines[: req.max_lines]

    content = "".join(lines)
    return ReadFileResponse(path=req.path, content=content, lines=len(lines))


# ---------------------------------------------------------------------------
# Write (create/overwrite)
# ---------------------------------------------------------------------------

def write_file(req: WriteFileRequest) -> WriteFileResponse:
    target = _resolve(req.path)

    if target.exists() and target.is_dir():
        raise HTTPException(status_code=400, detail=f"Path is a directory: {req.path}")

    if req.create_dirs:
        target.parent.mkdir(parents=True, exist_ok=True)

    with open(target, "w", encoding="utf-8") as fh:
        fh.write(req.content)

    return WriteFileResponse(path=req.path, bytes_written=len(req.content.encode("utf-8")))


# ---------------------------------------------------------------------------
# Update (in-place string replacement)
# ---------------------------------------------------------------------------

def update_file(req: UpdateFileRequest) -> UpdateFileResponse:
    target = _resolve(req.path)
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"Not found: {req.path}")
    if target.is_dir():
        raise HTTPException(status_code=400, detail=f"Is a directory: {req.path}")

    with open(target, "r", encoding="utf-8") as fh:
        content = fh.read()

    count = content.count(req.old_text)
    if count == 0:
        raise HTTPException(
            status_code=400,
            detail=f"Text not found in file: {req.path}",
        )

    new_content = content.replace(req.old_text, req.new_text, count)
    with open(target, "w", encoding="utf-8") as fh:
        fh.write(new_content)

    return UpdateFileResponse(path=req.path, replacements=count)


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

def delete_file(req: DeleteFileRequest) -> DeleteFileResponse:
    target = _resolve(req.path)
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"Not found: {req.path}")

    if target.is_dir():
        if not req.recursive:
            raise HTTPException(
                status_code=400,
                detail="Cannot delete directory without recursive=true",
            )
        # Safety: never allow deleting the workspace root itself
        if target.resolve() == Path(WORKSPACE).resolve():
            raise HTTPException(
                status_code=403,
                detail="Cannot delete workspace root",
            )
        import shutil
        shutil.rmtree(target)
    else:
        target.unlink()

    return DeleteFileResponse(path=req.path, deleted=True)


# ---------------------------------------------------------------------------
# Diff
# ---------------------------------------------------------------------------

def diff_files(req: DiffRequest) -> DiffResponse:
    a_path = _resolve(req.path_a)
    b_path = _resolve(req.path_b)

    for tp, label in [(a_path, "path_a"), (b_path, "path_b")]:
        if not tp.exists():
            raise HTTPException(status_code=404, detail=f"Not found: {label}")
        if tp.is_dir():
            raise HTTPException(status_code=400, detail=f"Is a directory: {label}")

    try:
        with open(a_path, "r", encoding="utf-8") as fh:
            lines_a = fh.readlines()
        with open(b_path, "r", encoding="utf-8") as fh:
            lines_b = fh.readlines()
    except UnicodeDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Cannot read as text: {e}")

    diff = list(
        difflib.unified_diff(
            lines_a,
            lines_b,
            fromfile=req.path_a,
            tofile=req.path_b,
            lineterm="",
        )
    )

    return DiffResponse(diff="".join(diff) if diff else "(no changes)", path_a=req.path_a, path_b=req.path_b)


# ---------------------------------------------------------------------------
# Patch
# ---------------------------------------------------------------------------

def patch_file(req: PatchRequest) -> PatchResponse:
    target = _resolve(req.path)
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"Not found: {req.path}")
    if target.is_dir():
        raise HTTPException(status_code=400, detail=f"Is a directory: {req.path}")

    try:
        with open(target, "r", encoding="utf-8") as fh:
            original = fh.read()
    except UnicodeDecodeError:
        return PatchResponse(path=req.path, applied=False, message="Cannot read file as text")

    # Create backup
    if req.backup:
        backup = target.with_suffix(target.suffix + ".bak")
        try:
            backup.write_text(original, encoding="utf-8")
        except OSError:
            pass  # non-critical

    # Try applying as unified diff using difflib / fileinput approach
    try:
        patched_content, applied = _apply_unified_diff(original, req.patch, str(target))

        with open(target, "w", encoding="utf-8") as fh:
            fh.write(patched_content)

        return PatchResponse(
            path=req.path,
            applied=applied,
            message="Patch applied successfully" if applied else "Partial patch — some hunks may have failed",
        )
    except Exception as e:
        # Restore from backup if we wrote bad data
        if req.backup and target.exists():
            try:
                backup = target.with_suffix(target.suffix + ".bak")
                if backup.exists():
                    target.write_text(backup.read_text(encoding="utf-8"), encoding="utf-8")
            except OSError:
                pass
        return PatchResponse(path=req.path, applied=False, message=f"Patch failed: {e}")


def _apply_unified_diff(original: str, patch_str: str, filepath: str) -> tuple[str, bool]:
    """Apply a unified diff patch to the original content.

    Returns (patched_content, fully_applied).
    """
    import io
    import re

    lines = original.splitlines(keepends=True)
    patch_file = io.StringIO(patch_str)

    hunk_re = re.compile(
        r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@"
    )

    result = list(lines)
    hunks_applied = 0

    for line in patch_file:
        line = line.rstrip("\n")
        m = hunk_re.match(line)
        if not m:
            continue

        old_start = int(m.group(1))
        old_count = int(m.group(2)) if m.group(2) is not None else 1
        new_start = int(m.group(3))
        new_count = int(m.group(4)) if m.group(4) is not None else 1

        # Read hunk lines
        hunk_lines = []
        for hline in patch_file:
            hline_stripped = hline.rstrip("\n")
            if hunk_re.match(hline_stripped):
                # start of next hunk, put back
                break
            hunk_lines.append(hline_stripped)

        # Apply hunk
        offset = old_start - 1
        # Find the best match offset (handle shifted line numbers)
        best_offset = _find_hunk_offset(result, offset, hunk_lines, old_count)

        if best_offset is not None:
            # Remove old lines
            del result[best_offset : best_offset + old_count]
            # Insert new lines
            new_lines = []
            for hl in hunk_lines:
                if hl and hl[0] == "+":
                    new_lines.append(hl[1:] + "\n")
                elif hl and hl[0] == "\\":  # "\ No newline at end of file"
                    continue
            result[best_offset:best_offset] = new_lines
            hunks_applied += 1

    return "".join(result), hunks_applied > 0


def _find_hunk_offset(lines: list, expected_offset: int, hunk_lines: list, old_count: int) -> Optional[int]:
    """Find the best offset to apply a hunk, with some flexibility."""
    # Extract the "from" lines from the hunk
    from_lines = []
    for hl in hunk_lines:
        if hl and hl[0] == "-":
            from_lines.append(hl[1:] + "\n")
        elif hl and hl[0] == " ":
            from_lines.append(hl[1:] + "\n")
        elif hl and hl[0] == "\\":
            continue

    # Try exact offset first
    if expected_offset + len(from_lines) <= len(lines):
        if lines[expected_offset : expected_offset + len(from_lines)] == from_lines:
            return expected_offset

    # Search nearby (±20 lines)
    for delta in range(1, 21):
        for offset in [expected_offset - delta, expected_offset + delta]:
            if 0 <= offset and offset + len(from_lines) <= len(lines):
                if lines[offset : offset + len(from_lines)] == from_lines:
                    return offset

    return None
