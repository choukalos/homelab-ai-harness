---
name: session-memory
description: Use at the start of any substantive session and before ending one — fetches relevant long-term memory and captures durable session outcomes.
---

# Session Memory

Use long-term memory at session start and close out durable facts at session
end. Works on any pi connected to the litellm gateway (homelab and Mac).
This skill only calls `mcp_memory` / `mcp_knowledge` tools — it never touches
services.

## Session start

Trigger: the first substantive request of a new session, or
`/skill:session-memory` (force-load).

1. Call `memory_search` for the topic(s) the user is working on
   (top_k 5–10).
2. If the session touches family, health, or projects, also run `kb_search`
   (use `kb_medical` for medical) per `memory-conventions`.
3. Surface retrieved context briefly, with provenance ("per your note
   2026-11-02…"). If nothing relevant came back, say "no relevant memory
   found". Never fabricate memory.

## During the session

Defer to the `memory-conventions` skill for all `memory_remember` and KB
rules — when to remember, private vs `household`, research notes, the
medical reference split. Do not duplicate those rules here.

### Voice notes / personal transcriptions

After transcribing a personal voice note (medical, family, personal), follow
`memory-conventions`:

- Evolving reference material → `kb_medical`.
- Durable facts → `memory_remember`.
- **Default scope: private to the caller.** `household=true` only if the
  user explicitly says the family should know.
- Never auto-upload raw transcript text to memory — store distilled facts
  only.

## Session closeout

Trigger: the user ends the session, or says "wrap up" / "close out".

1. If durable outcomes occurred (decisions, new facts, completed work worth
   remembering), call `memory_remember` with **1–3 distilled facts**
   (`importance='high'` for medical / key dates).
2. If nothing durable: do nothing — no noise writes.
3. Offer (don't do): "Want me to sync this session transcript to the
   homelab? (`session-sync` skill)" — only if the `session-sync` skill is
   installed.

## Constraints

- No raw transcript content in memory facts — distilled facts only.
- No writes on behalf of another identity — facts are stored under the
  caller's own identity.
- Respect the no-restart / no-reboot standing rules — this skill never
  touches services.