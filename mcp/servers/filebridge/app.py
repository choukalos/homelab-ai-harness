"""mcp_filebridge — the homelab's single public file edge (P12-A + P12-B, SEC-12).

Face 1 (public HTTP, behind Caddy on siri.choukalos.com / choukalos.com):

  GET  /health                 — status + pipeline reachability (no secrets).
  GET  /dl/{token}             — transparent streaming relay to
                                 {MEDIA_PIPELINE_URL}/dl/{token}. Range
                                 passthrough, never buffered; token
                                 validation stays on Matrix.
  POST /upload                 — streaming multipart relay to
                                 {MEDIA_PIPELINE_URL}/upload. The Caddy key
                                 gate is unchanged upstream of us; the
                                 X-Api-Key is STRIPPED on the upstream leg
                                 (the family key must not propagate to
                                 Matrix). The UPLOAD_MAX_MB cap is enforced
                                 at the relay too (Matrix enforces it as
                                 well — keep in sync).
  GET  /media/files/dl/{token} — 1b bridge-minted signed token (P12-B):
                                 path-bound, TTL'd (1-168 h), in-process
                                 store; the token IS the credential.
                                 Minted ONLY via the MCP face (file_push
                                 destination="client"). Unknown/expired/
                                 missing -> 404 (never 403). Registered
                                 BEFORE the catch-all below (precedence).
  GET  /media/files/{path}     — serves MEDIA_ROOT via FileResponse (native
                                 Range) ONLY for allowlisted top-level
                                 subdirs (filebridge.yaml, default-deny).
                                 Non-allowlisted / traversal / missing /
                                 directory -> 404 (never 403 — do not leak
                                 which subdirs exist). Lands finding 12.4:
                                 siri_outputs is NOT publicly served.

Face 2 (MCP, via litellm — P12-B, decision 3a): streamable HTTP at
  POST /mcp — tools file_pull / file_push / file_publish /
  file_work_areas / file_targets. No auth of its own: the litellm key
  gate (access groups) decides which callers see the tools; registry
  policies enforce per-area rules regardless of caller. D13:
  siri_outputs (remote_write: false) rejects writes + public tokens for
  ALL callers.

Face 3 (ai-net only — P12-C): the publish engine endpoint
  POST /publish — the single publish engine (publish_engine.py,
  extracted from the publish-file skill; the skill is now a thin wrapper
  that POSTs here). NOT routed publicly (Caddy has no /publish route) and
  the container publishes no host ports, so it is reachable only from the
  ai-net docker network (skill-runner et al.). JSON body:
  {source_path, target, destination_name?, subdirectory?, overwrite?}.
  200 = the report shape {summary, artifact_path, report:{...}};
  400 = {error}.

No public upload of work-area files (D10). No secrets in this container,
ever: env is FILEBRIDGE_PORT, MEDIA_PIPELINE_URL, MEDIA_ROOT, UPLOAD_MAX_MB,
PULL_MAX_MB, FILEBRIDGE_PUBLIC_URL, TZ — no LiteLLM / memory / master / API
keys.

Registry (filebridge.yaml): public_file_serving + work_areas +
publish_targets — linted at boot (fail-fast) and standalone
(`python app.py lint`).

Kill switch: stopping this container kills the public file routes; Matrix
and skill-runner are untouched.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse

import fileops
import mcp_face
import publish_engine
import registry as regmod
import tokens as tokmod

# ---------------------------------------------------------------------------
# Config (env — minimal by design; no secrets)
# ---------------------------------------------------------------------------

FILEBRIDGE_PORT = int(os.environ.get("FILEBRIDGE_PORT", "8000"))
MEDIA_PIPELINE_URL = os.environ.get("MEDIA_PIPELINE_URL", "http://192.168.4.55:8189").rstrip("/")
MEDIA_ROOT = Path(os.environ.get("MEDIA_ROOT", "/home/chuck/data/media"))
UPLOAD_MAX_MB = int(os.environ.get("UPLOAD_MAX_MB", "500"))
UPLOAD_MAX_BYTES = UPLOAD_MAX_MB * 1024 * 1024
# Policy file: next to this file in the image; overridable via env for tests.
POLICY_FILE = Path(os.environ.get("FILEBRIDGE_POLICY", Path(__file__).parent / "filebridge.yaml"))

# Upstream client: connect ~10 s; NO read timeout — a 500 MB download over
# the internet is slow and must never be cut off mid-stream.
UPSTREAM_TIMEOUT = httpx.Timeout(connect=10.0, read=None, write=None, pool=None)

# P12-B: cap for file_pull remote fetches (parity with the 500 MB
# upload/publish caps) + public base for 1b token URLs (Caddy
# /media/files/* on both hosts — not a secret; the token is the credential).
PULL_MAX_MB = int(os.environ.get("PULL_MAX_MB", "500"))
PULL_MAX_BYTES = PULL_MAX_MB * 1024 * 1024
FILEBRIDGE_PUBLIC_URL = os.environ.get(
    "FILEBRIDGE_PUBLIC_URL", "https://siri.choukalos.com/media/files"
).rstrip("/")

# ---------------------------------------------------------------------------
# Registry (P12-B): public_file_serving + work_areas + publish_targets.
# Linted at import (fail-fast at boot / `python app.py lint`).
# ---------------------------------------------------------------------------

REGISTRY = regmod.load(POLICY_FILE)
POLICY = regmod.serving(REGISTRY)  # P12-A shape: {"root": Path, "allow": [...]}
LINT_ERRORS, LINT_WARNINGS = regmod.lint(REGISTRY)
TOKENS = tokmod.TokenStore()

# Response headers we pass through from Matrix on the /dl relay.
DL_PASSTHROUGH_HEADERS = (
    "content-type",
    "content-length",
    "content-disposition",
    "content-range",
    "accept-ranges",
)

# Request headers we forward to Matrix on the /dl relay.
DL_FORWARD_HEADERS = ("range",)

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("filebridge")


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.client = httpx.AsyncClient(timeout=UPSTREAM_TIMEOUT, follow_redirects=False)
    # P12-B: start the MCP session manager's task group. The mounted
    # sub-app's own lifespan is not run by the parent app, so we start it
    # here (uvicorn runs this lifespan). ASGITransport-based tests never
    # run lifespans — they start it via the session-scoped `mcp_session`
    # fixture instead (the RuntimeError guard makes double-start a no-op).
    sm_cm = None
    try:
        sm_cm = mcp_face.mcp.session_manager.run()
        await sm_cm.__aenter__()
    except RuntimeError:
        sm_cm = None
    try:
        yield
    finally:
        if sm_cm is not None:
            await sm_cm.__aexit__(None, None, None)
        await app.state.client.aclose()


app = FastAPI(title="mcp_filebridge", lifespan=lifespan)


# ---------------------------------------------------------------------------
# Request logging — one JSON line per request
# ---------------------------------------------------------------------------


class _RequestLog:
    def __init__(self, request: Request, upstream: str | None):
        self.method = request.method
        self.path = request.url.path
        self.upstream = upstream
        self.client_ip = request.client.host if request.client else "-"
        self.started = time.monotonic()
        self.status: int | None = None
        self.bytes_in = 0
        self.bytes_out = 0

    def emit(self) -> None:
        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "method": self.method,
            "path": self.path,
            "upstream": self.upstream,
            "status": self.status,
            "bytes_in": self.bytes_in,
            "bytes_out": self.bytes_out,
            "duration_ms": int((time.monotonic() - self.started) * 1000),
            "client_ip": self.client_ip,
        }
        log.info(json.dumps(entry, separators=(",", ":")))


def _log_end(rlog: _RequestLog, status: int, bytes_in: int, bytes_out: int) -> None:
    rlog.status = status
    rlog.bytes_in = bytes_in
    rlog.bytes_out = bytes_out
    rlog.emit()


# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------


@app.get("/health")
async def health(request: Request):
    rlog = _RequestLog(request, None)
    pipeline_ok = False
    try:
        r = await request.app.state.client.get(f"{MEDIA_PIPELINE_URL}/health")
        pipeline_ok = r.status_code == 200
    except httpx.HTTPError:
        pipeline_ok = False
    status = 200 if pipeline_ok else 503
    body = JSONResponse(
        {
            "status": "ok" if pipeline_ok else "degraded",
            "pipeline": MEDIA_PIPELINE_URL,
            "pipeline_reachable": pipeline_ok,
            "media_root": str(POLICY["root"]),
            "public_allow": sorted(POLICY["allow"]),
            "upload_max_mb": UPLOAD_MAX_MB,
        },
        status_code=status,
    )
    _log_end(rlog, status, 0, 0)
    return body


# ---------------------------------------------------------------------------
# GET /dl/{token} — transparent streaming relay (never buffers)
# ---------------------------------------------------------------------------


@app.get("/dl/{token}")
async def dl_relay(request: Request, token: str):
    rlog = _RequestLog(request, f"{MEDIA_PIPELINE_URL}/dl/{token}")
    url = f"{MEDIA_PIPELINE_URL}/dl/{token}"
    fwd = {k: v for k, v in request.headers.items() if k.lower() in DL_FORWARD_HEADERS}
    try:
        up = await request.app.state.client.send(
            request.app.state.client.build_request("GET", url, headers=fwd),
            stream=True,
        )
    except httpx.HTTPError:
        _log_end(rlog, 502, 0, 0)
        return JSONResponse({"error": "upstream unreachable"}, status_code=502)

    headers = {
        k: v
        for k, v in up.headers.items()
        if k.lower() in DL_PASSTHROUGH_HEADERS
    }

    async def gen():
        nonlocal rlog
        try:
            async for chunk in up.aiter_bytes(chunk_size=64 * 1024):
                rlog.bytes_out += len(chunk)
                yield chunk
        finally:
            await up.aclose()
            _log_end(rlog, up.status_code, 0, rlog.bytes_out)

    return StreamingResponse(gen(), status_code=up.status_code, headers=headers)


# ---------------------------------------------------------------------------
# POST /upload — streaming multipart relay with relay-side cap
# ---------------------------------------------------------------------------


async def _read_capped(request: Request, limit: int) -> tuple[bytes | None, int]:
    """Read the request body up to `limit` bytes.

    Returns (body, n) where body is None when the cap was exceeded (n is the
    count at which we aborted). Reads are chunked — nothing is held beyond
    the cap.
    """
    n = 0
    parts: list[bytes] = []
    async for chunk in request.stream():
        n += len(chunk)
        if n > limit:
            return None, n
        parts.append(chunk)
    return b"".join(parts), n


@app.post("/upload")
async def upload_relay(request: Request):
    rlog = _RequestLog(request, f"{MEDIA_PIPELINE_URL}/upload")

    # Fast path: declared Content-Length over the cap -> 413 before reading
    # any body bytes.
    cl = request.headers.get("content-length")
    if cl is not None:
        try:
            if int(cl) > UPLOAD_MAX_BYTES:
                _log_end(rlog, 413, int(cl), 0)
                return JSONResponse(
                    {"error": f"upload exceeds {UPLOAD_MAX_MB} MB relay cap"},
                    status_code=413,
                )
        except ValueError:
            pass  # malformed; fall through to counting

    body, n = await _read_capped(request, UPLOAD_MAX_BYTES)
    rlog.bytes_in = n
    if body is None:
        # Chunked (or lying Content-Length) body crossed the cap while
        # streaming: 413 from the relay; Matrix never sees the body.
        _log_end(rlog, 413, n, 0)
        return JSONResponse(
            {"error": f"upload exceeds {UPLOAD_MAX_MB} MB relay cap"},
            status_code=413,
        )

    # X-Api-Key is STRIPPED on the upstream leg: the key gate is Caddy's;
    # the family key must not propagate to Matrix. Content-Type (incl.
    # multipart boundary) is forwarded; httpx sets Content-Length itself
    # from the body we pass.
    fwd = {
        k: v for k, v in request.headers.items() if k.lower() == "content-type"
    }
    try:
        up = await request.app.state.client.post(
            f"{MEDIA_PIPELINE_URL}/upload", content=body, headers=fwd
        )
    except httpx.HTTPError:
        _log_end(rlog, 502, n, 0)
        return JSONResponse({"error": "upstream unreachable"}, status_code=502)

    # Pass through Matrix's response verbatim (incl. its own 413).
    _log_end(rlog, up.status_code, n, len(up.content))
    return Response(
        content=up.content,
        status_code=up.status_code,
        media_type={k: v for k, v in up.headers.items() if k.lower() == "content-type"}.get("content-type"),
    )


# ---------------------------------------------------------------------------
# GET /media/files/dl/{token} — 1b bridge-minted signed token (P12-B)
#
# Path-bound, TTL'd; the token IS the credential. Minted ONLY via the MCP
# face (file_push destination="client") — no public mint endpoint (D10).
# Registered BEFORE the /media/files/{filepath:path} catch-all below so it
# wins route precedence (FastAPI matches in registration order).
# ---------------------------------------------------------------------------


@app.get("/media/files/dl/{token}")
async def media_files_dl(request: Request, token: str):
    rlog = _RequestLog(request, None)
    entry = TOKENS.lookup(token)
    if entry is None or not Path(entry["path"]).is_file():
        # Unknown / expired / missing file -> 404 (never 403 — do not leak
        # which tokens exist).
        _log_end(rlog, 404, 0, 0)
        return JSONResponse({"error": "Not Found"}, status_code=404)
    resp = FileResponse(Path(entry["path"]))  # native Range support
    _log_end(rlog, 200, 0, 0)
    return resp


# ---------------------------------------------------------------------------
# GET /media/files/{filepath:path} — policy-gated work-area serving
# ---------------------------------------------------------------------------


def _resolve_media_file(relpath: str) -> Path | None:
    """Resolve `relpath` under the policy root, or None if it must 404.

    404 conditions (never 403 — do not leak which subdirs exist):
      - empty path / path traversal (".." segments)
      - first segment not in the allowlist (default-deny; includes
        siri_outputs, research_reports, investment_briefs, homelab_reports,
        code_reviews, public)
      - resolved path escapes the root (symlink/contamination defense)
      - missing, or a directory
    """
    if not relpath or ".." in relpath.split("/"):
        return None
    first = relpath.split("/", 1)[0]
    if first not in POLICY["allow"]:
        return None
    root = POLICY["root"].resolve()
    target = (POLICY["root"] / relpath).resolve()
    if target != root and root not in target.parents:
        return None
    if not target.is_file():
        return None
    return target


@app.get("/media/files/{filepath:path}")
async def media_files(request: Request, filepath: str):
    rlog = _RequestLog(request, None)
    target = _resolve_media_file(filepath)
    if target is None:
        _log_end(rlog, 404, 0, 0)
        return JSONResponse({"error": "Not Found"}, status_code=404)
    resp = FileResponse(target)  # native Range support
    _log_end(rlog, 200, 0, 0)
    return resp


# ---------------------------------------------------------------------------
# POST /publish — the publish engine (P12-C; ai-net only, NOT public)
#
# The single publish engine (publish_engine.py, extracted from the
# publish-file skill — the skill is a thin wrapper that POSTs here).
# Reachable only from the ai-net docker network: Caddy has no /publish
# route and the container publishes no host ports.
# ---------------------------------------------------------------------------


@app.post("/publish")
async def publish_endpoint(request: Request):
    rlog = _RequestLog(request, None)
    try:
        body = await request.json()
    except Exception:
        _log_end(rlog, 400, 0, 0)
        return JSONResponse({"error": "invalid JSON body"}, status_code=400)
    if not isinstance(body, dict):
        _log_end(rlog, 400, 0, 0)
        return JSONResponse({"error": "invalid JSON body"}, status_code=400)
    src = str(body.get("source_path") or "").strip()
    target = str(body.get("target") or "").strip()
    if not src or not target:
        _log_end(rlog, 400, 0, 0)
        return JSONResponse(
            {"error": "source_path and target are required"}, status_code=400)
    try:
        # Blocking file I/O (up to the target size cap) -> worker thread
        # so the event loop stays responsive during large local copies.
        out = await asyncio.to_thread(
            publish_engine.publish,
            REGISTRY, target, src,
            subdirectory=str(body.get("subdirectory") or ""),
            destination_name=str(body.get("destination_name") or ""),
            overwrite=bool(body.get("overwrite", False)))
    except publish_engine.PublishError as e:
        fileops.audit("publish", source=src[:200], target=target,
                      status="error", error=str(e))
        _log_end(rlog, 400, 0, 0)
        return JSONResponse({"error": str(e)}, status_code=400)
    fileops.audit("publish", source=src[:200], target=target, status="ok",
                  path=out["report"]["path"],
                  duplicate=out["report"].get("duplicate", False))
    _log_end(rlog, 200, 0, 0)
    return JSONResponse(out)


# ---------------------------------------------------------------------------
# Face 2: MCP — streamable HTTP at POST /mcp (P12-B, decision 3a).
# Mounted LAST so every explicit route above wins (including the
# /media/files/dl/{token} precedence over the /media/files catch-all).
# ---------------------------------------------------------------------------
app.mount("/", mcp_face.mcp.streamable_http_app())


def main() -> None:
    """Boot the bridge (uvicorn). Fails fast on a broken registry."""
    if LINT_ERRORS:
        for e in LINT_ERRORS:
            log.error("registry lint: %s", e)
        raise SystemExit(f"registry lint failed ({len(LINT_ERRORS)} errors) "
                         "— refusing to boot (fix filebridge.yaml)")
    for w in LINT_WARNINGS:
        log.warning("registry lint: %s", w)
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=FILEBRIDGE_PORT)


if __name__ == "__main__":
    # `python app.py lint` — standalone registry lint (exit 0 = green).
    if len(sys.argv) > 1 and sys.argv[1] == "lint":
        raise SystemExit(regmod.lint_cli(REGISTRY))
    main()
