# DIGEST — music_theory
# source: <path or title>
# type: music_theory | downstream task: answer theory questions / generate
#                scales & chords / compute intervals & keys
# (also fits other *computation-rule* textbook domains: the key is capturing
#  the rules in machine-checkable form.)

## concepts
<!-- One entry per core concept: a tight definition. -->
- <term> : <definition>

## relationships
<!-- THE load-bearing section: the computation rules, in machine-checkable
     form (arrays, formulas, tables) — NOT prose. This is what makes the
     downstream task possible. -->
- <name> : <rule as an array / formula / table>
  <!-- e.g. major_scale_pattern : semitones [2,2,1,2,2,2,1]
       relative_minor : minor tonic = major tonic − 3 semitones (6th degree)
       interval_semitonemap : m2=1 M2=2 m3=3 M3=4 P4=5 TT=6 P5=7 ... -->

## practice_exercises
<!-- The downstream tasks this digest must support. These double as the
     verification checklist. -->
- <task, e.g. "generate a major scale from a tonic">

## gotchas
<!-- Easy-to-get-wrong details. (The stress test caught one here: relative
     minor is −3 semitones, not +3.) -->
- <gotcha>

## Verification
<!-- For each load-bearing rule, the independent check. e.g.:
     - generate C major from the pattern; assert it equals C D E F G A B.
     - relative minor of C major; assert it is A minor (not E).
     - diatonic triads of C; assert I M, ii m, iii m, IV M, V M, vi m, vii° dim. -->
- claim: <rule> → check: <concrete input → expected output>

## page_refs
<!-- Where each rule was grounded. -->
- <rule>: <source page / URL>