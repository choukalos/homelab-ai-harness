#!/usr/bin/env python3
"""Reusable music-theory checker (from a music_theory digest).

Encodes the core Western tonal rules in machine-checkable form and asserts
known answers. Use it to verify scale/chord/interval/progression outputs.

Usage:
    theory.py scale <tonic> <mode>     # e.g. scale C major
    theory.py relative_minor <tonic>   # e.g. relative_minor G -> E
    theory.py diatonic <tonic>         # diatonic triads of a major key
    theory.py interval <n1> <n2>       # named interval, e.g. interval C G
    theory.py circle <n>               # circle-of-fifths chain of length n
    theory.py check                    # run all built-in checks
"""
import sys

CHROMATIC = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
MAJOR = [2, 2, 1, 2, 2, 2, 1]        # whole-whole-half-whole-whole-whole-half
MINOR = [2, 1, 2, 2, 1, 2, 2]        # natural minor
# Diatonic triad quality pattern in a major key (degrees I..vii)
TRIAD_QUALITY = ["M", "m", "m", "M", "M", "m", "dim"]
# Interval name by semitone distance (within an octave)
INTERVALS = {0: "P1", 1: "m2", 2: "M2", 3: "m3", 4: "M3", 5: "P4",
             6: "TT", 7: "P5", 8: "m6", 9: "M6", 10: "m7", 11: "M7"}


def note_index(name: str) -> int:
    if name not in CHROMATIC:
        raise ValueError(f"unknown note {name!r}")
    return CHROMATIC.index(name)


def scale(tonic: str, mode: str) -> list[str]:
    """Generate a 7-note scale from a tonic + interval array."""
    pattern = MAJOR if mode.lower() in ("major", "maj") else MINOR
    start = note_index(tonic)
    out, idx = [], start
    for step in pattern:
        out.append(CHROMATIC[idx % 12])
        idx += step
    return out


def relative_minor(tonic: str) -> str:
    """Relative minor of a major tonic = 6th degree = tonic - 3 semitones."""
    return CHROMATIC[(note_index(tonic) - 3) % 12]


def diatonic(tonic: str) -> list[str]:
    """Diatonic triads of a major key (stack thirds; quality pattern I..vii)."""
    notes = scale(tonic, "major")
    out = []
    for i in range(7):
        root = notes[i]
        third = notes[(i + 2) % 7]
        fifth = notes[(i + 4) % 7]
        out.append(f"{root}{third}{fifth} {TRIAD_QUALITY[i]}")
    return out


def interval(n1: str, n2: str) -> str:
    """Named interval from n1 up to n2 (within an octave)."""
    dist = (note_index(n2) - note_index(n1)) % 12
    return INTERVALS[dist]


def circle(n: int) -> list[str]:
    """Circle-of-fifths chain of length n starting at C (+7 semitones/step)."""
    return [CHROMATIC[(i * 7) % 12] for i in range(n)]


def check() -> list[tuple[str, bool, str]]:
    """Run all built-in checks (the stress-test assertions)."""
    results = []

    def c(name, cond, detail=""):
        results.append((name, bool(cond), detail))

    c("C major scale", scale("C", "major") == ["C", "D", "E", "F", "G", "A", "B"],
      str(scale("C", "major")))
    c("G major scale", scale("G", "major") == ["G", "A", "B", "C", "D", "E", "F#"],
      str(scale("G", "major")))
    c("A natural minor", scale("A", "minor") == ["A", "B", "C", "D", "E", "F", "G"],
      str(scale("A", "minor")))
    c("relative minor C -> A", relative_minor("C") == "A", relative_minor("C"))
    c("relative minor G -> E", relative_minor("G") == "E", relative_minor("G"))
    c("relative minor D -> B", relative_minor("D") == "B", relative_minor("D"))
    c("diatonic of C", diatonic("C") == [
        "CEG M", "DFA m", "EGB m", "FAC M", "GBD M", "ACE m", "BDF dim"],
      str(diatonic("C")))
    c("interval C->G = P5", interval("C", "G") == "P5", interval("C", "G"))
    c("interval C->E = M3", interval("C", "E") == "M3", interval("C", "E"))
    c("interval C->F = P4", interval("C", "F") == "P4", interval("C", "F"))
    c("interval C->B = M7", interval("C", "B") == "M7", interval("C", "B"))
    c("interval C->F# = TT", interval("C", "F#") == "TT", interval("C", "F#"))
    c("circle of fifths (7)", circle(7) == ["C", "G", "D", "A", "E", "B", "F#"],
      str(circle(7)))
    return results


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 2
    cmd = args[0]
    if cmd == "scale" and len(args) == 3:
        print(" ".join(scale(args[1], args[2])))
    elif cmd == "relative_minor" and len(args) == 2:
        print(relative_minor(args[1]))
    elif cmd == "diatonic" and len(args) == 2:
        print("  ".join(diatonic(args[1])))
    elif cmd == "interval" and len(args) == 3:
        print(interval(args[1], args[2]))
    elif cmd == "circle" and len(args) == 2:
        print(" ".join(circle(int(args[1]))))
    elif cmd == "check":
        results = check()
        for name, ok, detail in results:
            print(f"  [{'PASS' if ok else 'FAIL'}] {name}"
                  + (f"  ({detail})" if detail else ""))
        passed = sum(1 for _, ok, _ in results if ok)
        print(f"{passed}/{len(results)} checks passed")
        return 0 if passed == len(results) else 1
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())