# Content strategy — Homelab (choukalos.com)

- **Goal:** serve **Homelab O1** (cycle 2026-12) — *personal-interest content
  ships on a steady rhythm and is worth coming back to* — by giving the 6
  pillars (arcade, guitar, songs/clips, RPGs & war games, cars,
  build-learnings lab) a documented format/channel/search-intent map and a
  30/60/90 calendar the `marketing` agent can produce from.
- **Date:** 2026-11-27
- **Updated:** 2026-11-27 (initial: 2026-11-27)
- **Status:** active (proposal — the calendar is advisory to the `marketing`
  agent; chuck approves/adjusts at the weekly review before items become
  board cards, per the strategist charter guardrails)
- **Serves:** `org/homelab/O1-KR1` (KR2–KR4 as well, see §7);
  `agent/strategist/O2-KR1` + `O2-KR2`
- **Method note:** `mcp_search` was not available in the authoring session, so
  SERP "three Cs" checks were not run per the S12 fallback; intent mapping is
  grounded in (a) the live-site + repo content inventory curl-verified
  2026-11-27 (see §4), (b) the R7 intent buckets and topical-lane rules
  (`docs/research/R7-content-marketing-organic-traffic.md`), and (c) the R9
  operating-cadence rules (repurpose-first, planned-vs-published, 3–6-month
  review — `docs/research/R9-marketing-strategy-operating-cadence.md`).
  Demand estimates are qualitative with the method named; no invented
  numbers. First refresh should run the per-pillar SERP checks via
  `mcp_search` and correct §1.

---

## 1. Audience & intent

**Readers (two concrete personas):**

1. **The builder-curious** — a technical person (devops/indie-dev/younger
   sibling energy) who lands on a game or a lab post and wants to see *how it
   was built*: one-file HTML games, a GPU media pipeline, a homelab run by an
   AI team. They read the lab, view-source the games, and come back for the
   next build.
2. **The hobbyist** — a guitar player, TTRPG player, or car enthusiast who
   lands via a search ("hurt tab johnny cash", "battletech lance", "jeep
   donut") and wants a usable artifact: a tab PDF, an infographic, a clip.
   They take the file and come back when they need the next one.

Both personas share one trait: they come for a *specific artifact*, not a
general news feed. The site's job is to make "worth coming back to" true by
shipping the next artifact on a steady, predictable rhythm (3–4 pieces/mo).

| Pillar area | Intent bucket(s) | Representative target query | Three Cs (type / format / angle) — *to verify at refresh* |
|---|---|---|---|
| Arcade | informational + transactional (play it now) | "asteroids in browser", "play tetris online" | game page / playable single-file HTML / "no download, no ads" angle |
| Guitar | transactional (get the tab) | "<song> guitar tab" | tab PDF / chord+tab sheet / specific-artist song angle |
| Songs/clips | informational + navigational | "AI-generated song <style>", homelab status | audio clip / short post + player / first-hand "we made this" angle |
| RPGs & war games | informational (rules/character help) | "dnd 5e character sheet cheat sheet", "battletech lance" | reference graphic / infographic or character sheet / system-specific angle |
| Cars | informational (facts, comparisons) | "jeep donut", "<car> test drive" | post + photo/infographic / one specific car or physics fact |
| Build-learnings lab | informational (how it's built) | "single-file html game", "ai video pipeline" | lab post / build write-up with code+pipeline detail / first-hand homelab angle |

Notes: multiple intents per query are normal (R7 Q3) — the table records the
dominant one. The arcade pillar is the one where the *artifact itself is the
answer* (play the game); everything else is artifact + short write-up.

## 2. Positioning & guiding principles

- **Topical lane:** a personal homelab where a person + an AI team build and
  play — games, music, tabletop, cars, and the write-ups of what building
  taught us. Site-radius test: a first-time visitor sees four nav sections
  (ARCADE / LAB / THOUGHTS / FILES) and immediately understands "this is a
  person's build-and-play lab". Anything that doesn't fit those four is off
  lane (see exclusion list, §9).
- **Information-gain stance:** everything here was *actually built or
  produced on this homelab* — 16 single-file games with view-source-able
  code, tabs transcribed by our own DSP+ASR pipeline, clips rendered by our
  own GPU pipeline, infra lessons from a running system (the P12 file bridge,
  the kanban agent org). Copycat content can't fake the artifacts or the
  failures; the "honesty corner" (what still doesn't work) is part of the
  brand (see the Kalen v2 post, 2026-11-03).
- **Brand-vs-information position:** the site is a *brand with artifacts*,
  not an info blog. Information-only content is the surface AI answers eat
  first; our moat is the playable/downloadable artifact plus the first-hand
  build story around it.
- **Guiding principles:**
  1. **Repurpose-first** — before any new piece, check the inventory (§4)
     and the `/files/` drop: existing games, tabs, clips, infographics, and
     build history feed the calendar (R9 S9 step 2, S16). New production only
     fills a gap the inventory doesn't.
  2. **Artifact before article** — every piece ships a concrete artifact
     (game, tab PDF, clip, infographic, code) with the write-up as the frame.
  3. **Slow burn** — 3–4 pieces/mo total across all pillars (chuck
     2026-11-26); a cadence you can miss is a cadence you will miss (R7/R9).
  4. **Honesty corner** — lab and build posts name what still fails; the
     process story is the content.
  5. **No orphaned content** — every new piece links to its pillar home
     (`/arcade/`, `/lab/`, `/files/`) and to at least one related piece.

## 3. The 6 pillars — format / channel / search-intent / repurpose-first

| Pillar | Audience + search intent | Formats | Channels | Repurpose-first rule (what existing content feeds it) |
|---|---|---|---|---|
| **Arcade** | Builder-curious + casual players; "play X in browser" (informational + transactional) | game (single-file HTML, 2D canvas or inlined Three.js), lab post about a game build | `/arcade` (primary), `/lab` (build write-ups), `/files/` (shots/assets) | 16 live games + the "One-Page Arcade" lab post (2026-08-24) + per-game shots. Each new game reuses the `one-page-arcade-2d/3d` skill conventions (resize/ensureAudio/loop, hi-score, index JSON entry) — the roster is the source material for "how we rebuilt X" posts. |
| **Guitar** | Hobbyist guitarists; "<song> tab" (transactional) | tab PDF (chords + tab), roundup post, pipeline write-up | `/files/tabs/` (primary), blog `/lab` or `/thoughts` (post linking the PDFs) | 8 live tab PDFs (U2 One, RHCP Californication, Johnny Cash Hurt, AC/DC Back in Black, Riptide, Old Porch, Submission, Sweet Child O' Mine). The `song-transcribe` pipeline (DSP note events + ASR lyrics + LLM polish) is the production engine; a roundup post repurposes the existing 8 before any new transcription. |
| **Songs/clips** | Hobbyist + builder-curious; "AI music" / novelty clips (informational + navigational) | audio clip (mp3), short post with player, video clip | `/files/audio/` + `/files/video/` (primary), blog post as the frame | `audio/neon_thunder.mp3` and the existing `/files/video/` clips (Peanut, Potato Wars trilogy, holiday spoof). ACE-Step/MMAudio generation from the media pipeline is the engine; the first calendar item repurposes an existing clip with a "how it was made" frame before producing new audio. |
| **RPGs & war games** | TTRPG players; "dnd 5e cheat sheet", "battletech lance", character help (informational) | reference infographic, character sheet (PDF/MD), post, short video clip | `/files/images/` + `/files/ai/` (primary), blog post as the frame, `/files/video/` for clips | 3 live artifacts: D&D 5e character-creator cheat sheet (PNG), Battletech lance infographic (PNG), Kaelen Thornwood GURPS-150 character (MD) + the Kalen ranger video pair and the 2026-11-03 lab post. The `ttrpg`/`digest` skills are the production engine. |
| **Cars** | Car enthusiasts; specific-car facts, comparisons, physics (informational) | post + photo collage, infographic, fact-check piece | blog `/thoughts` (primary), `/files/images/` for the visuals | 3 live artifacts: zootopia-jeep donut-facts infographic, car test-drive collage, Porsche 911 Gentian render. The `infographic` skill is the production engine; each new piece reuses an existing image set before shooting/rendering new ones. |
| **Build-learnings lab** | Builder-curious; "how is X built" (informational) | lab post (build write-up with code/pipeline detail + honesty corner), before/after comparison | `/lab` (primary), `/files/` for supporting artifacts | First topics per chuck 2026-11-26: **arcade & media pipeline lessons, then AI-harness lessons**. Already live: "One-Page Arcade" (2026-08-24) and "Kalen the Ranger vs the Orcs — v2 (new media pipeline)" (2026-11-03). The homelab repo itself (P12 file bridge, kanban agent org, security phases) is the source material for the AI-harness lessons. |

Pillars are mutually exclusive (a piece carries exactly one pillar tag — the
inventory row's `pillar` field is the single source of truth) and collectively
cover the site: every channel in §6 maps to at least one pillar.

## 4. Current content inventory (repurpose base, verified 2026-11-27)

**Blog (choukalos.com, Hugo — repo `github.com/choukalos/homelab-blog`):**

| Piece | Pillar | Format | Where |
|---|---|---|---|
| Hello from the new portal (2026-08-24) | (site) | announcement post | `/thoughts/` |
| One-Page Arcade (2026-08-24) | arcade + lab | lab post | `/lab/one-page-arcade/` |
| Kalen the Ranger vs the Orcs — v2 (2026-11-03) | lab (+ RPG) | lab post, before/after | `/lab/kalen-the-ranger-vs-the-orcs-v2-new-media-pipeline/` (live; source not yet in repo `main` — flag for the marketing agent) |
| 16 arcade games (14 classics + 2 originals: Zombie City 2025, Alpine Rush 2026) | arcade | games | `/arcade/*.html` (data-driven index, `data/arcade/games.json`) |

**`/files/` public drop (choukalos.com/files/, served from the publish root):**

| Folder | Existing content | Feeds pillar |
|---|---|---|
| `tabs/` | 8 tab PDFs (see §3) | guitar |
| `audio/` | `neon_thunder.mp3` | songs/clips |
| `video/` | Peanut clips, Potato Wars trilogy (6 files), SW holiday spoof, Buck Rogers 25th, Duck Dodgers, Kalen ranger v1+v2 | songs/clips, RPG |
| `images/` | D&D 5e cheat sheet, Battletech lance infographic, zootopia-jeep donut facts, car test-drive collage, Porsche 911 Gentian, retirement infographic | RPG, cars |
| `ai/` | Kaelen Thornwood GURPS-150 character, TTS A/B script | RPG |
| `briefs/` | morning brief + market-research briefs | (off-pillar — utility output, not content; excluded from the calendar) |

**Gaps (what the calendar must produce, not repurpose):** a second arcade
original or next classic rebuild, a new transcribed tab, a new song clip, a
second RPG reference artifact, a second car piece, and the AI-harness lab
lessons (none of which exist yet).

> Note for the marketing agent: the durable content inventory at
> `docs/roles/content-marketer/inventory.md` (CM-2) does not exist yet — it is
> created at first publish. Until then, this §4 table + the board's done tasks
> are the dedupe/repurpose base.

## 5. Funnel mapping

The Homelab Blog has no lead form; the conversion action is **"come back"** —
concrete: play a game (hi-score), download an artifact, and return for the
next one. Stages:

| Cluster / topic | Stage | Conversion action |
|---|---|---|
| Arcade games (each `/arcade/*.html`) | TOFU (traffic + AI-surface) → BOFU for the pillar | play the game; hi-score in `localStorage` |
| Lab build posts | TOFU (informational; the surface AI Overviews appear on — must carry information gain) | read to the end; follow the "view source / steal what you like" CTA |
| Tab PDFs / infographics / character sheets | MOFU (specific-need, high-intent) | download the file |
| Songs/clips | MOFU | play the clip; return for the next |
| Pillar home pages (`/arcade/`, `/lab/`, `/files/`) | BOFU (the "come back" surface) | revisit within 30 days |

Pillar pages optimize for the conversion action; cluster pieces (individual
games/tabs/posts) optimize for traffic. TOFU content (lab posts, game pages)
must carry information gain — that is the §2 stance, enforced per piece by
`content-qa` (CM-1).

## 6. Distribution

- **Owned channels (all real, all in-repo or in the publish root):**
  1. Blog (Hugo, git-published) — `/lab`, `/thoughts`
  2. `/arcade` — the games themselves (the artifact is the content)
  3. `/files/` — the public drop (tabs, audio, video, images)
  4. RSS (`/lab/index.xml` etc.) — the "come back" mechanism
- **Repurposing plan (the cost lever, R9 S10 step 7):** one build → multiple
  artifacts. Example chain: a new arcade game → `/arcade` game + index entry +
  screenshot → a lab post on one hard problem in its build → a `/files/`
  asset drop. One transcription run → tab PDF + a "how we transcribe" post.
  Keep the main ideas, change the format/length/structure/CTA per channel.
- **External comms:** none in v1 — the strategist charter bans external
  comms without an explicit ask, and the `marketing` agent's social
  distribution is out of scope for this cycle. "Search everywhere" (R7 Q4):
  the site is no-cookie/no-tracker and git-published; off-Google presence is
  whatever chuck shares manually. No `llms.txt` work (R7: 97% of published
  files are never fetched).

## 7. Measurement plan (mandatory — strategist O2 KR4)

**Which org KRs this feeds:** Homelab O1 KR1 (content output), KR2 (pillar
spread), KR3 (revisit/traffic), KR4 (quality). Strategist O2 KR1 (this doc),
KR2 (the calendar), KR3 (calendar completeness — 0 items missing
format+channel+metric).

**KPIs (cluster-level, not post-level — R7 Q6; ~3 that ladder up to O1):**

| KPI | Ladders to | Source | Target | Cadence |
|---|---|---|---|---|
| Planned-vs-published: pieces published / pieces planned this month | O1-KR1 | content inventory + board done tasks | 3–4/mo (slow burn; ≤ 4) | monthly |
| Pillar spread: pillars with ≥ 1 published piece | O1-KR2 | content inventory | ≥ 2 of 6/mo (proxy) | monthly |
| Return-visitor share / sessions MoM | O1-KR3 | Plausible — **not wired (G3)**; until it lands, proxy = RSS feed fetches + direct feedback, flagged `proxy` in the monthly review | +10% MoM sessions (validate when Plausible lands) | monthly |
| Quality: published pieces that failed content QA (CM-1) | O1-KR4 | QA records on board cards + inventory | 0 | per publish |

**ROI method (fixed up front, R7 S12):** *lifetime traffic value* — monthly
traffic value × content lifetime, applied consistently once Plausible lands;
directional, not precise. Until then the KPI set above is the measurement.

**Review cadence:**
- **Per publish:** content-QA gate (CM-1) before finalizing — hard gate.
- **Weekly:** strategist weekly review checks calendar status (planned →
  asked → drafted → QA → published) against the board.
- **Monthly:** the monthly org review (first Friday) scores Homelab O1 KRs
  against this KPI table; the strategist's planned-vs-published line is the
  pipeline check (R9 S9: "how many they planned vs actually published…
  identify and fix issues in the production pipeline").
- **Strategy refresh:** every 3–6 months (R9 S10), or immediately on a
  **refresh trigger**: traffic drop from peak; a superseded stat; a channel
  change (e.g., Plausible wiring = G3 lands → replace the proxy KPI); a
  pillar going dark for 2 consecutive months; a competitor/adjacent site
  substantially updating its lane.

## 8. 30/60/90 calendar (slow burn: 4 pieces/mo max)

Sequencing rule: repurposed pieces first (cheap, validates the rhythm),
new production second. Lab topics follow chuck's 2026-11-26 order: arcade &
media pipeline lessons first, then AI-harness lessons. Every item carries
**pillar / format / channel / success metric / source**. Status: planned →
asked (board card) → drafted → QA → published.

### Days 1–30 (December 2026) — 4 pieces

| # | Item | Pillar | Format | Channel | Success metric | Source (repurposed / new) |
|---|---|---|---|---|---|---|
| 1 | "How we rebuilt 16 arcade classics as one-file HTML" (deep-dive: the conventions, the hard parts, view-source CTA) | build-learnings lab | lab post | `/lab` | Published with 0 content-QA failures; ≥ 3 internal links to live `/arcade` games; 1 pillar-spread point (lab active in Dec) | Repurposed — the 16 live games + the 2026-08-24 One-Page Arcade post (expanded, not duplicated) |
| 2 | Donkey Kong (1981) rebuild | arcade | game (single-file HTML, 2D canvas) | `/arcade` | Published with index JSON entry + screenshot; headless QA 0 console errors; hi-score persists across reloads | New — built via the `one-page-arcade-2d` skill (conventions repurposed from the existing 16) |
| 3 | "8 tabs from the homelab transcription pipeline" (roundup with embedded links + one-paragraph how-it-works) | guitar | roundup post + tab PDFs | blog (`/thoughts`) + `/files/tabs/` | Published with all 8 tab links curl-verified live; 0 content-QA failures | Repurposed — the 8 existing tab PDFs |
| 4 | "Kaelen the Ranger — a GURPS-150 character sheet" (post framing the character + the Kalen video pair) | RPGs & war games | post + reference (character sheet + infographic link) | blog + `/files/ai/` + `/files/images/` | Published with the GURPS MD, the D&D 5e cheat sheet, and both Kalen videos linked and curl-verified; 0 content-QA failures | Repurposed — `ai/kaelen-thornwood-gurps-150.md`, `images/dnd5e_character_creator_cheatsheet.png`, the Kalen v1/v2 videos + 2026-11-03 lab post |

### Days 31–60 (January 2027) — 4 pieces

| # | Item | Pillar | Format | Channel | Success metric | Source (repurposed / new) |
|---|---|---|---|---|---|---|
| 5 | "Running a virtual team on a kanban board — AI-harness lesson #1" (the agent org, the QA gate, what it caught) | build-learnings lab | lab post (build write-up + honesty corner) | `/lab` | Published with 0 content-QA failures; ≥ 3 internal links (repo docs / prior lab posts); first AI-harness lesson shipped (charter order) | New — sourced from the homelab repo (kanban agent org, P12 file bridge, security phases); no prior piece covers it |
| 6 | "Donuts, jeeps, and physics — a fact-check" (the donut-facts infographic, verified) | cars | post + infographic | blog (`/thoughts`) + `/files/images/` | Published with the infographic live-linked; every physics claim fact-checked (content-qa); 0 content-QA failures | Repurposed — `images/zootopia-jeep-donut-facts.png` (+ `car-test-drive-collage.png` as supporting visual) |
| 7 | "How neon_thunder was made" (the clip + the ACE-Step/MMAudio pipeline in one screen) | songs/clips | audio clip + short post with player | `/files/audio/` + blog | Clip playable at the published URL (curl-verified); post published with 0 content-QA failures | Repurposed — existing `audio/neon_thunder.mp3`; pipeline description is new framing |
| 8 | Next arcade rebuild (Pac-Man 1980 — classic, not yet in the roster) | arcade | game (single-file HTML, 2D canvas) | `/arcade` | Published with index JSON entry + screenshot; headless QA 0 console errors; hi-score persists | New — `one-page-arcade-2d` skill; roster gap filled (deduped against the 16 live games) |

### Days 61–90 (February 2027) — 4 pieces

| # | Item | Pillar | Format | Channel | Success metric | Source (repurposed / new) |
|---|---|---|---|---|---|---|
| 9 | "Battletech lance — how to field one" (infographic + short rules primer) | RPGs & war games | post + infographic | blog + `/files/images/` | Published with the infographic live-linked; rules claims checked against the digest; 0 content-QA failures | Repurposed — `images/battletech_lance_infographic.png` |
| 10 | New transcribed tab (chuck picks the song; pipeline run + tab PDF + one-paragraph post) | guitar | tab PDF + short post | `/files/tabs/` + blog | Tab PDF published at the `/files/tabs/` URL (curl-verified); post published with 0 content-QA failures | New — `song-transcribe` pipeline run (the 8 existing tabs are the format template) |
| 11 | "Securing a public file edge — AI-harness lesson #2" (the P12 file bridge: default-deny registry, signed tokens, one-reload cutover) | build-learnings lab | lab post (build write-up + honesty corner) | `/lab` | Published with 0 content-QA failures; ≥ 3 internal links; second AI-harness lesson shipped | New — sourced from the homelab repo (security Phase 12 / file-bridge work); no prior public piece covers it |
| 12 | Second car piece — the test-drive collage, annotated (what the shots show, what the specs say) | cars | post + photo collage | blog (`/thoughts`) + `/files/images/` | Published with the collage live-linked; specs fact-checked; 0 content-QA failures | Repurposed — `images/car-test-drive-collage.png` (+ `porsche911-gentian.png`) |

**Calendar checks (O2 KR3 quality gate — 0 missing):** every item above has a
pillar, format, channel, success metric, and source. Volume: 4 + 4 + 4 = 12
pieces over 90 days = 4/mo — at (never above) the slow-burn ceiling. Pillar
spread: arcade 2, guitar 2, songs/clips 1, RPGs 2, cars 2, lab 3 — all 6
pillars active in the window; every 30-day window has ≥ 2 pillars (satisfies
O1-KR2 from month one).

## 9. Exclusion list (the "do nothing" list — R7 Q2)

- **Bluebovine / product-management content** — different site, different
  strategy doc (`strategy/bluebovine.md`); never mixed into this lane.
- **Generic "top 10 / best X" listicles** — no information gain; the
  copycat surface AI answers eat first.
- **News/ commentary on the AI industry** — off-lane; the lane is *what we
  built*, not what the industry did.
- **`/files/briefs/` output** (morning brief, market-research briefs) —
  utility output for chuck, not content; never promoted to the calendar.
- **Anything requiring external comms** (social posts, email) in v1 —
  charter constraint; distribution is owned channels only.
- **InvestHub / personal-finance content** — out of agent scope per
  `docs/org/goals.md`.

## Appendix A — candidate `kb_homelab-content` facts (Q15 flag)

The homelab content domain KB (`kb_homelab-content`) is owned by the
`marketing` agent. Cross-domain KB writes are single-approval (Q7) and no
approval was available in this session — so these candidate distilled facts
are recorded here with provenance, **flagged for the owner (marketing agent /
chuck) to distill**. Not written to the KB.

1. *choukalos.com serves 16 arcade games at `/arcade` (14 classics + 2
   originals: Zombie City: Last Stand 2025, Alpine Rush 2026), each a
   self-contained HTML file with a data-driven index
   (`data/arcade/games.json`).* — provenance: live site curl 2026-11-27 +
   `homelab-blog` repo `static/arcade/` + `content/arcade/_index.md`.
2. *The `/files/` public drop currently holds 8 guitar tab PDFs, 1 audio
   clip (`neon_thunder.mp3`), 6+ video clips (incl. the Potato Wars trilogy
   and the Kalen ranger v1/v2 pair), 8+ images (incl. the D&D 5e cheat sheet
   and the Battletech lance infographic), and a GURPS-150 character sheet.* —
   provenance: publish-root listing 2026-11-27 + live `/files/` curl.
3. *The live `/lab` page carries a post ("Kalen the Ranger vs the Orcs — v2",
   2026-11-03) whose source file is not in `homelab-blog` `main` — the live
   build (deploy branch) is ahead of `main`; the durable inventory must treat
   the live site as the source of truth until the repo catches up.* —
   provenance: `git ls-tree origin/main` vs live curl, 2026-11-27.
4. *The site's conversion action is "come back" (play a game / download an
   artifact / return within 30 days); there is no lead form, and Plausible
   analytics is not yet wired (G3), so traffic KPIs are proxy until it
   lands.* — provenance: `docs/org/goals.md` (Homelab O1 KR3) + site footer
   ("no cookies · no trackers").
5. *The 6 content pillars are arcade, guitar, songs/clips, RPGs & war games,
   cars, and build-learnings lab; the slow-burn target is 3–4 pieces/mo
   total, with lab topics ordered arcade & media pipeline first, then
   AI-harness lessons (chuck 2026-11-26).* — provenance:
   `docs/org/goals.md` + `docs/agents/strategist/charter.md` (O2 KR1).

---
*G12 artifact — durable, versioned; updates are edits with an "updated
<date>" note. Companion impact reviews land at
`docs/roles/marketing-strategist/impact-reviews/homelab-<YYYY-MM-DD>.md`.*
