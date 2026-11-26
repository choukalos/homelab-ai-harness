"""mcp_filebridge MCP face (Face 2) — P12-B (SEC-12).

Streamable HTTP at POST /mcp (stateless — each request is independent, so
the LiteLLM proxy's registry handshake + per-call auth work without
session state on our side).

Auth (decision 3a): this face carries NO auth of its own — the litellm
key gate (per-key access groups) decides which callers see these tools.
Registry policies enforce per-area rules regardless of caller. The
one-line JSON audit log (fileops.audit) is the trail (decision 2a).

Tools: file_pull, file_push, file_work_areas, file_targets.
"""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

from mcp.server import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

mcp = FastMCP(
    "mcp_filebridge",
    instructions=(
        "Homelab file bridge — boundary-crossing file moves (public <-> "
        "internal). file_pull(source, work_area): source = http(s) URL | "
        "Matrix pipeline /dl token (bare token) | media_jobs path "
        "(absolute or relative) | a path under a registered work area; "
        "work_area = destination work-area name (basename collisions are "
        "suffixed, never overwritten). file_push(file, destination): file "
        "must be under a registered work area; destination = work-area "
        "name (local copy) | 'matrix_pipeline' (Matrix /upload, returns "
        "the media_jobs path) | 'client' (mints a signed public URL, TTL "
        "1-168 h — the token IS the credential) | publish-target name "
        "(blog/nas). siri_outputs is siri-only (D13): writes and public "
        "tokens are rejected for ALL callers. file_publish(file, target, "
        "destination_name, subdirectory, overwrite) publishes to a "
        "publish target (blog/nas) — validated/atomic/size-capped/"
        " idempotent (identical content = no-op success). file_work_areas() / "
        "file_targets() enumerate the registry."
    ),
    # DNS-rebinding protection ON (container has no published ports — the
    # only production caller is the litellm proxy on the docker network,
    # Host: mcp_filebridge:8000; localhost entries cover local debugging).
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=["mcp_filebridge:*", "127.0.0.1", "127.0.0.1:*",
                       "localhost", "localhost:*", "[::1]", "[::1]:*"],
        allowed_origins=["http://mcp_filebridge:*", "http://127.0.0.1:*",
                         "http://localhost:*", "http://[::1]:*"],
    ),
)
mcp.settings.streamable_http_path = "/mcp"
mcp.settings.stateless_http = True


def _app():
    """The root FastAPI app MODULE — resolve the RUNNING instance.

    The bridge boots as a script (`python app.py`) or via `python -m app`:
    in both cases the running module is __main__, while `import app`
    resolves to a DIFFERENT module object (a fresh import for `python
    app.py`; runpy's spec-import copy for `python -m app`). A second
    instance carries a separate TOKENS store and app.state, so the MCP
    face would mint tokens the HTTP routes never see and report "upstream
    client not initialized" (E2E finding, 2026-11-26 TODO 6). Prefer
    __main__ when it is the app module (TOKENS + app markers); fall back
    to a plain import (unit tests import app as a module, where __main__
    is the pytest runner).
    """
    import sys

    main = sys.modules.get("__main__")
    if main is not None and hasattr(main, "TOKENS") and hasattr(main, "app"):
        return main
    import app as appmod
    return appmod


def _client():
    appmod = _app()
    return getattr(appmod.app.state, "client", None)


@mcp.tool()
async def file_pull(source: str, work_area: str) -> dict:
    """Pull a file into a registered work area.

    source: an http(s) URL (decision 2a — arbitrary URLs), a Matrix
    pipeline /dl token (bare token string), a media_jobs path (absolute
    /home/chuck/data/comfyui/run/media_jobs/... or relative
    media_jobs/<job_id>/<file>), or a path under a registered work area.
    work_area: destination work-area name. Basename collisions are
    suffixed (never overwritten). Returns {local_path, size_bytes,
    source_type, work_area}.
    """
    appmod = _app()
    doc = appmod.REGISTRY
    err = appmod.fileops.area_write_error(doc, work_area)
    if err:
        return {"error": err}
    client = _client()
    if client is None:
        return {"error": "upstream client not initialized"}
    dest_root = Path(appmod.fileops.area(doc, work_area)["path"])
    dest_root.mkdir(parents=True, exist_ok=True)
    try:
        out = await appmod.fileops.pull_source(
            client, source, dest_root, appmod.MEDIA_PIPELINE_URL,
            appmod.PULL_MAX_BYTES, doc)
    except appmod.fileops.FileOpsError as e:
        appmod.fileops.audit("file_pull", source=source[:200],
                             work_area=work_area, status="error",
                             error=str(e))
        return {"error": str(e)}
    appmod.fileops.audit("file_pull", source=source[:200],
                         work_area=work_area, status="ok",
                         local_path=out["local_path"],
                         size_bytes=out["size_bytes"],
                         source_type=out["source_type"])
    return {"local_path": out["local_path"], "size_bytes": out["size_bytes"],
            "source_type": out["source_type"], "work_area": work_area}


@mcp.tool()
async def file_push(file: str, destination: str, subdirectory: str = "",
                    ttl_hours: float = 24.0) -> dict:
    """Push a work-area file to a destination.

    file: a path under a registered work area (default-deny).
    destination: a work-area name (local copy, collision-suffixed) |
    'matrix_pipeline' (Matrix /upload -> {path: media_jobs path}) |
    'client' (mints a 1b signed public URL for the file; ttl_hours 1-168,
    default 24) | a publish-target name (blog/nas; subdirectory selects
    the target subdir, default per target). siri_outputs rejects writes
    for ALL callers (D13).
    """
    appmod = _app()
    doc = appmod.REGISTRY
    f = Path(file)
    if not f.is_file():
        return {"error": f"file not found: {file}"}
    src_area = appmod.fileops.area_of_path(doc, f)
    if src_area is None:
        return {"error": f"file is not under a registered work area "
                         f"(default-deny): {file}"}

    if destination == "matrix_pipeline":
        client = _client()
        if client is None:
            return {"error": "upstream client not initialized"}
        try:
            out = await appmod.fileops.push_matrix(
                client, f, appmod.MEDIA_PIPELINE_URL,
                appmod.UPLOAD_MAX_BYTES)
        except appmod.fileops.FileOpsError as e:
            appmod.fileops.audit("file_push", file=file,
                                 destination=destination, status="error",
                                 error=str(e))
            return {"error": str(e)}
        appmod.fileops.audit("file_push", file=file,
                             destination=destination, status="ok",
                             path=out.get("path"))
        return {"path": out.get("path"), "location": "gpu_host",
                "note": "Matrix media_jobs path — use it in pipeline tools, "
                        "or media_pull for a signed URL"}

    if destination == "client":
        a = appmod.fileops.area(doc, src_area)
        if a is not None and a.get("remote_write") is False:
            appmod.fileops.audit("token_mint", file=file, status="error",
                                 error="D13: siri-only area")
            return {"error": f"work area {src_area!r} is siri-only (D13) — "
                             "public tokens are rejected for all callers"}
        try:
            token, expires = appmod.TOKENS.mint(str(f.resolve()), ttl_hours)
            ttl = appmod.tokmod.clamp_ttl(ttl_hours)
        except ValueError as e:
            return {"error": str(e)}
        url = appmod.tokmod.public_url(token, appmod.FILEBRIDGE_PUBLIC_URL)
        appmod.fileops.audit("token_mint", token=token,
                             path=str(f.resolve()), ttl_h=ttl,
                             via="file_push", status="ok")
        return {"url": url, "expires_at": appmod.tokmod.iso_utc(expires),
                "token": token, "path": str(f.resolve()), "ttl_hours": ttl,
                "note": "the token IS the credential — anyone holding the "
                        "URL can download the file until expiry"}

    a = appmod.fileops.area(doc, destination)
    if a is not None:
        err = appmod.fileops.area_write_error(doc, destination)
        if err:
            return {"error": err}
        dest_root = Path(a["path"])
        dest_root.mkdir(parents=True, exist_ok=True)
        target = appmod.fileops._suffix_name(dest_root, f.name)
        shutil.copyfile(f, target)
        appmod.fileops.audit("file_push", file=file,
                             destination=destination, status="ok",
                             local_path=str(target),
                             size_bytes=target.stat().st_size)
        return {"local_path": str(target),
                "size_bytes": target.stat().st_size,
                "work_area": destination}

    t = (doc.get("publish_targets") or {}).get(destination)
    if t is not None:
        try:
            # The engine does blocking file I/O (up to the size cap) —
            # run it in a worker thread so the event loop stays responsive.
            out = await asyncio.to_thread(
                appmod.publish_engine.publish,
                doc, destination, f, subdirectory=subdirectory)
        except appmod.publish_engine.PublishError as e:
            appmod.fileops.audit("file_push", file=file,
                                 destination=destination, status="error",
                                 error=str(e))
            return {"error": str(e)}
        appmod.fileops.audit("file_push", file=file,
                             destination=destination, status="ok",
                             path=out["report"]["path"],
                             duplicate=out["report"].get("duplicate", False))
        return out

    return {"error": f"unknown destination: {destination!r} (work area, "
                     "'matrix_pipeline', 'client', or publish target)"}


@mcp.tool()
async def file_publish(file: str, target: str, destination_name: str = "",
                       subdirectory: str = "", overwrite: bool = False) -> dict:
    """Publish a file to a registered publish target (blog/nas) — the
    publish-file engine (validated / atomic / size-capped / idempotent).

    file: an absolute path under the target's source_roots (see
    file_targets()). target: a publish-target name ('blog' = the public
    drop zone at choukalos.com/files; 'nas' = /mnt/lego-media-store/
    published, not public). destination_name: optional target filename
    (default: the source basename; plain filename, 1..150 chars).
    subdirectory: target subdir (default: the target's default — 'ai' for
    blog; '' for flat targets like nas). overwrite: force-replace an
    existing destination (default: identical content is a no-op success
    with report.duplicate=true; different content fails with a sha256
    mismatch error). Returns {summary, artifact_path, report:{path, url,
    size_bytes, sha256, destination_name, subdirectory[, duplicate]}} —
    url is null for non-public targets.
    """
    appmod = _app()
    try:
        # Blocking file I/O (up to the target size cap) -> worker thread.
        out = await asyncio.to_thread(
            appmod.publish_engine.publish,
            appmod.REGISTRY, target, file,
            subdirectory=subdirectory, destination_name=destination_name,
            overwrite=overwrite)
    except appmod.publish_engine.PublishError as e:
        appmod.fileops.audit("file_publish", file=str(file)[:200],
                             target=target, status="error", error=str(e))
        return {"error": str(e)}
    appmod.fileops.audit("file_publish", file=str(file)[:200], target=target,
                         status="ok", path=out["report"]["path"],
                         duplicate=out["report"].get("duplicate", False))
    return out


@mcp.tool()
async def file_work_areas() -> dict:
    """Enumerate the registered work areas (name, path/api, flags,
    writable)."""
    doc = _app().REGISTRY
    out = []
    for name, spec in (doc.get("work_areas") or {}).items():
        e: dict = {"name": name}
        if "path" in spec:
            e["path"] = spec["path"]
        else:
            e["api"] = spec["api"]
        for flag in ("remote_write", "automount", "shared_output"):
            if flag in spec:
                e[flag] = spec[flag]
        e["writable"] = ("path" in spec
                         and spec.get("remote_write") is not False)
        out.append(e)
    return {"work_areas": out}


@mcp.tool()
async def file_targets() -> dict:
    """Enumerate the registered publish targets (name, root, subdirs,
    url_base, size_cap_mb, source_roots)."""
    doc = _app().REGISTRY
    out = []
    for name, spec in (doc.get("publish_targets") or {}).items():
        out.append({
            "name": name,
            "root": spec.get("root"),
            "subdirs": spec.get("subdirs") or [],
            "url_base": spec.get("url_base") or "",
            "size_cap_mb": spec.get("size_cap_mb"),
            "source_roots": spec.get("source_roots") or [],
        })
    return {"publish_targets": out}
