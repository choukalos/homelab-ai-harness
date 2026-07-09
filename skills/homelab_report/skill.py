#!/usr/bin/env python3
"""
homelab_report skill — generate a homelab infrastructure health report.

Purpose:
  Calls the mcp_homelab_status MCP server (via LiteLLM) to collect Docker
  container status and system resource data, then synthesizes a concise
  markdown health report through the LLM.

Workflow:
  1. Determine scope (full, containers, system) from params.
  2. Call mcp_homelab_status tools via the LiteLLM client:
     - docker_ps()          — list all containers with status
     - system_info()        — CPU, memory, disk usage
     - container_logs()     — logs for unhealthy containers (full scope)
  3. Synthesize a markdown report via LLM (chat_completion).
  4. Save the report to the artifact path.

Constraints:
  - Max runtime: 120 seconds (2 minutes).
  - Uses MCP tools via LiteLLM client, never calls MCP servers directly.
  - Stateless: no rollback needed.

See skill.yml for the full manifest and README.md for usage.
"""

import json
import logging
import os
import re
import signal
import threading
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

ARTIFACT_DIR = Path(
    os.environ.get("HOMELAB_REPORT_ARTIFACT_DIR", "/home/chuck/data/media/homelab_reports")
)
MAX_RUNTIME_SECS = int(os.environ.get("HOMELAB_REPORT_MAX_RUNTIME", "120"))
MODEL_ALIAS = os.environ.get("HOMELAB_REPORT_MODEL", "local/qwen-coder")

logger = logging.getLogger("skill.homelab_report")

# ---------------------------------------------------------------------------
# Timeout enforcement
# ---------------------------------------------------------------------------


class TimeoutError(Exception):
    """Raised when the skill exceeds its maximum runtime."""


def _timeout_handler(signum, frame):
    raise TimeoutError(f"homelab_report exceeded {MAX_RUNTIME_SECS}s max runtime")


def _install_timeout():
    """Install a signal-based timeout (Unix only, main thread only)."""
    if sys.platform != "win32" and threading.main_thread() is threading.current_thread():
        signal.signal(signal.SIGALRM, _timeout_handler)
        signal.alarm(MAX_RUNTIME_SECS)


def _cancel_timeout():
    """Cancel the pending alarm."""
    if sys.platform != "win32" and threading.main_thread() is threading.current_thread():
        signal.alarm(0)


# ---------------------------------------------------------------------------
# MCP data collection via LiteLLM client
# ---------------------------------------------------------------------------


def _call_mcp_tool(litellm_client, server_id: str, tool_name: str, arguments: dict) -> Any:
    """
    Call an MCP tool through the LiteLLM sync wrapper.

    Args:
        litellm_client: The _SyncLiteLLMWrapper (or similar) client.
        server_id: MCP server identifier (e.g. 'mcp_homelab_status').
        tool_name: Tool name (e.g. 'docker_ps').
        arguments: Dict of tool arguments.

    Returns:
        The structured result if available, or a dict with error info.
    """
    result = litellm_client.mcp_call(
        tool_name=tool_name,
        arguments=arguments,
        server_id=server_id,
    )

    # Extract structured data from the MCP response
    if result.get("is_error"):
        error_text = "unknown error"
        for item in result.get("output", []):
            if item.get("type") == "text":
                error_text = item.get("text", "unknown error")
        return {"error": error_text}

    # Prefer structured result if present
    if "result" in result:
        return result["result"]

    # Fall back to text output
    output = result.get("output", [])
    for item in output:
        if item.get("type") == "text":
            return {"text_output": item.get("text", "")}

    return {"raw_output": output}


def _collect_container_data(litellm_client) -> dict:
    """Collect Docker container status via mcp_homelab_status.docker_ps."""
    logger.info("Collecting container data via MCP...")
    raw = _call_mcp_tool(litellm_client, "mcp_homelab_status", "docker_ps", {})

    if "error" in raw:
        return {"containers": [], "error": raw["error"]}

    containers = raw.get("results", raw.get("containers", []))
    if isinstance(raw, dict) and not raw.get("results") and not raw.get("containers"):
        # Might be returned directly as a list in structured result
        containers = raw if isinstance(raw, list) else []

    if isinstance(containers, list):
        return {"containers": containers}
    return {"containers": [], "error": "Unexpected response format from docker_ps"}


def _collect_system_data(litellm_client) -> dict:
    """Collect system info via mcp_homelab_status.system_info."""
    logger.info("Collecting system data via MCP...")
    raw = _call_mcp_tool(litellm_client, "mcp_homelab_status", "system_info", {})

    if "error" in raw:
        return {"system": {}, "error": raw["error"]}

    # system_info returns a dict with cpu, memory, disk keys
    system = raw.get("results", raw)
    if isinstance(system, dict) and not system.get("results"):
        system = raw
    return {"system": system}


def _collect_logs_for_unhealthy(containers: list[dict], litellm_client) -> list[dict]:
    """Collect recent logs for containers that are not healthy."""
    unhealthy = []
    for c in containers:
        state = c.get("state", "")
        health = c.get("health", "unknown")
        if state != "running" or health not in ("healthy", "unknown"):
            unhealthy.append(c)

    logs_data = []
    for c in unhealthy[:5]:  # Cap at 5 unhealthy containers to avoid long runs
        name = c.get("name", "unknown")
        logger.info(f"Collecting logs for unhealthy container: {name}")
        raw = _call_mcp_tool(
            litellm_client, "mcp_homelab_status", "container_logs",
            {"service_name": name, "tail": 20},
        )
        if "error" not in raw:
            logs_data.append({
                "container": name,
                "logs": raw.get("results", raw),
            })
    return logs_data


# ---------------------------------------------------------------------------
# LLM report synthesis
# ---------------------------------------------------------------------------


def _format_raw_data(containers: list[dict], system: dict, logs_data: list[dict]) -> str:
    """
    Convert raw MCP data into a plain-text summary for the LLM prompt.
    """
    lines = []

    # Container summary
    lines.append("## Docker Containers")
    running = [c for c in containers if c.get("state") == "running"]
    stopped = [c for c in containers if c.get("state") != "running"]
    lines.append(f"Running: {len(running)}, Stopped/Exited: {len(stopped)}")
    lines.append("")

    for c in containers:
        name = c.get("name", "unknown")
        state = c.get("state", "unknown")
        health = c.get("health", "unknown")
        image = c.get("image", "unknown")
        started = c.get("started_at", "N/A")
        exit_code = c.get("exit_code")
        ports = c.get("ports", [])

        status_parts = [f"**{name}**", f"({image})"]
        status_parts.append(f"State: {state}, Health: {health}")
        if state == "running":
            status_parts.append(f"Started: {started}")
        elif state == "exited" and exit_code is not None:
            status_parts.append(f"Exit code: {exit_code}, Last started: {started}")
        if ports:
            status_parts.append(f"Ports: {json.dumps(ports)}")
        lines.append("  - " + ", ".join(status_parts))

    lines.append("")

    # System info
    lines.append("## System Resources")
    cpu = system.get("cpu", {})
    mem = system.get("memory", {})
    disks = system.get("disk", [])

    lines.append(f"CPU: {cpu.get('percent', 'N/A')}% ({cpu.get('cores', 'N/A')} cores)")
    if mem:
        total_mb = mem.get("total_bytes", 0) / (1024 * 1024)
        used_mb = mem.get("used_bytes", 0) / (1024 * 1024)
        avail_mb = mem.get("available_bytes", 0) / (1024 * 1024)
        lines.append(
            f"Memory: {used_mb:.0f}MB / {total_mb:.0f}MB "
            f"({mem.get('percent', 'N/A')}%), "
            f"Available: {avail_mb:.0f}MB"
        )

    if disks:
        lines.append("Disk:")
        for d in disks:
            if "error" in d:
                lines.append(f"  - {d.get('mountpoint', 'unknown')}: {d['error']}")
            else:
                total_gb = d.get("total_bytes", 0) / (1024 ** 3)
                used_gb = d.get("used_bytes", 0) / (1024 ** 3)
                lines.append(
                    f"  - {d.get('mountpoint', 'unknown')}: "
                    f"{used_gb:.1f}GB / {total_gb:.1f}GB ({d.get('percent', 'N/A')}%)"
                )

    lines.append("")

    # Unhealthy container logs
    if logs_data:
        lines.append("## Unhealthy Container Logs")
        for ld in logs_data:
            logs = ld.get("logs", {})
            log_lines = logs.get("logs", []) if isinstance(logs, dict) else logs
            lines.append(f"### {ld['container']}")
            lines.append("```")
            for line in log_lines[-10:]:  # Last 10 lines
                lines.append(str(line))
            lines.append("```")
            lines.append("")

    return "\n".join(lines)


def _synthesize_report(litellm_client, raw_data_text: str, scope: str) -> str:
    """
    Send raw data to the LLM for markdown report synthesis.

    Uses the LiteLLM chat_completion endpoint.
    """
    system_prompt = textwrap.dedent("""\
        You are a homelab infrastructure analyst. Given raw monitoring data,
        produce a concise, well-formatted Markdown health report.

        Rules:
        - Use clear headings, bullet points, and status indicators (✅ healthy, ⚠️ warning, ❌ down).
        - Keep it scannable: highlight issues first, then summary details.
        - Include a "Health Score" section with an overall assessment.
        - If data is missing or an error occurred, note it clearly.
        - Keep total output under 1000 words.
    """)

    user_prompt = textwrap.dedent(f"""\
        Generate a homelab health report (scope: {scope}).

        Raw monitoring data:

        {raw_data_text}

        Produce the markdown report now.
    """)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    logger.info("Synthesizing report via LLM (model=%s)...", MODEL_ALIAS)
    response = litellm_client.chat_completion(
        model=MODEL_ALIAS,
        messages=messages,
        temperature=0.1,
        max_tokens=2000,
    )

    # Extract the LLM's text content
    choices = response.get("choices", [])
    if choices and "message" in choices[0]:
        return choices[0]["message"].get("content", "[No content from LLM]")
    return "[Error: could not parse LLM response]"


# ---------------------------------------------------------------------------
# Artifact saving
# ---------------------------------------------------------------------------


def _slugify(value: str) -> str:
    """Convert a string to a filename-safe slug."""
    return "".join(c if c.isalnum() or c == "-" else "-" for c in value[:60]).strip("-")


def _save_report(report: str, scope: str) -> Optional[str]:
    """
    Save the markdown report to the artifact directory.
    Returns the file path or None on failure.
    """
    try:
        ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
        slug = _slugify(f"homelab_{scope}")
        filename = f"homelab_report_{ts}_{slug}.md"
        path = ARTIFACT_DIR / filename

        path.write_text(report, encoding="utf-8")
        logger.info("Report saved: %s", path)
        return str(path)
    except OSError as exc:
        logger.warning("Could not save report: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------


def run(params: dict[str, Any], job, litellm_client=None) -> dict[str, Any]:
    """
    Execute the homelab_report skill.

    Calls mcp_homelab_status tools via LiteLLM to gather container and system
    data, synthesizes a markdown report via LLM, and saves it as an artifact.

    Args:
        params: Skill parameters (scope).
        job: The runner Job object for logging.
        litellm_client: The _SyncLiteLLMWrapper client for MCP and LLM calls.

    Returns:
        Dict with report, artifact_path, and metadata.
    """
    # Validate inputs
    scope = str(params.get("scope", "full")).strip().lower() or "full"
    if scope not in ("full", "containers", "system"):
        scope = "full"

    # Log the invocation
    if hasattr(job, "add_log"):
        job.add_log(f"Executing homelab_report: scope='{scope}'")
        job.add_log(f"Model: {MODEL_ALIAS}")
        job.add_log(f"Max runtime: {MAX_RUNTIME_SECS}s")

    # Install timeout
    _install_timeout()

    # Require litellm_client (injected by runner)
    if litellm_client is None:
        msg = "litellm_client not provided (expected from skill runner)"
        if hasattr(job, "add_log"):
            job.add_log(msg)
        return {"error": msg, "scope": scope, "status": "error"}

    try:
        # Collect data based on scope
        containers_data = {}
        system_data = {}
        logs_data = []

        if scope in ("full", "containers"):
            containers_data = _collect_container_data(litellm_client)
            if hasattr(job, "add_log"):
                count = len(containers_data.get("containers", []))
                job.add_log(f"Collected {count} containers")

        if scope in ("full", "system"):
            system_data = _collect_system_data(litellm_client)
            if hasattr(job, "add_log"):
                job.add_log("Collected system info")

        if scope == "full":
            containers = containers_data.get("containers", [])
            logs_data = _collect_logs_for_unhealthy(containers, litellm_client)
            if hasattr(job, "add_log"):
                job.add_log(f"Collected logs for {len(logs_data)} unhealthy containers")

        # Build raw data text for LLM
        raw_text = _format_raw_data(
            containers_data.get("containers", []),
            system_data.get("system", {}),
            logs_data,
        )

        # Synthesize report via LLM
        report = _synthesize_report(litellm_client, raw_text, scope)

        if hasattr(job, "add_log"):
            job.add_log(f"Report synthesized ({len(report)} chars)")

        # Save artifact
        artifact_path = _save_report(report, scope)

        if hasattr(job, "add_log"):
            if artifact_path:
                job.add_log(f"Artifact saved: {artifact_path}")
            else:
                job.add_log("Warning: artifact save failed")

        # Build result
        result: dict[str, Any] = {
            "report": report,
            "summary": f"Homelab report ({scope}) generated, {len(report)} chars",
            "scope": scope,
            "artifact_path": artifact_path,
        }

        # Include error info if collection had issues
        if "error" in containers_data:
            result["container_error"] = containers_data["error"]
        if "error" in system_data:
            result["system_error"] = system_data["error"]

        if hasattr(job, "add_log"):
            job.add_log("homelab_report completed successfully")

        return result

    except TimeoutError as exc:
        msg = str(exc)
        if hasattr(job, "add_log"):
            job.add_log(f"Timeout: {msg}")
        return {
            "error": msg,
            "scope": scope,
            "status": "timeout",
        }

    except RuntimeError as exc:
        msg = str(exc)
        if hasattr(job, "add_log"):
            job.add_log(f"Runtime error: {msg}")
        return {
            "error": msg,
            "scope": scope,
            "status": "error",
        }

    except Exception as exc:
        msg = f"Unexpected error: {exc}"
        if hasattr(job, "add_log"):
            job.add_log(msg)
        return {
            "error": msg,
            "scope": scope,
            "status": "error",
        }

    finally:
        _cancel_timeout()


# ---------------------------------------------------------------------------
# CLI entrypoint (for standalone testing)
# ---------------------------------------------------------------------------


class _MockJob:
    """Dummy job object for standalone testing."""

    def __init__(self):
        self.logs: list[str] = []

    def add_log(self, msg: str) -> None:
        self.logs.append(msg)
        print(f"  [LOG] {msg}")


class _MockLiteLLMClient:
    """Mock LiteLLM client for standalone testing."""

    def mcp_call(self, tool_name, arguments, server_id=None, **kwargs):
        if tool_name == "docker_ps":
            return {
                "is_error": False,
                "output": [{"_structured": {}}],
                "result": {
                    "results": [
                        {"name": "nginx", "state": "running", "health": "healthy", "image": "nginx:latest", "ports": [], "started_at": "2026-07-01T00:00:00Z"},
                        {"name": "postgres", "state": "running", "health": "healthy", "image": "postgres:15", "ports": [{"container": "5432", "host_port": "5432"}], "started_at": "2026-07-01T00:00:00Z"},
                        {"name": "redis", "state": "exited", "health": "n/a", "image": "redis:7", "ports": [], "started_at": "2026-06-30T00:00:00Z", "exit_code": 1},
                    ]
                },
            }
        elif tool_name == "system_info":
            return {
                "is_error": False,
                "output": [{"_structured": {}}],
                "result": {
                    "cpu": {"percent": 25.5, "cores": 8},
                    "memory": {"total_bytes": 32 * 1024**3, "used_bytes": 12 * 1024**3, "available_bytes": 20 * 1024**3, "percent": 37.5},
                    "disk": [
                        {"device": "/dev/sda1", "mountpoint": "/", "fstype": "ext4", "total_bytes": 500 * 1024**3, "used_bytes": 200 * 1024**3, "free_bytes": 300 * 1024**3, "percent": 40},
                    ],
                },
            }
        elif tool_name == "container_logs":
            return {
                "is_error": False,
                "output": [{"_structured": {}}],
                "result": {
                    "name": "redis",
                    "logs": ["ERR: Could not open tcp listen socket", "Exiting..."],
                },
            }
        return {"is_error": True, "output": [{"type": "text", "text": f"Mock: {tool_name} not implemented"}]}

    def chat_completion(self, model, messages, **kwargs):
        return {
            "choices": [{
                "message": {
                    "content": "# Homelab Health Report\n\n## Health Score: ⚠️ WARNING\n\n## Containers\n- ✅ nginx — running, healthy\n- ✅ postgres — running, healthy\n- ❌ redis — exited (exit code 1)\n\n## System\n- CPU: 25.5% (8 cores)\n- Memory: 37.5% used\n- Disk: 40% used\n\n## Issues\n- Redis is down. Recent logs indicate a socket binding error."
                }
            }]
        }


def main():
    """Standalone test entrypoint.

    Usage:
        python skill.py --scope full
        python skill.py --scope containers --dry-run
    """
    import argparse

    parser = argparse.ArgumentParser(description="homelab_report standalone test")
    parser.add_argument(
        "--scope", default="full", choices=["full", "containers", "system"],
        help="Report scope (default: full)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Print parameters without calling MCP or LLM"
    )
    args = parser.parse_args()

    if args.dry_run:
        print("=== DRY RUN ===")
        print(f"  Scope: {args.scope}")
        print(f"  Model: {MODEL_ALIAS}")
        print(f"  Max runtime: {MAX_RUNTIME_SECS}s")
        print(f"  Artifact dir: {ARTIFACT_DIR}")
        print(f"  MCP server: mcp_homelab_status")
        print(f"  Tools: docker_ps, system_info, container_logs")
        print()
        print("  Expected flow:")
        print("    1. Call mcp_homelab_status.docker_ps() via LiteLLM")
        print("    2. Call mcp_homelab_status.system_info() via LiteLLM")
        print("    3. (full scope) Call container_logs() for unhealthy containers")
        print("    4. Synthesize markdown report via LLM")
        print("    5. Save report to artifact path")
        return

    params = {"scope": args.scope}
    result = run(params, _MockJob(), _MockLiteLLMClient())

    print(f"\n--- homelab_report response ---")
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
