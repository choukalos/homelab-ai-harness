#!/usr/bin/env python3
"""
tab_pdf — render a transcribed song (tab.md + lyrics.txt + analysis.json)
into a print-quality PDF song sheet.

CANONICAL SOURCE — used by both:
  - the `media_render_tab_pdf` MCP tool (mcp_media server, in-process), and
  - the standalone `homelab-tab-pdf` container (scripts/tab-pdf/).

Deterministic — no LLM. The tab content is rendered verbatim from the
pipeline's tab.md; title/artist overrides replace the LLM-guessed header
when the real song identity is known.

CLI (standalone container):
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


def fmt_time(s):
    """Seconds -> m:ss.d (matches the tab.md time ranges)."""
    s = max(0.0, float(s))
    return f"{int(s) // 60}:{int(s) % 60:02d}.{int(round((s % 1) * 10))}"


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


def parse_analysis_sections(analysis):
    """analysis.json -> chart sections with WORD-LEVEL timing.

    [{label, start_s, end_s, chords: [(time_s, symbol)],
      lines: [{start, end, words: [(time_s, text)]}]}]

    Word timing comes from the ASR word timestamps; when a line lacks them,
    words are interpolated evenly across the line's time window."""
    out = []
    for sec in analysis.get("sections", []):
        chords = sorted(
            (float(c.get("time_s", 0.0)), str(c.get("symbol", "")).strip())
            for c in sec.get("chords", []) if c.get("symbol"))
        lines = []
        for l in sec.get("lyrics", []):
            words = [(float(w.get("start_s", 0.0)), str(w.get("word", "")).strip())
                     for w in l.get("words", []) if str(w.get("word", "")).strip()]
            if not words:
                text = str(l.get("text", "")).strip()
                if not text:
                    continue
                ws = text.split()
                a = float(l.get("start_s", 0.0))
                b = float(l.get("end_s", 0.0))
                if b - a < 0.2 * len(ws):
                    b = a + 0.2 * len(ws)
                step = (b - a) / len(ws)
                words = [(a + i * step, w) for i, w in enumerate(ws)]
            lines.append({"start": float(l.get("start_s", 0.0)),
                          "end": float(l.get("end_s", 0.0)), "words": words})
        out.append({"label": str(sec.get("label", "section")),
                    "start_s": float(sec.get("start_s", 0.0)),
                    "end_s": float(sec.get("end_s", 0.0)),
                    "chords": chords, "lines": lines})
    return out


def place_chords(sec):
    """Attach chord symbols to the word being sung at each chord change.

    Returns lines of [(time_s, word, [chord_symbols])]. A word is 'active'
    from its start until the next word starts, so a chord at time t lands on
    the last word that started at or before t (or the first word if t is
    before all words). Chords falling between lines attach to the first word
    of the next line. Multiple changes on one word are listed together."""
    lines = sec["lines"]
    if not sec["chords"] or not lines:
        return [[(t, w, []) for t, w in ln["words"]] for ln in lines]
    placements = [{} for _ in lines]
    for t, sym in sec["chords"]:
        li = next((i for i, ln in enumerate(lines) if ln["start"] <= t < ln["end"]), None)
        if li is None:
            later = [i for i, ln in enumerate(lines) if ln["start"] > t]
            li = min(later) if later else len(lines) - 1
        words = lines[li]["words"]
        before = [j for j, (wt, _) in enumerate(words) if wt <= t]
        wi = max(before) if before else 0
        placements[li].setdefault(wi, []).append(sym)
    return [[(t, w, placements[i].get(j, []))
             for j, (t, w) in enumerate(ln["words"])]
            for i, ln in enumerate(lines)]


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

/* ── Chart (chords over lyrics) ─────────────────────────────────────── */
.part-kicker { font-size: 9pt; letter-spacing: 2.2pt; color: #b0512f; font-weight: 700;
               margin: 16pt 0 10pt 0; padding-top: 8pt; border-top: 1.6pt solid #23232e; }
.lyr { border-collapse: collapse; margin: 0 0 5pt 0; }
.lyr td { padding: 0 0.32em 0 0; vertical-align: bottom; }
.lword { font-size: 11pt; color: #23232e; }
.lchord { display: block; font-family: 'JetBrains Mono', 'DejaVu Sans Mono', monospace;
          font-size: 9.5pt; font-weight: 700; color: #b0512f; margin-bottom: 1.5pt; }
.plain-line { font-size: 11pt; color: #23232e; margin-bottom: 5pt; }
.chord-strip { display: flex; gap: 16pt; flex-wrap: wrap; margin-bottom: 4pt; }
.cs-item { font-family: 'JetBrains Mono', 'DejaVu Sans Mono', monospace; font-weight: 700;
           font-size: 11pt; color: #23232e; }
.cs-t { display: block; font-size: 7pt; color: #98968c; font-weight: 400; }
.tab-part { page-break-before: always; }
"""


def esc(s):
    return html.escape(str(s), quote=True)


def build_chart_section_html(cs):
    """One chart section: heading + chord-over-lyrics lines (or a chord strip)."""
    placed = place_chords(cs)
    e = []
    e.append("<section>")
    e.append(
        f"<div class='section-head'><span class='section-name'>{esc(cs['label'].title())}</span>"
        f"<span class='section-time'>{fmt_time(cs['start_s'])}\u2013{fmt_time(cs['end_s'])}</span></div>"
    )
    if placed and any(ln for ln in placed):
        for ln in placed:
            if not ln:
                continue
            has_chords = any(chs for _, _, chs in ln)
            if not has_chords:
                e.append("<div class='plain-line'>" + esc(" ".join(w for _, w, _ in ln)) + "</div>")
                continue
            e.append("<table class='lyr'><tr>")
            for _, w, chs in ln:
                if chs:
                    e.append(f"<td><span class='lchord'>{esc(' '.join(chs))}</span>"
                             f"<span class='lword'>{esc(w)}</span></td>")
                else:
                    e.append(f"<td><span class='lword'>{esc(w)}</span></td>")
            e.append("</tr></table>")
    elif cs["chords"]:
        e.append("<div class='chord-strip'>")
        for t, sym in cs["chords"]:
            e.append(f"<span class='cs-item'><span class='cs-t'>{fmt_time(t)}</span>{esc(sym)}</span>")
        e.append("</div>")
    e.append("</section>")
    return e


def build_html(title, artist, meta, notes, sections, chart_secs, analysis):
    e = []
    e.append("<!DOCTYPE html><html><head><meta charset='utf-8'><style>" + CSS + "</style></head><body>")

    # ── Header ────────────────────────────────────────────────────────────
    e.append("<header>")
    e.append("<div class='kicker'>GUITAR TAB</div>")
    e.append(f"<h1>{esc(title)}</h1>")
    if artist:
        e.append(f"<div class='artist'>{esc(artist)}</div>")
    capo = analysis.get("capo_suggestion") or {}
    capo_val = f"{capo.get('capo')} ({capo.get('finger_key')} finger)" if capo.get("capo") else "\u2014"
    chips = [
        ("KEY", meta.get("key", "\u2014")),
        ("BPM", meta.get("bpm", "\u2014")),
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

    # ── Chart: chords over lyrics (play & sing) ──────────────────────────
    if any(cs["lines"] or cs["chords"] for cs in chart_secs):
        e.append("<div class='part-kicker'>CHART \u2014 CHORDS OVER LYRICS (SING &amp; PLAY)</div>")
        for cs in chart_secs:
            if cs["lines"] or cs["chords"]:
                e.extend(build_chart_section_html(cs))

    # ── Tab: fretboard reference ──────────────────────────────────────────
    e.append("<div class='tab-part'></div>")
    e.append("<div class='part-kicker'>TAB \u2014 FRETBOARD REFERENCE</div>")
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

    e.append("</body></html>")
    return "\n".join(e)

def render(song_dir, out_path, title=None, artist=None):
    """Render <song_dir>/tab.md (+ analysis.json/lyrics.txt) to a PDF.

    Layout: CHART (chords over word-timed lyrics — play & sing) then
    TAB (fretboard reference). Returns {pdf, pages, title, artist,
    sections, chart_lines}. Importable by the mcp_media server
    (media_render_tab_pdf tool)."""
    d = Path(song_dir)
    tab_path = d / "tab.md"
    if not tab_path.exists():
        raise FileNotFoundError(f"{tab_path} not found")
    parsed_title, meta, notes, sections = parse_tab(tab_path.read_text())
    title = title or parsed_title
    if not artist and meta.get("artist") and meta["artist"].lower() != "unknown":
        artist = meta["artist"]

    analysis = {}
    if (d / "analysis.json").exists():
        analysis = json.loads((d / "analysis.json").read_text())
    chart_secs = parse_analysis_sections(analysis)
    # Fallback: sections with no word-timed lyrics in analysis keep the
    # tab.md 'Lyrics:' lines as plain chart lines (no chord placement).
    if len(chart_secs) == len(sections):
        for cs, ts in zip(chart_secs, sections):
            if not cs["lines"] and ts["lyrics"]:
                cs["lines"] = [{"start": 0.0, "end": 0.0,
                                "words": [(0.0, w) for w in l.split()]}
                               for l in ts["lyrics"]]
    doc_html = build_html(title, artist, meta, notes, sections, chart_secs, analysis)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    from weasyprint import HTML

    document = HTML(string=doc_html).render()
    document.write_pdf(str(out))
    return {"pdf": str(out), "pages": len(document.pages),
            "title": title, "artist": artist or None,
            "sections": len(sections),
            "chart_lines": sum(len(cs["lines"]) for cs in chart_secs)}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("song_dir", help="dir with tab.md (lyrics.txt/analysis.json optional)")
    ap.add_argument("-o", "--out", help="output PDF path (default: <song_dir>/<slug>-tab.pdf)")
    ap.add_argument("--title", help="override the LLM-guessed title")
    ap.add_argument("--artist", help="override the LLM-guessed artist")
    args = ap.parse_args()

    d = Path(args.song_dir)
    out = args.out if args.out else str(d / f"{d.name}-tab.pdf")
    print(json.dumps(render(d, out, title=args.title, artist=args.artist)))


if __name__ == "__main__":
    main()