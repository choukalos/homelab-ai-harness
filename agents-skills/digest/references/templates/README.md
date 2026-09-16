# Digest Templates

A **digest** is a structured *model* of a document — not a summary. It captures
the **action-relevant structure** (rules, formulas, tables, beats, components)
with **page/line references**, so a downstream task can be run *from the digest*
and independently **verified** against the source.

## The five templates

| Template | File | Downstream task it enables |
|----------|------|----------------------------|
| `game_system` | `game_system.md` | generate characters, adjudicate combat/skills, DM a game |
| `story` | `story.md` | plot summary, character arcs, thematic analysis, "what happens next" |
| `whitepaper` | `whitepaper.md` | implement the algorithm/idea, reproduce the method |
| `music_theory` | `music_theory.md` | answer theory questions, generate scales/chords, compute |
| `media` | `media.md` | film/TV insight from 3 perspectives (cinematics / entertainment / art critics); refs are timecodes/chapters, not pages |

## How a digest is built (the `digest` skill)

1. **Classify** the type from the TOC + a content sample (LLM judgment).
2. **Read the template** for that type (this directory).
3. **Map-reduce**: use the TOC as the map; read only the TOC-guided pages
   (`kb_get_pages`), not the whole doc.
4. **Fill the template** — every load-bearing claim gets a `page_ref`.
5. **Verify** the load-bearing claims independently (see each template's
   `## Verification`).
6. **Store** via `kb_digest_store` (file = source of truth; section facts go
   into the source doc's KB for `kb_search`).

## Rules that apply to every template

1. **Ground in the source.** Every load-bearing claim carries a `page_ref`
   (PDF page number, or line number for plain text). No ungrounded claims.
2. **Machine-checkable over prose** for procedural domains. Capture rules as
   formulas, patterns, tables, arrays — not "roughly". `[2,2,1,2,2,2,1]` beats
   "whole-whole-half…". A confident-but-wrong digest is indistinguishable from
   a correct one without this.
3. **Capture the *process*, not just the arithmetic.** For games, the
   character-creation *method* (point-buy vs 3d6, the actual costs) is the
   load-bearing claim — not just that HP==ST.
4. **Version-specific details require reading the actual source.** (GURPS
   Revised sets Will=IQ, not the old 4e IQ/2.) Don't rely on possibly-stale
   model knowledge.
5. **`## Downstream Task`** states what the digest is *for* — this focuses the
   digest on capturing the right structure.
6. **`## Verification`** lists the load-bearing claims and the independent
   check for each. Verification is not optional — it's the point.
7. **Lossy is OK.** Capture the action-relevant structure, not everything.
   Out-of-scope tasks fall back to source lookup via `page_refs`.

## Section → fact mapping

`kb_digest_store` splits the digest markdown on `## ` headings. Each `## `
section becomes one searchable fact (`kind=digest`) in the source doc's KB,
sharing a `digest_id`. So **each `## ` section should be a coherent,
self-contained unit** (a field), not a sentence fragment.