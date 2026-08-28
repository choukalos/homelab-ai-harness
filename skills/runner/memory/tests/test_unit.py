#!/usr/bin/env python3
"""Unit tests for the memory module — NO live services, NO mem0 required.

Covers (per memory_todo.md Phase 2 gate):
  - flag-off path (one env switch disables retrieval / writeback / all)
  - policy (secret filter, sanitize, store/forget signals)
  - context rendering (shape + token budget)
  - timeout -> graceful degradation (MemoryTimeout raised, caller degrades)
  - unknown-user guard (no retrieval / writeback)

Run with plain python3 (no pytest, no mem0):
    python3 skills/runner/memory/tests/test_unit.py
"""
from __future__ import annotations

import os
import sys
import threading
import time

# Ensure the runner root is importable (memory is a package under it).
HERE = os.path.dirname(os.path.abspath(__file__))
RUNNER_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, RUNNER_ROOT)

from memory import (  # noqa: E402
    context,
    policy,
    interface,
    config as memconfig,
)
from memory.client import MemoryClient, MemoryTimeout  # noqa: E402

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


def test_policy():
    print("policy:")
    check("secret: sk- key", policy.is_secret_like("key is sk-abcDEF1234567890XYZ"))
    check("secret: AWS", policy.is_secret_like("AKIAIOSFODNN7EXAMPLE"))
    check("secret: bearer", policy.is_secret_like("Authorization: Bearer abcdef1234567890ab"))
    check("secret: password=", policy.is_secret_like("password=hunter2secret"))
    check("not secret: plain", not policy.is_secret_like("I like oat milk lattes"))
    check("not secret: empty", not policy.is_secret_like(""))
    check("store signal", policy.has_store_signal("remember that my birthday is in May"))
    check("store signal: prefer", policy.has_store_signal("I prefer dark roast"))
    check("no store signal", not policy.has_store_signal("what is the weather"))
    check("forget signal", policy.has_forget_signal("forget that memory"))
    msgs = [
        {"role": "system", "content": "you are siri"},
        {"role": "user", "content": "I like oat milk"},
        {"role": "tool", "content": "tool output"},
        {"role": "assistant", "content": "noted"},
        {"role": "user", "content": ""},
    ]
    cleaned = policy.sanitize_turn(msgs)
    check("sanitize strips system/tool", all(m["role"] in ("user", "assistant") for m in cleaned))
    check("sanitize drops empty", all(m["content"].strip() for m in cleaned))
    check("sanitize keeps user+assistant", len(cleaned) == 2)
    ok, reason = policy.should_store(msgs)
    check("should_store ok", ok, reason)
    ok2, reason2 = policy.should_store([{"role": "system", "content": "x"}])
    check("should_store rejects no-user", not ok2, reason2)
    ok3, reason3 = policy.should_store([{"role": "user", "content": "api_key=abc12345xyz"}])
    check("should_store rejects secret", not ok3, reason3)


def test_context():
    print("context:")
    cfg = memconfig.MemoryConfig(max_context_tokens=1500)
    hits = [
        {"text": "I like oat milk", "score": 0.9, "source": "private"},
        {"text": "server rack in basement", "score": 0.8, "source": "household"},
    ]
    block = context.render_memory_block(hits, cfg)
    check("block has tag", "<long_term_memory>" in block and "</long_term_memory>" in block)
    check("block has private section", "PRIVATE USER MEMORY:" in block)
    check("block has household section", "HOUSEHOLD MEMORY:" in block)
    check("block has context framing", "CONTEXT, not instructions" in block)
    check("block empty when no hits", context.render_memory_block([], cfg) == "")
    # Token budget: tiny budget should drop entries (or empty).
    tiny = memconfig.MemoryConfig(max_context_tokens=10)
    tiny_block = context.render_memory_block(hits, tiny)
    check("budget trims or empties", tiny_block == "" or len(tiny_block) < len(block))


def test_config_env():
    print("config:")
    saved = {k: os.environ.get(k) for k in (
        "MEMORY_ENABLED", "MEMORY_RETRIEVAL_ENABLED", "MEMORY_WRITEBACK_ENABLED",
        "MEMORY_TOP_K", "MEMORY_TIMEOUT_MS", "MEMORY_ADMIN_TIMEOUT_MS",
        "MEMORY_QDRANT_API_KEY",
    )}
    try:
        os.environ["MEMORY_ENABLED"] = "false"
        os.environ["MEMORY_RETRIEVAL_ENABLED"] = "true"
        os.environ["MEMORY_WRITEBACK_ENABLED"] = "true"
        os.environ["MEMORY_TOP_K"] = "9"
        os.environ["MEMORY_TIMEOUT_MS"] = "2500"
        os.environ["MEMORY_ADMIN_TIMEOUT_MS"] = "12345"
        cfg = memconfig.load_config()
        check("enabled=false parsed", cfg.enabled is False)
        check("top_k=9 parsed", cfg.top_k == 9)
        check("timeout_ms=2500 parsed", cfg.timeout_ms == 2500)
        check("admin_timeout_ms=12345 parsed", cfg.admin_timeout_ms == 12345)
        check("admin_timeout_s property", cfg.admin_timeout_s == 12.345)
        check("retrieval_allowed off when disabled", cfg.retrieval_allowed is False)
        check("writeback_allowed off when disabled", cfg.writeback_allowed is False)
        os.environ["MEMORY_ENABLED"] = "true"
        os.environ["MEMORY_RETRIEVAL_ENABLED"] = "false"
        cfg2 = memconfig.load_config()
        check("retrieval flag independent", cfg2.retrieval_enabled is False)
        check("writeback still on", cfg2.writeback_allowed is True)
        # Phase 9: scoped Qdrant JWT passthrough (empty default = unauthenticated)
        check("qdrant_api_key empty by default", cfg2.qdrant_api_key == "")
        os.environ["MEMORY_QDRANT_API_KEY"] = "test-jwt-token"
        cfg3 = memconfig.load_config()
        check("qdrant_api_key passthrough", cfg3.qdrant_api_key == "test-jwt-token")
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_flag_off_path():
    print("flag-off path (interface returns safe defaults, no live calls):")
    saved = {k: os.environ.get(k) for k in (
        "MEMORY_ENABLED", "MEMORY_RETRIEVAL_ENABLED", "MEMORY_WRITEBACK_ENABLED",
    )}
    try:
        # Retrieval off.
        os.environ["MEMORY_ENABLED"] = "true"
        os.environ["MEMORY_RETRIEVAL_ENABLED"] = "false"
        os.environ["MEMORY_WRITEBACK_ENABLED"] = "true"
        interface._reset_singleton()
        check("search off -> []", interface.search_memory("chuck", "coffee") == [])
        # Writeback off.
        os.environ["MEMORY_RETRIEVAL_ENABLED"] = "true"
        os.environ["MEMORY_WRITEBACK_ENABLED"] = "false"
        interface._reset_singleton()
        check("learn off -> []", interface.learn_from_turn(
            "chuck", [{"role": "user", "content": "I like oat milk"}]) == [])
        # Master off.
        os.environ["MEMORY_ENABLED"] = "false"
        interface._reset_singleton()
        check("all off: search -> []", interface.search_memory("chuck", "coffee") == [])
        check("all off: learn -> []", interface.learn_from_turn(
            "chuck", [{"role": "user", "content": "I like oat milk"}]) == [])
        check("all off: list -> []", interface.list_memories("chuck") == [])
        check("all off: update -> False", interface.update_memory("id1", "x") is False)
        check("all off: delete -> False", interface.delete_memory("id1") is False)
        check("all off: delete_user -> 0", interface.delete_user_memories("chuck") == 0)
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        interface._reset_singleton()


def test_unknown_user():
    print("unknown-user guard:")
    saved = {k: os.environ.get(k) for k in ("MEMORY_ENABLED",)}
    try:
        os.environ["MEMORY_ENABLED"] = "true"
        interface._reset_singleton()
        check("unknown: search -> []", interface.search_memory("unknown", "coffee") == [])
        check("unknown: learn -> []", interface.learn_from_turn(
            "unknown", [{"role": "user", "content": "I like oat milk"}]) == [])
        check("empty user: search -> []", interface.search_memory("", "coffee") == [])
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        interface._reset_singleton()


def test_singleton_first_call():
    print("singleton first-call (regression: self-deadlock in _get_client):")
    interface._reset_singleton()
    # is_healthy() as the FIRST interface call in process state: _get_client()
    # used to call _get_config() while holding the non-reentrant _lock and
    # deadlock forever. Run in a worker thread so a regression hangs the
    # check (5s join) instead of the whole suite.
    result = {}

    def _call():
        result["ok"] = interface.is_healthy()

    t = threading.Thread(target=_call, daemon=True)
    t0 = time.time()
    t.start()
    t.join(5.0)
    elapsed_ms = (time.time() - t0) * 1000
    check(
        "first is_healthy() returns promptly (no deadlock)",
        not t.is_alive() and "ok" in result,
        f"{elapsed_ms:.0f}ms" if not t.is_alive() else "HANG >5s (deadlock regression)",
    )
    # Second call (cached client) also returns promptly.
    result.clear()
    t2 = threading.Thread(target=_call, daemon=True)
    t2.start()
    t2.join(5.0)
    check("second is_healthy() returns promptly", not t2.is_alive() and "ok" in result)
    interface._reset_singleton()


def test_delete_user_count():
    print("delete_user_memories count semantics (regression: household over-count):")
    # Regression for the 2026-08-26 "memory_test_other mystery": the old
    # implementation counted via the merged list_memories() view (private +
    # household), so a user with 0 private memories reported 1 whenever a
    # household fact existed — even though delete_all only removes the
    # user's own points. The count must reflect only the user's own points.
    saved = {k: os.environ.get(k) for k in ("MEMORY_ENABLED", "MEMORY_TIMEOUT_MS")}

    class _FakeMem0:
        def __init__(self, data):
            self._data = data  # user_id -> list of point dicts
            self.deleted = []

        def get_all(self, filters=None, top_k=20):
            uid = (filters or {}).get("user_id")
            return [dict(p) for p in self._data.get(uid, [])]

        def delete_all(self, user_id=None):
            self.deleted.append(user_id)
            self._data.pop(user_id, None)

    class _FakeClient:
        def __init__(self, data):
            self._mem = _FakeMem0(data)

        def _ensure_client(self):
            return self._mem

        def _with_timeout(self, fn, timeout_s=None):
            return fn()

        def reset(self):
            pass

    try:
        os.environ["MEMORY_ENABLED"] = "true"
        os.environ["MEMORY_TIMEOUT_MS"] = "1500"
        interface._reset_singleton()
        # memory_test_other: 0 private; household: 1 (basement).
        fake = _FakeClient({
            "memory_test_other": [],
            "household": [{"id": "hh1", "memory": "server rack in basement"}],
        })
        interface._client = fake
        n = interface.delete_user_memories("memory_test_other")
        check("count excludes household view", n == 0, f"count={n}")
        check("household point untouched",
              len(fake._mem._data.get("household", [])) == 1)
        check("delete_all called for the user",
              fake._mem.deleted == ["memory_test_other"])
        # The household user's own count is unaffected by the fix.
        n2 = interface.delete_user_memories("household")
        check("household user counts own points", n2 == 1, f"count={n2}")
        check("household point removed", fake._mem.deleted.count("household") == 1)
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        interface._reset_singleton()


def test_score_threshold():
    print("score threshold (relevance gate for injected memories):")
    saved = {k: os.environ.get(k) for k in (
        "MEMORY_ENABLED", "MEMORY_SCORE_THRESHOLD",
    )}

    class _FakeMem0:
        def __init__(self, data):
            self._data = data  # user_id -> list of raw hits

        def search(self, query, filters=None, top_k=10):
            uid = (filters or {}).get("user_id")
            return [dict(h) for h in self._data.get(uid, [])]

    class _FakeClient:
        def __init__(self, data):
            self._mem = _FakeMem0(data)

        def _ensure_client(self):
            return self._mem

        def _with_timeout(self, fn, timeout_s=None):
            return fn()

        def reset(self):
            pass

    try:
        os.environ["MEMORY_ENABLED"] = "true"
        os.environ["MEMORY_SCORE_THRESHOLD"] = "0.5"
        interface._reset_singleton()
        fake = _FakeClient({
            "chuck": [
                {"id": "a", "memory": "oat milk latte", "score": 0.9},
                {"id": "b", "memory": "unrelated fact", "score": 0.3},
            ],
            "household": [
                {"id": "c", "memory": "server rack in basement", "score": 0.55},
            ],
        })
        interface._client = fake
        hits = interface.search_memory("chuck", "coffee")
        ids = [h["id"] for h in hits]
        check("high-score hit kept", "a" in ids, str(ids))
        check("below-threshold hit dropped", "b" not in ids, str(ids))
        check("household hit at/above threshold kept", "c" in ids, str(ids))

        # Threshold 0 disables the gate.
        os.environ["MEMORY_SCORE_THRESHOLD"] = "0"
        interface._reset_singleton()
        interface._client = fake
        hits0 = interface.search_memory("chuck", "coffee")
        check("threshold=0 keeps low-score hits",
              any(h["id"] == "b" for h in hits0))

        # render_context: nothing above threshold -> no block.
        os.environ["MEMORY_SCORE_THRESHOLD"] = "0.99"
        interface._reset_singleton()
        interface._client = fake
        check("render_context empty when all below threshold",
              interface.render_context("chuck", "coffee") == "")

        # Config parsing.
        os.environ["MEMORY_SCORE_THRESHOLD"] = "0.7"
        check("threshold 0.7 parsed", memconfig.load_config().score_threshold == 0.7)
        os.environ["MEMORY_SCORE_THRESHOLD"] = "abc"
        check("invalid threshold -> default 0.5",
              memconfig.load_config().score_threshold == 0.5)
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        interface._reset_singleton()


def test_timeout_degradation():
    print("timeout -> graceful degradation:")
    cfg = memconfig.MemoryConfig(timeout_ms=200)  # 200ms budget
    client = MemoryClient(cfg)

    def slow():
        time.sleep(1.0)  # longer than the budget
        return "done"

    t0 = time.time()
    try:
        client._with_timeout(slow)
        check("timeout raised", False, "no exception raised")
    except MemoryTimeout:
        elapsed = time.time() - t0
        check("timeout raised", True, f"after {elapsed*1000:.0f}ms")
        check("returned promptly (<1s)", elapsed < 0.9, f"{elapsed*1000:.0f}ms")
    # Fast op succeeds.
    check("fast op ok", client._with_timeout(lambda: 42) == 42)


def test_phase5_writeback():
    print("Phase 5 writeback (provenance metadata, remember/forget, extraction instructions):")
    saved = {k: os.environ.get(k) for k in (
        "MEMORY_ENABLED", "MEMORY_EXTRACTION_INSTRUCTIONS",
    )}

    class _FakeMem0:
        def __init__(self, hits):
            self._hits = hits  # user_id -> list of raw search hits
            self.added = []    # (user_id, metadata, infer)
            self.last_text = ""  # last user message content passed to add()
            self.deleted = []  # memory ids

        def add(self, messages, user_id=None, metadata=None, infer=True):
            self.last_text = next(
                (m.get("content") for m in messages if m.get("role") == "user"),
                "",
            )
            self.added.append((user_id, dict(metadata or {}), infer))
            return {"results": [{"id": f"new{len(self.added)}"}]}

        def search(self, query, filters=None, top_k=10):
            uid = (filters or {}).get("user_id")
            q = [w for w in (query or "").lower().split() if w]
            out = []
            for h in self._hits.get(uid, []):
                mem = h["memory"].lower()
                if any(w in mem for w in q):
                    out.append(dict(h))
            return out

        def delete(self, memory_id):
            self.deleted.append(memory_id)

    class _FakeClient:
        def __init__(self, hits):
            self._mem = _FakeMem0(hits)

        def _ensure_client(self):
            return self._mem

        def _with_timeout(self, fn, timeout_s=None):
            return fn()

        def reset(self):
            pass

    try:
        os.environ["MEMORY_ENABLED"] = "true"
        os.environ.pop("MEMORY_EXTRACTION_INSTRUCTIONS", None)
        interface._reset_singleton()
        fake = _FakeClient({
            "chuck": [
                {"id": "m1", "memory": "oat milk flat white", "score": 0.9},
                {"id": "m2", "memory": "unrelated fact", "score": 0.2},
            ],
        })
        interface._client = fake

        # learn_from_turn: provenance metadata on every stored fact.
        interface.learn_from_turn(
            "chuck",
            [{"role": "user", "content": "I switched to oat milk flat whites"}],
            source="chat", agent_id="siri_chat", run_id="run123",
        )
        uid, meta, infer = fake._mem.added[-1]
        check("learn: user routed", uid == "chuck", uid)
        check("learn: infer default", infer is True, str(infer))
        check("learn: source metadata", meta.get("source") == "chat", str(meta))
        check("learn: importance default", meta.get("importance") == "normal", str(meta))
        check("learn: confidence default", meta.get("confidence") == "normal", str(meta))
        check("learn: agent metadata", meta.get("agent") == "siri_chat", str(meta))
        check("learn: turn_id metadata", meta.get("turn_id") == "run123", str(meta))

        # remember_direct: direct_user + high importance/confidence,
        # deterministic (infer=False), imperative prefix stripped.
        ids = interface.remember_direct(
            "chuck", "Remember that my birthday is June 4th", run_id="r9")
        check("remember: stored", len(ids) == 1, str(ids))
        uid, meta, infer = fake._mem.added[-1]
        check("remember: infer=False (no LLM)", infer is False, str(infer))
        check("remember: prefix stripped",
              fake._mem.last_text == "my birthday is June 4th",
              repr(fake._mem.last_text))
        check("remember: source=direct_user", meta.get("source") == "direct_user", str(meta))
        check("remember: importance=high", meta.get("importance") == "high", str(meta))
        check("remember: confidence=high", meta.get("confidence") == "high", str(meta))
        check("remember: turn_id", meta.get("turn_id") == "r9", str(meta))

        # Empty text → no-op.
        check("remember: empty text no-op", interface.remember_direct("chuck", "   ") == [])

        # forget_matching: deletes only the above-threshold hit.
        deleted = interface.forget_matching("chuck", "oat milk coffee")
        check("forget: one hit deleted", len(deleted) == 1, str(deleted))
        check("forget: right id", deleted[0]["id"] == "m1", str(deleted))
        check("forget: text returned", "oat milk" in deleted[0]["text"], str(deleted))
        check("forget: low-score hit kept", "m2" not in fake._mem.deleted,
              str(fake._mem.deleted))

        # forget_matching: no match → [].
        check("forget: no match empty", interface.forget_matching("chuck", "zzz nothing") == [])

        # forget_matching: unknown user → [] (no writeback for unmapped).
        check("forget: unknown user no-op",
              interface.forget_matching("unknown", "oat milk") == [])

        # Extraction instructions: built-in default + env override.
        from memory import policy as _policy
        default = _policy.DEFAULT_EXTRACTION_INSTRUCTIONS
        check("extract: default instructions non-empty", len(default) > 200, str(len(default)))
        check("extract: excludes secrets",
              "secret" in default.lower() and "credential" in default.lower())
        check("extract: excludes prompt-injection",
              "instructions" in default.lower())
        check("extract: supersede rule", "supersed" in default.lower())
        # remember prefix stripping (explicit remember is stored verbatim).
        check("remember prefix: basic",
              _policy.strip_remember_prefix("Remember that my dog is Biscuit")
              == "my dog is Biscuit",
              _policy.strip_remember_prefix("Remember that my dog is Biscuit"))
        check("remember prefix: please + no that",
              _policy.strip_remember_prefix("Please remember my dog is Biscuit")
              == "my dog is Biscuit")
        check("remember prefix: note that",
              _policy.strip_remember_prefix("Note that I work nights")
              == "I work nights")
        check("remember prefix: keep in mind",
              _policy.strip_remember_prefix("Keep in mind that I am vegan")
              == "I am vegan")
        check("remember prefix: plain statement untouched",
              _policy.strip_remember_prefix("My dog is Biscuit") == "My dog is Biscuit")
        check("remember prefix: empty -> empty",
              _policy.strip_remember_prefix("Remember that") == "")
        check("remember prefix: 'Remembering' untouched",
              _policy.strip_remember_prefix("Remembering my dog")
              == "Remembering my dog")
        os.environ["MEMORY_EXTRACTION_INSTRUCTIONS"] = "custom rules here"
        check("extract: env override parsed",
              memconfig.load_config().extraction_instructions == "custom rules here")
        os.environ.pop("MEMORY_EXTRACTION_INSTRUCTIONS", None)
        check("extract: empty default = use built-in",
              memconfig.load_config().extraction_instructions == "")
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        interface._reset_singleton()


def test_phase7_jobctx():
    print("Phase 7 jobctx (identity propagation, gated retrieve/writeback, agent outcomes):")
    saved = {k: os.environ.get(k) for k in ("MEMORY_ENABLED",)}

    class _FakeJob:
        def __init__(self, user_id="chuck", run_id="r1", memory_enabled=True,
                     has_switch=True):
            self.user_id = user_id
            self.run_id = run_id
            if has_switch:
                self.memory_enabled = memory_enabled
            self.logs = []

        def add_log(self, msg):
            self.logs.append(msg)

    class _NoSwitchJob:
        """A Job object from before the memory_enabled field existed."""
        user_id = "chuck"
        run_id = "r-old"

    class _FakeMem0:
        def __init__(self, hits):
            self._hits = hits
            self.added = []     # (user_id, metadata, infer)
            self.searched = []  # user_id
            self.fail = False

        def add(self, messages, user_id=None, metadata=None, infer=True):
            if self.fail:
                raise RuntimeError("boom")
            self.added.append((user_id, dict(metadata or {}), infer))
            return {"results": [{"id": f"new{len(self.added)}"}]}

        def search(self, query, filters=None, top_k=10):
            if self.fail:
                raise RuntimeError("boom")
            uid = (filters or {}).get("user_id")
            self.searched.append(uid)
            return [dict(h) for h in self._hits.get(uid, [])]

    class _FakeClient:
        def __init__(self, hits):
            self._mem = _FakeMem0(hits)

        def _ensure_client(self):
            return self._mem

        def _with_timeout(self, fn, timeout_s=None):
            return fn()

        def reset(self):
            pass

    from memory import jobctx

    try:
        os.environ["MEMORY_ENABLED"] = "true"
        interface._reset_singleton()

        # ── job_identity: safe extraction ──────────────────────────
        check("identity: None job -> unknown",
              jobctx.job_identity(None) == ("unknown", None, True),
              str(jobctx.job_identity(None)))
        check("identity: full job",
              jobctx.job_identity(_FakeJob("chuck", "r1", True))
              == ("chuck", "r1", True))
        check("identity: service job",
              jobctx.job_identity(_FakeJob("service", "r2", True))[0] == "service")
        check("identity: switch off propagates",
              jobctx.job_identity(_FakeJob("chuck", "r1", False))[2] is False)
        check("identity: legacy job (no switch) defaults on",
              jobctx.job_identity(_NoSwitchJob()) == ("chuck", "r-old", True),
              str(jobctx.job_identity(_NoSwitchJob())))

        # ── retrieve: gated, non-fatal ────────────────────────────
        fake = _FakeClient({"chuck": [{"id": "m1", "memory": "oat milk", "score": 0.9}]})
        interface._client = fake

        check("retrieve: switch off -> no block, no search",
              jobctx.retrieve(_FakeJob("chuck", "r", False), "coffee") == ""
              and fake._mem.searched == [],
              str(fake._mem.searched))
        check("retrieve: service -> no personal memory",
              jobctx.retrieve(_FakeJob("service", "r", True), "coffee") == "")
        check("retrieve: unknown -> no personal memory",
              jobctx.retrieve(_FakeJob("unknown", "r", True), "coffee") == "")
        block = jobctx.retrieve(_FakeJob("chuck", "r", True), "coffee")
        check("retrieve: user -> block rendered",
              "oat milk" in block, repr(block))

        fake._mem.fail = True
        check("retrieve: error -> non-fatal empty",
              jobctx.retrieve(_FakeJob("chuck", "r", True), "coffee") == "")
        fake._mem.fail = False

        # ── writeback_turn: gated, non-fatal, provenance ───────────
        fake2 = _FakeClient({})
        interface._client = fake2
        check("writeback: switch off -> no store",
              jobctx.writeback_turn(_FakeJob("chuck", "r", False),
                                    [{"role": "user", "content": "x"}]) == []
              and fake2._mem.added == [])
        check("writeback: service -> no store",
              jobctx.writeback_turn(_FakeJob("service", "r", True),
                                    [{"role": "user", "content": "x"}]) == []
              and fake2._mem.added == [])
        ids = jobctx.writeback_turn(
            _FakeJob("chuck", "r77", True),
            [{"role": "user", "content": "I like oat milk"}],
            source="chat",
        )
        check("writeback: user -> stored", len(ids) == 1, str(ids))
        uid, meta, infer = fake2._mem.added[-1]
        check("writeback: user routed", uid == "chuck", uid)
        check("writeback: source=chat", meta.get("source") == "chat", str(meta))
        check("writeback: turn_id=run_id", meta.get("turn_id") == "r77", str(meta))

        fake2._mem.fail = True
        check("writeback: error -> non-fatal []",
              jobctx.writeback_turn(_FakeJob("chuck", "r", True),
                                    [{"role": "user", "content": "x"}]) == [])
        fake2._mem.fail = False

        # ── writeback_outcome: agent_result provenance ─────────────
        fake3 = _FakeClient({})
        interface._client = fake3
        check("outcome: service -> no store",
              jobctx.writeback_outcome(_FakeJob("service", "r", True),
                                       "resolved the issue") == []
              and fake3._mem.added == [])
        check("outcome: empty text -> no store",
              jobctx.writeback_outcome(_FakeJob("chuck", "r", True), "   ") == [])
        ids = jobctx.writeback_outcome(
            _FakeJob("chuck", "run-9", True),
            "User's router issue was resolved by resetting the DHCP lease.",
            agent="deep_research",
        )
        check("outcome: user -> stored", len(ids) == 1, str(ids))
        uid, meta, infer = fake3._mem.added[-1]
        check("outcome: source=agent_result",
              meta.get("source") == "agent_result", str(meta))
        check("outcome: confidence=normal (lower trust)",
              meta.get("confidence") == "normal", str(meta))
        check("outcome: agent provenance tag",
              meta.get("agent") == "deep_research", str(meta))
        check("outcome: run_id correlated",
              meta.get("turn_id") == "run-9", str(meta))

        # ── skill content is never stored (procedural memory) ──────
        # A turn that is ONLY system/skill-instruction content must not
        # be stored (skills stay procedural — PDF §2).
        skill_turn = [
            {"role": "system", "content": "You are the morning brief generator. "
                                           "Follow these instructions: ..."},
            {"role": "tool", "content": "search results ..."},
        ]
        ok, reason = policy.should_store(skill_turn)
        check("skill content: system-only turn not stored",
              ok is False, reason)
        check("skill content: sanitize drops system/tool",
              policy.sanitize_turn(skill_turn) == [])
        check("skill content: learn_from_turn no-op on system-only",
              interface.learn_from_turn("chuck", skill_turn) == [])

    finally:
        for k in saved:
            if saved[k] is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = saved[k]
        interface._reset_singleton()


def test_phase8_admin():
    print("Phase 8 admin + metrics (admin-key ops bypass _valid_user, metrics exposition):")
    saved = {k: os.environ.get(k) for k in (
        "MEMORY_ENABLED", "MEMORY_HOUSEHOLD_ENABLED", "MEMORY_TIMEOUT_MS",
    )}

    class _FakeMem0:
        def __init__(self, data):
            self._data = data          # user_id -> list of point dicts
            self.deleted_users = []    # delete_all(user_id)
            self.deleted_ids = []      # delete(memory_id)
            self.updated = []          # (memory_id, text)
            self.searched = []         # (query, user_id)

        def get_all(self, filters=None, top_k=20):
            uid = (filters or {}).get("user_id")
            return [dict(p) for p in self._data.get(uid, [])][:top_k]

        def search(self, query, filters=None, top_k=10):
            uid = (filters or {}).get("user_id")
            self.searched.append((query, uid))
            return [dict(p) for p in self._data.get(uid, [])][:top_k]

        def update(self, memory_id, text):
            self.updated.append((memory_id, text))

        def delete(self, memory_id):
            self.deleted_ids.append(memory_id)

        def delete_all(self, user_id=None):
            self.deleted_users.append(user_id)
            self._data.pop(user_id, None)

    class _FakeClient:
        def __init__(self, data):
            self._mem = _FakeMem0(data)

        def _ensure_client(self):
            return self._mem

        def _with_timeout(self, fn, timeout_s=None):
            return fn()

        def reset(self):
            pass

    from memory import admin, metrics

    try:
        os.environ["MEMORY_ENABLED"] = "true"
        os.environ["MEMORY_HOUSEHOLD_ENABLED"] = "true"
        os.environ["MEMORY_TIMEOUT_MS"] = "1500"
        interface._reset_singleton()
        fake = _FakeClient({
            "chuck": [
                {"id": "c1", "memory": "chuck likes oat milk", "score": 0.9},
                {"id": "c2", "memory": "chuck's birthday is June 4", "score": 0.8},
            ],
            "service": [{"id": "s1", "memory": "service note", "score": 0.7}],
            "household": [{"id": "h1", "memory": "server rack in basement", "score": 0.6}],
        })
        interface._client = fake

        # ── list_user bypasses _valid_user (service is rejected by the chat path) ──
        check("admin list: service (bypass _valid_user)",
              {h["id"] for h in admin.list_user("service", scope="private")} == {"s1"},
              str([h["id"] for h in admin.list_user("service", scope="private")]))
        check("chat path: service rejected (contrast)",
              interface.list_memories("service") == [])

        hits_all = admin.list_user("chuck", scope="all")
        check("admin list: chuck private + household",
              {h["id"] for h in hits_all} == {"c1", "c2", "h1"},
              str([h["id"] for h in hits_all]))
        hits_priv = admin.list_user("chuck", scope="private")
        check("admin list: scope=private excludes household",
              {h["id"] for h in hits_priv} == {"c1", "c2"},
              str([h["id"] for h in hits_priv]))

        # ── list_user with query (semantic search) ──
        fake._mem.searched.clear()
        hits_q = admin.list_user("chuck", query="oat milk", scope="private")
        check("admin search: query triggers search",
              len(fake._mem.searched) >= 1 and hits_q, str(fake._mem.searched))

        # ── update / delete delegate to the interface ──
        check("admin update: ok", admin.update("c1", "chuck likes almond milk") is True)
        check("admin update: routed",
              fake._mem.updated == [("c1", "chuck likes almond milk")])
        check("admin delete: ok", admin.delete("c2") is True)
        check("admin delete: routed", fake._mem.deleted_ids == ["c2"])

        # ── delete_user bypasses _valid_user ──
        n = admin.delete_user("service")
        check("admin delete_user: service (bypass)", n == 1, f"n={n}")
        check("admin delete_user: routed", fake._mem.deleted_users == ["service"])

        # ── health ──
        h = admin.health()
        check("admin health: keys",
              {"healthy", "enabled", "counters", "user_counts"} <= set(h.keys()),
              str(sorted(h.keys())))
        check("admin health: enabled", h["enabled"] is True)

        # ── non-fatal: a failing client degrades to [] / 0 ──
        class _Boom:
            def _ensure_client(self):
                raise RuntimeError("boom")

            def reset(self):
                pass
        interface._client = _Boom()
        check("admin list: error -> non-fatal []", admin.list_user("chuck") == [])
        check("admin delete_user: error -> non-fatal 0", admin.delete_user("chuck") == 0)

        # ── metrics recording + exposition ──
        metrics._metrics = metrics._Metrics()  # fresh registry
        m2 = metrics.get_metrics()
        m2.record_search("ok", 0.12, 3)
        m2.record_search("error", 1.5, 0)
        m2.record_writeback("ok", 5.2, 2)
        m2.record_error("update")
        m2.set_user_count("chuck", 7)
        out = m2.exposition()
        check("metrics: search counter", 'memory_search_total{status="ok"} 1' in out, out[:200])
        check("metrics: search hits", "memory_search_hits_total 3" in out)
        check("metrics: writeback stored", "memory_writeback_stored_total 2" in out)
        check("metrics: error counter", 'memory_errors_total{op="update"} 1' in out)
        check("metrics: user gauge", 'memory_user_count{user_id="chuck"} 7' in out)
        check("metrics: histogram +Inf",
              'memory_search_latency_seconds_bucket{status="ok",le="+Inf"} 1' in out)
        check("metrics: histogram cumulative (le=2.5 covers 1.5)",
              'memory_search_latency_seconds_bucket{status="error",le="2.5"} 1' in out)
        check("metrics: no double braces", '{status="ok"}{le' not in out)
        check("metrics: no secrets in exposition", "oat milk" not in out and "chuck's birthday" not in out)
        check("metrics: exposition is str", isinstance(out, str) and out)

    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        interface._reset_singleton()


def main():
    test_policy()
    test_context()
    test_config_env()
    test_flag_off_path()
    test_unknown_user()
    test_delete_user_count()
    test_score_threshold()
    test_singleton_first_call()
    test_timeout_degradation()
    test_phase5_writeback()
    test_phase7_jobctx()
    test_phase8_admin()
    print()
    if FAILURES:
        print(f"RESULT: FAIL ({FAIL} failed: {FAILURES})")
        sys.exit(1)
    print(f"RESULT: ALL PASS ({PASS} checks)")


if __name__ == "__main__":
    main()