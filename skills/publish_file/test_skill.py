#!/usr/bin/env python3
"""Unit tests for the publish_file skill — NO live services, no network.

Covers:
  - subdirectory enum regression (proposal publish-file-subdirectory-enum-test,
    2026-11-13): SUBDIRS is exactly (ai, images, audio, video, tabs); the
    invalid 'files' is rejected with a clear error; 'tabs' is accepted;
    every valid subdirectory is accepted; invalid ones are rejected;
    skill.yml's documented enum matches the code enum (the 2026-11-06
    drift — commit bd2d2f32d502 — listed 'files' in the docs while the
    code rejected it)
  - idempotent republish (proposal publish-file-dedup, 2026-11-13): the
    2026-11-08 job ledger showed same-file re-publishes failing with
    "destination already exists" (10 failed duplicate jobs). Now:
    identical content → no-op SUCCESS (report.duplicate=true, no copy);
    different content without overwrite → error naming the sha256
    mismatch + the overwrite hint; overwrite=true always replaces
    (the force flag — a changed render is never silently suppressed)

Run with plain python3 (no pytest, no fastapi, no yaml):
    python3 skills/publish_file/test_skill.py
"""
from __future__ import annotations

import hashlib
import importlib.util
import os
import re
import sys
import tempfile
import types
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


def load_skill(tmp: Path) -> types.ModuleType:
    """Load the skill module with a temp drop zone + approved source root."""
    os.environ["PUBLISH_FILE_ROOT"] = str(tmp / "public")
    os.environ["PUBLISH_FILE_PUBLIC_BASE"] = "https://example.test/files"
    spec = importlib.util.spec_from_file_location("skill_publish_file_test", SKILL_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    # Approved source root → the temp media dir (resolved: the skill
    # compares against root.resolve()).
    mod.SOURCE_ROOTS = [(tmp / "media").resolve()]
    return mod


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_source(tmp: Path, name: str, data: bytes) -> Path:
    p = tmp / "media" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


def yml_enum() -> list[str]:
    """Parse the inline `enum: [...]` line from skill.yml (no yaml dep)."""
    text = Path(YML_PATH).read_text()
    m = re.search(r"^\s*enum:\s*\[([^\]]*)\]", text, re.MULTILINE)
    if not m:
        raise AssertionError("no inline `enum: [...]` line found in skill.yml")
    return [s.strip() for s in m.group(1).split(",") if s.strip()]


# ---------------------------------------------------------------------------
# Proposal 1 — subdirectory enum regression
# ---------------------------------------------------------------------------


def test_subdirectory_enum():
    print("test_subdirectory_enum")
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        mod = load_skill(tmp)
        check(
            "SUBDIRS is exactly (ai, images, audio, video, tabs)",
            tuple(mod.SUBDIRS) == ("ai", "images", "audio", "video", "tabs"),
            str(mod.SUBDIRS),
        )
        check("'files' is NOT a valid subdirectory", "files" not in mod.SUBDIRS)
        check("'tabs' IS a valid subdirectory", "tabs" in mod.SUBDIRS)
        # 'files' is rejected with the specific guard (not just the generic
        # allowlist error) — the 2026-09-16 kaelen /files/files/... incident.
        try:
            mod._validate_destination("files", "x.txt")
            check("'files' rejected", False, "no error raised")
        except mod.PublishError as exc:
            check("'files' rejected", True)
            check(
                "'files' error explains why (no /files/files/...)",
                "files" in str(exc) and "files/files" in str(exc),
                str(exc)[:100],
            )
        # Every valid subdirectory is accepted.
        for s in mod.SUBDIRS:
            try:
                dest = mod._validate_destination(s, "ok.txt")
                check(f"subdirectory '{s}' accepted", dest.name == "ok.txt")
            except mod.PublishError as exc:
                check(f"subdirectory '{s}' accepted", False, str(exc))
        # An invalid (non-'files') subdirectory is rejected.
        try:
            mod._validate_destination("bogus", "x.txt")
            check("invalid subdirectory rejected", False, "no error raised")
        except mod.PublishError as exc:
            check("invalid subdirectory rejected", True)
            check(
                "invalid error lists the valid set",
                all(s in str(exc) for s in mod.SUBDIRS),
                str(exc)[:100],
            )
        # Docs match code: skill.yml's enum == SUBDIRS (the 2026-11-06 drift
        # regression — bd2d2f32d502).
        enum = yml_enum()
        check(
            "skill.yml enum matches SUBDIRS",
            enum == list(mod.SUBDIRS),
            f"yml={enum} code={list(mod.SUBDIRS)}",
        )


# ---------------------------------------------------------------------------
# Proposal 3 — idempotent republish (content-hash dedup)
# ---------------------------------------------------------------------------


def test_publish_new():
    print("test_publish_new")
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        mod = load_skill(tmp)
        src = write_source(tmp, "a.txt", b"hello publish")
        job = FakeJob()
        res = mod.run(
            {"source_path": str(src), "subdirectory": "ai"}, job
        )
        check("no error", "error" not in res, str(res.get("error")))
        check("summary says published", "published" in res.get("summary", ""))
        check("not flagged duplicate", res.get("report", {}).get("duplicate") is not True)
        dest = Path(res["artifact_path"])
        check("destination file exists", dest.is_file())
        check("content copied", dest.read_bytes() == b"hello publish")
        rep = res["report"]
        check(
            "report sha256 correct",
            rep["sha256"] == _sha256(b"hello publish"),
            rep["sha256"][:12],
        )
        check("report size correct", rep["size_bytes"] == len(b"hello publish"))
        check("report url uses subdirectory", "/files/ai/a.txt" in rep["url"])


def test_duplicate_identical_content_is_noop_success():
    print("test_duplicate_identical_content_is_noop_success")
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        mod = load_skill(tmp)
        src = write_source(tmp, "b.txt", b"same content twice")
        job1 = FakeJob()
        res1 = mod.run({"source_path": str(src), "subdirectory": "audio"}, job1)
        check("first publish ok", "error" not in res1, str(res1.get("error")))
        dest = Path(res1["artifact_path"])
        mtime_before = dest.stat().st_mtime_ns
        # Second publish, same content, no overwrite → no-op success.
        job2 = FakeJob()
        res2 = mod.run({"source_path": str(src), "subdirectory": "audio"}, job2)
        check("duplicate is a SUCCESS (no error)", "error" not in res2, str(res2))
        check("report.duplicate=true", res2.get("report", {}).get("duplicate") is True)
        check(
            "summary says already published / no-op",
            "already published" in res2.get("summary", "").lower()
            and "no-op" in res2.get("summary", "").lower(),
            res2.get("summary", ""),
        )
        check(
            "no re-copy (destination mtime unchanged)",
            dest.stat().st_mtime_ns == mtime_before,
        )
        check(
            "report sha256 matches the published file",
            res2["report"]["sha256"] == _sha256(b"same content twice"),
        )
        check(
            "job log records the dedup",
            any("duplicate" in line for line in job2.logs),
            str(job2.logs)[:120],
        )


def test_different_content_fails_without_overwrite():
    print("test_different_content_fails_without_overwrite")
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        mod = load_skill(tmp)
        src = write_source(tmp, "c.txt", b"v1 content")
        job1 = FakeJob()
        res1 = mod.run({"source_path": str(src), "subdirectory": "tabs"}, job1)
        check("first publish ok", "error" not in res1, str(res1.get("error")))
        # Source changes (new render, same filename) → republish must FAIL
        # (never silently return the old content) unless overwrite=true.
        src.write_bytes(b"v2 content - different")
        job2 = FakeJob()
        res2 = mod.run({"source_path": str(src), "subdirectory": "tabs"}, job2)
        check("changed content fails", "error" in res2, str(res2)[:120])
        check(
            "error names the mismatch + overwrite hint",
            "different content" in res2["error"] and "overwrite=true" in res2["error"],
            res2["error"][:120],
        )
        dest = Path(res1["artifact_path"])
        check("old content preserved", dest.read_bytes() == b"v1 content")


def test_overwrite_is_the_force_flag():
    print("test_overwrite_is_the_force_flag")
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        mod = load_skill(tmp)
        src = write_source(tmp, "d.txt", b"original")
        job1 = FakeJob()
        res1 = mod.run({"source_path": str(src), "subdirectory": "video"}, job1)
        check("first publish ok", "error" not in res1, str(res1.get("error")))
        # overwrite=true with IDENTICAL content still replaces (bypasses the
        # dedup no-op) — the force flag must always win.
        job2 = FakeJob()
        res2 = mod.run(
            {"source_path": str(src), "subdirectory": "video", "overwrite": True},
            job2,
        )
        check("overwrite identical content succeeds", "error" not in res2, str(res2))
        check(
            "overwrite is not reported as a duplicate no-op",
            res2.get("report", {}).get("duplicate") is not True,
            res2.get("summary", ""),
        )
        # overwrite=true with CHANGED content replaces the file.
        src.write_bytes(b"replaced content")
        job3 = FakeJob()
        res3 = mod.run(
            {"source_path": str(src), "subdirectory": "video", "overwrite": True},
            job3,
        )
        check("overwrite changed content succeeds", "error" not in res3, str(res3))
        dest = Path(res1["artifact_path"])
        check("file actually replaced", dest.read_bytes() == b"replaced content")


def test_same_source_different_destination_is_not_duplicate():
    print("test_same_source_different_destination_is_not_duplicate")
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        mod = load_skill(tmp)
        src = write_source(tmp, "e.txt", b"one file, two homes")
        job1 = FakeJob()
        res1 = mod.run(
            {"source_path": str(src), "subdirectory": "ai", "destination_name": "one.txt"},
            job1,
        )
        job2 = FakeJob()
        res2 = mod.run(
            {"source_path": str(src), "subdirectory": "images", "destination_name": "two.txt"},
            job2,
        )
        check("first publish ok", "error" not in res1, str(res1.get("error")))
        check("second (different dest) publishes normally", "error" not in res2, str(res2))
        check(
            "second is not a duplicate no-op",
            res2.get("report", {}).get("duplicate") is not True,
        )
        check("two distinct destinations", res1["artifact_path"] != res2["artifact_path"])


def main():
    tests = [
        test_subdirectory_enum,
        test_publish_new,
        test_duplicate_identical_content_is_noop_success,
        test_different_content_fails_without_overwrite,
        test_overwrite_is_the_force_flag,
        test_same_source_different_destination_is_not_duplicate,
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