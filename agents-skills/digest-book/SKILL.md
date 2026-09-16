---
name: digest-book
description: Analyze a novel/story from a story digest — produce a plot summary, character-arc analysis, and thematic reading. Loads the story digest (built by /skill:digest) and synthesizes the three analyses from its grounded beats, arcs, and themes, citing source page/line refs.
---

# Book / story analyst

Produce a literary analysis *from a `story` digest*. The digest (built by
`/skill:digest`) is the grounded source — its plot beats carry page/line refs,
so every claim is traceable to the text. You synthesize; you don't re-read the
whole book.

## When to use
- "Summarize the plot of <book>."
- "Analyze the character arcs in <book>."
- "What are the themes of <book>?"
- "Write a book report / study guide for <book>."

## Prerequisites
- A `story` digest (`kb_digest_get(slug, "story")`). If none exists, run
  `/skill:digest` on the source text first.

## Workflow
1. **Load the digest**: `kb_digest_get(slug, "story")`. It has: premise,
   setting, characters, plot_beats (ordered, with page/line refs), arcs,
   themes, open_questions.
2. **Plot summary**: walk `plot_beats` in order into a 2-4 paragraph summary.
   Keep it chronological; name the pivotal beats. Cite the source ref for the
   key turning points (e.g. "the climax, p.2682").
3. **Character arcs**: for each major character in `characters`, trace their
   arc using the `arcs` section + the beats they appear in. State the arc in
   one line (e.g. "from X to Y") and ground it in 2-3 beats.
4. **Thematic analysis**: take `themes`, and for each, show *how the text
   supports it* (cite the beats/scenes that embody the theme). Don't just list
   themes — connect them to specific moments.
5. **Open questions / gaps**: surface the digest's `open_questions` (ambiguities,
   unresolved threads) — these make the analysis honest and useful.

## Output shape
A Markdown report with sections:
- **Premise & setting** (1 paragraph).
- **Plot** (chronological summary, with source refs on turning points).
- **Characters & arcs** (per character: role + arc, grounded).
- **Themes** (per theme: claim + textual support).
- **Open questions** (what the text leaves unresolved).
- **Sources** (the digest slug + the underlying source path).

## Grounding rules
- **Every claim traces to a beat/ref in the digest.** If a claim isn't in the
  digest, either read the source page/line to confirm it, or flag it as
  interpretation (not grounded).
- **Interpretation is welcome** (themes, arcs are interpretive) — but label
  interpretation vs. grounded fact.
- **Don't invent plot points.** The digest's beats are the plot; if a beat is
  missing, say so (the digest is lossy).

## Notes
- The digest is the model; this skill reads it and writes the analysis.
- For a deeper pass (e.g. a specific character or theme), read the relevant
  source lines (the digest's `page_refs`) and expand.