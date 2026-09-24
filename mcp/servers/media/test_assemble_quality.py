#!/usr/bin/env python3
"""Live verification that the pipeline /assemble honors upscale_each +
text_overlays (the two features just added to the local client + MCP tool).

Flow: qwen21 keyframe -> I2V shot -> assemble(upscale_each=True,
text_overlays=[...]) -> verify 1080p mp4. Then vision-check the burned-in
title separately.

Run on thor (LAN access to matrix :8189). Long-running (~7-8 min: image +
shot + SeedVR2 upscale of one shot).
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import media_pipeline_client as m  # noqa: E402

BASE = "http://192.168.4.55:8189"
p = m.MediaPipelineClient(BASE)

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


def t(label):
    print(f"\n== {label} ==", flush=True)


t("health")
h = p.health()
check("pipeline reachable", h.get("ok") is True, f"({h})")

t("1. qwen21 keyframe")
img = p.generate_image(
    "A cinematic keyframe of a red fox sitting on a mossy log in a misty "
    "pine forest at dawn, volumetric light, 35mm film still",
    width=1280, height=720, seed=42, user="chuck", client="pi")
print(f"   {img}")
check("keyframe path", img.startswith(m._JOB_PREFIX))

t("2. fetch keyframe locally (generate_shot needs a local file)")
local_img = p.fetch(img, "/tmp")
print(f"   {local_img}")
check("local keyframe exists", os.path.isfile(local_img), f"({local_img})")

t("3. I2V shot (LTXV)")
t0 = time.time()
shot = p.generate_shot(
    local_img, "gentle mist drifting through the pines, subtle slow camera "
              "push-in, cinematic, soft volumetric light",
    width=768, height=512, frames=97, fps=24, seed=42, strength=0.7,
    user="chuck", client="pi")
print(f"   ({time.time()-t0:.0f}s) {shot}")
check("shot path", shot.startswith(m._JOB_PREFIX))

t("4. assemble(upscale_each=True, text_overlays=[...])  [SeedVR2 ~5 min]")
t0 = time.time()
video = p.assemble(
    [shot],
    width=1920, height=1080, fps=24,
    upscale_each=True, upscale_resolution=1080,
    text_overlays=[{"text": "THE FOX", "start": 0.5, "end": 3.5,
                    "position": "bottom", "size": 48, "color": "white"}],
    user="chuck", client="pi")
print(f"   ({time.time()-t0:.0f}s) {video}")
check("video path", video.startswith(m._JOB_PREFIX))

t("5. verify output")
info = p.info(video)
print("   info:", json.dumps(info))
check("output 1920x1080", info.get("width") == 1920 and info.get("height") == 1080,
      f"({info.get('width')}x{info.get('height')})")
check("output is video", info.get("video_codec") not in (None, "", "png"),
      f"({info.get('video_codec')})")
check("output has duration", info.get("duration_s", 0) > 1,
      f"({info.get('duration_s')}s)")

print(f"\n== RESULT: {ok} passed, {fail} failed ==")
print(f"VIDEO: {video}")
sys.exit(1 if fail else 0)