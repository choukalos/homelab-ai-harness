# Song Transcription (YouTube URL → guitar tab + lyrics) — Plan

> Date: 2026-10-31. Status: **PLANNED** (not started).
> Companion doc: `docs/song_transcribe_matrix_handoff.md` (GPU-host flow spec —
> the Matrix-side AI implements from that file).
> Pattern references: `docs/media-mcp-handoff.md` (pipeline contract + thin
> client), `docs/thor_mcp_architecture.md` (client access), `METRICS.md`
> ("Media Work Metering (v2)").

## 1. Goal

User story: **supply a YouTube URL of a song → get a guitar tab + lyrics**,
from any client (pi, Siri/portal, skill runner, anything with a LiteLLM key).

Target instrument for v1: **guitar** (6-string, standard tuning EADGBE).
`instrument` is a parameter from day one but v1 validates `guitar` only.

Deliverable per song (all files in the pipeline job dir, retrievable via
`media_fetch` / `media_pull`):

| File | Content |
|---|---|
| `tab.md` | Readable 6-string ASCII tab, per section, chord symbols + aligned lyrics |
| `lyrics.txt` | Timestamped lyrics (`[mm:ss.d] text`) |
| `analysis.json` | Structured, machine-checkable analysis (schema in handoff §4) |
| `song.mid` | Full polyphonic note events (verification / re-render) |
| `audio.wav` | Extracted 44.1 kHz stereo audio (the analyzed source) |

**Honest positioning (set this expectation in every output):** v1 is a strong
*draft*. Chords / key / BPM / lyrics are high-confidence (deterministic DSP +
ASR); the fret-by-fret lead line is medium-confidence (note events +
heuristics). The tab is a starting point for the player, not a certified tab —
the raw MIDI + `analysis.json` are shipped so any line can be verified.

## 2. Current state and the gap

| Piece | Today | Gap |
|---|---|---|
| `mcp_vision` | Frame analysis of video/images/YouTube (yt-dlp). **Audio dropped.** | Can't hear the music |
| `mcp_media` + media-pipeline (Matrix :8189) | Generation only (storyboard, images, I2V, TTS, ACE-Step music, SFX, upscale, assemble, trim/freeze/caption, put/pull) | No analysis flows |
| `digest-music` skill | Music *theory* from KB digest | No audio input |
| Client access | All MCP servers registered in `litellm/config.yml` (`allow_all_keys: true`) | — nothing to do |

The single missing capability: **audio analysis on the GPU host**.

## 3. Architecture (decision)

```
[ any client — pi / Siri / skill runner / external, via LiteLLM key ]
        │  MCP tools via LiteLLM (mcp_media already registered)
        ▼
[ mcp_media container (Thor) — thin client ]
        │  media_transcribe_song(source)
        │    • YouTube URL → yt-dlp audio (container-local, mcp_vision pattern)
        │    • local staging file / direct URL → existing /upload / /download
        ▼
[ GPU-host media-pipeline (Matrix :8189) — POST /transcribe (job) ]
        │  transcribe worker (NEW — see handoff doc):
        │    ffmpeg → librosa (key/BPM/sections) → basic-pitch (note events)
        │    → chord templates → faster-whisper (lyrics, +optional demucs stems)
        │    → deterministic guitar mapping (string/fret, roles)
        │    → matrix-coder VLLM polish (labels, lyrics cleanup, confidence notes)
        ▼
[ job output: tab.md / lyrics.txt / analysis.json / song.mid / audio.wav ]
        │  media_job_result (poll) · media_fetch (local) · media_pull (off-LAN)
        ▼
[ user ]
```

**Why a pipeline flow (not a standalone `mcp_music` container on Thor):**

1. Heavy work belongs on the GPU host — whisper large-v3 + optional demucs are
   GPU jobs; the VLLM polish step needs matrix-coder (Matrix-only).
2. Job queue, 503 back-pressure, 14-day retention, per-user work-unit metering,
   and identity threading (`user`/`client` on every POST) all come for free.
3. The "from any client" plumbing is already done: `mcp_media` is in
   `litellm/config.yml` with `allow_all_keys: true` — a new tool on an existing
   server appears to **every** client automatically on container restart.
   No LiteLLM config change, no per-client work, no new Caddy route
   (`media_pull` signed URLs already serve off-LAN retrieval).
4. A CPU-only Thor container would work for basic-pitch + whisper-small but
   would duplicate ingest logic, skip metering/queue, and still need Matrix
   for the LLM polish step — strictly worse.

**Why deterministic DSP + LLM polish (not LLM-generated tab):**

The tab data (string/fret per note, chords, sections) is computed
deterministically from the audio — reproducible and verifiable, in the spirit
of the `digest-music` skill ("reproducible and verifiable — not vibes"). The
LLM (matrix-coder, same worker as `/storyboard`) only: labels sections
(intro/verse/chorus), cleans up ASR lyrics (punctuation/line breaks, flags
unclear words — never invents), and writes confidence notes. The worker
renders the ASCII tab lines itself and **rejects any LLM output that alters a
tab line** (diff check); on LLM failure the deterministic version ships —
the job is never blocked on the LLM step.

**Why yt-dlp on the Thor side (not Matrix):** yt-dlp breaks when YouTube
changes; the Thor container is cheap to rebuild, and the pattern is already
proven in `mcp_vision`. The pipeline stays free of yt-dlp and accepts a
`path` (media file in `media_jobs`) as its only input.

## 4. Phases

### Phase 1 — Matrix: `/transcribe` flow (handoff doc)

Deliverable: `docs/song_transcribe_matrix_handoff.md` (the spec). The
GPU-host AI implements:

- `POST /transcribe` job flow (contract: handoff §2)
- transcribe worker, stages 0–7 (handoff §3): ingest → global features →
  note events → chords → sections → lyrics → guitar mapping → LLM polish
- output files + `analysis.json` schema (handoff §4)
- deterministic guitar mapping rules (handoff §5)
- deps: librosa, basic-pitch, faster-whisper (large-v3), demucs (optional)
  (handoff §6)
- new work-unit kind `transcribe` (audio-seconds) in metering (handoff §8)
- QA checklist (handoff §9)

### Phase 2 — Thor: `mcp_media` client

Files to change (all in this repo):

| File | Change |
|---|---|
| `mcp/servers/media/Dockerfile` | `RUN pip install --no-cache-dir yt-dlp` (pattern: `mcp/servers/vision/Dockerfile`) |
| `mcp/servers/media/media_pipeline_client.py` | High-level `transcribe(path, instrument, lyrics, stems, user, client, non_blocking, timeout)` → `POST /transcribe`; `finalize_job` gains a transcribe branch (output has `tab` → return `{analysis, tab, lyrics, midi, audio, location: "gpu_host"}`) |
| `mcp/servers/media/server.py` | New tool `media_transcribe_song` (spec below) + YouTube source resolution (regex per `mcp_vision` `_download_youtube`, audio-only: `-f bestaudio --no-playlist` → m4a/webm, no ffmpeg needed on Thor — the pipeline decodes) |
| `mcp/servers/media/README.md` | Tool table row + history entry |
| `docs/media-mcp-handoff.md` | Append `/transcribe` to the §4 API contract table (canonical contract) |

**`media_transcribe_song` tool spec:**

```
media_transcribe_song(
    source: str,            # YouTube URL | http(s) URL | GPU-host path | thor staging file
    instrument: str = "guitar",   # v1: "guitar" only (else clean 400-style error)
    lyrics: bool = True,          # run ASR
    stems: bool = False,          # demucs vocal stem first (cleaner lyrics, +1–2 min)
    non_blocking: bool = False,   # existing submit-and-poll pattern
) -> dict
```

Source resolution (follows the existing path model in `server.py`):

1. **YouTube URL** (`YOUTUBE_RE`): yt-dlp in-container → bestaudio file →
   `POST /upload` (multipart; 500 MB cap is far above a song's audio) → path.
2. **Direct http(s) URL**: pipeline's existing `POST /download` (sync) → path.
3. **GPU-host path** (starts with the media_jobs prefix): pass through.
4. **Thor-local file**: must be under `MEDIA_STAGING_DIR` (same guard as
   `media_trim`/`media_freeze`/`media_caption`) → `POST /upload` → path.

Then `POST /transcribe` with `user`/`client` stamped (existing identity
threading — automatic). Blocking: poll to done (per-flow timeout, transcribe
≤ 30 min budget). Non-blocking: return `{job_id, status: "running"}` in ~1 s;
clients poll `media_job_result` (already generic — works via the
`finalize_job` extension). Retrieval: `media_fetch` (local copy) and
`media_pull` (signed public URL, off-LAN) work unchanged on the returned
paths.

### Phase 3 — pi skill + docs

- **`agents-skills/song-transcribe/SKILL.md`** — the natural-language entry
  point ("transpose this YouTube URL into a tab"). Workflow:
  1. `media_transcribe_song(source, non_blocking=true)` → `job_id`
  2. Poll `media_job_result(job_id, wait_seconds=20)` until done (transcribe
     is minutes-long; expect 5–15 polls)
  3. `media_fetch` the `tab` + `lyrics` paths → local
  4. Present the tab (markdown) + lyrics; state the confidence caveats;
     offer `media_pull` signed URLs for off-LAN retrieval
  5. Optional: store `analysis.json` facts into a `music_theory`/`media`
     digest via `kb_*` for later queries
- **Docs:** `README.md` (MCP table row + short section),
  `docs/thor_ai_inventory.md` — the "71 tools" history line was stale
  (predates the 2026-09-25 `media_job_result` + 3 voice tools and further
  Sept–Oct additions; live count as of 2026-10-31 is **87**, verified via
  LiteLLM `/mcp-rest/tools/list`) — extended with the 75 and 87 marks — and
  `docs/thor_validation_log.md` (verification entry, per house convention).

### Phase 4 (optional, later) — Siri / skill-runner skill

`POST /skills/song-transcribe` (skill.py/skill.yml in the skill-runner,
registered via the existing pattern in `docs/thor_skill_architecture.md`) so
"transcribe this song" works from the Siri chat channel. The pi skill
(Phase 3) is the v1 surface; Phase 4 is a thin wrapper over the same MCP
tools.

## 5. Metering

- New work-unit kind **`transcribe`**: `audio_seconds × rate`. Placeholder
  rate = the existing audio rate ($3.1e-5/s, `METRICS.md` Media Work
  Metering v2); calibrate on Matrix after the first real runs (same
  procedure as the 2026-09-09 calibration).
- VLLM polish tokens route through the LiteLLM proxy with the caller's key →
  counted in **LLM $** (storyboard pattern; excluded from media $ to avoid
  double counting — the permanent rule).

## 6. Verification plan

**Matrix (handoff §9, summary):** health unchanged → known-song job completes
with all 5 outputs → `analysis.json` schema valid → deterministic re-run
identical (tab data) → chord accuracy on a known I–IV–V–I recording
(100%) → every tab note asserts `midi == open_string + fret` and
`1 ≤ string ≤ 6, 0 ≤ fret ≤ 15` → whisper spot-check on a clean vocal →
metering shows `transcribe` work unit + `user`/`client` → one existing flow
regression check.

**Thor:** `tools/list` via LiteLLM shows the new tool + schema → YouTube
submit non-blocking returns `job_id` in <5 s → poll to done with all 5 paths
→ `media_fetch` tab.md/lyrics.txt readable locally → `media_pull` signed URL
200 through `siri.choukalos.com` (off-LAN) → job payload shows
`user=chuck, client=pi` → staging-file source works → error paths (bad URL,
`instrument="piano"` → clean "v1 supports guitar only") → regression:
`media_info` + one existing non-blocking job tool.

**End-to-end acceptance:** one real song, end to end from pi, tab presented
to the owner; quality bar = chords/key/BPM/lyrics correct, lead line
"playable with minor fixes". Logged to `docs/thor_validation_log.md`.

## 7. Risks and known limitations

| Risk | Mitigation |
|---|---|
| Lead/accompaniment separation on dense mixes is heuristic | v1 = draft positioning; ship raw MIDI + `analysis.json` for verification; per-section confidence in output |
| Whisper on dense mixes | `stems=true` (demucs vocal stem) option |
| Heavy distortion / pitch-shifted guitar smears note events | basic-pitch is best-effort there; warnings section in `tab.md` |
| YouTube ToS | yt-dlp is the established homelab pattern (`mcp_vision`); audio-only, personal use |
| Copyright | Personal transcription use; outputs are private (no public route beyond owner's signed URLs) |
| New deps/VRAM on Matrix | Budgeted in handoff §6 (~3 GB whisper, ~4 GB demucs optional, one-time model downloads ~4 GB disk) |
| LLM polish hallucinates | Tab lines are deterministic + diff-verified; LLM failure → deterministic output ships (never blocks the job) |
| Long job vs 30 s client abort | Existing submit-and-poll pattern (`non_blocking` + `media_job_result`) |

## 8. Rollout checklist

- [x] **1. Matrix:** implement `/transcribe` per handoff doc — DONE 2026-10-31
      (GPU-host AI). Verified live: happy path, schema, key/BPM vs ground
      truth, determinism, error paths, metering all green. Chord detection
      (QA item 5) was failing at first verification and is **FIXED + verified
      2026-10-31 (part 2)** (synthetic ground truth exact; SHA cross-check
      green). The reported key/BPM "drift" on Riptide was a **false alarm** —
      the recording is actually in C# major @ ~102 BPM (verified by raw-audio
      Goertzel measurement + external source; the standard D-major guitar tab
      is a capo'd/different arrangement). **Still open: lyrics sparseness**
      (Riptide 4 lines / ~30; raw-ASR quality on real vocals). See
      `docs/thor_validation_log.md` 2026-10-31 entries (both parts).
- [x] **2. Thor:** `mcp_media` changes — DONE 2026-10-31 (Dockerfile +yt-dlp,
      `media_pipeline_client.transcribe()` + `finalize_job` transcribe branch,
      `media_transcribe_song` tool with 4-way source resolution).
      Verified: **27/27 mock-pipeline checks** (`mcp/servers/media/test_transcribe.py`
      — local stdlib stub implementing /health, /upload, /download,
      /transcribe, /jobs, /files; **live pipeline untouched** — safe while
      Matrix is busy) + tool schema (23 tools on `mcp_media`). Production
      container rebuild + restart deliberately held until Matrix's QA is
      green (no LiteLLM config change needed — auto-discovery).
- [x] **3. Thor:** client-side QA green — 27/27 mock checks + **live-pipeline
      smoke done 2026-10-31** (Riptide via LiteLLM `/mcp-rest/tools/call`:
      submit → poll → fetch → pull, identity `user=chuck`, signed URL 200
      through `siri.choukalos.com`).
- [x] **4. Skill:** `agents-skills/song-transcribe/SKILL.md` (done 2026-10-31)
- [x] **5. Docs:** `media-mcp-handoff.md` §4 table (done 2026-10-31),
      `thor_validation_log.md` entry (done 2026-10-31), `README.md` +
      `thor_ai_inventory.md` (done 2026-10-31 — inventory history line now
      carries the live 87-tool count; the doc's "71 tools" figure had been
      stale since 2026-09-20).
- [x] **6. E2E:** real song from pi — done 2026-10-31 (Riptide; full chain
      green). Re-verified 2026-10-31 (part 2) after the chord fix: tab data
      (key/chords/notes/structure) fully verified correct. Owner review:
      PENDING (tab is now review-worthy; lyrics still sparse — see item 1).
- [x] **7. Metering:** confirmed 2026-10-31 — `media_work_units_total
      {kind="transcribe"}` (80.0 = 40 s × 2 runs) + `media_cost_usd_total
      {stage="transcribe"}` at exactly the $3.1e-5/s placeholder rate, user/
      client stamped. Dashboard exposure: **CONFIRMED 2026-10-31 (part 2)** —
      series present in VictoriaMetrics via the existing `media-pipeline-matrix`
      Prometheus scrape; the AI Work & Spend dashboard queries
      `media_cost_usd_total`/`media_work_units_total` directly, so transcribe
      shows up with no new plumbing. Rate calibration: PENDING (needs
      real-song runtime data).