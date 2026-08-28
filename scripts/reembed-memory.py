#!/usr/bin/env python3
"""Re-embed a mem0 Qdrant collection from stored text into a NEW collection.

Part of the embedding-migration runbook (docs/memory/embedding-migration.md).
Used when the memory embedding model changes (v1 -> v2): read every point's
stored TEXT from the source collection, embed it with the NEW model, and write
it to a NEW collection (new dimension / new vector space). The source
collection is left intact for rollback.

This tool is a REFERENCE implementation — it is NOT run as part of v1 (no
live migration). It is committed so the runbook is concrete and ready to use.

Design:
  - Reads points from SRC with payloads; text is payload["data"] (mem0's key).
  - Embeds in batches via LiteLLM /v1/embeddings (model = the NEW alias).
  - Upserts into DST with the SAME point id + SAME payload (only the vector
    changes). Upsert-by-id is idempotent, so re-runs / resumes are safe.
  - Rate-limited between batches; progress logged.
  - --dry-run shows the plan and writes nothing.

Credentials (env, from homelab/.env):
  QDRANT_ADMIN_API_KEY  — full-access Qdrant key (ops tool).
  LITELLM_KEY           — a key allowed to call the v2 embedding alias
                          (LITELLM_MASTER_KEY also works).

Usage:
  # dry run (safe — writes nothing)
  python3 scripts/reembed-memory.py --dry-run \
      --src mem0_memories --dst mem0_memories_v2 --model homelab-embedding-v2
  # real run
  python3 scripts/reembed-memory.py \
      --src mem0_memories --dst mem0_memories_v2 --model homelab-embedding-v2
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

BATCH = 16
SLEEP_BETWEEN_BATCHES_S = 0.5


def _req(url, method="GET", headers=None, body=None, timeout=60.0):
    """Minimal JSON HTTP request. Returns (status_code, parsed_json_or_text)."""
    data = json.dumps(body).encode() if body is not None else None
    h = {"Content-Type": "application/json"}
    if headers:
        h.update(headers)
    r = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            raw = resp.read().decode()
            try:
                return resp.status, json.loads(raw)
            except json.JSONDecodeError:
                return resp.status, raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, raw


def scroll_all(qdrant_url, key, collection):
    """Yield (id, vector, payload) for every point in the collection."""
    offset = None
    while True:
        body = {"limit": 256, "with_payload": True, "with_vectors": True}
        if offset is not None:
            body["offset"] = offset
        status, data = _req(
            f"{qdrant_url}/collections/{collection}/points/scroll",
            "POST", {"api-key": key}, body)
        if status != 200:
            print(f"ERROR: scroll {collection} -> HTTP {status}: {data}",
                  file=sys.stderr)
            sys.exit(1)
        res = data.get("result", {})
        for pid, vec, payload in res.get("points", []):
            yield pid, vec, payload
        offset = res.get("offset")
        if offset is None:
            break


def embed_batch(litellm_url, key, model, texts):
    """Return a list of embedding vectors (one per input text, in order)."""
    status, data = _req(
        f"{litellm_url}/v1/embeddings", "POST",
        {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        {"model": model, "input": texts})
    if status != 200:
        print(f"ERROR: embed -> HTTP {status}: {str(data)[:300]}", file=sys.stderr)
        sys.exit(1)
    items = sorted(data.get("data", []), key=lambda d: d.get("index", 0))
    return [d["embedding"] for d in items]


def upsert(qdrant_url, key, collection, points):
    if not points:
        return
    status, data = _req(
        f"{qdrant_url}/collections/{collection}/points", "PUT",
        {"api-key": key}, {"points": points, "wait": True})
    if status not in (200, 201, 202):
        print(f"ERROR: upsert {collection} -> HTTP {status}: {str(data)[:300]}",
              file=sys.stderr)
        sys.exit(1)


def main():
    p = argparse.ArgumentParser(
        description="Re-embed a mem0 collection into a new one (v1 -> v2).")
    p.add_argument("--src", default="mem0_memories",
                   help="source collection (v1)")
    p.add_argument("--dst", default="mem0_memories_v2",
                   help="destination collection (v2)")
    p.add_argument("--model", default="homelab-embedding-v2",
                   help="NEW embedding alias to embed with")
    p.add_argument("--qdrant-url",
                   default=os.environ.get("QDRANT_URL", "http://localhost:6333"))
    p.add_argument("--litellm-url",
                   default=os.environ.get("LITELLM_URL", "http://localhost:4000"))
    p.add_argument("--dry-run", action="store_true",
                   help="show the plan; write nothing")
    args = p.parse_args()

    qkey = os.environ.get("QDRANT_ADMIN_API_KEY", "")
    lkey = os.environ.get("LITELLM_KEY", "")
    if not qkey:
        print("ERROR: QDRANT_ADMIN_API_KEY not set", file=sys.stderr)
        return 2
    if not lkey:
        print("ERROR: LITELLM_KEY not set", file=sys.stderr)
        return 2

    print(f"==> reading {args.src} ...")
    points = list(scroll_all(args.qdrant_url, qkey, args.src))
    total = len(points)
    if total == 0:
        print(f"==> {args.src} is empty — nothing to re-embed.")
        return 0

    # Determine the v2 dimension from a single probe embedding.
    probe = embed_batch(args.litellm_url, lkey, args.model, ["dimension probe"])
    v2_dim = len(probe[0])
    print(f"==> v2 model '{args.model}' dimension = {v2_dim}")

    if args.dry_run:
        print("==> DRY RUN — plan:")
        print(f"    src={args.src} ({total} pts) -> dst={args.dst} (dim {v2_dim})")
        for pid, _vec, payload in points[:5]:
            text = (payload or {}).get("data", "")
            print(f"    [{str(pid)[:8]}] {text[:70]!r}")
        if total > 5:
            print(f"    ... ({total - 5} more)")
        print("    (no writes performed)")
        return 0

    # Ensure the destination collection exists with the right dimension.
    status, _data = _req(f"{args.qdrant_url}/collections/{args.dst}",
                         "GET", {"api-key": qkey})
    if status == 404:
        print(f"==> creating {args.dst} (dim {v2_dim}) ...")
        status, data = _req(
            f"{args.qdrant_url}/collections/{args.dst}", "PUT",
            {"api-key": qkey},
            {"vectors": {"size": v2_dim, "distance": "Cosine"}})
        if status not in (200, 201, 202):
            print(f"ERROR: create {args.dst} -> HTTP {status}: {data}",
                  file=sys.stderr)
            return 1
        time.sleep(1.0)
    else:
        print(f"==> {args.dst} already exists (reusing; upsert-by-id is idempotent)")

    print(f"==> re-embedding {total} points in batches of {BATCH} ...")
    done = 0
    texts: list[str] = []
    meta: list[tuple] = []

    def _flush():
        nonlocal texts, meta, done
        if not texts:
            return
        vecs = embed_batch(args.litellm_url, lkey, args.model, texts)
        if len(vecs) != len(texts):
            print(f"ERROR: embed returned {len(vecs)} vectors for "
                  f"{len(texts)} texts", file=sys.stderr)
            sys.exit(1)
        pts = [{"id": pid, "vector": vec, "payload": payload}
               for (pid, payload), vec in zip(meta, vecs)]
        upsert(args.qdrant_url, qkey, args.dst, pts)
        done += len(texts)
        print(f"    {done}/{total}")
        texts, meta = [], []

    for pid, _vec, payload in points:
        text = (payload or {}).get("data", "") or ""
        texts.append(text)
        meta.append((pid, payload))
        if len(texts) >= BATCH:
            _flush()
            time.sleep(SLEEP_BETWEEN_BATCHES_S)
    _flush()

    print(f"==> done. {done} points re-embedded into {args.dst}.")
    print("    Next: quality comparison (runbook Step 5), then cutover (Step 6).")
    print("    DO NOT delete the source collection until the rollback window closes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())