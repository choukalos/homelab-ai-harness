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

- `household=true` — family-shared facts (wife's medical status, kids, pets,
  shared projects). Visible to all family users.
- `importance='high'` — critical facts (medical conditions, allergies, key
  dates).
- Facts are stored under the **caller's own identity** — never write on
  behalf of another user.

## Research-note convention

When substantive research is finished in pi (medical, technical deep-dive,
decision support), store the outcome — otherwise it lives only in the
session. Call `memory_remember` with a structured note at
`importance='high'`:

```
Research on <topic> (<YYYY-MM-DD>): <2-4 key findings>. Sources: <...>.
```

Family-relevant research (e.g. the wife's medical condition) → also
`household=true`.

## Medical-reference convention (KB)

Evolving reference-grade medical material belongs in the **`kb_medical`** KB
domain, not memory — memory is add-only, the KB supports correction:

- Diagnosis, symptoms, treatment, doctor/clinic, vet, next appointment →
  `kb_add_fact(kb="medical", ...)` (the collection is created on the fly).
- Status change (new appointment, updated diagnosis) →
  `kb_correct(kb="medical", old_query=..., new_text=...)`.
- Outdated or wrong → `kb_forget(kb="medical", ...)`.
- Conversational medical facts ("the appointment moved to Tuesday") →
  `memory_remember(household=true)` instead.

## Provenance

When citing a retrieved fact, surface its source + date so the user can
trust and correct it ("per your chat on 2026-09-02…").

## Example

```
/skill:memory-conventions — review the memory conventions (force-loads this skill)
```