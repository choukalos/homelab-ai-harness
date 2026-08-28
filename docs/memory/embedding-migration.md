# Embedding Migration Runbook (v1 → v2)

**Status:** procedure only — **NO live migration performed in v1**
(memory_todo.md Phase 9 item 4). This is the runbook to follow when the
embedding model behind long-term memory changes.

The one invariant this runbook protects:

> **Never silently repoint a live alias.** `homelab-embedding-v1` is pinned to
> `ollama/nomic-embed-text` (768-dim) forever. A new model is a **new alias**
> (`homelab-embedding-v2`) + a **new collection** + a **re-embed from stored
> text** + a **quality comparison** + a **cutover**, with v1 kept briefly for
> rollback.

---

## Why a new collection (not an in-place re-embed)

- A Qdrant collection has a **fixed vector dimension** at creation. You cannot
  change it in place. A different embedding model (different dim, or the same
  dim but a different vector space) cannot share the old collection.
- Even with the *same* dimension, a new model produces a *different* vector
  space. Mixing v1 and v2 vectors in one collection makes similarity scores
  meaningless.
- So: new model ⇒ new collection. The old collection is left intact (read-only
  in practice) until the rollback window closes.

Current state (2026-08-28):

| alias | backend | dim | used by |
|---|---|---|---|
| `embeddings` | `ollama/nomic-embed-text` | 768 | KB path (`family_kb`, 384-dim legacy — separate) |
| `homelab-embedding-v1` | `ollama/nomic-embed-text` | 768 | long-term memory (`mem0_memories`) |

---

## Pre-flight (do this first, every time)

1. **Backup** — run `scripts/backup-memory.sh`. This captures `.env` + a
   `mem0_memories` snapshot + verifies the git tree is clean. You need this to
   roll back.
2. **Record the current state** (write it into the migration log):
   ```bash
   # point count + dimension of the live collection (admin key)
   curl -s -H "api-key: $QDRANT_ADMIN_API_KEY" \
     http://localhost:6333/collections/mem0_memories | \
     python3 -c 'import json,sys; r=json.load(sys.stdin)["result"]; \
       print("points=",r["points_count"], \
             "dim=",r["vectors_config"]["size"])'
   ```
3. **Confirm the alias→backend map** in `litellm/config.yml` and note which
   alias memory currently uses (`MEMORY_EMBED_MODEL`, default
   `homelab-embedding-v1`).
4. **Freeze writes** (optional but recommended for a clean re-embed): set
   `MEMORY_WRITEBACK_ENABLED=false` and rebuild skill-runner, OR simply accept
   that a few new points written during the re-embed will be re-embedded too
   (the re-embed script is idempotent by point id).

---

## Step 1 — Add the new alias (do NOT touch v1)

Add a **new** model entry to `litellm/config.yml` pointing at the new model.
Leave `homelab-embedding-v1` exactly as it is.

```yaml
  # ── New embedding model for long-term memory (versioned alias) ──────
  # v2: <new model>. v1 stays pinned to nomic-embed-text for rollback.
  # (copy the drop_params note from the v1 entry if the new backend needs it)
  - model_name: homelab-embedding-v2
    model_info:
      input_cost_per_token: 0.0000001
      output_cost_per_token: 0.0000001
      cache_creation_input_token_cost: 0.0000001
      cache_read_input_token_cost: 0.00000001
    litellm_params:
      model: <NEW_MODEL>          # e.g. ollama/<new-embed-model>
      api_base: http://matrix:11434
```

**Manual step (Chuck):** `./homelab.sh rebuild ai-only` (recreates litellm with
the new config). Then verify the new alias:

```bash
# returns a vector; note its length = the v2 dimension
curl -s http://localhost:4000/v1/embeddings \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"model":"homelab-embedding-v2","input":"ping"}' | \
  python3 -c 'import json,sys; print("v2 dim=",len(json.load(sys.stdin)["data"][0]["embedding"]))'
```

Record the v2 dimension — it is the dimension of the new collection.

---

## Step 2 — Create the new collection

Use the **admin key** (a scoped JWT cannot create collections — see
`docs/memory/IMPLEMENTATION_STATE.md` Phase 9 least-privilege).

```bash
V2_DIM=<from step 1>
curl -s -X PUT http://localhost:6333/collections/mem0_memories_v2 \
  -H "api-key: $QDRANT_ADMIN_API_KEY" -H 'Content-Type: application/json' \
  -d "{\"vectors\":{\"size\":${V2_DIM},\"distance\":\"Cosine\"}}"
```

(If the memory stack later enables BM25/hybrid, mirror the sparse-vector config
from `mem0_memories` — see the Phase 1 notes. v1 is dense-only.)

---

## Step 3 — Re-embed from stored text

Copy every point (text + metadata) from `mem0_memories` (v1) into
`mem0_memories_v2` (v2), embedding the **stored text** with the new model. The
reference tool is `scripts/reembed-memory.py`:

```bash
# dry run first (shows what it would do, writes nothing)
python3 scripts/reembed-memory.py --dry-run \
  --src-collection mem0_memories --dst-collection mem0_memories_v2 \
  --src-alias homelab-embedding-v1 --dst-alias homelab-embedding-v2

# then run it (idempotent by point id; resumable; rate-limited)
python3 scripts/reembed-memory.py \
  --src-collection mem0_memories --dst-collection mem0_memories_v2 \
  --src-alias homelab-embedding-v1 --dst-alias homelab-embedding-v2
```

Properties the tool guarantees:
- **Idempotent**: upserts by the original point id, so re-running is safe and
  picks up any points written during the migration.
- **Preserves metadata**: payload (user, source, importance, turn_id, …) is
  copied verbatim; only the vector changes.
- **Reads with the admin key, writes with the admin key** (ops tool).
- **Never touches v1** — it only reads `mem0_memories` and writes
  `mem0_memories_v2`.

Verify the copy:

```bash
for c in mem0_memories mem0_memories_v2; do
  echo -n "$c: "
  curl -s -H "api-key: $QDRANT_ADMIN_API_KEY" \
    http://localhost:6333/collections/$c | \
    python3 -c 'import json,sys; r=json.load(sys.stdin)["result"]; \
      print("points=",r["points_count"],"dim=",r["vectors_config"]["size"])'
done
# expect: same point count; v2 dim = the new model's dimension.
```

---

## Step 4 — Quality comparison (gate the cutover on this)

Run a representative query set against **both** collections and compare. The
goal: confirm v2 retrieves at least as well as v1 before you cut over.

```bash
# For a set of representative queries (preferences, facts, household), search
# each collection with its own alias and compare top-k overlap + relevance.
# (Use the memory search path or a small script; record the results.)
```

Record, for each query: top-3 hits from v1 vs v2, and a human judgment
(better / equal / worse). **Do not cut over if v2 is clearly worse** on the
representative set — fix the model choice or the re-embed first.

---

## Step 5 — Cut over

Point the memory service at v2 via env (in `.env`):

```
MEMORY_EMBED_MODEL=homelab-embedding-v2
MEMORY_COLLECTION=mem0_memories_v2
```

**Manual step (Chuck):** `./homelab.sh rebuild skill-only`. After the rebuild:
- New writes go to `mem0_memories_v2` with v2 vectors.
- Retrieval reads `mem0_memories_v2`.
- Run `scripts/memory-regression.sh` — it must pass, including the
  embedding-dimension check (now asserting the v2 dimension).

---

## Step 6 — Keep v1 briefly for rollback

- **Do not delete** `mem0_memories` (v1) or the `homelab-embedding-v1` alias.
- The rollback window is however long you need to be confident v2 is stable in
  production (suggest at least a few days of real use).
- **Rollback** = revert the two env vars to v1 + `./homelab.sh rebuild
  skill-only`. v1's collection and alias are still intact, so rollback is a
  config revert, not a data recovery.

---

## Step 7 — Cleanup (after the rollback window)

Once v2 is confirmed stable:
1. Back up again (`scripts/backup-memory.sh`) — the backup now snapshots
   `mem0_memories_v2` (update the script's `COLLECTION` if it is hardcoded).
2. Delete the v1 collection:
   ```bash
   curl -s -X DELETE http://localhost:6333/collections/mem0_memories \
     -H "api-key: $QDRANT_ADMIN_API_KEY"
   ```
3. Optionally remove the `homelab-embedding-v1` alias from `litellm/config.yml`
   (or keep it as a documented historical pin). Rebuild litellm.

---

## Do / Don't

| Do | Don't |
|---|---|
| Add a **new** versioned alias for the new model | **Repoint** `homelab-embedding-v1` to a new model |
| Create a **new** collection at the new dimension | Re-embed **in place** into the old collection |
| Re-embed **from stored text** (idempotent, by id) | Mix v1 and v2 vectors in one collection |
| **Quality-compare** before cutover | Cut over on "it's a newer model" alone |
| **Keep v1** for the rollback window | Delete the old collection before the window closes |
| Cut over via **env + rebuild** (auditable) | Change the alias mapping silently at runtime |

---

## Migration log (append one entry per migration)

| date | v1 alias → v2 alias | v1 dim → v2 dim | points | quality verdict | cutover commit | rollback window closed |
|---|---|---|---|---|---|---|
| — | (none yet) | — | — | — | — | — |