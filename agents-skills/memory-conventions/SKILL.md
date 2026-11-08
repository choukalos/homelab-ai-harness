---
name: memory-conventions
description: Family long-term memory conventions — when to search or remember facts via mcp_memory, and when to use the mcp_knowledge KB (research notes, medical reference)
---

# Memory Conventions

Conventions for the family's long-term memory. Two stores, different jobs:

| Store | Tools | Use for | Mutability |
|---|---|---|---|
| **memory** (`mcp_memory`) | `memory_search`, `memory_list`, `memory_remember` | Durable conversational facts — personal (private) or family-shared (`household=true`) | Add-only (new statements supersede old ones) |
| **KB** (`mcp_knowledge`) | `kb_search`, `kb_add_fact`, `kb_correct`, `kb_forget` | Reference-grade material that evolves — medical reference, docs, digests | Correctable + forgettable |

## When to `memory_search`

- At the start of a conversation about a known topic (family, health,
  projects, preferences, key dates) — retrieve before asking the user.
- When the user references the past ("last time", "the thing about …",
  "what did we decide").
- Household (family-shared) facts are already merged into every user's
  search results — no extra step.

## When to `memory_remember`

Call `memory_remember` when the user shares durable personal information
worth keeping across sessions and machines:

- Health/medical updates, family matters, projects, preferences, key dates.
- An explicit "remember this: …".

Parameters:

- `household=true` — family-shared facts (kids, pets, shared projects).
  Visible to all family users.
- `importance='high'` — critical facts (medical conditions, allergies, key
  dates).
- Facts are stored under the **caller's own identity** — never write on
  behalf of another user.
- **Personal medical facts** (wife's condition, Chuck's own health, diagnoses,
  symptoms, treatments, appointments) → `memory_remember` **PRIVATE**
  (`household=false`), `importance='high'` — never in the family KB.

## Research-note convention

When substantive research is finished in pi (medical, technical deep-dive,
decision support), store the outcome — otherwise it lives only in the
session. Call `memory_remember` with a structured note at
`importance='high'`:

```
Research on <topic> (<YYYY-MM-DD>): <2-4 key findings>. Sources: <...>.
```

Medical research on a family member (e.g. the wife's condition) defaults to
**PRIVATE to the caller** (`household=false`); `household=true` only when the
user explicitly says the family should know.

## Medical-reference convention (KB)

The **`kb_medical`** KB is for **non-personal reference material only** —
disease/drug info, research findings, general medical reference. The KB is
family-shared with **no per-user scoping**, so personal or identifiable
medical content (a specific person's condition, diagnosis, symptoms,
treatment, appointments) must not go there. Evolving reference-grade material
belongs in the KB, not memory — memory is add-only, the KB supports
correction:

- Disease/drug info, research, general reference →
  `kb_add_fact(kb="medical", ...)` (the collection is created on the fly).
- Reference correction (updated guideline, corrected drug info) →
  `kb_correct(kb="medical", old_query=..., new_text=...)`.
- Outdated or wrong reference → `kb_forget(kb="medical", ...)`.
- Personal medical facts (a family member's or your own condition,
  diagnoses, symptoms, treatments, appointments) → `memory_remember`
  PRIVATE (`household=false`), `importance='high'` instead.

## Voice notes / personal transcriptions

After transcribing a personal voice note (medical, family, personal):

- Store **distilled durable facts** via `memory_remember` — private to the
  caller, `importance='high'` for medical.
- **Never store raw transcript text** in memory or the KB — distilled facts
  only.
- Offer `session-sync` (if installed) to ship the raw transcript to the
  homelab — user-initiated, never automatic.

## Provenance

When citing a retrieved fact, surface its source + date so the user can
trust and correct it ("per your chat on 2026-09-02…").

## Example

```
/skill:memory-conventions — review the memory conventions (force-loads this skill)
```