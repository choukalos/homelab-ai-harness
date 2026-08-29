# mcp_knowledge — Family Knowledge Base (v2)

MCP server for the family KB: **ingest, search, correct, forget, backup**.
The LLM is the operator — there is no watcher or pipeline; the LLM calls
`kb_ingest_file` / `kb_add_fact` when a document or fact should be stored.

**Live since 2026-08-29** (replaces the v1 read-only server, which searched
a static allowlist of non-existent collections).

## Architecture

```
LLM (LiteLLM / any MCP client)
  │  streamable-http, ai-net only (no published ports)
  ▼
mcp_knowledge (python:3.12-slim, :8000)
  ├─ Qdrant 1.18  ── kb_* collections (768-dim Cosine), JWT auth
  ├─ LiteLLM /v1/embeddings ── `embeddings` alias (nomic, 768-dim), batched
  └─ LiteLLM /v1/chat/completions ── `matrix-coder` vision (≤5 img/call,
                                     thinking OFF) for images + thin PDF pages
```

## Collections & naming

- One Qdrant collection per KB domain: `kb_<slug>` (e.g. `kb_gaming`,
  `kb_house`). Created **on the fly** by the first ingest/fact.
- **`kb_` prefix is enforced in code** on every Qdrant operation — the
  server cannot touch any other collection (the memory system's
  `mem0_memories` is out of reach by construction).
- `KB_API_KEY` is a **global-`m`** Qdrant JWT (`sub=mcp-knowledge`):
  per-collection scoping cannot cover on-the-fly collections (Qdrant
  requires global access for collection creation — proven 2026-08-29).
  The prefix gate, not the JWT, is the security boundary.
- Every collection has a **manifest point** (`kind=manifest`) carrying the
  KB's required `description` (owner decision N4).

## Point schema

| field | meaning |
|---|---|
| `text` | chunk text (verbatim for facts) |
| `kind` | `doc` / `image` / `fact` / `manifest` |
| `source` | source path (facts: `fact:<sha16>`) |
| `chunk_index` | 0-based index within the document |
| `page_range` | `[start, end]` PDF pages, or `null` |
| `sha256` | source file hash (ingest idempotency) |
| `ingested_at` / `updated_at` | ISO-8601 UTC |
| `superseded_by` | set only when superseded by `kb_correct` |

- **Deterministic point IDs**: `sha256(f"{source}:{chunk_index}")` →
  re-ingest is an idempotent upsert (same content = no-op, flagged via
  `sha_unchanged`).
- `kb_search` / `kb_forget` filter out `kind=manifest` and
  `superseded_by` points.

## Tools (11)

| tool | purpose |
|---|---|
| `kb_overview` | Map of all KBs: descriptions, doc/chunk counts, last ingested. Call first. |
| `kb_search` | Vector search (nomic 768-dim) across all KBs or one; keyword fallback; filters manifest + superseded. |
| `kb_get_document` | All chunks of one document, ordered, with page ranges. |
| `kb_list_documents` | Per-document metadata per KB (or all KBs). |
| `kb_recent_changes` | Ingested/updated within N days. |
| `kb_ingest_file` | PDF (pymupdf page-by-page + vision fallback for image/table pages), DOCX/PPTX/XLSX/HTML/CSV/EPUB/txt (markitdown), images (vision). ~1200-token chunks, 15% overlap, page ranges, batched embeddings. |
| `kb_add_fact` | Store a verbatim fact (also the vehicle for vision output: analyze an image, store the description). |
| `kb_delete_document` | Remove all chunks for a source path. Re-ingest = delete + ingest. |
| `kb_forget` | **Two-step** semantic delete: step 1 returns matches (deletes nothing); step 2 `confirm=true` + `ids` deletes. |
| `kb_correct` | Supersede a matched fact (score gate) and store the correction. |
| `kb_backup` | Snapshot all `kb_*` collections to `/home/chuck/data/backups/kb/` (+ optional source tar). |

## Ingestion rules

- **Canonical drop point**: `/home/chuck/data/ai-kb/raw/` (host) =
  `/data/ai-kb/raw` (container). `KB_ALLOWED_ROOTS` also covers
  `/data/media` and `/data/workspace` (all read-only mounts).
- `kb_ingest_file` resolves the path and **rejects anything outside the
  allowlist** (symlinks resolved; traversal blocked).
- PDF quality gate: pages with <200 chars of extracted text are rendered
  to PNG (150 dpi) and described by `matrix-coder` (≤5 pages/call).
- Long files are fine (LiteLLM MCP timeout 7200 s); the 29 MB / 500-page
  GURPS Basic Set ingests in minutes.

## Security

- `kb_` prefix gate on **all** Qdrant operations (unit-tested, K7).
- `KB_API_KEY` (global `m`) — the key itself cannot be scoped to
  on-the-fly collections; the code gate is the boundary.
- Source paths: allowlist + `resolve()` (no traversal, no symlinks out).
- ai-net only; no published ports; no Caddy route.
- Search excludes `superseded_by` points (corrections win).
- `kb_forget` is two-step by design (match → confirm + ids).

## Ops

- **Backup**: `kb_backup` (Qdrant snapshots → `/home/chuck/data/backups/kb/`).
- **Re-ingest**: `kb_delete_document` + `kb_ingest_file` (or just re-ingest
  — idempotent upsert; unchanged sha is a flagged no-op).
- **New KB**: first `kb_ingest_file`/`kb_add_fact` with a fresh name +
  `description` (required).
- **Env**: `QDRANT_URL`, `KB_API_KEY`, `LITELLM_API_BASE`,
  `LITELLM_API_KEY`, `EMBED_MODEL`, `VISION_MODEL`, `KB_ALLOWED_ROOTS`,
  `KB_BACKUP_DIR`.

## Retirements (2026-08-29)

- v1 read-only server (static allowlist, keyword-only) — replaced.
- `family_kb_ingest` skill — retired + deleted (the LLM is the ingest
  operator now).
- `family-wiki` container (mkdocs) — removed.
- Legacy `family_kb` collection (384-dim) — snapshotted + dropped.
- `/home/chuck/data/ai-kb/` legacy pipeline dirs — deleted (legacy tar in
  `/home/chuck/data/backups/`); only `raw/` remains.