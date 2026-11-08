#!/usr/bin/env python3
"""Unit tests for Phase 4 pitch-contour b/v marks (enhance_tab_tool.md B4).

The pipeline emits a per-note `pitch_contour`: pitch deviation from the
note's nominal pitch in semitones, 5 samples across the note's duration
(onset -> offset). `tab_pdf._contour_mark` classifies a contour as a bend
("b+"/"b-"), a vibrato ("v"), or None; the SOLO lane renders bends as an
arc through the dot (+ "b" badge) and contour vibrato as a wave.

Deterministic, no network / no LLM. The full-render test needs
WeasyPrint (runs in the mcp_media container; skipped elsewhere).

Run: python3 test_solo_marks.py   (plain script, exit 1 on failure;
functions are also pytest-compatible).
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tab_pdf  # noqa: E402


# ── _contour_mark classification ──────────────────────────────────────

def test_contour_mark_classification():
    cm = tab_pdf._contour_mark
    # clear bends: sustained monotonic ramp, onset->offset >= 1 semitone
    assert cm([0.0, 0.33, 0.67, 1.0, 1.33]) == "b+"
    assert cm([1.33, 1.0, 0.67, 0.33, 0.0]) == "b-"
    # slide-in from below reads as a bend-up (pitch travels up)
    assert cm([-0.67, 0.33, 0.33, 0.33, 0.33]) == "b+"
    # vibrato: >=2 reversals with total deviation >= 0.5
    assert cm([0.0, 0.67, 0.0, 0.67, 0.0]) == "v"
    assert cm([0.67, 0.0, 0.67, 0.0, 0.67]) == "v"
    # flat / tracking jitter: no mark
    assert cm([0.0, 0.0, 0.0, 0.0, 0.0]) is None
    assert cm([0.33, 0.33, 0.0, 0.33, 0.33]) is None
    # short ramp (< 1 semitone net rise): no mark
    assert cm([0.0, 0.33, 0.67, 0.33, 0.33]) is None
    # tracking spike (1 reversal, small net rise): no mark
    assert cm([0.0, 0.0, 1.67, 0.33, 0.33]) is None
    # noise (1 reversal, small net rise): no mark
    assert cm([0.67, 0.33, 0.33, -1.67, 0.33]) is None
    # tiny-amplitude oscillation (dev < 0.5): no mark
    assert cm([0.33, 0.0, 0.33, 0.0, 0.33]) is None
    # missing / malformed contours: no mark, no crash
    assert cm(None) is None
    assert cm([]) is None
    assert cm([0.0, 0.33]) is None
    assert cm(["x", 0.33, 0.67, 1.0, 1.33]) is None


def test_mark_char():
    assert tab_pdf._mark_char(None) == ""
    assert tab_pdf._mark_char("b+") == "b"
    assert tab_pdf._mark_char("b-") == "b"
    assert tab_pdf._mark_char("v") == "v"


# ── text tab carries the marks ─────────────────────────────────────────

def test_solo_cell_marks():
    lead = [
        {"t": 0.0, "end": 0.4, "string": 4, "fret": 5, "mark": "b+"},
        {"t": 0.5, "end": 0.9, "string": 4, "fret": 7, "mark": "v"},
        {"t": 1.0, "end": 1.4, "string": 4, "fret": 7, "mark": None},
    ]
    cell = tab_pdf._solo_cell(lead, 0.0, 2.0)
    d_row = [l for l in cell.split("\n") if l.startswith("D|")][0]
    # '5b' then '7v' (the unmarked repeat of 7 carries no mark)
    assert d_row.startswith("D|5b7v7"), d_row


# ── board SVG renders the marks ────────────────────────────────────────

def test_board_svg_marks():
    notes = [
        {"t": 0.0, "end": 0.9, "string": 4, "fret": 5, "mark": "b+"},
        {"t": 1.5, "end": 2.4, "string": 3, "fret": 6, "mark": "v"},
        {"t": 3.0, "end": 3.9, "string": 5, "fret": 2, "mark": None},
    ]
    svg = tab_pdf._solo_board_svg(notes, 0, 1.0, 44.0)
    # bend: an arc path + a 'b' badge
    assert "fill='none' stroke='#6d6c66'" in svg
    assert ">b</text>" in svg, svg[-400:]
    # vibrato: a wave path over the dot
    assert svg.count("q 0.8 -1.4 1.6 0") >= 1
    # no mark on the third note: exactly one 'b' badge, one contour wave
    assert svg.count(">b</text>") == 1
    # unmarked notes still render their dots
    assert svg.count("<circle") == 3


# ── full render: counts + PDF (needs WeasyPrint) ───────────────────────

_TAB_MD = """# Test Song — guitar tab

Artist: Test Artist | Key: E minor | BPM: 120 | Tuning: Standard (EADGBE)
Confidence: medium — test fixture.
Raw data: analysis.json (test).

## [Verse] (0:00–0:08)

Chords: Em | C

Lyrics: (none — instrumental)
"""


def _fixture_analysis():
    def note(midi, t, dur, string, fret, pc, role="lead"):
        return {"midi": midi, "start_s": t, "end_s": t + dur,
                "freq_hz": 440.0, "amplitude": 0.8, "role": role,
                "tab": {"string": string, "fret": fret},
                "pitch_contour": pc}
    return {
        "version": 1, "source": "test", "instrument": "guitar",
        "tuning": "standard", "duration_s": 8.0, "key": "E minor",
        "bpm": 120.0, "stems_used": False, "polish_fallback": False,
        "confidence": "medium", "caveats": [],
        "sections": [{
            "index": 0, "label": "verse", "start_s": 0.0, "end_s": 8.0,
            "chords": [{"time_s": 0.0, "symbol": "Em", "confidence": 0.9},
                       {"time_s": 4.0, "symbol": "C", "confidence": 0.9}],
            "notes": [
                note(64, 0.0, 0.5, 1, 12, [0.0, 0.33, 0.67, 1.0, 1.33]),
                note(62, 1.0, 0.5, 2, 10, [0.0, 0.67, 0.0, 0.67, 0.0]),
                note(64, 2.0, 0.5, 1, 12, [0.33, 0.33, 0.0, 0.33, 0.33]),
                note(60, 3.0, 0.5, 3, 9, [0.0, 0.0, 0.0, 0.0, 0.0]),
            ],
            "lyrics": [],
        }],
        "chord_progression": "Em - C",
    }


def test_render_counts():
    try:
        import weasyprint  # noqa: F401
    except ImportError:
        print("  (skipped: WeasyPrint not available)")
        return
    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "tab.md"), "w") as f:
            f.write(_TAB_MD)
        import json
        with open(os.path.join(td, "analysis.json"), "w") as f:
            json.dump(_fixture_analysis(), f)
        out = os.path.join(td, "out.pdf")
        res = tab_pdf.render(td, out)
        assert res["bend_marks"] == 1, res
        assert res["vibrato_marks"] == 1, res
        assert res["solo_fallbacks"] == 0
        assert res["pages"] >= 1
        assert os.path.getsize(out) > 10_000


def main():
    ok = fail = 0
    for fn in (test_contour_mark_classification, test_mark_char,
               test_solo_cell_marks, test_board_svg_marks,
               test_render_counts):
        try:
            fn()
            ok += 1
            print(f"PASS {fn.__name__}")
        except AssertionError as e:
            fail += 1
            print(f"FAIL {fn.__name__}: {e}")
    print(f"\n{ok} passed, {fail} failed")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())