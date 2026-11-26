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
        transport=httpx.ASGITransport(app=appmod.app), base_url="http://testserver"
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
