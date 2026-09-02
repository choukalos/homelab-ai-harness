#!/usr/bin/env python3
"""Unit tests for memory.identity (Phase 3) — pure, NO live services.

Covers (per memory_todo.md Phase 3):
  - key -> user_id mapping (chuck via legacy comma-list env, service)
  - unknown/missing key -> "unknown" (never defaults to a real user)
  - comma-separated key lists in the referenced env var
  - first-match-wins, malformed entries skipped, unset env vars skipped
  - raw key values NEVER appear in log output
  - RequestContext defaults (household_id="family", unique run_id, source)
  - contextvar set/get/reset (task-scoped request context)
  - resolve_user_id() singleton + reset_resolver() test hook

Run with plain python3 (no pytest, no mem0):
    python3 skills/runner/memory/tests/test_identity.py
"""
from __future__ import annotations

import logging
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RUNNER_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, RUNNER_ROOT)

from memory import identity  # noqa: E402
from memory.identity import (  # noqa: E402
    HOUSEHOLD_ID,
    USER_SERVICE,
    USER_UNKNOWN,
    IdentityResolver,
    RequestContext,
    get_current_context,
    get_resolver,
    reset_current_context,
    reset_resolver,
    resolve_user_id,
    set_current_context,
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


class _LogCapture(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.records: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record.getMessage())


def main():
    # ── Map parsing + resolution ──────────────────────────────────────
    print("map parsing + resolution...")
    r = IdentityResolver(
        "chuck=ENV_A,service=ENV_B",
        environ={"ENV_A": "key-chuck", "ENV_B": "key-service"},
    )
    check("chuck key -> chuck", r.resolve("key-chuck") == "chuck")
    check("service key -> service", r.resolve("key-service") == "service")
    check("unmapped key -> unknown", r.resolve("key-son") == USER_UNKNOWN)
    check("missing key -> unknown", r.resolve(None) == USER_UNKNOWN)
    check("empty key -> unknown", r.resolve("") == USER_UNKNOWN)
    check("whitespace key -> unknown", r.resolve("   ") == USER_UNKNOWN)

    print("comma-separated key list (legacy SKILL_RUNNER_API_KEY)...")
    r2 = IdentityResolver("chuck=ENV_A", environ={"ENV_A": " k1 , k2 "})
    check("first listed key -> chuck", r2.resolve("k1") == "chuck")
    check("second listed key -> chuck", r2.resolve("k2") == "chuck")
    check("unlisted key -> unknown", r2.resolve("k3") == USER_UNKNOWN)

    print("edge cases...")
    r3 = IdentityResolver(
        "chuck=ENV_A,service=ENV_B",
        environ={"ENV_A": "same", "ENV_B": "same"},
    )
    check("same key in two entries -> first match wins", r3.resolve("same") == "chuck")

    r4 = IdentityResolver("badentry, chuck=ENV_A, =ENV_C, chuck=", environ={"ENV_A": "k"})
    check("malformed entries skipped", r4.resolve("k") == "chuck")

    r5 = IdentityResolver("chuck=UNSET_VAR", environ={})
    check("unset env var -> unknown", r5.resolve("anything") == USER_UNKNOWN)

    r6 = IdentityResolver("", environ={"ENV_A": "k"})
    check("empty map -> unknown", r6.resolve("k") == USER_UNKNOWN)

    # ── Phase 3.1: overlapping key claims (shadowing) ─────────────────
    print("Phase 3.1: overlapping claims warn + fixed map resolves...")
    cap3 = _LogCapture()
    log = logging.getLogger("memory.identity")
    log.addHandler(cap3)
    try:
        # Legacy shape that caused the 2026-09-02 bug: a shared comma-list
        # env var (SKILL_RUNNER_API_KEY = chuck+dylan keys) mapped to chuck
        # FIRST, shadowing dylan's own entry.
        r7 = IdentityResolver(
            "chuck=ENV_SHARED,chuck=ENV_CHUCK,dylan=ENV_DYLAN",
            environ={
                "ENV_SHARED": "k-chuck,k-dylan",
                "ENV_CHUCK": "k-chuck",
                "ENV_DYLAN": "k-dylan",
            },
        )
        check("shadowed key resolves to first user (documented first-match)",
              r7.resolve("k-dylan") == "chuck")
        check("conflict warning logged at construction",
              any("MEMORY_USER_KEYS CONFLICT" in rec for rec in cap3.records))
        conflict_recs = [r for r in cap3.records if "CONFLICT" in r]
        check("conflict names both users",
              any("chuck" in r and "dylan" in r for r in conflict_recs))
        check("conflict names env var names (not values)",
              any("ENV_SHARED" in r and "ENV_DYLAN" in r for r in conflict_recs))
        check("conflict leaks no raw key values",
              not any("k-dylan" in r or "k-chuck" in r for r in conflict_recs))
    finally:
        log.removeHandler(cap3)

    # Fixed per-user shape (post-Phase 3.1): disjoint pools, no warning.
    r8 = IdentityResolver(
        "chuck=ENV_CHUCK,dylan=ENV_DYLAN,service=ENV_SVC",
        environ={"ENV_CHUCK": "k-chuck", "ENV_DYLAN": "k-dylan", "ENV_SVC": "k-svc"},
    )
    check("fixed map: chuck key -> chuck", r8.resolve("k-chuck") == "chuck")
    check("fixed map: dylan key -> dylan", r8.resolve("k-dylan") == "dylan")
    check("fixed map: service key -> service", r8.resolve("k-svc") == USER_SERVICE)
    check("fixed map: unmapped -> unknown", r8.resolve("k-other") == USER_UNKNOWN)
    cap4 = _LogCapture()
    log.addHandler(cap4)
    try:
        r8.resolve("k-dylan")
    finally:
        log.removeHandler(cap4)
    check("fixed map: no conflict warning",
          not any("CONFLICT" in rec for rec in cap4.records))

    # ── Raw key values never appear in logs ───────────────────────────
    print("no raw key in log output...")
    cap = _LogCapture()
    log = logging.getLogger("memory.identity")
    old_level = log.level
    log.addHandler(cap)
    log.setLevel(logging.DEBUG)
    try:
        r.resolve("super-secret-key-value-123")
        r.resolve("key-chuck")
        r.resolve(None)
    finally:
        log.removeHandler(cap)
        log.setLevel(old_level)
    leaked = [rec for rec in cap.records if "super-secret-key-value-123" in rec]
    check("key value not in any log record", len(leaked) == 0, f"records={len(cap.records)}")
    check("unmapped key is logged (user_id only)",
          any("Unmapped API key" in rec and "unknown" in rec for rec in cap.records))

    # ── RequestContext ────────────────────────────────────────────────
    print("RequestContext...")
    ctx = RequestContext(user_id="chuck")
    check("default household_id", ctx.household_id == HOUSEHOLD_ID == "family")
    check("default source", ctx.source == "web")
    check("default agent_id", ctx.agent_id is None)
    check("run_id populated", len(ctx.run_id) > 0)
    ctx2 = RequestContext(user_id="chuck")
    check("run_id unique per request", ctx.run_id != ctx2.run_id)
    ctx3 = RequestContext(user_id="service", source="job", agent_id="siri_chat")
    check("explicit overrides", ctx3.source == "job" and ctx3.agent_id == "siri_chat")

    # ── contextvar (task-scoped request context) ──────────────────────
    print("contextvar...")
    check("no context outside a request", get_current_context() is None)
    tok = set_current_context(ctx)
    check("get after set", get_current_context() is ctx)
    reset_current_context(tok)
    check("get after reset", get_current_context() is None)

    # ── singleton + resolve_user_id ───────────────────────────────────
    print("resolve_user_id singleton...")
    os.environ["MEMORY_USER_KEYS"] = "chuck=TEST_ENV_A,service=TEST_ENV_B"
    os.environ["TEST_ENV_A"] = "host-chuck-key"
    os.environ["TEST_ENV_B"] = "host-service-key"
    reset_resolver()
    try:
        check("resolve_user_id (chuck)", resolve_user_id("host-chuck-key") == "chuck")
        check("resolve_user_id (service)", resolve_user_id("host-service-key") == USER_SERVICE)
        check("resolve_user_id (unknown)", resolve_user_id("other") == USER_UNKNOWN)
        check("singleton stable", get_resolver() is get_resolver())
        reset_resolver()
        check("reset_resolver drops singleton", get_resolver() is not None)
    finally:
        reset_resolver()
        for var in ("MEMORY_USER_KEYS", "TEST_ENV_A", "TEST_ENV_B"):
            os.environ.pop(var, None)

    print()
    if FAILURES:
        print(f"RESULT: FAIL ({FAIL} failed: {FAILURES})")
        sys.exit(1)
    print(f"RESULT: ALL PASS ({PASS} checks)")


if __name__ == "__main__":
    main()