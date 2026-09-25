"""media_pipeline_client — thin HTTP client for the GPU-host media-pipeline service.

This is the file the REMOTE machine ships to its media-mcp server. It is
self-contained (Python stdlib only — no third-party deps) so it drops into any
MCP server with zero extra installs.

Configure the pipeline location via the MEDIA_PIPELINE_URL env var
(e.g. http://<gpu-host>:8189). All high-level methods BLOCK until the job
finishes and return the GPU-host path of the result. Use .fetch() to download
a result to the local machine.

Example:
    from media_pipeline_client import MediaPipelineClient
    pipe = MediaPipelineClient()
    shot = pipe.generate_shot("keyframe.jpg", "neon reflections, slow push-in")
    final = pipe.assemble(shots=[shot], vo="vo.wav", music="music.wav")
"""
from __future__ import annotations
import json
import mimetypes
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

def _load_dotenv(path: str | None = None) -> None:
    """Load KEY=VALUE pairs from a .env into os.environ (no override of existing).
    Lets the remote box keep MEDIA_PIPELINE_URL in a .env instead of exporting it."""
    p = Path(path or os.environ.get("MEDIA_ENV_FILE", ".env"))
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


# If MEDIA_PIPELINE_URL isn't already in the environment, try a .env file.
if "MEDIA_PIPELINE_URL" not in os.environ:
    _load_dotenv()
DEFAULT_URL = os.environ.get("MEDIA_PIPELINE_URL", "http://127.0.0.1:8189")
# Public base for signed pull URLs (media_pull). Served by the thor Caddy
# public route (2026-09-07: siri.choukalos.com/media/pipeline/* — option C,
# no media.choukalos.com subdomain). Token IS the credential; no API key.
PUBLIC_URL = os.environ.get(
    "MEDIA_PUBLIC_URL", "https://siri.choukalos.com/media/pipeline").rstrip("/")
# /files/{name} is relative to the pipeline's job dir (JOB_DIR on the GPU host).
_JOB_PREFIX = "/home/chuck/data/comfyui/run/media_jobs/"


class PipelineError(RuntimeError):
    pass


class MediaPipelineClient:
    def __init__(self, base_url: str | None = None, poll: float = 5.0):
        self.base = (base_url or DEFAULT_URL).rstrip("/")
        self.poll = poll

    # ------------------------------------------------------------ low level
    def _post_json(self, endpoint: str, payload: dict,
                   user: str | None = None, client: str | None = None) -> str:
        if user:
            payload["user"] = user
        if client:
            payload["client"] = client
        req = urllib.request.Request(
            f"{self.base}{endpoint}", data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read())["job_id"]

    def _post_multipart(self, endpoint: str, filepath: str, fields: dict,
                        user: str | None = None, client: str | None = None) -> str:
        if user:
            fields["user"] = user
        if client:
            fields["client"] = client
        boundary = "----mpb" + uuid.uuid4().hex
        fname = os.path.basename(filepath)
        ctype = mimetypes.guess_type(fname)[0] or "application/octet-stream"
        body = b""
        for k, v in fields.items():
            body += (f"--{boundary}\r\nContent-Disposition: form-data; "
                     f"name=\"{k}\"\r\n\r\n{v}\r\n").encode()
        with open(filepath, "rb") as f:
            fdata = f.read()
        body += (f"--{boundary}\r\nContent-Disposition: form-data; "
                 f"name=\"file\"; filename=\"{fname}\"\r\n"
                 f"Content-Type: {ctype}\r\n\r\n").encode()
        body += fdata + f"\r\n--{boundary}--\r\n".encode()
        req = urllib.request.Request(
            f"{self.base}{endpoint}", data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST")
        with urllib.request.urlopen(req, timeout=300) as r:
            return json.loads(r.read())["job_id"]

    def _post_multipart_sync(self, endpoint: str, filepath: str, fields: dict,
                             timeout: float = 900) -> dict:
        """Multipart POST that returns the FULL JSON (sync endpoints like
        /upload, which return {path} instead of {job_id})."""
        boundary = "----mpb" + uuid.uuid4().hex
        fname = os.path.basename(filepath)
        ctype = mimetypes.guess_type(fname)[0] or "application/octet-stream"
        body = b""
        for k, v in fields.items():
            body += (f"--{boundary}\r\nContent-Disposition: form-data; "
                     f"name=\"{k}\"\r\n\r\n{v}\r\n").encode()
        with open(filepath, "rb") as f:
            fdata = f.read()
        body += (f"--{boundary}\r\nContent-Disposition: form-data; "
                 f"name=\"file\"; filename=\"{fname}\"\r\n"
                 f"Content-Type: {ctype}\r\n\r\n").encode()
        body += fdata + f"\r\n--{boundary}--\r\n".encode()
        req = urllib.request.Request(
            f"{self.base}{endpoint}", data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())

    def _get_json(self, path: str, timeout: float = 60) -> dict:
        with urllib.request.urlopen(f"{self.base}{path}", timeout=timeout) as r:
            return json.loads(r.read())

    def _post_json_sync(self, endpoint: str, payload: dict,
                        timeout: float = 300) -> dict:
        """JSON POST for SYNC endpoints (no job_id; returns the full JSON)."""
        req = urllib.request.Request(
            f"{self.base}{endpoint}", data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())

    def _ensure_source(self, source: str) -> str:
        """Return a matrix media_jobs path for trim/freeze/caption `source`:
        GPU-host paths pass through; LOCAL files are uploaded via /upload
        (multipart, sync) and the resulting media_jobs path is returned."""
        if source.startswith(_JOB_PREFIX):
            return source
        if not os.path.isfile(source):
            raise PipelineError(f"source not found (local or on GPU host): {source}")
        return self._post_multipart_sync("/upload", source, {})["path"]

    def _resolve_path(self, ref: str) -> str:
        """Accept a media_jobs path OR a job_id (resolved via GET /jobs/{id})."""
        if ref.startswith("/"):
            return ref
        j = self._get_json(f"/jobs/{ref}")
        if j.get("status") == "error":
            raise PipelineError(f"job {ref} failed: {j.get('error')}")
        out = j.get("output") or {}
        for k in ("video", "image", "audio", "storyboard"):
            if k in out:
                return out[k]
        raise PipelineError(f"job {ref} has no resolvable output path: {out}")

    def _wait(self, jid: str, timeout: float) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            with urllib.request.urlopen(f"{self.base}/jobs/{jid}", timeout=30) as r:
                j = json.loads(r.read())
            if j.get("status") == "done":
                return j.get("output", {})
            if j.get("status") in ("error", "timeout"):
                raise PipelineError(f"job {jid} {j.get('status')}: {j.get('error')}")
            time.sleep(self.poll)
        raise PipelineError(f"job {jid} timed out after {timeout:.0f}s")

    # ------------------------------------------------------------- utilities
    def health(self) -> dict:
        with urllib.request.urlopen(f"{self.base}/health", timeout=15) as r:
            return json.loads(r.read())

    def fetch(self, host_path: str, local_dir: str = ".") -> str:
        """Download a result file from the GPU host to the local machine."""
        rel = host_path[len(_JOB_PREFIX):] if host_path.startswith(_JOB_PREFIX) \
            else os.path.basename(host_path)
        name = urllib.parse.quote(rel)
        with urllib.request.urlopen(f"{self.base}/files/{name}", timeout=600) as r:
            data = r.read()
        os.makedirs(local_dir, exist_ok=True)
        out = Path(local_dir) / os.path.basename(host_path)
        out.write_bytes(data)
        return str(out)

    # ----------------------------------------------------------- high level
    def storyboard(self, brief: str, n_shots: int = 5, aspect: str = "16:9",
                   user: str | None = None, client: str | None = None,
                   timeout: float = 300) -> dict:
        """LLM shot list -> {"shots": [{"id","visual","vo"}]}."""
        out = self._wait(self._post_json("/storyboard",
                                         {"brief": brief, "n_shots": n_shots,
                                          "aspect": aspect},
                                         user, client), timeout)
        local = self.fetch(out["storyboard"], "/tmp")
        return json.loads(Path(local).read_text())

    def generate_image(self, prompt: str, width: int = 1344, height: int = 768,
                       seed: int = 42, steps: int = 25, model: str | None = None,
                       user: str | None = None, client: str | None = None,
                       timeout: float = 600) -> str:
        """Text -> image (keyframe). Returns GPU-host path of the PNG.

        model: 'qwen21' (default; Qwen-Image-2.1 — 25 steps, ~30-120 s at
        1280x720) | 'legacy' (Qwen-Image-2512 GGUF + Lightning; pass steps=4).
        steps: the server clamps qwen21 steps to [10, 50] (no distilled LoRA
        at launch); the legacy path honors 4/8.
        """
        payload = {"prompt": prompt, "width": width, "height": height,
                   "seed": seed, "steps": steps}
        if model is not None:
            payload["model"] = model
        return self._wait(self._post_json("/images", payload,
                                          user, client), timeout)["image"]

    def edit_image(self, image: str, prompt: str, seed: int = 42, steps: int = 25,
                   model: str | None = None, references: list[str] | None = None,
                   user: str | None = None, client: str | None = None,
                   timeout: float = 600) -> str:
        """Image+text -> edited image. `image` is a LOCAL path (uploaded).

        model: 'qwen21' (default; unified Qwen-Image-2.1 editing) | 'legacy'
        (Qwen-Image-Edit-2511 GGUF + Lightning; pass steps=8).
        references: up to 9 extra identity/consistency images (qwen21 only);
        each entry = a ComfyUI input/ filename OR a media_jobs-relative path
        like 'media_jobs/<job_id>/<file>.png' (staged into ComfyUI input/
        server-side). The canvas follows `image`; references influence
        identity only (e.g. a previous shot's keyframe for character/product
        consistency across shots).
        """
        fields = {"prompt": prompt, "seed": str(seed), "steps": str(steps)}
        if model is not None:
            fields["model"] = model
        if references:
            fields["references"] = ",".join(str(r) for r in references)
        return self._wait(self._post_multipart("/images/edit", image, fields,
                                               user, client), timeout)["image"]

    def generate_shot(self, keyframe: str, prompt: str, width: int = 768,
                      height: int = 512, frames: int = 97, fps: float = 24.0,
                      seed: int = 42, strength: float = 0.7,
                      user: str | None = None, client: str | None = None,
                      timeout: float = 3600) -> str:
        """Keyframe (LOCAL path) + style prompt -> ~4s I2V clip. Returns host path.

        strength: how strongly the keyframe anchors the clip. Lower = less
        warble/morphing (0.7 is the tuned default; 0.6 marginally smoother,
        0.8+ more motion but more warble). Prompt for visual STYLE, not motion.
        """
        return self._wait(self._post_multipart("/shots", keyframe,
                                               {"prompt": prompt, "width": str(width),
                                                "height": str(height),
                                                "frames": str(frames), "fps": str(fps),
                                                "seed": str(seed),
                                                "strength": str(strength)},
                                               user, client), timeout)["video"]

    def text_to_speech(self, text: str, voice: str = "trailer",
                       user: str | None = None, client: str | None = None,
                       timeout: float = 1800) -> str:
        """Script -> voice-over wav. Returns GPU-host path. `voice` = a library
        name (see list_voices: trailer, default, narrator_f, deep_m, ...) or a
        reference wav path on the GPU host (3-15 s single-speaker clip)."""
        return self._wait(self._post_json("/tts", {"text": text, "voice": voice},
                                          user, client),
                          timeout)["audio"]

    # ------------------------------------------------- voice library (2026-09-25)
    def list_voices(self, timeout: float = 30) -> list:
        """GET /voices (sync) -> [{name, description, gender, style, added,
        protected, ref_exists, sample}]."""
        return self._get_json("/voices", timeout)["voices"]

    def add_voice(self, name: str, source: str, description: str = "",
                  gender: str = "", style: str = "", sample_text: str = "",
                  user: str | None = None, client: str | None = None,
                  timeout: float = 900) -> dict:
        """POST /voices (job): register a voice from a reference wav (3-15 s).
        `source` = GPU-host path under the run/basedir dirs (stage external
        files with download/upload_local/put first). Re-registering a name
        replaces it (protected names -> 400). Returns the job output
        {voice, ref, sample, ref_duration_s}."""
        payload = {"name": name, "source": source, "description": description,
                   "gender": gender, "style": style}
        if sample_text:
            payload["sample_text"] = sample_text
        return self._wait(self._post_json("/voices", payload, user, client),
                          timeout)

    def delete_voice(self, name: str, timeout: float = 30) -> dict:
        """DELETE /voices/{name} (sync). 400 on protected names, 404 missing.
        Returns {"deleted": name}."""
        req = urllib.request.Request(f"{self.base}/voices/{name}",
                                     method="DELETE")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            raise PipelineError(f"/voices/{name} -> HTTP {e.code}: "
                                f"{e.read()[:200]!r}")

    def generate_music(self, prompt: str, lyrics: str = "", duration: int = 30,
                       seed: int = 42, user: str | None = None,
                       client: str | None = None, timeout: float = 3600) -> str:
        """Prompt(+lyrics) -> song/instrumental wav. Returns GPU-host path."""
        return self._wait(self._post_json("/music",
                                          {"prompt": prompt, "lyrics": lyrics,
                                           "duration": duration, "seed": seed},
                                          user, client),
                          timeout)["audio"]

    def sfx(self, video: str, description: str = "", duration: float = 8.0,
            steps: int = 25, cfg: float = 4.5, seed: int = 42,
            user: str | None = None, client: str | None = None,
            timeout: float = 3600) -> str:
        """Video (LOCAL path) -> synced SFX bed. Returns GPU-host path."""
        return self._wait(self._post_multipart("/sfx", video,
                                               {"duration": str(duration),
                                                "steps": str(steps), "cfg": str(cfg),
                                                "seed": str(seed), "prompt": description,
                                                "negative_prompt": "", "fps": "24"},
                                               user, client),
                          timeout)["audio"]

    def upscale(self, video: str, pipeline: str = "b", resolution: int = 1080,
                noise_scale: float = 0.0, fps: int = 24, seed: int = 42,
                user: str | None = None, client: str | None = None,
                timeout: float = 7200) -> str:
        """Video (LOCAL path) -> upscaled. pipeline 'b'=SeedVR2 | 'a2'=fast."""
        return self._wait(self._post_multipart("/upscale", video,
                                               {"pipeline": pipeline,
                                                "resolution": str(resolution),
                                                "noise_scale": str(noise_scale),
                                                "fps": str(fps), "seed": str(seed)},
                                               user, client),
                          timeout)["video"]

    def assemble(self, shots: list, vo: str | None = None, music: str | None = None,
                 sfx: str | None = None, width: int = 1920, height: int = 1080,
                 fps: int = 24, vo_volume: float = 1.0, music_volume: float = 0.35,
                 sfx_volume: float = 0.9, vo_start: float | None = None,
                 loudnorm: bool = False, upscale_each: bool = False,
                 upscale_resolution: int = 1080, upscale_noise_scale: float = 0.0,
                 upscale_fps: int = 24, upscale_seed: int = 42,
                 text_overlays: list | None = None, user: str | None = None,
                 client: str | None = None, timeout: float = 1800) -> str:
        """Concat shots + mix audio -> final mp4. `shots` are GPU-host paths.

        M4 extensions (backward compatible): `shots` entries may be objects
        {path, in?, out?, duration?} (trim/hold a shot; still image + duration
        renders a static clip); `sfx` may be a list [{path, at}] for
        timestamped placement; `vo_start` offsets the VO from t=0; `loudnorm`
        applies EBU R128 to the final mix.

        Quality extensions (2026-09-24): `upscale_each` runs SeedVR2 (B) on
        every shot before concat for 1080p-quality output (tune with
        upscale_resolution / upscale_noise_scale / upscale_fps / upscale_seed);
        `text_overlays` burns crisp titles into shots post-I2V (list of
        {text, start?, end?, position?, size?, color?} — LTXV warps baked-in
        text, so composite titles in post, not in the I2V prompt).
        """
        payload = {"shots": shots, "width": width, "height": height, "fps": fps,
                   "vo_volume": vo_volume, "music_volume": music_volume,
                   "sfx_volume": sfx_volume}
        for k, v in (("vo", vo), ("music", music), ("sfx", sfx)):
            if v:
                payload[k] = v
        if vo_start is not None:
            payload["vo_start"] = vo_start
        if loudnorm:
            payload["loudnorm"] = True
        if upscale_each:
            payload.update({"upscale_each": True,
                            "upscale_resolution": upscale_resolution,
                            "upscale_noise_scale": upscale_noise_scale,
                            "upscale_fps": upscale_fps,
                            "upscale_seed": upscale_seed})
        if text_overlays:
            payload["text_overlays"] = text_overlays
        return self._wait(self._post_json("/assemble", payload, user, client),
                          timeout)["video"]

    # ------------------------------------------------- post-gen edit tools (M1–M8)
    def trim(self, source: str, start: float = 0.0, end: float | None = None,
             duration: float | None = None, fps: int | None = None,
             width: int | None = None, height: int | None = None,
             user: str | None = None, client: str | None = None,
             timeout: float = 1800) -> str:
        """Cut a clip to a time range (ffmpeg, always re-encodes libx264 crf 18).
        Exactly one of `end`/`duration`. `source` = GPU-host path OR local file
        (auto-uploaded). Returns GPU-host path of the trimmed video."""
        if (end is None) == (duration is None):
            raise PipelineError("exactly one of end/duration is required")
        payload = {"source": self._ensure_source(source), "start": start}
        if end is not None:
            payload["end"] = end
        else:
            payload["duration"] = duration
        for k, v in (("fps", fps), ("width", width), ("height", height)):
            if v is not None:
                payload[k] = v
        return self._wait(self._post_json("/trim", payload, user, client),
                          timeout)["video"]

    def freeze(self, source: str, frame: int = 0, duration: float = 2.0,
               width: int = 1280, height: int = 720, fps: int = 24,
               user: str | None = None, client: str | None = None,
               timeout: float = 1800) -> str:
        """Still image or video frame -> pixel-static N-second clip (NO generative
        model). `frame` is a frame INDEX (0-based) when source is a video.
        `source` = GPU-host path OR local file (auto-uploaded)."""
        payload = {"source": self._ensure_source(source), "frame": frame,
                   "duration": duration, "width": width, "height": height,
                   "fps": fps}
        return self._wait(self._post_json("/freeze", payload, user, client),
                          timeout)["video"]

    def caption(self, source: str, text: str, start: float = 0.0,
                end: float | None = None, position: str = "bottom",
                font_size: int | None = None, font: str = "DejaVuSans-Bold.ttf",
                color: str = "white", outline: int = 3,
                user: str | None = None, client: str | None = None,
                timeout: float = 1800) -> str:
        """Burn text into a clip (ffmpeg drawtext, textfile-based; multiline OK).
        `source` = GPU-host path OR local file (auto-uploaded). `end` defaults
        to clip end. Returns GPU-host path of the captioned video."""
        payload = {"source": self._ensure_source(source), "text": text,
                   "start": start, "position": position, "font": font,
                   "color": color, "outline": outline}
        if end is not None:
            payload["end"] = end
        if font_size is not None:
            payload["font_size"] = font_size
        return self._wait(self._post_json("/caption", payload, user, client),
                          timeout)["video"]

    def info(self, path: str, timeout: float = 60) -> dict:
        """ffprobe metadata for a matrix path (sync).
        -> {duration_s, width, height, fps, video_codec, audio_codecs[],
            size_bytes, bitrate_bps}"""
        return self._get_json(f"/info?path={urllib.parse.quote(path, safe='')}",
                              timeout)

    def upload_local(self, source: str, subdirectory: str | None = None,
                     timeout: float = 300) -> str:
        """Copy a file from the MATRIX host into media_jobs (sync). `source`
        MUST be under the ComfyUI basedir (400 otherwise). Returns the
        media_jobs path."""
        payload = {"source": source}
        if subdirectory:
            payload["subdirectory"] = subdirectory
        return self._post_json_sync("/upload_local", payload, timeout)["path"]

    def download(self, url: str, subdirectory: str | None = None,
                 filename: str | None = None, timeout: float = 600) -> str:
        """Fetch a URL into media_jobs on the matrix host (sync).
        Returns the media_jobs path."""
        payload = {"url": url}
        if subdirectory:
            payload["subdirectory"] = subdirectory
        if filename:
            payload["filename"] = filename
        return self._post_json_sync("/download", payload, timeout)["path"]

    def put(self, local_file: str, subdirectory: str | None = None,
            timeout: float = 900) -> str:
        """Push a LOCAL file to media_jobs/uploads/ (multipart, sync).
        500MB cap (413). Returns the media_jobs path to use in subsequent tools."""
        fields = {}
        if subdirectory:
            fields["subdirectory"] = subdirectory
        return self._post_multipart_sync("/upload", local_file, fields,
                                         timeout)["path"]

    def pull(self, path: str, ttl_hours: float = 24, local_dir: str | None = None,
             timeout: float = 60) -> dict:
        """Mint a signed public URL for a media_jobs path (or job_id).
        -> {url, expires_at, token, path} (+ local_path when local_dir given;
        the local copy uses the LAN /files fetch)."""
        if not (0 < ttl_hours <= 168):
            raise PipelineError("ttl_hours must be in (0, 168]")
        p = self._resolve_path(path)
        d = self._post_json_sync("/dl_token", {"path": p, "ttl_hours": ttl_hours},
                                 timeout)
        out = {"url": PUBLIC_URL + d["url_path"], "expires_at": d["expires_at"],
               "token": d["token"], "path": p}
        if local_dir:
            out["local_path"] = self.fetch(p, local_dir)
        return out


# Convenience singleton (reads MEDIA_PIPELINE_URL from env)
pipe = MediaPipelineClient()