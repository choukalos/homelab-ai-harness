// @options: {"timeout_ms": 3600000}
// ============================================================================
// media-film resume (spec §3.4) — run AFTER any crash, timeout, or session
// reset, BEFORE submitting anything new.
//
//   (a) read the state file
//   (b) re-poll all known job ids (live jobs stay in the registry)
//   (c) ledger sweep: media_list_jobs by client tag — recover job ids that
//       never made it into state (crash between submit and persist)
//   (d) ADOPT ledger jobs, don't resubmit them (orphaned duplicates waste
//       GPU time); resubmit ONLY units with no recoverable job
//   (e) report pending for the next chunk
// ============================================================================

const CFG = {
  state: "/Users/chuck/Code/media-film/PROJECT/state.json", // <- project state file
  client: "PROJECT",          // <- client tag prefix (jobs tagged <client>/<unit>)
  poll_wait: 20,              // media_job_result wait_seconds (max 25)
};

const M = "mcp__litellm__mcp_media_";

// ---- R2: retried MCP call (same wrapper as chunk.js — full tool names) ----
const mcall = async (name, args, tries = 4) => {
  let last;
  for (let i = 0; i < tries; i++) {
    try { return JSON.parse((await tools[name](args)).content[0].text); }
    catch (e) { last = e; }
    try { await tools[M + "media_list_jobs"]({ status: "running", limit: 1 }); } catch (_) {}
  }
  throw last;
};
const poll = (jid) => mcall(M + "media_job_result", { job_id: jid, wait_seconds: CFG.poll_wait });

// ---- R1: state file ---------------------------------------------------------
const loadState = async () =>
  JSON.parse((await tools.bash({ command: `cat '${CFG.state}'` })).output.trim());
const saveState = async (st) => {
  const d = "MFEOF" + Math.random().toString(36).slice(2);
  await tools.bash({
    command: `mkdir -p "$(dirname '${CFG.state}')" && cat > '${CFG.state}' << '${d}'\n` +
             JSON.stringify(st, null, 2) + "\n" + d,
  });
};

const st = await loadState();
const log = [];
const pathOf = (r) => r.path || (r.output ? r.output.image || r.output.video || r.output.audio : null);

// ---- (b) re-poll all known job ids ------------------------------------------
for (const [phase, pkey] of [["kf", "kf"], ["i2v", "i2v"], ["audio", "audio_jobs"]]) {
  const table = st[pkey] || {};
  for (const id of Object.keys(table)) {
    const e = table[id];
    if (!e || !e.job_id || e.status === "done") continue;
    let r;
    try { r = await poll(e.job_id); } catch (err) { log.push(phase + "/" + id + ": poll failed — " + err); continue; }
    if (r.status === "done") {
      const path = pathOf(r);
      table[id] = { ...e, path, status: "done" };
      if (phase === "kf") st.shots[id].kf_path = path;
      if (phase === "i2v") { st.shots[id].i2v_job = e.job_id; st.shots[id].i2v_path = path; }
      if (phase === "audio") st.audio[id] = path;
      st[phase + "_pending"] = (st[phase + "_pending"] || []).filter((x) => x !== id);
      log.push(phase + "/" + id + ": recovered done -> " + path);
    } else if (r.status === "error" || r.status === "timeout") {
      table[id] = { ...e, status: "error", error: r.error };
      log.push(phase + "/" + id + ": " + r.status + " — " + (r.error || ""));
    } else {
      log.push(phase + "/" + id + ": still running (" + e.job_id + ")");
    }
  }
}
if (st.assemble?.job_id && !st.assemble.path) {
  let r;
  try { r = await poll(st.assemble.job_id); } catch (err) { r = { status: "unknown", error: String(err) }; }
  if (r.status === "done") { st.assemble.path = pathOf(r); log.push("assemble: recovered done -> " + st.assemble.path); }
  else log.push("assemble: " + r.status + " (" + st.assemble.job_id + ")");
}
await saveState(st);

// ---- (c) ledger sweep: recover job ids lost from state ----------------------
// The client filter is EXACT match (verified 2026-11-04): jobs are tagged
// <project>/<unit>, so the sweep queries per unit id. N×3 cheap calls —
// resume is a rare operation, that's fine.
// since = project creation (ISO-8601 — the ledger rejects relative values like '2h')
const since = st.created || "2026-01-01T00:00:00Z";
const unitIds = [...new Set([
  ...Object.keys(st.shots || {}),
  ...Object.keys(st.audio_jobs || {}),
  "assemble",
])];
const sweep = [];
for (const unit of unitIds) {
  for (const status of ["running", "done", "error"]) {
    const r = await mcall(M + "media_list_jobs", { client: CFG.client + "/" + unit, status, since, limit: 200 });
    sweep.push(...(r.jobs || []));
    if ((r.jobs || []).length < 200) continue;
    log.push("ledger: " + unit + "/" + status + " sweep hit the 200-job cap — narrow `since` if this project is huge");
  }
}

const known = new Set();
for (const p of ["kf", "i2v", "audio_jobs"])
  for (const id of Object.keys(st[p] || {})) if (st[p][id]?.job_id) known.add(st[p][id].job_id);
if (st.assemble?.job_id) known.add(st.assemble.job_id);

const FLOW2PHASE = {
  images: "kf", images_edit: "kf", shots: "i2v",
  tts: "audio", music: "audio", sfx: "audio", assemble: "assemble",
};
let adopted = 0;
for (const j of sweep) {
  if (known.has(j.job_id)) continue;
  const mtag = String(j.client || "").match(new RegExp("^" + CFG.client + "/([^/]+)$"));
  if (!mtag) { log.push("ledger: " + j.job_id + " (" + j.client + ") — unexpected tag, manual review"); continue; }
  const unit = mtag[1];
  const phase = FLOW2PHASE[j.flow];
  if (!phase) { log.push("ledger: " + j.job_id + " (" + j.flow + "/" + unit + ") — unclaimed flow, manual review"); continue; }
  if (phase === "audio" && !["music", "vo", "sfx"].includes(unit)) {
    log.push("ledger: " + j.job_id + " (audio/" + unit + ") — unknown audio unit, manual review"); continue;
  }
  // (d) ADOPT — this job belongs to the unit; do NOT resubmit.
  const path = j.status === "done" ? pathOf(j) : null;
  if (phase === "assemble") {
    st.assemble.job_id = j.job_id;
    if (j.status === "done" && path) st.assemble.path = path;
  } else {
    if (!st[phase]) st[phase] = {};
    st[phase][unit] = { job_id: j.job_id, status: j.status, ...(path ? { path } : {}) };
    if (j.status === "done" && path) {
      if (phase === "kf") st.shots[unit].kf_path = path;
      if (phase === "i2v") { st.shots[unit].i2v_job = j.job_id; st.shots[unit].i2v_path = path; }
      if (phase === "audio") st.audio[unit] = path;
      st[phase + "_pending"] = (st[phase + "_pending"] || []).filter((x) => x !== unit);
    }
  }
  adopted++;
  log.push("ledger: adopted " + j.job_id + " as " + phase + "/" + unit + " (" + j.status + (path ? " -> " + path : "") + ")");
}
await saveState(st);

// ---- (e) report pending ------------------------------------------------------
const pending = {
  kf: st.kf_pending || [],
  i2v: st.i2v_pending || [],
  audio: Object.keys(st.audio_jobs || {}).filter((id) => st.audio_jobs[id]?.status !== "done"),
  assemble: st.assemble?.path ? [] : (st.assemble?.job_id || (st.assemble?.shots?.length ? "assemble" : [])),
};
return {
  state: CFG.state,
  log,
  adopted,
  pending,
  next: "run templates/chunk.js for each non-empty pending phase (state is on disk)",
};