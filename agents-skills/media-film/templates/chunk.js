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

const M = "mcp__litellm__mcp_media_";

// ---- R2: retried MCP call (4 attempts) ------------------------------------
// `name` = FULL tool name (mcp__litellm__mcp_media_* / mcp__litellm__mcp_vision_*).
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

// ---- phase plumbing --------------------------------------------------------
const st = await loadState();
const PKEY = { kf: "kf", i2v: "i2v", audio: "audio_jobs", assemble: null }[CFG.phase];

// units = the work items this phase drives (shot ids / audio unit names)
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

const SUBMIT = {
  kf: (u) => mcall(M + "media_generate_image", {
    prompt: st.shots[u.id].kf_prompt, width: 1280, height: 720,
    non_blocking: true, client: CFG.client + "/" + u.id,
  }),
  i2v: (u) => mcall(M + "media_generate_shot", {
    keyframe: st.shots[u.id].kf_path, prompt: st.shots[u.id].i2v_prompt,
    model: CFG.model || st.model || "wan14b", non_blocking: true,
    client: CFG.client + "/" + u.id,
  }),
  audio: (u) =>
    u.id === "music"
      ? mcall(M + "media_generate_music", {
          prompt: st.music_prompt, duration: st.music_duration || 60,
          non_blocking: true, client: CFG.client + "/music",
        })
      : mcall(M + "media_text_to_speech", {
          text: st.vo_text || st.shots[u.id]?.vo_text, voice: st.voice || "trailer",
          non_blocking: true, client: CFG.client + "/" + u.id,
        }),
  assemble: () => mcall(M + "media_assemble", {
    shots: st.assemble.shots, vo: st.audio?.vo || "", music: st.audio?.music || "",
    sfx: st.audio?.sfx || "", text_overlays: st.assemble.text_overlays || null,
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
  if (CFG.phase === "audio") st.audio[u.id] = path;
  st[CFG.phase + "_pending"] = (st[CFG.phase + "_pending"] || []).filter((x) => x !== u.id);
};
const recordError = (u, r) => {
  if (CFG.phase === "assemble") { st.assemble.error = r.error; return; }
  st[PKEY][u.id] = { ...(st[PKEY]?.[u.id] || {}), status: "error", error: r.error };
  // stays in <phase>_pending — pi decides: fix prompt/seed and resubmit.
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
    try { r = await SUBMIT[CFG.phase](u); }
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