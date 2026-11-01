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
import math
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
    """analysis.json -> score sections with WORD-LEVEL timing.

    [{label, start_s, end_s, chords: [(time_s, symbol)],
      lines: [{start, end, words: [(time_s, text)]}],
      lead: [{t, string, fret}]}]

    Word timing comes from the ASR word timestamps; when a line lacks them,
    words are interpolated evenly across the line's time window. `lead` is
    the section's lead-guitar (solo/riff) notes, for the SCORE's SOLO lane."""
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
        lead = []
        for n in sec.get("notes", []):
            if n.get("role") != "lead":
                continue
            tab = n.get("tab") or {}
            try:
                s = int(tab.get("string"))
                f = int(tab.get("fret"))
            except (TypeError, ValueError):
                continue
            if 1 <= s <= 6 and f >= 0:
                lead.append({"t": float(n.get("start_s", 0.0)),
                             "string": s, "fret": f})
        lead.sort(key=lambda x: x["t"])
        out.append({"label": str(sec.get("label", "section")),
                    "start_s": float(sec.get("start_s", 0.0)),
                    "end_s": float(sec.get("end_s", 0.0)),
                    "chords": chords, "lines": lines, "lead": lead})
    return out


def is_minor(symbol):
    s = re.sub(r"\d+$", "", str(symbol).lower())  # strip numeric quality (7, 9, ...)
    if s.endswith("maj"):
        return False
    return s.endswith("m")


def _ordinal(n):
    n = int(n)
    if 11 <= n % 100 <= 13:
        suf = "th"
    else:
        suf = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suf}"


def _fret_note(fret):
    fret = int(fret)
    return "open" if fret <= 0 else f"{_ordinal(fret)} fret"


def _power_frets(base, fret):
    """Power chord (root + 5th). base 'E' = E-shape (root 6th str, 5th on 5th),
    'A' = A-shape (root 5th str, 5th on 4th)."""
    f = [None] * 6
    if base == "E":
        f[0] = fret; f[1] = fret + 2
    else:
        f[1] = fret; f[2] = fret + 2
    return f


def _barre_frets(base, fret, minor):
    """Full barre chord. base 'E' = E-shape (root 6th str), 'A' = A-shape (root 5th str)."""
    f = [None] * 6
    if base == "E":
        # open E 022100 (major) / Em 022000 (minor)
        f[0] = fret; f[1] = fret + 2; f[2] = fret + 2
        f[3] = fret + (1 if not minor else 0)
        f[4] = fret; f[5] = fret
    else:
        # open A x02220 (major) / Am x02210 (minor)
        f[0] = fret; f[1] = fret; f[2] = fret + 2; f[3] = fret + 2
        f[4] = fret + (2 if not minor else 1); f[5] = fret
    return f


# Standard open chord shapes (strings 6->1; 0 = open, None = muted).
OPEN_CHORDS = {
    "C": [None, 3, 2, 0, 1, 0], "Cmaj7": [None, 3, 2, 0, 0, 0],
    "C7": [None, 3, 2, 3, 1, 0], "C6": [None, 3, 2, 2, 3, 3],
    "C9": [None, 3, 2, 0, 3, 6], "Csus4": [None, 3, 3, 0, 2, 0],
    "G": [3, 2, 0, 0, 0, 3], "G7": [3, 2, 0, 0, 0, 1],
    "Gmaj7": [3, 2, 0, 0, 0, 2], "Gsus4": [3, 3, 2, 0, 0, 3],
    "Gm": [3, 5, 5, 3, 3, 3], "Gm7": [3, 5, 3, 3, 3, 3],
    "D": [None, None, 0, 2, 3, 2], "D7": [None, None, 0, 2, 1, 2],
    "Dmaj7": [None, None, 0, 2, 2, 2], "Dm": [None, None, 0, 2, 3, 1],
    "Dm7": [None, None, 0, 2, 1, 1], "Dsus4": [None, None, 0, 2, 3, 3],
    "A": [None, 0, 2, 2, 2, 0], "Am": [None, 0, 2, 2, 1, 0],
    "Am7": [None, 0, 2, 0, 1, 0], "Amaj7": [None, 0, 2, 1, 2, 0],
    "A7": [None, 0, 2, 0, 2, 0], "A6": [None, 0, 4, 2, 2, 0],
    "Asus4": [None, 0, 2, 2, 3, 0],
    "E": [0, 2, 2, 1, 0, 0], "Em": [0, 2, 2, 0, 0, 0],
    "Em7": [0, 2, 0, 0, 0, 0], "Emaj7": [0, 2, 2, 1, 4, 0],
    "E7": [0, 2, 0, 1, 0, 0], "Esus4": [0, 2, 2, 2, 0, 0],
    "F": [1, 3, 3, 2, 1, 1], "Fm": [1, 3, 3, 1, 1, 1],
    "Fm7": [1, 3, 1, 1, 1, 1], "F7": [1, 3, 1, 2, 1, 1],
    "Fmaj7": [1, 3, 2, 2, 1, 1], "F9": [1, 3, 7, 7, 4, 1],
    "B7": [None, 2, 1, 2, 0, 2], "Bm": [None, 2, 4, 4, 3, 2],
    "Bmaj7": [None, 2, 1, 3, 0, 2],
    "Bb": [None, 1, 3, 3, 3, 1], "Bbmaj7": [None, 1, 3, 2, 3, 1],
    "Bbm7": [None, 1, 3, 1, 2, 1],
    "F#m": [None, 2, 7, 4, 2, 2], "F#m7": [None, 2, 4, 2, 5, 2],
    "F#maj7": [None, 2, 4, 3, 6, 2],
}


def chord_frets(symbol, shape):
    """(frets[6..1], start_fret, note) for a chord symbol + pipeline shape hint.

    frets: per string (6->1) an int fret (0=open) or None (muted). Returns
    frets=None when no shape is known (renderer shows the name only)."""
    shape = shape or {}
    t = shape.get("type")
    fret = int(shape.get("fret", 0) or 0)
    if t == "power":
        return _power_frets(shape.get("base", "E"), fret), max(1, fret), _fret_note(fret)
    if t == "barre":
        return _barre_frets(shape.get("base", "E"), fret, is_minor(symbol)), max(1, fret), _fret_note(fret)
    f = OPEN_CHORDS.get(str(symbol).strip())
    if f:
        return f, 1, "open"
    return None, 1, ""


def unique_chords(analysis):
    """[(symbol, shape)] in first-appearance order across the song."""
    seen = {}
    for sec in analysis.get("sections", []):
        for c in sec.get("chords", []):
            sym = str(c.get("symbol", "")).strip()
            if sym and sym not in seen:
                seen[sym] = c.get("shape")
    return list(seen.items())


def chord_token_html(name, shape, mini=False):
    """One fixed-size chord diagram token (name + fingering + fret note).

    mini=True: compact variant for inline placement in the SCORE (above the
    word where a chord change lands) — smaller diagram, no fret note."""
    frets, start, note = chord_frets(name, shape)
    cls = "chordtok mini" if mini else "chordtok"
    e = [f"<div class='{cls}'>"]
    e.append(f"<div class='ct-name'>{esc(name)}</div>")
    if frets is None:
        if mini:
            e.append("</div>")
            return e
        e.append("<div class='ct-diagwrap'><div class='ct-unknown'>n/a</div></div>")
        e.append("<div class='ct-note'>no shape</div>")
        e.append("</div>")
        return e
    e.append("<div class='ct-diagwrap'><div class='ct-diag'>")
    for i in range(6):  # strings (6 vertical lines)
        e.append(f"<div class='ct-str' style='left:{i / 5 * 100}%'></div>")
    for j in range(5):  # fret lines (5 horizontal lines)
        line_cls = "ct-nut" if (start == 1 and j == 0) else "ct-fret"
        e.append(f"<div class='{line_cls}' style='top:{j / 4 * 100}%'></div>")
    if start == 1:  # X/O markers above the nut (open chords)
        for i, v in enumerate(frets):
            if v is None:
                e.append(f"<div class='ct-xo ct-x' style='left:{i / 5 * 100}%'>x</div>")
            elif v == 0:
                e.append(f"<div class='ct-xo ct-o' style='left:{i / 5 * 100}%'>o</div>")
    for i, v in enumerate(frets):  # finger dots
        if v is None or v == 0:
            continue
        r = v - start
        if 0 <= r <= 3:
            e.append(f"<div class='ct-dot' style='left:{i / 5 * 100}%;top:{(r + 0.5) / 4 * 100}%'></div>")
    e.append("</div></div>")
    if not mini:
        e.append(f"<div class='ct-note'>{esc(note)}</div>")
    e.append("</div>")
    return e


def chord_grid_html(items):
    e = ["<div class='chord-grid'>"]
    for sym, shape in items:
        e.extend(chord_token_html(sym, shape))
    e.append("</div>")
    return e


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
.section-lyrics { font-size: 9.5pt; font-style: italic; color: #6d6c66; margin-top: 4pt; }

/* ── Score (measure-aligned vocals · rhythm · solo) ──────────────────── */
.part-kicker { font-size: 9pt; letter-spacing: 2.2pt; color: #b0512f; font-weight: 700;
               margin: 16pt 0 10pt 0; padding-top: 8pt; border-top: 1.6pt solid #23232e; }
.score { border-collapse: collapse; width: 100%; margin: 0 0 6pt 0; page-break-inside: avoid; }
.sc-lane { width: 40pt; min-width: 40pt; text-align: left; font-size: 6.8pt;
           letter-spacing: 1.1pt; text-transform: uppercase; color: #98968c;
           font-weight: 700; padding: 2pt 5pt 2pt 0; vertical-align: middle; }
.score td { padding: 1.5pt 3pt; vertical-align: bottom; }
tr.sc-ruler td { vertical-align: middle; padding: 0 3pt 1.5pt 3pt; }
.sc-meas { font-family: 'JetBrains Mono', 'DejaVu Sans Mono', monospace; font-size: 6.8pt; color: #b8b5ab; }
.sc-vcell { min-width: 54pt; }
.sc-chords { display: flex; gap: 4pt; flex-wrap: wrap; margin-bottom: 2pt; }
.sc-words { font-size: 10pt; color: #23232e; }
.solo-cell { font-family: 'JetBrains Mono', 'DejaVu Sans Mono', monospace; font-size: 7.5pt;
             line-height: 1.45; margin: 0; color: #23232e; width: 12ch; white-space: pre; }

/* ── Chord tokens (fixed-size fingering diagrams) ─────────────────────── */
.chord-grid { display: flex; flex-wrap: wrap; gap: 8pt 14pt; margin-bottom: 4pt; }
.chordtok { width: 46pt; text-align: center; }
.ct-name { font-family: 'JetBrains Mono', 'DejaVu Sans Mono', monospace; font-weight: 700;
           font-size: 10pt; color: #23232e; margin-bottom: 1pt; }
.ct-diagwrap { position: relative; width: 40pt; height: 50pt; margin: 0 auto; }
.ct-diag { position: absolute; left: 2pt; top: 10pt; width: 36pt; height: 38pt; }
.ct-str { position: absolute; top: 0; bottom: 0; width: 0.7pt; background: #4a4a55;
          transform: translateX(-50%); }
.ct-fret { position: absolute; left: 0; right: 0; height: 0.5pt; background: #a5a29a; }
.ct-nut { position: absolute; left: 0; right: 0; height: 1.6pt; background: #23232e; }
.ct-dot { position: absolute; width: 6.2pt; height: 6.2pt; border-radius: 50%;
          background: #b0512f; transform: translate(-50%, -50%); }
.ct-xo { position: absolute; top: -9.5pt; transform: translateX(-50%); font-size: 7.5pt;
         font-weight: 700; line-height: 1; color: #6d6c66; }
.ct-x { color: #b0512f; }
.ct-note { font-size: 7pt; color: #98968c; margin-top: 1pt; letter-spacing: 0.4pt;
           text-transform: uppercase; }
.ct-unknown { font-size: 14pt; color: #98968c; text-align: center; padding-top: 14pt; }
.chordtok.mini { width: 30pt; }
.chordtok.mini .ct-name { font-size: 7.5pt; margin-bottom: 0; }
.chordtok.mini .ct-diagwrap { width: 24pt; height: 30pt; }
.chordtok.mini .ct-diag { left: 1.5pt; top: 7pt; width: 21pt; height: 24pt; }
.chordtok.mini .ct-dot { width: 4.4pt; height: 4.4pt; }
.chordtok.mini .ct-xo { top: -7pt; font-size: 6.5pt; }
"""


def esc(s):
    return html.escape(str(s), quote=True)


# ── Score (measure-aligned vocals · rhythm · solo) ─────────────────────
MEASURES_PER_ROW = 7          # keep one band within a Letter page width
SOLO_CELL_CHARS = 12          # max fret digits per string per measure
SOLO_REPEAT_CAP = 5           # max repeated fret digits per run
STR_LABELS = {1: "e", 2: "B", 3: "G", 4: "D", 5: "A", 6: "E"}


def bar_length(analysis):
    """One bar in seconds (4 beats). Falls back to 2.0s when BPM is unknown."""
    try:
        bpm = float(analysis.get("bpm") or 0.0)
    except (TypeError, ValueError):
        bpm = 0.0
    return 240.0 / bpm if bpm > 30.0 else 2.0


def _measure_of(t, start, bar, nmeas):
    """Time -> measure index within a section (clamped to [0, nmeas-1])."""
    if bar <= 0:
        return 0
    return max(0, min(nmeas - 1, int((t - start) // bar)))


def _solo_cell(lead, t0, t1):
    """Compact 6-string tab for the lead notes in [t0, t1).

    One row per string (e top -> E bottom, standard tab order); consecutive
    repeats of the same fret collapse (capped at SOLO_REPEAT_CAP), so a
    strummed '1111111' reads as '11111'. Fixed 12-char cells keep the
    measure columns aligned."""
    rows = {s: [] for s in range(1, 7)}
    for n in lead:
        if t0 <= n["t"] < t1:
            rows[n["string"]].append(n["fret"])
    out = []
    for s in range(1, 7):
        txt, run_f, run_n = "", None, 0
        for f in rows[s]:
            if f == run_f:
                run_n += 1
                if run_n <= SOLO_REPEAT_CAP:
                    txt += str(f)
            else:
                run_f, run_n = f, 1
                txt += str(f)
        out.append(f"{STR_LABELS[s]}|{txt[:SOLO_CELL_CHARS]:<{SOLO_CELL_CHARS}}")
    return "\n".join(out)


def _mini_chords(chords, shape_map):
    """Mini chord-diagram tokens (shape + name) for a list of symbols."""
    e = []
    for sym in chords:
        e.extend(chord_token_html(sym, shape_map.get(sym), mini=True))
    return e


def _score_band_html(cs, m0, m1, bar, shape_map, words_by_meas, chords_by_meas,
                     has_vocals, has_lead):
    """One band (<= MEASURES_PER_ROW measures) of the section's score table.

    Lanes: ruler (measure numbers), Vocals (words per measure, mini chord
    diagram above the change), Rhythm (chord diagrams, instrumental
    sections), Solo (compact 6-string tab cell per measure)."""
    start = cs["start_s"]
    e = ["<table class='score'>"]
    e.append("<tr class='sc-ruler'><th class='sc-lane'></th>")
    for m in range(m0, m1):
        e.append(f"<td class='sc-meas'>{m + 1}</td>")
    e.append("</tr>")
    if has_vocals or (not has_vocals and cs["chords"]):
        label = "Vocals" if has_vocals else "Rhythm"
        e.append(f"<tr><th class='sc-lane'>{label}</th>")
        for m in range(m0, m1):
            e.append("<td class='sc-vcell'>")
            if chords_by_meas[m]:
                e.append("<div class='sc-chords'>")
                e.extend(_mini_chords(chords_by_meas[m], shape_map))
                e.append("</div>")
            if has_vocals and words_by_meas[m]:
                e.append(f"<span class='sc-words'>{esc(' '.join(words_by_meas[m]))}</span>")
            e.append("</td>")
        e.append("</tr>")
    if has_lead:
        e.append("<tr class='sc-solo'><th class='sc-lane'>Solo</th>")
        for m in range(m0, m1):
            t0 = start + m * bar
            e.append(f"<td><pre class='solo-cell'>{esc(_solo_cell(cs['lead'], t0, t0 + bar))}</pre></td>")
        e.append("</tr>")
    e.append("</table>")
    return e


def build_score_section_html(cs, bar, shape_map):
    """One SCORE section: heading + measure-aligned bands of the score.

    Sections with no lyrics, no chords and no lead notes render nothing."""
    start, end = cs["start_s"], cs["end_s"]
    has_vocals = bool(cs["lines"])
    has_lead = bool(cs["lead"])
    has_chords = bool(cs["chords"])
    if not (has_vocals or has_lead or has_chords):
        return []
    nmeas = max(1, math.ceil((end - start) / bar)) if bar > 0 else 1
    words_by_meas = {m: [] for m in range(nmeas)}
    for ln in cs["lines"]:
        for wt, w in ln["words"]:
            words_by_meas[_measure_of(wt, start, bar, nmeas)].append(w)
    chords_by_meas = {m: [] for m in range(nmeas)}
    for t, sym in cs["chords"]:
        chords_by_meas[_measure_of(t, start, bar, nmeas)].append(sym)

    e = ["<section>"]
    e.append(
        f"<div class='section-head'><span class='section-name'>{esc(cs['label'].title())}</span>"
        f"<span class='section-time'>{fmt_time(start)}\u2013{fmt_time(end)}</span></div>"
    )
    n_bands = max(1, math.ceil(nmeas / MEASURES_PER_ROW))
    size = math.ceil(nmeas / n_bands)
    for b in range(0, nmeas, size):
        m0, m1 = b, min(b + size, nmeas)
        e.extend(_score_band_html(cs, m0, m1, bar, shape_map, words_by_meas,
                                  chords_by_meas, has_vocals, has_lead))
    e.append("</section>")
    return e


def build_html(title, artist, meta, notes, chart_secs, analysis):
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

    # ── Chords: fixed-size fingering grid (reference sheet) ─────────────
    chord_items = unique_chords(analysis)
    if chord_items:
        e.append("<div class='part-kicker'>CHORDS \u2014 FINGERINGS</div>")
        e.extend(chord_grid_html(chord_items))

    # ── Score: measure-aligned vocals · rhythm · solo (sing & play) ─────
    bar = bar_length(analysis)
    shape_map = dict(chord_items)
    if any(cs["lines"] or cs["lead"] or cs["chords"] for cs in chart_secs):
        e.append("<div class='part-kicker'>SCORE \u2014 SING &amp; PLAY (VOCALS \u00b7 RHYTHM \u00b7 SOLO)</div>")
        for cs in chart_secs:
            e.extend(build_score_section_html(cs, bar, shape_map))

    e.append("</body></html>")
    return "\n".join(e)

def render(song_dir, out_path, title=None, artist=None):
    """Render <song_dir>/tab.md (+ analysis.json/lyrics.txt) to a PDF.

    Layout: CHORDS (fixed-size fingering grid) then SCORE (measure-aligned
    vocals + rhythm + solo — sing & play with a friend). Returns {pdf, pages,
    title, artist, sections, chart_lines}. Importable by the mcp_media server
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
    doc_html = build_html(title, artist, meta, notes, chart_secs, analysis)
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