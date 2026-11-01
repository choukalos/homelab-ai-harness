#!/usr/bin/env python3
"""
tab_pdf — render a transcribed song (tab.md + lyrics.txt + analysis.json)
into a print-quality PDF song sheet.

Deterministic — no LLM. The tab content is rendered verbatim from the
pipeline's tab.md; --title/--artist override the LLM-guessed header when
the real song identity is known.

Usage (inside the tab-pdf container):
  python tab_pdf.py <song_dir> [-o out.pdf] [--title T] [--artist A]

<song_dir> must contain tab.md (lyrics.txt / analysis.json optional).
"""
import argparse
import html
import json
import re
from pathlib import Path

# Chord name: tonic letter + optional accidental + optional quality + optional root.
CHORD_QUALITY = r"(?:maj7|maj|m7|m|dim|aug|sus4|sus2|7|9|11|13)?"
CHORD_RE = re.compile(rf"([A-G][#b]?{CHORD_QUALITY}\d?)\s*(\[[^\]]*\])?")
SECTION_RE = re.compile(r"^## \[(.+?)\] \((.+?)\)\s*$")
META_RE = re.compile(
    r"^Artist:\s*(?P<artist>.+?)\s*\|\s*Key:\s*(?P<key>.+?)\s*\|\s*"
    r"BPM:\s*(?P<bpm>.+?)\s*\|\s*Tuning:\s*(?P<tuning>.+)$"
)
LYRIC_TS_RE = re.compile(r"^\[(\d+):(\d+(?:\.\d+)?)\]\s*(.*)$")


def parse_chords(line):
    """'Chords: A5 [open A5]  C5 [power @ 3 (A-shape)]' -> [(name, hint|None)]"""
    body = line.split(":", 1)[1]
    out = []
    for m in CHORD_RE.finditer(body):
        name = m.group(1)
        hint = m.group(2)[1:-1].strip() if m.group(2) else None
        out.append((name, hint))
    return out


def parse_tab(text):
    """Parse the pipeline's tab.md -> (title, meta, notes, sections).

    Sections: {name, time, chords: [(name, hint)], blocks: [[lines]], lyrics: [lines]}
    Tab blocks are the verbatim indented lines between the Chords: line and the
    Lyrics: line, split on blank lines (one box per phrase).
    """
    meta, notes, sections = {}, [], []
    title = None
    cur = None
    for raw in text.splitlines():
        line = raw.rstrip()
        if line.startswith("# ") and title is None:
            title = line[2:].split("—")[0].strip()
            continue
        m = META_RE.match(line)
        if m:
            meta.update(m.groupdict())
            continue
        if line.startswith(("Capo:", "Transposed:", "Chords shown as")):
            notes.append(line)
            continue
        if line.startswith(("Source:", "Confidence:", "Raw data:")):
            continue
        m = SECTION_RE.match(line)
        if m:
            cur = {
                "name": m.group(1),
                "time": m.group(2),
                "chords": [],
                "blocks": [],
                "lyrics": [],
                "_buf": [],
            }
            sections.append(cur)
            continue
        if cur is None:
            continue
        if line.startswith("Chords:"):
            cur["chords"] = parse_chords(line)
            continue
        if line.startswith("Lyrics:"):
            body = line[len("Lyrics:"):].strip()
            if body and "none" not in body.lower():
                cur["lyrics"].append(body)
            continue
        if line.strip():
            cur["_buf"].append(line)
        elif cur["_buf"]:
            cur["blocks"].append(cur["_buf"])
            cur["_buf"] = []
    if cur and cur["_buf"]:
        cur["blocks"].append(cur["_buf"])
    for s in sections:
        s.pop("_buf", None)
    return title, meta, notes, sections


def parse_lyrics(text):
    """'[mm:ss.s] line' list -> stanzas (new stanza on a >= 4s gap)."""
    lines = []
    for raw in text.splitlines():
        m = LYRIC_TS_RE.match(raw.strip())
        if m and m.group(3).strip():
            t = int(m.group(1)) * 60 + float(m.group(2))
            lines.append((t, m.group(3).strip()))
    stanzas, cur, last = [], [], None
    for t, text in lines:
        if cur and (last is None or t - last >= 4.0):
            stanzas.append(cur)
            cur = []
        cur.append(text)
        last = t
    if cur:
        stanzas.append(cur)
    return stanzas


CSS = """
@page {
  size: Letter;
  margin: 16mm 15mm 20mm 15mm;
  @bottom-left {
    content: "Transcribed by the homelab media pipeline — strong draft; verify against the recording";
    font-family: 'Inter', 'DejaVu Sans', sans-serif;
    font-size: 7.2pt; color: #98968c;
  }
  @bottom-right {
    content: "Page " counter(page) " of " counter(pages);
    font-family: 'Inter', 'DejaVu Sans', sans-serif;
    font-size: 7.2pt; color: #98968c;
  }
}
/* Fonts are baked into the image at /usr/share/fonts/tabpdf (variable TTFs;
   fontconfig exposes their instances — Playfair Display / Inter / JetBrains
   Mono with Regular..Bold). WeasyPrint 70's @font-face cannot instantiate
   the JetBrains Mono variable font, so we use fontconfig family names. */

* { box-sizing: border-box; }
body { font-family: 'Inter', 'DejaVu Sans', sans-serif; color: #23232e; font-size: 10pt; }

header { border-bottom: 2.5pt solid #23232e; padding-bottom: 10pt; margin-bottom: 14pt; }
.kicker { font-size: 8pt; letter-spacing: 2.4pt; color: #b0512f; font-weight: 700; margin-bottom: 4pt; }
h1 { font-family: 'Playfair Display', 'DejaVu Serif', serif; font-size: 30pt; font-weight: 700;
     margin: 0 0 2pt 0; line-height: 1.05; }
.artist { font-size: 12.5pt; color: #6d6c66; font-style: italic; margin-bottom: 10pt; }
.chips { display: flex; gap: 6pt; }
.chip { background: #f2f1ec; border: 0.6pt solid #ddd9cf; border-radius: 3pt; padding: 3.5pt 7pt; }
.chip .k { display: block; font-size: 6.5pt; letter-spacing: 1.2pt; color: #98968c; font-weight: 700; }
.chip .v { display: block; font-size: 10.5pt; font-weight: 700; color: #23232e; }
.note { margin-top: 8pt; font-size: 9pt; color: #6d6c66; }

section { margin-bottom: 12pt; }
.section-head { display: flex; justify-content: space-between; align-items: baseline;
                border-bottom: 0.8pt solid #d8d5cb; padding-bottom: 2.5pt; margin-bottom: 6pt; }
.section-name { font-size: 9.5pt; font-weight: 700; letter-spacing: 1.6pt;
                text-transform: uppercase; color: #b0512f; }
.section-time { font-size: 8pt; color: #98968c; }
.chords { margin-bottom: 5pt; }
.chord { display: inline-block; margin-right: 12pt; }
.chord .n { font-family: 'Playfair Display', 'DejaVu Serif', serif; font-size: 14pt; font-weight: 700; }
.chord .h { display: block; font-size: 7.5pt; color: #98968c; margin-top: 0.5pt; }
pre.tab { font-family: 'JetBrains Mono', 'DejaVu Sans Mono', monospace; font-size: 9.5pt; line-height: 1.5;
          background: #f7f6f2; border: 0.6pt solid #e3e0d6; border-radius: 4pt;
          padding: 7pt 9pt; margin: 0 0 5pt 0; white-space: pre; }
.section-lyrics { font-size: 9.5pt; font-style: italic; color: #6d6c66; margin-top: 4pt; }

.lyrics-page { page-break-before: always; }
.lyric-stanza { margin-bottom: 10pt; font-size: 10.5pt; line-height: 1.55; color: #2f2f38; }
"""


def esc(s):
    return html.escape(str(s), quote=True)


def build_html(title, artist, meta, notes, sections, lyrics_stanzas, analysis):
    e = []
    e.append("<!DOCTYPE html><html><head><meta charset='utf-8'><style>" + CSS + "</style></head><body>")

    # ── Header ────────────────────────────────────────────────────────────
    e.append("<header>")
    e.append("<div class='kicker'>GUITAR TAB</div>")
    e.append(f"<h1>{esc(title)}</h1>")
    if artist:
        e.append(f"<div class='artist'>{esc(artist)}</div>")
    capo = analysis.get("capo_suggestion") or {}
    capo_val = f"{capo.get('capo')} ({capo.get('finger_key')} finger)" if capo.get("capo") else "—"
    chips = [
        ("KEY", meta.get("key", "—")),
        ("BPM", meta.get("bpm", "—")),
        ("TUNING", meta.get("tuning", "Standard (EADGBE)")),
        ("CAPO", capo_val),
    ]
    e.append("<div class='chips'>")
    for k, v in chips:
        e.append(f"<div class='chip'><span class='k'>{esc(k)}</span><span class='v'>{esc(v)}</span></div>")
    e.append("</div>")
    for n in notes:
        e.append(f"<div class='note'>{esc(n)}</div>")
    e.append("</header>")

    # ── Sections ──────────────────────────────────────────────────────────
    for s in sections:
        e.append("<section>")
        e.append(
            f"<div class='section-head'><span class='section-name'>{esc(s['name'].title())}</span>"
            f"<span class='section-time'>{esc(s['time'])}</span></div>"
        )
        if s["chords"]:
            e.append("<div class='chords'>")
            for name, hint in s["chords"]:
                e.append(f"<span class='chord'><span class='n'>{esc(name)}</span>")
                if hint:
                    e.append(f"<span class='h'>{esc(hint)}</span>")
                e.append("</span>")
            e.append("</div>")
        for block in s["blocks"]:
            e.append("<pre class='tab'>" + esc("\n".join(block)) + "</pre>")
        if s["lyrics"]:
            for line in s["lyrics"]:
                e.append(f"<div class='section-lyrics'>{esc(line)}</div>")
        e.append("</section>")

    # ── Lyrics page ───────────────────────────────────────────────────────
    if lyrics_stanzas:
        e.append("<div class='lyrics-page'>")
        e.append("<div class='kicker'>LYRICS</div>")
        for stanza in lyrics_stanzas:
            e.append("<div class='lyric-stanza'>" + "<br>".join(esc(l) for l in stanza) + "</div>")
        e.append("</div>")

    e.append("</body></html>")
    return "\n".join(e)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("song_dir", help="dir with tab.md (lyrics.txt/analysis.json optional)")
    ap.add_argument("-o", "--out", help="output PDF path (default: <song_dir>/<slug>-tab.pdf)")
    ap.add_argument("--title", help="override the LLM-guessed title")
    ap.add_argument("--artist", help="override the LLM-guessed artist")
    args = ap.parse_args()

    d = Path(args.song_dir)
    tab_path = d / "tab.md"
    if not tab_path.exists():
        raise SystemExit(f"error: {tab_path} not found")
    title, meta, notes, sections = parse_tab(tab_path.read_text())
    title = args.title or title
    artist = args.artist
    if not artist and meta.get("artist") and meta["artist"].lower() != "unknown":
        artist = meta["artist"]

    analysis = {}
    if (d / "analysis.json").exists():
        analysis = json.loads((d / "analysis.json").read_text())
    lyrics_stanzas = []
    if (d / "lyrics.txt").exists():
        lyrics_stanzas = parse_lyrics((d / "lyrics.txt").read_text())

    doc_html = build_html(title, artist, meta, notes, sections, lyrics_stanzas, analysis)
    out = Path(args.out) if args.out else d / f"{d.name}-tab.pdf"

    from weasyprint import HTML

    document = HTML(string=doc_html).render()
    document.write_pdf(str(out))
    print(json.dumps({"pdf": str(out), "pages": len(document.pages),
                      "title": title, "artist": artist or None,
                      "sections": len(sections), "lyric_lines": sum(len(s) for s in lyrics_stanzas)}))


if __name__ == "__main__":
    main()