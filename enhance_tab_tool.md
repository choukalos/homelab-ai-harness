# Enhance the tab tool (`tab_pdf.py`) — missing shapes + solo-lane rework

> Planning doc. Canonical generator: `mcp/servers/media/tab_pdf.py` (used
> in-process by the `mcp_media` container's `media_render_tab_pdf` tool and
> by the standalone `homelab-tab-pdf` image, `scripts/tab-pdf/`).
>
> Trigger: 4 tabs published 2026-11-05 (Sweet Child O' Mine, Hurt,
> Californication, One) — several chords rendered as **"NO SHAPE / n/a"**
> because the open-shape library doesn't cover them, and the SOLO lane
> doesn't show note durations or techniques (hammer-ons, slides, …).
>
> **Status (2026-11-08):** Phase 1 + Phase 2 + Phase 3 + **Phase 4 all
> implemented and verified.** Phase 4 (b/v marks from the pipeline's
> `pitch_contour`) shipped 2026-11-08 — pipeline side by Matrix, renderer
> side in `tab_pdf.py` (see §B4), `mcp_media` rebuilt, all 4 published
> tabs re-rendered + republished 16:46 UTC, public sha256 verified
> (`docs/thor_validation_log.md` part 11). Phases 1–3 deployed
> 2026-11-06 13:53 UTC (see §C).

---

## A. Missing chord shapes

### A1. Confirmed missing (verified in the published PDFs)

Scanned all four published PDFs for `NO SHAPE` entries (pypdf text extract):

| Song | Chord(s) rendered "NO SHAPE" |
|---|---|
| Guns N' Roses — Sweet Child O' Mine | **B6** |
| Johnny Cash — Hurt | — (all shapes present) |
| RHCP — Californication | **F6** |
| U2 — One | **F6, G6** |

Root cause (confirmed against the live `analysis.json` of all 4 jobs,
2026-11-06): the pipeline's shape hint for these chords is
`{type: "open", base: null, fret: null}` — it says "open position" but
carries no fret data, so `chord_frets()` fell back to the hand-maintained
`OPEN_CHORDS` dict, which had no entry → renderer printed name + "n/a".
(Other unknown symbols like C#maj7/G#7 rendered fine because the pipeline
gave them `barre`/`power` shape hints, which the generator synthesizes.)

**Fix — added to `OPEN_CHORDS` (frets 6→1; interval-verified by
`test_chord_shapes.py`): DONE ✅**

| Chord | Frets | Tones produced | Check |
|---|---|---|---|
| **B6** | `x26442` | B D# F# G# | exact B6 (A6 shape x04220 + 2 frets) |
| **F6** | `133211` | F A C | standard open F6 (6th implied) |
| **G6** | `320000` | G B D E | exact G6 (open G, 1st string open adds the 6th) |

### A2. Recommended additions (same class of bug, not yet hit)

Verified by the interval checker — **all added to `OPEN_CHORDS`** ✅
(2026-11-06; "Tones produced" column corrected below — the original
laptop draft had 4 wrong note lists, and the D6 shape itself was wrong,
see the rejected list):

| Chord | Frets | Tones produced | Check |
|---|---|---|---|
| D6 | `xx0202` | D A B F# | exact D6 — **NOT `xx0212`** (that's the D7 voicing, already in the library) |
| E6 | `022100` | E G# B | standard E6 (6th implied) |
| A9 | `x02020` | A C# E G | standard A9 (9th implied) |
| D9 | `xx0232` | D A E F# | standard D9 (7th implied) |
| G9 | `353233` | G D F A | verified — 3rd implied, 9th present. Note: the "standard" `353433` is actually **G7** (no 9th), so `353233` is the correct G9 |
| Am9 | `x02012` | A C E G F# | verified — common open voicing (13th) |

**Rejected candidates** (failed interval verification — keep this list so
nobody re-proposes them blindly):

| Chord | Shape | Why rejected |
|---|---|---|
| G9 | `353533` | tones = G C D F → that's G7sus4, not G9 (no 9th at all) |
| E9 | `025100` | tones = E G G# B → that's E6 (4th string 5th fret is G, not A) |
| Bm9 | `x23210` | tones = B F A C E → F natural = b5; not a Bm9 voicing |
| Emaj9 | `020100` | tones = E G# B D → that's an **Emaj7** voicing (D = 7th, no 9th at all). Emaj7 is already in the library and renders fine |
| D6 | `xx0212` | tones = D A C F# → that's a **D7** voicing (C = 7th of D, not the 6th). The real open D6 is `xx0202` |

All five rejected shapes are regression-guarded in
`test_chord_shapes.py::test_rejected_candidates` (they must stay out of the
library and keep failing the interval check).

### A3. Structural fixes (kill the whole "n/a" class, not just 3 entries)

1. **Synthesized-barre fallback. DONE ✅** `_synth_barre_frets()` in
   `tab_pdf.py`: when a symbol is unknown and the shape hint is `open`
   (or absent), find the root fret on the 5th string (A-shape) and 6th
   string (E-shape), pick the lower one, and reuse `_barre_frets()`.
   Quality handling beyond major/minor: 7th chords add the 7th
   (E-shape: 4th string, A-shape: 3rd string — the exact E7/A7 patterns),
   maj7 adds 7th + 11th (the exact Emaj7/Amaj7 patterns); 9/6 render the
   triad(+7) and the quality is left to the printed name. Labeled
   `barre @ N (synthesized)`. Flat spellings (Bb, Db, …) handled via
   `NOTE_IDX`. Unparseable symbols (e.g. `N.C.`) still render honest "n/a".
2. **Report coverage in the render result. DONE ✅** `render()` returns
   `missing_shapes` (fell through to n/a) and `synthesized_shapes`
   (fallback used), computed by `shape_coverage()` / `chord_status()`.
   The `media_render_tab_pdf` MCP tool surfaces both (result dict is
   passed through as-is — no server.py change needed beyond the tool
   description). **Open question resolved: yes**, missing shapes also
   appear as a visible note line in the PDF under the CHORDS grid:
   "Chords without a known shape (name only, verify fingering): …".
3. **Unit-test the shape library. DONE ✅** `mcp/servers/media/
   test_chord_shapes.py` (plain-python script, pytest-compatible, no
   network): for every `OPEN_CHORDS` entry, frets → note names → assert
   (a) root present, (b) no tone outside the chord's theoretical tones +
   allowed extensions. Extension policy is documented in the test: 9th
   chords may carry the 13th; 6th chords the 9th (6/9); 7th chords the
   13th (C9/F9 voicings); sus4 the 3rd (conventional) + 9th; maj7 the
   11th/13th (the E-shape maj7 family carries the 13th at the root and
   the 11th elsewhere). Run: `python3 test_chord_shapes.py` — **55/55
   entries pass**.
4. **Data-file the library. SKIPPED (deliberate).** Moving `OPEN_CHORDS`
   to `chord_shapes.json` doesn't simplify the test (it imports the dict
   directly) and still needs a container rebuild — no benefit.

**The checker caught 5 pre-existing bad entries (fixed 2026-11-06):**

| Chord | Old shape | Problem | New shape |
|---|---|---|---|
| Csus4 | `x33020` | tones C C# E F G — C# = b7 | `x33030` (standard: C D E F G) |
| Gsus4 | `332003` | tones G C E B — B = 6th (G6 color) | `330033` (standard: G C D) |
| F#m | `x27422` | tones B F# A F# — no 5th, 4th in place of 3rd | `244222` (standard E-shape @2: F# A C#) |
| F#m7 | `x24252` | tones B F# A E F# — no 5th | `242222` (standard E-shape m7 @2: F# A E) |
| F#maj7 | `x24362` | tones F# A# B F# — no 3rd | `244362` (standard E-shape maj7 @2: F# A# C# B E) |

Note on SCOM: the pipeline detected the song in **B major** (common
reference: A major). If it's ever re-transcribed with `target_key="A"`,
the chord set shifts to A6/F#6/Bmaj7/… — the library above covers the
natural outcomes either way (F#6 = F6 + 2 frets is not in the open
library, but the synthesized-barre fallback would cover it; add
`F#6: [3, 5, 5, 4, 3, 3]` if a re-transcribe ever needs it).

---

## B. SOLO lane rework (note durations + techniques)

### B1. Current state (why it's weak)

`_solo_cell()` renders each measure as 6 fixed rows (one per string),
each row ≤ 12 fret digits, consecutive repeats collapsed (`1111111` →
`11111`). It uses **only `start_s`** per note. Consequences:

- no idea **how long** to hold a note (the repeat-collapse actively
  destroys duration info),
- no **technique** info (hammer-on? pull-off? slide? separate strokes?),
- all 6 strings shown even when only 2 are used → hard to read,
- no beat grid, no dynamics.

### B2. Data already available (no pipeline change needed for v1)

Lead note events in `analysis.json` carry (schema **confirmed against the
live 2026-11-05 job artifacts, 2026-11-06** — every lead note has all
fields; note roles are `lead` / `bass` / `accompaniment`):

| Field | Use |
|---|---|
| `start_s`, `end_s` | **note duration** (already there — just unused!) |
| `tab.string`, `tab.fret` | placement |
| `amplitude` | dynamics (optional, v2; range in QA data: 0.23–0.75) |
| `freq_hz` | single value per note → **not enough for bend detection** (see B4) |
| `midi` | (bonus) absolute pitch — useful for cross-checks |

**Real-data profile of the 4 QA songs** (2026-11-06, using the
generator's own `bar_length()` = 240/bpm):

| Song | BPM | lead notes | measures w/ notes | max notes/meas | max fret span | overlaps (h/p candidates) | slides (<0.25 beat) |
|---|---|---|---|---|---|---|---|
| SCOM | 126.0 | — | 153 | 9 | 14 | 222 | 90 |
| Hurt | 92.3 | — | 87 | 13 | 15 | 213 | 79 |
| Californication | 97.5 | 102 | 135 | 9 | 14 | 255 | 95 |
| One | 90.7 | 13 | 108 | 11 | 14 | 248 | 92 |

Design implications: the 12-note dense-measure fallback threshold is
right-sized (only 1 measure in Hurt exceeds it); the 7-fret window will
split into two boards frequently (spans 14–15); there's plenty of
overlap/slide material to tune the technique thresholds against.

### B3. Design — per-measure fretboard boards (chord-diagram visual language)

Each measure in the SOLO lane gets a **mini fretboard board** — the same
visual language as the CHORDS grid (string lines, fret lines, orange
dots, starting-fret annotation) — but the dots are **notes placed at
(string, fret)**, with **duration**, **time order**, and **technique
connectors** (hammer-on / pull-off / slide / hold). Vector rendering
(positioned divs or inline SVG — crisp in the PDF, no raster images),
replacing the monospace `<pre>` tab cells. All deterministic
post-processing on the note events (same pattern as the chord stage —
no LLM involved).

**Why a board instead of tab digits:** the reader already knows how to
read the CHORDS diagrams on page 1; the solo board is "the same kind of
board, but the dots are notes in time order, with connectors showing how
to connect them." It encodes all four dimensions (string, fret, time,
duration) natively, which tab digits can't.

**Geometry** (per measure, reusing the chord-diagram CSS):
- 6 vertical string lines (low E left — same as the chord diagram),
  fret lines horizontal.
- **Fret window**: min→max fret used in that measure (padded by 1,
  clamped to 4–7 lines) + a **starting-fret annotation** (`4f`) when the
  window doesn't start at the nut — exactly like the barre chord
  diagrams.
- Fixed board size (~40pt × 50pt, same as the chord tokens) → 7 boards
  per row, measure-aligned with the VOCALS / RHYTHM lanes.
- Strings with no notes in that measure drawn dim (light gray).

**Note glyphs** (one dot per note event):
- Dot at (string, fret) — same dot style as the chord diagram.
- **Dot size ∝ duration** (`end_s − start_s` in beats; clamped 3–8pt)
  — "how long to play it" at a glance.
- **Time-order badge** (1, 2, 3…) beside the dot — the playing order
  within the measure.
- **Duration tail (ON by default)**: thin line extending right from
  the dot, length ∝ beats — the primary "how long to play it" cue,
  alongside the dot size.
- Same (string, fret) repeats: dots stacked with a small vertical
  offset + `×n` count.

**Technique connectors** (between consecutive notes in time order;
deterministic rules, `beat = bar/4`):

| Condition | Inference | Board rendering |
|---|---|---|
| next.start ≤ cur.end (overlap), fret **up** | hammer-on | line dot A → dot B, `h` badge at midpoint |
| next.start ≤ cur.end (overlap), fret **down** | pull-off | line, `p` badge |
| 0 < gap < 0.25·beat | slide (legato) | connector line with a small **arrow icon** at the midpoint, pointing up/down (direction) |
| gap ≥ 0.25·beat | separate strokes | no connector |
| same fret, overlapping | hold / vibrato candidate | small **wavy-line (sine) icon** beside the dot (low confidence) |
| fret jump > 4 with a gap | position shift | no mark (avoid noise) |

Hammer-on / pull-off keep the standard `h` / `p` text badges; slide and
hold/vibrato use small **vector glyph icons** (inline SVG paths baked
into the generator — no external assets, no LLM) so the boards stay
clean and visually consistent at any zoom.

Thresholds (0.25·beat etc.) go in named constants with a comment —
tune against the 4 QA songs.

**Timing**: a 4-beat ruler under each board (4/4 — same assumption the
VOCALS lane already makes); time-order badges + dot size carry the
within-measure timing.

**Fret-window overflow**: if a measure's note range exceeds 7 frets,
split the measure into two side-by-side boards (low-fret window /
high-fret window) with a boundary tick. Deterministic rule, documented.

**Dense-measure fallback**: if a measure exceeds 12 lead notes (or
collisions exceed the stack offset), fall back to the current compact
text tab for that measure only — a deterministic guard that keeps the
layout stable.

**Fingering (finger numbers)**: not inferable from the data (human
judgment). v2: deterministic heuristic (index on the lowest fret of a
group, adjacent fingers for adjacent frets) with optional validated LLM
polish; out of scope for Phase 3.

**Solo key (standard key, mandatory)**: a dedicated key panel at the
top of the SCORE part, so anyone reading the tab can decode the boards
without prior context. Two parts:
1. **Example board** — a small mock board with one of each element,
   labeled with leader lines: a dot with duration tail + time-order
   badge, an `h` connector, a `p` connector, a slide arrow icon, a
   vibrato wavy icon, a dimmed (unused) string, and the 4-beat ruler.
2. **Mark table** — dot size / tail = hold time · number = play order
   · `h` = hammer-on · `p` = pull-off · arrow = slide (direction =
   arrow) · wavy line = hold/vibrato (inferred) · dim string = unused
   in this measure · starting-fret label (e.g. `4f`) = first fret
   shown.

**Dynamics (v2, optional)**: `amplitude` percentile → dot color/weight
for soft notes.

**Confidence footer** (already in the page footer): techniques are
inferred from timing/fret patterns — medium confidence; verify against
the recording.

### B3b. Phase 3 implementation blueprint (function-level, 2026-11-06)

Concrete plan for implementing B3 in `tab_pdf.py` (all deterministic,
no LLM; weasyprint handles positioned divs and inline SVG alike —
recommend **inline SVG per board**: one `<svg>` element per measure
board makes connectors/icons/rotated lines trivial and keeps the HTML
flat):

1. **Data prep — `parse_analysis_sections()`**: extend the `lead` events
   to carry `end_s` (currently only `t`/`string`/`fret` are kept):
   `lead.append({"t": …, "end": float(n.get("end_s", …)), "string": s,
   "fret": f, "amp": n.get("amplitude")})`. Sort by `t`.
2. **`SOLO_STYLE = Enum`** — `class SoloStyle(str, Enum): BOARD = "board";
   TEXT = "text"`; default `BOARD`. (No `both` — the text tab serves only
   as the dense-measure fallback.)
3. **Per-measure note grouping** (in `build_score_section_html`,
   alongside `words_by_meas`/`chords_by_meas`): `lead_by_meas[m] =
   [events in [t0, t0+bar)]` — reuse `_measure_of()`.
4. **`_solo_board_svg(notes, bar, beat)`** — one measure's board:
   - `fret_lo = max(0, min(frets) - 1)`, `fret_hi = min(20, max(frets) + 1)`;
     `nlines = clamp(fret_hi - fret_lo + 1, 4, 7)`; if
     `max - min > 7` → **two side-by-side boards** (split at the median
     fret), each with a boundary tick.
   - SVG viewBox ~40×50pt (same as `.ct-diagwrap`); 6 vertical string
     lines (`.sb-str`, dimmed class `.sb-str-dim` when the string has no
     notes in the measure), horizontal fret lines; starting-fret label
     `f"{fret_lo + 1}f"` top-left when `fret_lo > 0` (reuse the barre
     chord annotation style).
   - Dots: `<circle>` at (string, fret), `r` = 1.5 + 1.5·beats clamped
     1.5–4 (3–8pt); time-order badge `<text>` (1, 2, 3…) offset upper-
     right; duration tail: thin `<line>`/`<rect>` from the dot rightward,
     length ∝ beats (ON by default).
   - Same (string, fret) repeats: stack with 1.5pt vertical offset +
     `×n` text.
   - **Connectors** between consecutive notes (time order), constants
     named + commented: `SLIDE_GAP_MAX = 0.25` (·beat),
     `JUMP_NO_MARK = 4` (frets):
     - overlap + fret up → line + `h` badge at midpoint;
     - overlap + fret down → line + `p` badge;
     - `0 < gap < SLIDE_GAP_MAX·beat` → line + arrow icon (SVG path,
       direction = up/down);
     - same fret + overlap → wavy-line icon (SVG path, 3-hump sine);
     - else → nothing.
   - 4-beat ruler under the board (4 ticks + numbers, 4/4).
5. **Dense-measure fallback**: `len(notes) > 12` (or > 2 dots colliding
   at the same (string, fret) beyond the stack offset) → render that
   measure with the existing `_solo_cell()` text instead (keep the
   function; it becomes the fallback, not the default).
6. **Solo key panel** — `solo_key_panel()`: rendered once, at the top of
   the SCORE part (next to the part kicker): a mock board with one of
   each element + leader-line labels, and the mark table (2 columns,
   ~7pt text). Deterministic mock data (no song data).
7. **`_score_band_html()`**: replace the SOLO row's
   `<pre class='solo-cell'>` cells with the board SVG (or the text
   fallback); keep `MEASURES_PER_ROW = 7` and measure alignment.
8. **CSS**: new `.sb-*` classes (board, str, str-dim, fret, dot, badge,
   tail, ruler, label); reuse `.ct-*` colors (#b0512f dots, #4a4a55
   strings).
9. **QA**: render all 4 QA songs in the `mcp_media` image (pattern used
   2026-11-06: `docker run --rm -v <dir>:/work ai-mcp-mcp_media:latest
   python …` with `sys.path.insert(0, '/work')`), `pdftotext` for
   structure + `pdftoppm -png` for visual check; verify: zero missing
   boards, fallback fires only on Hurt's dense measure, technique
   badges present in SCOM's intro (known hammer-ons) and One's verse
   (known slides), boards stay measure-aligned with VOCALS/RHYTHM.

### B4. What the current data CANNOT do (and where the fix lives)

**Bends and vibrato.** A bend is a pitch ramp *inside* one note event;
the DSP emits a single `freq_hz` per note, so bends/vibrato are invisible
to `tab_pdf.py` today. Detecting them requires the pipeline's DSP (on the
**GPU host / Matrix**, stage 4/5) to emit a pitch contour per note
(e.g. freq at onset/mid/offset, or a small contour array). That's a
pipeline-side change; `tab_pdf.py` just renders whatever it's given.
Track as a separate work item (Phase 4) — don't scope it into the
tab_pdf rework.

**DONE 2026-11-08 (both sides).** The pipeline now ships a per-note
`pitch_contour` (5 samples across the note's duration; pitch deviation
from the note's nominal pitch — assumed **semitones**, ⅓-quantized,
ranges seen: [-1.67, 2.33]; confirm against
`docs/transcribe_pipeline_spec.md` on the GPU host). `tab_pdf.py`
renders the marks:

- `_contour_mark(pc)` → `"b+"` / `"b-"` / `"v"` / None. Bend: ≤1
  direction reversal + |onset→offset rise| ≥ `SOLO_BEND_RISE` (1.0
  semitone) + total deviation ≥ `SOLO_BEND_DEV` (0.6). Vibrato: ≥2
  reversals + total deviation ≥ `SOLO_VIB_DEV` (0.5). Conservative on
  purpose — on dense distorted mixes the contour is tracking noise;
  only clear sustained patterns are marked.
- SOLO lane: bend = arc through the dot (direction = pitch travel) +
  `b` badge; contour vibrato = the existing wave glyph. Text-tab
  fallback appends `b`/`v` to the fret digit. SOLO KEY panel gained a
  bend demo note + legend rows. `render()` reports `bend_marks` /
  `vibrato_marks`; a PDF note line appears when > 0.
- Back in Black (first contour job): 13 bends + 18 vibrato over 328
  lead notes; the other 3 published tabs predate the pipeline change
  (0 marks — backward compatible). Tests: `test_solo_marks.py` (5
  suites). Deployed + all 4 tabs republished 2026-11-08 16:46 UTC
  (`docs/thor_validation_log.md` part 11).

### B5. Rendering notes

- Board = positioned divs (consistent with the chord diagram) or inline
  SVG — **decided: inline SVG** (see B3b.4); WeasyPrint handles
  line/circle/path/text.
- Technique icons (slide arrow, vibrato wavy line) are inline SVG paths
  in the generator — deterministic, no asset files.
- CSS reuse: `.ct-*` classes for strings/frets/dots; new `.sb-*`
  (solo-board) classes for badges, tails, ruler, dimmed strings.
- Keep `MEASURES_PER_ROW = 7` and the measure alignment with
  VOCALS/RHYTHM.
- Config flag `solo_style` as a **string enum** (`enum.Enum`; members
  `board` (default) and `text`) — an enum so new members (e.g.
  `both`) can be added later without breaking callers. No `both` for
  now: the text tab serves only as the dense-measure fallback, not a
  parallel view.

---

## C. Deployment & rollout

**Where things live** (answers the "does this need Matrix?": **no**):

| Piece | Location | Role |
|---|---|---|
| `tab_pdf.py` (the code being changed) | this repo, `mcp/servers/media/` | canonical source |
| `mcp_media` container (renders in-process) | **thor** (media host) | `media_render_tab_pdf` tool |
| Job artifacts (analysis.json, tab.md, lyrics.txt) | **Matrix** (GPU host, 192.168.4.55) | fetched by mcp_media itself — untouched |
| `publish_file` skill (blog drop zone) | **thor** | republish with `overwrite=true` |

**Deploy path** (no SSH from the Mac; thor doesn't auto-sync the repo):

1. Commit + push to `github.com/choukalos/homelab-ai-harness`.
2. On thor: `cd /home/chuck/homelab && git pull && docker compose -f compose/compose.mcp.yml build mcp_media && docker compose -f compose/compose.mcp.yml up -d mcp_media` (or `./homelab.sh rebuild mcp`).
3. Re-render (artifacts already on the GPU host — no re-transcription):
   `media_render_tab_pdf(job_id, title, artist, slug)` per song.
4. Republish: `publish_file` skill, `subdirectory=tabs`,
   `overwrite=true`, same slug-prefixed names.
5. QA: standalone `homelab-tab-pdf` image + poppler (`pdftotext`,
   `pdffonts`) for regression; verify zero `NO SHAPE` entries and visual
   check of the new solo lane on all 4 songs.

**QA artifacts** (job IDs from the 2026-11-05 run):
`7184c0486ef7` SCOM · `5b159972e526` Hurt · `65083db9057d` Californication
· `f6b1d2fb2f98` One.

### Phases

| Phase | Scope | Effort | Status |
|---|---|---|---|
| **1 — bugfix** | A1 (B6/F6/G6) + A2 safe set (D6/E6/A9/D9/G9/Am9) | ~30 min + 1 rebuild on thor | **DONE 2026-11-06** (code + tests + local render QA; deployed + republished 13:53 UTC) |
| **2 — robustness** | A3 (synthesized fallback, `missing_shapes`/`synthesized_shapes` in result + PDF header note, `test_chord_shapes.py`, 5 pre-existing library fixes) | small | **DONE 2026-11-06** (same deploy) |
| **3 — solo rework** | B3 (per-measure fretboard boards per B3b: duration-sized dots + duration tail (default on), time-order badges, technique connectors with vector slide/vibrato icons, solo key panel, fret window + starting-fret label, beat ruler, dense-measure fallback, `solo_style` enum `board`\|`text`) + visual QA on all 4 songs | the big one | **DONE 2026-11-06** (code + QA in §D; deployed + republished 13:53 UTC) |
| **4 — pipeline-side (Matrix)** | B4: pitch-contour note events so bends/vibrato become detectable; `tab_pdf.py` renders `b`/`v` marks when present | separate work item, GPU-host DSP | **DONE 2026-11-08** (pipeline shipped `pitch_contour` — Matrix; renderer: `_contour_mark` + board arc/wave + text-tab `b`/`v` + key-panel legend + `bend_marks`/`vibrato_marks` reporting; `test_solo_marks.py` 5/5; container rebuilt; all 4 tabs republished 16:46 UTC — `docs/thor_validation_log.md` part 11) |

### Open questions

- ~~Should `missing_shapes` also appear as a visible note line in the PDF
  header?~~ → **yes, done** (note line under the CHORDS grid).
- Technique thresholds: validate against SCOM's intro (known hammer-ons)
  and U2 One's verse (known slides) before tuning. (QA data profiled:
  213–255 overlaps and 79–95 sub-quarter-beat gaps per song — plenty of
  material; see B2 table.)
- Fingering (finger numbers): deferred to v2 (B3).

---

## D. Verification log (2026-11-06, this session)

- **Root cause confirmed** against live `analysis.json` of all 4 QA jobs
  (fetched from `192.168.4.55:8189/files/<job>/analysis.json`): B6/F6/G6
  carry `{type: "open", base: null, fret: null}` hints; note-event schema
  confirmed (`start_s`/`end_s`/`amplitude`/`freq_hz`/`midi`/
  `tab.{string,fret}`; roles `lead`/`bass`/`accompaniment`; no lead note
  missing `end_s` or `tab`).
- **Interval checker** (promoted to `test_chord_shapes.py`) verified every
  proposed shape and the whole 55-entry library. Findings: A1 all pass;
  A2 pass except D6 (was the D7 voicing — fixed to `xx0202`) and Emaj9
  (is an Emaj7 voicing — moved to rejected); all 3 original rejected
  candidates confirmed rejected; G9/Am9 cross-checks resolved (kept);
  **5 pre-existing entries fixed** (Csus4/Gsus4/F#m/F#m7/F#maj7 — see A3).
- **Render smoke test** in the real `ai-mcp-mcp_media:latest` image
  (weasyprint + fonts): all 4 QA songs re-rendered — **zero "n/a" /
  "NO SHAPE"** entries; B6/F6/G6 render as proper OPEN diagrams;
  `missing_shapes`/`synthesized_shapes` empty for all 4. Synthetic song
  with `Badd9` + `N.C.`: Badd9 → synthesized barre diagram labeled
  "(SYNTHESIZED)"; N.C. → honest n/a + visible header note; both
  reported in the result dict.
- **Deploy (DONE 2026-11-06 13:53 UTC)**: `mcp_media` rebuilt on thor from
  repo HEAD (container `tab_pdf.py`/`server.py` byte-identical to repo);
  all 4 tabs re-rendered via live `media_render_tab_pdf` (real
  title/artist) and republished with `publish_file`
  (`subdirectory=tabs`, `overwrite=true`) at 13:54 UTC; public URLs
  verified live + sha256-identical to local files (all 4; SCOM 13 pages,
  SOLO KEY panel present). Validation log: `docs/thor_validation_log.md`
  part 10.

### D2. Phase 3 (solo boards) verification log (2026-11-06, this session)

QA pattern: `docker run --rm -v /tmp/tabqa:/work -v <repo>/mcp/servers/media/tab_pdf.py:/src/tab_pdf.py:ro ai-mcp-mcp_media:latest python qa_*.py` (working-tree `tab_pdf.py` mounted at `/src`; artifacts fetched from `192.168.4.55:8189/files/<job>/`).

- **Zero missing boards**: board count = lead measures + fret-window
  splits + 1 key panel (SCOM 153→231 · Hurt 87→120 · Cali 135→163 ·
  One 108→150); zero "NO SHAPE" / "n/a" in any PDF (Phases 1–2
  regression held).
- **Dense-measure fallback**: fires exactly once — Hurt's single
  >12-note measure (matches the B2 profile); that measure renders the
  legacy 6-line text tab, all others render boards. `render()`'s
  `solo_fallbacks` now accumulates across sections (was `=` — QA
  caught it).
- **Technique badges where expected**: SCOM intro h=6/p=14 (known
  hammer-ons); One's verse 2 slide arrows (known slides); song-wide
  h/p/slide/vib: SCOM 43/52/66/66 · Hurt 58/56/64/64 ·
  Cali 80/74/75/76 · One 74/59/72/98. No threshold tuning needed.
- **Geometry clean** (image-blind visual check: every SVG coordinate
  inside its viewBox, every solo row ≤ 7 measure cells, board group
  width ≤ 460pt): 0 issues across all 4 songs.
- **SOLO KEY panel** renders once at the top of the SCORE part (page 1)
  with example board + leader labels + mark table; suppressed in `text`
  style (it explains the boards).
- **`text` style regression**: all 4 songs render with the legacy tab —
  no boards, no key panel, `solo_fallbacks=0`; CLI `--solo-style text`
  works.
- **MCP tool**: `media_render_tab_pdf` gained `solo_style` ('board'
  default | 'text'); result dict now includes `solo_style` +
  `solo_fallbacks` (tool description + README updated).