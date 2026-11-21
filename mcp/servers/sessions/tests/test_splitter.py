#!/usr/bin/env python3
"""Unit tests for splitter.py (mcp_sessions Phase 1).

Pure stdlib — run directly:  python3 tests/test_splitter.py
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..")))

from splitter import (  # noqa: E402
    MAX_TOTAL_BYTES,
    PART_MAX_BYTES,
    PART_TARGET_BYTES,
    SplitError,
    split_transcript,
    validate_session_id,
)

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


def _raises(fn) -> bool:
    try:
        fn()
        return False
    except SplitError:
        return True


print("== validate_session_id ==")
check("valid simple id", validate_session_id("2026-11-06T13-30-04-455Z_01a1b10d"))
check("valid with dots", validate_session_id("sess.part1"))
check("rejects empty", not validate_session_id(""))
check("rejects leading dot", not validate_session_id(".hidden"))
check("rejects slash", not validate_session_id("../evil"))
check("rejects 129 chars", not validate_session_id("a" * 129))
check("accepts 128 chars", validate_session_id("a" * 128))

print("== single part ==")
t1 = '{"a":1}\n{"b":2}\n'
parts = split_transcript(t1, "sess-1")
check("one part", len(parts) == 1)
check("bare session_id (no suffix)", parts[0]["session_id"] == "sess-1")
check("transcript verbatim", parts[0]["transcript"] == t1)
check("line range (1, 2)", parts[0]["lines"] == (1, 2))

print("== multi-part split ==")
# ~4 MiB of lines: 4000 lines x ~1 KB
line = '{"role":"user","content":"' + "x" * 1000 + '"}\n'
big = line * 4000
parts = split_transcript(big, "sess-big")
check("3 parts (1.5 MiB target)", len(parts) == 3, f"got {len(parts)}")
check("part ids are .part1/.part2/.part3",
      [p["session_id"] for p in parts] ==
      ["sess-big.part1", "sess-big.part2", "sess-big.part3"])
check("no part exceeds 2 MiB",
      all(len(p["transcript"].encode("utf-8")) <= PART_MAX_BYTES for p in parts))
check("line ranges contiguous from 1 to 4000",
      parts[0]["lines"][0] == 1
      and parts[-1]["lines"][1] == 4000
      and all(parts[i]["lines"][1] + 1 == parts[i + 1]["lines"][0]
              for i in range(len(parts) - 1)),
      str([p["lines"] for p in parts]))
check("concatenation is lossless",
      "".join(p["transcript"] for p in parts) == big)
check("total lines preserved",
      sum(e - s + 1 for s, e in (p["lines"] for p in parts)) == 4000)

print("== caps and errors ==")
check("empty transcript -> SplitError",
      _raises(lambda: split_transcript("", "s")))
check("whitespace transcript -> SplitError",
      _raises(lambda: split_transcript("   \n  ", "s")))
check("bad session_id -> SplitError",
      _raises(lambda: split_transcript("x", "../evil")))
check("20 MiB + 1 -> SplitError",
      _raises(lambda: split_transcript("a" * (MAX_TOTAL_BYTES + 1), "s")))
check("single 20 MiB line -> SplitError (line > part cap)",
      _raises(lambda: split_transcript("a" * MAX_TOTAL_BYTES, "s")))
check("single line > 2 MiB -> SplitError (unsplitable)",
      _raises(lambda: split_transcript("a" * (PART_MAX_BYTES + 1), "s")))
check("base id too long to split -> SplitError",
      _raises(lambda: split_transcript(
          "a\n" * 3_000_000, "b" * 115)))  # 115 + ".partNNN" > 128
check("base id 110 chars splits fine",
      not _raises(lambda: split_transcript(
          "a\n" * 3_000_000, "b" * 110)))


print()
print(f"{'PASS' if FAIL == 0 else 'FAIL'}: {PASS} passed, {FAIL} failed")
if FAILURES:
    print("Failed checks:")
    for name in FAILURES:
        print(f"  - {name}")
    sys.exit(1)
