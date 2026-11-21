#!/usr/bin/env python3
"""M1–M5 client-layer acceptance — live test against matrix :8189.

Exercises the NEW client methods end-to-end (the pipeline-side behavior was
already accepted by media-pipeline/qa_m1_m5.py on the GPU host; this verifies
the mcp_media client layer — media_pipeline_client.kill_job / queue_status —
against the live pipeline):

  queue_status (M3): idle shape, features list, pending invariant;
                     populated shape (queued job: id/flow/client/waited_s)
  kill_job (M2):     real kill of a queued job (slot freed),
                     idempotent re-kill (200 no-op),
                     running -> 409 (queued-only),
                     unknown id -> 404,
                     client-tag mismatch -> 403, matching tag -> 200,
                     durable ledger row (list_jobs status=killed)

The queue is global (shared with any other client) and ltxv2b shots finish in
~8 s once the model is warm, so the test SYNCHRONIZES on queue state (polls
until the expected job is running/queued) instead of assuming a race window.

Run:  python3 test_m1m5_client.py [pipeline_url]
Default URL: http://192.168.4.55:8189 (from matrix itself, localhost works).
GPU cost: ~3 ltxv2b draft shots (~8 s each) on the media GPU.
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import media_pipeline_client as m  # noqa: E402

URL = sys.argv[1] if len(sys.argv) > 1 else "http://192.168.4.55:8189"
p = m.MediaPipelineClient(URL)
ok = 0
fail = 0

KEYFRAME = ("/home/chuck/data/comfyui/run/media_jobs/"
            "a163ed04215a/mp_a163ed04215a_00001_.png")
TAG = "m1m5-client-test"


def check(name, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  PASS  {name}")
    else:
        fail += 1
        print(f"  FAIL  {name} {detail}")


def expect_error(name, fn, code_substr, detail=""):
    """fn must raise PipelineError containing code_substr."""
    try:
        fn()
    except m.PipelineError as e:
        check(name, code_substr.lower() in str(e).lower(), f"({e})")
    except Exception as e:  # noqa: BLE001
        check(name, False, f"wrong exception type: {type(e).__name__}: {e}")
    else:
        check(name, False, f"no error raised {detail}")


def wait_until(pred, timeout=90, interval=2.0):
    """Poll queue_status until pred(qs) is True; return the last qs."""
    t0 = time.time()
    qs = p.queue_status()
    while time.time() - t0 < timeout:
        if pred(qs):
            return qs
        time.sleep(interval)
        qs = p.queue_status()
    return qs


def wait_status(jid, want, timeout=60):
    """Poll GET /jobs/{id} until status is in `want`; return the job dict."""
    t0 = time.time()
    j = p.job_status(jid)
    while time.time() - t0 < timeout and j.get("status") not in want:
        time.sleep(1.0)
        j = p.job_status(jid)
    return j


def submit_shot(tag):
    r = p.generate_shot(KEYFRAME, "a calm studio scene, gentle camera push",
                        model="ltxv2b", client=tag, non_blocking=True)
    return r["job_id"]


print(f"== 0. reachability ({URL}) ==")
h = p.health()
print("  ", json.dumps({k: h.get(k) for k in
                        ("ok", "pending", "max_concurrent", "max_queue_depth",
                         "features")}))
check("pipeline reachable", h.get("ok") is True)
check("M1-M5 features advertised",
      isinstance(h.get("features"), list)
      and {"assemble-duration-hold", "job-kill", "queue-summary",
           "job-progress"} <= set(h["features"]),
      f"({h.get('features')})")

print("== 1. queue_status idle (M3) ==")
# Wait for any in-flight jobs to drain (the queue is shared).
qs = wait_until(lambda q: not q.get("pending"), timeout=300)
print("  ", json.dumps(qs))
check("idle counts", qs["queue"]["counts"] == {"running": 0, "queued": 0},
      f"({qs['queue']['counts']})")
check("idle queued_jobs empty", qs["queue"]["queued_jobs"] == [])
check("idle oldest_queued null", qs["queue"]["oldest_queued"] is None)
check("pending invariant", qs["pending"] == 0)
check("max_* present", qs.get("max_concurrent") is not None
      and qs.get("max_queue_depth") is not None)

print("== 2. A running + B queued (synchronized) ==")
a = submit_shot(TAG)
# A must be RUNNING (not already done — a warm model can finish in ~8 s):
# resubmit until we catch it in flight.
for _ in range(5):
    j = wait_status(a, {"running", "done", "error", "timeout"}, timeout=30)
    if j.get("status") == "running":
        break
    print(f"   A finished too fast ({j.get('status')}) — resubmitting")
    a = submit_shot(TAG)
b = submit_shot(TAG)
# B must be QUEUED behind A (poll the queue view; resubmit if A finished
# and B slipped through to running/done first):
qs = p.queue_status()
for _ in range(5):
    qs = wait_until(lambda q: b in (q.get("queued") or []), timeout=30)
    if b in (qs.get("queued") or []):
        break
    j = p.job_status(b)
    if j.get("status") in ("done", "error", "timeout", "killed"):
        print(f"   B finished too fast ({j['status']}) — resubmitting")
        b = submit_shot(TAG)
    else:
        break
print(f"   A={a} B={b}")
print("  ", json.dumps(qs["queue"]))
check("A running", a in (qs.get("running") or []),
      f"(running={qs.get('running')})")
check("B queued", b in (qs.get("queued") or []),
      f"(queued={qs.get('queued')})")
qjobs = {j["job_id"]: j for j in qs["queue"]["queued_jobs"]}
check("queued_jobs has B with fields",
      b in qjobs and qjobs[b].get("flow") == "shots"
      and qjobs[b].get("client") == TAG and "created" in qjobs[b]
      and isinstance(qjobs[b].get("waited_s"), (int, float)),
      f"({qjobs.get(b)})")
check("oldest_queued is B", qs["queue"]["oldest_queued"]
      and qs["queue"]["oldest_queued"]["job_id"] == b)
check("pending == running+queued",
      qs["pending"] == qs["queue"]["counts"]["running"]
      + qs["queue"]["counts"]["queued"], f"({qs['pending']})")

print("== 3. kill the RUNNING job A -> 409 (queued-only) ==")
expect_error("running kill refused (409)",
             lambda: p.kill_job(a), "409")

print("== 4. kill the QUEUED job B -> real kill, slot freed ==")
res = p.kill_job(b, client=TAG)
print("  ", json.dumps(res))
check("B killed", res.get("killed") is True and res.get("status") == "killed",
      f"({res})")
check("queue_position_freed reported",
      isinstance(res.get("queue_position_freed"), int))
qs = wait_until(lambda q: b not in (q.get("queued") or []), timeout=30)
check("B gone from queue", b not in (qs.get("queued") or [])
      and b not in {j["job_id"] for j in qs["queue"]["queued_jobs"]},
      f"(queued={qs.get('queued')})")

print("== 5. re-kill B -> idempotent 200 no-op ==")
res = p.kill_job(b, client=TAG)
print("  ", json.dumps(res))
check("re-kill no-op", res.get("killed") is False
      and res.get("status") == "killed", f"({res})")

print("== 6. client-tag scoping (fresh queued job C) ==")
# A (step 3's running job) may finish mid-test — a sacrificial runner D
# holds the running slot so C is reliably QUEUED for the scope tests.
d = submit_shot(TAG + "/d")
jd = wait_status(d, {"running", "done", "error", "timeout"}, timeout=30)
if jd.get("status") != "running":
    d = submit_shot(TAG + "/d")
    jd = wait_status(d, {"running", "done", "error", "timeout"}, timeout=30)
c = submit_shot(TAG + "/c")
qs = wait_until(lambda q: c in (q.get("queued") or []), timeout=30)
expect_error("wrong tag refused (403)",
             lambda: p.kill_job(c, client="some-other-client"), "403")
res = p.kill_job(c, client=TAG + "/c")
print("  ", json.dumps(res))
check("matching tag kills", res.get("killed") is True, f"({res})")
# Clean up D if it ended up queued (it was submitted to hold the slot).
jd = p.job_status(d)
if jd.get("status") == "queued":
    p.kill_job(d, client=TAG + "/d")

print("== 7. unknown id -> 404 ==")
expect_error("unknown id 404",
             lambda: p.kill_job("deadbeef0000"), "404")

print("== 8. durable ledger rows (killed survives) ==")
time.sleep(2)
lj_b = p.list_jobs(status="killed", client=TAG, limit=20)
ids_b = [j["job_id"] for j in lj_b.get("jobs", [])]
lj_c = p.list_jobs(status="killed", client=TAG + "/c", limit=20)
ids_c = [j["job_id"] for j in lj_c.get("jobs", [])]
print("  ", json.dumps([ids_b, ids_c]))
check("killed jobs in ledger (exact client tags)",
      b in ids_b and c in ids_c, f"({ids_b} {ids_c})")
row = next((j for j in lj_b["jobs"] if j["job_id"] == b), {})
check("ledger row fields", row.get("status") == "killed"
      and row.get("flow") == "shots" and row.get("client") == TAG,
      f"({row})")

print("== 9. job A completes (no collateral damage) ==")
r = p.poll_job(a, wait_seconds=180)
print("  ", r["status"])
check("A done", r["status"] == "done", f"({r['status']})")
out = p.finalize_job(r["job"])
check("A has video output", isinstance(out, dict) and "path" in out,
      f"({out})")

print(f"\nSUMMARY: {ok} passed, {fail} failed")
sys.exit(1 if fail else 0)
