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
from enum import Enum
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


def _line_timing_bad(words, sec_start, sec_end):
    """True when a line's ASR word timestamps are broken.

    Whisper word timestamps (and the LLM polish step that merges lines)
    can produce: pile-ups (many words on one timestamp), words spilling
    far past the section end (they would clamp into one measure),
    non-monotonic times, or impossible rates. Mild spills (<=3 s) are
    left alone — they clamp harmlessly into the last measure."""
    ts = [t for t, _ in words]
    n = len(ts)
    if n < 3:
        return False
    lo, hi = min(ts), max(ts)
    if min(b - a for a, b in zip(ts, ts[1:])) < -0.05:  # non-monotonic
        return True
    for j in range(n):  # pile-up: >4 words inside any 0.1 s window
        if sum(1 for t in ts if 0 <= t - ts[j] < 0.1) > 4:
            return True
    if (hi - lo) < 0.10 * (n - 1):  # >10 words/s — impossible
        return True
    if hi > sec_end + 3.0 or lo < sec_start - 3.0:  # big spill
        return True
    return False


def _retimed_lines(lines, start, end):
    """Re-time a section's lines when the ASR timestamps are broken.

    Splits the section window across the lines proportionally to word
    count; words are placed evenly (centered) inside each slice. Keeps
    the words in order, inside the section, and out of one measure."""
    total = sum(len(l["words"]) for l in lines)
    dur = end - start
    if total <= 0 or dur <= 0:
        return lines
    t = start
    for l in lines:
        n = len(l["words"])
        if n == 0:
            continue
        step = dur * n / total / n
        l["words"] = [(t + (j + 0.5) * step, w) for j, (_, w) in enumerate(l["words"])]
        t += dur * n / total
    return lines


def parse_analysis_sections(analysis):
    """analysis.json -> score sections with WORD-LEVEL timing.

    [{label, start_s, end_s, chords: [(time_s, symbol)],
      lines: [{start, end, words: [(time_s, text)]}],
      lead: [{t, string, fret}]}]

    Word timing comes from the ASR word timestamps; when a line lacks them,
    words are interpolated evenly across the line's time window. Lines with
    broken timestamps (pile-ups / big spills — a known whisper+polish
    failure mode) are re-timed evenly across the section window. `lead` is
    the section's lead-guitar (solo/riff) notes, for the SCORE's SOLO lane."""
    out = []
    for sec in analysis.get("sections", []):
        sec_start = float(sec.get("start_s", 0.0))
        sec_end = float(sec.get("end_s", 0.0))
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
        if any(_line_timing_bad(l["words"], sec_start, sec_end)
               for l in lines if l["words"]):
            _retimed_lines(lines, sec_start, sec_end)
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
            if 1 <= s <= 6 and 0 <= f <= 20:
                t = float(n.get("start_s", 0.0))
                end = float(n.get("end_s", 0.0) or 0.0)
                lead.append({"t": t,
                             "end": max(end, t + 0.05),
                             "string": s, "fret": f,
                             "amp": n.get("amplitude"),
                             "mark": _contour_mark(n.get("pitch_contour"))})
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


# Note math (standard tuning EADGBE) for the synthesized-barre fallback (A3.1)
# and the shape-library unit test (test_chord_shapes.py).
NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
NOTE_IDX = {n: i for i, n in enumerate(NOTE_NAMES)}
for _flat, _sharp in (("Bb", "A#"), ("Db", "C#"), ("Eb", "D#"),
                      ("Gb", "F#"), ("Ab", "G#")):
    NOTE_IDX[_flat] = NOTE_IDX[_sharp]  # flat spellings
OPEN_STRING_SEMIS = [4, 9, 14, 19, 23, 28]  # MIDI of open strings 6..1


def _synth_barre_frets(symbol):
    """Synthesize a movable barre shape for a symbol with no known open shape.

    A3.1 (enhance_tab_tool.md): find the root fret on the 6th string
    (E-shape) and 5th string (A-shape), take the lower one, and reuse
    _barre_frets(). Quality handling: 7th chords add the 7th (E-shape: 4th
    string, A-shape: 3rd string — the exact E7/A7 patterns), maj7 adds the
    7th + 11th (the exact Emaj7/Amaj7 patterns); 9/6 render the triad(+7) and
    the quality is left to the printed name. Returns
    (frets, start_fret, note) or None when the root can't be parsed."""
    m = re.match(r"^([A-G])([#b]?)", str(symbol).strip())
    if not m:
        return None
    root = NOTE_IDX.get(m.group(1) + m.group(2))
    if root is None:
        return None
    e_fret = (root - OPEN_STRING_SEMIS[0]) % 12  # root on 6th string (E-shape)
    a_fret = (root - OPEN_STRING_SEMIS[1]) % 12  # root on 5th string (A-shape)
    if a_fret <= e_fret:
        base, fret = "A", a_fret
    else:
        base, fret = "E", e_fret
    frets = _barre_frets(base, fret, is_minor(symbol))
    q = str(symbol).strip()[len(m.group(0)):].lower()
    if q.startswith("7") or q.startswith("9") or q.startswith("maj7"):
        frets[2 if base == "E" else 3] = fret  # 7th (E7: 4th str, A7: 3rd str)
    if q.startswith("maj7"):
        frets[4] = fret + (4 if base == "E" else 2)  # 11th (Emaj7/Amaj7)
    note = f"barre @ {fret} (synthesized)" if fret else "open (synthesized)"
    return frets, max(1, fret), note


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
# 2026-11-06 (enhance_tab_tool.md A1+A2): added the 6th/9th family that the
# 2026-11-05 QA tabs hit as "NO SHAPE" (B6/F6/G6) plus the same-class
# additions; every entry interval-verified by test_chord_shapes.py. Also
# corrected 5 pre-existing entries the checker caught (Csus4/Gsus4 carried
# wrong notes; F#m/F#m7/F#maj7 were non-standard voicings missing core
# tones). NOTE: D6 is xx0202 (D A B F#) — xx0212 is the D7 voicing.
OPEN_CHORDS = {
    "C": [None, 3, 2, 0, 1, 0], "Cmaj7": [None, 3, 2, 0, 0, 0],
    "C7": [None, 3, 2, 3, 1, 0], "C6": [None, 3, 2, 2, 3, 3],
    "C9": [None, 3, 2, 0, 3, 6], "Csus4": [None, 3, 3, 0, 3, 0],
    "G": [3, 2, 0, 0, 0, 3], "G7": [3, 2, 0, 0, 0, 1],
    "Gmaj7": [3, 2, 0, 0, 0, 2], "Gsus4": [3, 3, 0, 0, 3, 3],
    "G6": [3, 2, 0, 0, 0, 0], "G9": [3, 5, 3, 2, 3, 3],  # 353433 is G7 (no 9th)
    "Gm": [3, 5, 5, 3, 3, 3], "Gm7": [3, 5, 3, 3, 3, 3],
    "D": [None, None, 0, 2, 3, 2], "D7": [None, None, 0, 2, 1, 2],
    "Dmaj7": [None, None, 0, 2, 2, 2], "Dm": [None, None, 0, 2, 3, 1],
    "Dm7": [None, None, 0, 2, 1, 1], "Dsus4": [None, None, 0, 2, 3, 3],
    "D6": [None, None, 0, 2, 0, 2], "D9": [None, None, 0, 2, 3, 2],
    "A": [None, 0, 2, 2, 2, 0], "Am": [None, 0, 2, 2, 1, 0],
    "Am7": [None, 0, 2, 0, 1, 0], "Amaj7": [None, 0, 2, 1, 2, 0],
    "A7": [None, 0, 2, 0, 2, 0], "A6": [None, 0, 4, 2, 2, 0],
    "A9": [None, 0, 2, 0, 2, 0], "Am9": [None, 0, 2, 0, 1, 2],
    "Asus4": [None, 0, 2, 2, 3, 0],
    "E": [0, 2, 2, 1, 0, 0], "Em": [0, 2, 2, 0, 0, 0],
    "Em7": [0, 2, 0, 0, 0, 0], "Emaj7": [0, 2, 2, 1, 4, 0],
    "E6": [0, 2, 2, 1, 0, 0], "E7": [0, 2, 0, 1, 0, 0], "Esus4": [0, 2, 2, 2, 0, 0],
    "F": [1, 3, 3, 2, 1, 1], "F6": [1, 3, 3, 2, 1, 1],  # F6 = F voicing, 6th implied
    "Fm": [1, 3, 3, 1, 1, 1], "Fm7": [1, 3, 1, 1, 1, 1],
    "F7": [1, 3, 1, 2, 1, 1], "Fmaj7": [1, 3, 2, 2, 1, 1],
    "F9": [1, 3, 7, 7, 4, 1],
    "B7": [None, 2, 1, 2, 0, 2], "Bm": [None, 2, 4, 4, 3, 2],
    "Bmaj7": [None, 2, 1, 3, 0, 2], "B6": [None, 2, 6, 4, 4, 2],
    "Bb": [None, 1, 3, 3, 3, 1], "Bbmaj7": [None, 1, 3, 2, 3, 1],
    "Bbm7": [None, 1, 3, 1, 2, 1],
    "F#m": [2, 4, 4, 2, 2, 2], "F#m7": [2, 4, 2, 2, 2, 2],
    "F#maj7": [2, 4, 4, 3, 6, 2],
}


def chord_frets(symbol, shape):
    """(frets[6..1], start_fret, note) for a chord symbol + pipeline shape hint.

    frets: per string (6->1) an int fret (0=open) or None (muted). Returns
    frets=None when no shape is known (renderer shows the name only).
    Unknown symbols with an open/no hint fall back to a synthesized barre
    (A3.1) instead of n/a."""
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
    if t in ("open", None):
        synth = _synth_barre_frets(symbol)
        if synth:
            return synth
    return None, 1, ""


def chord_status(symbol, shape):
    """'power' | 'barre' | 'open' | 'synthesized' | 'missing' — which path
    chord_frets() takes (A3.2: lets render() report shape coverage)."""
    shape = shape or {}
    t = shape.get("type")
    if t == "power":
        return "power"
    if t == "barre":
        return "barre"
    if str(symbol).strip() in OPEN_CHORDS:
        return "open"
    if t in ("open", None) and _synth_barre_frets(symbol):
        return "synthesized"
    return "missing"


def shape_coverage(analysis):
    """(missing, synthesized) chord symbols across the song (A3.2).

    missing = symbols that fall through to "n/a"; synthesized = symbols
    rendered by the synthesized-barre fallback. Lets the MCP tool warn
    instead of silently shipping "n/a" pages."""
    missing, synthesized = [], []
    for sym, shp in unique_chords(analysis):
        st = chord_status(sym, shp)
        if st == "missing":
            missing.append(sym)
        elif st == "synthesized":
            synthesized.append(sym)
    return missing, synthesized


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

/* ── Solo boards (Phase 3: per-measure fretboard boards) ──────────────── */
.solo-key {
  margin: 0 0 8pt 0;
  border: 0.5pt solid #d8d5cb;
  border-radius: 3pt;
  padding: 5pt 7pt 6pt 7pt;
  background: #faf9f6;
}
.solo-key .sk-title {
  font-size: 6.5pt; letter-spacing: 1.2pt; color: #98968c; font-weight: 700;
  margin-bottom: 3pt;
}
.solo-key .sk-body { display: flex; gap: 10pt; align-items: flex-start; }
.solo-key .sk-table { border-collapse: collapse; font-size: 6.8pt; color: #6d6c66; }
.solo-key .sk-table td { padding: 0.9pt 8pt 0.9pt 0; vertical-align: middle; }
.solo-key .sk-table .mk {
  font-family: 'JetBrains Mono', 'DejaVu Sans Mono', monospace;
  font-weight: 700; color: #23232e; white-space: nowrap;
}
.sb-boards { display: flex; gap: 1pt; align-items: flex-start; }
.sb-svg text, .sk-svg text { font-family: 'Inter', 'DejaVu Sans', sans-serif; }
"""


def esc(s):
    return html.escape(str(s), quote=True)


# ── Score (measure-aligned vocals · rhythm · solo) ─────────────────────
# 4 per row (2026-11-06): the solo boards need the horizontal room to be
# legible — 7 crammed them to ~44pt in ~69pt cells. 4 per row gives each
# measure ~120pt so the boards can render at SOLO_BOARD_SCALE.
MEASURES_PER_ROW = 4

# ── Solo boards (Phase 3) ─────────────────────────────────────────────
class SoloStyle(str, Enum):
    """SOLO lane rendering style (string enum: add members later without
    breaking callers)."""
    BOARD = "board"   # per-measure fretboard boards (default)
    TEXT = "text"     # legacy compact 6-line text tab

SOLO_DENSE_LIMIT = 12        # >12 lead notes/measure -> text fallback
SOLO_STACK_LIMIT = 5         # >5 notes on one (string, fret) -> text fallback
SOLO_BOARD_SPACES = 6        # fret spaces per board (7 lines)
SOLO_SLIDE_GAP_BEATS = 0.25  # gap < 0.25*beat -> slide
SOLO_JUMP_NO_MARK = 4        # |Δfret| > 4 -> no connector
SOLO_BEND_RISE = 1.0         # Phase 4: |onset→offset rise| (semitones) for a
                             # bend mark (pitch_contour deviation from the
                             # note's nominal pitch; 5 samples per note)
SOLO_BEND_DEV = 0.6          # Phase 4: min total contour deviation for a bend
SOLO_VIB_DEV = 0.5           # Phase 4: min total contour deviation for vibrato
SOLO_BOARD_W = 44.0          # total width (pt) of a board group (viewBox geometry)
SOLO_BOARD_H = 54.0          # height (pt): board 46 + ruler
SOLO_BOARD_SCALE = 2.0       # render scale (2026-11-06): SVG is emitted at
                             # width×SCALE × height×SCALE with the same viewBox,
                             # so dots/tails/badges/connectors/ruler all scale up
                             # uniformly — the boards were too small to read at 1×
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


def _contour_mark(pc):
    """Phase 4: classify a note's `pitch_contour` as a bend or vibrato.

    `pc` is the pipeline's per-note pitch contour: pitch deviation from the
    note's nominal pitch in **semitones**, 5 samples across the note's
    duration (onset → offset). Returns "b+" (bend up), "b-" (bend down),
    "v" (vibrato), or None.

    Heuristics (conservative — on dense distorted mixes the contour is
    tracking noise, so only clear sustained patterns are marked; verify
    against the recording):
    - bend: near-monotonic (≤1 direction reversal) sustained ramp whose
      onset→offset rise is ≥ SOLO_BEND_RISE semitone (total deviation
      ≥ SOLO_BEND_DEV). A slide-in from below reads as a bend-up (the
      pitch travels up through the note).
    - vibrato: ≥2 direction reversals with total deviation ≥ SOLO_VIB_DEV.
    """
    if not pc or len(pc) < 3:
        return None
    try:
        vals = [float(x) for x in pc]
    except (TypeError, ValueError):
        return None
    dev = max(vals) - min(vals)
    rise = vals[-1] - vals[0]
    nz = [1 if b > a else (-1 if b < a else 0)
          for a, b in zip(vals, vals[1:])]
    nz = [x for x in nz if x != 0]
    rev = sum(1 for a, b in zip(nz, nz[1:]) if a != b)
    if rev <= 1 and abs(rise) >= SOLO_BEND_RISE and dev >= SOLO_BEND_DEV:
        return "b+" if rise > 0 else "b-"
    if rev >= 2 and dev >= SOLO_VIB_DEV:
        return "v"
    return None


def _mark_char(mark):
    """Phase 4: mark string -> single character for the text tab ('b'/'v')."""
    if not mark:
        return ""
    return "b" if mark.startswith("b") else "v"


def _solo_cell(lead, t0, t1):
    """Compact 6-string tab for the lead notes in [t0, t1).

    One row per string (e top -> E bottom, standard tab order); consecutive
    repeats of the same fret collapse (capped at SOLO_REPEAT_CAP), so a
    strummed '1111111' reads as '11111'. Fixed 12-char cells keep the
    measure columns aligned. Phase 4: a note's pitch-contour mark (b = bend,
    v = vibrato) is appended to its fret digit (e.g. '5b')."""
    rows = {s: [] for s in range(1, 7)}
    for n in lead:
        if t0 <= n["t"] < t1:
            rows[n["string"]].append((n["fret"], _mark_char(n.get("mark"))))
    out = []
    for s in range(1, 7):
        txt, run_f, run_n = "", None, 0
        for f, mk in rows[s]:
            if f == run_f:
                run_n += 1
                if run_n <= SOLO_REPEAT_CAP:
                    txt += str(f)
            else:
                run_f, run_n = f, 1
                txt += str(f) + mk
        out.append(f"{STR_LABELS[s]}|{txt[:SOLO_CELL_CHARS]:<{SOLO_CELL_CHARS}}")
    return "\n".join(out)


# ── Solo boards (Phase 3: per-measure fretboard boards) ───────────────

def _solo_dense(notes):
    """True when a measure is too dense for a board (B3 fallback):
    > SOLO_DENSE_LIMIT notes, or > SOLO_STACK_LIMIT on one (string, fret)."""
    if len(notes) > SOLO_DENSE_LIMIT:
        return True
    pos = {}
    for n in notes:
        k = (n["string"], n["fret"])
        pos[k] = pos.get(k, 0) + 1
    return max(pos.values()) > SOLO_STACK_LIMIT


def _solo_board_inner(notes, lo, beat, width, e):
    """Append one mini fretboard board to SVG-element list `e` (B3).

    `notes`: events {t, end, string (1=high e .. 6=low E), fret} whose frets
    lie in [lo, lo+SOLO_BOARD_SPACES]. Dots are size-proportional to
    duration, with a time-order badge and a duration tail; repeats on the
    same (string, fret) are stacked with an ×n count. Connectors: h/p
    (overlapping notes), slide arrow (gap < ¼ beat), vibrato wave (same
    fret overlap). A 4-beat ruler sits below the board."""
    W, H = float(width), float(SOLO_BOARD_H)
    y0, y1 = 3.0, 44.0
    sp = (y1 - y0) / SOLO_BOARD_SPACES
    x0, x1 = 2.5, W - 2.5
    sx = (x1 - x0) / 5
    narrow = W < 40
    order = sorted(range(len(notes)), key=lambda i: notes[i]["t"])
    # technique kinds between consecutive notes in time order
    kinds = {}
    for a, b in zip(order, order[1:]):
        a_, b_ = notes[a], notes[b]
        gap = b_["t"] - a_["end"]
        df = b_["fret"] - a_["fret"]
        if gap <= 0:
            if df == 0 and a_["string"] == b_["string"]:
                kinds[(a, b)] = "vib"
            elif 0 < abs(df) <= SOLO_JUMP_NO_MARK:
                kinds[(a, b)] = "h" if df > 0 else "p"
        elif gap < SOLO_SLIDE_GAP_BEATS * beat and abs(df) <= SOLO_JUMP_NO_MARK:
            kinds[(a, b)] = "slide"
    stacks = {}
    for i in order:
        k = (notes[i]["string"], notes[i]["fret"])
        stacks[k] = stacks.get(k, 0) + 1
    used = {notes[i]["string"] for i in range(len(notes))}
    e.append("<g class='sb-board'>")
    # strings: 6 vertical lines, string 6 (low E) left -> string 1 right
    for s in range(6, 0, -1):
        x = x0 + (6 - s) * sx
        col = "#4a4a55" if s in used else "#d8d5cb"
        e.append(f"<line x1='{x:.2f}' y1='{y0:g}' x2='{x:.2f}' y2='{y1:g}' "
                 f"stroke='{col}' stroke-width='0.5'/>")
    # fret lines (SOLO_BOARD_SPACES+1); top line is the nut when lo == 0
    for j in range(SOLO_BOARD_SPACES + 1):
        y = y0 + j * sp
        nut = j == 0 and lo == 0
        e.append(f"<line x1='{x0:g}' y1='{y:.2f}' x2='{x1:.2f}' y2='{y:.2f}' "
                 f"stroke='{'#23232e' if nut else '#a5a29a'}' "
                 f"stroke-width='{1.4 if nut else 0.45:g}'/>")
    if lo > 0:
        e.append(f"<text x='{x0:g}' y='{y0 - 1.2:g}' font-size='3' font-weight='700' "
                 f"fill='#6d6c66'>{lo + 1}f</text>")

    def pos(i):
        nt = notes[i]
        return x0 + (6 - nt["string"]) * sx, y0 + (nt["fret"] - lo + 0.5) * sp

    # draw positions (stacked repeats offset vertically)
    seen = {}
    xy = {}
    for i in order:
        k = (notes[i]["string"], notes[i]["fret"])
        j = seen.get(k, 0)
        seen[k] = j + 1
        x, y = pos(i)
        xy[i] = (x, y + j * 1.4)
    durs = {i: max(0.0, (notes[i]["end"] - notes[i]["t"]) / beat) if beat > 0 else 0.0
            for i in range(len(notes))}

    def radius(i):
        rmin = 1.2 if narrow else 1.6
        rmax = 2.3 if narrow else 3.8
        r = min(max(rmin + (0.45 if narrow else 0.9) * durs[i], rmin), rmax)
        if stacks[(notes[i]["string"], notes[i]["fret"])] > 1:
            r = min(r, 1.5 if narrow else 1.9)
        return r

    # connectors (drawn under the dots)
    for (a, b), kind in kinds.items():
        if kind == "vib":
            continue
        x1_, y1_ = xy[a]
        x2_, y2_ = xy[b]
        dx, dy = x2_ - x1_, y2_ - y1_
        L = math.hypot(dx, dy)
        if L < 1.0:
            continue
        ux, uy = dx / L, dy / L
        xa, ya = x1_ + ux * (radius(a) + 0.4), y1_ + uy * (radius(a) + 0.4)
        xb, yb = x2_ - ux * (radius(b) + 0.4), y2_ - uy * (radius(b) + 0.4)
        e.append(f"<line x1='{xa:.2f}' y1='{ya:.2f}' x2='{xb:.2f}' y2='{yb:.2f}' "
                 "stroke='#6d6c66' stroke-width='0.55'/>")
        mx, my = (xa + xb) / 2, (ya + yb) / 2
        if kind in ("h", "p"):
            e.append(f"<text x='{mx:.2f}' y='{my - 0.9:.2f}' font-size='2.8' "
                     f"font-weight='700' fill='#b0512f' text-anchor='middle'>{kind}</text>")
        else:  # slide: arrow along the connector, tip toward the later note
            ah = 1.3
            ang = math.atan2(uy, ux)
            tx, ty = mx + ux * ah, my + uy * ah
            e.append(f"<line x1='{mx - ux * ah:.2f}' y1='{my - uy * ah:.2f}' "
                     f"x2='{tx:.2f}' y2='{ty:.2f}' stroke='#6d6c66' stroke-width='0.8'/>")
            for sgn in (1, -1):
                ba = ang + sgn * 2.6
                e.append(f"<line x1='{tx:.2f}' y1='{ty:.2f}' "
                         f"x2='{tx - ah * math.cos(ba):.2f}' "
                         f"y2='{ty - ah * math.sin(ba):.2f}' stroke='#6d6c66' "
                         "stroke-width='0.8'/>")
    # dots + tails + badges (in time order)
    for rank, i in enumerate(order):
        nt = notes[i]
        k = (nt["string"], nt["fret"])
        x, y = xy[i]
        r = radius(i)
        if durs[i] >= 0.2:
            tl = min(max((1.0 if narrow else 1.5) + (0.7 if narrow else 1.2) * durs[i],
                         1.0), 4.5 if narrow else 7.0)
            tl = min(tl, W - (x + r) - 0.5)  # never past the board edge
            if tl >= 0.5:
                e.append(f"<line x1='{x + r:.2f}' y1='{y:.2f}' "
                         f"x2='{x + r + tl:.2f}' y2='{y:.2f}' stroke='#b0512f' "
                         "stroke-width='0.5' opacity='0.5'/>")
        e.append(f"<circle cx='{x:.2f}' cy='{y:.2f}' r='{r:.2f}' fill='#b0512f'/>")
        fs = 2.2 if narrow else 2.6
        e.append(f"<text x='{x + r + 0.7:.2f}' y='{y - r - 0.4:.2f}' font-size='{fs:g}' "
                 f"font-weight='700' fill='#6d6c66'>{rank + 1}</text>")
        if stacks[k] > 1:
            e.append(f"<text x='{x + r + 0.7:.2f}' y='{y + r + 2.4:.2f}' font-size='2.3' "
                     f"fill='#98968c'>×{stacks[k]}</text>")
    # Phase 4: b/v marks from the pipeline's pitch contours (drawn over the
    # dots). Bend = an arc through the dot, direction = pitch travel;
    # vibrato = the same wave glyph as the inferred overlap-vibrato.
    for i in order:
        mk = notes[i].get("mark")
        if not mk:
            continue
        x, y = xy[i]
        r = radius(i)
        if mk.startswith("b"):
            up = mk == "b+"
            sgn = -1.0 if up else 1.0
            e.append(f"<path d='M {x - r - 1.3:.2f} {y - sgn * 0.9:.2f} "
                     f"Q {x:.2f} {y + sgn * 2.2:.2f} {x + r + 1.3:.2f} "
                     f"{y - sgn * 0.9:.2f}' fill='none' stroke='#6d6c66' "
                     "stroke-width='0.5'/>")
            e.append(f"<text x='{x + r + 1.9:.2f}' y='{y + sgn * 2.6:.2f}' "
                     "font-size='2.3' font-weight='700' fill='#b0512f'>b</text>")
        else:  # vibrato: wave centered over the dot
            e.append(f"<path d='M {x - 1.6:.2f} {y - 1.5:.2f} q 0.8 -1.4 1.6 0 "
                     f"q 0.8 1.4 1.6 0 q 0.8 -1.4 1.6 0' fill='none' "
                     "stroke='#6d6c66' stroke-width='0.45'/>")
    # vibrato waves (drawn over the dots)
    for (a, b), kind in kinds.items():
        if kind != "vib":
            continue
        x, y = xy[b]
        e.append(f"<path d='M {x + 1.2:.2f} {y - 1.4:.2f} q 0.7 -1.3 1.4 0 "
                 f"q 0.7 1.3 1.4 0 q 0.7 -1.3 1.4 0' fill='none' stroke='#6d6c66' "
                 "stroke-width='0.45'/>")
    # 4-beat ruler
    for i in range(4):
        x = x0 + (i + 0.5) * (x1 - x0) / 4
        e.append(f"<line x1='{x:.2f}' y1='46' x2='{x:.2f}' y2='48.5' stroke='#b8b5ab' "
                 "stroke-width='0.5'/>")
        e.append(f"<text x='{x:.2f}' y='52' font-size='2.6' fill='#b8b5ab' "
                 f"text-anchor='middle'>{i + 1}</text>")
    e.append("</g>")


def _solo_board_svg(notes, lo, beat, width):
    """Standalone per-measure solo board (B3). See _solo_board_inner.

    The viewBox keeps the base geometry (width × SOLO_BOARD_H) but the SVG
    is emitted at SOLO_BOARD_SCALE × that size, so the whole board — dots,
    tails, badges, connectors, ruler — renders uniformly larger for
    readability (2026-11-06)."""
    w = float(width)
    e = [f"<svg class='sb-svg' width='{w * SOLO_BOARD_SCALE:g}' "
         f"height='{SOLO_BOARD_H * SOLO_BOARD_SCALE:g}' "
         f"viewBox='0 0 {w:g} {SOLO_BOARD_H:g}' "
         "xmlns='http://www.w3.org/2000/svg'>"]
    _solo_board_inner(notes, lo, beat, width, e)
    e.append("</svg>")
    return "".join(e)


def _solo_boards_html(notes, beat):
    """Per-measure solo board group (B3): splits wide fret spans into
    side-by-side boards (each ≤ SOLO_BOARD_SPACES spaces). Returns HTML."""
    fmin = min(n["fret"] for n in notes)
    fmax = max(n["fret"] for n in notes)
    base = min(max(0, fmin - 1), 20 - SOLO_BOARD_SPACES)
    wins = []
    for k in range((fmax - base) // SOLO_BOARD_SPACES + 1):
        lo = base + k * SOLO_BOARD_SPACES
        g = [n for n in notes if lo <= n["fret"] <= lo + SOLO_BOARD_SPACES]
        if g:
            wins.append((lo, g))
    W = SOLO_BOARD_W / len(wins)
    e = ["<div class='sb-boards'>"]
    for lo, g in wins:
        e.append(_solo_board_svg(sorted(g, key=lambda n: n["t"]), lo, beat, W))
    e.append("</div>")
    return "".join(e)


def _solo_key_panel():
    """SOLO key panel (B3): one example board with leader-line labels plus
    a mark table, rendered once at the top of the SCORE part."""
    beat = 1.0
    mock = [
        {"t": 0.0, "end": 0.9, "string": 4, "fret": 1},    # dot + tail, badge 1
        {"t": 0.8, "end": 1.4, "string": 4, "fret": 2},    # h (fret up, overlap)
        {"t": 1.3, "end": 1.9, "string": 5, "fret": 1},    # p (fret down, overlap)
        {"t": 2.05, "end": 2.65, "string": 3, "fret": 3},  # slide (gap 0.15 beat)
        {"t": 3.0, "end": 3.9, "string": 5, "fret": 2},
        {"t": 3.4, "end": 4.0, "string": 5, "fret": 2},    # vib (same fret, overlap)
        {"t": 4.35, "end": 5.0, "string": 2, "fret": 2, "mark": "b+"},  # bend (pitch contour)
    ]
    # leader anchors (ax, ay, label_y, label) — label order is monotone in
    # anchor y so the leader lines never cross.
    leaders = [
        (21.5, 10.4, 7.0, "1, 2, 3… = play order"),
        (24.0, 13.3, 13.5, "dot size + tail = hold time"),
        (14.2, 16.7, 19.0, "p = pull-off"),
        (18.1, 16.7, 24.0, "h = hammer-on"),
        (12.5, 18.7, 29.0, "wave = hold / vibrato (inferred)"),
        (18.1, 20.1, 34.0, "arrow = slide (direction = arrow)"),
        (33.7, 21.5, 38.5, "b = bend (pitch contour)"),
        (2.5, 30.0, 41.0, "dim string = unused here"),
        (22.0, 47.0, 50.0, "1 2 3 4 = 4/4 beat ruler"),
    ]
    e = ["<div class='solo-key'>"]
    e.append("<div class='sk-title'>SOLO KEY — HOW TO READ THE BOARDS</div>")
    e.append("<div class='sk-body'>")
    e.append("<svg class='sk-svg' width='130' height='56' viewBox='0 0 130 56' "
             "xmlns='http://www.w3.org/2000/svg'>")
    _solo_board_inner(mock, 0, beat, 44.0, e)
    for ax, ay, ly, label in leaders:
        e.append(f"<line x1='{ax:.2f}' y1='{ay:.2f}' x2='49.5' y2='{ly:.2f}' "
                 "stroke='#b8b5ab' stroke-width='0.3'/>")
        e.append(f"<text x='50.5' y='{ly + 1.2:.2f}' font-size='3.4' "
                 f"fill='#6d6c66'>{esc(label)}</text>")
    e.append("</svg>")
    e.append("<table class='sk-table'>")
    for mk, desc in [
        ("●", "hold time — dot size + tail ∝ beats"),
        ("1 2 3", "play order within the measure"),
        ("h", "hammer-on (up into a higher fret)"),
        ("p", "pull-off (down to a lower fret)"),
        ("→", "slide (gap < ¼ beat; arrow = direction)"),
        ("b", "bend — pitch contour (onset→offset ≥ 1 semitone; verify)"),
        ("∿", "hold / vibrato (inferred or pitch contour)"),
        ("┆", "string unused in this measure"),
        ("4f", "board starts at fret 4 (first-fret label)"),
        ("1 2 3 4", "4/4 beat ruler"),
    ]:
        e.append(f"<tr><td class='mk'>{esc(mk)}</td><td>{esc(desc)}</td></tr>")
    e.append("</table>")
    e.append("</div></div>")
    return e


def _mini_chords(chords, shape_map):
    """Mini chord-diagram tokens (shape + name) for a list of symbols."""
    e = []
    for sym in chords:
        e.extend(chord_token_html(sym, shape_map.get(sym), mini=True))
    return e


def _score_band_html(cs, m0, m1, bar, shape_map, words_by_meas, chords_by_meas,
                     has_vocals, has_lead, lead_by_meas, solo_style):
    """One band (<= MEASURES_PER_ROW measures) of the section's score table.

    Lanes: ruler (measure numbers), Vocals (words per measure, mini chord
    diagram above the change), Rhythm (chord diagrams, instrumental
    sections), Solo (per-measure fretboard boards, or the legacy compact
    6-line text tab when solo_style is SoloStyle.TEXT or the measure is
    too dense for a board)."""
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
        beat = bar / 4 if bar > 0 else 0.5
        for m in range(m0, m1):
            t0 = start + m * bar
            notes = lead_by_meas.get(m, [])
            if notes and solo_style is SoloStyle.BOARD and not _solo_dense(notes):
                e.append(f"<td>{_solo_boards_html(notes, beat)}</td>")
            elif notes:
                e.append(f"<td><pre class='solo-cell'>{esc(_solo_cell(cs['lead'], t0, t0 + bar))}</pre></td>")
            else:
                e.append("<td></td>")
        e.append("</tr>")
    e.append("</table>")
    return e


def build_score_section_html(cs, bar, shape_map, solo_style):
    """One SCORE section: heading + measure-aligned bands of the score.

    Sections with no lyrics, no chords and no lead notes render nothing.
    `solo_style` (SoloStyle) selects the SOLO lane rendering."""
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
    lead_by_meas = {m: [] for m in range(nmeas)}
    for n in cs["lead"]:
        lead_by_meas[_measure_of(n["t"], start, bar, nmeas)].append(n)

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
                                  chords_by_meas, has_vocals, has_lead,
                                  lead_by_meas, solo_style))
    e.append("</section>")
    return e


def build_html(title, artist, meta, notes, chart_secs, analysis, solo_style):
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
    missing_shapes = [sym for sym, shp in chord_items
                      if chord_status(sym, shp) == "missing"]
    if chord_items:
        e.append("<div class='part-kicker'>CHORDS \u2014 FINGERINGS</div>")
        e.extend(chord_grid_html(chord_items))
    if missing_shapes:
        e.append(f"<div class='note'>Chords without a known shape (name only, verify "
                 f"fingering): {esc(', '.join(missing_shapes))}</div>")
    # Phase 4: note line when pitch-contour b/v marks are present in the
    # SOLO lane (only jobs from the contour-enabled pipeline have any).
    if any(n.get("mark") for cs in chart_secs for n in cs["lead"]):
        e.append("<div class='note'>Bends (b) and vibrato (v) in the SOLO lane "
                 "are inferred from the pipeline's pitch contours — verify "
                 "against the recording</div>")

    # ── Score: measure-aligned vocals · rhythm · solo (sing & play) ─────
    bar = bar_length(analysis)
    shape_map = dict(chord_items)
    if any(cs["lines"] or cs["lead"] or cs["chords"] for cs in chart_secs):
        e.append("<div class='part-kicker'>SCORE \u2014 SING &amp; PLAY (VOCALS \u00b7 RHYTHM \u00b7 SOLO)</div>")
        if solo_style is SoloStyle.BOARD and any(cs["lead"] for cs in chart_secs):
            e.extend(_solo_key_panel())
        for cs in chart_secs:
            e.extend(build_score_section_html(cs, bar, shape_map, solo_style))

    e.append("</body></html>")
    return "\n".join(e)

def render(song_dir, out_path, title=None, artist=None, solo_style=None):
    """Render <song_dir>/tab.md (+ analysis.json/lyrics.txt) to a PDF.

    Layout: CHORDS (fixed-size fingering grid) then SCORE (measure-aligned
    vocals + rhythm + solo — sing & play with a friend). `solo_style`
    (SoloStyle / 'board' | 'text'; None = 'board') selects the SOLO lane
    rendering: per-measure fretboard boards (default) or the legacy
    compact text tab.
    Returns {pdf, pages, title, artist, sections, chart_lines,
    missing_shapes, synthesized_shapes, solo_style, solo_fallbacks,
    bend_marks, vibrato_marks}
    (missing_shapes = symbols that fell through to "n/a";
    synthesized_shapes = symbols rendered by the synthesized-barre
    fallback; solo_fallbacks = measures rendered as text tab because they
    were too dense for a board; bend_marks / vibrato_marks = Phase 4
    pitch-contour marks rendered in the SOLO lane). Importable by the
    mcp_media server (media_render_tab_pdf tool)."""
    if solo_style is None:
        solo_style = "board"
    try:
        solo_style = SoloStyle(str(solo_style).strip().lower())
    except ValueError:
        raise ValueError(
            f"invalid solo_style: {solo_style!r} (expected 'board' or 'text')")
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
    doc_html = build_html(title, artist, meta, notes, chart_secs, analysis,
                          solo_style)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    # A3.2: report shape coverage so the MCP tool can warn instead of
    # silently shipping "n/a" pages.
    missing, synthesized = shape_coverage(analysis)

    # B3: count measures that fell back to the text tab (too dense for a
    # board) so the MCP tool can report the degradation.
    solo_fallbacks = 0
    if solo_style is SoloStyle.BOARD:
        bar = bar_length(analysis)
        for cs in chart_secs:
            if not cs["lead"]:
                continue
            start, end = cs["start_s"], cs["end_s"]
            nmeas = max(1, math.ceil((end - start) / bar)) if bar > 0 else 1
            by_meas = {m: [] for m in range(nmeas)}
            for n in cs["lead"]:
                by_meas[_measure_of(n["t"], start, bar, nmeas)].append(n)
            solo_fallbacks += sum(1 for g in by_meas.values()
                                  if g and _solo_dense(g))

    # Phase 4: count the pitch-contour b/v marks so the MCP tool can report
    # them (0 when the job predates pipeline pitch contours).
    bend_marks = vibrato_marks = 0
    for cs in chart_secs:
        for n in cs["lead"]:
            mk = n.get("mark")
            if mk:
                if mk.startswith("b"):
                    bend_marks += 1
                else:
                    vibrato_marks += 1

    from weasyprint import HTML

    document = HTML(string=doc_html).render()
    document.write_pdf(str(out))
    return {"pdf": str(out), "pages": len(document.pages),
            "title": title, "artist": artist or None,
            "sections": len(sections),
            "chart_lines": sum(len(cs["lines"]) for cs in chart_secs),
            "missing_shapes": missing,
            "synthesized_shapes": synthesized,
            "solo_style": solo_style.value,
            "solo_fallbacks": solo_fallbacks,
            "bend_marks": bend_marks,
            "vibrato_marks": vibrato_marks}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("song_dir", help="dir with tab.md (lyrics.txt/analysis.json optional)")
    ap.add_argument("-o", "--out", help="output PDF path (default: <song_dir>/<slug>-tab.pdf)")
    ap.add_argument("--title", help="override the LLM-guessed title")
    ap.add_argument("--artist", help="override the LLM-guessed artist")
    ap.add_argument("--solo-style", choices=["board", "text"], default="board",
                    help="SOLO lane rendering: per-measure fretboard boards "
                         "(default) or the legacy compact text tab")
    args = ap.parse_args()

    d = Path(args.song_dir)
    out = args.out if args.out else str(d / f"{d.name}-tab.pdf")
    print(json.dumps(render(d, out, title=args.title, artist=args.artist,
                            solo_style=args.solo_style)))


if __name__ == "__main__":
    main()