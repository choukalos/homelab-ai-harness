# Family KB / Knowledge MCP — Rebuild Plan

> Planning doc for the KB/knowledge workstream (post-memory-project).
> Companion to `blog-todo.md` style: discovered state → decisions → phases → questions.
> Owner: chuck. Last updated: 2026-08-28 (K0 discovery + owner decision rounds 1–2 locked).

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
| Collection | `mem0_memories` (768) | **`kb_*` collections** (on-the-fly, 768) | No — separate, prefix-isolated |
| Qdrant key | JWT (rw `mem0_memories` only) | **new `KB_API_KEY` JWT, global `m`, code-enforced `kb_` prefix** | No — separate credential (see note below) |
| Engine | mem0 in skill-runner | mcp_knowledge container | No |
| Identity | per-user (`chuck`/`service`) | **no user_id — household-shared** | No |
| Write path | auto-extraction from chat | **explicit LLM tool calls only** | No |
| Read path | auto pre-request retrieval | **`kb_search` MCP tool — available to ANY AI using LiteLLM** (`allow_all_keys: true`, confirmed in `litellm/config.yml`) | No (v1) |
| Embeddings | `homelab-embedding-v1` (nomic 768) | `embeddings` (same backend, per D7) | Compatible |

**KB key design (consequence of on-the-fly collections, Q3):** per-collection
JWT scoping can't cover collections created later, so `KB_API_KEY` is a
global-`m` JWT (`sub=mcp-knowledge`, no expiry, via
`scripts/qdrant-jwt.py --global-access m`). The **code enforces the `kb_`
collection prefix on every Qdrant operation** (read/write/create/delete/
snapshot) — the key is broader than the code will ever use. Accepted risk
(documented): a code bug *could* reach `mem0_memories` with this key.
Mitigations: strict prefix allowlist + unit tests, and a **K7 audit-log
check** that no `sub=mcp-knowledge` operation ever touches
`mem0_memories` (Qdrant 1.18 audit logging).

**Semantic boundary (to document):** memory = *who we are / what we
prefer*, learned from conversation, per-person. KB = *what we know / what
we filed*, explicit documents + facts, household-shared. A fact can live in
both (accepted; dedup awareness is a future workstream).

**v1 rule: chat does NOT auto-retrieve from the KB.** Retrieval happens
via the `kb_search` MCP tool, which is registered in LiteLLM with
`allow_all_keys: true` — so **any AI using LiteLLM** (Siri, OWUI, pi, any
channel) can query the KB (owner decision, Q8). Write tools are likewise
callable by any LiteLLM key (per-key MCP restrictions are deferred to
Phase 14) — accepted; ops are idempotent + timestamped (`kb_recent_changes`).

### 3.2 Ingestion model — the LLM is the operator

No watcher, no watched dir, no pipeline directories. Two entry points:

- **Files:** LLM has a path → calls `kb_ingest_file(path, kb, ...)` →
  server converts (markitdown), chunks with pagination, embeds (batched
  via LiteLLM), upserts. Returns `{doc_id, pages, chunks, sha256,
  warnings[]}`.
- **Canonical drop point (owner, Q4):** `/home/chuck/data/ai-kb/raw/` —
  the owner uploads/drops files there (Thor). The LLM may also pass any
  other Thor-readable path (media/, workspace/). Files on other machines:
  owner copies them to Thor first (v1, see N3).
- **Facts:** LLM calls `kb_add_fact(text, kb, ...)` — single fact, stored
  verbatim (`kind=fact`). Also the vehicle for **vision output**: the LLM
  reads an image (via a vision model), then stores the description/table
  as a fact tied to the source.

**Where the code lives:** `mcp_knowledge` becomes the full KB server
(convert + embed + Qdrant rw). Rationale: "LLM uses the tooling" = MCP
tools; single container; no skill-runner dependency for KB ops.
Tradeoffs accepted: container image gets `markitdown[all]` + `pymupdf`
(deps, ~50 MB); container gets the **`KB_API_KEY` JWT** (§3.1) + ro mounts
of `/home/chuck/data/ai-kb/raw` + `/home/chuck/data/media` +
`/home/chuck/workspace` (source access). Same trust model as mcp_mysql
(write-protected user): code + prefix allowlist are the guardrails.

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
- Vision model (owner-confirmed, Q1): **`matrix-coder` is vision-capable —
  up to 5 images and/or 1 video per turn.** Page-render fallback uses
  image input; ≤5 pages per vision call (batch larger sets across turns).

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

- **Multiple collections, one per KB, created on the fly by the LLM**
  (owner Q3: gaming / family / household / cars / guitar / side-biz
  projects / … — "organized on the fly by the LLM").
- **Naming:** `kb_<slug>` — the LLM passes a friendly `kb` name
  ("Side Biz Project Blah") → server slugifies → `kb_side_biz_blah`
  (lowercase, `[a-z0-9_]`). Prefix `kb_` is the isolation boundary
  (enforced on every operation; see §3.1 key design). Examples:
  `kb_gaming`, `kb_family`, `kb_household`, `kb_cars`, `kb_guitar`,
  `kb_side_biz_blah`.
- **On-the-fly creation:** `kb_ingest_file` / `kb_add_fact` create the
  collection if missing (768-dim, Cosine) — no pre-provisioning.
- **Manifest point:** each collection carries one special point
  (`kind=manifest`, deterministic ID, `text` = short KB description). The
  description is **required when a new KB is created** (owner N4): the
  user or the LLM supplies context for the KB name + a collection summary
  at creation — the server rejects a first write to a missing `kb_<slug>`
  without a `description` (the LLM derives it from the user's request or
  asks the user). Manifest points are filtered out of `kb_search` results.
- **Old 384-dim `family_kb` collection: dropped, NOT migrated** (owner
  Q5: "no, drop them"). Snapshot taken first (rollback safety), then
  dropped. Wiki index pages + the 3 old docs: gone forever.

```
text          chunk text (markdown)
kind          doc | fact | image | table | manifest
source        file path or "fact:<slug>"
chunk_index   int
page_range    [int, int] | null
sha256        source file hash (docs) | null
ingested_at   iso8601
updated_at    iso8601
superseded_by point_id | null   (corrections, see 3.6)
```

(The `kb` tag field is gone — the collection name IS the KB.)

Deterministic point IDs: `sha256(source + ":" + chunk_index)` → re-ingest
is idempotent upsert; deletes are exact. (ID space is per-collection, so
the same source in two KBs is fine.)

### 3.6 Toolset — mcp_knowledge v2 (~11 tools)

All tools take `kb` as a **friendly name** (server slugifies + validates
the `kb_` prefix). Omitted `kb` where sensible = all KBs (`kb_search` /
`kb_forget` search across all `kb_*`). Registered in LiteLLM with
`allow_all_keys: true` → available to **any AI using LiteLLM** (Q8).

**Read (fixed/kept):**
| Tool | Notes |
|---|---|
| `kb_search(query, top_k=5, kb?)` | **real vector search** (embed via LiteLLM `embeddings`); hybrid keyword fallback; searches all `kb_*` (or one); filters manifest + superseded; returns snippets + `page_range` + `source` + `kb` |
| `kb_get_document(source, kb)` | all chunks of a doc, ordered |
| `kb_list_documents(kb?)` | per-doc metadata (source, pages, chunks, sha, ingested_at) |
| `kb_recent_changes(days=7)` | kept (now has real timestamps), across all `kb_*` |

**High-level (requirement 6):**
| Tool | Notes |
|---|---|
| `kb_overview()` | "what KBs do I have": every `kb_*` collection — manifest description, doc count, chunk count, total size, last ingested. The LLM's map of the KB. |

**Write (new — requirement 4, 7):**
| Tool | Notes |
|---|---|
| `kb_ingest_file(path, kb, description?)` | markitdown pipeline (§3.3/3.4); creates `kb_<slug>` if missing — **`description` required on new-KB creation** (manifest, N4); long-running; returns doc_id + stats + warnings |
| `kb_add_fact(text, kb, description?)` | verbatim fact; also stores vision-model output; `description` required on new-KB creation (manifest, N4) |
| `kb_delete_document(source)` | remove all chunks for a source |
| `kb_forget(query, confirm=false)` | **two-step**: default returns semantic matches (ids + snippets, nothing deleted); `confirm=true` + `ids` deletes. "forget that fact" |
| `kb_correct(old_query, new_text, kb?)` | finds the old fact/chunk (top-1, must exceed score gate), marks `superseded_by`, stores new text as new point; `kb_search` filters superseded. "it should be this instead" |

**Backup (requirement 8):**
| Tool | Notes |
|---|---|
| `kb_backup()` | Qdrant snapshot of all `kb_*` collections → `/home/chuck/data/backups/kb/` (+ optional `tar` of source files if `include_sources=true`). Mirrors `backup-memory.sh` layout. |

### 3.7 Removals (requirements 3, 4)

- **`family-wiki` container** + its block in `compose/compose.ai-core.yml`
  (port 8011 freed). Owner restarts the ai-core stack.
- **`/home/chuck/data/ai-kb/`:** delete **everything except `raw/`**
  (owner Q10: "delete everything else other than the raw/ ingestion
  point") — i.e. `repo/` (wiki), `mkdocs.yml`, `processed/`, `failed/`,
  `embeddings/`, `reports/`. `raw/` stays as the canonical ingestion drop
  point (owner will drop sample PDFs/images there for E2E).
- **Old 384-dim `family_kb` collection:** snapshot → drop (no migration).
- **`family_kb_ingest` skill:** retired + deleted (owner Q9).
- **Docs:** `thor_ai_inventory.md`, `thor_data_classification.md`,
  `thor_skill_architecture.md`, root README — wiki + old pipeline refs.

### 3.8 Qdrant exposure (D9 — owner decision: LEAVE for now)

Owner (Q7): other services/tooling use the Qdrant endpoint — leave the
0.0.0.0:6333 publication as-is for now. D9 stays open as a future
hardening item (not a K-phase).

### 3.9 Backup strategy

- `scripts/backup-kb.sh`: Qdrant snapshot (all `kb_*`) + optional source
  tar → `/home/chuck/data/backups/kb/` (same layout as memory backups).
- `kb_backup` MCP tool for LLM-triggered snapshots.
- Sources themselves live on disk (`ai-kb/raw` or media/workspace) —
  optionally included in the backup tar (Q6).

---

## 4. Phased plan

> **Ordering (owner, 2026-08-28):** the **`mcp_vision` image/video
> analysis MCP tool** (N2 — separate workstream, built from the owner's
> `video-analyze` pi skill; planning doc `mcp-vision-todo.md`) is built
> **before** KB K1 starts. Rationale: it validates the `matrix-coder`
> vision path end-to-end (the Q1 "≤5 images/turn" probe) and K4 reuses
> the proven pattern/client.

### K0. Discovery + decisions — **DONE (2026-08-28)**
- [x] Inventory memory state (Phase 9 complete, RBAC live)
- [x] Inventory old KB (collections, points, skill, wiki, on-disk data)
- [x] markitdown capability review (tables/images/vision/plugins)
- [x] This plan + questions to owner

### K1. Qdrant foundation
- [ ] Issue `KB_API_KEY` JWT (global `m`, `sub=mcp-knowledge`, no expiry)
      via `scripts/qdrant-jwt.py --global-access m`; store in `.env`
- [ ] Verify empirically: create throwaway `kb_test` collection with it;
      confirm `kb_` prefix code-gate works; confirm it CANNOT be narrowed
      (document why global-`m` is required); drop `kb_test`
- [ ] Snapshot old 384-dim `family_kb` (rollback safety) → drop it
      (no migration, owner Q5)
- [ ] Verify: mem0 untouched (counts + auth matrix unchanged), memory
      regression suite still green

### K2. mcp_knowledge v2 — read tools
- [ ] Real vector `kb_search` (embed query via LiteLLM `embeddings`;
      hybrid keyword fallback; multi-`kb_*` search; manifest/superseded
      filters)
- [ ] `kb_get_document`, `kb_list_documents`, `kb_overview` (all `kb_*`
      + manifest descriptions), `kb_recent_changes` (fixed)
- [ ] Container: `KB_API_KEY` env + `kb_` prefix enforcement on every
      Qdrant op; image rebuild; ro mounts (ai-kb/raw, media, workspace)
- [ ] E2E via LiteLLM MCP (raw JSON-RPC probe): create a test KB, add a
      fact, search it back

### K3. Ingestion — files (gated on owner fixtures in `ai-kb/raw/`)
- [ ] markitdown integration (`[pdf,docx,pptx,xlsx]` + base) +
      pymupdf page pass + chunking/pagination (§3.4)
- [ ] `kb_ingest_file` (on-the-fly collection + manifest), `kb_add_fact`,
      `kb_delete_document`
- [ ] Batched embedding (32/batch via LiteLLM)
- [ ] E2E: owner's sample files from `ai-kb/raw/` (owner will drop PDFs/
      images/etc there); multi-page PDF; **1000-page PDF timing test**
      (if owner provides one); re-ingest idempotency (sha256)
- [ ] LiteLLM MCP timeout 7200 for mcp_knowledge

### K4. Images + tables + vision
- [ ] Vision: `matrix-coder` (owner-confirmed: ≤5 images and/or 1 video
      per turn) via LiteLLM image input; ≤5 pages per vision call
- [ ] markitdown-ocr plugin eval (LiteLLM as llm_client) vs page-render
      splice fallback; pick one, implement
- [ ] Standalone image ingestion (EXIF+OCR+vision description) from
      `ai-kb/raw/` samples
- [ ] E2E: owner's table/image fixtures — tables come out as markdown
      tables; image pages get descriptions; warnings surface

### K5. Forget / correct
- [ ] `kb_forget` (two-step semantic delete) + `kb_correct`
      (supersede) + superseded filtering in `kb_search`
- [ ] E2E: "forget that fact" round-trip; correction round-trip;
      confirm-gate negative test (no delete without confirm)

### K6. Backup + removals + docs
- [ ] `kb_backup` tool + `scripts/backup-kb.sh` + restore test
      (throwaway Qdrant, like memory's); scope: snapshot of all `kb_*`
      + optional source tar (owner Q6: yes)
- [ ] Remove `family-wiki` container + compose block (owner restarts
      ai-core stack)
- [ ] Clean `/home/chuck/data/ai-kb/` — delete everything except `raw/`
      (owner Q10)
- [ ] Retire + delete `family_kb_ingest` skill (owner Q9)
- [ ] Docs: README, thor_ai_inventory, thor_data_classification,
      thor_skill_architecture, memory IMPLEMENTATION_STATE (D6 closed,
      D9 left open per owner)

### K7. Verification + handoff
- [ ] Memory isolation: full `scripts/memory-regression.sh` 70/70 after
      all KB work; mem0 counts unchanged
- [ ] Code-gate proof: unit tests + live probe that mcp_knowledge rejects
      any non-`kb_` collection (incl. `mem0_memories`) at the tool layer;
      **Qdrant audit-log scan: zero `sub=mcp-knowledge` operations on
      non-`kb_` collections** (the KB key is global-`m` by necessity —
      §3.1 — so the code gate is the boundary; the audit log proves it)
- [ ] Auth matrix: read-only key 403 on KB writes; no-key 401; memory
      JWT still 403 on `kb_*` (unchanged)
- [ ] No secrets in payloads/logs; no internal leakage
- [ ] Update this file + commit; handoff notes

---

## 5. Decisions log (owner, 2026-08-28) + open questions

### Round 1 — answered (locked)

| # | Decision |
|---|---|
| Q1 | **`matrix-coder` IS the vision model** — up to **5 images and/or 1 video per turn**. |
| Q2 | Test fixtures: owner will **drop sample PDFs/images/etc into `ai-kb/raw/`** on Thor (K3/K4 E2E is gated on that). |
| Q3 | **Multiple collections**, one per KB, **created on the fly by the LLM** (gaming / family / household / cars / guitar / side-biz projects / …). → `kb_<slug>` naming, §3.5. |
| Q4 | **`/home/chuck/data/ai-kb/raw/` = canonical ingestion drop point** (Thor); LLM may pass any other Thor-readable path; other machines → copy to Thor first (v1). |
| Q5 | **Old 3 docs: NO migration — drop them** (snapshot first, then drop the 384-dim collection). |
| Q6 | Backup: **Qdrant snapshot of all `kb_*` + optional source tar → `/home/chuck/data/backups/kb/`** — approved. |
| Q7 | **Qdrant 0.0.0.0:6333 stays as-is for now** (other services/tooling use it). D9 remains open, not a K-phase. |
| Q8 | **Chat retrieval via MCP tools for ANY AI using LiteLLM** — `mcp_knowledge` is already registered `allow_all_keys: true` (confirmed); no change needed, all kb tools (incl. writes) are LiteLLM-wide. |
| Q9 | **`family_kb_ingest` skill: retire + delete** ("not needed anymore"). |
| Q10 | **Delete everything in `ai-kb/` except `raw/`** ("I'll drop sample pdfs/images/etc to ingest in that raw/ folder"). |

### Round 2 — answered (locked 2026-08-28)

| # | Decision |
|---|---|
| N1 | **`kb_<slug>` naming: yes.** No KB rename/merge in v1 (re-ingest into a new name): **yes, acceptable.** |
| N2 | **Video files: NOT a KB ingest format.** Handled by the **`mcp_vision` MCP tool** (separate workstream, `mcp-vision-todo.md`) built from the owner's `video-analyze` pi skill. Owner wants it built **before** the KB update (it also de-risks K4's vision path). See §4 note. |
| N3 | **Default stands:** v1 requires files readable on Thor (`ai-kb/raw/`, media/, workspace/). |
| N4 | **New-KB creation requires context:** the user or the LLM provides the KB name context + a collection summary (manifest description) when a new `kb_<slug>` is created; `description` is mandatory on first write to a new KB. |

### Round 3 — open

(none — all questions resolved; remaining unknowns are implementation details,
not owner decisions)

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
- **Memory contamination:** prevented by construction (separate
  `kb_*`-prefix collections; code-gated key; no shared identity) — the
  KB key is global-`m` by necessity (§3.1), so the code gate is the
  boundary; K7 regression + audit-log scan prove it.
- **Rollback K1:** snapshot of old 384-dim collection taken before drop
  (kept in backups dir until K7 passes).

---

## 7. Explicitly NOT in scope

- Memory changes (mem0, skill-runner memory code) — read-only observer.
- Hybrid memory+KB retrieval (future workstream).
- Multi-user KB scoping (household-shared by design).
- **Video file ingestion into the KB** (N2: out — video/image *analysis*
  is the `mcp_vision` workstream, built first).
- KB rename/merge/repurpose tools (re-ingest into a new name; v1).
- OCR quality tuning beyond the vision fallback.
- KB ingestion of URLs/web content (files + facts only; crawl4ai stays
  separate).
- Qdrant TLS + 0.0.0.0 exposure hardening (D9 — owner: leave for now).
- Per-key MCP restrictions (LiteLLM Phase 14).
- Analytics/visits/status-panel workstreams (blog project).