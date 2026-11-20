// @options: {"timeout_ms": 10800000}
// ============================================================================
// media-film chunk — submit pending work + poll to completion.
//
// One codemode call = one chunk: up to CFG.max_completions job completions
// (spec: 4-8 completions, ~45-90 min wall clock max). When the budget trips,
// the chunk returns and pi starts a fresh chunk from the on-disk state.
//
// R1: state is written (via tools.bash — the codemode sandbox has no
//     filesystem) immediately after EVERY submit and EVERY completion.
// R2: every MCP call goes through mcall (4 attempts).
// R5: at most CFG.queue_limit own in-flight submits; on 503 stop submitting
//     and keep polling.
// C8:  assemble phase runs a media_info preflight on every shot + audio
//      path and aborts with the precise missing list.
// C11: audio_jobs keys are the single canonical family (tts_<shot> /
//      sfx_<name> / music_cue_<x>) — written once at submit, updated in place.
// C12: prompt fields go through rawPrompt (raw text only — never
//      JSON-encoded values into MCP prompt fields).
//
// pi adapts CFG (state path, client tag, phase, model, prompts in state) and
// runs this whole script in codemode.
// ============================================================================

const CFG = {
  state: "/Users/chuck/Code/media-film/PROJECT/state.json", // <- project state file
  client: "PROJECT",          // <- client tag prefix; jobs tagged <client>/<unit>
  phase: "i2v",               // <- "kf" | "i2v" | "audio" | "assemble"
  model: null,                // <- e.g. "wan14b" (production) or "ltxv2b" (dry run); null = state.model
  max_completions: 8,         // stop after this many completions this chunk
  max_passes: 40,             // safety: stop after this many poll passes
  budget_ms: 90 * 60 * 1000,  // hard timebox (spec: ~45-90 min max)
  poll_wait: 20,              // media_job_result wait_seconds (max 25)
  queue_limit: 5,             // max own in-flight submits (queue: 1 running + 5 queued, shared)
};

// Tool-name prefixes — pi's codemode MCP layer names gateway tools
// differently per pi/host version (verified 2026-11-19):
//   thor pi 1.3.0: "mcp__litellm__mcp_media_" (underscore form works; dash fails)
//   Mac (film run 2026-11-17): "mcp_media-" (dash form worked; underscore failed)
// Raw gateway names are dash-form (mcp_media-media_list_jobs per /v1/mcp/tools);
// pi re-names them per its codemode layer. Resolve once with a cheap call
// BEFORE any other MCP call; both forms are tried.
let M = null, V = null;
const ensurePrefixes = async () => {
  if (M) return;
  const forms = [
    ["mcp__litellm__mcp_media_", "mcp__litellm__mcp_vision_"],
    ["mcp_media-", "mcp_vision-"],
  ];
  for (const [m, v] of forms) {
    try { await tools[m + "media_list_jobs"]({ status: "running", limit: 1 }); M = m; V = v; return; } catch (_) {}
  }
  throw new Error("media tool prefix unresolved — underscore and dash forms both failed (check MCP server registration)");
};

// ---- R2: retried MCP call (4 attempts) ------------------------------------
// `name` = FULL tool name (resolved prefix + tool: M + "media_*" / V + "vision_*").
// EVERY MCP call — media, vision, skills — goes through this wrapper. A single
// un-retried 60s gateway timeout kills the whole chunk (verified in the
// 2026-11-04 dry run: an un-wrapped vision call died the QC script).
const mcall = async (name, args, tries = 4) => {
  let last;
  for (let i = 0; i < tries; i++) {
    try { return JSON.parse((await tools[name](args)).content[0].text); }
    catch (e) { last = e; }
    // Backoff WITHOUT timers — the codemode QuickJS sandbox has no setTimeout.
    // A cheap blocking call stands in (spec: media_job_result on a known-done
    // job with wait_seconds 25; media_list_jobs is the always-available variant).
    try { await tools[M + "media_list_jobs"]({ status: "running", limit: 1 }); } catch (_) {}
  }
  throw last;
};
const poll = (jid) => mcall(M + "media_job_result", { job_id: jid, wait_seconds: CFG.poll_wait });
await ensurePrefixes(); // resolve tool-name prefixes before any MCP call (see note above)

// ---- R1: state file (written immediately after every submit) --------------
const loadState = async () =>
  JSON.parse((await tools.bash({ command: `cat '${CFG.state}'` })).output.trim());
const saveState = async (st) => {
  const d = "MFEOF" + Math.random().toString(36).slice(2); // unique delimiter
  await tools.bash({
    command: `mkdir -p "$(dirname '${CFG.state}')" && cat > '${CFG.state}' << '${d}'\n` +
             JSON.stringify(st, null, 2) + "\n" + d,
  });
};

// ---- C12: raw-text prompt getter -------------------------------------------
// Prompt fields are plain strings in state. Never JSON.stringify a prompt
// into state and never paste JSON-encoded values into MCP prompt fields
// (bash submits: jq -n --arg). Fail fast on double-encoded prompts.
const rawPrompt = (s, what) => {
  if (typeof s !== "string") throw new Error(what + " is not a raw string: " + JSON.stringify(s).slice(0, 120));
  if (s.length > 1 && s.startsWith('"') && s.endsWith('"')) throw new Error(what + " looks JSON-encoded — store raw text in state (C12)");
  return s;
};

// ---- phase plumbing --------------------------------------------------------
const st = await loadState();
const PKEY = { kf: "kf", i2v: "i2v", audio: "audio_jobs", assemble: null }[CFG.phase];

// units = the work items this phase drives (shot ids / audio unit names)
// C11: audio unit names are the single canonical key family —
// tts_<shot> / sfx_<name> / music_cue_<x> (written once at submit, updated
// in place; no parallel key families).
const units =
  CFG.phase === "kf"       ? (st.kf_pending || []).map((id) => ({ id })) :
  CFG.phase === "i2v"      ? (st.i2v_pending || []).map((id) => ({ id })) :
  CFG.phase === "audio"    ? Object.keys(st.audio_jobs || {}).filter((id) => st.audio_jobs[id]?.status !== "done").map((id) => ({ id })) :
  CFG.phase === "assemble" ? [{ id: "assemble" }] :
  (() => { throw new Error("unknown phase: " + CFG.phase); })();

const jobOf = (u) =>
  CFG.phase === "kf"       ? (st.kf?.[u.id]?.job_id || st.shots?.[u.id]?.kf_job) :
  CFG.phase === "i2v"      ? (st.i2v?.[u.id]?.job_id || st.shots?.[u.id]?.i2v_job) :
  CFG.phase === "audio"    ? st.audio_jobs?.[u.id]?.job_id :
                             st.assemble?.job_id;

// C11: first done audio path in the canonical family (for assemble inputs).
const audioDonePath = (prefix) => {
  for (const [k, v] of Object.entries(st.audio_jobs || {}))
    if (k.startsWith(prefix) && v && v.status === "done" && v.path) return v.path;
  return "";
};

const SUBMIT = {
  kf: (u) => mcall(M + "media_generate_image", {
    prompt: rawPrompt(st.shots[u.id].kf_prompt, "kf_prompt " + u.id), width: 1280, height: 720,
    non_blocking: true, client: CFG.client + "/" + u.id,
  }),
  i2v: (u) => mcall(M + "media_generate_shot", {
    // C3: the card's i2v_prompt already carries the per-character identity
    // re-anchor + gentle motion + 1978 TV look — submit it verbatim.
    // C12: raw text only (never re-encode); preflight diff = exact match
    // with the card.
    keyframe: st.shots[u.id].kf_path, prompt: rawPrompt(st.shots[u.id].i2v_prompt, "i2v_prompt " + u.id),
    model: CFG.model || st.model || "wan14b", non_blocking: true,
    client: CFG.client + "/" + u.id,
  }),
  audio: (u) => {
    // C11: canonical audio keys — tts_<shot> / sfx_<name> / music_cue_<x>.
    if (u.id.startsWith("music_cue_")) {
      const c = (st.music_cues || {})[u.id.slice(11)] || {};
      return mcall(M + "media_generate_music", {
        prompt: rawPrompt(c.prompt || st.music_prompt, "music prompt " + u.id),
        duration: c.duration || st.music_duration || 60,
        non_blocking: true, client: CFG.client + "/" + u.id,
      });
    }
    if (u.id.startsWith("sfx_")) {
      const c = (st.sfx_cues || {})[u.id.slice(4)] || {};
      return mcall(M + "media_sfx", {
        video: c.video, description: rawPrompt(c.description, "sfx description " + u.id),
        duration: c.duration || 8.0,
        non_blocking: true, client: CFG.client + "/" + u.id,
      });
    }
    if (u.id.startsWith("tts_")) {
      const sid = u.id.slice(4); // tts_S1 -> S1
      return mcall(M + "media_text_to_speech", {
        text: rawPrompt(st.shots[sid]?.vo_text || st.vo_text, "vo_text " + u.id),
        voice: st.voice || "trailer",
        non_blocking: true, client: CFG.client + "/" + u.id,
      });
    }
    throw new Error("audio key '" + u.id + "' is not canonical (tts_<shot> / sfx_<name> / music_cue_<x>) — C11; run tools/validate_state.py");
  },
  assemble: () => mcall(M + "media_assemble", {
    // C11: derive final audio inputs from the canonical audio_jobs family
    // (st.audio holds the combined uploaded VO track when the multi-segment
    // mix pattern was used).
    shots: st.assemble.shots,
    vo: st.audio?.vo || audioDonePath("tts_"),
    music: st.audio?.music || audioDonePath("music_cue_"),
    sfx: st.audio?.sfx || "",
    text_overlays: st.assemble.text_overlays || null,
    non_blocking: true, client: CFG.client + "/assemble",
  }),
};

const recordSubmit = (u, jid) => {
  if (CFG.phase === "assemble") { st.assemble.job_id = jid; return; }
  if (!st[PKEY]) st[PKEY] = {};
  st[PKEY][u.id] = { job_id: jid, status: "submitted" };
  if (CFG.phase === "i2v") st.shots[u.id].i2v_job = jid;
  if (CFG.phase === "kf") st.shots[u.id].kf_job = jid;
};
const recordDone = (u, r) => {
  const jid = jobOf(u);
  const path = r.path || (r.output ? r.output.image || r.output.video || r.output.audio : null);
  if (CFG.phase === "assemble") { st.assemble.path = path; return; }
  st[PKEY][u.id] = { job_id: jid, path, status: "done" };
  if (CFG.phase === "kf") st.shots[u.id].kf_path = path;
  if (CFG.phase === "i2v") { st.shots[u.id].i2v_job = jid; st.shots[u.id].i2v_path = path; }
  // C11: the audio path lives in the single canonical audio_jobs record
  // above — no parallel key family (stale second families over-report
  // pending audio).
  st[CFG.phase + "_pending"] = (st[CFG.phase + "_pending"] || []).filter((x) => x !== u.id);
};
const recordError = (u, r) => {
  if (CFG.phase === "assemble") { st.assemble.error = r.error; return; }
  st[PKEY][u.id] = { ...(st[PKEY]?.[u.id] || {}), status: "error", error: r.error };
  // stays in <phase>_pending — pi decides: fix prompt/seed and resubmit.
};

// ---- C8: assemble preflight — media_info every shot + audio path ----------
// A 44.5 s-short cut must never reach the render queue. One sync media_info
// per path is cheap next to a 4.5 h upscale render. Abort with the precise
// missing list.
const assemblePreflight = async (st) => {
  const paths = [
    ...(st.assemble?.shots || []).map((s) => (typeof s === "string" ? s : s.path)).filter(Boolean),
    st.audio?.vo, st.audio?.music,
    ...(Array.isArray(st.audio?.sfx) ? st.audio.sfx : (st.audio?.sfx ? [st.audio.sfx] : []))
      .map((s) => (typeof s === "string" ? s : s.path)).filter(Boolean),
  ];
  const missing = [];
  for (const p of paths) {
    try {
      const r = await mcall(M + "media_info", { path: p });
      if (!r || r.status === "error" || (typeof r.duration_s !== "number" && !r.path))
        missing.push(p + " (media_info: " + JSON.stringify(r).slice(0, 80) + ")");
    } catch (e) { missing.push(p + " (" + String(e).slice(0, 80) + ")"); }
  }
  if (missing.length) {
    await saveState(st); // R1: persist before aborting
    throw new Error("assemble preflight (C8) — " + missing.length + " path(s) failed media_info:\n  " + missing.join("\n  "));
  }
  return paths.length;
};

// ---------------------------------------------------------------- main loop
const t0 = Date.now();
let completions = 0, passes = 0;
const doneIds = new Set();
const log = [];

while (completions < CFG.max_completions && passes < CFG.max_passes &&
       Date.now() - t0 < CFG.budget_ms) {
  passes++;
  let progress = false;

  // 1) poll units that already have a job
  for (const u of units) {
    if (doneIds.has(u.id)) continue;
    const jid = jobOf(u);
    if (!jid) continue; // no job yet — submit below
    const r = await poll(jid);
    if (r.status === "running") continue;
    if (r.status === "error" || r.status === "timeout") {
      recordError(u, r); await saveState(st);
      doneIds.add(u.id); completions++; progress = true;
      log.push(u.id + ": " + r.status + " — " + (r.error || ""));
      continue;
    }
    recordDone(u, r); await saveState(st); // R1: persist immediately
    doneIds.add(u.id); completions++; progress = true;
    log.push(u.id + ": done -> " + (r.path || JSON.stringify(r).slice(0, 120)));
  }

  if (doneIds.size === units.length) break;

  // 2) submit units without a job, respecting queue capacity (R5)
  let inflight = 0;
  try { inflight = (await mcall(M + "media_list_jobs", { status: "running", limit: 200 })).count; }
  catch (_) { inflight = CFG.queue_limit; } // visibility down: be conservative
  for (const u of units) {
    if (doneIds.has(u.id) || jobOf(u)) continue;
    if (inflight >= CFG.queue_limit) { log.push("queue full (" + inflight + " in-flight) — polling"); break; }
    let r;
    try {
      if (CFG.phase === "assemble") {
        log.push("C8 preflight: media_info on all shot + audio paths");
        await assemblePreflight(st); // aborts with the precise missing list
      }
      r = await SUBMIT[CFG.phase](u);
    }
    catch (e) {
      const msg = String(e && e.message ? e.message : e);
      if (msg.includes("503")) { log.push(u.id + ": 503 queue full — stop submitting, keep polling"); break; }
      throw e;
    }
    // 503 can also arrive as an error body (not a transport exception)
    if (r && r.status === "error" && String(r.error || "").includes("503")) {
      log.push(u.id + ": 503 queue full — stop submitting, keep polling"); break;
    }
    const jid = r.job_id;
    recordSubmit(u, jid); await saveState(st); // R1: persist IMMEDIATELY after submit
    inflight++;
    log.push(u.id + ": submitted " + jid);
  }

  if (!progress && doneIds.size === units.length) break;
}

const pending = units.filter((u) => !doneIds.has(u.id)).map((u) => u.id);
return {
  phase: CFG.phase,
  state: CFG.state,
  log,
  done: [...doneIds],
  pending,
  budget_left_ms: CFG.budget_ms - (Date.now() - t0),
  next: pending.length === 0
    ? "phase complete — move to next phase"
    : "run next chunk (same template); state is on disk",
};