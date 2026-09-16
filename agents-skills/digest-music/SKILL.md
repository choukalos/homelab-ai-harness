---
name: digest-music
description: Answer music-theory questions and generate scales/chords/progressions from a music_theory digest. Uses the digest's machine-checkable computation rules (interval arrays, scale patterns, chord formulas) so outputs are reproducible, and verifies load-bearing results with the reusable checker.
---

# Music theory (from a music_theory digest)

Answer theory questions and generate scales/chords/progressions *from a
`music_theory` digest*. The digest captures the computation rules in
machine-checkable form (interval arrays, scale patterns, chord formulas), so
outputs are reproducible and verifiable — not vibes.

## When to use
- "What's the relative minor of G major?"
- "Generate the C major scale / A natural minor scale."
- "What are the diatonic triads of D major?"
- "Build a I–IV–V–I progression in E."
- "What interval is C to G?"

## Prerequisites
- A `music_theory` digest (`kb_digest_get(slug, "music_theory")`). If none
  exists, run `/skill:digest` on a theory source (textbook, Wikipedia
  articles, etc.) first.

## Workflow
1. **Load the digest**: `kb_digest_get(slug, "music_theory")`. It has:
   concepts, relationships (the computation rules), practice_exercises,
   gotchas, Verification.
2. **Read the computation rules** you need:
   - Chromatic circle (the 12-note array).
   - Scale patterns as interval arrays (e.g. major = [2,2,1,2,2,2,1]).
   - Relative-minor rule (major tonic − 3 semitones = the 6th degree).
   - Diatonic triad formula (stack thirds; quality pattern).
   - Circle of fifths (+7 semitones per step).
3. **Compute** the answer using the rules (a short script or careful
   arithmetic). For scales/chords, generate the notes from the tonic + the
   interval array.
4. **Verify** with the checker: `python3 scripts/theory.py <command>` (see
   below). It independently recomputes and asserts known answers.
5. **Present** the answer with the reasoning (which rule, which notes).

## The checker (scripts/theory.py)
A reusable, self-contained checker that encodes the core rules and asserts
known answers (the same checks that passed in the stress test). Use it to
verify your outputs:
```bash
python3 scripts/theory.py scale C major        # C D E F G A B
python3 scripts/theory.py relative_minor G     # E
python3 scripts/theory.py diatonic C           # I M, ii m, iii m, IV M, V M, vi m, vii° dim
python3 scripts/theory.py interval C G         # P5
python3 scripts/theory.py circle 5             # C G D A E B F# C# ...
python3 scripts/theory.py check                # run all built-in checks
```
If your answer disagrees with the checker, the digest (or your arithmetic) is
wrong — fix it and re-verify.

## Grounding rules
- **Use the digest's rules, not your memory.** The digest's interval arrays
  and formulas are the source. (The stress test caught a real error here:
  relative minor is −3 semitones, not +3.)
- **Verify non-trivial outputs** with the checker.
- **Name the rule** you used (e.g. "relative minor = 6th degree = tonic − 3
  semitones").

## Notes
- The checker encodes the standard Western tonal rules from the digest. For
  non-standard theory (modes, atonality, microtonality), read the source and
  note the checker doesn't cover it.
- Keep answers concrete (actual note names), not just "the 6th degree".