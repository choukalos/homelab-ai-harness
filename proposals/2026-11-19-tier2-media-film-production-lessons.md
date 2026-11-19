# media-film skill: bake in the SW Holiday Spoof production lessons (thor-side)

- slug: tier2-media-film-production-lessons
- date: 2026-11-19
- status: open
- tier: 2
- target user: chuck
- source: workspace/ideas/2026-11-17-media-pipeline-improvements.md (C1–C14, A2, D1 — thor-side items; matrix-side items are in `tier2-matrix-media-pipeline-improvements`)

## What
Update `agents-skills/media-film/` (SKILL.md + `references/pipeline-contract.md` + `templates/`) with the lessons from the 2026-11-16/17 production run. Verified 2026-11-19: **none** of these are in the committed skill (no `tpad`/natural-length caveat, no 22050 probe, no `amix normalize=0`, no `validate_state`, no identity re-anchor, no implied-gag rule, no `ACCEPTED-WITH-NOTE`).

**P0**
- **C14 — `shots[].duration` does NOT frame-hold.** Document in the pipeline contract that the assembler concatenates at natural clip length (the `duration` field is accepted but has no effect). Plan rule: per-shot durations MUST be derived from the actual clip length (`media_info` after I2V) — never a creative estimate. P6 QC gate: in addition to `duration ∈ [180,240]`, verify the **last VO start + VO duration** and the **last overlay end fit inside the cut** — the numeric gate alone let a 44.5 s-short film (missing closing VO + end card) pass after a 4.5 h upscale render.
- **C1 — state drift.** Make per-shot records the single source of truth (`shots.<id>.{kf,i2v,qc,vo}`); derive pending lists at read time (or recompute on every write). Ship `tools/validate_state.py` (cross-check lists vs records, job ids vs ledger, paths vs `media_info`); children run it as preflight and refuse to proceed on mismatch (or auto-repair).

**P1**
- **C9 — TTS is 22050 Hz mono.** Skill template: probe the actual sample rate before `asetrate` (`ffmpeg -i` / `media_info`); formula `asetrate=SR*P,aresample=44100` with SR from the probe, not the plan text. Document TTS output format (22050 Hz mono) and music format (48000 Hz stereo) in the pipeline contract. (The plan's 44100-based formula would have doubled every pitch shift — silent landmine.)
- **C10 — `amix` normalize.** VO mix template: always `normalize=0` + post-mix level check (`volumedetect`/`astats` mean/max dB sanity gate before upload). (19-input default-normalize mix is ~25 dB too quiet — effectively silent.)
- **C3 — `i2v_prompt` identity re-anchor.** Template: `[one-line identity re-anchor per character in frame] + [gentle motion spec] + [1978 TV look]`. (S4 drifted tuxedo bicolor → brown tabby over 5 s; the keyframe only anchors frame 0.)
- **C4 — implied gags.** Plan-stage feasibility rule: if a gag depends on a complex object state (broken, headless, torn, melted), make it implied (SFX + caption + reaction shots), not rendered. Make `ACCEPTED-WITH-NOTE` a first-class QC outcome with explicit criteria (the VO or a neighbor shot carries the beat).
- **C2 — shot-card schema.** Explicit JSON Schema / `shots/_card_template.json` + a 10-line validator the parent runs before production (string `vo_text`, canonical voices, numeric `duration_s`). (Three different `vo_text` shapes appeared in one run.)

**P2**
- **C5** — plan-stage validation: count characters in each frame from the identity refs, enforce ≤3 (or flag for the reviewer).
- **C6** — bounded fix-forward budgets: kf = 3 (then accept-with-note or shots.json fallback), I2V clip = 2 (then accept best), audio = 2.
- **C7** — batch vision QC: if the vision tool accepts multiple images, judge the 3 action frames in one call.
- **C8** — assemble preflight: `media_info` on every shot path + every audio path; abort with a precise missing-list.
- **C11** — single canonical state key per audio item (`tts_<shot>` / `sfx_<name>` / `music_cue_<x>`), written once at submit, updated in place; no parallel key families (stale `submitted` keys over-report pending audio).
- **C12** — raw-text prompt getter in the state helper; submit path builds MCP args with `jq -n --arg`, never pastes JSON-encoded values into prompt fields; preflight diff: submitted prompt == card `i2v_prompt` exactly.
- **C13 (thor-side)** — pipeline contract publishes expected wall-clock per assemble config (range-based: ~12.5 min/shot upscale observed under shared-queue contention, not the ~5 min estimate); offer a **draft assemble** (`upscale_each: false`, ~90 s for 36 shots) for QC-before-commit — assemble the draft, run P6 vision QC, only pay for the final upscaled render if the draft passes.
- **A2** — workflow convention: cap shot-director fan-out at 8–12 concurrent (batch into 3–4 waves); the GPU queue is the real bottleneck downstream anyway.
- **D1** — workflow convention: per-shot auto-retry (1 retry on `!ok`, 120 s backoff for 524s) + preflight gate before production verifying all shot cards exist on disk.

## Why (evidence)
- Film published 2026-11-17 15:04Z after ~16 h, 30 production attempts: 11/36 children died on 524s, 5 production attempts killed at exactly 30 min, C14 cost one full 4.5 h upscale render + fix-forward, C9/C10 were silent landmines that would have forced a full VO re-mix after publish-stage discovery.
- The skill was committed 2026-11-17 (`9d2b145`) **without** these lessons — the next film run hits the same defects.

## Risk + rollback
Low — docs, templates, skill text, one new validator script. Rollback = revert.

## Files touched
- `agents-skills/media-film/SKILL.md`
- `agents-skills/media-film/references/pipeline-contract.md`
- `agents-skills/media-film/templates/` (+ new `tools/validate_state.py`)

---
_Drafted 2026-11-19 (pi, thor) from the workspace/ideas review. Review with `cli/proposals.sh`; applying is a human decision._
