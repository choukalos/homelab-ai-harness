# <Title> — media digest

# source: <path or URL> | type: media | runtime: <N> min | year: <YYYY>

## Downstream Task
Provide insight on a film/TV work from three distinct perspectives in one pass:
(1) cinematics (how it's made/looks), (2) entertainment (will it hold an
audience), (3) art critics (thematic/artistic merit). One digest, queryable
from any angle.

## Overview
- premise: <one-paragraph logline + what the work is about>
- genre / tone: <e.g. sci-fi, grounded, slow-burn>
- setting: <time, place, world>

## Plot
- synopsis: <chronological summary, grounded in scenes>
- key_beats:
  - <beat> @ <timecode/chapter>
  - <beat> @ <timecode/chapter>
- structure: <act structure, pacing notes>

## Characters
- <name>: <role + arc, grounded>
- <name>: <role + arc>

## Cinematics
The "how it's made / how it looks" perspective. Grounded in the visual analysis
(frames, scene detection).
- cinematography: <camera work, shot scale, movement>
- color & lighting: <palette, contrast, mood>
- composition & framing: <recurring visual motifs, blocking>
- score & sound: <music, sound design, if discernible from frames>
- visual_style_notes: <what makes the look distinctive>

## Entertainment
The "will it hold an audience" perspective — **deliberately NOT the critic's
POV**. Pure audience appeal.
- hooks: <what grabs you early>
- pacing: <where it drags / surges>
- rewatchability: <rewatch value, easter eggs, quotability>
- audience_fit: <who this is for, what they'd enjoy>
- verdict: <one-line "is it fun / worth watching" — audience, not critic>

## Art Critics
The "critical / artistic merit" perspective — what a thoughtful critic would
say.
- themes: <themes + how the work develops them>
- artistic_merit: <what it does well / poorly as an art form>
- context: <how it fits the genre/period, influences>
- critical_verdict: <a critic's assessment, balanced>

## open_questions
- <ambiguities, unresolved threads, or things the frames couldn't confirm>

## page_refs
- For media, refs are **timecodes** (e.g. `00:12:34`) or **scene/chapter
  markers** (from `vision_extract_frames`' chapters.json), not page numbers.
- cinematics: <timecodes/chapters>
- plot_beats: <timecodes/chapters>
- source: <the analyzed video/image path or URL>