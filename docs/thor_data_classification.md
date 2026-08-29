# Thor Data Classification and KB Strategy

> Phase 4.2 — Define data classification rules and knowledge base ingestion policy.
> Date: 2026-07-03 (design baseline)
> Status: **Classification rules still apply.** Current KB reality (2026-08-29):
> the family KB is a set of Qdrant `kb_*` collections (one per domain,
> 768-dim nomic, created on the fly by `mcp_knowledge` v2) plus
> `mem0_memories` (768-dim, skill-runner long-term memory). Ingestion is
> LLM-driven via `kb_ingest_file` / `kb_add_fact` (canonical drop point
> `/home/chuck/data/ai-kb/raw/`); backups via `scripts/backup-kb.sh`.
> Legacy `family_kb` (384-dim) and the `family_kb_ingest` skill were
> retired 2026-08-29 (snapshotted + dropped). See `mcp/servers/knowledge/README.md`.

---

## Core Principle

**The KB is curated-only. Nothing enters the KB without explicit approval.**

Automatic ingestion of family data, financial documents, or historical archives is strictly prohibited until the pipeline is proven reliable.

---

## Data Classification

| Class | Description | Examples | KB Eligible |
|---|---|---|---|
| **Public** | Non-sensitive, freely shareable | Blog posts, public docs, weather data | Yes |
| **Family Curated** | Approved family knowledge | Family recipes, event summaries, approved photos | Yes (manual) |
| **Homelab Curated** | Approved homelab documentation | Config notes, runbooks, architecture docs | Yes (manual) |
| **Finance Curated** | Approved financial data | Curated investment notes, tax summaries | Yes (manual) |
| **Coding Curated** | Approved project knowledge | Architecture docs, API specs, coding standards | Yes (manual) |
| **Private** | Sensitive, never auto-ingested | Passwords, keys, PII, medical records | No |
| **Raw** | Unprocessed source data | NAS shares, home folders, raw media, historical archives | No |

---

## Ingestion Rules

### Approved Path

```
User manually selects files → files are embedded and indexed into the appropriate Qdrant collection
```

- Only files explicitly chosen by Chuck are ingested.
- Ingestion happens through CLI or a manual workflow.
- Chuck reviews and approves before embedding.

### Forbidden Paths

Do **not** auto-ingest:

- Lego home folders (`/home/*`)
- Lego Share folder (`/share/*`)
- Financial documents (raw statements, tax forms)
- Raw multimedia files (photos, videos, music)
- Historical personal archives
- Anything on the NAS without explicit approval

---

## Qdrant Collections

| Collection | Data Class | Description |
|---|---|---|
| `family_curated` | Family Curated | Family knowledge: recipes, events, notes, approved photos |
| `homelab_curated` | Homelab Curated | Homelab documentation, runbooks, config notes |
| `finance_curated` | Finance Curated | Investment research summaries, tax notes (curated) |
| `coding_curated` | Coding Curated | Project architecture, API docs, coding standards |
| `private_curated` | Private | Sensitive but approved knowledge (never exposed to non-admin channels) |

### Collection Access by Channel

| Collection | Open WebUI | CLI | Siri | llm.choukalos.com | PI | Portal |
|---|---|---|---|---|---|---|
| `family_curated` | Read | Read/Write | — | — | — | Read |
| `homelab_curated` | Read | Read/Write | — | — | Read | Read |
| `finance_curated` | — | Read/Write | — | — | — | — |
| `coding_curated` | Read | Read/Write | — | — | Read | — |
| `private_curated` | — | Read/Write | — | — | — | — |

---

## Embedding Strategy

- Embedding model: `local/embed` (runs on Matrix)
- Embeddings stored in Qdrant
- Each document chunk includes metadata: `source`, `collection`, `ingested_by`, `ingested_at`
- No automatic re-embedding of existing data

---

## Future Work

- Automated ingestion pipeline (after curated pipeline is proven reliable)
- Incremental updates for curated collections
- Deletion/rotation policies
- Permission-aware retrieval (channel can only query collections it has access to)

All ingestion improvements are future work. Current policy: **manual only**.
