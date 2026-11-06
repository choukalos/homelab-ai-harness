#!/usr/bin/env python3
"""Unit test for the tab_pdf chord-shape library (enhance_tab_tool.md A3.3).

Deterministic interval check, no network / no LLM. For every OPEN_CHORDS
entry: frets (6->1, standard tuning EADGBE) -> note names -> assert
  (a) the root is present, and
  (b) no tone outside the chord's theoretical tones + allowed extensions.

Extension policy (documented, matches how these voicings are actually
published): 9th chords may carry the 13th; 6th chords may carry the 9th
(6/9); 7th chords may carry the 13th (C9/F9 voicings); sus4 may carry the
3rd (conventional) and the 11th; maj7 may carry the 11th/13th (the
E-shape maj7 family carries the 13th at the root and the 11th elsewhere).

Also: regression-guards the rejected-candidates list from
enhance_tab_tool.md A2 (they must NOT be in the library and must fail the
interval check), and exercises the synthesized-barre fallback (A3.1).

Run: python3 test_chord_shapes.py   (plain script, exit 1 on failure;
functions are also pytest-compatible).
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tab_pdf  # noqa: E402

NOTE_IDX = tab_pdf.NOTE_IDX
OPEN = tab_pdf.OPEN_STRING_SEMIS  # [4, 9, 14, 19, 23, 28] strings 6..1


def parse_symbol(sym):
    """'C#maj7' -> (root_semitone_idx, 'maj7'); 'D' -> (2, '')."""
    m = re.match(r"^([A-G])([#b]?)(.*)$", str(sym))
    if not m:
        return None, None
    return NOTE_IDX.get(m.group(1) + m.group(2)), m.group(3)


def allowed_tones(root_idx, q):
    """Pitch classes (mod 12) allowed for a chord symbol's quality."""
    if q in ("", "maj"):
        base = [0, 4, 7]
    elif q.startswith("m7b5"):
        base = [0, 3, 6, 10]
    elif q.startswith("m9"):
        base = [0, 3, 7, 10, 14]
    elif q.startswith("maj9"):
        base = [0, 4, 7, 11, 14]
    elif q.startswith("m7"):
        base = [0, 3, 7, 10]
    elif q.startswith("maj7"):
        base = [0, 4, 7, 11]
    elif q.startswith("m6"):
        base = [0, 3, 7, 9]
    elif q.startswith("9"):
        base = [0, 4, 7, 10, 14]
    elif q.startswith("7"):
        base = [0, 4, 7, 10]
    elif q.startswith("6"):
        base = [0, 4, 7, 9]
    elif q.startswith("dim7"):
        base = [0, 3, 6, 9]
    elif q.startswith("dim"):
        base = [0, 3, 6]
    elif q.startswith("aug"):
        base = [0, 4, 8]
    elif q.startswith("sus4"):
        base = [0, 5, 7]
    elif q.startswith("sus2"):
        base = [0, 2, 7]
    elif q.startswith("5"):
        base = [0, 7]
    elif q.startswith("m"):
        base = [0, 3, 7]
    else:
        base = [0, 4, 7]
    tones = {(root_idx + iv) % 12 for iv in base}
    if "9" in q:
        tones.add((root_idx + 14) % 12)   # 9th
        tones.add((root_idx + 21) % 12)   # 13th (common in 9th voicings)
    if "6" in q:
        tones.add((root_idx + 9) % 12)    # 6th/13th
        tones.add((root_idx + 14) % 12)   # 9th (6/9 voicings)
    if "7" in q and not q.startswith("maj7"):
        tones.add((root_idx + 21) % 12)   # 13th (C9/F9 voicings)
    if q.startswith("maj7"):
        tones.add((root_idx + 17) % 12)   # 11th
        tones.add((root_idx + 21) % 12)   # 13th (Emaj7 at the root)
    if q.startswith("sus4"):
        tones.add((root_idx + 4) % 12)    # 3rd (conventional in sus4)
        tones.add((root_idx + 2) % 12)    # 9th (Csus4 x33030 carries D)
    return tones


def played_notes(frets):
    return [tab_pdf.NOTE_NAMES[(open_m + f) % 12]
            for open_m, f in zip(OPEN, frets) if f is not None]


def shape_ok(sym, frets):
    """True when the shape is a valid voicing of the symbol."""
    root_idx, q = parse_symbol(sym)
    if root_idx is None:
        return False
    allowed = allowed_tones(root_idx, q)
    notes = played_notes(frets)
    if not notes:
        return False
    bad = [n for n in notes if tab_pdf.NOTE_NAMES.index(n) not in allowed]
    return not bad and root_idx % 12 in {tab_pdf.NOTE_NAMES.index(n) for n in notes}


# Rejected candidates (enhance_tab_tool.md A2) — must stay OUT of the
# library and must fail the interval check. Keep this list: it records
# shapes that look plausible but are not the named chord.
REJECTED = {
    "G9": [3, 5, 3, 5, 3, 3],       # tones G C D F = G7sus4 (no 9th)
    "E9": [0, 2, 5, 1, 0, 0],       # tones E G G# B = E6 (4th str 5th fret is G, not A)
    "Bm9": [None, 2, 3, 2, 1, 0],   # tones B F A C E — F natural = b5
    "Emaj9": [0, 2, 0, 1, 0, 0],    # tones E G# B D = Emaj7 (D = 7th, no 9th)
    "D6": [None, None, 0, 2, 1, 2], # tones D A C F# = D7 (C = 7th, not the 6th)
}

# The 2026-11-05 QA tabs (SCOM/Hurt/Californication/One) use these symbols
# with open-position hints; every one must resolve to a real shape.
QA_SONGS_OPEN_HINTS = [
    "B6", "F6", "G6",                      # the 2026-11-05 "NO SHAPE" chords
    "B7", "Bmaj7", "A6", "Cmaj7", "Am7", "Dmaj7", "Gmaj7", "Fmaj7", "C7",
    "Amaj7", "G7", "Dm7", "F#m7", "Emaj7",
]


def test_open_chords_library():
    """Every OPEN_CHORDS entry passes the interval check (A3.3)."""
    bad = []
    for sym, frets in tab_pdf.OPEN_CHORDS.items():
        if not shape_ok(sym, frets):
            bad.append(f"{sym} {frets} -> {played_notes(frets)}")
    assert not bad, "invalid shapes: " + "; ".join(bad)


def test_qa_songs_covered():
    """The 2026-11-05 QA tabs' open-hint chords all have library entries
    (A1 confirmed missing + A2 safe set)."""
    missing = [s for s in QA_SONGS_OPEN_HINTS if s not in tab_pdf.OPEN_CHORDS]
    assert not missing, f"missing from OPEN_CHORDS: {missing}"
    for sym in QA_SONGS_OPEN_HINTS:
        ok, detail = shape_ok(sym, tab_pdf.OPEN_CHORDS[sym]), sym
        assert shape_ok(sym, tab_pdf.OPEN_CHORDS[sym]), f"{sym} invalid"


def test_rejected_candidates():
    """Rejected candidates (enhance_tab_tool.md A2) are neither in the
    library nor valid voicings — regression guard."""
    for sym, frets in REJECTED.items():
        assert tab_pdf.OPEN_CHORDS.get(sym) != frets, \
            f"{sym}: rejected shape {frets} is in the library"
        assert not shape_ok(sym, frets), \
            f"rejected shape {sym} {frets} passed the interval check"
    # D7/D6 disambiguation: xx0212 is D7, xx0202 is D6
    assert shape_ok("D7", [None, None, 0, 2, 1, 2])
    assert shape_ok("D6", [None, None, 0, 2, 0, 2])
    assert not shape_ok("D6", [None, None, 0, 2, 1, 2])  # that's a D7 voicing


def test_synth_barre_fallback():
    """A3.1: unknown symbols with an open hint synthesize a playable barre."""
    open_hint = {"type": "open", "base": None, "fret": None}
    # B6 with the pipeline's open hint renders the library shape
    frets, start, note = tab_pdf.chord_frets("B6", open_hint)
    assert frets is not None and note == "open", f"B6: {frets} {note}"
    # unknown-but-parseable symbols fall back to a synthesized barre
    for sym in ("Badd9", "C#m9", "Db6", "G#m7"):
        frets, start, note = tab_pdf.chord_frets(sym, open_hint)
        assert frets is not None, f"{sym}: no shape"
        assert "synthesized" in note, f"{sym}: note={note!r}"
        root_idx, _ = parse_symbol(sym)
        # root must sit at the start fret on the 6th or 5th string
        assert (frets[0] == start) or (frets[1] == start), \
            f"{sym}: root not at start fret: {frets} start={start}"
    # unparseable symbols still report missing (honest n/a)
    assert tab_pdf.chord_frets("??", open_hint)[0] is None
    assert tab_pdf.chord_status("??", open_hint) == "missing"


def test_chord_status():
    """A3.2: chord_status classifies every path."""
    open_hint = {"type": "open", "base": None, "fret": None}
    assert tab_pdf.chord_status("C", None) == "open"
    assert tab_pdf.chord_status("C", open_hint) == "open"
    assert tab_pdf.chord_status("C#maj7", {"type": "barre", "base": "A", "fret": 4}) == "barre"
    assert tab_pdf.chord_status("A5", {"type": "power", "base": "A", "fret": 5}) == "power"
    assert tab_pdf.chord_status("Badd9", open_hint) == "synthesized"
    assert tab_pdf.chord_status("??", open_hint) == "missing"


def test_shape_coverage():
    """A3.2: shape_coverage() classifies missing vs synthesized; render()
    surfaces both (checked end-to-end in the docker smoke test, which has
    weasyprint)."""
    open_hint = {"type": "open", "base": None, "fret": None}
    analysis = {"sections": [
        {"chords": [
            {"time_s": 0.0, "symbol": "Badd9", "shape": open_hint},
            {"time_s": 8.0, "symbol": "C", "shape": open_hint},
            {"time_s": 16.0, "symbol": "??", "shape": open_hint},
        ]}]}
    missing, synthesized = tab_pdf.shape_coverage(analysis)
    assert missing == ["??"], missing
    assert synthesized == ["Badd9"], synthesized
    # the 2026-11-05 QA chord set: no missing, no synthesized
    qa = {"sections": [{"chords": [
        {"time_s": 0.0, "symbol": s, "shape": open_hint}
        for s in QA_SONGS_OPEN_HINTS]}]}
    assert tab_pdf.shape_coverage(qa) == ([], []), tab_pdf.shape_coverage(qa)


def main():
    ok = fail = 0
    for fn in (test_open_chords_library, test_qa_songs_covered,
               test_rejected_candidates, test_synth_barre_fallback,
               test_chord_status, test_shape_coverage):
        try:
            fn()
            ok += 1
            print(f"PASS {fn.__name__}")
        except AssertionError as e:
            fail += 1
            print(f"FAIL {fn.__name__}: {e}")
    print(f"\n{ok} passed, {fail} failed "
          f"({len(tab_pdf.OPEN_CHORDS)} library entries checked)")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
