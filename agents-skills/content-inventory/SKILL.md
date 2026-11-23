---
name: content-inventory
description: Maintain the content inventory — the repo registry of published content (URL, publish date, pillar, format, goal, performance when available) at docs/roles/content-marketer/inventory.md. Use at publish time (add the row when content ships and the live URL is verified), before pitching new content (the dedupe and repurpose check against what already exists), when the strategist or BA needs the published-content list for impact reviews or measurement, and when calibrating brand voice against existing content (MKT-1's G8 step). Fills gap G10 (no content inventory); grounded in R9 (docs/research/R9-marketing-strategy-operating-cadence.md — the content-inventory concept, the planned-vs-published pipeline check, the repurpose-first rule).
---

# Content Inventory

The registry of published content — the repo artifact behind gap G10. One
file, one table, updated at publish time. The BA measures against it, the
strategist reviews it (impact reviews, voice calibration), and the CM checks
it before pitching (dedupe/repurpose). Grounded in R9
(`docs/research/R9-marketing-strategy-operating-cadence.md` — the
content-inventory concept from the voice-calibration step [R9 S1], the
planned-vs-published pipeline check from the editorial-calendar benefits [R9
S9], the repurpose-first rule [R9 S9 step 2]) and the org model (gap G10 in
`todo_agent_skills.md`).

## When to use

- **Use it:** content just published (add the row — the CM workflow step 6,
  after the live URL is verified); the CM is about to pitch angles for an
  open ask (dedupe/repurpose check first); the strategist runs an impact
  review or calibrates the voice (the inventory is the input); the BA needs
  the published-content list for measurement; the inventory is stale
  (published pieces missing rows, or performance data now available).
- **Skip it:** the ask is about *unpublished* drafts (those live on the
  board, not here — the inventory is the published record); or the ask is a
  one-off "what did we publish about X" (grep the inventory and answer — no
  update needed unless the answer reveals missing rows).

## The artifact

`docs/roles/content-marketer/inventory.md` (the G12 artifact conventions —
one file, one table, per site). Create it on first use if missing:

```markdown
# Content inventory — <site/brand>

Updated: <YYYY-MM-DD>

| URL | Published | Pillar | Cluster | Format | Funnel stage | Goal | Ask (board ref) | QA | Performance |
|-----|-----------|--------|---------|--------|--------------|------|-----------------|----|-------------|
| <live URL> | <YYYY-MM-DD> | <pillar> | <cluster> | <blog/social/video> | <TOFU/MOFU/BOFU> | <the goal the piece served> | <card id> | <QA-clean / exceptions> | <sessions/leads/rankings + source + as-of date, or "no data yet"> |
```

Field notes:

- **URL** — the live URL, verified (S3 discipline: checked, not assumed).
- **Pillar / Cluster** — from the strategy doc
  (`docs/roles/marketing-strategist/strategy/<site>.md`); the cluster-level
  grouping is what impact reviews measure against (R7 Q5: cluster-level, not
  post-level).
- **Goal** — the goal the piece served (from the ask) — the BA measures
  against it.
- **QA** — the CM-1 gate verdict (QA-clean / signed-off exceptions) — the
  published record carries the gate evidence.
- **Performance** — the metric + data source + as-of date, or "no data yet"
  (a valid entry until the G3 wiring lands — Plausible; never an invented
  number, S9 discipline).

## Method

1. **At publish time (the primary use).** After the piece passes CM-1
   `content-qa` and is published via the project's path, and the live URL is
   verified (CM workflow step 6): add the row. A published piece with no
   inventory row is a process violation — same class as a deploy without the
   post-deploy check. Bump the file's "Updated" date.
2. **Before pitching (dedupe/repurpose).** When the CM pitches angles for an
   open ask (CM workflow step 2) or the strategist ideates asks: scan the
   inventory for the topic/angle first —
   - **Duplicate?** An existing piece covers it → the ask is a *refresh*, not
     a new piece (the refresh triggers from the strategy doc's measurement
     section apply — R7 Q2).
   - **Repurpose candidate?** An existing piece's core content fits the new
     angle/format → repurpose (R9 S9 step 2: "revisit your existing content
     library to find pieces you can repurpose — saving you time, money,
     additional resources, and effort"; R9 S16: the repurpose-first rule).
   - **Gap?** Nothing covers it → pitch the new angles.
   The pitch says which of the three it is — "new" without the dedupe check
   is the G10 failure mode (duplicate content diluting the topical lane).
3. **For impact reviews (strategist input).** MKT-1's impact review uses the
   inventory as the per-ask/per-cluster performance base + the
   planned-vs-published pipeline check (how many asks shipped vs. planned —
   the pipeline problem vs. the content problem, R9 S9).
4. **For voice calibration (MKT-1 input).** The voice step (MKT-1 step 3)
   classifies the inventory's pieces by performance where data exists and
   extracts the voice traits from the top performers (R9 S1: the
   content-inventory step of the voice framework).
5. **Performance updates (periodic).** When data becomes available (the G3
   wiring — Plausible → data-hub; until then GSC / manual spot-checks / BA
   reports): fill the Performance column with the metric + source + as-of
   date. Stale performance values get the as-of date bumped or are marked
   stale — a performance number without an as-of date is a stale claim.

## Rules

- **One file, one table, per site** — `docs/roles/content-marketer/inventory.md`
  is the only home (G12). No spreadsheets in `tmp/`, no second registry in a
  chat transcript.
- **The inventory records what is live** — a row is added only after the
  live URL is verified. Unpublished drafts live on the board; the
  inventory's planned-vs-actual gap *is* the pipeline signal (R9 S9).
- **Unpublishing is a status change, not a deletion** — a piece that gets
  unpublished, merged, or redirected keeps its row (mark it:
  "unpublished <date>", "merged into <URL>", "redirects to <URL>"). The
  history is the record — the BA's trend lines and the strategist's
  refresh-trigger checks depend on it.
- **Performance values carry their source** — metric + source + as-of date,
  or "no data yet". No invented numbers (S9 discipline); the G3 gap is the
  reason for "no data yet", not an excuse to estimate.
- **The row is cheap, so it's never skipped** — the row is ~10 fields copied
  from the ask + the publish step; skipping it is how the registry rots
  (the G10 failure mode: the inventory exists but nobody updates it, so
  nobody trusts it, so nobody uses it).

## Output

1. **The updated inventory** — `docs/roles/content-marketer/inventory.md`
   with the new/updated rows + the bumped "Updated" date.
2. **The dedupe/repurpose report** (when asked before pitching) — per
   candidate ask: duplicate / repurpose / gap, with the matching inventory
   rows (URLs) and the recommended move (refresh / repurpose / new).

## Handoff

- **→ CM-1 `content-qa`:** the QA verdict written to the row is the
  published record's gate evidence.
- **→ MKT-1 `brand-strategy`:** the inventory is the voice-calibration input
  (step 3) and the impact-review performance base (step 6).
- **→ BA:** the inventory is the measurement base for content KPIs (the BA
  loop, Phase 3 — the G3 wiring closes the data side).
- **→ the board:** dedupe/repurple findings route back to the ask pipeline
  (a "new" ask that's actually a refresh gets re-briefed as a refresh).
