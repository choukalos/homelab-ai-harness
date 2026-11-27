# Content inventory — choukalos.com

> G12 role artifact (marketing agent, project 12). The single-table registry of
> all published content: URL, publish date, pillar, format, goal; performance
> column present (empty until Plausible wiring lands — G3, never fabricated).
>
> Serves: Homelab O1 (KR1 content output, KR2 pillar spread — declared source)
> and the marketing charter O1 KR3 (inventory current — 100% of publishes).
>
> Bootstrap 2026-11-27 (task 22). Sources: homelab-blog repo (`main` +
> `deploy` branches, read-only clone), live choukalos.com, `/files/` public
> drop (`/home/chuck/data/media/public`), `data/arcade/games.json`.

## Conventions

- **One table, one row per published piece.** Updated **at publish time**:
  when content ships and the live URL is verified (HTTP 200), add the row
  (CM-2 `content-inventory` skill). No row without a live URL.
- **Publish date**: frontmatter `date:` when present (Hugo posts); file mtime
  in the public drop when dropped there; `unknown` when no reliable source
  (the blog repo's git history is squashed to a single commit dated
  2026-10-21, so arcade-game dates are `unknown` — see Gaps).
- **Pillar**: one of the 6 (docs/org/goals.md Homelab O1): arcade, guitar,
  songs/clips, RPGs & war games, cars, build-learnings lab. Content that
  doesn't map is **not silently dropped** — it gets pillar `unmapped` and a
  flag in the Gaps section (candidate for the strategist's pillar review).
- **Goal**: one short phrase — what the piece is for (pillar output,
  build-learnings vehicle, repurpose source, …).
- **Performance**: left empty until Plausible is wired (G3). Never
  fabricated. The BA measures against this table once data lands.
- **Dedupe/repurpose check**: before pitching any new piece, search this
  table by URL/title/pillar (repurpose-first rule — charter O2 KR2).
- Hub/index pages (`/`, `/arcade/`, `/files/` browser) are site chrome, not
  content rows; the arcade index's 16 games are the rows.

## Inventory

| URL | Publish date | Pillar | Format | Goal | Performance |
|---|---|---|---|---|---|
| https://choukalos.com/thoughts/hello-from-the-new-portal/ | 2026-08-24 | build-learnings lab | thoughts post (Hugo) | Portal migration announcement; first post on the new static portal | |
| https://choukalos.com/lab/one-page-arcade/ | 2026-08-24 | build-learnings lab (arcade cross) | lab post (Hugo) | Document the one-page arcade rebuild process (arcade & media pipeline first) | |
| https://choukalos.com/lab/kalen-the-ranger-vs-the-orcs-v2-new-media-pipeline/ | 2026-11-03 | build-learnings lab (RPGs & war games cross) | lab post (Hugo, media post-mortem) | Show the new media pipeline's QC discipline via a GURPS ranger scene rebuild | |
| https://choukalos.com/arcade/asteroids.html | unknown | arcade | one-page HTML game | Playable arcade pillar content (Asteroids, 1979 rebuild) | |
| https://choukalos.com/arcade/battlezone.html | unknown | arcade | one-page HTML game (Three.js 3D) | Playable arcade pillar content (Battlezone, 1990 rebuild) | |
| https://choukalos.com/arcade/depth-charge.html | unknown | arcade | one-page HTML game | Playable arcade pillar content (Depth Charge, 1977 rebuild) | |
| https://choukalos.com/arcade/double-dragon.html | unknown | arcade | one-page HTML game | Playable arcade pillar content (Double Dragon, 1987 rebuild) | |
| https://choukalos.com/arcade/elite.html | unknown | arcade | one-page HTML game (Three.js 3D) | Playable arcade pillar content (Elite, 1984 rebuild) | |
| https://choukalos.com/arcade/galaga.html | unknown | arcade | one-page HTML game | Playable arcade pillar content (Galaga, 1981 rebuild) | |
| https://choukalos.com/arcade/kungfu.html | unknown | arcade | one-page HTML game | Playable arcade pillar content (Kung Fu Master, 1984 rebuild) | |
| https://choukalos.com/arcade/lunar-lander.html | unknown | arcade | one-page HTML game | Playable arcade pillar content (Lunar Lander, 1979 rebuild) | |
| https://choukalos.com/arcade/missile-command.html | unknown | arcade | one-page HTML game | Playable arcade pillar content (Missile Command, 1980 rebuild) | |
| https://choukalos.com/arcade/outrun.html | unknown | arcade | one-page HTML game (pseudo-3D) | Playable arcade pillar content (OutRun, 1986 rebuild) | |
| https://choukalos.com/arcade/pitfall.html | unknown | arcade | one-page HTML game | Playable arcade pillar content (Pitfall!, 1982 rebuild) | |
| https://choukalos.com/arcade/skiing.html | unknown | arcade | one-page HTML game (Three.js 3D) | Playable arcade pillar content (Alpine Rush, original 2026) | |
| https://choukalos.com/arcade/star-trek.html | unknown | arcade | one-page HTML game | Playable arcade pillar content (Star Trek, 1983 rebuild) | |
| https://choukalos.com/arcade/star-wars.html | unknown | arcade | one-page HTML game | Playable arcade pillar content (Star Wars, 1983 rebuild) | |
| https://choukalos.com/arcade/tetris.html | unknown | arcade | one-page HTML game | Playable arcade pillar content (Tetris, 1984 rebuild) | |
| https://choukalos.com/arcade/zombie-city.html | unknown | arcade | one-page HTML game (3D) | Playable arcade pillar content (Zombie City: Last Stand, original 2025) | |
| https://choukalos.com/files/tabs/guns-n-roses-sweet-child-o-mine-tab.pdf | 2026-11-06 | guitar | guitar tab (PDF) | Guitar pillar content (transcribed tab) | |
| https://choukalos.com/files/tabs/johnny-cash-hurt-tab.pdf | 2026-11-06 | guitar | guitar tab (PDF) | Guitar pillar content (transcribed tab) | |
| https://choukalos.com/files/tabs/rhcp-californication-tab.pdf | 2026-11-06 | guitar | guitar tab (PDF) | Guitar pillar content (transcribed tab) | |
| https://choukalos.com/files/tabs/u2-one-tab.pdf | 2026-11-06 | guitar | guitar tab (PDF) | Guitar pillar content (transcribed tab) | |
| https://choukalos.com/files/tabs/old-porch-tab.pdf | 2026-11-08 | guitar | guitar tab (PDF) | Guitar pillar content (transcribed tab) | |
| https://choukalos.com/files/tabs/back-in-black-tab.pdf | 2026-11-08 | guitar | guitar tab (PDF) | Guitar pillar content (transcribed tab) | |
| https://choukalos.com/files/tabs/submission-tab.pdf | 2026-11-08 | guitar | guitar tab (PDF) | Guitar pillar content (transcribed tab) | |
| https://choukalos.com/files/tabs/riptide-tab.pdf | 2026-11-08 | guitar | guitar tab (PDF) | Guitar pillar content (transcribed tab) | |
| https://choukalos.com/files/video/elven_ranger_battles_orcs.mp4 | 2026-10-03 | RPGs & war games | AI video clip (~57s) | Kalen the Ranger scene (old media pipeline) — comparison baseline for the v2 lab post | |
| https://choukalos.com/files/video/elven_ranger_battles_orcs_v2.mp4 | 2026-11-03 | RPGs & war games | AI video clip (~40s) | Kalen the Ranger scene rebuilt on the new media pipeline (v2) | |
| https://choukalos.com/files/video/Potato%20Wars%20Trilogy/potato-wars-trilogy-1-potato-wars_original.mp4 | 2026-11-23 | RPGs & war games | AI video (game footage, original cut) | Potato Wars Trilogy ep. 1 — original | |
| https://choukalos.com/files/video/Potato%20Wars%20Trilogy/potato-wars-trilogy-1-potato-wars_updated_draft.mp4 | 2026-11-23 | RPGs & war games | AI video (game footage, draft) | Potato Wars Trilogy ep. 1 — updated draft | |
| https://choukalos.com/files/video/Potato%20Wars%20Trilogy/potato-wars-trilogy-1-potato-wars_revisited_draft.mp4 | 2026-11-23 | RPGs & war games | AI video (game footage, draft) | Potato Wars Trilogy ep. 1 — revisited draft | |
| https://choukalos.com/files/video/Potato%20Wars%20Trilogy/potato-wars-trilogy-1-potato-wars_production.mp4 | 2026-11-24 | RPGs & war games | AI video (game footage, production) | Potato Wars Trilogy ep. 1 — production cut | |
| https://choukalos.com/files/video/Potato%20Wars%20Trilogy/potato-wars-trilogy-2-revenge-of-the-banana_original.mp4 | 2026-11-23 | RPGs & war games | AI video (game footage, original cut) | Potato Wars Trilogy ep. 2 — original | |
| https://choukalos.com/files/video/Potato%20Wars%20Trilogy/potato-wars-trilogy-2-revenge-of-the-banana_updated_draft.mp4 | 2026-11-23 | RPGs & war games | AI video (game footage, draft) | Potato Wars Trilogy ep. 2 — updated draft | |
| https://choukalos.com/files/video/Potato%20Wars%20Trilogy/potato-wars-trilogy-2-vegetables-strike-back_revisited_draft.mp4 | 2026-11-23 | RPGs & war games | AI video (game footage, draft) | Potato Wars Trilogy ep. 2 — revisited draft | |
| https://choukalos.com/files/video/Potato%20Wars%20Trilogy/potato-wars-trilogy-2-vegetables-strike-back_production.mp4 | 2026-11-24 | RPGs & war games | AI video (game footage, production) | Potato Wars Trilogy ep. 2 — production cut | |
| https://choukalos.com/files/video/Potato%20Wars%20Trilogy/potato-wars-trilogy-3-revenge-of-the-potato_revisited_draft.mp4 | 2026-11-23 | RPGs & war games | AI video (game footage, draft) | Potato Wars Trilogy ep. 3 — revisited draft | |
| https://choukalos.com/files/video/Potato%20Wars%20Trilogy/potato-wars-trilogy-3-revenge-of-the-potato_production.mp4 | 2026-11-25 | RPGs & war games | AI video (game footage, production) | Potato Wars Trilogy ep. 3 — production cut | |
| https://choukalos.com/files/ai/kaelen-thornwood-gurps-150.md | 2026-10-03 | RPGs & war games | GURPS character sheet (markdown) | RPG source content (Kaelen Thornwood, GURPS 4e) — feeds the ranger video clips | |
| https://choukalos.com/files/images/dnd5e_character_creator_cheatsheet.png | 2026-11-20 | RPGs & war games | infographic (PNG) | RPG reference sheet (D&D 5e character creator) | |
| https://choukalos.com/files/images/battletech_lance_infographic.png | 2026-11-20 | RPGs & war games | infographic (PNG) | RPG reference sheet (BattleTech lance) | |
| https://choukalos.com/files/images/banana_keyframe.png | 2026-10-03 | RPGs & war games | keyframe still (PNG) | Media-pipeline keyframe (Potato Wars ep. 2) — draft artifact | |
| https://choukalos.com/files/images/porsche911-gentian.png | 2026-10-03 | cars | image (PNG) | Cars pillar content (Porsche 911) | |
| https://choukalos.com/files/images/car-test-drive-collage.png | 2026-11-20 | cars | collage (PNG) | Cars pillar content (test-drive collage) | |
| https://choukalos.com/files/images/zootopia-jeep-donut-facts.png | 2026-10-03 | cars | facts image (PNG) | Cars pillar content (jeep/donut facts) | |
| https://choukalos.com/files/briefs/investment_brief.html | 2026-11-27 | unmapped ⚑ | HTML brief | Investment brief (agent output) — business domain, not a personal-interest pillar | |
| https://choukalos.com/files/briefs/latest.html | 2026-11-27 | unmapped ⚑ | HTML brief | Morning-brief "New Stories" digest (agent output) | |
| https://choukalos.com/files/briefs/ecommerce_platforms_brief.html | 2026-11-01 | unmapped ⚑ | HTML brief | Ecommerce market research brief, latest (agent output) | |
| https://choukalos.com/files/briefs/smarthome_homesecurity_brief.html | 2026-11-01 | unmapped ⚑ | HTML brief | Smart home & security market research brief, latest (agent output) | |
| https://choukalos.com/files/briefs/market_research/ecommerce_platforms_brief_2026-10.html | 2026-10-13 | unmapped ⚑ | HTML brief | Ecommerce market research brief, October 2026 (dated copy) | |
| https://choukalos.com/files/briefs/market_research/ecommerce_platforms_brief_2026-11.html | 2026-11-01 | unmapped ⚑ | HTML brief | Ecommerce market research brief, November 2026 (dated copy) | |
| https://choukalos.com/files/briefs/market_research/ecommerce_platforms_reference.html | 2026-11-01 | unmapped ⚑ | HTML brief | Ecommerce annual reference (agent output) | |
| https://choukalos.com/files/briefs/market_research/smarthome_homesecurity_brief_2026-10.html | 2026-10-13 | unmapped ⚑ | HTML brief | Smart home & security brief, October 2026 (dated copy) | |
| https://choukalos.com/files/briefs/market_research/smarthome_homesecurity_brief_2026-11.html | 2026-11-01 | unmapped ⚑ | HTML brief | Smart home & security brief, November 2026 (dated copy) | |
| https://choukalos.com/files/briefs/market_research/smarthome_homesecurity_reference.html | 2026-11-01 | unmapped ⚑ | HTML brief | Smart home & security annual reference (agent output) | |
| https://choukalos.com/files/ai/tts_ab_script.txt | 2026-10-31 | unmapped ⚑ | TTS test script (text) | TTS A/B test script — pipeline test artifact | |
| https://choukalos.com/files/audio/neon_thunder.mp3 | 2026-10-03 | unmapped ⚑ (songs/clips candidate) | audio clip (MP3) | Audio clip — unverified; candidate for the songs/clips pillar | |
| https://choukalos.com/files/video/peanut_doc_final.mp4 | 2026-10-03 | unmapped ⚑ | video (MP4) | Personal/family video (peanut) — not a pillar | |
| https://choukalos.com/files/video/a-peanut-risky-business.mp4 | 2026-11-02 | unmapped ⚑ | video (MP4) | Personal/family video (peanut) — not a pillar | |
| https://choukalos.com/files/video/chuck_buck_rogers_25th.mp4 | 2026-10-03 | unmapped ⚑ | home video (MP4) | Personal home video — not a pillar | |
| https://choukalos.com/files/video/chuck_duck_dodgers_235.mp4 | 2026-10-03 | unmapped ⚑ | home video (MP4) | Personal home video — not a pillar | |
| https://choukalos.com/files/video/chuck_starwars_garage_crawl.mp4 | 2026-10-03 | unmapped ⚑ | home video (MP4) | Personal home video — not a pillar | |
| https://choukalos.com/files/video/sw-holiday-spoof.mp4 | 2026-11-17 | unmapped ⚑ | video (MP4) | Personal Star Wars holiday spoof — not a pillar | |
| https://choukalos.com/files/video/mf-test-3shot-lighthouse.mp4 | 2026-11-04 | unmapped ⚑ | video (MP4) | Media-pipeline test clip (3-shot lighthouse) — test artifact | |
| https://choukalos.com/files/images/retirement-infographic.svg | 2026-11-17 | unmapped ⚑ | infographic (SVG) | Personal retirement infographic — not a pillar | |
| https://choukalos.com/files/images/test.svg | 2026-11-17 | unmapped ⚑ | SVG | Test artifact — candidate for removal from the public drop (chuck) | |

## Gaps & flags

1. **Unmapped content (⚑, not silently dropped)**: 10 briefs (business/agent
   output — belongs to the Bluebovine/business domain, not the 6 personal-
   interest pillars; candidate for a separate Bluebovine inventory under
   charter O2), `tts_ab_script.txt` + `mf-test-3shot-lighthouse.mp4` +
   `test.svg` (pipeline/test artifacts — candidates for removal from the
   public drop, needs chuck), `neon_thunder.mp3` (songs/clips candidate —
   verify before mapping), peanut/home videos + `retirement-infographic.svg`
   (personal content outside the 6 pillars — candidate for the strategist's
   pillar review).
2. **Kalen lab post — source markdown missing**:
   `content/lab/kalen-the-ranger-vs-the-orcs-v2-new-media-pipeline.md` is
   absent from `main` `content/`; only the built HTML exists on the `deploy`
   branch. The source should be restored to the repo (two-branch flow:
   source → main → `./deploy.sh`).
3. **Arcade publish dates `unknown`**: the blog repo's git history is
   squashed (single commit, 2026-10-21, on both `main` and `deploy`), so
   per-game publish dates are not recoverable from git. Hugo post dates come
   from frontmatter; `/files/` dates from drop mtimes (publish = drop, live
   instantly).
4. **Board cross-check limited**: the kanban board (projects 5/6 done tasks)
   is not reachable from the executor sandbox (no board MCP/HTTP access) —
   cross-check was done via the repo (`main` + `deploy` trees), the live
   site, and the `/files/` drop. Spot-check: 12 URLs verified HTTP 200
   (2026-11-27): `/`, `/thoughts/hello-from-the-new-portal/`,
   `/lab/one-page-arcade/`,
   `/lab/kalen-the-ranger-vs-the-orcs-v2-new-media-pipeline/`, `/arcade/`,
   `/arcade/galaga.html`, `/arcade/star-wars.html`, `/files/`,
   `/files/tabs/back-in-black-tab.pdf`,
   `/files/video/elven_ranger_battles_orcs_v2.mp4`,
   `/files/images/porsche911-gentian.png`,
   `/files/ai/kaelen-thornwood-gurps-150.md`.
5. **`/files/files/`** (a `files/` subdir inside the public drop) is empty —
   no rows; kept in the tree, nothing to inventory.
6. **Performance column empty everywhere**: Plausible not wired (G3). Fill
   per-row when data lands; never backfill from memory.

---
updated 2026-11-27 — bootstrap (task 22): 67 rows (3 Hugo posts, 16 arcade
games, 48 `/files/` drop files); 21 unmapped/flagged.
