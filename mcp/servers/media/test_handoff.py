#!/usr/bin/env python3
"""Smoke test for the 2026-11-04 thor handoff (T1/T2/T4) on mcp_media.

Runs against a LOCAL MOCK pipeline (stdlib http.server on 127.0.0.1) that
implements the handoff contract: durable GET /jobs (status/client/user/flow/
since/limit filters), GET /jobs/{id} with the 404 recovery hint, POST /image,
POST /storyboard, GET /files/{rel}. **Nothing here touches the live pipeline
(Matrix :8189)** -- safe to run while Matrix is busy.

Covers:
  T1  SUBMIT / DONE container-log lines (job_id + tag + path)
  T2  media_list_jobs tool + client-tag pass-through on job tools
  T4  fetch() basename-collision suffixing (never overwrite) + FETCH log

Run:  python3 test_handoff.py        (plain asserts, no pytest needed)
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
import tempfile
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
JOB_PREFIX = "/home/chuck/data/comfyui/run/media_jobs/"


# ---------------------------------------------------------------------------
# mcp package stub (host python has no `mcp` installed; the container does)
# ---------------------------------------------------------------------------

def _install_mcp_stub() -> str:
    stub = Path(tempfile.mkdtemp(prefix="mcpstub_"))
    (stub / "mcp").mkdir()
    (stub / "mcp" / "server").mkdir()
    (stub / "mcp" / "__init__.py").write_text("")
    (stub / "mcp" / "server" / "__init__.py").write_text(
        "from mcp.server.fastmcp import FastMCP, Context\n")
    (stub / "mcp" / "server" / "fastmcp.py").write_text(
        "class Context:\n"
        "    def __init__(self, request=None):\n"
        "        self.request = request\n\n"
        "class FunctionTool:\n"
        "    def __init__(self, fn, name=None, description=None):\n"
        "        self.fn = fn\n"
        "        self.name = name or fn.__name__\n"
        "        self.description = description\n\n"
        "class FastMCP:\n"
        "    def __init__(self, name=None, instructions=None, **kw):\n"
        "        self.name = name\n"
        "        self.instructions = instructions\n"
        "        self.tools = {}\n\n"
        "    def tool(self, name=None, description=None, **kw):\n"
        "        def deco(fn):\n"
        "            t = FunctionTool(fn, name, description)\n"
        "            self.tools[t.name] = t\n"
        "            return t\n"
        "        return deco\n\n"
        "    def run(self, *a, **kw):\n"
        "        raise NotImplementedError\n")
    return str(stub)


# ---------------------------------------------------------------------------
# Mock pipeline (durable /jobs ledger + live jobs)
# ---------------------------------------------------------------------------

class MockState:
    def __init__(self, delay_polls: int = 3):
        self.jobs: dict[str, dict] = {}      # live jobs
        self.ledger: list[dict] = []         # durable finished jobs
        self.files: dict[str, bytes] = {}    # media_jobs rel -> bytes
        self.next_job = 0
        self.delay_polls = delay_polls
        self.recorded: list[dict] = []       # submit payloads (client/user)

    def new_job(self, flow: str, payload: dict) -> str:
        self.next_job += 1
        jid = f"mock-{self.next_job:03d}"
        self.jobs[jid] = {"job_id": jid, "flow": flow, "status": "running",
                          "client": payload.get("client"),
                          "user": payload.get("user"),
                          "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
                          "done": None, "error": None, "output": None,
                          "outputs": None,
                          "payload": payload, "polls": 0}
        return jid

    def poll_job(self, jid: str) -> dict:
        j = self.jobs[jid]
        j["polls"] += 1
        if j["status"] == "running" and j["polls"] >= self.delay_polls:
            if j["flow"] == "image":
                rel = f"media_jobs/{jid}/out.png"
                self.files[rel] = b"PNG-mock"
                j["output"] = {"image": JOB_PREFIX + rel}
            else:  # storyboard
                rel = f"media_jobs/{jid}/storyboard.json"
                self.files[rel] = json.dumps(
                    {"shots": [{"id": 1, "visual": "v", "vo": "o"}]}).encode()
                j["output"] = {"storyboard": JOB_PREFIX + rel}
            j["status"] = "done"
            j["done"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            self.ledger.insert(
                0, {k: j[k] for k in ("job_id", "flow", "status", "client",
                                      "user", "created", "done",
                                      "error", "output", "outputs")})
        return {k: j[k] for k in ("job_id", "flow", "status", "client",
                                  "user", "created", "done",
                                  "error", "output", "outputs")}

    def list_jobs(self, status=None, client=None, user=None, flow=None,
                  since=None, limit=50) -> list[dict]:
        want = set(s for s in str(status).split(",") if s) if status else set()
        seen = set()
        out = []
        for j in list(self.jobs.values()) + self.ledger:
            if j["job_id"] in seen:
                continue
            seen.add(j["job_id"])
            if want and j["status"] not in want:
                continue
            if client and j.get("client") != client:
                continue
            if user and j.get("user") != user:
                continue
            if flow and j.get("flow") != flow:
                continue
            out.append(j)
        out.sort(key=lambda j: j.get("created") or "", reverse=True)
        return out[:max(1, min(int(limit), 200))]


class _Handler(BaseHTTPRequestHandler):
    state: MockState

    def log_message(self, *a):
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
        path = urllib.parse.urlparse(self.path)
        if path.path == "/health":
            return self._json(200, {"ok": True, "gpu_locked": False,
                                    "jobs": 0, "max_concurrent": 1,
                                    "max_queue_depth": 5})
        if path.path == "/jobs":
            q = urllib.parse.parse_qs(path.query)
            jobs = self.state.list_jobs(
                status=q.get("status", [None])[0],
                client=q.get("client", [None])[0],
                user=q.get("user", [None])[0],
                flow=q.get("flow", [None])[0],
                since=q.get("since", [None])[0],
                limit=int(q.get("limit", ["50"])[0]))
            return self._json(200, {"count": len(jobs), "jobs": jobs})
        m = re.match(r"^/jobs/([^/]+)$", path.path)
        if m:
            jid = urllib.parse.unquote(m.group(1))
            if jid in self.state.jobs:
                return self._json(200, self.state.poll_job(jid))
            for l in self.state.ledger:
                if l["job_id"] == jid:
                    return self._json(200, l)
            return self._json(404, {
                "error": f"unknown job '{jid}' (it may have expired or the "
                         "pipeline restarted)",
                "hint": "GET /jobs?status=...&client=... lists the durable "
                        "job ledger"})
        m = re.match(r"^/files/(.+)$", path.path)
        if m:
            rel = urllib.parse.unquote(m.group(1))
            data = self.state.files.get(rel)
            if data is None:
                return self._json(404, {"error": "no such file"})
            return self._send(200, data, "application/octet-stream")
        return self._json(404, {"error": f"unhandled GET {self.path}"})

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        if self.path in ("/images", "/storyboard"):
            payload = json.loads(body)
            self.state.recorded.append({"endpoint": self.path, **payload})
            jid = self.state.new_job(
                "image" if self.path == "/images" else "storyboard", payload)
            return self._json(200, {"job_id": jid})
        return self._json(404, {"error": f"unhandled POST {self.path}"})


def _start_mock(delay_polls: int = 3):
    state = MockState(delay_polls)
    handler = type("MockHandler", (_Handler,), {"state": state})
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, state, port


# ---------------------------------------------------------------------------
# Log capture
# ---------------------------------------------------------------------------

class LogCapture(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.records: list[str] = []

    def emit(self, record):
        self.records.append(record.getMessage())

    def grep(self, needle: str) -> list[str]:
        return [r for r in self.records if needle in r]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

async def _run(image, job_result, list_jobs, fetch, storyboard,
               state: MockState, cap: LogCapture) -> int:
    passed = 0

    def ok(name: str, cond: bool, detail: str = ""):
        nonlocal passed
        if not cond:
            print(f"FAIL: {name} {detail}")
            raise SystemExit(1)
        passed += 1
        print(f"  ok: {name}")

    print("== T2: client tag pass-through + T1: SUBMIT log ==")
    r = await image(prompt="a red fox", non_blocking=True,
                    client="proj/shot1")
    jid = r.get("job_id")
    ok("image submit returns job_id", bool(jid), str(r))
    rec = state.recorded[-1]
    ok("client tag sent to pipeline", rec.get("client") == "proj/shot1",
       str(rec.get("client")))
    ok("user sent to pipeline", rec.get("user") == "testuser",
       str(rec.get("user")))
    ok("SUBMIT log line",
       len(cap.grep(f"SUBMIT kind=media_generate_image tag=proj/shot1 "
                    f"job_id={jid}")) == 1, str(cap.records))

    print("== T2: default client tag (MEDIA_CLIENT) when client omitted ==")
    r = await storyboard("a fox commercial", non_blocking=True)
    jid_sb = r.get("job_id")
    ok("storyboard submit", bool(jid_sb), str(r))
    ok("default tag SUBMIT log",
       len(cap.grep(f"SUBMIT kind=media_storyboard tag=pytest "
                    f"job_id={jid_sb}")) == 1, str(cap.records))

    print("== T1: DONE log on terminal result ==")
    r = await job_result(jid, wait_seconds=15)
    ok("job done", r.get("status") == "done", str(r))
    p = r.get("path", "")
    ok("path returned", p.startswith(JOB_PREFIX), str(r))
    ok("DONE log line",
       len(cap.grep(f"DONE job_id={jid} status=done path={p}")) == 1,
       str(cap.records))

    print("== T1: storyboard terminal result (DONE log #2) ==")
    r = await job_result(jid_sb, wait_seconds=15)
    ok("storyboard done", r.get("status") == "done", str(r))
    ok("storyboard shots finalized",
       isinstance(r.get("shots"), list) and len(r["shots"]) == 1, str(r))

    print("== T2: 404 recovery hint mentions media_list_jobs ==")
    r = await job_result("mock-999", wait_seconds=2)
    ok("unknown job -> error", "error" in r, str(r))
    ok("error mentions media_list_jobs",
       "media_list_jobs" in str(r.get("error")), str(r))

    print("== T2: media_list_jobs tool ==")
    r = await list_jobs(status="done")
    ok("list_jobs shape", isinstance(r, dict) and "count" in r
       and "jobs" in r, str(r))
    ids = {j["job_id"] for j in r["jobs"]}
    ok("done jobs listed", jid in ids and jid_sb in ids, str(ids))
    r = await list_jobs(status="done", client="proj/shot1")
    ok("client filter", r["count"] == 1
       and r["jobs"][0]["job_id"] == jid, str(r))
    r = await list_jobs(status="done", user="testuser")
    ok("user filter", r["count"] == 2, str(r))
    r = await list_jobs(status="done", flow="image")
    ok("flow filter", r["count"] == 1
       and r["jobs"][0]["flow"] == "image", str(r))
    r = await list_jobs(limit=1)
    ok("limit", r["count"] <= 1, str(r))

    print("== T4: fetch collision suffixing (never overwrite) ==")
    host_path = p  # .../media_jobs/mock-001/out.png
    r1 = await fetch(host_path)
    lp1 = r1.get("local_path", "")
    ok("fetch 1", os.path.isfile(lp1)
       and os.path.basename(lp1) == "out.png", str(r1))
    ok("FETCH log 1",
       len(cap.grep(f"FETCH host_path={host_path} local_path={lp1}")) == 1,
       str(cap.records))
    r2 = await fetch(host_path)
    lp2 = r2.get("local_path", "")
    ok("fetch 2 renamed", r2.get("renamed") is True
       and os.path.basename(lp2) == "out_2.png", str(r2))
    ok("fetch 2 note", "collision" in str(r2.get("note", "")), str(r2))
    r3 = await fetch(host_path)
    ok("fetch 3 suffix increments",
       os.path.basename(r3.get("local_path", "")) == "out_3.png", str(r3))
    ok("original untouched", Path(lp1).read_bytes() == b"PNG-mock")
    ok("copy 2 content", Path(lp2).read_bytes() == b"PNG-mock")

    print(f"\nALL {passed} HANDOFF SMOKE TESTS PASSED")
    return passed


def main() -> int:
    stub_dir = _install_mcp_stub()
    sys.path.insert(0, stub_dir)
    sys.path.insert(0, HERE)

    httpd, state, port = _start_mock(delay_polls=3)
    os.environ["MEDIA_PIPELINE_URL"] = f"http://127.0.0.1:{port}"
    os.environ["MEDIA_USER"] = "testuser"
    os.environ["MEDIA_CLIENT"] = "pytest"
    os.environ["LITELLM_PROXY_URL"] = "http://127.0.0.1:9"  # never called
    os.environ["MEDIA_STAGING_DIR"] = tempfile.mkdtemp(prefix="handoff_stage_")
    os.environ["MEDIA_PIPELINE_FETCH_DIR"] = \
        tempfile.mkdtemp(prefix="handoff_fetch_")

    import server
    server.PIPELINE.poll = 0.05  # fast polling for tests

    cap = LogCapture()
    server.logger.addHandler(cap)
    server.logger.setLevel(logging.DEBUG)

    try:
        n = asyncio.run(_run(
            server.media_generate_image.fn,
            server.media_job_result.fn,
            server.media_list_jobs.fn,
            server.media_fetch.fn,
            server.media_storyboard.fn,
            state, cap))
    finally:
        httpd.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
