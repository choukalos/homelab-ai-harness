"""Work-area file ops — P12-B (file_pull / file_push semantics, SEC-12).

Default-deny: every local source/destination must be a registered work
area (pulls additionally accept URLs / pipeline tokens / media_jobs paths
per decision 2a). D13: a work area with `remote_write: false`
(siri_outputs) rejects writes for ALL callers — including public-token
mints. The one-line JSON audit log (`audit()`) is the trail (decision 2a).
"""

from __future__ import annotations

import json
import logging
import mimetypes
import os
import re
import shutil
import time
import urllib.parse
from pathlib import Path

import httpx

# Mirror of mcp/servers/media/media_pipeline_client.py::_JOB_PREFIX — the
# Matrix GPU-host job dir (keep in sync).
MEDIA_JOBS_PREFIX = "/home/chuck/data/comfyui/run/media_jobs/"

# A bare Matrix pipeline /dl token: no path separators (a work-area source
# is always a full path; the bridge relays /dl/{token} without format
# validation, so the heuristic is disambiguation-only).
TOKENISH_RE = re.compile(r"^[^/]{4,256}$")

log = logging.getLogger("filebridge.fileops")


class FileOpsError(RuntimeError):
    pass


def audit(event: str, **fields) -> None:
    """One-line JSON audit entry (the trail, decision 2a)."""
    entry = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
             "event": event}
    entry.update(fields)
    log.info(json.dumps(entry, separators=(",", ":")))


# ---------------------------------------------------------------------------
# Registry helpers (default-deny)
# ---------------------------------------------------------------------------


def area(doc: dict, name: str) -> dict | None:
    return (doc.get("work_areas") or {}).get(name)


def area_write_error(doc: dict, name: str) -> str | None:
    """Error string if writing into work area `name` must be refused
    (unknown / API area / D13 remote_write:false), else None."""
    a = area(doc, name)
    if a is None:
        return f"unknown work area: {name!r}"
    if "api" in a:
        return (f"{name} is an API area (Matrix pipeline) — use "
                "destination='matrix_pipeline'")
    if a.get("remote_write") is False:
        return (f"work area {name!r} is read-only for remote writes "
                "(D13: siri-only) — rejected for all callers")
    return None


def area_of_path(doc: dict, path: Path) -> str | None:
    """The registered work area containing `path` (None = default-deny)."""
    rp = path.resolve()
    for name, spec in (doc.get("work_areas") or {}).items():
        p = spec.get("path")
        if not p:
            continue
        root = Path(p).resolve()
        if rp == root or root in rp.parents:
            return name
    return None


def _suffix_name(root: Path, name: str) -> Path:
    """Collision-suffixed destination (name -> name_2.ext); never
    overwrites (same convention as media_fetch)."""
    out = root / name
    if not out.exists():
        return out
    stem, dot, ext = name.partition(".")
    base, suffix = (stem, "." + ext) if dot else (name, "")
    n = 2
    while True:
        out = root / f"{base}_{n}{suffix}"
        if not out.exists():
            return out
        n += 1


def _safe_filename(hint: str) -> str | None:
    """A usable basename from a Content-Disposition hint (else None)."""
    base = os.path.basename(urllib.parse.unquote(hint))
    if not base or base in (".", "..") or not re.fullmatch(r"[\w.\-]+", base):
        return None
    return base


# ---------------------------------------------------------------------------
# file_pull
# ---------------------------------------------------------------------------


def classify_source(source: str) -> str:
    """url | pipeline_token | pipeline_path | work_area_path."""
    if source.startswith(("http://", "https://")):
        return "url"
    if source.startswith(MEDIA_JOBS_PREFIX) or source.startswith("media_jobs/"):
        return "pipeline_path"
    if TOKENISH_RE.fullmatch(source):
        return "pipeline_token"
    return "work_area_path"


async def pull_source(client: httpx.AsyncClient, source: str, dest_root: Path,
                      pipeline_url: str, max_bytes: int, doc: dict) -> dict:
    """Fetch `source` into `dest_root`. Returns
    {local_path, size_bytes, source_type}; raises FileOpsError.

    `doc` = the registry — a work_area_path source must be under a
    registered work area (default-deny)."""
    stype = classify_source(source)

    if stype == "work_area_path":
        src = Path(source)
        if not src.is_file():
            raise FileOpsError(f"work-area source not found: {source}")
        if area_of_path(doc, src) is None:
            raise FileOpsError(
                f"source is not under a registered work area (default-deny): "
                f"{source}")
        target = _suffix_name(dest_root, src.name)
        shutil.copyfile(src, target)
        return {"local_path": str(target), "size_bytes": target.stat().st_size,
                "source_type": stype}

    # Remote fetch (url / pipeline_token / pipeline_path).
    if stype == "url":
        url = source
        name = (urllib.parse.unquote(
            urllib.parse.urlparse(source).path.rsplit("/", 1)[-1])
            or "download")
    elif stype == "pipeline_token":
        url = f"{pipeline_url}/dl/{urllib.parse.quote(source)}"
        name = "download"
    else:  # pipeline_path
        # /files/{rel} is relative to the pipeline's job dir (Matrix
        # convention — see media_pipeline_client.fetch): both the absolute
        # /home/chuck/data/comfyui/run/media_jobs/... and the relative
        # media_jobs/<job_id>/<file> forms normalize to <job_id>/<file>.
        if source.startswith(MEDIA_JOBS_PREFIX):
            rel = source[len(MEDIA_JOBS_PREFIX):]
        else:
            rel = source[len("media_jobs/"):]
        url = f"{pipeline_url}/files/{urllib.parse.quote(rel)}"
        name = rel.rsplit("/", 1)[-1] or "download"

    target = _suffix_name(dest_root, name)
    tmp = target.with_name(target.name + ".part")
    n = 0
    try:
        async with client.stream("GET", url) as r:
            if r.status_code != 200:
                raise FileOpsError(
                    f"fetch failed (HTTP {r.status_code}): {source[:200]}")
            hint = r.headers.get("content-disposition", "")
            m = re.search(r'filename="?([^";]+)"?', hint)
            if m:
                fn = _safe_filename(m.group(1))
                if fn:
                    target = _suffix_name(dest_root, fn)
                    tmp = target.with_name(target.name + ".part")
            with open(tmp, "wb") as f:
                async for chunk in r.aiter_bytes(64 * 1024):
                    n += len(chunk)
                    if n > max_bytes:
                        raise FileOpsError(
                            f"download exceeds {max_bytes // (1024 * 1024)} MB "
                            "cap")
                    f.write(chunk)
        os.replace(tmp, target)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return {"local_path": str(target), "size_bytes": n, "source_type": stype}


# ---------------------------------------------------------------------------
# file_push
# ---------------------------------------------------------------------------


async def push_matrix(client: httpx.AsyncClient, file: Path,
                      pipeline_url: str, max_bytes: int) -> dict:
    """Upload `file` to Matrix `/upload` (multipart, streamed from disk).
    Returns Matrix's response ({path: media_jobs/...})."""
    size = file.stat().st_size
    if size > max_bytes:
        raise FileOpsError(
            f"file exceeds {max_bytes // (1024 * 1024)} MB Matrix upload cap")
    ctype = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
    with open(file, "rb") as fh:
        r = await client.post(f"{pipeline_url}/upload",
                              files={"file": (file.name, fh, ctype)})
    if r.status_code != 200:
        raise FileOpsError(f"Matrix /upload failed (HTTP {r.status_code})")
    return r.json()
