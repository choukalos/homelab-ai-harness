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
from typing import Callable

# Hook signature for the job-logging callback (2026-11-04, thor handoff T1):
# on_job(job_id, status, output) with status in
# {"submitted", "done", "error", "timeout"}; output = the job's output dict
# (done) or None. Lets the MCP server log SUBMIT/DONE lines with the exact
# tool name + client tag, so `docker logs` is a job-id recovery path.
OnJob = Callable[[str, str, dict | None], None]

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
# Parent of the job dir — the root relative media_jobs paths resolve against,
# so "media_jobs/<job_id>/<file>" -> "/home/chuck/data/comfyui/run/media_jobs/...".
_JOB_ROOT = _JOB_PREFIX.rsplit("media_jobs/", 1)[0]


class PipelineError(RuntimeError):
    pass


class MediaPipelineClient:
    def __init__(self, base_url: str | None = None, poll: float = 5.0):
        self.base = (base_url or DEFAULT_URL).rstrip("/")
        self.poll = poll

    # ------------------------------------------------------------ low level
    def _post_json(self, endpoint: str, payload: dict,
                   user: str | None = None, client: str | None = None,
                   on_job: OnJob | None = None) -> str:
        if user:
            payload["user"] = user
        if client:
            payload["client"] = client
        req = urllib.request.Request(
            f"{self.base}{endpoint}", data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=120) as r:
            jid = json.loads(r.read())["job_id"]
        if on_job:
            on_job(jid, "submitted", None)
        return jid

    def _post_multipart(self, endpoint: str, filepath: str, fields: dict,
                        user: str | None = None, client: str | None = None,
                        on_job: OnJob | None = None) -> str:
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
            jid = json.loads(r.read())["job_id"]
        if on_job:
            on_job(jid, "submitted", None)
        return jid

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
        """Accept an absolute GPU-host path, a relative media_jobs path
        ("media_jobs/<job_id>/<file>"), OR a job_id (resolved via GET /jobs/{id}).
        The pipeline's /dl_token only accepts absolute paths, so relative
        media_jobs refs are normalized against the job root."""
        if ref.startswith("/"):
            return ref
        if ref.startswith("media_jobs/"):
            return _JOB_ROOT + ref
        j = self._get_json(f"/jobs/{ref}")
        if j.get("status") == "error":
            raise PipelineError(f"job {ref} failed: {j.get('error')}")
        out = j.get("output") or {}
        for k in ("video", "image", "audio", "storyboard"):
            if k in out:
                return out[k]
        raise PipelineError(f"job {ref} has no resolvable output path: {out}")

    def _wait(self, jid: str, timeout: float,
              on_job: OnJob | None = None) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            with urllib.request.urlopen(f"{self.base}/jobs/{jid}", timeout=30) as r:
                j = json.loads(r.read())
            st = j.get("status")
            if st in ("done", "error", "timeout"):
                if on_job:
                    on_job(jid, st, j.get("output") if st == "done" else None)
                if st == "done":
                    return j.get("output", {})
                raise PipelineError(f"job {jid} {st}: {j.get('error')}")
            time.sleep(self.poll)
        raise PipelineError(f"job {jid} timed out after {timeout:.0f}s")

    # ------------------------------------- submit-and-poll (non-blocking)
    def job_status(self, job_id: str, timeout: float = 30) -> dict:
        """GET /jobs/{id} -> the full job dict (id, flow, status, output,
        error, created/started/finished, user, client, payload).
        Raises PipelineError on 404 (unknown id, or a finished job whose
        dir was retention-swept — recover via the durable ledger: the
        media_list_jobs MCP tool / list_jobs() client method)."""
        try:
            return self._get_json(f"/jobs/{job_id}", timeout)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise PipelineError(
                    f"job {job_id} not found — unknown id, or finished and "
                    f"retention-swept. Recover it with media_list_jobs / "
                    f"list_jobs() (durable ledger — finished jobs survive "
                    f"pipeline restarts); finished files are retained 14d "
                    f"and can be pulled via media_pull / pull() if you know "
                    f"the path")
            raise PipelineError(f"GET /jobs/{job_id} -> HTTP {e.code}")

    def poll_job(self, job_id: str, wait_seconds: float = 20.0) -> dict:
        """Long-poll a job for up to `wait_seconds` (non-raising while the
        job is merely still running). Returns:
          {"status": "done"|"error"|"timeout", "job": <job dict>}
          {"status": "running", "job": <job dict>, "waited_s": <float>}
        Raises PipelineError only for unknown/evicted jobs (404)."""
        t0 = time.time()
        deadline = t0 + max(1.0, wait_seconds)
        while True:
            j = self.job_status(job_id)
            st = j.get("status")
            if st in ("done", "error", "timeout"):
                return {"status": st, "job": j}
            if time.time() >= deadline:
                return {"status": "running", "job": j,
                        "waited_s": round(time.time() - t0, 1)}
            time.sleep(min(self.poll, 2.0))

    def finalize_job(self, job: dict) -> dict:
        """Convert a DONE job dict into the payload the blocking tools
        return: media files -> {path, location}; storyboard -> the parsed
        shot list; transcribe -> all artifact paths; other flows (e.g.
        add_voice) -> the raw output mapping."""
        out = job.get("output") or {}
        if "storyboard" in out:
            local = self.fetch(out["storyboard"], "/tmp")
            return json.loads(Path(local).read_text())
        if "tab" in out:
            # transcribe flow (2026-10-31): multi-file output — return every
            # artifact path (media_fetch / media_pull each one by path).
            return {k: out[k] for k in ("analysis", "tab", "lyrics", "midi",
                                        "audio") if k in out} | {
                       "location": "gpu_host"}
        for k in ("video", "image", "audio"):
            if k in out:
                return {"path": out[k], "location": "gpu_host"}
        return dict(out)

    # ------------------------------------------------------------- utilities
    def health(self) -> dict:
        with urllib.request.urlopen(f"{self.base}/health", timeout=15) as r:
            return json.loads(r.read())

    def list_jobs(self, status: str | None = None, client: str | None = None,
                  user: str | None = None, flow: str | None = None,
                  since: str | None = None, limit: int = 50,
                  timeout: float = 60) -> dict:
        """GET /jobs — durable job listing, newest first (2026-11-04).

        Finished jobs come from the pipeline's jobs.jsonl ledger (they
        SURVIVE pipeline restarts); live in-flight jobs are included.
        Filters: status (comma-separated: queued,running,done,error,timeout
        or 'all'), client, user, flow, since (ISO-8601), limit (1..200,
        default 50). Use it to RECOVER lost job_ids (match by client tag
        and/or time).
        -> {"count": N, "jobs": [{job_id, flow, status, client, user,
        created, done, model, duration_s, cost_usd, error, output, outputs}]}
        where outputs = run-dir-relative files (null when the job dir was
        retention-swept after 14 days)."""
        q = {k: v for k, v in {
            "status": status, "client": client, "user": user,
            "flow": flow, "since": since, "limit": limit,
        }.items() if v is not None}
        path = "/jobs" + ("?" + urllib.parse.urlencode(q) if q else "")
        return self._get_json(path, timeout)

    def fetch(self, host_path: str, local_dir: str = ".") -> str:
        """Download a result file from the GPU host to the local machine.
        On a basename collision in local_dir the file is suffixed
        (vo.wav -> vo_2.wav, vo_3.wav, ...) — existing files are never
        silently overwritten (2026-11-04, thor handoff T4)."""
        rel = host_path[len(_JOB_PREFIX):] if host_path.startswith(_JOB_PREFIX) \
            else os.path.basename(host_path)
        name = urllib.parse.quote(rel)
        with urllib.request.urlopen(f"{self.base}/files/{name}", timeout=600) as r:
            data = r.read()
        os.makedirs(local_dir, exist_ok=True)
        fname = os.path.basename(host_path)
        out = Path(local_dir) / fname
        if out.exists():
            stem, dot, ext = fname.partition(".")
            base, suffix = (stem, "." + ext) if dot else (fname, "")
            n = 2
            while True:
                out = Path(local_dir) / f"{base}_{n}{suffix}"
                if not out.exists():
                    break
                n += 1
        out.write_bytes(data)
        return str(out)

    # ----------------------------------------------------------- high level
    def storyboard(self, brief: str, n_shots: int = 5, aspect: str = "16:9",
                   user: str | None = None, client: str | None = None,
                   on_job: Callable[[str, str, dict | None], None] | None = None,
                   non_blocking: bool = False, timeout: float = 300) -> dict:
        """LLM shot list -> {"shots": [{"id","visual","vo"}]}.
        non_blocking=True -> submit only; returns {"job_id"} immediately
        (poll with poll_job + finalize_job)."""
        jid = self._post_json("/storyboard",
                              {"brief": brief, "n_shots": n_shots,
                               "aspect": aspect}, user, client, on_job)
        if non_blocking:
            return {"job_id": jid}
        out = self._wait(jid, timeout, on_job)
        local = self.fetch(out["storyboard"], "/tmp")
        return json.loads(Path(local).read_text())

    def generate_image(self, prompt: str, width: int = 1344, height: int = 768,
                       seed: int = 42, steps: int = 25, model: str | None = None,
                       user: str | None = None, client: str | None = None,
                       on_job: Callable[[str, str, dict | None], None] | None = None,
                       non_blocking: bool = False, timeout: float = 600) -> str | dict:
        """Text -> image (keyframe). Returns GPU-host path of the PNG.

        model: 'qwen21' (default; Qwen-Image-2.1 — 25 steps, ~30-120 s at
        1280x720) | 'legacy' (Qwen-Image-2512 GGUF + Lightning; pass steps=4).
        steps: the server clamps qwen21 steps to [10, 50] (no distilled LoRA
        at launch); the legacy path honors 4/8.
        non_blocking=True -> submit only; returns {"job_id"} immediately
        (poll with poll_job + finalize_job).
        """
        payload = {"prompt": prompt, "width": width, "height": height,
                   "seed": seed, "steps": steps}
        if model is not None:
            payload["model"] = model
        jid = self._post_json("/images", payload, user, client, on_job)
        if non_blocking:
            return {"job_id": jid}
        return self._wait(jid, timeout, on_job)["image"]

    def edit_image(self, image: str, prompt: str, seed: int = 42, steps: int = 25,
                   model: str | None = None, references: list[str] | None = None,
                   user: str | None = None, client: str | None = None,
                   on_job: Callable[[str, str, dict | None], None] | None = None,
                   non_blocking: bool = False, timeout: float = 600) -> str | dict:
        """Image+text -> edited image. `image` is a LOCAL path (uploaded).

        model: 'qwen21' (default; unified Qwen-Image-2.1 editing) | 'legacy'
        (Qwen-Image-Edit-2511 GGUF + Lightning; pass steps=8).
        references: up to 9 extra identity/consistency images (qwen21 only);
        each entry = a ComfyUI input/ filename OR a media_jobs-relative path
        like 'media_jobs/<job_id>/<file>.png' (staged into ComfyUI input/
        server-side). The canvas follows `image`; references influence
        identity only (e.g. a previous shot's keyframe for character/product
        consistency across shots).
        non_blocking=True -> submit only; returns {"job_id"} immediately.
        """
        fields = {"prompt": prompt, "seed": str(seed), "steps": str(steps)}
        if model is not None:
            fields["model"] = model
        if references:
            fields["references"] = ",".join(str(r) for r in references)
        jid = self._post_multipart("/images/edit", image, fields, user, client,
                                   on_job)
        if non_blocking:
            return {"job_id": jid}
        return self._wait(jid, timeout, on_job)["image"]

    def generate_shot(self, keyframe: str, prompt: str, width: int | None = None,
                      height: int | None = None, frames: int | None = None,
                      fps: float | None = None, seed: int = 42,
                      strength: float = 0.7, model: str | None = None,
                      user: str | None = None, client: str | None = None,
                      on_job: Callable[[str, str, dict | None], None] | None = None,
                      non_blocking: bool = False, timeout: float = 3600) -> str | dict:
        """Keyframe (LOCAL path) + style prompt -> I2V clip. Returns host path.

        model: 'ltxv2b' (fast draft; LTXV 2B 0.9.6 distilled — 768x512, 97f,
        25fps, ~8s/clip) | 'wan14b' (quality; Wan 2.2 14B I2V GGUF Q5 —
        832x480 ONLY, 81f (4n+1), 16fps, ~10-12 min/clip; 720p is rejected
        with a 400 — VRAM OOM gate 2026-10-25). None = server default
        (MEDIA_SHOT_MODEL; wan14b as of 2026-10-31). Omitted
        width/height/frames/fps -> the server applies the selected model's
        native defaults.
        strength: ltxv2b only — how strongly the keyframe anchors the clip
        (0.7 is the tuned default; lower = less warble). Ignored for wan14b.
        non_blocking=True -> submit only; returns {"job_id"} immediately.
        """
        fields = {"prompt": prompt, "seed": str(seed),
                  "strength": str(strength)}
        for k, v in (("width", width), ("height", height),
                     ("frames", frames), ("fps", fps)):
            if v is not None:
                fields[k] = str(v)
        if model is not None:
            fields["model"] = model
        jid = self._post_multipart("/shots", keyframe, fields, user, client,
                                   on_job)
        if non_blocking:
            return {"job_id": jid}
        return self._wait(jid, timeout, on_job)["video"]

    def text_to_speech(self, text: str, voice: str = "trailer",
                       user: str | None = None, client: str | None = None,
                       on_job: Callable[[str, str, dict | None], None] | None = None,
                       non_blocking: bool = False, timeout: float = 1800) -> str | dict:
        """Script -> voice-over wav. Returns GPU-host path. `voice` = a library
        name (see list_voices: trailer, default, narrator_f, deep_m, ...) or a
        reference wav path on the GPU host (3-15 s single-speaker clip).
        non_blocking=True -> submit only; returns {"job_id"} immediately."""
        jid = self._post_json("/tts", {"text": text, "voice": voice},
                              user, client, on_job)
        if non_blocking:
            return {"job_id": jid}
        return self._wait(jid, timeout, on_job)["audio"]

    # ------------------------------------------------- voice library (2026-09-25)
    def list_voices(self, timeout: float = 30) -> list:
        """GET /voices (sync) -> [{name, description, gender, style, added,
        protected, ref_exists, sample}]."""
        return self._get_json("/voices", timeout)["voices"]

    def add_voice(self, name: str, source: str, description: str = "",
                  gender: str = "", style: str = "", sample_text: str = "",
                  user: str | None = None, client: str | None = None,
                  on_job: Callable[[str, str, dict | None], None] | None = None,
                  non_blocking: bool = False, timeout: float = 900) -> dict:
        """POST /voices (job): register a voice from a reference wav (3-15 s).
        `source` = GPU-host path under the run/basedir dirs (stage external
        files with download/upload_local/put first). Re-registering a name
        replaces it (protected names -> 400). Returns the job output
        {voice, ref, sample, ref_duration_s}.
        non_blocking=True -> submit only; returns {"job_id"} immediately."""
        payload = {"name": name, "source": source, "description": description,
                   "gender": gender, "style": style}
        if sample_text:
            payload["sample_text"] = sample_text
        jid = self._post_json("/voices", payload, user, client, on_job)
        if non_blocking:
            return {"job_id": jid}
        return self._wait(jid, timeout, on_job)

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
                       client: str | None = None, on_job: OnJob | None = None,
                       non_blocking: bool = False,
                       timeout: float = 3600) -> str | dict:
        """Prompt(+lyrics) -> song/instrumental wav. Returns GPU-host path.
        non_blocking=True -> submit only; returns {"job_id"} immediately."""
        jid = self._post_json("/music",
                              {"prompt": prompt, "lyrics": lyrics,
                               "duration": duration, "seed": seed},
                              user, client, on_job)
        if non_blocking:
            return {"job_id": jid}
        return self._wait(jid, timeout, on_job)["audio"]

    def sfx(self, video: str, description: str = "", duration: float = 8.0,
            steps: int = 25, cfg: float = 4.5, seed: int = 42,
            user: str | None = None, client: str | None = None,
            on_job: OnJob | None = None, non_blocking: bool = False,
            timeout: float = 3600) -> str | dict:
        """Video (LOCAL path) -> synced SFX bed. Returns GPU-host path.
        non_blocking=True -> submit only; returns {"job_id"} immediately."""
        jid = self._post_multipart("/sfx", video,
                                   {"duration": str(duration),
                                    "steps": str(steps), "cfg": str(cfg),
                                    "seed": str(seed), "prompt": description,
                                    "negative_prompt": "", "fps": "24"},
                                   user, client, on_job)
        if non_blocking:
            return {"job_id": jid}
        return self._wait(jid, timeout, on_job)["audio"]

    def upscale(self, video: str, pipeline: str = "b", resolution: int = 1080,
                noise_scale: float = 0.0, fps: int = 24, seed: int = 42,
                user: str | None = None, client: str | None = None,
                on_job: OnJob | None = None, non_blocking: bool = False,
                timeout: float = 7200) -> str | dict:
        """Video (LOCAL path) -> upscaled. pipeline 'b'=SeedVR2 | 'a2'=fast.
        non_blocking=True -> submit only; returns {"job_id"} immediately."""
        jid = self._post_multipart("/upscale", video,
                                   {"pipeline": pipeline,
                                    "resolution": str(resolution),
                                    "noise_scale": str(noise_scale),
                                    "fps": str(fps), "seed": str(seed)},
                                   user, client, on_job)
        if non_blocking:
            return {"job_id": jid}
        return self._wait(jid, timeout, on_job)["video"]

    def assemble(self, shots: list, vo: str | None = None, music: str | None = None,
                 sfx: str | None = None, width: int = 1920, height: int = 1080,
                 fps: int = 24, vo_volume: float = 1.0, music_volume: float = 0.35,
                 sfx_volume: float = 0.9, vo_start: float | None = None,
                 loudnorm: bool = False, upscale_each: bool = False,
                 upscale_resolution: int = 1080, upscale_noise_scale: float = 0.0,
                 upscale_fps: int = 24, upscale_seed: int = 42,
                 text_overlays: list | None = None, user: str | None = None,
                 client: str | None = None, on_job: OnJob | None = None,
                 non_blocking: bool = False,
                 timeout: float = 1800) -> str | dict:
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
        non_blocking=True -> submit only; returns {"job_id"} immediately.
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
        jid = self._post_json("/assemble", payload, user, client, on_job)
        if non_blocking:
            return {"job_id": jid}
        return self._wait(jid, timeout, on_job)["video"]

    # ------------------------------------------------- post-gen edit tools (M1–M8)
    def trim(self, source: str, start: float = 0.0, end: float | None = None,
             duration: float | None = None, fps: int | None = None,
             width: int | None = None, height: int | None = None,
             user: str | None = None, client: str | None = None,
             on_job: OnJob | None = None, non_blocking: bool = False,
             timeout: float = 1800) -> str | dict:
        """Cut a clip to a time range (ffmpeg, always re-encodes libx264 crf 18).
        Exactly one of `end`/`duration`. `source` = GPU-host path OR local file
        (auto-uploaded). Returns GPU-host path of the trimmed video.
        non_blocking=True -> submit only; returns {"job_id"} immediately."""
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
        jid = self._post_json("/trim", payload, user, client, on_job)
        if non_blocking:
            return {"job_id": jid}
        return self._wait(jid, timeout, on_job)["video"]

    def freeze(self, source: str, frame: int = 0, duration: float = 2.0,
               width: int = 1280, height: int = 720, fps: int = 24,
               user: str | None = None, client: str | None = None,
               on_job: OnJob | None = None, non_blocking: bool = False,
               timeout: float = 1800) -> str | dict:
        """Still image or video frame -> pixel-static N-second clip (NO generative
        model). `frame` is a frame INDEX (0-based) when source is a video.
        `source` = GPU-host path OR local file (auto-uploaded).
        non_blocking=True -> submit only; returns {"job_id"} immediately."""
        payload = {"source": self._ensure_source(source), "frame": frame,
                   "duration": duration, "width": width, "height": height,
                   "fps": fps}
        jid = self._post_json("/freeze", payload, user, client, on_job)
        if non_blocking:
            return {"job_id": jid}
        return self._wait(jid, timeout, on_job)["video"]

    def caption(self, source: str, text: str, start: float = 0.0,
                end: float | None = None, position: str = "bottom",
                font_size: int | None = None, font: str = "DejaVuSans-Bold.ttf",
                color: str = "white", outline: int = 3,
                user: str | None = None, client: str | None = None,
                on_job: OnJob | None = None, non_blocking: bool = False,
                timeout: float = 1800) -> str | dict:
        """Burn text into a clip (ffmpeg drawtext, textfile-based; multiline OK).
        `source` = GPU-host path OR local file (auto-uploaded). `end` defaults
        to clip end. Returns GPU-host path of the captioned video.
        non_blocking=True -> submit only; returns {"job_id"} immediately."""
        payload = {"source": self._ensure_source(source), "text": text,
                   "start": start, "position": position, "font": font,
                   "color": color, "outline": outline}
        if end is not None:
            payload["end"] = end
        if font_size is not None:
            payload["font_size"] = font_size
        jid = self._post_json("/caption", payload, user, client, on_job)
        if non_blocking:
            return {"job_id": jid}
        return self._wait(jid, timeout, on_job)["video"]

    # ------------------------------------------------- song transcription (2026-10-31)
    def transcribe(self, path: str, instrument: str = "guitar",
                   tuning: str = "standard", lyrics: bool = True,
                   stems: bool = True, full_notes: bool = False,
                   whisper_model: str | None = None,
                   transpose_semitones: int = 0, target_key: str | None = None,
                   chord_style: str = "as_detected", capo: bool = False,
                   shape_hints: bool = True,
                   user: str | None = None, client: str | None = None,
                   on_job: OnJob | None = None, non_blocking: bool = False,
                   timeout: float = 1800) -> dict:
        """Audio/video (media_jobs path) -> guitar tab + timestamped lyrics
        (POST /transcribe, job). `path` MUST be a media_jobs path — stage
        external files with download/put/upload_local first (YouTube ingest
        happens on the MCP-server side, which owns yt-dlp).

        Chord/key/fingering surface (2026-10-31) — all deterministic
        post-processing on the pipeline (worker stage 5.5); the LLM never
        sees or touches any of it. Defaults are faithful to the recording;
        every modification is opt-in:
          tuning: v1 'standard' only (EADGBE).
          stems: vocal-stem ASR (default true; demucs failure falls back to
            full mix + caveat).
          full_notes: include the full note events in the output.
          whisper_model: faster-whisper model name (default: pipeline env
            MEDIA_TRANSCRIBE_WHISPER_MODEL, large-v3).
          transpose_semitones: int in -12..12 (bool rejected). Shifts note
            events, chord symbols (root shifted, quality preserved) and the
            key label; notes.json + song.mid are rewritten from the shifted
            events. Lyrics/BPM/section boundaries are time-based, unchanged.
          target_key: tonic like "E" / "Bb" / "F#m" (^[A-G][#b]?m?$). The
            offset is computed from the DETECTED key (shortest direction,
            +/-6) and WINS over transpose_semitones if both are given.
          chord_style: 'as_detected' | 'triads' | 'power' (case-insensitive).
            triads: 7th/9th/6th -> triad (Dmaj7->D, Bm7->Bm; dim/aug/sus
            kept). power: everything -> X5 (root + 5th, mode-agnostic —
            Dmaj7->D5, A#m7->A#5; also a correction for metal, where the
            CQT major/minor guess on power-chord material is arbitrary).
          capo: when the (transposed) key has no open shapes, suggest the
            smallest capo (0-5) landing the key on a friendly open-shape key
            (G/C/D/A/E/Bm/Em/Am); chords are then shown as the finger shapes
            (shifted down by the capo), like a capo tab site. Independent of
            chord_style.
          shape_hints: annotate every chord with its easiest fingering
            (open / E- or A-shape barre / power) computed on the FINAL finger
            chord (after transpose + capo — what you actually play).

        Returns the job output {analysis, tab, lyrics, midi, audio}
        (GPU-host paths). non_blocking=True -> submit only; returns
        {"job_id"} immediately (poll with poll_job + finalize_job)."""
        payload = {"path": path, "instrument": instrument, "tuning": tuning,
                   "lyrics": lyrics, "stems": stems, "full_notes": full_notes,
                   "transpose_semitones": transpose_semitones,
                   "chord_style": chord_style, "capo": capo,
                   "shape_hints": shape_hints}
        if whisper_model is not None:
            payload["whisper_model"] = whisper_model
        if target_key is not None:
            payload["target_key"] = target_key
        jid = self._post_json("/transcribe", payload, user, client, on_job)
        if non_blocking:
            return {"job_id": jid}
        return self._wait(jid, timeout, on_job)

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
        """Mint a signed public URL for a media_jobs path — absolute or
        relative ("media_jobs/<job_id>/<file>") — or a job_id.
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