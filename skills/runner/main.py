#!/usr/bin/env python3
"""
Thor Skill Runner — Lightweight skill orchestration API.

Runs on dev port 8091 alongside the current AI Harness (8090).
Provides the job lifecycle API: launch, status, and artifact retrieval.
"""

import asyncio
import concurrent.futures
import importlib.util
import inspect
import json
import logging
import os
import sys
import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import JSONResponse
from httpx import AsyncClient, Timeout
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG_DIR = Path(os.environ.get("SKILL_RUNNER_LOG_DIR", "/home/chuck/homelab/logs/skill_runner"))
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_DIR / "skill_runner.log"),
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
LITELLM_BASE_URL = os.environ.get(
    "LITELLM_BASE_URL", "http://litellm-proxy:4000"
)
LITELLM_API_KEY = os.environ.get("LITELLM_API_KEY", "")

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
        env_key = f"MCP_SERVER_{name.upper()}_URL"
        base_url = os.environ.get(env_key, f"http://{server_id}:8000").rstrip("/")

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

        async with AsyncClient(timeout=Timeout(120.0)) as client:
            # ---- Step 1: POST initialize, get X-Session-Id ----
            try:
                init_resp = await client.post(mcp_url, json=initialize_request, timeout=30.0)
                init_resp.raise_for_status()
                init_body = init_resp.json()
                session_id = init_resp.headers.get("X-Session-Id")
                if not session_id:
                    parse_error_holder[0] = "initialize response missing X-Session-Id header"
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
                    headers={"X-Session-Id": session_id},
                    timeout=15.0,
                )
                init_ack.raise_for_status()
                logger.info("MCP initialized notification sent")
            except Exception as exc:
                parse_error_holder[0] = f"MCP initialized notification failed: {exc}"
                # Attempt cleanup and return
                try:
                    await client.delete(mcp_url, headers={"X-Session-Id": session_id}, timeout=10.0)
                except Exception:
                    pass
                return {"output": [{"type": "text", "text": parse_error_holder[0]}], "is_error": True}

            # ---- Step 3: POST tools/call ----
            try:
                tool_resp = await client.post(
                    mcp_url,
                    json=jsonrpc_request,
                    headers={"X-Session-Id": session_id},
                    timeout=60.0,
                )
            except Exception as exc:
                parse_error_holder[0] = f"tools/call POST failed: {exc}"
                # Attempt cleanup
                try:
                    await client.delete(mcp_url, headers={"X-Session-Id": session_id}, timeout=10.0)
                except Exception:
                    pass
                return {"output": [{"type": "text", "text": parse_error_holder[0]}], "is_error": True}

            logger.info("tools/call POST returned status %d", tool_resp.status_code)

            # ---- Step 3a: 200 OK — direct JSON-RPC result ----
            if tool_resp.status_code == 200:
                try:
                    jsonrpc_response = tool_resp.json()
                except Exception as exc:
                    parse_error_holder[0] = f"Failed to parse tool response JSON: {exc}"
                    # Attempt cleanup
                    try:
                        await client.delete(mcp_url, headers={"X-Session-Id": session_id}, timeout=10.0)
                    except Exception:
                        pass
                    return {"output": [{"type": "text", "text": parse_error_holder[0]}], "is_error": True}

                self._parse_tool_response(jsonrpc_response, result_content,
                                           parse_error_holder, structured_result_holder)

                if parse_error_holder[0]:
                    error = parse_error_holder[0]
                    try:
                        await client.delete(mcp_url, headers={"X-Session-Id": session_id}, timeout=10.0)
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

    Skill modules run in synchronous code (no async event loop).  This wrapper
    runs each async call in a dedicated thread with a fresh event loop, so it
    never clashes with uvloop's running loop in the FastAPI/uvicorn main thread.

    Usage:

        client = LiteLLMClient()
        sync = _SyncLiteLLMWrapper(client)
        result = sync.chat_completion("matrix-coder", messages)
        result = sync.mcp_call("search_web", {"query": "test"})
    """

    def __init__(self, client: LiteLLMClient) -> None:
        self._client = client

    @property
    def base_url(self) -> str:
        """Delegate to the wrapped client's base_url."""
        return self._client.base_url

    # Reusable thread pool for async execution
    _thread_pool: concurrent.futures.ThreadPoolExecutor = None

    def _get_thread_pool(self) -> concurrent.futures.ThreadPoolExecutor:
        if self._thread_pool is None:
            self._thread_pool = concurrent.futures.ThreadPoolExecutor(max_workers=4)
        return self._thread_pool

    def _run_async_in_thread(self, coro) -> Any:
        """Run an async coroutine in a dedicated thread with a new event loop."""
        def _run():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(coro)
            finally:
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
        return self._run_async_in_thread(
            self._client.chat_completion(model, messages, **kwargs)
        )

    def mcp_call(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        server_id: Optional[str] = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Sync wrapper for ``LiteLLMClient.mcp_call``."""
        return self._run_async_in_thread(
            self._client.mcp_call(tool_name, arguments, server_id=server_id, **kwargs)
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
    }
    return mapping.get(skill)


def _slugify(value: str) -> str:
    return "".join(c if c.isalnum() or c == "-" else "-" for c in value[:50]).strip("-")


# ---------------------------------------------------------------------------
# FastAPI Application
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Thor Skill Runner",
    description="Skill orchestration API — runs on dev port 8091.",
    version="0.1.0",
)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "port": APP_PORT, "jobs_total": len(jobs)}


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
async def get_job_status(job_id: str) -> SkillJobResponse:
    """Get the status of a skill job."""
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

    uvicorn.run(
        "main:app",
        host=APP_HOST,
        port=APP_PORT,
        log_level="info",
    )


if __name__ == "__main__":
    main()
