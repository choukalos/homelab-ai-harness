#!/usr/bin/env python3
"""Tests for media_transcribe_song + the /transcribe client path.

Runs against a LOCAL MOCK pipeline (stdlib http.server on 127.0.0.1) — it
implements /health, /upload, /download, /transcribe, /jobs/{id}, /files/{name}
with the same contract as the GPU-host media-pipeline. **Nothing here touches
the live pipeline (Matrix :8189)** — safe to run while Matrix is busy.

The yt-dlp step is monkeypatched (no YouTube network access in tests).

Run:  python3 test_transcribe.py        (plain asserts, no pytest needed)
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import sys
import tempfile
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from pathlib import Path
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
JOB_PREFIX = "/home/chuck/data/comfyui/run/media_jobs/"

# ---------------------------------------------------------------------------
# Mock pipeline
# ---------------------------------------------------------------------------


class MockState:
    """In-memory pipeline: jobs, files, and recorded payloads."""

    def __init__(self, delay_polls: int = 10):
        self.root = tempfile.mkdtemp(prefix="mock_pipeline_")
        self.jobs: dict[str, dict] = {}
        self.files: dict[str, bytes] = {}          # media_jobs rel -> bytes
        self.transcribe_payloads: list[dict] = []
        self.next_job = 0
        self.delay_polls = delay_polls            # job completes after N polls

    def new_job(self, flow: str, payload: dict) -> str:
        self.next_job += 1
        jid = f"mock-{self.next_job:03d}"
        self.jobs[jid] = {"id": jid, "flow": flow, "status": "running",
                          "output": None, "error": None, "payload": payload,
                          "polls": 0}
        return jid

    def poll_job(self, jid: str) -> dict:
        j = self.jobs[jid]
        j["polls"] += 1
        if j["flow"] == "transcribe" and j["polls"] >= self.delay_polls:
            j["status"] = "done"
            jobdir = os.path.join(self.root, "media_jobs", jid)
            os.makedirs(jobdir, exist_ok=True)
            out = {}
            artifacts = (
                ("analysis.json",
                 json.dumps({"version": 1, "key": "E minor", "bpm": 128,
                             "sections": []}).encode()),
                ("tab.md", b"# Mock Song - guitar tab\n"),
                ("lyrics.txt", b"[0:01.0] hello world\n"),
                ("song.mid", b"MThd-mock"),
                ("audio.wav", b"RIFF-mock-wav"),
            )
            keymap = {"analysis.json": "analysis", "tab.md": "tab",
                      "lyrics.txt": "lyrics", "song.mid": "midi",
                      "audio.wav": "audio"}
            for name, content in artifacts:
                rel = f"media_jobs/{jid}/{name}"
                with open(os.path.join(jobdir, name), "wb") as f:
                    f.write(content)
                self.files[rel] = content
                out[keymap[name]] = JOB_PREFIX + rel
            j["output"] = out
        return dict(j)


class _Handler(BaseHTTPRequestHandler):
    state: MockState  # set on the subclass

    def log_message(self, *a):  # quiet
        pass

    def _send(self, code: int, body: bytes = b"",
              ctype: str = "application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj):
        self._send(code, json.dumps(obj).encode())

    def do_GET(self):
        if self.path == "/health":
            return self._json(200, {"ok": True, "gpu_locked": False,
                                    "jobs": 0, "max_concurrent": 1,
                                    "max_queue_depth": 5})
        m = re.match(r"^/jobs/([^/]+)$", self.path)
        if m:
            jid = urllib.parse.unquote(m.group(1))
            if jid not in self.state.jobs:
                return self._json(404, {"error": "unknown job"})
            return self._json(200, self.state.poll_job(jid))
        m = re.match(r"^/files/(.+)$", self.path)
        if m:
            rel = urllib.parse.unquote(m.group(1))
            data = self.state.files.get(rel)
            if data is None:
                return self._json(404, {"error": "no such file"})
            return self._send(200, data, "application/octet-stream")
        return self._json(404, {"error": f"unhandled GET {self.path}"})

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        if self.path == "/transcribe":
            payload = json.loads(body)
            # Contract check: path must be a media_jobs path.
            if not str(payload.get("path", "")).startswith(JOB_PREFIX):
                return self._json(400, {"error": "path must be in media_jobs"})
            self.state.transcribe_payloads.append(payload)
            return self._json(200, {"job_id": self.state.new_job(
                "transcribe", payload)})
        if self.path == "/upload":
            m = re.search(rb'filename="([^"]+)"', body)
            fname = m.group(1).decode() if m else "upload.bin"
            idx = body.find(b"\r\n\r\n", m.end() if m else 0)
            data = body[idx + 4:]
            data = data[:data.rfind(b"\r\n--")]
            rel = f"media_jobs/uploads/{fname}"
            self.state.files[rel] = data
            return self._json(200, {"path": JOB_PREFIX + rel})
        if self.path == "/download":
            payload = json.loads(body)
            fname = payload.get("filename") or os.path.basename(
                payload.get("url", "file"))
            rel = f"media_jobs/downloads/{fname}"
            self.state.files[rel] = b"mock-downloaded"
            return self._json(200, {"path": JOB_PREFIX + rel})
        return self._json(404, {"error": f"unhandled POST {self.path}"})


def _start_mock(delay_polls: int = 10):
    state = MockState(delay_polls)
    handler = type("MockHandler", (_Handler,), {"state": state})
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, state, port


# ---------------------------------------------------------------------------
# Setup: point the server at the mock BEFORE importing it
# ---------------------------------------------------------------------------


def _tool_fn(name: str):
    """The @mcp.tool-decorated function (raw fn or FunctionTool wrapper)."""
    import server
    obj = getattr(server, name)
    return getattr(obj, "fn", obj)


def main() -> int:
    httpd, state, port = _start_mock()
    staging = tempfile.mkdtemp(prefix="mock_staging_")
    os.environ["MEDIA_PIPELINE_URL"] = f"http://127.0.0.1:{port}"
    os.environ["MEDIA_USER"] = "testuser"
    os.environ["MEDIA_CLIENT"] = "pytest"
    os.environ["LITELLM_PROXY_URL"] = "http://127.0.0.1:9"  # never called
    os.environ["MEDIA_STAGING_DIR"] = staging
    sys.path.insert(0, HERE)

    import media_pipeline_client
    import server
    server.PIPELINE.poll = 0.2  # fast polling for tests

    passed = 0

    def ok(name: str, cond: bool, detail: str = ""):
        nonlocal passed
        if not cond:
            print(f"FAIL: {name} {detail}")
            raise SystemExit(1)
        passed += 1
        print(f"  ok: {name}")

    print("== client: finalize_job ==")
    job = {"output": {k: JOB_PREFIX + f"media_jobs/mock-001/{v}"
                      for k, v in (("analysis", "analysis.json"),
                                   ("tab", "tab.md"), ("lyrics", "lyrics.txt"),
                                   ("midi", "song.mid"), ("audio", "audio.wav"))}}
    fin = server.PIPELINE.finalize_job(job)
    ok("transcribe branch: all 5 paths + location",
       all(fin.get(k) for k in ("analysis", "tab", "lyrics", "midi", "audio"))
       and fin.get("location") == "gpu_host", str(fin))
    ok("video regression",
       server.PIPELINE.finalize_job({"output": {"video": "x.mp4"}})
       == {"path": "x.mp4", "location": "gpu_host"})
    ok("raw-output regression",
       server.PIPELINE.finalize_job({"output": {"voice": "v"}})
       == {"voice": "v"})

    print("== client: transcribe() ==")
    host_audio = JOB_PREFIX + "media_jobs/uploads/song.wav"
    r = server.PIPELINE.transcribe(host_audio, non_blocking=True,
                                   user="u1", client="c1")
    ok("non_blocking -> {job_id}", set(r) == {"job_id"}, str(r))
    p = state.transcribe_payloads[-1]
    ok("payload: path/instrument/lyrics/stems + identity",
       p["path"] == host_audio and p["instrument"] == "guitar"
       and p["lyrics"] is True and p["stems"] is False
       and p["user"] == "u1" and p["client"] == "c1", str(p))
    r = server.PIPELINE.transcribe(host_audio, user="u1", client="c1")
    ok("blocking -> output dict with 5 keys",
       set(r) == {"analysis", "tab", "lyrics", "midi", "audio"}, str(r))

    print("== client: poll_job (running -> done) ==")
    jid = server.PIPELINE.transcribe(host_audio, non_blocking=True)["job_id"]
    r = server.PIPELINE.poll_job(jid, wait_seconds=1.0)
    ok("still running within budget", r["status"] == "running", str(r))
    r = server.PIPELINE.poll_job(jid, wait_seconds=10.0)
    ok("done after budget", r["status"] == "done"
       and set(r["job"]["output"]) == {"analysis", "tab", "lyrics", "midi",
                                       "audio"})

    print("== source resolution ==")
    ok("host path passthrough",
       server._resolve_transcribe_source(host_audio) == host_audio)
    try:
        server._resolve_transcribe_source("/tmp/definitely-not-here.wav")
        ok("missing local file -> PipelineError", False)
    except media_pipeline_client.PipelineError as e:
        ok("missing local file -> PipelineError", "not found" in str(e))
    outside = os.path.join(tempfile.mkdtemp(prefix="mock_outside_"), "x.wav")
    Path(outside).write_bytes(b"x")
    try:
        server._resolve_transcribe_source(outside)
        ok("local file outside staging -> PipelineError", False)
    except media_pipeline_client.PipelineError as e:
        ok("local file outside staging -> PipelineError",
           "staging" in str(e), str(e))
    staged = os.path.join(staging, "staged-song.wav")
    with open(staged, "wb") as f:
        f.write(b"RIFF-staged")
    p = server._resolve_transcribe_source(staged)
    ok("staged file -> /upload path",
       p == JOB_PREFIX + "media_jobs/uploads/staged-song.wav", p)
    ok("staged file bytes uploaded",
       state.files.get("media_jobs/uploads/staged-song.wav") == b"RIFF-staged")
    p = server._resolve_transcribe_source("http://example.com/song.mp3")
    ok("direct URL -> /download path",
       p == JOB_PREFIX + "media_jobs/downloads/song.mp3", p)

    # YouTube: monkeypatch the yt-dlp step (no network in tests).
    def fake_yt(url: str, tmpdir: str) -> str:
        p = os.path.join(tmpdir, "song.m4a")
        with open(p, "wb") as f:
            f.write(b"mock-m4a")
        return p
    server._youtube_audio_download = fake_yt
    p = server._resolve_transcribe_source(
        "https://www.youtube.com/watch?v=abc123")
    ok("YouTube URL -> yt-dlp -> /upload path",
       p == JOB_PREFIX + "media_jobs/uploads/song.m4a", p)
    ok("YouTube audio bytes uploaded",
       state.files.get("media_jobs/uploads/song.m4a") == b"mock-m4a")
    ok("YOUTUBE_RE matches youtu.be",
       bool(server.YOUTUBE_RE.search("https://youtu.be/xyz")))

    print("== tool: media_transcribe_song ==")
    tool = _tool_fn("media_transcribe_song")

    r = asyncio.run(tool(source="x", instrument="piano"))
    ok("instrument=piano -> clean error",
       "guitar" in r.get("error", ""), str(r))

    r = asyncio.run(tool(source="/tmp/definitely-not-here.wav"))
    ok("bad source -> clean error", "error" in r, str(r))

    r = asyncio.run(tool(source=staged, non_blocking=True))
    ok("non_blocking -> {job_id, status}",
       r.get("status") == "running" and "job_id" in r, str(r))

    r = asyncio.run(tool(source=staged))
    ok("blocking -> 5 paths + source + location",
       all(r.get(k) for k in ("analysis", "tab", "lyrics", "midi", "audio"))
       and r.get("source") == staged and r.get("location") == "gpu_host",
       str(r))
    p = state.transcribe_payloads[-1]
    ok("identity stamped (MEDIA_USER fallback, no auth header)",
       p["user"] == "testuser" and p["client"] == "pytest", str(p))
    ok("stems/lyrics forwarded",
       asyncio.run(tool(source=staged, stems=True, lyrics=False,
                        non_blocking=True)) is not None)
    p = state.transcribe_payloads[-1]
    ok("stems=true/lyrics=false in payload",
       p["stems"] is True and p["lyrics"] is False, str(p))

    print("== tool: media_job_result (transcribe job) ==")
    r = asyncio.run(tool(source=staged, non_blocking=True))
    jid = r["job_id"]
    jr = asyncio.run(_tool_fn("media_job_result")(job_id=jid,
                                                  wait_seconds=1.0))
    ok("first poll -> running", jr.get("status") == "running", str(jr))
    jr = asyncio.run(_tool_fn("media_job_result")(job_id=jid,
                                                  wait_seconds=10.0))
    ok("second poll -> done + 5 paths + location",
       jr.get("status") == "done" and jr.get("flow") == "transcribe"
       and all(jr.get(k) for k in ("analysis", "tab", "lyrics", "midi",
                                   "audio"))
       and jr.get("location") == "gpu_host", str(jr))

    print("== fetch: transcribe artifacts ==")
    dest = tempfile.mkdtemp(prefix="mock_fetch_")
    local = server.PIPELINE.fetch(jr["tab"], dest)
    ok("media_fetch tab.md", os.path.isfile(local)
       and open(local, "rb").read() == b"# Mock Song - guitar tab\n")

    print(f"\nALL {passed} CHECKS PASSED (mock pipeline — live pipeline untouched)")
    httpd.shutdown()
    shutil.rmtree(state.root, ignore_errors=True)
    shutil.rmtree(staging, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())