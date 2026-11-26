# Plan: Expose Gemma 4 31B (GPU 1 copywriter) via Thor LiteLLM

> Created: 2026-11-25
> Status: **APPLIED 2026-11-25 (zero-downtime runtime path)** — entry +
> fallback live via `POST /model/new` (no proxy restart; model_id
> f62c1c71-0574-4e30-9caa-ba172be8ea48); `litellm/config.yml` updated for
> persistence. Verification 1–2 PASS (serving confirmed; see "Observed
> behavior" below), 3 partial (loaded, but VRAM-degraded while the C-production
> render held GPU 1 — full-footprint check deferred), 4–7 deferred (need a quiet
> GPU 1 window and/or the Matrix console); Matrix-side doc updates
> (contract v1.2, profile comment, Matrix TODO.md) pending the same.
> **2026-11-26 verification session: check 5 PASS** (live fallback fired —
> dead-upstream request returned 200 from qwen38-27b in 0.5 s, no 5xx to the
> caller) and surfaced a real bug: the per-entry `fallbacks:` idiom (used by
> this entry AND `matrix-coder`) bypasses the router and 500s on group
> aliases. Fallbacks moved to router-level `router_settings.fallbacks`
> (config applied + proxy recreated 2026-11-26 15:53 UTC with
> `--force-recreate`; verified live). Check 3 partially confirmed from Thor
> (loaded + VRAM slice via `/api/ps`); 4/6/7 still deferred (quiet GPU 1
> window + Matrix console). See "Verification session 2026-11-26" below.
> Option A from the 2026-11-25 GPU-1 sidecar discussion: Ollama tenant on GPU 1,
> exposed through Thor LiteLLM with a fallback to `matrix-coder`.

## Goal

`gemma4:31b` (the GPU 1 copywriter, already pulled + validated) becomes a selectable
model in Thor LiteLLM as **`matrix-copywriter`**, with:

- **Automatic VRAM coordination** (already live on Matrix — no work):
  media-job headroom guard evicts it (`server.py _ensure_vram_headroom`),
  `OLLAMA_KEEP_ALIVE=5m` idle-unload, on-demand load (~10–46 s) on first request.
- **Graceful degradation**: if the model can't load because media owns GPU 1,
  the request falls back to `matrix-coder` (72 GB daily driver) instead of erroring.
- **Manual override** unchanged: `model-manager gpu1 swap {media|copywriter}`.

## What already exists (do NOT redo)

| Piece | Where | State |
|---|---|---|
| `gemma4:31b` weights | Matrix Ollama (GPU 1, `device_ids: ['1']`) | Pulled, validated (46 s load, ~30 tok/s, 22.1 GB @ 64K) |
| Idle unload | `OLLAMA_KEEP_ALIVE=5m` in `compose/gemma4-moe.yml` | Live |
| Evict-on-media | `media-pipeline/server.py` VRAM headroom guard | Live (Phase 6) |
| Manual swap | `model-manager gpu1 swap {media\|copywriter}` | Live |
| Ollama endpoint for Thor | `http://matrix:11434` (contract §2) | Live |

The ONLY missing piece is the Thor LiteLLM entry (+ fallback). The
`ollama-copywriter-gpu1` profile has carried the note "Thor entry" since Phase 3 —
this plan closes it.

---

## Step 1 — Thor: add the model entry

In Thor's `litellm/config.yml` (the file that already defines `matrix-coder`,
`matrix-coder-fast`, `embeddings`, `homelab-embedding-v1`; mounted at
`/app/config.yaml` in the `litellm-proxy` container), add to `model_list`:

```yaml
  - model_name: matrix-copywriter
    model_info:
      mode: chat
      input_cost_per_token: 0.0000001
      output_cost_per_token: 0.0000001
    litellm_params:
      model: ollama/gemma4:31b
      api_base: http://matrix:11434
      api_key: "unused"
      timeout: 180        # first request after idle-unload triggers a ~46 s load
      # No num_retries: global router num_retries is 0 → the fallback fires on
      # the FIRST failure (a load that can't fit in VRAM fails fast instead of
      # burning a ~46 s doomed retry).
      fallbacks:
        - {model: matrix-coder}
```

Follows the existing local-model pattern (the `embeddings` entries:
`ollama/<model>` → `http://matrix:11434`) and the file's existing per-entry
fallback idiom (`matrix-coder` carries `fallbacks: [{model: studio-gemma4-26b}]`).
NOTE: `matrix-gemma4-moe` does NOT exist in the config (never did — the original
"mirror the matrix-gemma4-moe entry" was stale).

## Step 2 — Thor: the fallback

**SUPERSEDED 2026-11-26**: the per-entry `fallbacks:` idiom below is broken —
see "Verification session 2026-11-26". The live fallback is router-level:
`router_settings.fallbacks` in `litellm/config.yml` (matrix-copywriter →
matrix-coder; matrix-coder → studio-inkling-mini), applied at startup via
`Router(**router_settings)`; runtime equivalent `POST /fallback`.

---

The fallback was originally the per-entry `fallbacks:` above (the config file's
own idiom), NOT a new `litellm_settings.model_group_fallbacks` block —
`litellm_settings`
already exists (prometheus callbacks) and the file's convention is per-entry
`fallbacks:`.

Semantics: if `matrix-copywriter` fails (model can't load — GPU 1 held by media,
or Ollama down), LiteLLM retries the request on `matrix-coder`. The caller gets
an answer from the 72 GB daily driver, not an error. With the global
`num_retries: 0` the fallback fires on the first failure — do NOT add
`num_retries: 1` (that would retry a doomed ~46 s load before falling back).

## Step 3 — Thor: apply (zero-downtime — NO restart)

The proxy (litellm v1.104.0) supports runtime config, so this ships without
restarting `litellm-proxy` (a session-carrying service — gated per
docs/operations/approval-gates.md):

```bash
# 1. Add the model group in-memory (same shape as the config entry):
curl -s -X POST http://localhost:4000/model/new \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" -H 'Content-Type: application/json' \
  -d '{"model_name":"matrix-copywriter","litellm_params":{"model":"ollama/gemma4:31b","api_base":"http://matrix:11434","api_key":"unused","timeout":180,"fallbacks":[{"model":"matrix-coder"}]},"model_info":{"mode":"chat","input_cost_per_token":0.0000001,"output_cost_per_token":0.0000001}}'
# 2. Confirm it came up:
curl -s http://localhost:4000/model/info | python3 -m json.tool | grep -A3 copywriter
```

Runtime state is in-memory (lost on the next proxy restart) — that is why the
config file is updated in the SAME pass: after any future restart the file
supplies the identical entry. (The v1.104.0 `POST /fallback` endpoint also
exists and is the runtime equivalent; the per-entry `fallbacks` in
`/model/new` keeps one source of truth.)

## Step 4 — Verification checklist

Run 1–2 from Thor; 3–7 need the Matrix console (Thor has no ssh to Matrix —
`chuck@192.168.4.55` key-auth denied 2026-11-25). Thor-side proxy for the
Ollama state: `curl http://192.168.4.55:11434/api/ps` (VRAM + processor; the
GPU *index* is not visible from Thor — the profile pins `device_ids: ['1']`).

- [x] **1. Listed**: `matrix-copywriter` appears in `/model/info` (done 2026-11-25,
      zero-downtime runtime apply).
- [x] **2. Serves**: chat completion returns a coherent reply (done 2026-11-25;
      first call = the on-demand load).
- [x] **3. Loaded on GPU 1** (Matrix): `docker exec ollama ollama ps` (gemma4:31b
      listed, PROCESSOR 100% GPU) + `nvidia-smi -i 1 --query-gpu=memory.used
      --format=csv` (~22 GB). — **PARTIAL 2026-11-26 (from Thor)**: loaded state +
      VRAM slice confirmed via `http://192.168.4.55:11434/api/ps` (gemma4:31b
      listed, 642→714→1353 MB slice across the render window — degraded while
      media/ComfyUI hold GPU 1). Full ~22 GB footprint + GPU index via
      `nvidia-smi -i 1` still need the Matrix console.
- [ ] **4. Idle unload** (Matrix): wait 5 min with no requests → `ollama ps` empty,
      `nvidia-smi -i 1` back to media-pipeline baseline. (Observable from Thor via
      `http://192.168.4.55:11434/api/ps`.)
- [x] **5. Fallback**: with GPU 1 held (ComfyUI hot at ~18 GB, or a media job
      running), request `matrix-copywriter` from Thor → reply comes back from
      `qwen38-27b` (check LiteLLM logs for the fallback event; the response content
      is the tell — 31B vs 27B style). No 5xx to the caller.
      (Wiring verified 2026-11-25 via the entry's `fallbacks`; live test deferred
      until the C-production media task finishes — needs GPU 1 held + model
      unloaded.) — **PASS 2026-11-26 (router-level mechanism)**: 5a — degraded
      live request 200 in ~14.1 s (model loaded in a small VRAM slice, served
      slowly — the expected degraded-mode behavior); 5b — throwaway entry
      `copywriter-fb-test` pointed at a dead upstream (`matrix:11435`) with a
      router-level fallback to `matrix-coder`: request returned **200 in ~0.5 s
      served by `qwen38-27b`**, zero 5xx. The per-entry idiom on the SAME
      dead-upstream shape returned **500 in 10 s** ("LLM Provider NOT provided")
      — see the findings below. Test entry + its fallback deleted after the test.
- [ ] **6. Evict-on-media**: load the copywriter (step 2), then queue a small media
      job (e.g., TTS) → pipeline log shows the headroom-guard `ollama stop`, job
      completes, no OOM. (Passive variant: watch `/api/ps` while a media job runs —
      the guard evicts Ollama at job start. Do NOT queue an extra job while the
      production render is running.)
- [ ] **7. Manual swap still works**: `model-manager gpu1 swap media` then
      `model-manager gpu1 swap copywriter` — clean both ways. (Matrix-side;
      deferred — no Thor→Matrix ssh.)

## Step 5 — Doc updates

**Thor side (this repo) — DONE 2026-11-25:**

- `litellm/config.yml` — entry + per-entry `fallbacks` (committed `1a64ae0`)
- `docs/thor_model_alias_registry.md` — live-aliases row (6-model set,
  verified via `GET /v1/models`)
- This plan doc — status APPLIED + observed-behavior section

**Matrix side — PENDING (needs the Matrix console; Thor has no ssh to
Matrix, `chuck@192.168.4.55` key-auth denied 2026-11-25):**

1. **`docs/matrix_thor_contract.md` → v1.2**: add the row to §3 alias table:
   ```
   | `matrix-copywriter` | `ollama/gemma4:31b` → `http://matrix:11434` | Ollama port 11434 (GPU 1) | `daily`, `llms` — XOR-tenant with media-gpu1; falls back to `matrix-coder` when GPU 1 is media-held |
   ```
   and a note under the alias table: `matrix-copywriter` has per-entry
   `fallbacks: [matrix-coder]` (2026-11-25).
2. **`models/profiles/ollama-copywriter-gpu1.yaml`**: change
   `alias: matrix-copywriter  # NEW LiteLLM alias (Phase 3/4 adds the Thor entry)`
   → `alias: matrix-copywriter  # LIVE in Thor LiteLLM since 2026-11-25 (fallback → matrix-coder)`.
3. **`TODO.md` (Matrix)**: close the "Thor entry" checkbox.

## Observed behavior (applied 2026-11-25, render running)

Applied while board task 13 (PWV2 F2-C2-PROD, the C-production render) was
running on Matrix — deliberately, to prove coexistence. Findings:

- **Zero-downtime apply worked**: `POST /model/new` returned the entry (in-memory,
  `db_model: true`); `/model/info` lists `matrix-copywriter` with
  `model: ollama/gemma4:31b`, `api_base: http://matrix:11434`, `timeout: 180`,
  `fallbacks: [{model: matrix-coder}]`. No proxy restart, no interruption of
  task 13 (it kept committing through the whole window).
- **Serving works, degraded while the render holds GPU 1**: first request took
  2 m 32 s (on-demand load + CPU inference) and returned a coherent reply;
  second took 20.6 s ("GPU1 OK", 48 completion tokens). Direct Ollama
  (`/api/generate` on 192.168.4.55:11434) measured **2.5 tok/s** — the model
  was CPU-offloaded because the render held most of GPU 1's VRAM.
  `/api/ps` showed `gemma4:31b` at only **642 → 714 MB VRAM** (Ollama moved
  more layers to the GPU as the render's VRAM fluctuated between shots), the
  rest in CPU RAM.
- **The fallback did NOT fire — and that's the nuance**: when a copywriter
  request arrives mid-render, Ollama loads *partially* (GPU slice + CPU) and
  serves slowly instead of failing. The fallback to `matrix-coder` is for hard
  failures (Ollama down, or zero loadable VRAM — e.g. hot ComfyUI), not for
  degraded loads. Expect ~2.5 tok/s answers while a render is running; ~30
  tok/s when GPU 1 is free (the Matrix-side verified number).
- **Idle-unload (check 4) not observable during the render**: the keep_alive
  expiry kept getting reset (~00:16 and ~00:21 UTC) as Ollama's layer
  scheduling moved VRAM between shots — the model persisted through the
  render instead of unloading. Re-check after task 13 finishes.
- **No evict-on-media event observed (check 6)**: shot boundaries during the
  production task did NOT evict the loaded copywriter — the headroom guard
  runs at media *job* start, and the production task is one long-running job
  (the 714 MB GPU slice coexisted with the render without issue; task 13
  stayed healthy, usage 9.9 → 10.0, commits continuing). True check-6 test
  needs a NEW media job starting while the model is loaded.
- **No interference with the render**: task 13 stayed `running` with no
  failures throughout the test window.

**Deferred checks (quiet window / Matrix console):** 3 (full ~22 GB footprint +
GPU index via `nvidia-smi -i 1` — loaded state confirmed from Thor 2026-11-26),
4 (idle unload), 6 (new-job eviction), 7 (`model-manager gpu1 swap`).
Check 5 (live fallback) completed 2026-11-26 — see below.

---

## Verification session 2026-11-26 (fallback mechanism + config cutover)

Ran after the C-production render (board task 13) finished, using the Thor-side
proxy for Ollama state (`http://192.168.4.55:11434/api/ps`).

### Finding 1 — the per-entry `fallbacks:` idiom is broken (the big one)

The per-entry `litellm_params.fallbacks` (used by BOTH `matrix-copywriter` and
`matrix-coder` since 2026-11-19/25) resolves fallbacks via a direct
`litellm.acompletion()` call that **bypasses the router** — so a fallback target
that is a model-group alias (`matrix-coder`, `studio-inkling-mini`) fails with
"LLM Provider NOT provided" and the caller gets a **500**. Proved live with a
throwaway entry (`copywriter-fb-test`, dead upstream `matrix:11435`, timeout 10,
per-entry fallback to `matrix-coder`): request → **500 in 10 s**. The
router-level fallback (`POST /fallback`, persisted as `router_settings.fallbacks`)
on the same dead-upstream shape → **200 in ~0.5 s from `qwen38-27b`**, no 5xx.

**Fix applied**: per-entry `fallbacks:` removed from both entries; the two
fallbacks moved to `router_settings.fallbacks` in `litellm/config.yml` (applied
+ proxy recreated 2026-11-26 15:53 UTC with `docker compose up -d
--force-recreate` — plain `up -d` does NOT reload a changed mounted config file).
Verified post-cutover: container healthy, all 6 models, `GET /fallback` shows
both fallbacks, copywriter entry has no per-entry fallbacks (proof the new file
loaded), live copywriter request 200 with correct content.

### Finding 2 — LiteLLM model reconciliation clobbers runtime fallback state

Deleting model entries (`POST /model/delete`) triggers model reconciliation,
which rebuilds the router from the file config and **overwrote the DB
`router_settings` row** (the `POST /fallback` persistence target) with the file's
empty fallbacks — `GET /fallback` went from "configured" to "No general
fallbacks configured" immediately after the deletes. The live fallbacks had to be
re-POSTed. Consequence: runtime `POST /fallback` state is fragile across model
add/delete operations — the config file is the durable source of truth, and any
model-list surgery on this proxy should be followed by a `GET /fallback` check.
(Also removed during this session: the stale 2026-11-25 DB copywriter entry
`f62c1c71-…` that shadowed the file entry with the same broken per-entry idiom.)

### Finding 3 — reasoning-model token budget artifact (not a bug)

`max_tokens: 20` on `matrix-copywriter` → HTTP 200 with **empty content** (all
completion tokens consumed by reasoning; raw Ollama shows the same: 50 tokens
evaluated, empty content, `done_reason: length`). With `max_tokens: 100` the
same prompt returns the correct reply ("COPYWRITER-OK"). Confirms the existing
"Reasoning model" caveat: clients need a generous output budget on this alias.

### Checks closed this session

- **5 (fallback): PASS** — 5a degraded live request 200 (~14.1 s); 5b dead-upstream
  twin → router fallback fired, 200 from `qwen38-27b` in ~0.5 s, no 5xx.
- **3 (loaded on GPU 1): PARTIAL** — loaded + VRAM slice confirmed from Thor via
  `/api/ps`; full footprint + GPU index still need the Matrix console.
- **4/6/7: still deferred** — idle unload (the keep_alive expiry kept resetting
  while Ollama rescheduled VRAM), evict-on-media (needs a NEW media job starting
  while the model is loaded), manual swap (Matrix console; Thor→Matrix ssh denied).

---

## Caveats / known behavior

- **Reasoning model**: gemma4:31b is a reasoning model — it needs a generous output
  budget (profile note). Clients that cap `max_tokens` low will see truncated
  reasoning; if that bites, raise the cap per-client or set a sensible
  `max_tokens` default in the `litellm_params` entry.
- **First-request latency**: ~10–46 s cold load after idle-unload. Thor-side clients
  with aggressive timeouts (pi/codex) should tolerate ≥ 60 s on this model, or
  accept that the fallback may fire on a slow load.
- **Hard XOR with hot ComfyUI**: ComfyUI resident (~18 GB) + 22 GB model > 24 GB —
  the model simply cannot load while ComfyUI is hot. That's by design; the fallback
  makes it painless. The headroom guard covers the GPU *workers* (music/tts/
  transcribe); it does not (and should not) kill ComfyUI mid-job.
- **No daemon added**: per the model-manager design rule ("NOT an automation
  daemon"), all automation here is the existing guard + keep_alive + on-demand
  load. `gpu1 swap` remains the manual override.
- **Swap-in later**: the entry is model-agnostic in shape — pointing
  `matrix-copywriter` at a different Ollama model (e.g., `inkling2-mini` GGUF) is a
  one-line change on Thor when Experiment 9's model graduates.
