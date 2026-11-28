---
name: media-storyboard
description: "Interactive film pre-production on the NAS-durable project store (mcp_media film-project tools) — intake, character/environment look-dev, the two-tier shotplan (Scene → Beats → Micro-shots), multi-reference keyframe pass, storyboard-page review loop, and the approve gate. HARD RULE: no I2V/draft video spend before media_project_approve lands. Ends by handing off to the media-film skill for production."
---

# media-storyboard — interactive pre-production with approve gate

Plan a film or short **with the user in the loop**, on the NAS-durable film
project store (`mcp_media` `media_project_*` tools + the production image
tools). Everything here is pre-production: by the time this skill ends, the
project has approved storyboard pages and a saved two-tier shotplan — and
the `media-film` skill picks up from the project store for production.

**Source of truth:** the film project store on the GPU host
(`media_projects/<slug>/`, mirrored append-only to the NAS after every
mutation — a NAS failure never fails a mutation: `nas_sync.pending` +
hourly retry). `media_project_get(slug)` is the durable source of truth that
survives session resets; every asset and the shotplan live there.

## When to use

- The user wants to plan/pitch a film or short ("storyboard a film about X").
- Pre-production for a film that will be produced by the `media-film` skill.

Not for: producing video (that's `media-film` — and it refuses to render
until this skill's approve gate has landed), single-image or single-clip
jobs (call the tool directly), song transcription (the `song-transcribe`
skill).

## The hard rule (anti-suck-atude gate)

**No I2V/draft video spend before `media_project_approve` lands.** No
`media_generate_shot` calls, no `ltxv2b` drafts, no "quick test clip" — not
even one. The storyboard (keyframes + pages + user acceptance) is the
pacing/physics/continuity gate: it costs image generation only, and it is
where bad shots get caught before ~11 min/clip of wan14b (or the 4.5 h
upscale render) is burned. This is the potato-wars incident gate — the
2026-11-27 films handoff makes it a hard rule, not a suggestion.

Image generation (keyframes, character sheets, env plates) is allowed at any
time — that is the point of the skill.

## The tools (mcp_media)

| Tool | Used for |
|---|---|
| `media_project_create(slug, title?)` | S1 — create the project (sync) |
| `media_project_get(slug)` | every step — durable state (404 unknown) |
| `media_project_list()` | recover a project's slug after a session reset |
| `media_project_asset(slug, path, file)` | register every asset (sync) |
| `media_project_shotplan(slug, shotplan?)` | S3 — save/get the two-tier shotplan (sync pass-through) |
| `media_project_storyboard_pages(slug, per_page?, page_size?)` | S5 — render labeled review pages (sync, ffmpeg-only — not a pipeline job) |
| `media_project_approve(slug, what="storyboard", note?)` | S6 — the approve gate (sync) |
| `media_project_sync(slug)` | S6 — force the NAS mirror (sync) |
| `media_generate_image` | S2/S4 — character sheets, emotion grids, env plates, keyframes |
| `media_edit_image` | S4 — multi-reference keyframe compositing (character sheets + env plate) |
| `media_add_voice` | S2 — locked voices per speaking character |
| `media_list_voices` | S2 — pick/verify voices |
| `media_fetch` | S5 — download pages/keyframes for the user's review |
| `media_pull` | vision QC of GPU-host images (signed URL) |

The project-store tools are **sync** (no `job_id`, no queue, no
`non_blocking`). The job tools (`media_generate_image`, `media_edit_image`,
`media_add_voice`) follow the usual conventions: `non_blocking` +
`media_job_result` polling, `client` tag (convention `<project>/<unit>`),
`{path, location}` results, the 60 s gateway timeout (transient — retry the
call) and 503 queue-full (stop submitting, poll) — see `media-film` R2/R5.

## Workflow

### S1 — Intake

1. Interview the user: **premise, characters, style, target duration** (and
   tone/audience). Write it down — the premise is the brief for everything
   downstream.
2. `media_project_create(slug, title)` — slug `^[a-z0-9_]{1,64}$`
   (lowercase letters/digits/underscores; 400 otherwise, 409 if it exists).
   The store is the durable source of truth from this moment on.
3. Write the script/outline to `storyboard/script.md` via
   `media_project_asset(slug, "storyboard/script.md", <file>)`.

### S2 — Pre-production assets (before any shot keyframe)

Generate and register the look-dev assets first — every keyframe
compositing step (S4) is multi-reference against these, and a keyframe
without a locked character sheet is a character-drift incident waiting to
happen.

- **Per character** → `bible/characters/<char_id>/`:
  - **turnaround sheet** — front / 3-4 profile / back, neutral lighting,
    neutral gray background (`media_generate_image`, 1280×720, `qwen21`);
    register as `bible/characters/<char_id>/turnaround.png`.
  - **2×2 emotion grid** — neutral / angry / shocked / smirking (same
    character, same lighting) →
    `bible/characters/<char_id>/emotion_grid.png`. The shotplan's
    `expression_anchor` text points at these.
- **Per location** → `bible/environments/<env_id>/`: **3–4 environment
  plates** — angle-specific **empty sets** (no characters: north wall,
  south wall, low angle, over-the-counter), consistent lighting/props
  (`media_generate_image`) →
  `bible/environments/<env_id>/plate_<angle>.png`. Set the scene's
  `environment_plate_id` to this `<env_id>`.
- **Per speaking character**: create a **locked voice** —
  `media_add_voice` from a 3–15 s reference line (stage the reference wav
  with `media_put` first). Record the `voice_id` in every shotplan `audio`
  block for that character (S3) — registered voices are permanent until
  deleted (outside the 14-day media_jobs sweep).
- Register **every** asset with `media_project_asset` (the NAS mirror picks
  it up after the mutation; check `nas_sync.pending` in `media_project_get`).

### S3 — Two-tier shotplan (Scene → Beats → Micro-shots)

The shotplan is the anti-suck-atude contract: it is prescriptive enough that
production (`media-film`) needs zero re-planning. **The schema is exactly
`references/shotplan-schema.md`** (verified against the pipeline's
`validate_shotplan()` — the pipeline 400s with the exact field errors,
surfaced verbatim by `media_project_shotplan`).

Write one scene object per scene (or one combined scene for a short) and
save with `media_project_shotplan(slug, scene)`. Enforce the craft rules
while writing:

- **One physical beat per action shot.** Never "they clash blades, spin,
  and parry" — break it into micro-shots: the wind-up, the strike, the
  impact insert, the reaction. `duration_frames` is **4k+1** (wan14b-bound)
  and **≤129**; `action_impact` shots **≤49 frames** (~3 s @16 fps).
- **180° rule.** Every scene gets a `screen_direction_lock` (e.g. "Hero:
  screen-left facing right | Villain: screen-right facing left") —
  **injected verbatim into every keyframe prompt** in that scene. AI models
  love to flip characters across cuts; the lock is what keeps the viewer
  oriented.
- **Shot mix for action ≈10% wide / 50% medium / 40% macro inserts.** Wide
  = where they are in the room (minimal action); medium = waist-up
  (upper-body physics + face, legs out of frame); macro inserts = 0.8–1.2 s
  extreme close-ups with no faces (hands, sparks, feet) — they render fast,
  never drift, and make action feel twice as intense.
- **`keyframe_prompt` = static composition, ZERO motion verbs.** Lens
  (35mm anamorphic, 85mm, 100mm macro), lighting direction, spatial
  placement (left third, foreground), the `screen_direction_lock` line, the
  character refs + `expression_anchor`. The pipeline warns (non-fatal
  `schema_warnings`) on motion verbs — a keyframe is a still, not a clip.
- **`motion_prompt` = camera + physics only, ZERO appearance words.** Do not
  re-describe what the characters look like (the keyframe already drew
  them): velocity, physics, camera (handheld whip-pan right, sparks
  flying). **Mouth closed for dialogue** — the video model never talks
  (lip-sync is a post-render pass in production; see `media-film` F8).
- **`risk_level` on every shot** (`low` | `high` — there is no `medium`):
  high = fight impacts, two-character interaction, lunges. It routes
  production (draft passes on high-risk shots only).
- **`use_end_frame_anchor: true`** (FLF2V — wan14b only) for shots where
  the end pose matters (a block that must land, a lunge that must stop) —
  and then `end_keyframe_prompt` is **required** (the pipeline 400s
  without it).
- **`chain_from_prev_shot: true`** where continuity across a fast cut needs
  the previous shot's last clean frame as this shot's start (production
  extracts it with `media_extract_frame`).
- **`audio` on every speaking shot**: `{voice_id, dialogue_text,
  lip_sync_required}` — `voice_id` from S2's locked voices.
- **`shot_id` is unique across the whole plan** (pattern
  `s<scene>_b<beat>_sh<n>`, e.g. `s01_b01_sh01`) — the pipeline 400s on
  duplicates.
- **Scene level:** `scene_id` + `beats` (non-empty) are required; set
  `screen_direction_lock`, `environment_plate_id`, and `color_grade_lut`
  (the bundled LUT for the final assemble: `cinematic_teal_amber` /
  `warm_neutral` / `cool_noir`).

After each save, read the response: `warnings` / `schema_warnings` are
non-fatal (fix motion verbs anyway); a 400 carries the exact field errors —
fix and re-save. GET the saved plan (`media_project_shotplan(slug)`) and
show the user the JSON — the review loop covers both the pages and the
shotplan.

### S4 — Keyframe pass

Per shot, in order:

1. **Compose the keyframe** with `media_edit_image`: base = the environment
   plate for the shot's angle (or a neutral canvas for character-free
   inserts), `references` = the character sheet(s) + emotion grid (up to 9),
   prompt = the shot's `keyframe_prompt` (with the scene's
   `screen_direction_lock` line verbatim). For `use_end_frame_anchor`
   shots, compose the **end keyframe** too (from `end_keyframe_prompt`).
   (Plain `media_generate_image` is fine for character-free macro
   inserts.)
2. **Vision-QC every keyframe before the next** (one image → one vision
   call): identity matches the sheet, spatial placement matches the prompt,
   no extra limbs/warped faces, lighting matches the env plate.
   **Re-seed ≤3×, then flag the shot to the user** (a fourth attempt is a
   scope decision for the owner, not the worker).
3. **Register the keyframe** with `media_project_asset(slug,
   "storyboard/keyframes/<shot_id>.png", <file>)` (end keyframe:
   `storyboard/keyframes/<shot_id>_end.png`).

### S5 — Pages + review loop

1. `media_project_storyboard_pages(slug)` (sync, ffmpeg-only — returns
   directly: `{pages: [abs page paths], n_shots, n_pages, page_size,
   per_page}`; `per_page` 1..24 default 6, `page_size` WxH (64..2048 each)
   default 640×360; missing keyframes render as placeholder cells; 400 on
   bad params or a missing shotplan).
2. `media_fetch` each page and **present the pages to the user** (and the
   saved shotplan JSON for the text side).
3. **Explicit accept/revise loop** — the user reviews, requests per-shot
   changes: regenerate **only the changed keyframes** (S4 steps 2–3 for
   those shots), re-render the pages, repeat. **Do not proceed until the
   user explicitly accepts.** (This is where pacing, framing, and screen
   direction get fixed at image cost, not video cost.)

### S6 — Approve + handoff

1. `media_project_approve(slug, "storyboard", note="<what was accepted>")`
   — the gate. `media_project_get` now shows `status:
   'storyboard_approved'` + `approval.storyboard` timestamp. (v1:
   `what="storyboard"` only — anything else 400s; idempotent.)
2. `media_project_sync(slug)` — force the NAS mirror (success:
   `{ok: true, pending: false, files, local_files, dest}`; a NAS failure is
   **not an error** — `{ok: false, pending: true, reason, files: 0}`, the
   project is intact on the GPU host and retries hourly; confirm
   `nas_sync.pending` clears before handoff).
3. Tell the user the project is **ready for production** and hand off to
   the `media-film` skill: it starts from `media_project_get(slug)` (the
   durable store), checks the approve gate, and runs the animatic → draft →
   hero phases from the approved shotplan.

## Session reset

The project store is the recovery path: `media_project_list()` → find the
slug → `media_project_get(slug)` (assets, shotplan, approval state,
`nas_sync`) → resume at the step the state indicates (e.g. keyframes
registered but pages not rendered → S5; approved but not synced → S6 step
2).

## Verification plan

- **End-to-end 4-shot test project** through the approve gate:
  `media_project_create` → 1 character turnaround + 1 env plate + 1 locked
  voice → 4-shot shotplan (save → 400 on an invalid variant → save) → 4
  keyframes (vision-QC'd, registered) → `media_project_storyboard_pages`
  (pages exist, correct cell count) → user accept → `media_project_approve`
  → `media_project_get` shows `storyboard_approved` + `nas_sync` ok →
  `media_project_sync` ok.
- **400 paths:** bad slug (`media_project_create`), invalid shotplan (bad
  enum / non-4k+1 duration / duplicate `shot_id` / missing
  `end_keyframe_prompt` with `use_end_frame_anchor`) — each returns the
  exact field errors.
- **Gate:** `media-film` on the unapproved project refuses to render
  (F2); on the approved project it proceeds.
