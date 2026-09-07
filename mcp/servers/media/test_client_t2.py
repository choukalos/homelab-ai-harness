#!/usr/bin/env python3
"""T2 acceptance — live client test against matrix :8189 (run on thor).

Exercises the NEW client methods end-to-end:
  info, trim (end + duration), freeze, caption, upload_local (400 gate),
  /upload multipart (put), /download, /dl_token + LAN /dl/<token>,
  assemble M4 extensions (object shots, timestamped sfx, vo_start, loudnorm),
  pull (signed URL + local copy + job_id resolution).
"""
import hashlib
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import media_pipeline_client as m  # noqa: E402

p = m.MediaPipelineClient("http://192.168.4.55:8189")
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


PEANUT = "/home/chuck/data/comfyui/run/media_jobs/11b290ce2acf/final.mp4"

print("== 1. /info (sync) ==")
info = p.info(PEANUT)
print("  ", json.dumps(info))
check("info duration ~58.6", abs(info["duration_s"] - 58.6) < 1.0,
      f"({info['duration_s']}s)")
check("info fields", all(k in info for k in
      ("duration_s", "width", "height", "fps", "video_codec", "audio_codecs",
       "size_bytes")))

print("== 2. /trim (end and duration) ==")
t_end = p.trim(PEANUT, start=0.0, end=2.0)
print(f"   end=2.0: {t_end}")
check("trim path", t_end.startswith("/home/chuck/data/comfyui/run/media_jobs/"))
t_dur = p.trim(PEANUT, start=1.0, duration=1.5)
print(f"   duration=1.5: {t_dur}")
ti = p.info(t_end)
print("  ", json.dumps(ti))
check("trim end duration ~2.0", abs(ti["duration_s"] - 2.0) < 0.3,
      f"({ti['duration_s']}s)")
ti2 = p.info(t_dur)
check("trim duration= ~1.5", abs(ti2["duration_s"] - 1.5) < 0.3,
      f"({ti2['duration_s']}s)")
# exactly-one-of validation (client-side)
try:
    p.trim(PEANUT)
    check("trim rejects missing end/duration", False)
except m.PipelineError as e:
    check("trim rejects missing end/duration", "exactly one" in str(e))

print("== 3. /freeze (job) — frame 0 of trim, 2s ==")
freeze_path = p.freeze(t_end, frame=0, duration=2.0)
print(f"   {freeze_path}")
fi = p.info(freeze_path)
check("freeze duration ~2.0", abs(fi["duration_s"] - 2.0) < 0.3,
      f"({fi['duration_s']}s)")

print("== 4. /caption (job) — burn TEST CAPTION ==")
cap_path = p.caption(t_end, "TEST CAPTION", start=0.0)
print(f"   {cap_path}")
ci = p.info(cap_path)
check("caption duration ~2.0", abs(ci["duration_s"] - 2.0) < 0.3,
      f"({ci['duration_s']}s)")

print("== 5. /upload (multipart, sync) — local file -> media_jobs ==")
local = "/tmp/t2_upload_test.bin"
with open(local, "wb") as f:
    f.write(os.urandom(64 * 1024))
up = p.put(local, subdirectory="qa_tests")
print(f"   {up}")
check("upload path", up.startswith("/home/chuck/data/comfyui/run/media_jobs/"))

print("== 6. /upload_local (sync) — 400 gate on non-basedir source ==")
try:
    p.upload_local("/etc/hostname")
    check("upload_local 400 on bad source", False)
except urllib.error.HTTPError as e:
    body = e.read().decode()[:100]
    check("upload_local 400 on bad source", e.code == 400, f"({body})")

print("== 7. /download (sync) — URL -> media_jobs ==")
# Use the LAN /files URL of the peanut final as the download source.
files_url = ("http://192.168.4.55:8189/files/" +
             urllib.parse.quote("11b290ce2acf/final.mp4", safe=""))
dl = p.download(files_url, subdirectory="qa_tests", filename="t2_dl.mp4")
print(f"   {dl}")
check("download path", dl.endswith("t2_dl.mp4"))
di = p.info(dl)
check("download duration ~58.6", abs(di["duration_s"] - 58.6) < 1.0,
      f"({di['duration_s']}s)")

print("== 8. /dl_token (sync) + LAN /dl/<token> ==")
tok = p._post_json_sync("/dl_token", {"path": t_end, "ttl_hours": 2})
print("   url_path:", tok["url_path"], "expires_at:", tok["expires_at"])
check("token fields", all(k in tok for k in ("token", "url_path", "expires_at")))
with urllib.request.urlopen("http://192.168.4.55:8189" + tok["url_path"],
                             timeout=120) as r:
    data = r.read()
# fetch the trim via /files and compare byte-for-byte
trim_files = ("http://192.168.4.55:8189/files/" +
              urllib.parse.quote(t_end[len("/home/chuck/data/comfyui/run/media_jobs/"):],
                                 safe=""))
with urllib.request.urlopen(trim_files, timeout=120) as r:
    ref2 = r.read()
check("dl token bytes == /files bytes (trim)",
      hashlib.sha256(data).hexdigest() == hashlib.sha256(ref2).hexdigest(),
      f"({len(data)} vs {len(ref2)} bytes)")

print("== 9. /assemble M4 extensions (object shots, timestamped sfx, vo_start, loudnorm) ==")
tts = p.text_to_speech("This is the test voice line.")
print("   tts:", tts)
final = p.assemble(
    shots=[{"path": t_end, "in": 0.0, "out": 1.5},
           {"path": freeze_path, "duration": 1.5}],
    vo=tts, vo_start=0.5,
    sfx=[{"path": tts, "at": 0.5}],
    loudnorm=True,
)
print(f"   final: {final}")
fi2 = p.info(final)
print("  ", json.dumps(fi2))
check("assemble duration ~3.0", abs(fi2["duration_s"] - 3.0) < 0.4,
      f"({fi2['duration_s']}s)")

print("== 10. pull() — signed URL construction + local copy + job_id ==")
out = p.pull(t_end, ttl_hours=24, local_dir="/tmp/t2_pull")
print("   url:", out["url"])
check("pull url base",
      out["url"].startswith("https://siri.choukalos.com/media/pipeline/dl/"))
check("pull local copy", os.path.isfile(out.get("local_path", "")))
if os.path.isfile(out.get("local_path", "")):
    with open(out["local_path"], "rb") as f:
        check("pull local bytes == /files bytes",
              hashlib.sha256(f.read()).hexdigest() ==
              hashlib.sha256(ref2).hexdigest())
out2 = p.pull("11b290ce2acf", ttl_hours=1)
check("pull by job_id",
      out2["path"].startswith("/home/chuck/data/comfyui/run/media_jobs/"),
      f"({out2['path']})")

print(f"\n== RESULT: {ok} passed, {fail} failed ==")
sys.exit(1 if fail else 0)