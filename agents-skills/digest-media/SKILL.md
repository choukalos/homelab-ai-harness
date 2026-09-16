---
name: digest-media
description: Analyze a film/TV episode/clip (video, image, or URL) and provide insight from three distinct perspectives in one pass — cinematics (how it's made/looks), entertainment (will it hold an audience, critics be damned), and art critics (thematic/artistic merit). Builds and stores a media digest (via vision frame analysis) so the three angles are queryable later.
---

# Media analyst (film / TV / clip)

Analyze a piece of media and give insight from **three distinct perspectives**
in one pass. The three are deliberately separate lenses — one digest, queryable
from any angle:

1. **Cinematics** — how it's made / how it looks (camera, color, composition,
   score). The craft perspective.
2. **Entertainment** — will it hold an audience. **Deliberately NOT the
   critic's POV**: hooks, pacing, rewatchability, "is it fun / worth watching".
3. **Art Critics** — thematic and artistic merit. What a thoughtful critic
   would say.

The skill builds (or loads) a `media` digest via vision frame analysis, so the
three perspectives are stored and reusable.

## When to use
- "Analyze this movie / episode / clip" (give a path, URL, or YouTube URL).
- "Is this worth watching?" → the **entertainment** lens.
- "What's the cinematography / visual style like?" → the **cinematics** lens.
- "What would a critic say? What are the themes?" → the **art critics** lens.
- "Give me the full breakdown of <title>."

## Inputs
- **source**: a video path, an image path, an http(s) URL, or a YouTube URL
  (whatever `mcp_vision` accepts).
- **perspective** (optional): focus on one lens (`cinematics` /
  `entertainment` / `art_critics`); default is all three.

## Workflow

### 1. Ensure a media digest exists
- `kb_digest_list("media")` → is there already a digest for this source?
- If yes, load it: `kb_digest_get(slug, "media")`.
- If no, **build it** (the digest skill's media branch):
  1. `vision_extract_frames(source)` → scene chapters + frames + `summary.md`
     + `chapters.json` (the map; use scene/timecode as refs).
  2. `vision_analyze_video(source, mode="scene")` → consolidated storyboard
     report (scene-by-scene visual description). For a single image,
     `vision_analyze_image(source)`.
  3. Fill the `media` template
     (`digest/references/templates/media.md`): Overview, Plot, Characters,
     **Cinematics**, **Entertainment**, **Art Critics**, open_questions,
     page_refs (timecodes).
  4. Store: `kb_digest_store(slug, "media", md, kb, source)` (kb = a media KB,
     e.g. `media` — create if missing).

### 2. Present the requested perspective(s)
- **Cinematics**: from the digest's `Cinematics` section (camera, color,
  composition, score, visual style). Ground in the visual analysis.
- **Entertainment**: from the `Entertainment` section (hooks, pacing,
  rewatchability, audience fit, verdict). Keep the critic out of it — this is
  the "would a normal viewer enjoy it" lens.
- **Art Critics**: from the `Art Critics` section (themes, artistic merit,
  context, critical verdict). This is the "what's it *about*, is it good as an
  art form" lens.

If the user asked for one lens, lead with it; offer the others.

### 3. Be honest about the boundary
- Vision analysis reads **frames** (visuals), not the full audio/dialogue
  track. Dialogue-driven insight is limited unless the frames carry on-screen
  text. Say what the analysis could and couldn't see.
- If a perspective needs more (e.g. a specific scene), re-run
  `vision_analyze_video` on that time range or `vision_analyze_image` on a
  specific frame.

## Grounding rules
- **Ground claims in the visual analysis** (cite scene/timecode). Don't
  invent plot or visuals.
- **Keep the three lenses separate.** Don't let "art critics" bleed into
  "entertainment" (the audience lens is explicitly critic-free).
- **Label interpretation.** Cinematics/entertainment/critical takes are
  interpretive — say so, and ground them in what the frames actually show.

## Notes
- **`vision_extract_frames` fps param**: takes `"full"` or a number, **not**
  `"scene"` (that errors). Scene detection is automatic for videos under 5
  min (single-pass scene extraction); longer videos use chunked scene
  extraction. Omit `fps` for the default behavior.
- Long videos: `vision_analyze_video` is long-running (minutes). For very long
  works, analyze in chunks or sample scenes.
- The digest is stored under `/home/chuck/data/ai-kb/digests/media/<slug>.md`
  and its sections are searchable in the media KB.