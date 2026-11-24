---
name: infographic
description: Generate themed single-page HTML infographics, cheat sheets, and stat collages from source material (rulebooks, digests, data, photos) — self-contained 1080px pages with masthead, stat tables, character packages, and photo grids, rendered to retina PNG via headless Chrome. Use when the user wants a reference sheet, cheat sheet, one-page visual summary, or stat collage.
---

# Infographic — themed single-page HTML infographics

Build themed infographics, cheat sheets, and stat collages as **one self-contained HTML
page** — fixed 1080px wide, no `<script>`, no external assets (an optional Google Fonts
`<link>` and a local masthead banner are the only exceptions) — then render it to a retina
PNG. Proven outputs: GURPS TL3 character-creation + armory sheets, Mekton Zeta character /
mech creation, Zootopia test-drive citation, retirement-readiness sheet, TL3 dungeon
one-shots (batch of 4).

**Reference library (Mac):** `~/Code/test-pi/gurps-tl3-infographic/` (design.md, part*.html,
manifest.json, gen_part3.py), `~/Code/test-pi/mekton-zeta-{character,mech}-creation/`
(manifest-driven chunks, built from a kb digest), `~/Code/test-pi/jeep-infographic/`,
`~/Code/test-pi/retirement/` (html + svg + png), `~/Code/infographics/tl3-dungeon-one-shots/`
(gen_sheets.py batch generation).

## When to use

- Game-system cheat sheets / character-creation references (GURPS, D&D, Mekton Zeta, …).
- Stat collages from data (equipment/armory tables, budgets, retirement readiness).
- Photo/illustration collages with themed framing (test-drive citation, event recap).
- Batch sheet sets (dungeon one-shots, party character sheets) from structured data.

## Ground rules

1. **Source first — never from memory.** Locate the authoritative source (rulebook PDF,
   existing digest, data file, photos). Extract numbers programmatically (pypdf in a venv,
   parse the digest, read the data file) and read the actual table rows. Every number on
   the sheet must be verifiable against the source; note what the source is missing.
2. **Verify the math.** Sum every line item yourself; if a stated total disagrees with the
   sum, use the sum and flag it. Cross-check derived numbers (budgets, leftovers,
   percentages) before writing them into content.
3. **Label provenance.** Mark values not in the source as house values ("House value — not
   in the Basic Set"); keep source notation (damage formulas, skill names) verbatim.
4. **Chunk discipline.** Write content as small part files (~1–7KB each) or a manifest of
   small .md chunks — never one giant write (oversized writes get truncated mid-file and
   produce broken output). Verify each file landed complete (tail it) before the next.

## Project layout

```
<project>/
├── design.md            # theme + layout spec (palette, fonts, section order, data source)
├── content.md           # single source of truth for the numbers (extracted from source)
├── chunks/             # small .md sections (manifest-driven builds)
├── part0_head.html     # DOCTYPE, <style> theme CSS, masthead
├── partN_*.html        # one section per part (fragments only — no <html>/<style>/closes)
├── partN_foot.html     # footer + closing tags
├── manifest.json       # (optional) sheets, chunk lists, masthead text, theme
├── <Sheet>.html        # assembled infographic
└── <Sheet>-qa.png      # rendered screenshot (QA evidence)
```

Part files are concatenated in order: `cat part0_head.html part1_*.html … partN_foot.html
> <Sheet>.html`. The head part owns the DOCTYPE/style/masthead; only the last part closes
`.page`/`body`/`html`.

## HTML structure (single self-contained page)

- **Canvas:** `body` fixed at 1080px wide with a dark background; a `.page` container
  carries the themed background (subtle radial gradients over a base color).
- **Masthead:** banner image (local `banner.png`, `center/cover`) or a gradient block, with
  a dark bottom-gradient overlay for legibility; inside: `kicker` (small-caps source line),
  display-serif title with an accent span (`.tl`), one-line subtitle, and `chips`
  (source + 2–3 headline stats as pills).
- **Sections:** numbered head — roman numeral + display-serif title + right-aligned page
  ref — with a gold rule under. One section per part file.
- **Layout patterns** (pick per content; all are CSS-only):
  - `grid2` — two equal columns; `panel` — bordered box with a display-serif `h3`.
  - `cols3` — `column-count: 3` for long entry lists (advantages/disadvantages).
  - compact tables (`.tbl`) — small-caps header row, right-aligned numeric cells,
    `TOTAL` row highlighted.
  - entry rows — name (bold) + right-aligned cost badge (`.cost`; `.neg` for negative).
  - chips, callout boxes (SCN-style), ladders (label/value steps), flow strips
    (numbered step boxes with arrows) for process/how-to content.
  - stat boxes — big number + small-caps label + points (character packages).
  - photo collage — image grid with captions (test-drive / citation style).
- **Footer:** field notes (bulleted, terse, ≤ ~70 chars each) + credit line (source left,
  theme/edition right).
- **Tap-friendly:** no hover-dependent content, ≥12px body text, generous spacing,
  everything readable at 1× on a phone. **Print-friendly:**
  `print-color-adjust: exact`; for print sheets use a fixed page size (e.g. 1100×1220)
  so the PNG/PDF is a clean single page.
- **No `<script>`, no external assets** — the page must render offline from `file://`
  (Google Fonts `<link>` is the accepted exception; fall back to the system stack).

## Theme / branding

A theme = CSS variables in `:root` (palette + fonts) + the structural CSS. Proven themes:
**parchment** (medieval GURPS — Cinzel display + Alegreya Sans body, oxblood/gold),
**mecha** (Mekton Zeta), **ticket** (Zootopia PD — Bangers + Nunito), **navy** (retirement —
system fonts). To add a look, copy an existing theme's CSS and adjust `:root` (palette,
fonts) plus structural tweaks; keep a display serif for titles and a humanist sans for
body. Masthead banners: source or generate a wide image (1080px+); the dark gradient
overlay is what keeps the title legible.

## Assembly

- **Hand-assembled:** write the part files, `cat` them in order, spot-check the seams
  (no double `<style>`, balanced tags at the joins).
- **Manifest-driven (cheat-sheet builder):** `python3 <cheat-sheet skill>/scripts/build.py
  <project-dir>` — reads `manifest.json` (sheets, chunks, masthead `page` block, `theme`),
  concatenates the .md chunks, converts to themed HTML (md subset — headings, pipe tables,
  bullets, bold/italic; numeric cells right-align, `TOTAL` rows highlight).
- **Batch:** a Python generator (the `gen_sheets.py` pattern) renders N sheets from
  structured data + a shared theme CSS — use it for sheet sets (dungeon one-shots,
  character sheets) instead of hand-writing each page.

## Render to PNG

Headless Chrome (Mac):

```sh
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless --disable-gpu \
  --no-sandbox --hide-scrollbars --window-size=1080,<page height> \
  --screenshot=<Sheet>-qa.png file://<abs path to .html>
```

- Size the window to the full page height so nothing clips (render once tall, measure
  where content ends, re-render at that height).
- Retina Macs produce 2160px-wide PNGs (2×) — that is the house standard; do not downscale.
- Optional vector output: hand-write an SVG variant for crisp scaling (retirement pattern).

## QA gate (do not skip)

1. **Structure:** balanced tags (`<table>`, `<div>`, `<tr>`), no leaked markdown
   (`**`, `## `, raw `|` lines) in the HTML, no unclosed fragments at the seams.
2. **Content:** every section present in order; spot-check key numbers against
   `content.md` / the source.
3. **Visual:** render the PNG and inspect it (open it or vision-analyze) — overflow,
   column balance, masthead legibility, badge alignment. Fix overflow by trimming text or
   rebalancing columns, then re-render.
4. **Report:** final file sizes (html + png), what was verified against the source, and
   any flagged source gaps / house values.

## Digest tie-in

When the source is a `game_system` digest (kb_gaming etc.), build the sheet **from the
digest** (page refs = printed pages, printed = PDF page − 1) and carry the digest's
flagged uncertainties into the sheet's field notes (Mekton pattern — "built from the
kb_gaming digest … flagged spots: …").
