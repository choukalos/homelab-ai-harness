---
name: song-transcribe
description: Transcribe a song (YouTube URL, media URL, or local file) into a guitar tab + timestamped lyrics via the GPU-host media pipeline. Deterministic DSP (note events, chords, key/BPM) + ASR lyrics + LLM polish — a strong draft, not a certified tab.
---

# Song transcription (YouTube URL → guitar tab + lyrics)

Turn a song into a playable **guitar tab + timestamped lyrics**. All the heavy
work runs on the GPU-host media-pipeline (`/transcribe` flow); this skill just
drives the MCP tools and presents the result.

## When to use
- "Transpose this YouTube URL into a tab" / "make a tab + lyrics for this song"
- "What chords is this song in?" (key/BPM/chords come with the transcription)
- "Get the lyrics for this song" (timestamped)

## Inputs
- **source**: a YouTube URL (preferred), a direct http(s) media URL, a
  GPU-host media_jobs path, or a local file under the staging dir
  (`/home/chuck/workspace/media`).
- **instrument**: `guitar` only in v1 (6-string).
- **tuning**: `standard` only in v1 (EADGBE).
- **stems**: `true` by default (demucs vocal stem first — cleaner lyrics on
  dense mixes, +1–2 min); pass `false` to skip it.
- **full_notes**: `true` includes the full note events in the output.
- **whisper_model**: override the ASR model (default `large-v3`).
- **Chord/key/fingering options** (all deterministic post-processing on the
  pipeline — the LLM never touches them; defaults are faithful to the
  recording, every modification is opt-in):
  - **transpose_semitones** (int −12..12): shift the key; tab + MIDI are
    re-rendered in the new key.
  - **target_key** (a tonic like `E`, `Bb`, `F#m`): transpose from the
    *detected* key to that key (shortest direction, ±6). Wins over
    `transpose_semitones` if both are given. ("Put this song in E" →
    `target_key="E"`.)
  - **chord_style**: `as_detected` (default; 7ths/9ths/6ths as detected) |
    `triads` (7th/9th/6th → triad) | `power` (every chord → root+5th —
    idiomatic for metal, where the detected mode is unreliable).
  - **capo** (`true`): when the (transposed) key has no open shapes, the
    pipeline suggests the smallest capo (0–5) landing on a friendly
    open-shape key; chords are then shown as the finger shapes (shifted
    down by the capo, like a capo tab site).
  - **shape_hints** (default `true`): every chord annotated with its easiest
    fingering (open / E- or A-shape barre / power) computed on the final
    finger chord (after transpose + capo — what you actually play).

## Workflow

1. **Submit** (always non-blocking — a song takes minutes). Pass the
   chord/key/fingering options the user asked for (e.g. `target_key="E"`,
   `chord_style="power"`, `capo=true`); omit them for a faithful-to-the-
   recording tab:
   ```
   media_transcribe_song(source=<url>, non_blocking=true)
   → {job_id, status: "running"}
   ```
   YouTube URLs are downloaded here (yt-dlp, audio-only) and uploaded to the
   pipeline automatically — no separate ingest step.

2. **Poll** until done:
   ```
   media_job_result(job_id, wait_seconds=20)
   ```
   Repeat while `status` is `running` (expect 5–15 polls for a 3–4 min song;
   the job runs on the GPU host's serial queue — queue wait counts too).
   On done you get `{analysis, tab, lyrics, midi, audio}` (GPU-host paths).

3. **Fetch** the artifacts locally:
   ```
   media_fetch(host_path=<tab>)
   media_fetch(host_path=<lyrics>)
   ```
   (Optional: `media_fetch` the `analysis` path for the structured data —
   key/BPM/chords/notes with per-note confidence.)

4. **Present**:
   - The tab (markdown, per section with chord symbols + ASCII 6-string tab;
     shape hints like `E-shape barre @ 4` / `open A5` / `power @ 3` on the
     `Chords:` line when `shape_hints` is on, plus `Capo:` / `Transposed` /
     power / triad header lines when those options were used).
   - The lyrics (timestamped).
   - Key / BPM / chord progression from the analysis (note: when a capo was
     applied, the *sounding* key and the *finger* key differ — report both,
     e.g. "Capo 1, chords in A (sounds C#)").
   - **Always state the confidence caveat**: the output is a *strong draft* —
     chords/key/BPM/lyrics are high-confidence, the fret-by-fret lead line is
     medium-confidence. Encourage the user to verify against the recording;
     `song.mid` + `analysis.json` are the raw material for checking any line.

5. **Off-LAN delivery** (when the user wants the files on a device):
   ```
   media_pull(path=<tab>, ttl_hours=24)
   ```
   → signed public URL (`siri.choukalos.com/media/pipeline/dl/<token>`) —
   no homelab access needed.

## Grounding rules
- **Report what the pipeline returned** — don't invent chords, frets, or
  lyrics. If a section's chords are empty, say so (and offer to re-run with
  `stems=true` or a cleaner source).
- **Name the source** (title/URL) in the answer.
- **Lyrics are ASR** — flag uncertain lines; never "fix" lyrics from memory
  unless the user asks you to (and then label it as your correction).
- **v1 is guitar only** — for other instruments, say the tool is
  guitar-scoped (the note events in `analysis.json` are instrument-agnostic,
  so a re-render for another instrument is a future extension).

## Notes
- Cost: metered as `transcribe` work units (audio-seconds) + LLM polish
  tokens — see the AI Work & Spend dashboard.
- Queue: the GPU host runs 1 concurrent job + 5 queued; a 503
  (`retry_after_seconds`) means wait and resubmit — the job is idempotent
  per source.
- Artifacts live in the pipeline job dir (14-day retention); `media_pull`
  works even after the job id is evicted from the registry.
- The chord/key/fingering surface is **deterministic** (worker stage 5.5) —
  re-running with the same options gives the same tab; the LLM only labels
  sections / cleans ASR lyrics / writes confidence notes (validated, with a
  deterministic fallback). v1 scope: per-chord *easiest* shape; a global
  "consistent position" pass is a v2 refinement.