---
name: digest
description: Build a structured "digest" (model, not summary) of a document so downstream tasks can be run from it and verified. Classifies the type (game_system/story/whitepaper/music_theory/media), reads TOC-guided pages (or, for media, uses vision frame analysis), fills the template, verifies load-bearing claims, and stores it (file + KB facts).
---

# Digest

Turn a document into a **digest** — a structured *model* of its
action-relevant structure (rules, formulas, tables, beats, components) with
page references — so a downstream task (generate a character, summarize a
plot, implement an algorithm, compute scales) can be run **from the digest**
and **independently verified** against the source.

A digest is **not a summary**. It captures the structure a task depends on,
grounded in the source, and pairs it with verification of its load-bearing
claims. (A confident-but-wrong digest is otherwise indistinguishable from a
correct one.)

## When to use

- "Digest <doc>" / "build a digest of <doc>" / "model <doc> for <task>".
- You need to *do something with* a document (DM a game, implement a paper,
  analyze a book) and want a reusable, verifiable model of it.

## Inputs

- **source**: the document path (host path, e.g.
  `/home/chuck/data/ai-kb/raw/KBTest/Gaming - GURPS_....pdf`). The doc should
  already be ingested into a KB (or at least readable by `mcp_knowledge`).
- **kb** (optional): the KB the source doc lives in (e.g. `gaming`). If the
  doc is ingested, this is known; otherwise pick/create one.
- **type** (optional): force a type instead of classifying
  (`game_system` / `story` / `whitepaper` / `music_theory` / `media`).
- **task** (optional): the downstream task the digest is for — focus the
  digest on capturing the right structure.

## Workflow

### 1. Classify (get the work order)
Call `kb_digest(source)` **without** a type. It returns the TOC/bookmarks, a
content sample, the page count, and `candidate_types`. Read the TOC + sample
and **judge the type** (LLM judgment, not a hardcoded rule):
- `game_system` — rules, character creation, combat, skills (a game book).
- `story` — narrative: premise, characters, plot beats, arcs (a novel).
- `whitepaper` — problem, algorithm, results (a paper).
- `music_theory` — computation rules: scales, chords, intervals (theory).
- `media` — a film/TV episode/clip: plot, characters, cinematics, entertainment
  appeal, artistic merit (video or image). Uses vision analysis, not pages.
If the user gave a `type`, use it. If genuinely ambiguous, ask.

### 2. Read the template
Read `references/templates/<type>.md` (relative to this skill dir). It defines
the sections to fill and the `## Verification` checklist. Also read
`references/templates/README.md` for the cross-template rules.

### 3. Map-reduce the source
Use the TOC as the **map**. Pick the pages that carry the load-bearing
structure (for a game: character creation, combat, key tables; for a paper:
the method/algorithm sections; for a story: the pivotal chapters). Call
`kb_get_pages(source, pages)` for those page numbers (1-based, from the TOC).
Read them. **Do not read the whole doc** — read the TOC-guided pages. If a
page is out of range or the TOC is weak, fall back to `kb_search` +
`kb_get_document` for targeted lookup.

**For `media` (video/image)** there is no TOC/pages. Instead:
1. `vision_extract_frames(source)` → scene chapters + frames + `summary.md` +
   `chapters.json` (the "map" for a video).
2. `vision_analyze_video(source, mode="scene")` → a consolidated storyboard
   report (scene-by-scene visual description).
3. For a single image, `vision_analyze_image(source)`.
Use the scene chapters as the "page refs" (timecodes). Ground claims in
scene/timecode, not PDF pages.

### 4. Fill the template
Produce the digest markdown, filling every section of the template. Rules:
- **Ground every load-bearing claim** with a `page_ref` (PDF page, or line
  number for plain text).
- **Machine-checkable over prose** for procedural domains: formulas, patterns,
  tables, arrays — not "roughly". `[2,2,1,2,2,2,1]` > "whole-whole-half…".
- **Capture the *process*** (for games: the actual character-creation method
  and exact costs), not just derived arithmetic.
- **Version-specific details from the source** (don't rely on possibly-stale
  model knowledge — e.g. GURPS Revised sets Will=IQ).

### 5. Verify the load-bearing claims
Follow the template's `## Verification`. Independently check each load-bearing
claim:
- **Procedural (game/paper/theory)**: run a small computation *from the
  digest alone* and assert the expected result (build a character and check
  the budget/derived stats; implement the core primitive and check shapes;
  generate a scale and check it). This catches a wrong *model*, not just
  inconsistent arithmetic.
- **Narrative (story)**: confirm each plot beat actually occurs in the source
  (re-read the cited line/page).
Report each check as pass/fail. **If a check fails, fix the digest** (re-read
the source) and re-verify — do not ship a failing digest.

### 6. Store
Call `kb_digest_store(slug, type, md, kb, source, page_refs)`:
- **slug**: a short identifier derived from the doc (e.g. `gurps_basic_4e`,
  `time_machine`, `attention_transformer`). Lowercase, `[a-z0-9_-]`.
- **type**: the classified type.
- **md**: the digest markdown.
- **kb**: the source doc's KB (required).
- **source**: the source path.
- **page_refs**: `{section_title: [page, page]}` for the sections you grounded.
This writes the file (source of truth) under
`/home/chuck/data/ai-kb/digests/<type>/<slug>.md` and stores each `## `
section as a searchable fact in the KB.

### 7. Report
Tell the user: the type, the digest file path (host), the KB it's stored in,
the number of sections, and the verification results (pass/fail per
load-bearing claim). Note the lossy boundary (what the digest does *not*
cover) and that out-of-scope tasks fall back to source lookup via `page_refs`.

## Notes

- **Re-digest** overwrites the file and re-embeds the section facts (same
  `digest_id` per slug/type).
- **Digests are lossy** by design — they capture the action-relevant
  structure. If a task needs something the digest doesn't cover, read the
  source page via the `page_refs` (or `kb_get_pages`).
- **`kb_search` finds digest sections** alongside the raw chunks (they share
  the KB), so a later agent can discover the digest by searching.
- **Media digests** use timecodes/chapters (not page numbers) as refs, and the
  three perspectives (cinematics / entertainment / art critics) are stored as
  separate sections — so one digest is queryable from any angle.
- The digest file is written by the `mcp_knowledge` container (runs as root),
  so it's world-readable but root-owned; the skill reads it fine. Delete via
  the container or `sudo` if needed.