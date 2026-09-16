# agents-skills — pi-native skills

Pi-native skills for the family agent. Each skill is a `SKILL.md` (workflow
guide) that pi discovers from this directory (the `skills` entry in
`~/.pi/agent/settings.json`) and exposes as a `/skill:<name>` command
(`enableSkillCommands: true`).

**These are agent-driven workflows, not skill-runner jobs.** The agent reads
the SKILL.md and does the work (calling MCP tools, running scripts, reading
files). They are distinct from the skill-runner skills in `/home/chuck/homelab/skills/`
(`skill.yml`, one-shot jobs run by `mcp_skills`).

## The digest / comprehension layer

A **digest** is a structured *model* of a document (not a summary) — the
action-relevant structure with source refs — so a downstream task can be run
**from the digest** and **independently verified**. The `digest` skill builds
digests; the applier skills run tasks from them.

```
        source doc (PDF / text / video)
                 │
        ┌────────▼────────┐
        │   /skill:digest  │  classify → read TOC-guided pages (or vision
        └────────┬────────┘  frames) → fill template → verify → store
                 │  (mcp_knowledge: kb_digest, kb_get_pages, kb_digest_store)
        ┌────────▼────────┐
        │  digest (file +  │  /home/chuck/data/ai-kb/digests/<type>/<slug>.md
        │  KB facts)       │  + searchable sections in the source doc's KB
        └────────┬────────┘
   ┌─────────────┼──────────────┬───────────────┬────────────────┐
   ▼             ▼              ▼               ▼                ▼
 ttrpg      digest-book    digest-algo     digest-music     digest-media
 (game)      (story)        (whitepaper)    (music_theory)   (film/TV)
```

## Digest types & templates

Templates live in `digest/references/templates/`:

| type | template | downstream task | applier skill |
|------|----------|-----------------|---------------|
| `game_system` | `game_system.md` | generate a character, adjudicate combat/skills/social, recovery, leveling | `ttrpg` |
| `story` | `story.md` | plot summary, character arcs, thematic analysis | `digest-book` |
| `whitepaper` | `whitepaper.md` | implement the algorithm | `digest-algo` |
| `music_theory` | `music_theory.md` | answer theory questions, generate scales/chords | `digest-music` |
| `media` | `media.md` | insight on a film/TV work from 3 perspectives (cinematics / entertainment / art critics) | `digest-media` |

Every template has a `## Downstream Task` and a `## Verification` section —
verification is not optional (a confident-but-wrong digest is otherwise
indistinguishable from a correct one).

**Status:** all five types are stress-tested end-to-end (harness:
`/home/chuck/workspace/tm_test/run_all.sh`, 5/5 PASS) with one exemplar
digest per type stored in the KB via `kb_digest_store` (`attention_transformer`,
`gurps_basic_4e`, `music_theory_core`, `time_machine`, `peanut_doc`).

## Skills

### Comprehension
- **`digest`** — build a digest of a document. Classifies the type, reads
  TOC-guided pages (or vision frames for media), fills the template, verifies
  load-bearing claims, stores it (file + KB facts). The generic primitive.

### Appliers (run a task from a digest)
- **`ttrpg`** — run a TTRPG session from a `game_system` digest. Deterministic
  `scripts/dice.py` (seeded rolls) + `scripts/state.py` (derived stats,
  point-buy validation, HP tracking); the agent handles narrative.
- **`digest-book`** — analyze a novel/story from a `story` digest (plot,
  arcs, themes, open questions), grounded in the digest's beats.
- **`digest-algo`** — implement an algorithm from a `whitepaper` digest and
  verify it against the digest's invariants. Ships
  `references/transformer_from_digest.py` as the pattern.
- **`digest-music`** — answer theory questions / generate scales/chords from a
  `music_theory` digest, verified by `scripts/theory.py`.
- **`digest-media`** — analyze a film/TV work (video/image/URL) and provide
  insight from three perspectives in one pass: **cinematics** (how it's
  made/looks), **entertainment** (will it hold an audience — critics be
  damned), **art critics** (thematic/artistic merit). Builds/stores a `media`
  digest via vision frame analysis (`mcp_vision`), so the three angles are
  queryable later.

### Other pi-native skills
- `business-analyst`, `content-writer`, `deep-research`, `demo-browse`,
  `demo-workflow`, `homelab-report`, `investment-brief`, `marketing-strategy`,
  `morning-brief`, `presentation-build`, `presentation-update`,
  `publish-file`, `research-brief`, `siri-ask`, `siri-chat`.

## Verification strategy

- **Per-digest**: the `digest` skill's step 5 (follow the template's
  `## Verification`; fix + re-verify on failure).
- **Reusable checkers**: `digest-music/scripts/theory.py`,
  `digest-algo/references/transformer_from_digest.py`,
  `ttrpg/scripts/{dice,state}.py`.
- **Stress-test harness**: `/home/chuck/workspace/tm_test/run_all.sh` (proves
  the digest capability across all five domains, incl. media).

## Extending the digest layer (add a new type, e.g. `recipe`)

1. **Template** — add `digest/references/templates/<type>.md`; copy an
   existing one and keep the `## Downstream Task` and `## Verification`
   sections. Update `digest/references/templates/README.md`.
2. **Applier skill** — new dir `digest-<name>/` with a `SKILL.md`
   (pi-native: no `skill.yml`; frontmatter `name` must match the dir name —
   lowercase a-z, 0-9, hyphens only). It reads the digest via
   `kb_digest_get`/`kb_digest` and runs the downstream task.
3. **Verification pattern** — a per-type independent check (script or
   grounded re-read); wire it into the tm_test harness (`run_all.sh`).
4. **Docs** — update the type tables here and in the main `README.md`, and
   the `digest` skill's type list.
5. **KB** — store exemplar digests with `kb_digest_store` (type = new type;
   they land at `/home/chuck/data/ai-kb/digests/<type>/<slug>.md` +
   `kind=digest` facts in the source doc's KB).

## Notes
- **Skills are distributed via this dir** — pi's settings already point at
  `/home/chuck/homelab/agents-skills`, so a new skill here is live as
  `/skill:<name>` in any pi client (no install step).
- **Scripts are deterministic** — dice, derived stats, and math never come
  from the LLM.
- **Digests are lossy** by design; out-of-scope queries fall back to source
  lookup via the digest's `page_refs`.