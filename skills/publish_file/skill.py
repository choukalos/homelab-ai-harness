#!/usr/bin/env python3
"""
publish_file skill — THIN WRAPPER over the mcp_filebridge publish engine.

P12-C (SEC-12, 2026-11-26): the publish engine (validated / atomic /
size-capped / idempotent) now lives in the bridge —
`mcp/servers/filebridge/publish_engine.py`, parameterized by the bridge
registry (`filebridge.yaml` `publish_targets`). This skill keeps the
original contract (skill.yml inputs: source_path, destination_name,
subdirectory, overwrite) and POSTs to
http://mcp_filebridge:8000/publish (ai-net; override with
PUBLISH_FILE_BRIDGE_URL), passing the result through VERBATIM.

NO fallback: single engine, no duplicate logic. If the bridge is down the
skill fails with a clear error (the mcp_filebridge container is down or
ai-net is partitioned) — it never publishes locally.

Result (passed through from the engine):
  {summary, artifact_path, report: {path, url, size_bytes, sha256,
   destination_name, subdirectory[, duplicate]}}
or {"error": "..."} on rejection / bridge failure.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

import logging

logger = logging.getLogger("skill.publish_file")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# The bridge's publish endpoint (ai-net). The skill runs inside
# skill-runner (ai-net), where the docker DNS name resolves; override for
# non-container contexts (e.g. CLI on the host with a reachable URL).
BRIDGE_URL = os.environ.get("PUBLISH_FILE_BRIDGE_URL",
                            "http://mcp_filebridge:8000").rstrip("/")
# This skill is the blog drop zone (skill.yml contract) — the 'blog'
# publish target in the bridge registry.
TARGET = "blog"
# Blog target subdirs (must match skill.yml's enum + the bridge registry's
# blog subdirs — the 2026-11-06 drift regression, bd2d2f32d502). 'files'
# is intentionally NOT in the list (it would produce /files/files/<name>).
SUBDIRS = ("ai", "images", "audio", "video", "tabs")
# < max_runtime (60s in skill.yml) so the wrapper fails before the job
# runtime cap.
TIMEOUT_S = int(os.environ.get("PUBLISH_FILE_TIMEOUT_S", "55"))


# ---------------------------------------------------------------------------
# Entry point (skill runner contract)
# ---------------------------------------------------------------------------


def run(params: dict[str, Any], job: Any) -> dict[str, Any]:
    """Execute the publish via the bridge engine. See module docstring."""
    source_path = str(params.get("source_path") or "").strip()
    destination_name = str(params.get("destination_name") or "").strip()
    subdirectory = str(params.get("subdirectory") or "ai").strip()
    overwrite = bool(params.get("overwrite", False))

    if not source_path:
        return {"error": "source_path is required"}
    if subdirectory not in SUBDIRS:
        return {
            "error": (
                f"subdirectory must be one of {list(SUBDIRS)} "
                "(default: 'ai')"
            )
        }

    job.add_log(
        f"publish_file: POST {BRIDGE_URL}/publish target={TARGET} "
        f"source={source_path} subdir={subdirectory} overwrite={overwrite}"
    )
    body = json.dumps({
        "source_path": source_path,
        "target": TARGET,
        "destination_name": destination_name,
        "subdirectory": subdirectory,
        "overwrite": overwrite,
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{BRIDGE_URL}/publish", data=body, method="POST",
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            out = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            err = json.loads(e.read().decode("utf-8")).get("error", str(e))
        except Exception:
            err = str(e)
        job.add_log(f"publish_file: rejected — {err}")
        return {"error": err}
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        job.add_log(f"publish_file: bridge unreachable — {e}")
        return {
            "error": (
                f"publish bridge unreachable at {BRIDGE_URL}/publish ({e}) — "
                "the mcp_filebridge container is down or ai-net is "
                "partitioned (no local fallback by design)"
            )
        }
    except json.JSONDecodeError as e:
        job.add_log(f"publish_file: invalid bridge response — {e}")
        return {"error": f"publish bridge returned invalid JSON: {e}"}

    if not isinstance(out, dict) or "error" in out:
        err = out.get("error") if isinstance(out, dict) else str(out)
        job.add_log(f"publish_file: rejected — {err}")
        return {"error": str(err)}
    job.add_log(f"publish_file: done — {out.get('summary', '')}")
    return out
