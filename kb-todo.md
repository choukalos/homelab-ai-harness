# Family KB / Knowledge MCP — Rebuild Plan

> Planning doc for the KB/knowledge workstream (post-memory-project).
> Companion to `blog-todo.md` style: discovered state → decisions → phases → questions.
> Owner: chuck. Last updated: 2026-08-28 (K0 discovery complete).

---

## 1. S0 — Discovered state (Thor, 2026-08-28)

### 1.1 Memory (new — Phase 9 COMPLETE, do not disturb)

- **Engine:** mem0 2.0.19 OSS, in-process in `skill-runner`. Collection
  **`mem0_memories`** (768-dim, Cosine). Identity: `chuck` / `service` /
  `unknown` + `household` scope. Admin REST + CLI + metrics +
  `scripts/backup-memory.sh` all live.
- **Embeddings:** LiteLLM aliases `embeddings` + `homelab-embedding-v1` →
  `ollama/nomic-embed-text` (768-dim) on matrix:11434. Extraction LLM:
  `matrix-coder`.
- **Qdrant RBAC (live):** JWT for skill-runner (rw `mem0_memories` only),
  read-only API key for mcp_knowledge, admin API key (OPS). Verified:
  JWT foreign-collection 403, read-only write 403.
- **Boundary (locked):** memory = personal facts/preferences auto-extracted
  from conversation, per-user, ADD-only (supersede statements). Phase 6
  (MCP memory tools) deferred.

### 1.2 KB (old — broken, from the decommissioned harness)

- **Qdrant `family_kb`:** 384-dim (embedded by
  `BAAI/bge-small-en-v1.5` — model no longer in the stack), **18 points**:
  - 9 × auto-generated **wiki index pages** (`*/index.md` — the mkdocs
    "family blog" nav, pure RAG noise)
  - 8 × real chunks from **3 source docs**: `family/pet-care.md` (2),
    `house/house-hold-maintenance-notes.md` (3), `vehicles/auto-detailing.md` (3)
  - Payload schema: `{category, chunk_index, source, text}`
- **mcp_knowledge (live, 4 read-only tools):** `kb_search` /
  `kb_get_document` / `kb_list_collections` / `kb_recent_changes`.
  - **D6a:** allowlist `family_curated`/`homelab_curated`/`coding_curated`
    matches **no real collection** → every call finds nothing.
  - **D6b:** `kb_search` does exact-match `scroll` (MatchValue on `content`),
    **not vector search** — semantic search is broken by design.
  - Uses the Qdrant **read-only** key (correct for today, wrong for writes).
- **`family_kb_ingest` skill (broken):** POSTs to
  `skill-runner:8091/knowledge/ingest` — endpoint doesn't exist post-rebuild.
  Manifest still points at `local/qwen-coder` (dead alias).
- **Old pipeline (git history, `ai-harness/family_kb/`):**
  - File-structure pipeline: `raw/{category}/` → watchdog →
    `processed/{markdown,chunks}/` → `failed/` + `repo/{category}/` wiki.
  - **`nav_gen.py` (311 lines):** generated per-category `index.md` +
    `mkdocs.yml` nav = **the "family blog web site" portion**.
  - PDF: docling → markdown + docling.json. Images: pytesseract OCR.
  - Chunking: 1200 chars / 200 overlap. Embed: bge-small (384).
- **On disk:** `/home/chuck/data/ai-kb/` — `raw/` (category subdirs +
  `pdfs/` + `images/` — the **source files, keep**), `processed/`, `failed/`,
  `repo/` (wiki), `mkdocs.yml`, `embeddings/`, `reports/`.
- **`family-wiki` container (RUNNING):** `squidfunk/mkdocs-material:latest`
  in `compose/compose.ai-core.yml`, `serve -a 0.0.0.0:8000`, port
  **8011 (LAN)**, mounts `ai-kb/mkdocs.yml` + `ai-kb/repo`. No Caddy route
  (LAN-only). **This is what the owner wants removed.**
- **Qdrant exposure (D9, "revisit with family-KB work"):** port 6333
  published on **0.0.0.0** (LAN-wide). API keys required (JWT RBAC on).

### 1.3 markitdown (owner-suggested extractor)

- `pip install 'markitdown[all]'` — PDF (pypdf text layer), DOCX, PPTX,
  XLSX/XLS, HTML, CSV/JSON/XML, ZIP, EPUB, audio transcription, images
  (EXIF + OCR), YouTube.
- **Tables in PDFs:** base converter is text-flow (pypdf) — table *structure*
  is not guaranteed. **Images in PDFs:** base converter skips them.
- **LLM-vision hooks:** `llm_client`/`llm_model` (OpenAI-compatible) for
  image descriptions (pptx + standalone images). Third-party
  **`markitdown-ocr`** plugin: LLM-Vision OCR of images embedded in
  PDF/DOCX/PPTX/XLSX via the same `llm_client` pattern, no extra ML deps.
- **Pagination:** base PDF converter does not emit page markers → page
  mapping needs a parallel `pymupdf` (fitz) pass (also gives per-page image
  + table detection for the vision fallback).

---

## 2. Requirements (owner, 2026-08-28)

1. **No conflicts with memory** — KB and mem0 must coexist cleanly
   (separate collections/keys/identity; documented semantic boundary).
2. **Ingest images + tables** (PDFs with tables/images currently fail).
   Use **markitdown** as the suggested extractor; vision models available
   (`matrix-coder` named as candidate).
3. **Remove the family blog web site portion** (mkdocs wiki + nav/index
   generation) — "wasn't useful".
4. **KB = files or facts fed in via an LLM** that uses the tooling to
   process/store. **No file-structure cruft** (raw/processed/failed/repo
   tree, watcher, category directories).
5. **Pagination** — must handle ~1000-page PDFs.
6. **High-level KB listing** — tooling tells the LLM what KBs exist.
7. **Forget / correct** — "forget that fact", "it should be this instead".
8. **KB backup.**
9. Vision-enabled models may be used if needed.

---

## 3. Proposed architecture

### 3.1 Separation from memory (conflict analysis)

| Axis | Memory (mem0) | KB (new) | Conflict? |
|---|---|---|---|
| Collection | `mem0_memories` (768) | `family_kb` (rebuilt, 768) | No — separate |
| Qdrant key | JWT (rw `mem0_memories` only) | **new API key, rw KB collections only** | No — scoped |
| Engine | mem0 in skill-runner | mcp_knowledge container | No |
| Identity | per-user (`chuck`/`service`) | **no user_id — household-shared** | No |
| Write path | auto-extraction from chat | **explicit LLM tool calls only** | No |
| Read path | auto pre-request retrieval | **`kb_search` tool (LLM decides)** | No (v1) |
| Embeddings | `homelab-embedding-v1` (nomic 768) | `embeddings` (same backend, per D7) | Compatible |

**Semantic boundary (to document):** memory = *who we are / what we
prefer*, learned from conversation, per-person. KB = *what we know / what
we filed*, explicit documents + facts, household-shared. A fact can live in
both (accepted; dedup awareness is a future workstream).

**v1 rule: chat does NOT auto-retrieve from the KB.** Siri answers from
memory + tools; the LLM calls `kb_search` when it needs filed knowledge.
This keeps the two systems orthogonal. (Hybrid retrieval = future.)

### 3.2 Ingestion model — the LLM is the operator

No watcher, no watched dir, no pipeline directories. Two entry points:

- **Files:** LLM has a path (media/, workspace/, anywhere readable) →
  calls `kb_ingest_file(path, kb, ...)` → server converts (markitdown),
  chunks with pagination, embeds (batched via LiteLLM), upserts.
  Returns `{doc_id, pages, chunks, sha256, warnings[]}`.
- **Facts:** LLM calls `kb_add_fact(text, kb, ...)` — single fact, stored
  verbatim (`kind=fact`). Also the vehicle for **vision output**: the LLM
  reads an image (via a vision model), then stores the description/table
  as a fact tied to the source.

**Where the code lives:** `mcp_knowledge` becomes the full KB server
(convert + embed + Qdrant rw). Rationale: "LLM uses the tooling" = MCP
tools; single container; no skill-runner dependency for KB ops.
Tradeoffs accepted: container image gets `markitdown[all]` + `pymupdf`
(deps, ~50 MB); container gets a **new scoped write key** (not the
read-only key) + ro mounts of `/home/chuck/data/media` +
`/home/chuck/workspace` (source access). Same trust model as mcp_mysql
(write-protected user): the key can only touch KB collections.

`family_kb_ingest` skill: **retired** (MCP tools replace it; see Q9).

### 3.3 markitdown + vision pipeline (K3/K4)

```
file ──► markitdown.convert()  (PDF/DOCX/PPTX/XLSX/HTML/CSV/ZIP/EPUB/txt)
          │
          ├─ PDF: pymupdf parallel pass → page map (page → text span)
          │        + per-page flags: has_image / has_table (heuristic)
          │
          ├─ pages flagged (image/table) AND quality gate fails:
          │     render page (pymupdf, 150 dpi) → vision model
          │     (matrix-coder via LiteLLM, image input) → markdown
          │     (description + table as markdown table) → splice in
          │
          └─ standalone images: markitdown (EXIF+OCR) + llm_client
               (matrix-coder) description → fact or doc chunk
```

- `markitdown-ocr` plugin (third-party, LLM-vision OCR of embedded images)
  is the **preferred** mechanism if it works with a LiteLLM OpenAI-client
  — evaluate in K4; fallback is the page-render splice above (first-party,
  no plugin supply chain).
- **Quality gate (per doc):** after conversion, sample N pages; if
  table/image pages produced empty/garbage text → vision fallback for
  those pages. Warnings surfaced in the ingest result.
- Vision model: **Q1 — verify `matrix-coder` actually accepts image
  input** (Qwen3.6-27B text model may not; if not, pick the VL alias).

### 3.4 Pagination + chunking (1000-page PDFs)

- PDFs processed **page-by-page** (pymupdf) — never the whole doc in one
  conversion pass; markitdown used for the text-quality pass.
- Markdown assembled with `<!-- page N -->` markers.
- Chunking: ~1200 tokens, 15% overlap, **prefer heading/page boundaries**;
  every chunk carries `page_range: [start, end]` + `chunk_index`.
- 1000 pages → est. 3–6k chunks; embeddings in batches of 32 via LiteLLM
  (nomic on matrix — fast; full doc expected to ingest in minutes, not
  hours). `kb_ingest_file` is a long MCP call → LiteLLM MCP timeout for
  mcp_knowledge set to 7200 (same as mcp_media).
- Re-ingest = `kb_delete_document(source)` + `kb_ingest_file` (sha256 in
  payload enables change detection; `kb_ingest_file` warns if sha matches).

### 3.5 Collections + payload schema

- **One collection `family_kb` (rebuilt at 768-dim, Cosine)** with a
  `kb` tag field (`family` / `homelab` / `research` / …). Multi-KB =
  payload tag, not multiple collections (Q3). `kb_overview` groups by `kb`.
- Drop the old 384-dim collection; **re-ingest the 3 real source docs**
  from their markdown sources in `ai-kb/processed/markdown/` (Q5).
  Wiki index pages: gone forever (requirement 3).

```
text          chunk text (markdown)
kind          doc | fact | image | table
source        file path or "fact:<slug>"
kb            family | homelab | research | ...
chunk_index   int
page_range    [int, int] | null
sha256        source file hash (docs) | null
ingested_at   iso8601
updated_at    iso8601
superseded_by point_id | null   (corrections, see 3.6)
```

Deterministic point IDs: `sha256(source + ":" + chunk_index)` → re-ingest
is idempotent upsert; deletes are exact.

### 3.6 Toolset — mcp_knowledge v2 (~11 tools)

**Read (fixed/kept):**
| Tool | Notes |
|---|---|
| `kb_search(query, top_k=5, kb?)` | **real vector search** (embed via LiteLLM `embeddings`); hybrid: vector + keyword fallback; returns snippets + `page_range` + `source` |
| `kb_get_document(source)` | all chunks of a doc, ordered |
| `kb_list_documents(kb?)` | per-doc metadata (source, pages, chunks, sha, ingested_at) |
| `kb_recent_changes(days=7)` | kept (now has real timestamps) |

**High-level (requirement 6):**
| Tool | Notes |
|---|---|
| `kb_overview()` | "what KBs do I have": per `kb` tag — doc count, chunk count, total size, last ingested, top sources. The LLM's map of the KB. |

**Write (new — requirement 4, 7):**
| Tool | Notes |
|---|---|
| `kb_ingest_file(path, kb, description?)` | markitdown pipeline (§3.3/3.4); long-running; returns doc_id + stats + warnings |
| `kb_add_fact(text, kb, source_hint?)` | verbatim fact; also stores vision-model output |
| `kb_delete_document(source)` | remove all chunks for a source |
| `kb_forget(query, confirm=false)` | **two-step**: default returns semantic matches (ids + snippets, nothing deleted); `confirm=true` + `ids` deletes. "forget that fact" |
| `kb_correct(old_query, new_text, kb?)` | finds the old fact/chunk (top-1, must exceed score gate), marks `superseded_by`, stores new text as new point; `kb_search` filters superseded. "it should be this instead" |

**Backup (requirement 8):**
| Tool | Notes |
|---|---|
| `kb_backup()` | Qdrant snapshot of `family_kb` → `/home/chuck/data/backups/kb/` (+ optional `tar` of source files if `include_sources=true`). Mirrors `backup-memory.sh` layout. |

### 3.7 Removals (requirements 3, 4)

- **`family-wiki` container** + its block in `compose/compose.ai-core.yml`
  (port 8011 freed).
- **`/home/chuck/data/ai-kb/`:** delete `repo/` (wiki), `mkdocs.yml`,
  `processed/`, `failed/`, `embeddings/`, `reports/`. **Keep `raw/`**
  (source files) — rename to `/home/chuck/data/ai-kb/sources/`? (Q4)
- **Old 384-dim `family_kb` collection:** dropped after re-ingest verified.
- **`family_kb_ingest` skill:** retired (Q9).
- **Docs:** `thor_ai_inventory.md`, `thor_data_classification.md`,
  `thor_skill_architecture.md`, root README — wiki + old pipeline refs.

### 3.8 Qdrant exposure (D9 — revisit now)

Proposal: un-publish 6333 from 0.0.0.0 → bind `127.0.0.1:6333` (host
scripts keep working; containers use the docker network; LAN exposure
gone). Low risk, real improvement. (Q7)

### 3.9 Backup strategy

- `scripts/backup-kb.sh`: Qdrant snapshot (`family_kb`) + optional source
  tar → `/home/chuck/data/backups/kb/` (same layout as memory backups).
- `kb_backup` MCP tool for LLM-triggered snapshots.
- Sources themselves live on disk (`ai-kb/raw` or media/workspace) —
  optionally included in the backup tar (Q6).

---

## 4. Phased plan

### K0. Discovery + decisions — **DONE (2026-08-28)**
- [x] Inventory memory state (Phase 9 complete, RBAC live)
- [x] Inventory old KB (collections, points, skill, wiki, on-disk data)
- [x] markitdown capability review (tables/images/vision/plugins)
- [x] This plan + questions to owner

### K1. Qdrant foundation
- [ ] New Qdrant API key: rw `family_kb` only (verify 403 on
      `mem0_memories` + create_collection)
- [ ] Drop 384-dim `family_kb`; recreate 768-dim Cosine
- [ ] Re-ingest the 3 real source docs (pet-care, house maintenance,
      auto detailing) with the new payload schema
- [ ] Verify: old points gone, 3 docs searchable, mem0 untouched
      (count + auth matrix unchanged)

### K2. mcp_knowledge v2 — read tools
- [ ] Real vector `kb_search` (embed query via LiteLLM `embeddings`;
      hybrid keyword fallback; `kb` tag filter)
- [ ] `kb_get_document`, `kb_list_documents`, `kb_overview`,
      `kb_recent_changes` (fixed)
- [ ] Container: read-only key stays for reads; image rebuild
- [ ] E2E via LiteLLM MCP (raw JSON-RPC probe): search quality on the
      3 migrated docs

### K3. Ingestion — files
- [ ] markitdown integration (`[pdf,docx,pptx,xlsx,all]` as needed) +
      pymupdf page pass + chunking/pagination (§3.4)
- [ ] `kb_ingest_file`, `kb_add_fact`, `kb_delete_document`
- [ ] Batched embedding (32/batch via LiteLLM)
- [ ] E2E: ingest a real multi-page PDF; **1000-page PDF timing test**
      (owner fixture — Q2); re-ingest idempotency (sha256)
- [ ] LiteLLM MCP timeout 7200 for mcp_knowledge

### K4. Images + tables + vision
- [ ] Verify vision model accepts image input (Q1) — matrix-coder or alt
- [ ] markitdown-ocr plugin eval (LiteLLM as llm_client) vs page-render
      splice fallback; pick one, implement
- [ ] Standalone image ingestion (EXIF+OCR+vision description)
- [ ] E2E: owner's table/image PDF fixture (Q2) — tables come out as
      markdown tables; image pages get descriptions; warnings surface

### K5. Forget / correct
- [ ] `kb_forget` (two-step semantic delete) + `kb_correct`
      (supersede) + superseded filtering in `kb_search`
- [ ] E2E: "forget that fact" round-trip; correction round-trip;
      confirm-gate negative test (no delete without confirm)

### K6. Backup + removals + docs
- [ ] `kb_backup` tool + `scripts/backup-kb.sh` + restore test
      (throwaway Qdrant, like memory's)
- [ ] Remove `family-wiki` container + compose block (owner restarts
      ai-core stack)
- [ ] Clean `/home/chuck/data/ai-kb/` (keep sources per Q4)
- [ ] Retire `family_kb_ingest` skill
- [ ] Docs: README, thor_ai_inventory, thor_data_classification,
      thor_skill_architecture, memory IMPLEMENTATION_STATE (D6 closed,
      D9 resolved)

### K7. Verification + handoff
- [ ] Memory isolation: full `scripts/memory-regression.sh` 70/70 after
      all KB work; mem0 counts unchanged
- [ ] Auth matrix: KB key 403 on mem0_memories; read-only key 403 on
      KB writes; no-key 401
- [ ] No secrets in payloads/logs; no internal leakage
- [ ] Update this file + commit; handoff notes

---

## 5. Questions for the owner

| # | Question | Proposal |
|---|---|---|
| Q1 | **Vision model:** is `matrix-coder` (qwen38-27b) actually vision-capable (accepts image input via vLLM)? If not, which alias should be the vision model? (K4 is gated on this.) | Verify empirically in K4 with a 1-image probe; fallback = page-render + whichever alias has VL |
| Q2 | **Test fixtures:** which PDF with tables/images should be the E2E fixture, and where is the ~1000-page PDF? (Both on Thor or laptop?) | Any 2–3 real docs; the 1000-pager for the pagination timing test |
| Q3 | **One collection + `kb` tag** vs multiple collections (family_kb, homelab_kb, …)? | One collection, tag field (simpler; `kb_overview` groups by tag) |
| Q4 | **Source file location:** keep `ai-kb/raw/` as-is, rename to `ai-kb/sources/`, or no canonical location (LLM passes any readable path)? | Keep `raw/` (it works); new ingests record whatever path the LLM passes |
| Q5 | **Migrate the 3 existing real docs** (pet-care, house maintenance, auto detailing) from their markdown sources? | Yes — they're the only real KB content today |
| Q6 | **Backup scope:** Qdrant snapshot only, or also tar the source files? Where? | Snapshot + optional `include_sources` tar → `/home/chuck/data/backups/kb/` |
| Q7 | **Qdrant 0.0.0.0:6333 (D9):** bind to 127.0.0.1 now? (Host scripts unaffected; LAN exposure removed.) | Yes |
| Q8 | **Chat auto-retrieval from KB:** should Siri auto-retrieve KB chunks (like memory), or only via explicit `kb_search` tool calls? | v1: tool-only (keeps memory/KB orthogonal); hybrid later |
| Q9 | **`family_kb_ingest` skill:** retire it (LLM uses MCP tools directly), or keep as a thin wrapper (e.g., for scheduler jobs)? | Retire |
| Q10 | **Old wiki data:** confirm delete `ai-kb/repo/`, `mkdocs.yml`, `processed/`, `failed/`, `embeddings/`, `reports/` (keep `raw/`)? | Yes, per requirement 3/4 |

---

## 6. Rollback & failure modes

- **Bad ingest:** deterministic point IDs → re-ingest overwrites;
  `kb_delete_document` removes a whole doc; Qdrant snapshot before
  destructive ops (K1/K6 run `kb_backup` first).
- **Vision model absent/broken:** pipeline degrades to text-only +
  warnings (ingest never fails on vision).
- **markitdown format gap:** `kb_ingest_file` returns a structured error
  + the file is untouched (no partial state — upserts are per-doc).
- **1000-page timeout:** page-by-page processing + batched embedding
  keeps memory flat; LiteLLM MCP timeout 7200; if still too long,
  split at page boundaries into 2 docs (owner-visible warning).
- **Memory contamination:** impossible by construction (separate
  collection + scoped key); K7 regression proves it.
- **Rollback K1:** snapshot of old 384-dim collection taken before drop
  (kept in backups dir until K7 passes).

---

## 7. Explicitly NOT in scope

- Memory changes (mem0, skill-runner memory code) — read-only observer.
- Hybrid memory+KB retrieval (future workstream).
- Multi-user KB scoping (household-shared by design).
- OCR quality tuning beyond the vision fallback.
- KB ingestion of URLs/web content (files + facts only; crawl4ai stays
  separate).
- Qdrant TLS (D9 is exposure-only; TLS is a separate hardening item).
- Analytics/visits/status-panel workstreams (blog project).