# tab-pdf — song tab → PDF

Renders a transcribed song (the media pipeline's `tab.md` + `lyrics.txt` +
`analysis.json`) into a print-quality PDF song sheet. Deterministic — no LLM.

**Primary path (any client, any machine):** the `mcp_media` MCP tool
**`media_render_tab_pdf(job_id, title?, artist?, slug?)`** — it fetches the
job's artifacts from the GPU host and renders in-process (WeasyPrint + the
song-sheet fonts are baked into the `mcp_media` image). The generator's
**canonical source is `mcp/servers/media/tab_pdf.py`** (importable
`render()` + CLI `main()`).

This directory holds the **standalone/QA wrapper** image
(`homelab-tab-pdf:local`) around the same generator, with poppler-utils for
`pdffonts` / `pdftotext` QA. Use it when you want a one-off render from a
local song dir without going through the pipeline.

## Build (from the REPO ROOT — the generator lives in mcp/servers/media/)

```bash
docker build -t homelab-tab-pdf:local -f scripts/tab-pdf/Dockerfile .
```

## Usage (standalone)

```bash
docker run --rm -v /home/chuck/data/media/generated/pipeline:/work \
  homelab-tab-pdf:local /work/<slug> -o /work/<slug>/<slug>-tab.pdf \
  --title "Riptide" --artist "Vance Joy"
```

`--title`/`--artist` override the LLM-guessed header — pass the real song
identity whenever it's known (the pipeline only sees audio).

## Output

- **Header**: title (Playfair Display), artist, meta chips (KEY / BPM /
  TUNING / CAPO from `analysis.json`), plus any capo/transpose/power-chord
  note lines from the tab header.
- **CHORDS (first)**: a grid of fixed-size chord fingering diagrams
  (name + 6-string × 4-fret shape + X/O markers + starting-fret
  annotation), one per unique chord. Shapes are deterministic: power/barre
  generated from the pipeline's `shape` hint (base E/A + fret, major/minor
  from the symbol), open chords from a standard-shape library; unknown
  shapes render name-only.
- **SCORE (SING & PLAY)**: one measure-aligned block per section (7
  measures/row) with three lanes, so you can sing & play at once (with a
  friend):
  - **VOCALS**: the section's words in order, each placed in the measure it
    starts in (ASR word timestamps vs the BPM-derived measure length, 4/4
    assumed); a mini chord diagram floats above the measure where each chord
    change lands (chord event times) — the shape is visible at the exact
    word you're singing.
  - **RHYTHM**: chord diagrams, one per measure (instrumental sections get
    this instead of the vocals lane).
  - **SOLO**: a compact 6-string tab of the section's lead notes (string
    letter + fret digits, ≤12 chars, repeats collapsed), measure-aligned —
    you can see where the solo falls against the singing/rhythm, so a
    friend can play the SOLO lane while you sing.
- **Footer** (every page): "strong draft; verify against the recording" +
  page numbers. Letter size.

## QA

```bash
docker run --rm -v <dir>:/work --entrypoint pdffonts  homelab-tab-pdf:local /work/<slug>-tab.pdf
docker run --rm -v <dir>:/work --entrypoint pdftotext homelab-tab-pdf:local -f 1 -l 1 -layout /work/<slug>-tab.pdf -
```

Expected embedded fonts: `Inter`, `Playfair-Display-Bold`, `JetBrains-Mono`.
If you see `DejaVu-*` instead, a font failed to load — check
`/usr/share/fonts/tabpdf/` in the image.

## Notes

- WeasyPrint 70 resolves fonts through Pango/fontconfig; its `@font-face`
  path cannot instantiate the JetBrains Mono variable font, so the CSS uses
  fontconfig family names (`'JetBrains Mono'`, `'Playfair Display'`,
  `'Inter'`) rather than `@font-face`.
- Fonts are variable TTFs from google/fonts baked into the image at
  `/usr/share/fonts/tabpdf/` (build-time download; `fonts-dejavu-core` is
  the fallback if the CDN is unreachable).