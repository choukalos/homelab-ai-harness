#!/usr/bin/env python3
"""MCP Skills Server — cross-client skill discovery and execution.

The "tool gateway" pattern: three tiny always-on tools instead of one MCP
tool per skill, so the context footprint is negligible no matter how many
skills exist. Per-skill detail (inputs, description) is fetched on demand via
list_skills().

  - list_skills()                        List all skills (name, description, inputs)
  - run_skill(name, prompt?, params?)    Run a skill by name + short prompt
  - get_skill_job(job_id)                Retrieve a job's status/result

Backend: skill-runner (FastAPI, :8091). `POST /skills/{name}` is synchronous
(it blocks until the job reaches a terminal state or an approval gate), so
run_skill just issues the POST with a generous timeout and returns the final
job. The skill does NOT run on the client — it runs server-side.

Identity threading: the caller's LiteLLM key (forwarded by LiteLLM via the
Authorization header, `extra_headers: ["Authorization"]`) is passed to
skill-runner as X-API-Key so the job attributes to the right user. Falls back
to the service key (SKILL_RUNNER_API_KEY) when no caller key is present.

Transport: streamable-http (HTTP, default 0.0.0.0:8000)
"""

import os
import logging
from typing import Optional

import httpx
from mcp.server import FastMCP
from mcp.server.fastmcp import Context

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SKILL_RUNNER_URL: str = os.environ.get(
    "SKILL_RUNNER_URL", "http://skill-runner:8091"
).rstrip("/")
SKILL_RUNNER_API_KEY: str = os.environ.get("SKILL_RUNNER_API_KEY", "")  # service key (fallback)
MCPS_HOST: str = os.environ.get("MCPS_HOST", "0.0.0.0")
DEFAULT_MAX_WAIT: int = int(os.environ.get("SKILL_RUNNER_TIMEOUT", "180"))  # seconds

logger = logging.getLogger("mcp_skills")

_TERMINAL = ("completed", "failed", "cancelled", "interrupted")

# ---------------------------------------------------------------------------
# Identity threading
# ---------------------------------------------------------------------------


def _caller_key(ctx: Optional[Context]) -> Optional[str]:
    """Extract the caller's API key from the forwarded Authorization header.

    LiteLLM forwards the caller's Authorization header for plain non-OAuth
    MCP servers. Returns the raw key (stripping a "Bearer " prefix) or None.
    """
    try:
        request = ctx.request_context.request
        auth = request.headers.get("authorization")
        if not auth:
            return None
        if auth.lower().startswith("bearer "):
            return auth[7:].strip()
        return auth.strip()
    except Exception:  # no request context / not an HTTP request
        return None


def _headers(ctx: Optional[Context]) -> dict:
    """Headers for a skill-runner call. Presents the caller's key if present,
    else the service key (open mode when neither is set)."""
    h = {"Content-Type": "application/json"}
    key = _caller_key(ctx) or (SKILL_RUNNER_API_KEY or None)
    if key:
        h["X-API-Key"] = key
    return h


# ---------------------------------------------------------------------------
# skill-runner helpers
# ---------------------------------------------------------------------------


def _get_skills(ctx: Optional[Context]) -> dict:
    with httpx.Client(timeout=30) as client:
        r = client.get(f"{SKILL_RUNNER_URL}/skills", headers=_headers(ctx))
        r.raise_for_status()
        return r.json()


def _find_skill(ctx: Optional[Context], name: str) -> Optional[dict]:
    data = _get_skills(ctx)
    for s in data.get("skills", []):
        if s.get("name") == name:
            return s
    return None


def _resolve_params(
    ctx: Optional[Context], name: str, prompt: Optional[str], params: Optional[dict]
) -> dict:
    """Build the skill input dict.

    - `params` (explicit) wins — the agent mapped the prompt to the inputs.
    - else `prompt` (free-form) is mapped to the skill's primary string input
      (a well-known name first, then the first required string input, then the
      first string input). If no string input exists, passed as {"prompt": ...}.
    - else empty.
    """
    if params:
        return dict(params)
    if not prompt:
        return {}
    skill = _find_skill(ctx, name)
    if skill:
        inputs = skill.get("inputs", [])
        primary_names = (
            "prompt", "query", "topic", "interests", "subject", "question", "request"
        )
        for pn in primary_names:
            for inp in inputs:
                if inp.get("name") == pn and inp.get("type") in ("string", "str"):
                    return {pn: prompt}
        for inp in inputs:
            if inp.get("required") and inp.get("type") in ("string", "str"):
                return {inp["name"]: prompt}
        for inp in inputs:
            if inp.get("type") in ("string", "str"):
                return {inp["name"]: prompt}
    return {"prompt": prompt}


# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------

mcp = FastMCP(
    name="mcp_skills",
    instructions=(
        "Family skills/agents gateway. Call list_skills() to discover available "
        "skills (name, description, declared inputs). Call run_skill(name, prompt, "
        "params) to run one by name: pass the user's short prompt in `prompt` (it is "
        "mapped to the skill's primary input) or map it yourself into `params` (which "
        "wins). run_skill blocks until the job finishes (or hits an approval gate) and "
        "returns the job (job_id, status, summary, artifact_path). Call "
        "get_skill_job(job_id) to re-fetch a finished job. Skills run server-side; only "
        "the result and artifact path are returned."
    ),
    host=MCPS_HOST,
)


@mcp.tool(
    name="list_skills",
    description="List all available family skills/agents with name, description, and declared inputs.",
)
def list_skills(ctx: Context) -> dict:
    """List all skills.

    Returns:
        Dict with `skills` (list of {name, description, version, model_alias,
        max_runtime, channels, inputs}) and `count`.
    """
    try:
        return _get_skills(ctx)
    except httpx.HTTPStatusError as e:
        raise RuntimeError(
            f"skill-runner GET /skills failed: {e.response.status_code} {e.response.text}"
        ) from e
    except Exception as e:
        raise RuntimeError(f"skill-runner unreachable at {SKILL_RUNNER_URL}: {e}") from e


@mcp.tool(
    name="run_skill",
    description=(
        "Run a family skill by name with a short prompt (mapped to the skill's primary "
        "input) or explicit params. Blocks until the job finishes (up to the skill's "
        "max_runtime) and returns the job (job_id, status, summary, artifact_path)."
    ),
)
def run_skill(
    name: str,
    prompt: Optional[str] = None,
    params: Optional[dict] = None,
    max_wait: Optional[int] = None,
    ctx: Context = None,
) -> dict:
    """Run a skill.

    Args:
        name: Skill name (e.g. "morning_brief").
        prompt: Short natural-language prompt; mapped to the skill's primary
            string input. (The agent can map explicitly via `params` instead.)
        params: Explicit input dict (wins over `prompt`).
        max_wait: Seconds to wait before giving up (default: the skill's
            max_runtime, else 180s).

    Returns:
        The job: {job_id, skill, status, summary, artifact_path, ...}. If the
        job is at an approval gate, status is "awaiting_approval" (approve via
        the runner). If it did not finish within max_wait, an error is raised
        (the job is still running server-side; use get_skill_job once you have
        the id).
    """
    resolved_params = _resolve_params(ctx, name, prompt, params)
    skill = _find_skill(ctx, name)
    if skill is None:
        # Still attempt the run (the skill may exist but not be listed); warn.
        logger.warning("run_skill: '%s' not in GET /skills; attempting anyway", name)
    if max_wait is None:
        wait = (
            skill.get("max_runtime")
            if skill and skill.get("max_runtime")
            else DEFAULT_MAX_WAIT
        )
    else:
        wait = max_wait
    wait = max(1, int(wait))

    try:
        with httpx.Client(timeout=wait + 30) as client:
            r = client.post(
                f"{SKILL_RUNNER_URL}/skills/{name}",
                json={"params": resolved_params, "channel": "mcp"},
                headers=_headers(ctx),
            )
    except httpx.TimeoutException as e:
        raise RuntimeError(
            f"skill '{name}' did not finish within {wait}s (job is still running "
            f"server-side). Retry run_skill with a larger max_wait, or fetch the job "
            f"via get_skill_job once you have its id."
        ) from e
    if r.status_code >= 400:
        raise RuntimeError(
            f"skill-runner POST /skills/{name} failed: {r.status_code} {r.text}"
        )
    job = r.json()
    return job


@mcp.tool(
    name="get_skill_job",
    description="Retrieve a skill job's current status and result (summary, artifact path) by job_id.",
)
def get_skill_job(job_id: str, ctx: Context = None) -> dict:
    """Retrieve a skill job by id.

    Args:
        job_id: The job id returned by run_skill.

    Returns:
        Job details: {job_id, skill, status, summary, artifact_path, ...}.
    """
    with httpx.Client(timeout=30) as client:
        r = client.get(
            f"{SKILL_RUNNER_URL}/skills/jobs/{job_id}", headers=_headers(ctx)
        )
    if r.status_code == 404:
        raise RuntimeError(f"Job {job_id} not found")
    if r.status_code >= 400:
        raise RuntimeError(f"skill-runner GET job failed: {r.status_code} {r.text}")
    return r.json()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Run the MCP skills server over streamable-http transport (0.0.0.0:8000)."""
    logging.basicConfig(level=logging.INFO)
    logger.info("Starting mcp_skills, skill-runner=%s", SKILL_RUNNER_URL)
    mcp.run(transport="streamable-http")  # defaults to 0.0.0.0:8000


if __name__ == "__main__":
    main()