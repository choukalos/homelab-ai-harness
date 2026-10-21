#!/usr/bin/env python3
"""
memory_review skill — unit tests for the pure functions (no live services).

Covers:
  - _in_window: fresh / stale / undated / updated_at-refresh / naive-UTC
  - render_digest: sections, per-fact ID + provenance, importance flag,
    written_by, correction footer, empty-window note

Run: python3 skills/memory_review/test_skill.py
"""

import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import skill  # noqa: E402

PASS = 0
FAIL = 0
FAILURES = []


def check(name, cond, detail=""):
    global PASS, FAIL
    print(f"  {'PASS' if cond else 'FAIL'}: {name}"
          + (f" — {detail}" if detail else ""))
    if cond:
        PASS += 1
    else:
        FAIL += 1
        FAILURES.append(name)


def main():
    now = datetime(2026, 10, 21, 18, 0, tzinfo=timezone.utc)
    fresh = (now - timedelta(hours=2)).isoformat()
    stale = (now - timedelta(days=30)).isoformat()

    # ── _in_window ────────────────────────────────────────────────
    check("fresh fact in window",
          skill._in_window({"created_at": fresh}, 7, now))
    check("stale fact out of window",
          not skill._in_window({"created_at": stale}, 7, now))
    check("undated fact kept", skill._in_window({}, 7, now))
    check("updated_at refreshes window",
          skill._in_window({"created_at": stale, "updated_at": fresh}, 7, now))
    check("naive timestamp assumed UTC",
          skill._in_window({"created_at": fresh[:-6]}, 7, now))

    # ── render_digest ─────────────────────────────────────────────
    hits = [
        {"id": "11111111-aaaa-bbbb-cccc", "text": "private fact",
         "source": "private", "created_at": fresh,
         "metadata": {"source": "chat"}},
        {"id": "22222222-dddd-eeee-ffff", "text": "household fact",
         "source": "household", "created_at": fresh,
         "metadata": {"source": "pi_chat", "written_by": "chuck",
                      "importance": "high"}},
    ]
    md = skill.render_digest("chuck", hits, 7, now)
    check("header has user + window", "# Memory Review — chuck" in md)
    check("private section", "## Private (1)" in md)
    check("household section", "## Household (family-shared) (1)" in md)
    check("fact id shown", "id: 11111111" in md)
    check("provenance shown", "[2026-10-21 · chat]" in md)
    check("importance flag", "importance=high" in md)
    check("written_by shown", "written by chuck" in md)
    check("correction footer", "How to correct or delete" in md)
    empty_md = skill.render_digest("chuck", [], 7, now)
    check("empty window note", "Nothing new or updated" in empty_md)

    print()
    if FAILURES:
        print(f"RESULT: FAIL ({FAIL} failed: {FAILURES})")
        sys.exit(1)
    print(f"RESULT: ALL PASS ({PASS} checks)")


if __name__ == "__main__":
    main()