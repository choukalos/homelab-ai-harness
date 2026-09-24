#!/usr/bin/env python3
"""Qwen-Image-2.1 upgrade — client + live pipeline test (run on thor).

Offline (no GPU):
  A. payload construction: generate_image/edit_image defaults, model +
     references threading, user/client identity still stamped.
Live (matrix :8189):
  B. /images default -> qwen21, 25 steps (verify job output model field)
  C. /images model=legacy steps=4 -> legacy rollback path still works
  D. /images/edit default (qwen21) with references (consistency image)
  E. /images/edit model=legacy steps=8 -> legacy edit rollback path
"""
import io
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import media_pipeline_client as m  # noqa: E402

ok = 0
fail = 0


def check(name, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  PASS  {name}")
    else:
        fail += 1
        print(f"  FAIL  {name} {detail}")


class CapturingClient(m.MediaPipelineClient):
    """Capture payloads instead of hitting the network."""

    def __init__(self):
        super().__init__(base_url="http://127.0.0.1:1")
        self.json_payloads = []
        self.multipart_payloads = []

    def _post_json(self, endpoint, payload, user=None, client=None):
        p = dict(payload)
        if user:
            p["user"] = user
        if client:
            p["client"] = client
        self.json_payloads.append((endpoint, p))
        return "fake-job-id"

    def _post_multipart(self, endpoint, filepath, fields, user=None, client=None):
        f = dict(fields)
        if user:
            f["user"] = user
        if client:
            f["client"] = client
        self.multipart_payloads.append((endpoint, f))
        return "fake-job-id"

    def _wait(self, jid, timeout):
        # Return a plausible output per endpoint.
        if self.json_payloads and self.json_payloads[-1][0] == "/images":
            return {"image": "/home/chuck/data/comfyui/run/media_jobs/x/img.png"}
        return {"image": "/home/chuck/data/comfyui/run/media_jobs/x/edit.png"}


# ---------------------------------------------------------------- offline
print("== A. payload construction (offline) ==")
c = CapturingClient()
c.generate_image("a red fox", user="chuck", client="pi")
ep, p = c.json_payloads[-1]
check("t2i endpoint", ep == "/images", f"({ep})")
check("t2i default steps=25", p["steps"] == 25, f"({p['steps']})")
check("t2i default model omitted (server default qwen21)",
      "model" not in p, f"({p})")
check("t2i identity stamped", p.get("user") == "chuck" and p.get("client") == "pi")

c.generate_image("a red fox", model="legacy", steps=4)
ep, p = c.json_payloads[-1]
check("t2i legacy model+steps", p.get("model") == "legacy" and p["steps"] == 4,
      f"({p})")

c.generate_image("a red fox", model="qwen21", steps=30)
ep, p = c.json_payloads[-1]
check("t2i explicit qwen21+steps", p.get("model") == "qwen21" and p["steps"] == 30,
      f"({p})")

img = "/tmp/t2i_edit_input.png"
with open(img, "wb") as f:
    f.write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
c.edit_image(img, "make it night", user="chuck", client="pi")
ep, f = c.multipart_payloads[-1]
check("edit endpoint", ep == "/images/edit", f"({ep})")
check("edit default steps=25", f["steps"] == "25", f"({f['steps']})")
check("edit default model omitted", "model" not in f, f"({f})")
check("edit identity stamped", f.get("user") == "chuck" and f.get("client") == "pi")

c.edit_image(img, "make it night", references=[
    "media_jobs/abc123/keyframe.png", "char_sheet.png"])
ep, f = c.multipart_payloads[-1]
check("edit references comma-joined",
      f.get("references") == "media_jobs/abc123/keyframe.png,char_sheet.png",
      f"({f.get('references')})")

c.edit_image(img, "make it night", model="legacy", steps=8)
ep, f = c.multipart_payloads[-1]
check("edit legacy model+steps", f.get("model") == "legacy" and f["steps"] == "8",
      f"({f})")

# _wait surfaces 'timeout' job status (new contract)
try:
    c._wait = m.MediaPipelineClient._wait  # real one would poll; simulate:
    import types
    class T(m.MediaPipelineClient):
        def _get_json(self, path, timeout=60):
            raise RuntimeError("no")
    # direct unit: monkeypatch urlopen to return a timeout job
    real_urlopen = urllib.request.urlopen

    def fake_urlopen(req, timeout=30):
        class R:
            def read(self):
                return json.dumps({"status": "timeout",
                                   "error": "gpu job exceeded budget"}).encode()
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False
        return R()

    t = m.MediaPipelineClient(base_url="http://127.0.0.1:1")
    urllib.request.urlopen = fake_urlopen
    try:
        t._wait("somejob", timeout=5)
        check("_wait raises on timeout status", False)
    except m.PipelineError as e:
        check("_wait raises on timeout status", "timeout" in str(e), f"({e})")
    finally:
        urllib.request.urlopen = real_urlopen
except Exception as e:
    check("_wait raises on timeout status", False, f"({e!r})")

# ---------------------------------------------------------------- live
BASE = "http://192.168.4.55:8189"
p = m.MediaPipelineClient(BASE)
try:
    h = p.health()
    check("pipeline reachable", h.get("ok") is True, f"({h})")
except Exception as e:
    print(f"  (pipeline unreachable: {e} — skipping live sections)")
    print(f"\n== RESULT: {ok} passed, {fail} failed ==")
    sys.exit(1 if fail else 0)

print("== B. /images default (qwen21, 25 steps) ==")
img21 = p.generate_image(
    "A cinematic keyframe of a red fox in a misty pine forest at dawn, "
    "volumetric light, 35mm film still", width=1280, height=720,
    seed=42, user="chuck", client="pi")
print(f"   {img21}")
check("qwen21 image path", img21.startswith("/home/chuck/data/comfyui/run/media_jobs/"))
info = p.info(img21)
print("  ", json.dumps(info))
check("qwen21 image 1280x720", info["width"] == 1280 and info["height"] == 720,
      f"({info['width']}x{info['height']})")

# Verify the job recorded model=qwen21 (job output carries the model used).
jobid = img21[len("/home/chuck/data/comfyui/run/media_jobs/"):]
jobid = jobid.split("/")[0]
job = p._get_json(f"/jobs/{jobid}")
print("   job output:", json.dumps(job.get("output", {})))
check("job output model=qwen21",
      (job.get("output") or {}).get("model") == "qwen21",
      f"({(job.get('output') or {}).get('model')})")
check("job payload user/client", job.get("payload", {}).get("user") == "chuck"
      and job.get("payload", {}).get("client") == "pi",
      f"({job.get('payload', {})})")

print("== C. /images model=legacy steps=4 (rollback path) ==")
imgleg = p.generate_image(
    "A cinematic keyframe of a red fox in a misty pine forest at dawn, "
    "volumetric light, 35mm film still", width=1280, height=720,
    seed=42, steps=4, model="legacy", user="chuck", client="pi")
print(f"   {imgleg}")
check("legacy image path", imgleg.startswith("/home/chuck/data/comfyui/run/media_jobs/"))
jobid = imgleg[len("/home/chuck/data/comfyui/run/media_jobs/"):]
jobid = jobid.split("/")[0]
job = p._get_json(f"/jobs/{jobid}")
print("   job output:", json.dumps(job.get("output", {})))
check("legacy job model=legacy",
      (job.get("output") or {}).get("model") == "legacy",
      f"({(job.get('output') or {}).get('model')})")
linfo = p.info(imgleg)
check("legacy image 1280x720", linfo["width"] == 1280 and linfo["height"] == 720,
      f"({linfo['width']}x{linfo['height']})")

print("== D. /images/edit default (qwen21) with references ==")
# edit_image uploads a LOCAL file; fetch the qwen21 image first
local_img = p.fetch(img21, "/tmp")
print(f"   local copy: {local_img}")
# references = the qwen21 image's media_jobs-relative path (identity reference)
rel21 = "media_jobs/" + img21[len(m._JOB_PREFIX):]
edit21 = p.edit_image(
    local_img, "same fox, now at dusk with warm golden light, keep the character "
           "identical", seed=42, references=[rel21],
    user="chuck", client="pi")
print(f"   {edit21}")
check("edit21 image path", edit21.startswith("/home/chuck/data/comfyui/run/media_jobs/"))
jobid = edit21[len("/home/chuck/data/comfyui/run/media_jobs/"):]
jobid = jobid.split("/")[0]
job = p._get_json(f"/jobs/{jobid}")
print("   job output:", json.dumps(job.get("output", {})))
check("edit21 job model=qwen21",
      (job.get("output") or {}).get("model") == "qwen21",
      f"({(job.get('output') or {}).get('model')})")
check("edit21 job references=1",
      (job.get("output") or {}).get("references") == 1,
      f"({(job.get('output') or {}).get('references')})")
einfo = p.info(edit21)
# qwen21 snaps the canvas to its native grid (~1376x768 for a 1280x720
# input) — assert 16:9-ish aspect + size close to the source canvas, not exact.
check("edit21 image ~1280x720 (model grid snap)",
      abs(einfo["width"] / einfo["height"] - 16 / 9) < 0.05
      and abs(einfo["width"] - 1280) <= 128
      and abs(einfo["height"] - 720) <= 128,
      f"({einfo['width']}x{einfo['height']})")

print("== E. /images/edit model=legacy steps=8 (rollback path) ==")
editleg = p.edit_image(
    local_img, "same fox, now at dusk with warm golden light", seed=42,
    steps=8, model="legacy", user="chuck", client="pi")
print(f"   {editleg}")
check("legacy edit path", editleg.startswith("/home/chuck/data/comfyui/run/media_jobs/"))
jobid = editleg[len("/home/chuck/data/comfyui/run/media_jobs/"):]
jobid = jobid.split("/")[0]
job = p._get_json(f"/jobs/{jobid}")
print("   job output:", json.dumps(job.get("output", {})))
check("legacy edit job model=legacy",
      (job.get("output") or {}).get("model") == "legacy",
      f"({(job.get('output') or {}).get('model')})")
leginfo = p.info(editleg)
print("   legacy edit dims:", leginfo["width"], "x", leginfo["height"])
check("legacy edit ~1280x720", leginfo["width"] >= 1152 and leginfo["height"] >= 640,
      f"({leginfo['width']}x{leginfo['height']})")

print(f"\n== RESULT: {ok} passed, {fail} failed ==")
sys.exit(1 if fail else 0)