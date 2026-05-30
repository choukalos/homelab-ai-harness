# ComfyUI - harness Architecture

## Architecture Diagram

Open WebUI / Siri Shortcut / Future Apps
        |
        v
AI Harness API
  /tools/web
  /tools/kb
  /media/image
  /media/image-edit
  /media/video
        |
        v
Comfy Gateway / Worker
        |
        v
ComfyUI on Matrix GPU box
        |
        v
~/data/comfyui/basedir/
  models/
  workflows/
  inputs/
  outputs/

## Harness Directory Structure

homelab/ai-harness/
  app/
    routers/
      media.py              # image/video API endpoints
    services/
      comfy_client.py       # calls ComfyUI /prompt, /history, /upload/image
      media_jobs.py         # queue/status/result handling
      prompt_enhancer.py    # optional LLM prompt cleanup
    workflows/
      txt2img_sdxl.json
      img2img_sdxl.json
      upscale_4x.json
      svd_img2video.json
    schemas/
      media.py

## Flow

ComfyUI is the GPU execution engine, not the product/API layer

### Prompt to image flow:
Open WebUI tool / API call
→ ai-harness /media/image
→ load txt2img_sdxl workflow
→ inject prompt, seed, width, height, model
→ POST to ComfyUI /prompt
→ poll /history or websocket
→ return image URL/file

### Prompt + Image to Image flow
upload source image to harness
→ harness uploads image to ComfyUI input
→ load img2img workflow
→ inject prompt + image filename + denoise strength
→ return generated image

### Prompt to 10 sec video
prompt → image keyframe using JuggernautXL
image keyframe → video using SVD-XT
optional upscale/interpolate/export mp4

## API End Points
POST /media/image
POST /media/image/edit
POST /media/video
GET  /media/jobs/{job_id}
GET  /media/jobs/{job_id}/result

### Example API Payload
{
  "prompt": "cinematic photo of a silver 1980s sports car at sunset",
  "negative_prompt": "blurry, distorted, extra wheels",
  "style": "photoreal",
  "width": 1024,
  "height": 576,
  "upscale": true
}

## Open WebUI Tool 

generate_media(prompt, mode, image_optional, duration_optional)

Internally it calls the harness.  For Siri, keep the same API but add auth and family safe presets later.

### Blessed workflows

txt2img_sdxl_api.json
img2img_sdxl_api.json
prompt_to_svd_video_api.json

## Deployment Shape
Thor / homelab server:
  ai-harness
  Open WebUI
  LiteLLM
  reverse proxy

Matrix / AI workstation:
  ComfyUI
  ComfyUI models/data
  optional media-worker sidecar

## ComfyUI remains an internal network tool only
COMFY_BASE_URL=http://matrix:8188

# Build Order
1.  Make ComfyUI workflows manually in the UI.
2.  Export API JSON workflows.
3.  Add ComfyClient to ai-harness.
4.  Add /media/image.
5.  Add image upload + /media/image/edit.
6.  Add prompt→image→SVD video pipeline.
7.  Add job queue/status.
8.  Add Open WebUI tool.
9.  Add Siri shortcut API later.

