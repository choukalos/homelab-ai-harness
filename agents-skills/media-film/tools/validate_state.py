#!/usr/bin/env python3
"""media-film state validator — C1/C2/C11/C12 preflight.

Run as preflight before production (P0 steps 4-5) and after every chunk:

  python3 tools/validate_state.py <state.json> [--cards <shots-dir>]
      [--voices <voices.json>] [--ledger <ledger.json>] [--info <info.json>]
      [--fix]

Checks (exit 1 on any mismatch — children REFUSE to proceed):
  1. lists vs records (C1): every *_pending id has no done record; every
     done id is not in *_pending; every pending id exists in shots.
  2. mirrors vs tables (C1): shots.<id>.kf_job == kf.<id>.job_id (and i2v,
     and the *_path mirrors) — records win.
  3. job ids: non-empty, [A-Za-z0-9_-]+, unique across kf/i2v records.
  4. audio keys (C11): one canonical family — tts_<shot> / sfx_<name> /
     music_cue_<x>; no parallel key families.
  5. prompts (C12): kf_prompt / i2v_prompt / vo_text are raw strings —
     not JSON-encoded (no leading/trailing quote pair, no \" escapes),
     not arrays/objects.
  6. cards (C2, --cards): one card per shot id; vo_text is a string;
     voice is canonical (--voices); duration_s is numeric.
  7. optional cross-checks: --ledger (media_list_jobs JSON) -> every
     submitted job_id appears in the ledger sweep; --info (JSON
     {path: media_info result}) -> every recorded path probes OK.
--fix: repair *_pending lists and mirror fields from the records
  (records win), then report what still mismatches.

Exit: 0 clean | 1 mismatch | 2 usage error.
"""
import argparse
import json
import re
import sys
from pathlib import Path

JOBID_RE = re.compile(r"^[A-Za-z0-9_-]{4,64}$")
AUDIO_KEY_RE = re.compile(r"^(tts_[A-Za-z0-9]+|sfx_[A-Za-z0-9]+|music_cue_[A-Za-z0-9]+)$")


def die(msg, code=2):
    print(f"validate_state: {msg}", file=sys.stderr)
    sys.exit(code)


def load(path, what):
    try:
        return json.loads(Path(path).read_text())
    except Exception as e:
        die(f"cannot read {what} '{path}': {e}")


def looks_json_encoded(s):
    if not isinstance(s, str) or len(s) < 2:
        return False
    if s.startswith('"') and s.endswith('"'):
        return True
    if '\\"' in s:
        return True
    return False


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("state", help="project state.json")
    ap.add_argument("--cards", help="shots dir with one <id>.json card per shot (C2)")
    ap.add_argument("--voices", help="JSON list of canonical voice names (C2)")
    ap.add_argument("--ledger", help="media_list_jobs JSON ({jobs:[...]}) — cross-check job ids")
    ap.add_argument("--info", help="JSON {path: media_info result} — cross-check recorded paths")
    ap.add_argument("--fix", action="store_true",
                    help="repair *_pending lists and mirrors from the records (records win)")
    a = ap.parse_args()

    st = load(a.state, "state")
    if not isinstance(st, dict):
        die("state.json must be a JSON object")
    shots = st.get("shots") or {}
    if not isinstance(shots, dict):
        die("state.shots must be an object")
    errs = []

    tables = {
        "kf": st.get("kf") or {},
        "i2v": st.get("i2v") or {},
        "audio_jobs": st.get("audio_jobs") or {},
    }

    # --- --fix first: repair lists + mirrors from records (records win) -------
    if a.fix:
        for phase, (mjob, mpath) in (("kf", ("kf_job", "kf_path")),
                                     ("i2v", ("i2v_job", "i2v_path"))):
            pkey = phase + "_pending"
            tbl = tables[phase]
            fixed = [sid for sid in (st.get(pkey) or [])
                     if tbl.get(sid, {}).get("status") != "done"]
            if fixed != (st.get(pkey) or []):
                st[pkey] = fixed
                print(f"--fix: {pkey} repaired -> {fixed}")
            for sid, sh in shots.items():
                rec = tbl.get(sid)
                if not isinstance(rec, dict) or not isinstance(sh, dict):
                    continue
                if rec.get("job_id") and sh.get(mjob) != rec["job_id"]:
                    sh[mjob] = rec["job_id"]
                    print(f"--fix: {sid}.{mjob} -> {rec['job_id']}")
                if rec.get("path") and sh.get(mpath) != rec["path"]:
                    sh[mpath] = rec["path"]
                    print(f"--fix: {sid}.{mpath} -> {rec['path']}")
        Path(a.state).write_text(json.dumps(st, indent=2) + "\n")

    # --- 1. lists vs records (C1) -------------------------------------------
    for phase in ("kf", "i2v"):
        pkey = phase + "_pending"
        pending = st.get(pkey) or []
        tbl = tables[phase]
        for sid in pending:
            if tbl.get(sid, {}).get("status") == "done":
                errs.append(f"C1 {pkey}: {sid} is pending but its {phase} record is done")
            if sid not in shots:
                errs.append(f"C1 {pkey}: {sid} has no shots record")

    # --- 2. mirrors vs tables (C1) -------------------------------------------
    for phase, (mjob, mpath) in (("kf", ("kf_job", "kf_path")),
                                 ("i2v", ("i2v_job", "i2v_path"))):
        for sid, sh in shots.items():
            rec = tables[phase].get(sid)
            if not isinstance(rec, dict):
                continue
            if sh.get(mjob) and rec.get("job_id") and sh[mjob] != rec["job_id"]:
                errs.append(f"C1 {sid}.{mjob} mirror ({sh[mjob]}) != {phase}.{sid}.job_id ({rec['job_id']})")
            if sh.get(mpath) and rec.get("path") and sh[mpath] != rec["path"]:
                errs.append(f"C1 {sid}.{mpath} mirror != {phase}.{sid}.path")

    # --- 3. job ids ------------------------------------------------------------
    seen = set()
    for phase in ("kf", "i2v"):
        for sid, rec in tables[phase].items():
            jid = rec.get("job_id") if isinstance(rec, dict) else None
            if jid and (not isinstance(jid, str) or not JOBID_RE.match(jid)):
                errs.append(f"C1 {phase}.{sid}: job_id {jid!r} is malformed")
            if jid and jid in seen:
                errs.append(f"C1 {phase}.{sid}: job_id {jid} duplicated across records")
            if jid:
                seen.add(jid)
    ajid = (st.get("assemble") or {}).get("job_id")
    if ajid and (not isinstance(ajid, str) or not JOBID_RE.match(ajid)):
        errs.append(f"C1 assemble.job_id {ajid!r} is malformed")

    # --- 4. audio keys (C11) ----------------------------------------------------
    for key, rec in tables["audio_jobs"].items():
        if not AUDIO_KEY_RE.match(key):
            errs.append(
                f"C11 audio_jobs: '{key}' is not a canonical key "
                "(tts_<shot> / sfx_<name> / music_cue_<x>) — no parallel key families"
            )
            continue
        if not isinstance(rec, dict):
            errs.append(f"C11 audio_jobs.{key}: record must be an object")
            continue
        if rec.get("status") in ("submitted", "running", "done") and not rec.get("job_id"):
            errs.append(f"C11 audio_jobs.{key}: status {rec.get('status')} but no job_id")

    # --- 5. raw-text prompts (C12) ---------------------------------------------
    for sid, sh in shots.items():
        if not isinstance(sh, dict):
            continue
        for field in ("kf_prompt", "i2v_prompt", "vo_text"):
            v = sh.get(field)
            if v is None:
                continue
            if not isinstance(v, str):
                errs.append(f"C12 {sid}.{field}: not a raw string ({type(v).__name__})")
            elif looks_json_encoded(v):
                errs.append(f"C12 {sid}.{field}: looks JSON-encoded — store raw text in state")

    # --- 6. cards (C2) ------------------------------------------------------------
    if a.cards:
        voices = None
        if a.voices:
            voices = set(load(a.voices, "voices"))
        cards_dir = Path(a.cards)
        if not cards_dir.is_dir():
            errs.append(f"C2 cards dir not found: {cards_dir}")
        else:
            for sid in shots:
                card_f = cards_dir / f"{sid}.json"
                if not card_f.exists():
                    errs.append(f"C2 missing card for {sid}: {card_f}")
                    continue
                card = load(str(card_f), f"card {sid}")
                vt = card.get("vo_text")
                if vt is not None:
                    if not isinstance(vt, str):
                        errs.append(f"C2 {sid}.vo_text is {type(vt).__name__}, must be a string")
                    elif looks_json_encoded(vt):
                        errs.append(f"C2 {sid}.vo_text looks JSON-encoded")
                voice = card.get("voice")
                if voice is not None:
                    if not isinstance(voice, str):
                        errs.append(f"C2 {sid}.voice must be a string")
                    elif voices is not None and voice not in voices:
                        errs.append(f"C2 {sid}.voice '{voice}' is not canonical (media_list_voices)")
                ds = card.get("duration_s")
                if ds is not None and (isinstance(ds, bool) or not isinstance(ds, (int, float))):
                    errs.append(f"C2 {sid}.duration_s must be a number (got {type(ds).__name__})")

    # --- 7. optional cross-checks --------------------------------------------------
    if a.ledger:
        ledger = load(a.ledger, "ledger")
        ledger_ids = {j.get("job_id") for j in (ledger.get("jobs") or [])}
        for phase in ("kf", "i2v"):
            for sid, rec in tables[phase].items():
                jid = rec.get("job_id") if isinstance(rec, dict) else None
                if jid and jid not in ledger_ids:
                    errs.append(f"ledger {phase}.{sid}: job_id {jid} not in the ledger sweep (stale? lost?)")
    if a.info:
        info = load(a.info, "info")
        for phase in ("kf", "i2v"):
            for sid, rec in tables[phase].items():
                p = rec.get("path") if isinstance(rec, dict) else None
                if not p:
                    continue
                r = info.get(p)
                if r is None:
                    errs.append(f"info {phase}.{sid}: no media_info result for {p}")
                elif isinstance(r, dict) and (r.get("status") == "error" or not r.get("duration_s")):
                    errs.append(f"info {phase}.{sid}: media_info failed for {p}: {json.dumps(r)[:100]}")

    if errs:
        print(f"validate_state: {len(errs)} mismatch(es) — REFUSE to proceed (fix manually; --fix only repairs lists/mirrors):")
        for e in errs:
            print("  - " + e)
        sys.exit(1)
    print(f"validate_state: OK ({len(shots)} shots, {len(tables['audio_jobs'])} audio keys)")


if __name__ == "__main__":
    main()
