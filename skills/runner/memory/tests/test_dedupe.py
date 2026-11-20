#!/usr/bin/env python3
"""Write-time dedupe/supersede for harness_reflection lessons — NO live
services, NO mem0 required.

Covers (proposals/2026-11-19-tier3-memory-dedupe-supersede.md):
  - policy: lesson_stem / lesson_date / is_supersede (same stem, newer
    date, explicit supersede wording)
  - config: MEMORY_DEDUPE_THRESHOLD env parsing (default 0.85)
  - interface.learn_from_turn (source="harness_reflection", infer=False):
    (a) deliberate near-duplicate lesson write -> refresh, not a new row
        (existing id returned, updated_at bumped, no second entry)
    (b) genuinely new lesson -> insert
    (c) dedupe-search failure -> degrades to plain insert
    (d) non-reflection source (direct_user) is unaffected

Run with plain python3 (no pytest, no mem0):
    python3 skills/runner/memory/tests/test_dedupe.py
"""
from __future__ import annotations

import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

# Ensure the runner root is importable (memory is a package under it).
HERE = os.path.dirname(os.path.abspath(__file__))
RUNNER_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, RUNNER_ROOT)

from memory import (  # noqa: E402
    policy,
    interface,
    config as memconfig,
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


def test_policy_lesson_helpers():
    print("policy: lesson_stem / lesson_date / is_supersede:")
    check(
        "stem: date prefix stripped",
        policy.lesson_stem(
            "Lesson (2026-11-15): job failed -> check inputs first"
        )
        == "job failed -> check inputs first",
        repr(policy.lesson_stem("Lesson (2026-11-15): job failed -> check inputs first")),
    )
    check("stem: non-lesson unchanged",
          policy.lesson_stem("  user prefers dark roast  ") == "user prefers dark roast")
    check("stem: empty -> empty", policy.lesson_stem("") == "")
    check("date: extracted",
          policy.lesson_date("Lesson (2026-11-15): x -> y") == "2026-11-15")
    check("date: non-lesson -> None",
          policy.lesson_date("user prefers dark roast") is None)

    new1 = "Lesson (2026-11-22): reflection job ran 5x in one window -> tighten the guard"
    old1 = "Lesson (2026-11-15): reflection job ran 5x in one window -> tighten the guard"
    old1_variant = "Lesson (2026-11-15): reflection job ran 4x in one window -> tighten the guard"
    check("supersede: same stem, newer date", policy.is_supersede(new1, old1))
    check("supersede: same stem, same date", policy.is_supersede(old1, old1))
    check("supersede: case/whitespace normalized stems",
          policy.is_supersede(
              "Lesson (2026-11-22):   Reflection Job   ran 5x in one window -> tighten the guard",
              old1,
          ))
    check("supersede: different stem (updated counts) -> False",
          not policy.is_supersede(new1, old1_variant))
    check("supersede: non-lesson texts -> False",
          not policy.is_supersede("user switched to almond milk",
                                  "user prefers oat milk"))
    check("supersede: explicit wording ('superseding earlier counts')",
          policy.is_supersede(
              "User's router issue resolved via DHCP lease reset "
              "(superseding earlier counts)",
              "User's router issue resolved via DHCP lease reset",
          ))
    check("supersede: explicit wording ('replaces the earlier')",
          policy.is_supersede("new state replaces the earlier preference",
                              "old preference"))
    check("supersede: empty args -> False",
          not policy.is_supersede("", old1) and not policy.is_supersede(new1, ""))


def test_config_dedupe_threshold():
    print("config: MEMORY_DEDUPE_THRESHOLD (default 0.85, env-configurable):")
    saved = {k: os.environ.get(k) for k in ("MEMORY_DEDUPE_THRESHOLD",)}
    try:
        os.environ.pop("MEMORY_DEDUPE_THRESHOLD", None)
        check("default 0.85", memconfig.load_config().dedupe_threshold == 0.85)
        os.environ["MEMORY_DEDUPE_THRESHOLD"] = "0.9"
        check("0.9 parsed", memconfig.load_config().dedupe_threshold == 0.9)
        os.environ["MEMORY_DEDUPE_THRESHOLD"] = "0"
        check("0 parsed (disables dedupe)",
              memconfig.load_config().dedupe_threshold == 0.0)
        os.environ["MEMORY_DEDUPE_THRESHOLD"] = "abc"
        check("invalid -> default 0.85",
              memconfig.load_config().dedupe_threshold == 0.85)
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


# ── Fake in-process backend (no mem0, no Qdrant) ─────────────────────
class _FakeScored:
    """Stand-in for a Qdrant ScoredPoint (raw vector_store.search hit)."""

    def __init__(self, id_, score, payload):
        self.id = id_
        self.score = score
        self.payload = payload


class _FakeVectorStore:
    """Raw semantic stage: returns ScoredPoint-like hits (RAW cosine).

    mem0 2.x Memory.search returns a FUSED hybrid score, so the dedupe
    path (and this fake) go through the vector store directly — the fake
    ignores the query vector and matches on the query string, reporting
    the pre-set per-hit score as the raw cosine.
    """

    def __init__(self, mem0):
        self._m = mem0

    def search(self, query, vectors, top_k=5, filters=None):
        if self._m.search_fail:
            raise RuntimeError("qdrant down")
        uid = (filters or {}).get("user_id")
        self._m.search_calls.append((query, uid))
        out = []
        for h in self._m._data.get(uid, []):
            out.append(_FakeScored(
                h["id"], h["score"],
                {"data": h["memory"], "created_at": h.get("created_at"),
                 "updated_at": h.get("updated_at")},
            ))
        return out[:top_k]


class _FakeEmbedder:
    def embed(self, text, memory_action=None):
        return [0.0] * 8  # fake flat vector (content ignored)


class _FakeMem0:
    """In-memory mem0 stand-in: search by user_id, add/update/delete."""

    def __init__(self, data):
        self._data = data  # user_id -> list of point dicts
        self.added = []       # (user_id, metadata, infer)
        self.updated = []     # (memory_id, text)
        self.search_calls = []  # (query, user_id)
        self.search_fail = False
        self.update_fail = False
        self.mem0_search_calls = []  # mem0 Memory.search (FUSED score) —
                                     # the dedupe path must NOT use this
        self.embedding_model = _FakeEmbedder()
        self.vector_store = _FakeVectorStore(self)

    def search(self, query, filters=None, top_k=10):
        if self.search_fail:
            raise RuntimeError("qdrant down")
        uid = (filters or {}).get("user_id")
        self.mem0_search_calls.append((query, uid))
        return [dict(h) for h in self._data.get(uid, [])]

    def add(self, messages, user_id=None, metadata=None, infer=True, prompt=None):
        self.added.append((user_id, dict(metadata or {}), infer, prompt))
        return {"results": [{"id": f"new{len(self.added)}"}]}

    def update(self, memory_id, text):
        if self.update_fail:
            raise RuntimeError("update down")
        self.updated.append((memory_id, text))
        # Emulate mem0: replace text, bump updated_at.
        for pts in self._data.values():
            for p in pts:
                if p["id"] == memory_id:
                    p["memory"] = text
                    p["updated_at"] = datetime.now(timezone.utc).isoformat()


class _FakeClient:
    def __init__(self, data):
        self._mem = _FakeMem0(data)
        self._pool = ThreadPoolExecutor(max_workers=4)

    def _ensure_client(self):
        return self._mem

    def _with_timeout(self, fn, timeout_s=None):
        return fn()

    def reset(self):
        pass


ENV_KEYS = (
    "MEMORY_ENABLED", "MEMORY_SCORE_THRESHOLD", "MEMORY_DEDUPE_THRESHOLD",
    "MEMORY_HOUSEHOLD_ENABLED", "MEMORY_TIMEOUT_MS",
)


def _env_guard():
    return {k: os.environ.get(k) for k in ENV_KEYS}


def _env_restore(saved):
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    interface._reset_singleton()


def test_dedupe_write_path():
    print("interface: write-time dedupe/supersede (harness_reflection):")
    saved = _env_guard()
    now = datetime.now(timezone.utc)
    old_ts = (now - timedelta(days=7)).isoformat()
    old_lesson = "Lesson (2026-11-15): reflection job ran 4x in one window -> tighten the window guard"
    new_lesson = "Lesson (2026-11-22): reflection job ran 5x in one window -> tighten the window guard"
    new_lesson_stem = "reflection job ran 5x in one window -> tighten the window guard"

    try:
        os.environ["MEMORY_ENABLED"] = "true"
        os.environ["MEMORY_SCORE_THRESHOLD"] = "0.5"
        os.environ["MEMORY_DEDUPE_THRESHOLD"] = "0.85"
        os.environ["MEMORY_HOUSEHOLD_ENABLED"] = "false"
        os.environ["MEMORY_TIMEOUT_MS"] = "1500"
        interface._reset_singleton()

        # ── (a) deliberate near-duplicate lesson write -> refresh ──
        fake = _FakeClient({
            "chuck": [
                {"id": "lesson1", "memory": old_lesson, "score": 0.9,
                 "created_at": old_ts, "updated_at": old_ts,
                 "metadata": {"source": "harness_reflection"}},
            ],
        })
        interface._client = fake
        ids = interface.learn_from_turn(
            "chuck",
            [{"role": "user", "content": new_lesson}],
            source="harness_reflection",
            agent_id="harness_reflection",
            infer=False,
        )
        check("(a) existing id returned", ids == ["lesson1"], str(ids))
        check("(a) no insert (no second row)", fake._mem.added == [],
              str(fake._mem.added))
        check("(a) update called with new text",
              fake._mem.updated == [("lesson1", new_lesson)],
              str(fake._mem.updated))
        pt = fake._mem._data["chuck"][0]
        check("(a) text refreshed in place", pt["memory"] == new_lesson)
        check("(a) updated_at bumped",
              pt["updated_at"] > old_ts, pt["updated_at"])
        check("(a) dedupe query = stem WITHOUT date prefix",
              fake._mem.search_calls and fake._mem.search_calls[0][0] == new_lesson_stem,
              str(fake._mem.search_calls))
        check("(a) dedupe searched the write scope",
              fake._mem.search_calls and fake._mem.search_calls[0][1] == "chuck",
              str(fake._mem.search_calls))
        check("(a) raw-cosine path used (mem0 fused search NOT called)",
              fake._mem.mem0_search_calls == [], str(fake._mem.mem0_search_calls))

        # ── (a2) supersede below the strict threshold (same stem /
        # wording) still refreshes, clearing only the relevance floor ──
        fake2 = _FakeClient({
            "chuck": [
                {"id": "lesson2", "memory": old_lesson, "score": 0.7,
                 "created_at": old_ts, "updated_at": old_ts,
                 "metadata": {"source": "harness_reflection"}},
            ],
        })
        interface._client = fake2
        same_stem_new = "Lesson (2026-11-22): " + policy.lesson_stem(old_lesson)
        ids2 = interface.learn_from_turn(
            "chuck",
            [{"role": "user", "content": same_stem_new}],
            source="harness_reflection",
            agent_id="harness_reflection",
            infer=False,
        )
        check("(a2) same-stem supersede below 0.85 -> refresh",
              ids2 == ["lesson2"] and fake2._mem.added == []
              and fake2._mem.updated == [("lesson2", same_stem_new)],
              f"ids={ids2} added={fake2._mem.added} updated={fake2._mem.updated}")

        # ── (b) genuinely new lesson -> insert ─────────────────────
        fake3 = _FakeClient({
            "chuck": [
                # Distinct lesson: above the relevance floor (0.5), below
                # the strict dedupe threshold (0.85), no supersede signal.
                {"id": "other", "memory": "Lesson (2026-11-01): qdrant cold start is slow -> warm up at boot",
                 "score": 0.6, "created_at": old_ts, "updated_at": old_ts,
                 "metadata": {"source": "harness_reflection"}},
                # Unrelated low-score hit: below the floor, never a
                # dedupe candidate.
                {"id": "unrelated", "memory": "chuck likes oat milk", "score": 0.3,
                 "created_at": old_ts, "updated_at": old_ts,
                 "metadata": {"source": "chat"}},
            ],
        })
        interface._client = fake3
        fresh = "Lesson (2026-11-22): morning brief took 40s -> cache the job list"
        ids3 = interface.learn_from_turn(
            "chuck",
            [{"role": "user", "content": fresh}],
            source="harness_reflection",
            agent_id="harness_reflection",
            infer=False,
        )
        check("(b) new lesson inserted", ids3 == ["new1"], str(ids3))
        check("(b) exactly one insert", len(fake3._mem.added) == 1,
              str(fake3._mem.added))
        check("(b) no refresh of the distinct lesson",
              fake3._mem.updated == [], str(fake3._mem.updated))
        uid, meta, infer, _prompt = fake3._mem.added[0]
        check("(b) insert carries provenance",
              uid == "chuck" and meta.get("source") == "harness_reflection"
              and infer is False, str((uid, meta, infer)))

        # ── (c) dedupe-search failure -> degrades to plain insert ──
        fake4 = _FakeClient({
            "chuck": [
                {"id": "lesson1", "memory": old_lesson, "score": 0.9,
                 "created_at": old_ts, "updated_at": old_ts,
                 "metadata": {"source": "harness_reflection"}},
            ],
        })
        fake4._mem.search_fail = True
        interface._client = fake4
        ids4 = interface.learn_from_turn(
            "chuck",
            [{"role": "user", "content": new_lesson}],
            source="harness_reflection",
            agent_id="harness_reflection",
            infer=False,
        )
        check("(c) search failure -> plain insert (non-fatal)",
              ids4 == ["new1"], str(ids4))
        check("(c) insert happened despite search error",
              len(fake4._mem.added) == 1, str(fake4._mem.added))
        check("(c) no update attempted", fake4._mem.updated == [])

        # (c2) refresh failure also degrades to plain insert.
        fake5 = _FakeClient({
            "chuck": [
                {"id": "lesson1", "memory": old_lesson, "score": 0.9,
                 "created_at": old_ts, "updated_at": old_ts,
                 "metadata": {"source": "harness_reflection"}},
            ],
        })
        fake5._mem.update_fail = True
        interface._client = fake5
        ids5 = interface.learn_from_turn(
            "chuck",
            [{"role": "user", "content": new_lesson}],
            source="harness_reflection",
            agent_id="harness_reflection",
            infer=False,
        )
        check("(c2) update failure -> falls back to insert",
              ids5 == ["new1"] and len(fake5._mem.added) == 1,
              f"ids={ids5} added={fake5._mem.added}")

        # ── (d) non-reflection source (direct_user) is unaffected ──
        fake6 = _FakeClient({
            "chuck": [
                {"id": "lesson1", "memory": old_lesson, "score": 0.9,
                 "created_at": old_ts, "updated_at": old_ts,
                 "metadata": {"source": "harness_reflection"}},
            ],
        })
        interface._client = fake6
        ids6 = interface.remember_direct("chuck", "Remember that my birthday is June 4th")
        check("(d) direct_user still inserts", ids6 == ["new1"], str(ids6))
        check("(d) no dedupe search for direct_user",
              fake6._mem.search_calls == [], str(fake6._mem.search_calls))
        check("(d) no refresh for direct_user", fake6._mem.updated == [])
        uid, meta, infer, _prompt = fake6._mem.added[0]
        check("(d) direct_user provenance unchanged",
              meta.get("source") == "direct_user" and meta.get("importance") == "high"
              and infer is False, str((uid, meta, infer)))

        # (d2) chat source also unaffected.
        fake7 = _FakeClient({"chuck": []})
        interface._client = fake7
        ids7 = interface.learn_from_turn(
            "chuck",
            [{"role": "user", "content": new_lesson}],
            source="chat",
        )
        check("(d2) chat source still inserts (no dedupe search)",
              ids7 == ["new1"] and fake7._mem.search_calls == []
              and fake7._mem.updated == [],
              f"ids={ids7} searches={fake7._mem.search_calls}")

        # (e) dedupe disabled (threshold=0) -> plain insert.
        os.environ["MEMORY_DEDUPE_THRESHOLD"] = "0"
        interface._reset_singleton()
        fake8 = _FakeClient({
            "chuck": [
                {"id": "lesson1", "memory": old_lesson, "score": 0.9,
                 "created_at": old_ts, "updated_at": old_ts,
                 "metadata": {"source": "harness_reflection"}},
            ],
        })
        interface._client = fake8
        ids8 = interface.learn_from_turn(
            "chuck",
            [{"role": "user", "content": new_lesson}],
            source="harness_reflection",
            agent_id="harness_reflection",
            infer=False,
        )
        check("(e) threshold=0 disables dedupe (plain insert)",
              ids8 == ["new1"] and fake8._mem.search_calls == [],
              f"ids={ids8} searches={fake8._mem.search_calls}")
        os.environ["MEMORY_DEDUPE_THRESHOLD"] = "0.85"
        interface._reset_singleton()
    finally:
        _env_restore(saved)


def main():
    test_policy_lesson_helpers()
    test_config_dedupe_threshold()
    test_dedupe_write_path()
    print()
    if FAILURES:
        print(f"RESULT: FAIL ({FAIL} failed: {FAILURES})")
        sys.exit(1)
    print(f"RESULT: ALL PASS ({PASS} checks)")


if __name__ == "__main__":
    main()
