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
- **CHART (first)**: chords over the word-timed lyrics — play & sing. Each
  lyric line is a row of word cells; a chord change renders as a symbol
  floating above the word it lands on (ASR word timestamps vs chord event
  times from `analysis.json`). Chords before a section's first word attach
  to the first word; multiple changes on one word list together; sections
  with chords but no lyrics (intros/outros) get a timed chord strip.
- **TAB (second, page break)**: per-section name + time range, chord names
  with shape hints (from the `Chords:` line), and the ASCII tab blocks
  verbatim (JetBrains Mono, boxed).
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