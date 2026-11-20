# Memory Dedupe One-Time Cleanup — harness_reflection Lessons

_Ops note for the `tier3-memory-dedupe-supersede` proposal (applied
2026-11-20). One-time cleanup of the existing duplicate
`Lesson (date): …` entries written by `harness_reflection`, run after the
write-time dedupe/supersede landed in the memory interface. Executed via
short-lived `docker exec skill-runner python3` against the in-process
`memory.interface` (no containers/services restarted). User: `chuck`
(the reflection target user); household scope had 0 lesson entries._

## Method

1. **DRY-RUN first** (no writes): collected all `chuck` private memories
   with `metadata.source == "harness_reflection"` and a
   `Lesson (YYYY-MM-DD):` prefix (28 entries), then clustered them with
   search-based near-duplicate detection faithful to the write-path
   dedupe: for each entry, embed its **stem** (date prefix stripped) and
   run the raw semantic stage (`vector_store.search` → Qdrant cosine),
   keeping edges at **raw cosine ≥ 0.85** (`MEMORY_DEDUPE_THRESHOLD`
   default) or a `policy.is_supersede` match (same stem / explicit
   supersede wording) clearing the 0.5 relevance floor.
2. **Apply** (after the DRY-RUN table was reviewed): per cluster keep the
   most recent entry (max `updated_at`/`created_at`); where the most
   complete (longest) version differs, `update_memory` the keeper with
   that text (newer text wins, `updated_at` bumps); `delete_memory` the
   rest. A pre-apply safety check verified every plan ID was a
   `harness_reflection` `Lesson (...)` entry before any write.

**Key finding (affects the write path too):** mem0 2.x `Memory.search`
returns a **fused hybrid score** — `(semantic + BM25 + entity boost) /
max_possible` — NOT the raw cosine. A near-identical lesson pair scored
0.43 fused vs 0.97 raw. The write-path dedupe
(`interface._dedupe_find`) therefore runs the raw semantic stage
directly (embed query + `vector_store.search`) so
`MEMORY_DEDUPE_THRESHOLD` operates on the raw cosine it is documented
against. The DRY-RUN used the same raw-cosine metric.

## Result

The table below is the reviewed DRY-RUN would-merge/would-delete plan;
the apply step reproduced it exactly (0 failures), so DRY-RUN and
applied results are identical.

**28 → 5** `harness_reflection` lesson entries: **23 deleted**,
**1 keeper text updated**, 0 failures.

| Cluster (lesson) | Keeper (kept) | Deleted (id prefix) |
|---|---|---|
| recent_activity scheduled runs slow (~100–176s) → profile aggregation | `3709a1e3` (2026-11-15, most recent: 142s/102s/101s) | `c0513482`, `47068276`, `e20c6e2e`, `a494b460`, `fbe21baf`, `3a917385`, `9f6e3aa1`, `e4f14f8b` (8) |
| harness_reflection jobs duplicated in the 2026-11-08 window → idempotency/concurrency guard | `da6e729f` (2026-11-08T23:03, most recent: "Eight … jobs") | `73d000a3`, `07a55eea`, `8b554d87`, `e1580052`, `15bd3947`, `543d64b5` (6) |
| publish_file jobs created in identical batches at the same timestamps → deduplicate | `0308e8e4` (2026-11-08T23:03, most recent) — **text updated from `817f1217`** (most complete: adds "on 2026-11-08") | `817f1217`, `cc6d5214`, `1c72d164`, `8e9d3d71`, `931582a8` (5) |
| thor host reboot 2026-11-01 19:57 destroyed session context → checkpoint + approval | `0d37e5fc` (2026-11-08T23:03, most recent) | `c3ce74a2`, `9fe9b76f`, `6804a550`, `90e72c6b` (4) |

### Kept singletons (not clustered — below threshold)

- `1a51831b` (2026-11-15): "Multiple publish_file jobs were created at
  the same timestamp and one failed because the destination already
  existed with different content → preflight destination content hashes
  and require explicit overwrite." Borderline: raw cosine **0.8495** to
  the publish_file cluster (just under 0.85) and it carries genuinely
  new information (a different remedy) — kept, consistent with the
  write-path convention (a fresh write of it would also insert).

## Remaining (out of scope for this pass)

5 non-`Lesson` `harness_reflection` "duplication count is at least N
jobs" variants remain (`4b14f019`, `a8500869`, `ebd20df4` — "eight";
`b3030d8c`, `bda15e71` — "six"). The cleanup scope was `Lesson (...)`
entries only. The write-path dedupe now merges future writes of these
(including non-lesson reflection facts); a one-line follow-up cleanup or
the deferred periodic compaction job (see proposal) can fold the rest.

## Rollback

Deleted entries are gone from Qdrant (mem0 history.db keeps the
pre-delete text in the container's mem0 local dir until the container is
recreated). To restore, re-`memory_remember` the lesson text as `chuck`
or re-run the 2026-11-08/15 reflection inputs.
