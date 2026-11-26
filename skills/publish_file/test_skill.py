#!/usr/bin/env python3
"""Unit tests for the publish_file skill — THIN WRAPPER contract (P12-C).

The publish engine moved to the bridge (mcp/servers/filebridge/
publish_engine.py, served at POST /publish on ai-net); the skill is a
thin wrapper that POSTs and passes the result through verbatim. NO live
services, no network — the HTTP layer is stubbed.

Covers:
  - wrapper POSTs the correct request (URL, method, content-type, body:
    source_path / target=blob / destination_name / subdirectory /
    overwrite)
  - report-shape pass-through (bridge 200 -> identical dict)
  - bridge 400 {"error"} -> {"error": ...} (rejection surfaced verbatim)
  - bridge down (URLError) -> clear error naming the bridge, NO fallback
  - missing source_path / invalid subdirectory -> error WITHOUT any HTTP
    call (fail fast, keep the skill.yml enum)
  - skill.yml's documented enum matches the wrapper's SUBDIRS (the
    2026-11-06 drift regression — commit bd2d2f32d502)
  - the wrapper is THIN: no local copy/hash logic (single engine, no
    duplicate logic — the engine lives in the bridge)

Run with plain python3 (no pytest, no fastapi, no yaml):
    python3 skills/publish_file/test_skill.py
"""
from __future__ import annotations

import importlib.util
import io
import json
import os
import re
import sys
import types
import urllib.error
import urllib.request
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_PATH = os.path.join(HERE, "skill.py")
YML_PATH = os.path.join(HERE, "skill.yml")

PASS = 0
FAIL = 0
FAILURES = []


def check(name: str, cond: bool, detail: str = ""):
    global PASS, FAIL
    print(f"  {'PASS' if cond else 'FAIL'}: {name}" + (f" — {detail}" if detail else ""))
    if cond:
        PASS += 1
    else:
        FAIL += 1
        FAILURES.append(name)


class FakeJob:
    def __init__(self):
        self.logs: list[str] = []

    def add_log(self, msg: str) -> None:
        self.logs.append(msg)


class _FakeResponse:
    """Context manager mimicking urllib's response (readable bytes)."""

    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def load_skill() -> types.ModuleType:
    """Load the wrapper module with a stubbed bridge URL."""
    os.environ["PUBLISH_FILE_BRIDGE_URL"] = "http://bridge.test:8000"
    spec = importlib.util.spec_from_file_location("skill_publish_file_test", SKILL_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def yml_enum() -> list[str]:
    """Parse the inline `enum: [...]` line from skill.yml (no yaml dep)."""
    text = Path(YML_PATH).read_text()
    m = re.search(r"^\s*enum:\s*\[([^\]]*)\]", text, re.MULTILINE)
    if not m:
        raise AssertionError("no inline `enum: [...]` line found in skill.yml")
    return [s.strip() for s in m.group(1).split(",") if s.strip()]


REPORT = {
    "summary": "published a.txt (13.0 B) → https://choukalos.com/files/ai/a.txt",
    "artifact_path": "/home/chuck/data/media/public/ai/a.txt",
    "report": {
        "path": "/home/chuck/data/media/public/ai/a.txt",
        "url": "https://choukalos.com/files/ai/a.txt",
        "size_bytes": 13,
        "sha256": "abc123",
        "destination_name": "a.txt",
        "subdirectory": "ai",
    },
}


class StubHTTP:
    """Stub urllib.request.urlopen; captures the Request, returns a
    canned response or raises a canned error."""

    def __init__(self):
        self.requests: list[urllib.request.Request] = []
        self.response: bytes | None = None
        self.error: Exception | None = None

    def urlopen(self, req, timeout=None):
        self.requests.append(req)
        if self.error is not None:
            raise self.error
        if self.response is None:
            raise AssertionError("stub urlopen called with no canned response")
        return _FakeResponse(self.response)

    def install(self, mod):
        self._orig = mod.urllib.request.urlopen
        mod.urllib.request.urlopen = self.urlopen

    def uninstall(self, mod):
        mod.urllib.request.urlopen = self._orig


def test_posts_correct_request():
    print("test_posts_correct_request")
    mod = load_skill()
    stub = StubHTTP()
    stub.response = json.dumps(REPORT).encode()
    stub.install(mod)
    try:
        res = mod.run(
            {"source_path": "/home/chuck/data/media/x/a.txt",
             "destination_name": "a.txt", "subdirectory": "images",
             "overwrite": True},
            FakeJob())
    finally:
        stub.uninstall(mod)
    check("no error", "error" not in res, str(res.get("error")))
    check("exactly one HTTP call", len(stub.requests) == 1,
          str(len(stub.requests)))
    req = stub.requests[0]
    check("POSTs the bridge /publish URL",
          req.full_url == "http://bridge.test:8000/publish", req.full_url)
    check("method is POST", req.get_method() == "POST")
    check("content-type is JSON",
          req.get_header("Content-type") == "application/json",
          str(req.get_header("Content-type")))
    body = json.loads(req.data.decode())
    check("body has source_path",
          body.get("source_path") == "/home/chuck/data/media/x/a.txt")
    check("body target is blog (skill contract)", body.get("target") == "blog")
    check("body passes destination_name", body.get("destination_name") == "a.txt")
    check("body passes subdirectory", body.get("subdirectory") == "images")
    check("body passes overwrite", body.get("overwrite") is True)


def test_report_passthrough():
    print("test_report_passthrough")
    mod = load_skill()
    stub = StubHTTP()
    stub.response = json.dumps(REPORT).encode()
    stub.install(mod)
    try:
        res = mod.run({"source_path": "/home/chuck/data/media/x/a.txt"},
                      FakeJob())
    finally:
        stub.uninstall(mod)
    check("result is the engine report verbatim", res == REPORT,
          json.dumps(res)[:120])
    check("report shape intact (summary/artifact_path/report)",
          set(res) == {"summary", "artifact_path", "report"})
    check("report fields intact",
          set(res["report"]) == {"path", "url", "size_bytes", "sha256",
                                 "destination_name", "subdirectory"})


def test_bridge_rejection_surfaced():
    print("test_bridge_rejection_surfaced")
    mod = load_skill()
    stub = StubHTTP()
    stub.error = urllib.error.HTTPError(
        "http://bridge.test:8000/publish", 400, "Bad Request", {},
        io.BytesIO(json.dumps(
            {"error": "subdirectory 'files' is not a valid subdirectory: it "
                     "would produce a /files/files/... URL. Use one of "
                     "['ai', 'images', 'audio', 'video', 'tabs'] (default: "
                     "'ai')."}
        ).encode()))
    stub.install(mod)
    try:
        res = mod.run({"source_path": "/home/chuck/data/media/x/a.txt"},
                      FakeJob())
    finally:
        stub.uninstall(mod)
    check("error surfaced", "error" in res, str(res)[:120])
    check("bridge error text passed through verbatim",
          "files" in res.get("error", "") and "files/files" in res.get("error", ""))


def test_bridge_down_clear_error_no_fallback():
    print("test_bridge_down_clear_error_no_fallback")
    mod = load_skill()
    stub = StubHTTP()
    stub.error = urllib.error.URLError("Name or service not known")
    stub.install(mod)
    try:
        job = FakeJob()
        res = mod.run({"source_path": "/home/chuck/data/media/x/a.txt"}, job)
    finally:
        stub.uninstall(mod)
    check("error returned", "error" in res, str(res)[:160])
    check("error names the bridge URL",
          "bridge.test:8000/publish" in res.get("error", ""))
    check("error says no fallback by design",
          "no local fallback" in res.get("error", ""))
    check("job log records the failure",
          any("bridge unreachable" in line for line in job.logs),
          str(job.logs)[:120])


def test_missing_source_path_no_http():
    print("test_missing_source_path_no_http")
    mod = load_skill()
    stub = StubHTTP()
    stub.install(mod)
    try:
        res = mod.run({"source_path": "  "}, FakeJob())
    finally:
        stub.uninstall(mod)
    check("error returned", res.get("error") == "source_path is required")
    check("no HTTP call made", len(stub.requests) == 0)


def test_invalid_subdirectory_no_http():
    print("test_invalid_subdirectory_no_http")
    mod = load_skill()
    stub = StubHTTP()
    stub.install(mod)
    try:
        res = mod.run({"source_path": "/home/chuck/data/media/x/a.txt",
                       "subdirectory": "bogus"}, FakeJob())
    finally:
        stub.uninstall(mod)
    check("error returned", "error" in res, str(res)[:120])
    check("error lists the valid set",
          all(s in res.get("error", "") for s in mod.SUBDIRS))
    check("no HTTP call made", len(stub.requests) == 0)


def test_subdirectory_enum():
    print("test_subdirectory_enum")
    mod = load_skill()
    check("SUBDIRS is exactly (ai, images, audio, video, tabs)",
          tuple(mod.SUBDIRS) == ("ai", "images", "audio", "video", "tabs"),
          str(mod.SUBDIRS))
    check("'files' is NOT a valid subdirectory", "files" not in mod.SUBDIRS)
    check("'tabs' IS a valid subdirectory", "tabs" in mod.SUBDIRS)
    # Docs match code: skill.yml's enum == SUBDIRS (the 2026-11-06 drift
    # regression — bd2d2f32d502).
    enum = yml_enum()
    check("skill.yml enum matches SUBDIRS", enum == list(mod.SUBDIRS),
          f"yml={enum} code={list(mod.SUBDIRS)}")


def test_wrapper_is_thin():
    print("test_wrapper_is_thin")
    src = Path(SKILL_PATH).read_text()
    check("no local copy logic (mkstemp/os.replace)",
          "mkstemp" not in src and "os.replace" not in src)
    check("no local hash logic (hashlib)", "hashlib" not in src)
    check("no tempfile usage", "tempfile" not in src)
    check("posts to the bridge (single engine)",
          "/publish" in src and "mcp_filebridge" in src)


def main():
    tests = [
        test_posts_correct_request,
        test_report_passthrough,
        test_bridge_rejection_surfaced,
        test_bridge_down_clear_error_no_fallback,
        test_missing_source_path_no_http,
        test_invalid_subdirectory_no_http,
        test_subdirectory_enum,
        test_wrapper_is_thin,
    ]
    for fn in tests:
        fn()
    print()
    print(f"{'=' * 60}")
    print(f"PASS: {PASS}  FAIL: {FAIL}")
    if FAILURES:
        print("Failures:")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)


if __name__ == "__main__":
    main()
