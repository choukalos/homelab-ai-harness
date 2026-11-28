# Shotplan schema — two-tier (Scene → Beats → Micro-shots)

The exact contract for `media_project_shotplan(slug, shotplan)` — verified
2026-11-28 against `media-pipeline/films_plan_matrix.md` §2.4 + the shipped
`media-pipeline/projects.py` `validate_shotplan()` + live 400-error probes.
The pipeline validates server-side; 400s carry the exact field errors
(`detail: "shotplan validation failed: <field> …; <field> …"`, paths like
`beats[0].micro_shots[0].shot_category`) and are surfaced verbatim by the
MCP tool — no client-side schema enforcement is needed beyond the craft
rules in SKILL.md. `media_project_shotplan` is a pure pass-through: extra
fields flow through unvalidated.

## Request schema

### Scene (top level)

| Field | Type | Required | Notes |
|---|---|---|---|
| `scene_id` | string | **yes** | 400: `scene_id is required` |
| `beats` | list | **yes, non-empty** | 400: `beats is required (non-empty list)` |
| `screen_direction_lock` | string | no (skill: always set) | 180° rule, e.g. `"Hero: screen-left facing right \| Villain: screen-right facing left"`; injected verbatim into every keyframe prompt |
| `environment_plate_id` | string | no | e.g. `env_kitchen_night` (matches `bible/environments/<id>/` asset path) |
| `color_grade_lut` | string | no | e.g. `luts/cinematic_teal_amber.cube` (used by the final assemble `lut`) |

### Beat

`beat_id` (string), `narrative_goal` (string), `micro_shots` (list).

### Micro-shot

| Field | Type | Required | Notes |
|---|---|---|---|
| `shot_id` | string | **yes** | pattern seen: `s01_b01_sh01` (scene_beat_shot); **must be unique across the whole plan** — 400: `shot_id 'x' is not unique` |
| `shot_category` | enum | **yes** | `dialogue_drama` \| `action_impact` \| `macro_insert` \| `establishing` |
| `risk_level` | enum | **yes** | `low` \| `high` (**no "medium"**); high = fight impacts, two-character interaction, lunges |
| `shot_type` | enum | **yes** | `wide` \| `medium` \| `medium_close_up` \| `extreme_close_up` |
| `duration_frames` | int | **yes** | positive int, **must be 4k+1 (wan14b-bound) AND ≤129** — 400: `duration_frames must be 4k+1 (wan14b-bound): 50` / `duration_frames must be <= 129: N`; `action_impact` shots ≤49 (≈3 s @16 fps) |
| `keyframe_prompt` | string | **yes** | static composition, ZERO motion verbs — the server emits non-fatal `schema_warnings` on motion verbs (e.g. `"motion verb(s) in a static keyframe prompt: runs"`) |
| `motion_prompt` | string | **yes** | camera + physics only; mouth closed for dialogue |
| `animatic_move` | enum | **yes** | `push_in` \| `pull_out` \| `pan_left` \| `pan_right` \| `shake` \| `static` |
| `end_keyframe_prompt` | string | **conditional** | **required when `use_end_frame_anchor` is true** (FLF2V end frame); 400: `end_keyframe_prompt is required when use_end_frame_anchor is true` |
| `character_refs` | string[] | no | e.g. `["char_hero","char_villain"]` (matches `bible/characters/<id>/`) |
| `expression_anchor` | string | no | e.g. `"narrowed eyes, tense jaw"` |
| `chain_from_prev_shot` | bool | no | frame-chaining via `media_extract_frame` last-clean-frame → next `start` |
| `use_end_frame_anchor` | bool | no | FLF2V (wan14b only) |
| `audio` | object | no | `{voice_id (string), dialogue_text (string), lip_sync_required (bool)}`; `voice_id` from `media_add_voice` |

## Response shapes

- **Save (200):** `{"shotplan": "<abs path …/storyboard/shotplan.json>", "warnings": []}`.
- **GET (200):** the full scene object + server-managed `saved` (ISO ts) and
  `schema_warnings` (list of `{shot_id, field, warning}` — non-fatal, e.g.
  motion verbs in a `keyframe_prompt`).
- **GET when none saved:** **HTTP 404**
  `{"detail": "no shotplan saved for project <slug>"}`.
- **Validation failure (400):**
  `{"detail": "shotplan validation failed: <field> …; <field> …"}` — all
  field errors in one message.

## Production mapping (media-film)

- `use_end_frame_anchor` → FLF2V hero (`media_generate_shot` `end_keyframe`)
- `chain_from_prev_shot` → `media_extract_frame` last-clean-frame → next
  shot's `start`
- `audio.lip_sync_required` → `media_lipsync` post-render
- `color_grade_lut` → final assemble `lut`
- `animatic_move` → `media_animatic` manifest `move`
- `duration_frames` → I2V `frames` (4k+1, ≤129; `action_impact` ≤49)
- `risk_level` → draft routing (high-risk shots get the draft pass; macro
  inserts + slow dialogue skip straight to hero)
