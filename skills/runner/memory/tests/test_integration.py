#!/usr/bin/env python3
"""Integration test for the memory module — LIVE Qdrant + LiteLLM.

Runs in a throwaway container on ai-net (like the Phase 1 round-trip) but
exercises the Phase 2 ``memory`` package interface end-to-end:
  - health check
  - learn_from_turn (writeback) with extraction retries (matrix-coder is
    occasionally flaky on JSON output)
  - search_memory (private + household)
  - list_memories
  - update_memory / delete_memory
  - user isolation (different user sees nothing)
  - timeout -> graceful degradation (unreachable Qdrant -> [] not a crash)
  - cleanup (delete test users)

Requires env: MEMORY_LITELLM_BASE_URL, MEMORY_LITELLM_KEY, MEMORY_QDRANT_URL,
MEMORY_COLLECTION, MEMORY_EMBED_DIM, MEMORY_TOP_K, MEMORY_TIMEOUT_MS,
MEMORY_EXTRACTION_MODEL. Run with mem0ai installed.
"""
from __future__ import annotations

import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
RUNNER_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, RUNNER_ROOT)

from memory import interface  # noqa: E402
from memory import config as memconfig  # noqa: E402

PASS = 0
FAIL = 0
FAILURES = []


def check(name, cond, detail=""):
    global PASS, FAIL
    print(f"  {'PASS' if cond else 'FAIL'}: {name}" + (f" — {detail}" if detail else ""))
    if cond:
        PASS += 1
    else:
        FAIL += 1
        FAILURES.append(name)


def learn_with_retry(user, messages, marker, attempts=4):
    """learn_from_turn, retrying while the fact does not land (matrix-coder
    occasionally emits extraction JSON mem0's parser rejects). ``marker`` is a
    keyword expected to survive mem0's fact-rewriting (e.g. 'oat milk')."""
    marker = marker.lower()
    for i in range(1, attempts + 1):
        interface.learn_from_turn(user, messages)
        time.sleep(1.0)
        found = any(marker in h["text"].lower() for h in interface.list_memories(user, limit=50))
        if found:
            return True, i
        print(f"  (retry {i}/{attempts}: '{marker}' not stored yet)")
    return False, attempts


def main():
    cfg = interface._get_config()
    print(f"config: collection={cfg.collection} llm={cfg.extraction_model} "
          f"embed={cfg.embed_model} dim={cfg.embed_dim} top_k={cfg.top_k} "
          f"timeout_ms={cfg.timeout_ms} household={cfg.household_enabled}")
    print(f"retrieval_allowed={cfg.retrieval_allowed} writeback_allowed={cfg.writeback_allowed}")

    print("health...")
    check("is_healthy", interface.is_healthy() is True)

    user = "memory_test"
    other = "memory_test_other"

    print("cleanup (idempotent)...")
    interface.delete_user_memories(user)
    interface.delete_user_memories(other)
    interface.delete_user_memories("chuck")
    interface.delete_user_memories(cfg.household_user_id)

    print("learn (private, with retries)...")
    ok, tries = learn_with_retry(
        user,
        [{"role": "user", "content": "Remember: I prefer oat milk lattes because dairy upsets my stomach."}],
        "oat milk",
    )
    check("learn stored private fact", ok, f"tries={tries}")

    print("learn (household)...")
    okh, tries_h = learn_with_retry(
        cfg.household_user_id,
        [{"role": "user", "content": "The home server rack is in the basement next to the water heater."}],
        "basement",
    )
    check("learn stored household fact", okh, f"tries={tries_h}")

    print("search (private)...")
    hits = interface.search_memory(user, "what milk do I like in my coffee?")
    check("search finds private fact",
          any("oat milk" in h["text"].lower() for h in hits),
          f"top={hits[0]['text'][:60] if hits else 'none'}")
    check("search hit has source", all(h["source"] in ("private", "household") for h in hits))

    print("search (household merged)...")
    hits2 = interface.search_memory(user, "where is the server rack?")
    check("search finds household fact",
          any("basement" in h["text"].lower() for h in hits2),
          f"top={hits2[0]['text'][:60] if hits2 else 'none'}")

    print("list_memories...")
    listed = interface.list_memories(user, limit=50)
    check("list has >=1 private", len(listed) >= 1, f"count={len(listed)}")

    print("update_memory...")
    # Find the oat-milk memory id and update it.
    target = next((h for h in interface.list_memories(user, limit=50)
                   if "oat milk" in h["text"].lower()), None)
    if target:
        upd = interface.update_memory(target["id"], "I switched to oat milk flat whites.")
        time.sleep(1.0)
        refl = interface.search_memory(user, "what coffee do I drink?")
        joined = " ".join(h["text"].lower() for h in refl)
        check("update returned True", upd is True)
        check("update reflected", "flat white" in joined, f"top={joined[:80]}")
    else:
        check("update target found", False, "no oat-milk memory to update")

    print("delete_memory...")
    if target:
        dele = interface.delete_memory(target["id"])
        time.sleep(1.0)
        remaining = interface.list_memories(user, limit=50)
        check("delete returned True", dele is True)
        check("delete removed id", all(h["id"] != target["id"] for h in remaining),
              f"remaining={len(remaining)}")

    print("user isolation...")
    iso = interface.search_memory(other, "oat milk coffee")
    private_iso = [h for h in iso if h["source"] == "private"]
    check("other user sees no private facts", len(private_iso) == 0,
          f"private_hits={len(private_iso)}")

    # ── Phase 3: identity isolation (chuck vs memory_test) ─────────────
    # The real "chuck" principal is used (per memory_todo.md Phase 3 tests);
    # its memories are cleaned up at the end of the run.
    print("identity isolation (chuck vs memory_test)...")
    okc, tries_c = learn_with_retry(
        "chuck",
        [{"role": "user", "content": "I switched to black coffee in the mornings now."}],
        "black coffee",
    )
    check("chuck stores own preference", okc, f"tries={tries_c}")
    okt, tries_t = learn_with_retry(
        user,
        [{"role": "user", "content": "I prefer green tea with honey in the mornings."}],
        "green tea",
    )
    check("memory_test stores own preference", okt, f"tries={tries_t}")

    hits_chuck = interface.search_memory("chuck", "what do I drink in the morning?")
    hits_test = interface.search_memory(user, "what do I drink in the morning?")
    check("chuck finds own coffee fact",
          any("coffee" in h["text"].lower() for h in hits_chuck),
          f"top={hits_chuck[0]['text'][:60] if hits_chuck else 'none'}")
    check("chuck does NOT see memory_test's tea",
          not any("green tea" in h["text"].lower() for h in hits_chuck))
    check("memory_test finds own tea fact",
          any("tea" in h["text"].lower() for h in hits_test),
          f"top={hits_test[0]['text'][:60] if hits_test else 'none'}")
    check("memory_test does NOT see chuck's coffee",
          not any("black coffee" in h["text"].lower() for h in hits_test))

    # Household-scoped fact (learned above under cfg.household_user_id) is
    # visible to chuck, not just to the user who learned it.
    hits_chuck_hh = interface.search_memory("chuck", "where is the server rack?")
    check("household fact visible to chuck",
          any("basement" in h["text"].lower() for h in hits_chuck_hh),
          f"top={hits_chuck_hh[0]['text'][:60] if hits_chuck_hh else 'none'}")

    # Unknown principal: no retrieval, no writeback.
    check("unknown user search -> []", interface.search_memory("unknown", "anything") == [])
    check("unknown user learn -> []",
          interface.learn_from_turn("unknown", [{"role": "user", "content": "x"}]) == [])

    # Raw key values never stored: secret-like content is filtered by policy.
    fake_key = "sk-test-identity-9f8e7d6c5b4a"
    secret_res = interface.learn_from_turn(
        "chuck", [{"role": "user", "content": f"please remember my api_key={fake_key}"}])
    check("secret-like content not stored", secret_res == [], f"res={secret_res}")

    # Direct Qdrant scan: no payload contains the fake key or the real key.
    # Qdrant 1.18: the old GET /collections/{name}/points endpoint is gone —
    # use POST /collections/{name}/points/scroll instead.
    import json as _json
    import urllib.request as _urlreq
    real_key = os.environ.get("SKILL_RUNNER_API_KEY", "")
    _req = _urlreq.Request(
        f"{cfg.qdrant_url}/collections/{cfg.collection}/points/scroll",
        data=_json.dumps({"limit": 256}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with _urlreq.urlopen(_req, timeout=10) as _resp:
        _points = _json.loads(_resp.read()).get("result", {}).get("points", [])
    _all_payloads = _json.dumps([p.get("payload", {}) for p in _points])
    check("no fake key in any Qdrant payload", fake_key not in _all_payloads,
          f"points={len(_points)}")
    if real_key:
        check("no real API key in any Qdrant payload", real_key not in _all_payloads)

    print("timeout -> graceful degradation (unreachable qdrant)...")
    # Point a fresh client at an unreachable Qdrant with a short timeout.
    # Dummy api_key so mem0 init succeeds and the test exercises the real
    # network-failure path (not the missing-credentials init failure).
    badcfg = memconfig.MemoryConfig(
        enabled=True, retrieval_enabled=True,
        qdrant_url="http://nonexistent-host:6333", timeout_ms=800,
        litellm_api_key="test-dummy-key",
    )
    from memory.client import MemoryClient
    badclient = MemoryClient(badcfg)
    t0 = time.time()
    # Force a search through the bad client by monkeypatching the singleton.
    saved_client = interface._client
    interface._client = badclient
    try:
        res = interface.search_memory(user, "coffee")
        elapsed = time.time() - t0
        check("degraded search returns []", res == [], f"took {elapsed*1000:.0f}ms")
        check("degraded promptly (<3s)", elapsed < 3.0, f"{elapsed*1000:.0f}ms")
    finally:
        interface._client = saved_client
        interface._reset_singleton()

    print("cleanup...")
    interface.delete_user_memories(user)
    interface.delete_user_memories(other)
    interface.delete_user_memories("chuck")
    interface.delete_user_memories(cfg.household_user_id)
    time.sleep(1.0)
    check("cleanup: user empty", len(interface.list_memories(user, limit=50)) == 0)
    check("cleanup: chuck empty", len(interface.list_memories("chuck", limit=50)) == 0)

    print()
    if FAILURES:
        print(f"RESULT: FAIL ({FAIL} failed: {FAILURES})")
        sys.exit(1)
    print(f"RESULT: ALL PASS ({PASS} checks)")


if __name__ == "__main__":
    main()