#!/usr/bin/env python3
"""
Thor Skill Runner — Lightweight skill orchestration API.

Runs on port 8091.  Provides job lifecycle API: launch, status, and artifact
retrieval.  Accepts chat requests via /api/chat and dispatches to skills or
MCP servers.
"""

import asyncio
import base64
import concurrent.futures
import importlib.util
import inspect
import json
import logging
import logging.handlers
import os
import re
import signal
import sys
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from httpx import AsyncClient, Timeout
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG_DIR = Path(os.environ.get("SKILL_RUNNER_LOG_DIR", "/home/chuck/homelab/logs/skill_runner"))
LOG_DIR.mkdir(parents=True, exist_ok=True)

# Auto-rotate log at 10MB, keep 3 backups (max 30MB on disk)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.handlers.RotatingFileHandler(
            LOG_DIR / "skill_runner.log", maxBytes=10*1024*1024, backupCount=3
        ),
    ],
)
logger = logging.getLogger("skill_runner")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ARTIFACT_ROOT = Path(os.environ.get("ARTIFACT_ROOT", "/home/chuck/data/media"))
APP_PORT = int(os.environ.get("SKILL_RUNNER_PORT", "8091"))
APP_HOST = os.environ.get("SKILL_RUNNER_HOST", "0.0.0.0")
DRY_RUN_MODE = os.environ.get("SKILL_RUNNER_DRY_RUN", "").lower() in ("true", "1", "yes")

# Public base URL for media assets (served via Caddy reverse proxy)
# All assets live under /media/files/ and are served from ARTIFACT_ROOT:
#   /media/files/generated/sunset.png
#   /media/files/demos/some-demo.html
#   /media/files/images/whatever.jpg
#   /media/files/presentations/export.pptx
PUBLIC_MEDIA_BASE = "https://siri.choukalos.com/media/files"
LAN_MEDIA_BASE = os.environ.get("LAN_MEDIA_BASE", f"http://192.168.4.54:8091/media/files")

# Presentation URLs point to Presenton's dashboard.
# The user needs to log in (cookie-based auth) to view their presentations.
# For LAN: direct access. For public: Caddy proxies with auth.
PUBLIC_PRESENTATIONS_BASE = "https://siri.choukalos.com/presentations"
LAN_PRESENTATIONS_BASE = "http://192.168.4.54:5000"


from urllib.parse import quote as url_quote

def _make_media_url(filepath: str, public: bool = True) -> str:
    """Convert a local media file path to an accessible URL.
    All media is under ARTIFACT_ROOT (/home/chuck/data/media).
    Result: /media/files/{url_encoded_relative_path}
    E.g. /home/chuck/data/media/generated/abc.png -> /media/files/generated/abc.png
         /home/chuck/data/media/demos/demo.html -> /media/files/demos/demo.html
    """
    base = PUBLIC_MEDIA_BASE if public else LAN_MEDIA_BASE
    try:
        rel = os.path.relpath(filepath, str(ARTIFACT_ROOT))
    except ValueError:
        rel = filepath  # fallback
    # URL-encode each path segment to handle spaces/special chars
    encoded = "/".join(url_quote(seg) for seg in rel.split("/"))
    return f"{base}/{encoded}"


def _make_demo_url(demo_path: str, public: bool = True) -> str:
    """Convert a demo relative path to an accessible URL.
    Demos are under ARTIFACT_ROOT/demos/.  Result: /media/files/demos/{path}
    """
    return _make_media_url(str(ARTIFACT_ROOT / "demos" / demo_path), public=public)


def _make_presentation_url(pres_id: str, action: str = "view", public: bool = True) -> str:
    """Convert a presentation ID to Presenton URL.

    Points to Presenton's root since the SPA requires cookie-based auth.
    User opens the URL, logs in, and navigates to their presentation from the dashboard.
    """
    base = PUBLIC_PRESENTATIONS_BASE if public else LAN_PRESENTATIONS_BASE
    # Presenton doesn't support direct URL navigation to specific presentations
    # (SPA routing requires the user to be logged in and navigate from the dashboard)
    return base


def _human_size(nbytes: int) -> str:
    """Convert bytes to human-readable size string."""
    for unit in ("B", "KB", "MB", "GB"):
        if abs(nbytes) < 1024.0:
            return f"{nbytes:.1f}{unit}"
        nbytes /= 1024.0
    return f"{nbytes:.1f}TB"


LITELLM_BASE_URL = os.environ.get(
    "LITELLM_BASE_URL", "http://litellm-proxy:4000"
)
LITELLM_API_KEY = os.environ.get("LITELLM_API_KEY", "")
SKILL_RUNNER_API_KEY = os.environ.get("SKILL_RUNNER_API_KEY", "")
HARNESS_URL = os.environ.get("HARNESS_URL", "http://skill-runner:8091")

# MCP server base URLs — parsed from env vars, stored for skill dispatch
MCP_SERVER_FILESYSTEM_URL = os.environ.get(
    "MCP_SERVER_FILESYSTEM_URL", "http://mcp_filesystem:8000"
)
MCP_SERVER_MEDIA_URL = os.environ.get(
    "MCP_SERVER_MEDIA_URL", "http://mcp_media:8000"
)

# Build a lookup dict for streamable-HTTP MCP calls
MCP_SERVER_URLS: dict[str, str] = {
    "mcp_filesystem": MCP_SERVER_FILESYSTEM_URL,
    "mcp_media": MCP_SERVER_MEDIA_URL,
}

# ---------------------------------------------------------------------------
# Presenton (presentation service) — parsed from env vars
# ---------------------------------------------------------------------------
PRESENTON_URL = os.environ.get("PRESENTON_URL", "http://presenton:80")
PRESENTON_USERNAME = os.environ.get("PRESENTON_AUTH_USERNAME", "presenton")
PRESENTON_PASSWORD = os.environ.get("PRESENTON_AUTH_PASSWORD", "")

# ---------------------------------------------------------------------------
# Job Model
# ---------------------------------------------------------------------------


class JobStatus(str, Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"
    awaiting_approval = "awaiting_approval"
    cancelled = "cancelled"


class Job(BaseModel):
    """Complete job record for a skill invocation."""

    job_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    skill: str
    status: JobStatus = JobStatus.pending
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    completed_at: Optional[str] = None
    summary: Optional[str] = None
    artifact_path: Optional[str] = None
    requester: Optional[str] = None
    channel: Optional[str] = None
    params: dict[str, Any] = Field(default_factory=dict)
    dry_run: bool = False
    tool_bundle: Optional[str] = None
    model_alias: Optional[str] = None
    error: Optional[str] = None
    logs: list[str] = Field(default_factory=list)

    def add_log(self, message: str) -> None:
        self.logs.append(f"[{datetime.now(timezone.utc).isoformat()}] {message}")
        logger.info("Job %s: %s", self.job_id, message)


# ---------------------------------------------------------------------------
# In-memory job store (dev only — no database)
# ---------------------------------------------------------------------------
jobs: dict[str, Job] = {}

# Thread pool for background skill execution
_exec_pool: Optional[concurrent.futures.ThreadPoolExecutor] = None


def _get_exec_pool() -> concurrent.futures.ThreadPoolExecutor:
    """Get (or create) the thread pool for background skill execution."""
    global _exec_pool
    if _exec_pool is None:
        _exec_pool = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="skill-exec")
    return _exec_pool


# Per-skill timeouts (seconds) — enforced in background threads
_SKILL_TIMEOUTS = {
    "list_demos": 30,
    "list_images": 30,
    "list_presentations": 30,
    "deep_research": 180,
    "media_generate": 120,
    "siri_chat": 60,
    "siri_ask": 30,
    "demo_browse": 30,
    "demo_workflow": 300,
    "presentation_build": 120,
    "presentation_update": 120,
    "research_brief": 60,
    "morning_brief": 60,
    "homelab_report": 60,
    "investment_brief": 60,
    "family_kb_ingest": 60,
    "code_review": 120,
    "repo_maintenance": 120,
}
_DEFAULT_TIMEOUT = 120  # fallback


def dispatch_job(skill: str, params: dict[str, Any], requester: str = "siri", channel: str = "siri") -> Job:
    """
    Create a job for the given skill and dispatch it to a background thread.

    Returns the Job object IMMEDIATELY (execution happens in background).
    The caller should store this in `jobs[]` and return the job_id to the client.
    Timeout is enforced: if the skill exceeds its limit, the job is marked failed.
    """
    job = Job(
        skill=skill,
        params=params,
        requester=requester,
        channel=channel,
    )
    job.add_log(f"Dispatching job '{skill}' to background executor")

    timeout = _SKILL_TIMEOUTS.get(skill, _DEFAULT_TIMEOUT)

    def _run_with_timeout():
        """Run the skill in a sub-future with timeout enforcement."""
        pool = _get_exec_pool()
        future = pool.submit(_execute_skill, job)
        try:
            future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            if job.status in (JobStatus.completed, JobStatus.failed):
                return  # already handled
            job.status = JobStatus.failed
            job.completed_at = datetime.now(timezone.utc).isoformat()
            job.error = f"Skill '{skill}' timed out after {timeout}s"
            job.add_log(f"TIMEOUT after {timeout}s")
            logger.warning("Job %s timed out after %ds", job.job_id, timeout)
        except Exception as exc:
            if job.status in (JobStatus.completed, JobStatus.failed):
                return
            job.status = JobStatus.failed
            job.completed_at = datetime.now(timezone.utc).isoformat()
            job.error = f"Execution error: {exc}"
            job.add_log(f"Error: {exc}")

    # Run the timeout wrapper in the pool (separate worker from _execute_skill)
    _get_exec_pool().submit(_run_with_timeout)
    return job

# ---------------------------------------------------------------------------
# Scheduler
# ----------------------------------------------------------------------------

from scheduler import SimpleScheduler  # noqa: F401 — imported for type awareness

scheduler = SimpleScheduler(
    config_path=os.environ.get(
        "SCHEDULER_CONFIG_PATH",
        os.path.join(os.path.expanduser("~"), ".thor", "scheduler.json"),
    ),
    dispatch_fn=None,  # set in lifespan handler (below)
    check_interval=60.0,
)

# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class SkillLaunchRequest(BaseModel):
    """POST /skills/{skill_name} body."""

    params: dict[str, Any] = Field(default_factory=dict)
    requester: Optional[str] = None
    channel: Optional[str] = None
    dry_run: bool = False
    tool_bundle: Optional[str] = None
    model_alias: Optional[str] = None


class SkillJobResponse(BaseModel):
    """GET /skills/jobs/{job_id} response."""

    job_id: str
    skill: str
    status: str
    created_at: str
    completed_at: Optional[str] = None
    summary: Optional[str] = None
    artifact_path: Optional[str] = None
    requester: Optional[str] = None
    channel: Optional[str] = None
    params: dict[str, Any] = Field(default_factory=dict)
    dry_run: bool = False
    tool_bundle: Optional[str] = None
    model_alias: Optional[str] = None
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Schedule Request/Response Models
# ---------------------------------------------------------------------------


class ScheduleCreateRequest(BaseModel):
    """POST /api/schedule body."""

    name: str = Field(..., description="Human-readable schedule name")
    cron: str = Field(..., description="5-field cron expression (minute hour day month weekday)")
    skill: str = Field(..., description="Skill name to dispatch")
    params: dict[str, Any] = Field(default_factory=dict, description="Parameters to pass to the skill")
    enabled: bool = True
    timezone: str = "UTC"


class ScheduleResponse(BaseModel):
    """Response model for a single schedule entry."""

    id: str
    name: str
    cron: str
    skill: str
    params: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    timezone: str = "UTC"
    last_run_at: Optional[str] = None
    next_run_at: Optional[str] = None


class ScheduleListResponse(BaseModel):
    """GET /api/schedule response."""

    schedules: list[ScheduleResponse] = Field(default_factory=list)
    total: int = 0


# ---------------------------------------------------------------------------
# Skill Registry
# ---------------------------------------------------------------------------

# Known skill names (populated from manifest files in sibling directories).
# For now, any skill_name is accepted; production will validate against manifests.
KNOWN_SKILLS = [
    "siri_ask",
    "deep_research",
    "investment_brief",
    "presentation_build",
    "code_review",
    "repo_maintenance",
    "family_kb_ingest",
    "morning_brief",
    "homelab_report",
    "demo_workflow",
    "presentation_update",
    "demo_browse",
    "research_brief",
]


# ---------------------------------------------------------------------------
# LiteLLM HTTP Client
# ---------------------------------------------------------------------------

class LiteLLMClient:
    """
    HTTP client for LiteLLM proxy.

    Supports both LLM generation via /v1/chat/completions and MCP tool
    calls via /mcp-rest/tools/call.  Skills use this client exclusively —
    they never touch MCP servers directly.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: float = 120.0,
    ) -> None:
        self.base_url = (base_url or LITELLM_BASE_URL).rstrip("/")
        self.api_key = api_key or LITELLM_API_KEY
        self._timeout = Timeout(timeout)
        self._client: Optional[AsyncClient] = None

    async def _get_client(self) -> AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = AsyncClient(
                base_url=self.base_url,
                timeout=self._timeout,
                headers=self._auth_headers(),
            )
        return self._client

    def _auth_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    # -----------------------------------------------------------------------
    # LLM generation endpoint
    # -----------------------------------------------------------------------

    async def chat_completion(
        self,
        model: str,
        messages: list[dict[str, str]],
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Call /v1/chat/completions for LLM text generation.

        Args:
            model: Model alias (e.g. 'local/qwen-coder').
            messages: List of {role, content} dicts.
            **kwargs: Additional OpenAI-compatible params (temperature, max_tokens, tools, ...).

        Returns:
            Parsed JSON response dict from LiteLLM.
        """
        payload: dict[str, Any] = {"model": model, "messages": messages}
        payload.update(kwargs)

        client = await self._get_client()
        response = await client.post("/v1/chat/completions", json=payload)
        response.raise_for_status()
        return response.json()

    # -----------------------------------------------------------------------
    # MCP tool call endpoint
    # -----------------------------------------------------------------------

    async def mcp_call(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        server_id: Optional[str] = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Call an MCP tool via direct streamable-http (delegates to ``_mcp_call_streamable``).

        Args:
            tool_name: Name of the MCP tool to call (e.g. 'search_web').
            arguments: Dict of tool arguments.
            server_id: MCP server name/ID (e.g. 'mcp_search'). Required for streamable-http path.
            **kwargs: Additional params (currently unused; retained for compatibility).

        Returns:
            Dict with ``output`` (list of content dicts) and ``is_error`` (bool).
        """
        if not server_id:
            return {
                "output": [{"type": "text", "text": "server_id is required for streamable-http MCP calls"}],
                "is_error": True,
            }
        return await self._mcp_call_streamable(server_id, tool_name, arguments)

    # -----------------------------------------------------------------------
    # Convenience: list available tools
    # -----------------------------------------------------------------------

    async def mcp_list_tools(self) -> dict[str, Any]:
        """Call /mcp-rest/tools/list to discover available MCP tools."""
        client = await self._get_client()
        response = await client.get("/mcp-rest/tools/list")
        response.raise_for_status()
        return response.json()

    # -----------------------------------------------------------------------
    # Direct Streamable-HTTP MCP tool call (bypasses LiteLLM proxy)
    # -----------------------------------------------------------------------

    def _parse_sse_event(self, body_text: str) -> dict:
        """Parse a single SSE event from text/event-stream response."""
        import json as _json
        for line in body_text.split("\n"):
            line = line.strip()
            if line.startswith("data: "):
                return _json.loads(line[6:])
            elif line.startswith("event: ") or line.startswith("id: ") or line == "":
                continue
        # If no data: line found, try parsing as raw JSON
        return _json.loads(body_text.strip())

    async def _mcp_call_streamable(
        self,
        server_id: str,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Call an MCP server directly over the streamable-http protocol (bypasses LiteLLM /mcp-rest).

        The streamable-http transport (MCP spec) works as follows:
        1. POST JSON-RPC ``initialize`` to ``{base_url}/mcp`` → server returns
           ``X-Session-Id`` header in the response.
        2. POST JSON-RPC ``notifications/initialized`` to ``{base_url}/mcp``
           with the ``X-Session-Id`` header to complete the handshake.
        3. POST JSON-RPC ``tools/call`` to ``{base_url}/mcp`` with
           ``X-Session-Id`` header.
           - 200 OK with JSON-RPC result body (direct/synchronous result).
           - 202 Accepted (server will stream response via SSE).
        4. On 202, open GET ``{base_url}/mcp`` with ``X-Session-Id`` to receive
           an SSE stream containing the JSON-RPC response message.
        5. DELETE ``{base_url}/mcp`` with ``X-Session-Id`` to clean up the session.

        Returns:
            Dict with output (list of content dicts) and is_error (bool).
        """
        name = server_id.removeprefix("mcp_")
        # Prefer parsed MCP_SERVER_URLS dict, then env var, then default
        base_url = MCP_SERVER_URLS.get(
            server_id,
            os.environ.get(f"MCP_SERVER_{name.upper()}_URL", f"http://{server_id}:8000"),
        ).rstrip("/")

        logger.info("Streamable HTTP MCP call: server=%s base_url=%s tool=%s",
                     server_id, base_url, tool_name)

        initialize_request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": 2,
                "capabilities": {},
                "clientInfo": {"name": "skill-runner", "version": "0.1.0"},
            },
        }
        initialized_notification = {"jsonrpc": "2.0", "method": "notifications/initialized"}
        jsonrpc_request = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        }

        mcp_url = f"{base_url}/mcp"
        session_id: Optional[str] = None
        parse_error_holder: list[Optional[str]] = [None]
        result_content: list[dict[str, Any]] = []
        structured_result_holder: list[Optional[dict[str, Any]]] = [None]
        is_error = False

        async with AsyncClient(timeout=Timeout(120.0), headers={"Accept": "application/json, text/event-stream"}) as client:
            # ---- Step 1: POST initialize, get session ID ----
            try:
                init_resp = await client.post(mcp_url, json=initialize_request, timeout=30.0)
                init_resp.raise_for_status()
                # Handle both JSON and SSE responses
                ct = init_resp.headers.get("content-type", "")
                if "text/event-stream" in ct:
                    # Parse SSE event to extract JSON payload
                    body_text = init_resp.text
                    init_body = self._parse_sse_event(body_text)
                else:
                    init_body = init_resp.json()
                # Support both X-Session-Id (old spec) and mcp-session-id (new spec)
                session_id = init_resp.headers.get("X-Session-Id") or init_resp.headers.get("mcp-session-id")
                if not session_id:
                    parse_error_holder[0] = "initialize response missing session ID header"
                    return {"output": [{"type": "text", "text": parse_error_holder[0]}], "is_error": True}

                if "error" in init_body:
                    parse_error_holder[0] = f"MCP init error: {init_body['error']}"
                    return {"output": [{"type": "text", "text": parse_error_holder[0]}], "is_error": True}

                server_info = init_body.get("result", {}).get("serverInfo", {})
                logger.info("MCP initialized (server: %s, session: %s)",
                            server_info.get("name", "unknown"), session_id)
            except Exception as exc:
                parse_error_holder[0] = f"MCP initialize failed: {exc}"
                return {"output": [{"type": "text", "text": parse_error_holder[0]}], "is_error": True}

            # ---- Step 2: POST notifications/initialized ----
            try:
                init_ack = await client.post(
                    mcp_url,
                    json=initialized_notification,
                    headers={"Accept": "application/json, text/event-stream", "X-Session-Id": session_id or "", "mcp-session-id": session_id or ""},
                    timeout=15.0,
                )
                init_ack.raise_for_status()
                logger.info("MCP initialized notification sent")
            except Exception as exc:
                parse_error_holder[0] = f"MCP initialized notification failed: {exc}"
                # Attempt cleanup and return
                try:
                    await client.delete(mcp_url, headers={"Accept": "application/json, text/event-stream", "X-Session-Id": session_id or "", "mcp-session-id": session_id or ""}, timeout=10.0)
                except Exception:
                    pass
                return {"output": [{"type": "text", "text": parse_error_holder[0]}], "is_error": True}

            # ---- Step 3: POST tools/call ----
            try:
                tool_resp = await client.post(
                    mcp_url,
                    json=jsonrpc_request,
                    headers={"Accept": "application/json, text/event-stream", "X-Session-Id": session_id or "", "mcp-session-id": session_id or ""},
                    timeout=60.0,
                )
            except Exception as exc:
                parse_error_holder[0] = f"tools/call POST failed: {exc}"
                # Attempt cleanup
                try:
                    await client.delete(mcp_url, headers={"Accept": "application/json, text/event-stream", "X-Session-Id": session_id or "", "mcp-session-id": session_id or ""}, timeout=10.0)
                except Exception:
                    pass
                return {"output": [{"type": "text", "text": parse_error_holder[0]}], "is_error": True}

            logger.info("tools/call POST returned status %d", tool_resp.status_code)

            # ---- Step 3a: 200 OK — direct JSON-RPC result or SSE ----
            if tool_resp.status_code == 200:
                ct = tool_resp.headers.get("content-type", "")
                if "text/event-stream" in ct:
                    jsonrpc_response = self._parse_sse_event(tool_resp.text)
                else:
                    try:
                        jsonrpc_response = tool_resp.json()
                    except Exception as exc:
                        parse_error_holder[0] = f"Failed to parse tool response JSON: {exc}"
                        # Attempt cleanup
                        try:
                            await client.delete(mcp_url, headers={"Accept": "application/json, text/event-stream", "X-Session-Id": session_id or "", "mcp-session-id": session_id or ""}, timeout=10.0)
                        except Exception:
                            pass
                        return {"output": [{"type": "text", "text": parse_error_holder[0]}], "is_error": True}

                self._parse_tool_response(jsonrpc_response, result_content,
                                           parse_error_holder, structured_result_holder)

                if parse_error_holder[0]:
                    error = parse_error_holder[0]
                    try:
                        await client.delete(mcp_url, headers={"Accept": "application/json, text/event-stream", "X-Session-Id": session_id or "", "mcp-session-id": session_id or ""}, timeout=10.0)
                    except Exception:
                        pass
                    return {"output": [{"type": "text", "text": error}], "is_error": True}

                # Continue to step 5 (cleanup)
                await self._cleanup_session(client, mcp_url, session_id)
                return self._build_result(result_content, structured_result_holder[0], is_error,
                                           server_id, tool_name)

            # ---- Step 3b: 202 Accepted — read SSE stream for response ----
            elif tool_resp.status_code == 202:
                logger.info("Got 202 Accepted, reading SSE stream for response")
                try:
                    sse_resp = await client.send(
                        client.build_request("GET", mcp_url,
                                              headers={"X-Session-Id": session_id}),
                        stream=True,
                    )
                    sse_resp.raise_for_status()

                    response_ready = asyncio.Event()

                    async def sse_reader_task():
                        try:
                            event_type: Optional[str] = None
                            async for raw_line in sse_resp.aiter_lines():
                                line = raw_line.strip()
                                if not line:
                                    continue
                                if line.startswith("event: "):
                                    event_type = line[7:].strip()
                                elif line.startswith("data: "):
                                    data_value = line[6:].strip()
                                    if event_type == "message" and data_value:
                                        try:
                                            jsonrpc_response = json.loads(data_value)
                                            logger.info("MCP tool response via streamable-http SSE stream: keys=%s has_error=%s has_result=%s",
                                                        list(jsonrpc_response.keys()),
                                                        "error" in jsonrpc_response,
                                                        "result" in jsonrpc_response)
                                        except json.JSONDecodeError:
                                            parse_error_holder[0] = f"Failed to parse SSE tool response: {data_value}"
                                            response_ready.set()
                                            return

                                        if "error" in jsonrpc_response and "result" not in jsonrpc_response:
                                            is_error = True
                                            result_content.append(
                                                {"type": "text", "text": f"MCP error: {jsonrpc_response['error']}"}
                                            )
                                        elif "result" in jsonrpc_response:
                                            result = jsonrpc_response["result"]
                                            structured = result.get("structuredContent")
                                            if structured:
                                                structured_result_holder[0] = structured
                                                is_error = False
                                            else:
                                                content_items = result.get("content", [])
                                                result_content.extend(content_items)
                                                is_error = result.get("isError", False) and not content_items
                                        response_ready.set()
                                        return
                        except Exception as exc:
                            logger.error("SSE reader error: %s", exc)
                            parse_error_holder[0] = f"SSE reader error: {exc}"
                            response_ready.set()

                    reader_task = asyncio.create_task(sse_reader_task())
                    try:
                        await asyncio.wait_for(response_ready.wait(), timeout=60.0)
                    except asyncio.TimeoutError:
                        parse_error_holder[0] = "Timeout waiting for SSE response after 202"
                    reader_task.cancel()
                    try:
                        await asyncio.gather(reader_task, return_exceptions=True)
                    except Exception:
                        pass
                    try:
                        await sse_resp.aclose()
                    except Exception:
                        pass

                except Exception as exc:
                    parse_error_holder[0] = f"SSE stream after 202 failed: {exc}"

                # ---- Step 5: cleanup ----
                await self._cleanup_session(client, mcp_url, session_id)

                if parse_error_holder[0]:
                    return {"output": [{"type": "text", "text": parse_error_holder[0]}], "is_error": True}

                return self._build_result(result_content, structured_result_holder[0], is_error,
                                           server_id, tool_name)

            else:
                parse_error_holder[0] = f"Unexpected status {tool_resp.status_code} from tools/call"
                await self._cleanup_session(client, mcp_url, session_id)
                return {"output": [{"type": "text", "text": parse_error_holder[0]}], "is_error": True}

    # -----------------------------------------------------------------------
    # Streamable-HTTP helpers
    # -----------------------------------------------------------------------

    async def _cleanup_session(
        self, client: AsyncClient, mcp_url: str, session_id: Optional[str]
    ) -> None:
        """DELETE the MCP session to clean up server-side resources."""
        if not session_id:
            return
        try:
            del_resp = await client.delete(
                mcp_url,
                headers={"X-Session-Id": session_id},
                timeout=10.0,
            )
            logger.debug("Session cleanup: status=%d", del_resp.status_code)
        except Exception as exc:
            logger.warning("Session cleanup failed: %s", exc)

    @staticmethod
    def _parse_tool_response(
        jsonrpc_response: dict,
        result_content: list[dict[str, Any]],
        parse_error_holder: list[Optional[str]],
        structured_result_holder: list[Optional[dict]],
    ) -> None:
        """Parse a JSON-RPC tool response into result_content / structured_result."""
        if "error" in jsonrpc_response and "result" not in jsonrpc_response:
            parse_error_holder[0] = f"MCP error: {jsonrpc_response['error']}"
            result_content.append({"type": "text", "text": f"MCP error: {jsonrpc_response['error']}"})
        elif "result" in jsonrpc_response:
            result = jsonrpc_response["result"]
            structured = result.get("structuredContent")
            if structured:
                structured_result_holder[0] = structured
            else:
                content_items = result.get("content", [])
                result_content.extend(content_items)

    @staticmethod
    def _build_result(
        result_content: list[dict[str, Any]],
        structured_result: Optional[dict[str, Any]],
        is_error: bool,
        server_id: str,
        tool_name: str,
    ) -> dict[str, Any]:
        """Build the final result dict from parsed content and structured result."""
        parse_error: Optional[str] = None
        if not result_content and not structured_result and not is_error:
            parse_error = "No response received from MCP server via Streamable HTTP"
            logger.warning("Streamable HTTP call returned no data (server=%s, tool=%s)",
                           server_id, tool_name)
            return {"output": [{"type": "text", "text": parse_error}], "is_error": True}

        if structured_result is not None:
            sc = structured_result
            if isinstance(sc, dict):
                for key in ("result", "matches", "data", "items"):
                    if key in sc:
                        sc = dict(sc)
                        sc["results"] = sc[key]
                        break
                if "results" not in sc:
                    sc = {"results": sc}
            logger.info("Streamable HTTP call returning structured result (server=%s, tool=%s, results_count=%d)",
                        server_id, tool_name, len(sc.get("results", [])))
            return {
                "result": sc,
                "output": result_content if result_content else [{"_structured": sc}],
                "is_error": is_error,
            }
        if result_content:
            logger.info("Streamable HTTP call returning content result (server=%s, tool=%s, items=%d)",
                        server_id, tool_name, len(result_content))
            return {"output": result_content, "is_error": is_error}
        return {"output": [], "is_error": is_error}


# ---------------------------------------------------------------------------
# Sync Wrapper for LiteLLMClient (used by synchronous skill code)
# ---------------------------------------------------------------------------


class _SyncLiteLLMWrapper:
    """
    Synchronous wrapper around the async ``LiteLLMClient``.

    Each call creates a fresh LiteLLMClient with its own event loop in a
    dedicated thread. This avoids the "Event loop is closed" error when
    multiple calls happen in sequence (e.g. multi-round tool calling).
    """

    # Shared config from the original client
    _base_url: str = ""
    _api_key: str = ""

    # Reusable thread pool for async execution
    _thread_pool: concurrent.futures.ThreadPoolExecutor = None

    def __init__(self, client: LiteLLMClient) -> None:
        self._base_url = client.base_url
        self._api_key = client.api_key

    @property
    def base_url(self) -> str:
        return self._base_url

    def _get_thread_pool(self) -> concurrent.futures.ThreadPoolExecutor:
        if self._thread_pool is None:
            self._thread_pool = concurrent.futures.ThreadPoolExecutor(max_workers=4)
        return self._thread_pool

    def _run_in_thread(self, coro_factory) -> Any:
        """
        Run an async coroutine in a dedicated thread with a fresh event loop.

        coro_factory is a callable that takes a LiteLLMClient and returns
        a coroutine (e.g. lambda c: c.chat_completion(model, messages, **kw)).
        """
        def _run():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            local_client = LiteLLMClient(base_url=self._base_url, api_key=self._api_key)
            try:
                coro = coro_factory(local_client)
                return loop.run_until_complete(coro)
            finally:
                loop.run_until_complete(local_client.close())
                loop.close()
                asyncio.set_event_loop(None)

        return self._get_thread_pool().submit(_run).result()

    def chat_completion(
        self,
        model: str,
        messages: list[dict[str, str]],
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Sync wrapper for ``LiteLLMClient.chat_completion``."""
        return self._run_in_thread(
            lambda c, m=model, msg=messages, kw=kwargs: c.chat_completion(m, msg, **kw)
        )

    def mcp_call(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        server_id: Optional[str] = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Sync wrapper for ``LiteLLMClient.mcp_call``."""
        return self._run_in_thread(
            lambda c, t=tool_name, a=arguments, s=server_id, kw=kwargs:
            c.mcp_call(t, a, server_id=s, **kw)
        )


# ---------------------------------------------------------------------------
# Skill Execution
# ---------------------------------------------------------------------------

def _find_skill_module(skill_name: str) -> Optional[Path]:
    """Locate a skill's __init__.py or run.py in the skills/ directory."""
    # In container: skills mounted at /app/skills/
    # In dev on laptop: skills are parent of runner dir
    candidates = [
        Path("/app/skills"),                           # container mode
        Path(__file__).resolve().parent.parent,       # dev mode (laptop)
    ]
    for base in candidates:
        skill_dir = base / skill_name
        for entry in ("run.py", "skill.py", "__init__.py"):
            p = skill_dir / entry
            if p.is_file():
                return p
    return None


def _execute_skill(job: Job) -> None:
    """
    Execute a skill job.

    In skeleton form this logs the job details and marks it completed.
    Phase 9 will add real skill execution logic here.
    """
    job.status = JobStatus.running
    job.add_log(f"Executing skill '{job.skill}'")

    if job.dry_run:
        job.add_log("DRY RUN — skipping actual execution")
        job.add_log(f"Params: {job.params}")
        job.add_log(f"Tool bundle: {job.tool_bundle or 'none'}")
        job.add_log(f"Model alias: {job.model_alias or 'none'}")
        job.status = JobStatus.completed
        job.completed_at = datetime.now(timezone.utc).isoformat()
        job.summary = "Dry run completed — no action taken."
        logger.info("DRY RUN job %s completed.", job.job_id)
        return

    # Check approval gate
    if job.status == JobStatus.awaiting_approval:
        job.add_log("Approval gate — job paused awaiting manual approval")
        return

    # Find and execute the skill module
    skill_path = _find_skill_module(job.skill)
    if skill_path is None:
        job.status = JobStatus.failed
        job.completed_at = datetime.now(timezone.utc).isoformat()
        job.error = f"Skill '{job.skill}' module not found"
        job.add_log(job.error)
        logger.error("Skill not found: %s", job.skill)
        return

    job.add_log(f"Skill module found at: {skill_path}")

    # Build LiteLLM client and sync wrapper for the job
    litellm_client = LiteLLMClient()
    sync_client = _SyncLiteLLMWrapper(litellm_client)
    job.add_log(
        f"LiteLLM client initialised: base_url={litellm_client.base_url}"
    )

    try:
        # Dynamically import the skill module using importlib.util
        spec = importlib.util.spec_from_file_location(
            f"skill_{job.skill}", skill_path
        )
        if spec is None or spec.loader is None:
            raise ImportError(
                f"Could not load module spec for {skill_path}"
            )
        skill_module = importlib.util.module_from_spec(spec)

        # Add the skill's directory and parent to sys.path so relative imports work
        skill_dir = str(skill_path.parent)
        skills_root = str(skill_path.parent.parent)
        for path_dir in [skill_dir, skills_root]:
            if path_dir not in sys.path:
                sys.path.insert(0, path_dir)

        spec.loader.exec_module(skill_module)
        job.add_log("Skill module imported successfully")

        # Find the run() function
        if not hasattr(skill_module, "run"):
            raise ImportError(
                f"Skill module '{job.skill}' has no 'run()' function"
            )

        # Determine if the run() function accepts a client parameter
        sig = inspect.signature(skill_module.run)
        param_names = list(sig.parameters.keys())
        run_kwargs: dict[str, Any] = {"params": job.params, "job": job}
        # Pass client if the signature accepts it (litellm_client or client)
        for client_param_name in ("litellm_client", "client"):
            if client_param_name in param_names:
                run_kwargs[client_param_name] = sync_client
                job.add_log(f"Passing sync client as '{client_param_name}'")
                break

        # Execute the skill
        job.add_log("Invoking skill.run()...")
        result = skill_module.run(**run_kwargs)

        # Validate result is a dict
        if not isinstance(result, dict):
            raise ValueError(
                f"Skill '{job.skill}' run() returned {type(result).__name__}, expected dict"
            )

        job.add_log(f"Skill.run() returned: {list(result.keys())}")

        # Map skill result dict to job fields
        if "error" in result:
            job.error = result["error"]
            job.add_log(f"Skill reported error: {job.error}")

        if "summary" in result:
            job.summary = result["summary"]
            job.add_log(f"Skill summary: {job.summary[:200]}")
        elif "answer" in result:
            job.summary = result["answer"]
            job.add_log(f"Skill answer (used as summary): {job.summary[:200]}")

        if "artifact_path" in result and result["artifact_path"]:
            job.artifact_path = result["artifact_path"]
            job.add_log(f"Artifact path from skill: {job.artifact_path}")

        # Merge extra result keys (report, sources, etc.) into job params for retrieval
        extra_keys = {"report", "sources", "answer"}
        for key in extra_keys:
            if key in result and key != "summary":
                job.params[f"_result_{key}"] = result[key]
                job.add_log(f"Merged result key '{key}' into job params")

        # Determine final status
        if job.error:
            job.status = JobStatus.failed
        else:
            job.status = JobStatus.completed

    except ImportError as exc:
        job.status = JobStatus.failed
        job.error = f"Failed to import skill module: {exc}"
        job.add_log(f"ImportError: {exc}")
        logger.error("Skill import error: %s", exc)

    except Exception as exc:
        job.status = JobStatus.failed
        job.error = str(exc)
        job.add_log(f"Execution error: {exc}")
        logger.error("Skill execution error: %s", exc)

    # Finalize completion timestamp
    if job.status in (JobStatus.completed, JobStatus.failed):
        job.completed_at = datetime.now(timezone.utc).isoformat()
        if job.status == JobStatus.completed:
            logger.info("Job %s completed successfully.", job.job_id)
        else:
            logger.info("Job %s failed: %s", job.job_id, job.error)

    # Compute artifact path if not already set by the skill
    if (
        job.status == JobStatus.completed
        and not job.artifact_path
        and job.skill in KNOWN_SKILLS
    ):
        artifact_subdir = _artifact_subdir_for_skill(job.skill)
        if artifact_subdir:
            slug = job.params.get("query", job.params.get("topic", "output"))
            slug = _slugify(slug)
            ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
            ext = "md" if job.skill != "presentation_build" else "json"
            art_name = f"{job.skill}_{ts}_{slug}.{ext}"
            job.artifact_path = str(ARTIFACT_ROOT / artifact_subdir / art_name)
            job.add_log(f"Artifact path: {job.artifact_path}")


def _artifact_subdir_for_skill(skill: str) -> Optional[str]:
    mapping = {
        "deep_research": "research_reports",
        "investment_brief": "investment_briefs",
        "presentation_build": "presentations",
        "code_review": "code_reviews",
        "repo_maintenance": "code_reviews",
        "morning_brief": "homelab_reports",
        "homelab_report": "homelab_reports",
        "siri_ask": "siri_outputs",
        "family_kb_ingest": None,  # ingests into Qdrant, no file artifact
        "demo_workflow": "presentations",
    }
    return mapping.get(skill)


def _slugify(value: str) -> str:
    return "".join(c if c.isalnum() or c == "-" else "-" for c in value[:50]).strip("-")


# ---------------------------------------------------------------------------
# FastAPI Application — with lifespan for scheduler lifecycle
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manage the scheduler background thread lifecycle.

    On startup: load config and start the scheduler thread.
    On shutdown: gracefully stop the scheduler thread.
    """
    # --- Startup ---
    scheduler.dispatch_fn = _schedule_dispatch_fn
    num_loaded = scheduler.load_config()
    logger.info(
        "Scheduler loaded %d schedule(s), starting background thread.",
        num_loaded,
    )
    scheduler.start()
    logger.info("Thor Skill Runner startup complete.")

    yield

    # --- Shutdown ---
    logger.info("Thor Skill Runner shutting down — stopping scheduler.")
    scheduler.stop()
    logger.info("Shutdown complete.")


app = FastAPI(
    title="Thor Skill Runner",
    description="Skill orchestration API — runs on dev port 8091.",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "port": APP_PORT, "jobs_total": len(jobs)}


# ---------------------------------------------------------------------------
# Static file serving (for Caddy reverse proxy)
# All assets live under ARTIFACT_ROOT (/home/chuck/data/media)
# so /media/files/{filepath:path} serves the whole tree:
#   /media/files/generated/gen_sunset.png
#   /media/files/demos/some-demo.html
#   /media/files/presentations/whatever.pptx
#   /media/files/images/something.jpg
# etc.
# ---------------------------------------------------------------------------

from fastapi.responses import FileResponse
import mimetypes
from urllib.parse import unquote as url_unquote


@app.get("/media/files/{filepath:path}")
def serve_media_file(filepath: str):
    """Serve any file under ARTIFACT_ROOT. Path is relative to /home/chuck/data/media."""
    # FastAPI doesn't auto-decode path params for :path type
    filepath = url_unquote(filepath)
    full_path = ARTIFACT_ROOT / filepath
    if not full_path.is_file():
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"File not found: {filepath}")
    content_type = mimetypes.guess_type(str(full_path))[0] or "application/octet-stream"
    return FileResponse(str(full_path), media_type=content_type)


# NOTE: Presenton SPA uses cookie-based auth (login form), so we can't proxy it.
# Presentation URLs point to Presenton directly. Users log in to view their decks.



# ---------------------------------------------------------------------------
# Chat Gateway Models
# ---------------------------------------------------------------------------


class ChatRequest(BaseModel):
    text: str = Field(..., description="User query or command")
    intent: Optional[str] = Field(None, description="Override intent detection")
    model: Optional[str] = Field(None, description="Model alias override (default: matrix-gemma4-moe).")


class ChatResponse(BaseModel):
    speak: str = ""
    display: str = ""
    job_id: Optional[str] = None
    links: list[str] = []
    media: Optional[str] = None
    data: dict = {}


# ---------------------------------------------------------------------------
# Chat Gateway Helpers
# ---------------------------------------------------------------------------


_INTENT_SKILL_MAP = {
    "deep-research": "deep_research",
    "build-presentation": "presentation_build",
    "ask-siri": "siri_ask",
    "siri-chat": "siri_chat",
    "update-presentation": "presentation_update",
    "create-demo": "demo_workflow",
    "find-demos": "demo_browse",
    "research-brief": "research_brief",
    "investment-brief": "investment_brief",
    "morning-brief": "morning_brief",
    "media-generate": "mcp_media",
    "list-images": "list_images",
}


def _detect_intent(text: str, override: Optional[str]) -> str:
    """Detect intent from user text."""
    if override:
        return override
    text_lower = text.lower()
    # --- update-presentation: match 'update' + 'presentation' anywhere (not just adjacent) ---
    if "update" in text_lower and any(k in text_lower for k in ("presentation", "deck", "slides")):
        return "update-presentation"
    # --- list-demos: explicit list intent (must match BEFORE find-demos / generic demo) ---
    if any(k in text_lower for k in ("list demo", "list demos", "list my demos")):
        return "list-demos"
    # --- find-demos ---
    if any(k in text_lower for k in ("find demo", "find demos", "browse demos", "search demo", "search demos", "look for demo")):
        return "find-demos"
    # --- list-presentations ---
    if any(k in text_lower for k in ("list presentation", "list presentations", "list my presentations", "list my deck")):
        return "list-presentations"
    # --- list-images ---
    if any(k in text_lower for k in ("list image", "list images", "list my images", "list my photos", "list my pics", "show my images", "show my photos", "what images", "list generated image")):
        return "list-images"
    # --- investment-brief: must match before morning-brief and research-brief ---
    if any(k in text_lower for k in ("investment brief", "investment-brief", "stock brief", "stock-brief", "market brief", "market-brief")):
        return "investment-brief"
    # --- morning-brief: must match before research-brief ---
    if any(k in text_lower for k in ("morning brief", "morning-brief", "daily brief", "daily-brief", "daily summary", "morning briefing")):
        return "morning-brief"
    if any(k in text_lower for k in ("research brief", "research summary", "brief research")):
        return "research-brief"
    if any(k in text_lower for k in ("generate image", "create image", "image generate", "media generate", "generate media", "make image", "create media", "draw image", "render image")):
        return "media-generate"
    if re.search(r"(?:generate|create|make|draw|render)\s+(?:an\s+)?image", text_lower) or \
       re.search(r"(?:create|generate)\s+(?:an\s+)?media", text_lower):
        return "media-generate"
    if any(k in text_lower for k in ("deep", "research", "deep research")):
        return "deep-research"
    if any(k in text_lower for k in ("present", "slide", "deck")):
        return "build-presentation"
    if any(k in text_lower for k in ("siri ask", "siri-chat", "siri chat")):
        return "siri-chat"
    if any(k in text_lower for k in ("create demo", "create-demo", "new demo")):
        return "create-demo"
    return "chat"


def _truncate_for_speak(text: str, max_chars: int = 250) -> str:
    """Truncate text for voice playback."""
    text = (text or "").strip()
    if len(text) <= max_chars:
        return text
    sentences = text.split(". ")
    result_parts = []
    result_len = 0
    for s in sentences:
        if result_len + len(s) + 2 > max_chars:
            break
        result_parts.append(s)
        result_len += len(s) + 2
    return ". ".join(result_parts) + ("." if result_parts else "")


def _handle_update_presentation(text: str) -> ChatResponse:
    """
    Handler for 'update-presentation' intent.
    Dispatches to the presentation_update skill in a background thread.
    """
    job = dispatch_job(
        "presentation_update",
        params={"query": text, "instructions": text},
    )
    jobs[job.job_id] = job
    logger.info("Job %s dispatched (async) for skill 'presentation_update'.", job.job_id)
    return ChatResponse(
        speak="I've started updating your presentation. This typically takes a few minutes.",
        display=f"Job {job.job_id} started for presentation update.",
        job_id=job.job_id,
        data={"skill": "presentation_update", "intent": "update-presentation"},
    )


def _handle_find_demos(text: str) -> ChatResponse:
    """
    Handler for 'find-demos' / 'list-demos' intent.
    Dispatches to the demo_browse skill in a background thread.
    """
    job = dispatch_job(
        "demo_browse",
        params={"query": text},
    )
    jobs[job.job_id] = job
    logger.info("Job %s dispatched (async) for skill 'demo_browse'.", job.job_id)
    return ChatResponse(
        speak="I'm searching for demos matching your query. Results will be ready shortly.",
        display=f"Job {job.job_id} started for demo search.",
        job_id=job.job_id,
        data={"skill": "demo_browse", "intent": "find-demos"},
    )


def _handle_list_demos(text: str) -> ChatResponse:
    """
    Handler for 'list-demos' intent — list ALL demos (no keyword filter).
    Dispatches to the demo_browse skill in a background thread with a wildcard query.
    """
    job = dispatch_job(
        "demo_browse",
        params={"query": "*"},  # wildcard = return all
    )
    jobs[job.job_id] = job
    logger.info("Job %s dispatched (async) for skill 'demo_browse' (list all).", job.job_id)
    return ChatResponse(
        speak="I'm listing your demos. Results will be ready shortly.",
        display=f"Job {job.job_id} started for demo listing.",
        job_id=job.job_id,
        data={"skill": "demo_browse", "intent": "list-demos"},
    )


def _handle_research_brief(text: str) -> ChatResponse:
    """
    Handler for 'research-brief' intent.
    Dispatches to the research_brief skill in a background thread.
    """
    job = dispatch_job(
        "research_brief",
        params={"topic": text},
    )
    jobs[job.job_id] = job
    logger.info("Job %s dispatched (async) for skill 'research_brief'.", job.job_id)
    return ChatResponse(
        speak="I'm running a research brief on that topic. This may take a minute or two.",
        display=f"Job {job.job_id} started for research brief.",
        job_id=job.job_id,
        data={"skill": "research_brief", "intent": "research-brief"},
    )


async def _handle_media_generate(text: str) -> ChatResponse:
    """
    Handler for 'media-generate' intent.
    Calls mcp_media.generate_image directly via the MCP streamable-http transport
    and returns a structured response containing the generated image path.
    """
    client = LiteLLMClient()
    try:
        result = await client.mcp_call(
            tool_name="generate_image",
            arguments={"prompt": text},
            server_id="mcp_media",
        )

        # Extract the image path from the MCP response
        image_url = None
        error_msg = None
        if result.get("is_error"):
            error_msg = "Image generation failed."
            for item in result.get("output", []):
                if isinstance(item, dict) and item.get("type") == "text":
                    error_msg = item.get("text", error_msg)
                    break
            logger.error("media-generate error: %s", error_msg)
            return ChatResponse(
                speak="I couldn't generate an image. Please try again.",
                display=f"Error: {error_msg}",
                data={"skill": "mcp_media", "intent": "media-generate", "error": error_msg},
            )

        # Try structured result first, then output content
        if result.get("result"):
            structured = result["result"]
            # The _build_result wrapper nests the actual tool result under "results"
            tool_result = structured.get("results", structured)
            if isinstance(tool_result, dict):
                # mcp_media.generate_image returns saved_paths (list of file paths)
                saved_paths = tool_result.get("saved_paths", [])
                if saved_paths:
                    # Filter out error paths
                    for p in saved_paths:
                        if p and not p.startswith("ERROR"):
                            image_url = p
                            break
                    else:
                        image_url = None
                if not image_url:
                    image_url = (
                        tool_result.get("file_path")
                        or tool_result.get("path")
                        or tool_result.get("output_path")
                        or tool_result.get("url")
                    )
            elif not image_url:
                image_url = (
                    structured.get("file_path")
                    or structured.get("path")
                    or structured.get("output_path")
                    or structured.get("url")
                )
        if not image_url:
            for item in result.get("output", []):
                if isinstance(item, dict):
                    if item.get("type") == "image":
                        image_url = item.get("uri") or item.get("url")
                        break
                    elif item.get("type") == "text":
                        text_val = item.get("text")
                        if isinstance(text_val, str) and text_val.startswith("{"):
                            # The MCP library may stringify the tool result dict
                            try:
                                parsed = json.loads(text_val)
                                if isinstance(parsed, dict):
                                    # Check for saved_paths (mcp_media)
                                    sp = parsed.get("saved_paths", [])
                                    if sp:
                                        for p in sp:
                                            if p and not p.startswith("ERROR"):
                                                image_url = p
                                                break
                                        if image_url:
                                            break
                                    # Check other common path keys
                                    if not image_url:
                                        image_url = (
                                            parsed.get("file_path")
                                            or parsed.get("path")
                                            or parsed.get("output_path")
                                            or parsed.get("url")
                                        )
                                        if image_url:
                                            break
                            except (json.JSONDecodeError, TypeError):
                                pass
                        if not image_url:
                            image_url = text_val
                        break

        job = Job(
            skill="mcp_media",
            params={"query": text, "prompt": text},
            requester="siri",
            channel="siri",
        )
        job.add_log("Intent 'media-generate' dispatched to MCP server 'mcp_media'")
        if image_url:
            job.artifact_path = image_url
            job.add_log(f"Image generated: {image_url}")
        job.status = JobStatus.completed
        job.completed_at = datetime.now(timezone.utc).isoformat()
        job.summary = f"Image generated from prompt: {text}"
        jobs[job.job_id] = job
        logger.info("Job %s completed for media generation. image=%s", job.job_id, image_url)

        # Convert local file path to accessible URL (public by default)
        media_url = None
        if image_url and image_url.startswith("/"):
            # It's a local file path — convert to URL
            try:
                media_url = _make_media_url(image_url, public=True)
            except Exception:
                media_url = image_url
        elif image_url:
            media_url = image_url

        speak = "I've generated an image for you."
        if media_url:
            speak = f"I've generated an image for you. You can view it here: {media_url}"

        return ChatResponse(
            speak=speak,
            display=f"Image generated from prompt: {text}",
            job_id=job.job_id,
            media=media_url,
            data={"skill": "mcp_media", "intent": "media-generate", "image_url": media_url},
        )
    except Exception as exc:
        logger.error("media-generate exception: %s", exc)
        return ChatResponse(
            speak="I encountered an error generating the image. Please try again.",
            display=f"Error: {exc}",
            data={"skill": "mcp_media", "intent": "media-generate", "error": str(exc)},
        )
    finally:
        await client.close()


def _scan_demos(query: str) -> ChatResponse:
    """Scan the demos page for matching demos."""
    import subprocess
    try:
        result = subprocess.run(
            ["curl", "-s", "-m", "5", "http://open-webui:8080/demos"],
            capture_output=True, text=True,
        )
        content = result.stdout[:2000]
        display = f"Demos page content:\n{content}"
        return ChatResponse(
            speak="I checked the demos page. Here's what I found.",
            display=display,
            data={"query": query},
        )
    except Exception as e:
        return ChatResponse(
            speak="I couldn't reach the demos page.",
            display=f"Error: {e}",
        )


def _scan_presentations(query: str) -> ChatResponse:
    """
    List presentations via the Presenton API.

    Calls GET /api/v1/ppt/presentations with HTTP Basic auth,
    optionally filtering by title if a query is provided.

    Uses httpx.AsyncClient internally so it can run in a background thread
    without blocking the FastAPI event loop.
    """
    import base64

    credentials = f"{PRESENTON_USERNAME}:{PRESENTON_PASSWORD}"
    encoded = base64.b64encode(credentials.encode("utf-8")).decode("utf-8")
    auth_header = {"Authorization": f"Basic {encoded}", "Accept": "application/json"}

    url = f"{PRESENTON_URL}/api/v1/ppt/presentation/all"

    # Use a short timeout (5s) — Presenton should respond quickly
    import httpx
    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.get(url, headers=auth_header)
            resp.raise_for_status()
            body = resp.json()
    except httpx.HTTPStatusError as exc:
        body = {}
        try:
            body = exc.response.json()
        except Exception:
            pass
        return ChatResponse(
            speak=f"Presenton returned an error: HTTP {exc.response.status_code}.",
            display=f"Presenton error HTTP {exc.response.status_code}: {json.dumps(body)}",
            data={"query": query, "error": str(exc)},
        )
    except httpx.ConnectError as exc:
        return ChatResponse(
            speak="I couldn't reach Presenton to list presentations.",
            display=f"Cannot reach Presenton at {PRESENTON_URL}: {exc}",
            data={"query": query, "error": str(exc)},
        )
    except Exception as exc:
        return ChatResponse(
            speak="I encountered an error listing presentations.",
            display=f"Error: {exc}",
            data={"query": query, "error": str(exc)},
        )

    # Presenton returns a list of PresentationWithSlides objects
    presentations: list[dict] = []
    if isinstance(body, list):
        presentations = body
    elif isinstance(body, dict):
        presentations = body.get("presentations", body.get("items", []))

    # Optional: filter by query keywords (title or content match)
    _PRESENTATION_LIST_ALL = [
        "list my presentations", "list presentations", "list all presentations",
        "show my presentations", "show presentations", "show all presentations",
        "my presentations", "all presentations",
    ]
    q_lower = query.lower().strip() if query else ""
    # Filter only if the query doesn't match a list-all pattern
    has_filter = bool(q_lower and q_lower not in _PRESENTATION_LIST_ALL)
    if has_filter:
        matched = [
            p for p in presentations
            if q_lower in (p.get("title", "").lower())
            or q_lower in (p.get("content", "").lower())
        ]
        if matched:
            presentations = matched

    # Build a human-readable summary
    if not presentations:
        return ChatResponse(
            speak="No presentations found."
            if not has_filter
            else f"No presentations matching '{query}'.",
            display="No presentations found." if not has_filter else f"No presentations matching '{query}'.",
            data={"query": query, "count": 0, "presentations": []},
        )

    # Presenton returns fields: id (UUID), title, content, n_slides, language,
    # created_at, updated_at, tone, verbosity, slides, theme, fonts
    lines = []
    for p in presentations:
        title = p.get("title") or f"Presentation {str(p.get('id', ''))[:8]}"
        slides = p.get("n_slides", "?")
        tone = p.get("tone") or "default"
        language = p.get("language") or "en"
        created = str(p.get("created_at", ""))[:10]  # date only
        pres_id = str(p.get("id", ""))
        lines.append(f"- {title} ({slides} slides, {tone}, {language}, {created})")

    display = f"Found {len(presentations)} presentation(s):\n" + "\n".join(lines[:30])
    if len(presentations) > 30:
        display += f"\n... and {len(presentations) - 30} more."

    speak = (
        f"I found {len(presentations)} presentation(s)."
        if not has_filter
        else f"I found {len(presentations)} presentation(s) matching '{query}'."
    )

    # Include presentation metadata in data (with accessible URLs)
    short_presentations = []
    for p in presentations[:30]:
        pres_id = str(p.get("id", ""))
        short_presentations.append({
            "id": pres_id,
            "title": p.get("title"),
            "n_slides": p.get("n_slides"),
            "tone": p.get("tone"),
            "language": p.get("language"),
            "created_at": p.get("created_at"),
            "updated_at": p.get("updated_at"),
            "view_url": _make_presentation_url(pres_id, "view", public=True),
            "edit_url": _make_presentation_url(pres_id, "edit", public=True),
            "view_url_lan": _make_presentation_url(pres_id, "view", public=False),
        })

    return ChatResponse(
        speak=speak,
        display=display,
        data={"query": query, "count": len(presentations), "presentations": short_presentations},
    )


def _handle_list_presentations(text: str) -> ChatResponse:
    """
    Handler for 'list-presentations' intent.
    Dispatches _scan_presentations in a background thread and returns job_id for polling.
    """
    job = Job(
        skill="list_presentations",
        params={"query": text},
        requester="siri",
        channel="siri",
    )

    def _run_scan():
        job.add_log("Scanning Presenton for presentations...")
        try:
            result = _scan_presentations(text)
            if result:
                job.summary = result.speak
                job.params["_result_data"] = result.data
                job.params["_result_display"] = result.display
                job.status = JobStatus.completed
                job.completed_at = datetime.now(timezone.utc).isoformat()
                job.add_log(f"Presentation scan completed: {result.speak[:100]}")
            else:
                job.error = "Presentation scan returned no result"
                job.status = JobStatus.failed
                job.completed_at = datetime.now(timezone.utc).isoformat()
        except Exception as exc:
            job.error = str(exc)
            job.status = JobStatus.failed
            job.completed_at = datetime.now(timezone.utc).isoformat()
            job.add_log(f"Presentation scan error: {exc}")

    _get_exec_pool().submit(_run_scan)
    jobs[job.job_id] = job

    logger.info("Job %s dispatched (async) for presentation listing.", job.job_id)
    return ChatResponse(
        speak="I'm listing your presentations. Results will be ready shortly.",
        display=f"Job {job.job_id} started for presentation listing.",
        job_id=job.job_id,
        data={"skill": "list_presentations", "intent": "list-presentations"},
    )


def _scan_images(query: str) -> ChatResponse:
    """List generated images from /home/chuck/data/media/generated/ and /images/."""
    generated_dir = ARTIFACT_ROOT / "generated"
    images_dir = ARTIFACT_ROOT / "images"
    exts = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}
    image_files = []

    for directory in [generated_dir, images_dir]:
        if not directory.is_dir():
            continue
        for f in directory.iterdir():
            if not f.is_file() or f.suffix.lower() not in exts:
                continue
            try:
                st = f.stat()
            except OSError:
                continue
            if st.st_size > 50 * 1024 * 1024:
                continue
            name = (f.stem.replace("gen_", "") or f.stem).strip()
            image_files.append({
                "filename": f.name,
                "name": name,
                "directory": directory.name,
                "size_bytes": st.st_size,
                "size_human": _human_size(st.st_size),
                "modified": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
                "view_url": _make_media_url(str(f), public=True),
                "view_url_lan": _make_media_url(str(f), public=False),
            })

    # Normalize query: strip common "list all" phrases that shouldn't act as filters
    _LIST_ALL_PATTERNS = [
        "list my images", "list images", "list all images", "show my images",
        "show images", "show all images", "my images", "all images",
    ]
    q_lower = query.lower().strip() if query else ""
    # Filter only if the query doesn't match a list-all pattern
    if q_lower and q_lower not in _LIST_ALL_PATTERNS:
        image_files = [i for i in image_files if q_lower in i["name"].lower() or q_lower in i["filename"].lower()]
    has_filter = bool(q_lower and q_lower not in _LIST_ALL_PATTERNS)

    # Sort by most recent first
    image_files.sort(key=lambda i: i["modified"], reverse=True)

    if not image_files:
        msg = "No images found." if not has_filter else f"No images matching '{query}'."
        return ChatResponse(speak=msg, display=msg, data={"query": query, "count": 0, "images": []})

    lines = [f"- {i['name']} ({i['size_human']}, {i['directory']}, {i['modified'][:19]})" for i in image_files]
    display = f"Found {len(image_files)} image(s):\n" + "\n".join(lines[:50])
    if len(image_files) > 50:
        display += f"\n... and {len(image_files) - 50} more."

    speak = f"I found {len(image_files)} image(s) matching '{query}'." if has_filter else f"I found {len(image_files)} image(s)."
    return ChatResponse(speak=speak, display=display, data={"query": query, "count": len(image_files), "images": image_files[:50]})


def _handle_list_images(text: str) -> ChatResponse:
    """
    Handler for 'list-images' intent.
    Dispatches _scan_images in a background thread and returns job_id for polling.
    """
    job = Job(
        skill="list_images",
        params={"query": text},
        requester="siri",
        channel="siri",
    )

    def _run_scan():
        job.add_log("Scanning for generated images...")
        try:
            result = _scan_images(text)
            if result:
                job.summary = result.speak
                job.params["_result_data"] = result.data
                job.params["_result_display"] = result.display
                job.status = JobStatus.completed
                job.completed_at = datetime.now(timezone.utc).isoformat()
                job.add_log(f"Image scan completed: {result.speak[:100]}")
            else:
                job.error = "Image scan returned no result"
                job.status = JobStatus.failed
                job.completed_at = datetime.now(timezone.utc).isoformat()
        except Exception as exc:
            job.error = str(exc)
            job.status = JobStatus.failed
            job.completed_at = datetime.now(timezone.utc).isoformat()
            job.add_log(f"Image scan error: {exc}")

    _get_exec_pool().submit(_run_scan)
    jobs[job.job_id] = job

    logger.info("Job %s dispatched (async) for image listing.", job.job_id)
    return ChatResponse(
        speak="I'm listing your images. Results will be ready shortly.",
        display=f"Job {job.job_id} started for image listing.",
        job_id=job.job_id,
        data={"skill": "list_images", "intent": "list-images"},
    )


# ---------------------------------------------------------------------------
# Chat Gateway Endpoints
# ---------------------------------------------------------------------------


@app.post("/api/chat")
async def api_chat(
    body: ChatRequest,
    x_api_key: Optional[str] = Header(None),
) -> ChatResponse:
    """
    Unified chat gateway endpoint.

    - **chat**: Direct model chat (no tools)
    - **siri-chat**: Chat with MCP tool calling (via siri_chat skill)
    - **deep-research**: Async deep research job
    - **build-presentation**: Async presentation builder job
    - **ask-siri**: Siri ask skill
    - **list-demos**: Scan demos page
    - **list-presentations**: Scan presentations
    """
    if SKILL_RUNNER_API_KEY:
        allowed = [k.strip() for k in SKILL_RUNNER_API_KEY.split(",") if k.strip()]
        if allowed and x_api_key not in allowed:
            raise HTTPException(status_code=403, detail="Invalid API key")

    intent = _detect_intent(body.text, body.intent)
    model = body.model or "matrix-gemma4-moe"

    logger.info("Chat request: intent=%s text=%s model=%s", intent, body.text[:100], model)

    # --- Direct chat (no tools) ---
    if intent == "chat":
        return await _chat_direct(body.text, model)

    # --- Siri chat with tool calling (async skill dispatch) ---
    if intent in ("siri-chat", "ask-siri"):
        intent = "siri-chat"

    # --- Listing intents (dispatch async — return job_id for polling) ---
    if intent == "list-demos":
        return _handle_list_demos(body.text)
    if intent == "list-presentations":
        return _handle_list_presentations(body.text)
    if intent == "list-images":
        return _handle_list_images(body.text)

    # --- New intent handlers (dispatch to skills/MCP) ---
    if intent == "update-presentation":
        return _handle_update_presentation(body.text)
    if intent == "find-demos":
        return _handle_find_demos(body.text)
    if intent == "research-brief":
        return _handle_research_brief(body.text)
    if intent == "media-generate":
        return await _handle_media_generate(body.text)

    # --- Async dispatch to skills (background thread — return job_id for polling) ---
    skill_name = _INTENT_SKILL_MAP.get(intent)
    if not skill_name:
        # Unknown intent — fall back to direct chat
        return await _chat_direct(body.text, model)

    # demo_workflow expects 'prompt', others expect 'query'
    params = {"prompt": body.text} if skill_name == "demo_workflow" else {"query": body.text}

    job = dispatch_job(
        skill_name,
        params=params,
    )
    jobs[job.job_id] = job

    logger.info("Job %s dispatched (async) for skill '%s'.", job.job_id, skill_name)

    return ChatResponse(
        speak=f"I've started processing your {intent.replace('-', ' ')} request. Please wait a moment.",
        display=f"Job {job.job_id} started for skill '{skill_name}'.",
        job_id=job.job_id,
        data={"model_alias": model, "skill": skill_name, "intent": intent},
    )


async def _chat_direct(text: str, model: str) -> ChatResponse:
    """Simple direct chat via LiteLLM (no tool calling)."""
    client = LiteLLMClient()
    try:
        resp = await client.chat_completion(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a helpful AI assistant optimised for voice and mobile delivery. "
                        "Give SHORT, DIRECT answers. Use plain language suitable for spoken playback."
                    ),
                },
                {"role": "user", "content": text},
            ],
            temperature=0.3,
            max_tokens=1024,
        )
        choice = resp.get("choices", [{}])[0]
        msg = choice.get("message", {})
        answer = (msg.get("content") or "").strip() or "I don't have enough information to answer that."
        return ChatResponse(
            speak=_truncate_for_speak(answer),
            display=answer,
            data={"model_alias": model},
        )
    except Exception as exc:
        logger.error("Chat error: %s", exc)
        return ChatResponse(
            speak="I encountered an error processing your request.",
            display=f"Error: {exc}",
            data={"error": str(exc)},
        )
    finally:
        await client.close()


@app.post("/skills/{skill_name}")
async def launch_skill(skill_name: str, body: SkillLaunchRequest) -> SkillJobResponse:
    """
    Launch a skill job.

    - **skill_name**: The skill to execute (e.g. `deep_research`, `siri_ask`).
    - **body**: JSON with `params`, `requester`, `channel`, `dry_run`, `tool_bundle`, `model_alias`.
    """
    job = Job(
        skill=skill_name,
        params=body.params,
        requester=body.requester,
        channel=body.channel,
        dry_run=body.dry_run,
        tool_bundle=body.tool_bundle,
        model_alias=body.model_alias,
    )

    job.add_log(f"Job created for skill '{skill_name}'")
    if body.dry_run:
        job.add_log("Dry run mode enabled")

    # Approval gate: if the skill requires approval, pause here
    # In skeleton form, no skills require approval by default.
    # Phase 9 will add per-skill approval gate configuration.
    if skill_name in ("family_kb_ingest", "repo_maintenance"):
        job.status = JobStatus.awaiting_approval
        job.add_log("Awaiting approval gate")
        jobs[job.job_id] = job
        logger.info("Job %s awaiting approval.", job.job_id)
        return _job_to_response(job)

    # Execute (synchronously in skeleton; Phase 9 will add async background tasks)
    _execute_skill(job)
    jobs[job.job_id] = job

    logger.info("Job %s launched for skill '%s'.", job.job_id, skill_name)
    return _job_to_response(job)


@app.get("/skills/jobs/{job_id}")
@app.get("/api/jobs/{job_id}")
async def get_job_status(job_id: str) -> SkillJobResponse:
    """Get the status of a skill job (also available at /api/jobs/{job_id})."""
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return _job_to_response(job)


@app.get("/skills/jobs/{job_id}/artifact")
async def get_job_artifact(job_id: str):
    """
    Retrieve the output artifact file for a completed skill job.

    Returns the file content with appropriate media type.
    """
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    if not job.artifact_path:
        raise HTTPException(
            status_code=404, detail=f"Job {job_id} has no artifact"
        )

    artifact_file = Path(job.artifact_path)
    if not artifact_file.is_file():
        raise HTTPException(
            status_code=404,
            detail=f"Artifact file not found: {artifact_file}",
        )

    content = artifact_file.read_bytes()

    # Determine media type
    ext = artifact_file.suffix.lower()
    media_types = {
        ".md": "text/markdown",
        ".txt": "text/plain",
        ".json": "application/json",
        ".html": "text/html",
        ".csv": "text/csv",
        ".pdf": "application/pdf",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
    }
    media_type = media_types.get(ext, "application/octet-stream")

    return Response(content=content, media_type=media_type)


@app.post("/skills/jobs/{job_id}/approve")
async def approve_job(job_id: str) -> SkillJobResponse:
    """Approve a job waiting at an approval gate and resume execution."""
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    if job.status != JobStatus.awaiting_approval:
        raise HTTPException(
            status_code=400,
            detail=f"Job {job_id} is not awaiting approval (status: {job.status})",
        )

    job.add_log("Approval granted — resuming execution")
    _execute_skill(job)
    logger.info("Job %s approved and resumed.", job.job_id)
    return _job_to_response(job)


@app.post("/skills/jobs/{job_id}/cancel")
async def cancel_job(job_id: str) -> SkillJobResponse:
    """Cancel a pending or running job."""
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    terminal_states = {JobStatus.completed, JobStatus.failed, JobStatus.cancelled}
    if job.status in terminal_states:
        raise HTTPException(
            status_code=400,
            detail=f"Job {job_id} is already {job.status}",
        )

    job.status = JobStatus.cancelled
    job.completed_at = datetime.now(timezone.utc).isoformat()
    job.add_log("Job cancelled by requester")
    logger.info("Job %s cancelled.", job.job_id)
    return _job_to_response(job)


# ---------------------------------------------------------------------------
# Schedule dispatch helper
# ---------------------------------------------------------------------------


def _schedule_dispatch_fn(skill: str, params: dict[str, Any], meta: dict[str, Any]) -> None:
    """Callback used by SimpleScheduler to dispatch a scheduled job."""
    schedule_id = meta.get("schedule_id", "unknown")
    job = Job(
        skill=skill,
        params=params,
        requester="scheduler",
        channel="scheduler",
    )
    job.add_log(f"Scheduled job from schedule '{schedule_id}'")
    _execute_skill(job)
    jobs[job.job_id] = job
    logger.info("Scheduled job %s launched for skill '%s' (schedule %s).", job.job_id, skill, schedule_id)


# ---------------------------------------------------------------------------
# Schedule Endpoints
# ---------------------------------------------------------------------------


@app.get("/api/schedule", response_model=ScheduleListResponse)
def get_schedules() -> ScheduleListResponse:
    """
    List all scheduled jobs.

    Returns every schedule entry currently loaded in the scheduler.
    """
    entries = []
    for sched in scheduler._schedules.values():
        d = sched.to_dict()
        entries.append(ScheduleResponse(**d))
    return ScheduleListResponse(schedules=entries, total=len(entries))


@app.post("/api/schedule", status_code=201, response_model=ScheduleResponse)
def create_schedule(body: ScheduleCreateRequest) -> ScheduleResponse:
    """
    Create a new scheduled job.

    Body fields:
    - **name**: Human-readable name for the schedule.
    - **cron**: 5-field cron expression (minute hour day_of_month month day_of_week).
    - **skill**: Skill name to dispatch on schedule.
    - **params**: Dict of parameters to pass to the skill.
    - **enabled**: Whether the schedule is active (default True).
    - **timezone**: Timezone string (default "UTC").
    """
    sid = scheduler.add_schedule(
        name=body.name,
        cron=body.cron,
        skill=body.skill,
        params=body.params,
        enabled=body.enabled,
        tz=body.timezone,
    )
    sched = scheduler._schedules.get(sid)
    if sched is None:
        raise HTTPException(status_code=500, detail="Schedule was not created")
    d = sched.to_dict()
    return ScheduleResponse(**d)


@app.delete("/api/schedule/{schedule_id}", status_code=200)
def delete_schedule(schedule_id: str) -> dict[str, Any]:
    """
    Remove a scheduled job by ID.

    Returns ``{"deleted": true}`` on success, or 404 if the ID was not found.
    """
    found = scheduler.remove_schedule(schedule_id)
    if not found:
        raise HTTPException(
            status_code=404, detail=f"Schedule '{schedule_id}' not found"
        )
    return {"deleted": True, "schedule_id": schedule_id}


@app.post("/api/schedule/{schedule_id}/run-now", status_code=200)
def run_schedule_now(schedule_id: str) -> dict[str, Any]:
    """
    Trigger a scheduled job immediately, regardless of its cron schedule.

    Returns the job_id of the dispatched job.
    """
    sched = scheduler._schedules.get(schedule_id)
    if sched is None:
        raise HTTPException(
            status_code=404, detail=f"Schedule '{schedule_id}' not found"
        )
    if not sched.enabled:
        raise HTTPException(
            status_code=400, detail=f"Schedule '{schedule_id}' is disabled"
        )

    job = Job(
        skill=sched.skill,
        params=sched.params,
        requester="scheduler",
        channel="scheduler",
    )
    job.add_log(f"Run-now trigger for schedule '{schedule_id}' ({sched.name})")
    _execute_skill(job)
    jobs[job.job_id] = job
    logger.info("Run-now job %s launched for schedule '%s'.", job.job_id, schedule_id)
    return {"job_id": job.job_id, "schedule_id": schedule_id}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _job_to_response(job: Job) -> SkillJobResponse:
    return SkillJobResponse(
        job_id=job.job_id,
        skill=job.skill,
        status=job.status.value,
        created_at=job.created_at,
        completed_at=job.completed_at,
        summary=job.summary,
        artifact_path=job.artifact_path,
        requester=job.requester,
        channel=job.channel,
        params=job.params,
        dry_run=job.dry_run,
        tool_bundle=job.tool_bundle,
        model_alias=job.model_alias,
        error=job.error,
    )


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


def main():
    import uvicorn

    logger.info("Starting Thor Skill Runner on %s:%d", APP_HOST, APP_PORT)
    logger.info("Artifact root: %s", ARTIFACT_ROOT)
    logger.info("Dry-run global mode: %s", DRY_RUN_MODE)
    logger.info("Log directory: %s", LOG_DIR)
    logger.info("MCP filesystem server: %s", MCP_SERVER_FILESYSTEM_URL)
    logger.info("MCP media server: %s", MCP_SERVER_MEDIA_URL)

    # Scheduler is managed by the FastAPI lifespan handler (see _startup / _shutdown).
    # uvicorn will invoke the lifespan on startup/shutdown automatically.

    uvicorn.run(
        "main:app",
        host=APP_HOST,
        port=APP_PORT,
        log_level="info",
    )


if __name__ == "__main__":
    main()
