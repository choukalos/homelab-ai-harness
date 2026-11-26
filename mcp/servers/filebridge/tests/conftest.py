"""Shared fixtures: policy tree, stub Matrix upstream, bridge app client."""

from __future__ import annotations

import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest

# Make the server root (app.py) importable when pytest runs from tests/.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

POLICY_YAML = """
public_file_serving:
  root: {root}
  allow: [generated, images, demos, presentations]
"""


@pytest.fixture()
def media_root(tmp_path: Path) -> Path:
    """A MEDIA_ROOT mirroring the real subdir layout (policy test tree)."""
    root = tmp_path / "media"
    for sub in ("generated", "images", "demos", "presentations",
                "siri_outputs", "research_reports", "investment_briefs",
                "homelab_reports", "code_reviews", "public"):
        (root / sub).mkdir(parents=True)
    (root / "generated" / "abc.png").write_bytes(b"GEN-FILE-CONTENT-0123456789")
    (root / "images" / "photo.jpg").write_bytes(b"IMG-FILE-CONTENT")
    (root / "demos" / "demo.html").write_bytes(b"<html>demo</html>")
    (root / "presentations" / "deck.pptx").write_bytes(b"PPTX-BYTES")
    (root / "siri_outputs" / "siri_output_2026-01-01T00-00-00_weather.txt").write_bytes(b"SECRET-QA")
    (root / "public" / "video").mkdir(parents=True)
    (root / "public" / "video" / "x.mp4").write_bytes(b"PUBLIC-DROP")
    return root


@pytest.fixture()
def policy_file(tmp_path: Path, media_root: Path) -> Path:
    p = tmp_path / "filebridge.yaml"
    p.write_text(POLICY_YAML.format(root=str(media_root)))
    return p


class _StubHandler(BaseHTTPRequestHandler):
    """Stub Matrix media-pipeline upstream (records requests, canned replies)."""

    server: "_StubServer"  # type: ignore[assignment]

    def log_message(self, *a):  # silence
        pass

    def _send(self, status: int, body: bytes, headers: dict | None = None):
        self.send_response(status)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self._send(200, b'{"ok":true}')
        elif self.path.startswith("/files/"):
            rel = self.path[len("/files/"):]
            data = self.server.stub.files.get(rel)
            if data is None:
                self._send(404, b'{"error":"not found"}')
            else:
                self._send(200, data,
                           {"Content-Type": "application/octet-stream"})
        elif self.path.startswith("/raw/"):
            name = self.path[len("/raw/"):]
            body = bytes(range(256)) * 2  # 512 bytes
            self._send(200, body, {
                "Content-Type": "video/mp4",
                "Content-Disposition": f'attachment; filename="{name}"',
            })
        elif self.path.startswith("/dl/"):
            token = self.path[len("/dl/"):]
            if token == "badtoken":
                self._send(404, b'{"error":"unknown token"}')
            elif token == "goodtoken":
                body = bytes(range(256)) * 4  # 1024 bytes
                rng = self.headers.get("Range")
                if rng and rng.startswith("bytes="):
                    lo, hi = rng[6:].split("-")
                    lo, hi = int(lo), min(int(hi), len(body) - 1)
                    self._send(206, body[lo:hi + 1], {
                        "Content-Range": f"bytes {lo}-{hi}/{len(body)}",
                        "Accept-Ranges": "bytes",
                        "Content-Type": "application/octet-stream",
                    })
                else:
                    self._send(200, body, {
                        "Content-Type": "video/mp4",
                        "Content-Disposition": 'attachment; filename="out.mp4"',
                        "Accept-Ranges": "bytes",
                    })
            else:
                self._send(500, b'{"error":"unexpected token"}')
        else:
            self._send(404, b"nope")

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        stub = self.server.stub
        stub.uploads.append({
            "path": self.path,
            "headers": {k: v for k, v in self.headers.items()},
            "body": body,
            "chunked": self.headers.get("Transfer-Encoding") == "chunked",
        })
        if stub.upload_status is not None:
            self._send(stub.upload_status, stub.upload_body)
        else:
            self._send(200, b'{"path":"media_jobs/uploads/x"}')


class _StubServer:
    def __init__(self):
        self.uploads: list[dict] = []
        self.upload_status: int | None = None
        self.upload_body: bytes = b""
        self.files: dict[str, bytes] = {}  # P12-B: /files/{rel} contents
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), _StubHandler)
        self.httpd.stub = self  # handler access via self.server.stub
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    @property
    def url(self):
        return f"http://127.0.0.1:{self.port}"


@pytest.fixture()
def stub(monkeypatch, media_root, policy_file):
    s = _StubServer()
    s.thread.start()
    monkeypatch.setenv("MEDIA_PIPELINE_URL", s.url)
    monkeypatch.setenv("MEDIA_ROOT", str(media_root))
    monkeypatch.setenv("FILEBRIDGE_POLICY", str(policy_file))
    monkeypatch.setenv("UPLOAD_MAX_MB", "500")
    import app as appmod
    monkeypatch.setattr(appmod, "MEDIA_PIPELINE_URL", s.url)
    monkeypatch.setattr(appmod, "MEDIA_ROOT", media_root)
    monkeypatch.setattr(appmod, "UPLOAD_MAX_MB", 500)
    monkeypatch.setattr(appmod, "UPLOAD_MAX_BYTES", 500 * 1024 * 1024)
    monkeypatch.setattr(appmod, "POLICY", {"root": media_root,
                                          "allow": ["generated", "images", "demos", "presentations"]})
    s.app = appmod.app
    s.client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=appmod.app), base_url="http://127.0.0.1"
    )
    # app.state.client for the upstream leg (lifespan not run under ASGITransport)
    s.app.state.client = httpx.AsyncClient()
    yield s
    s.httpd.shutdown()


@pytest.fixture()
def stub_small_cap(stub, monkeypatch):
    """Same stub with UPLOAD_MAX_MB=1 (1 MiB relay cap) for cap tests."""
    import app as appmod
    monkeypatch.setattr(appmod, "UPLOAD_MAX_MB", 1)
    monkeypatch.setattr(appmod, "UPLOAD_MAX_BYTES", 1 * 1024 * 1024)
    return stub


# ---------------------------------------------------------------------------
# P12-B: full registry (work_areas + publish_targets) on temp paths
# ---------------------------------------------------------------------------

FULL_REGISTRY_YAML = """
public_file_serving:
  root: {root}
  allow: [generated, images, demos, presentations]
work_areas:
  media_staging: {{path: {staging}}}
  pipeline_fetch: {{path: {fetch}}}
  siri_outputs: {{path: {siri}, remote_write: false}}
  nas_media_store: {{path: {nas}, automount: true, shared_output: true}}
  matrix_pipeline: {{api: {api}}}
publish_targets:
  blog:
    root: {blogroot}
    subdirs: [ai, images, audio, video, tabs]
    default_subdir: ai
    url_base: https://choukalos.com/files
    source_roots: [{root}, {staging}]
    size_cap_mb: 100
  nas:
    root: {naspub}
    subdirs: []
    url_base: ""
    source_roots: [{root}, {staging}]
    size_cap_mb: 100
"""


@pytest.fixture()
def full_stub_base(stub, media_root, tmp_path, monkeypatch):
    """`stub` + the full P12-B registry (temp work areas / publish targets).

    Patches app.REGISTRY so the MCP face + token route see it; the P12-A
    HTTP /media/files face keeps the POLICY already patched by `stub`.
    Returns a namespace with the registry doc + the temp area paths."""
    from types import SimpleNamespace

    import app as appmod
    import yaml as _yaml

    staging = tmp_path / "staging"
    fetch = media_root / "generated" / "pipeline"
    siri = media_root / "siri_outputs"
    nas = tmp_path / "nas"
    naspub = nas / "published"
    for d in (staging, fetch, nas, naspub, media_root / "public" / "ai"):
        d.mkdir(parents=True, exist_ok=True)
    (staging / "staged.mp4").write_bytes(b"STAGED-FILE-CONTENT")
    (fetch / "fetched.mp4").write_bytes(b"FETCHED-FILE-CONTENT")

    doc = _yaml.safe_load(FULL_REGISTRY_YAML.format(
        root=str(media_root), staging=str(staging), fetch=str(fetch),
        siri=str(siri), nas=str(nas), api=stub.url,
        blogroot=str(media_root / "public"), naspub=str(naspub)))
    monkeypatch.setattr(appmod, "REGISTRY", doc)
    monkeypatch.setattr(appmod, "PULL_MAX_BYTES", 100 * 1024 * 1024)
    return SimpleNamespace(
        doc=doc, client=stub.client, url=stub.url, stub=stub,
        media_root=media_root, staging=staging, fetch=fetch, siri=siri,
        nas=nas, naspub=naspub)


@pytest.fixture(scope="session")
async def mcp_session():
    """Start the MCP session manager ONCE per test session, inside a
    dedicated background task.

    anyio task groups must be entered AND exited in the same task, so the
    session manager's `run()` (which owns the task group) lives in its own
    task for the whole session. uvicorn starts it via the app lifespan in
    production; ASGITransport never runs lifespans, so tests do it here.
    Idempotent: if `run()` was already started (app lifespan), this just
    waits for stop."""
    import asyncio

    import app as appmod  # noqa: F401  (mounts the face -> session manager exists)
    import mcp_face

    sm = mcp_face.mcp.session_manager
    stop = asyncio.Event()

    async def _run():
        try:
            async with sm.run():
                await stop.wait()
        except RuntimeError:
            await stop.wait()  # already started elsewhere

    task = asyncio.get_running_loop().create_task(_run())
    for _ in range(500):
        if getattr(sm, "_task_group", None) is not None:
            break
        await asyncio.sleep(0.01)
    assert getattr(sm, "_task_group", None) is not None, \
        "MCP session manager did not start"
    yield
    stop.set()
    await asyncio.wait_for(task, timeout=10)


@pytest.fixture()
async def full_stub(full_stub_base, mcp_session):
    """full_stub_base + the MCP session manager running (mcp_session)."""
    yield full_stub_base


# ---------------------------------------------------------------------------
# P12-B: MCP JSON-RPC helpers (streamable HTTP, stateless)
# ---------------------------------------------------------------------------


async def rpc(client, method, params=None, _id=1):
    """POST one JSON-RPC message to the MCP face; return the parsed
    JSON-RPC response (JSON or the last SSE data: line)."""
    import json as _json

    body = {"jsonrpc": "2.0", "id": _id, "method": method}
    if params is not None:
        body["params"] = params
    r = await client.post(
        "/mcp", json=body,
        headers={"Content-Type": "application/json",
                 "Accept": "application/json, text/event-stream"})
    assert r.status_code == 200, f"{method} -> {r.status_code}: {r.text[:300]}"
    ct = r.headers.get("content-type", "")
    if "text/event-stream" in ct:
        data = [l[5:].strip() for l in r.text.splitlines()
                if l.startswith("data:")]
        assert data, r.text[:300]
        return _json.loads(data[-1])
    return r.json()


async def call_tool(client, name, args, _id=1):
    """tools/call -> the tool's dict result (structuredContent or JSON text)."""
    import json as _json

    res = await rpc(client, "tools/call", {"name": name, "arguments": args}, _id)
    assert "result" in res, f"{name} -> error: {res}"
    out = res["result"]
    if out.get("isError"):
        raise AssertionError(f"tool {name} returned isError: {out}")
    if isinstance(out.get("structuredContent"), dict):
        return out["structuredContent"]
    text = out["content"][0]["text"]
    return _json.loads(text)
