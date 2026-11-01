# tab-pdf — song tab → PDF

Renders a transcribed song (the media pipeline's `tab.md` + `lyrics.txt` +
`analysis.json`) into a print-quality PDF song sheet. Deterministic — no LLM.

Part of the song-transcribe publish flow: the PDF is the primary published
artifact (`/files/tabs/<slug>-tab.pdf`); the raw `.md`/`.txt` are kept local
and only published on request.

## Usage

```bash
# build (fonts are downloaded at build time; best-effort with DejaVu fallback)
docker build -t homelab-tab-pdf:local scripts/tab-pdf

# render (song dir must contain tab.md; lyrics.txt/analysis.json optional)
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
- **Sections**: name + time range, chord names with shape hints (from the
  `Chords:` line), and the ASCII tab blocks verbatim (JetBrains Mono, boxed).
- **Lyrics page**: `lyrics.txt` timestamps stripped, grouped into stanzas on
  a ≥4 s gap.
- **Footer** (every page): "strong draft; verify against the recording" +
  page numbers. Letter size.

## QA

The image includes poppler-utils:

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
  `/usr/share/fonts/tabpdf/` (build-time download; `fonts-dejavu-core` is the
  fallback if the CDN is unreachable).