#!/usr/bin/env python3
"""MCP Homelab Status Server — Docker and system monitoring tools.

Provides four tools:
  - docker_ps()                    List all containers with status, image, ports
  - service_status(service_name)   Check if a specific container is running/healthy
  - system_info()                  CPU, memory, disk usage
  - container_logs(service_name, tail)  Last N lines from container logs

Backend: Docker daemon via docker-py SDK, system metrics via psutil
Transport: streamable-http (HTTP, default 0.0.0.0:8000)
"""

import os
import logging
from typing import Optional

import docker
import psutil
from mcp.server import FastMCP

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DOCKER_HOST: str = os.environ.get("DOCKER_HOST", "unix:///var/run/docker.sock")
MCPS_HOST: str = os.environ.get("MCPS_HOST", "0.0.0.0")

logger = logging.getLogger("mcp_homelab_status")

# ---------------------------------------------------------------------------
# Docker helpers
# ---------------------------------------------------------------------------


def _get_docker_client() -> docker.DockerClient:
    """Create a Docker client connected to the Docker daemon."""
    return docker.from_env()


# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------

mcp = FastMCP(
    name="mcp_homelab_status",
    instructions=(
        "Homelab infrastructure health monitoring. "
        "Lists Docker containers, checks service health, reports system metrics "
        "(CPU, memory, disk), and retrieves container logs. "
        "Read-only access to Docker daemon."
    ),
    host=MCPS_HOST,
)


@mcp.tool(
    name="docker_ps",
    description="List all Docker containers with their current status, image name, exposed ports, and uptime.",
)
def docker_ps() -> list[dict]:
    """List all containers (running and stopped) with key details.

    Returns:
        List of dicts with container name, id, state, image, ports, and status message.
    """
    client = _get_docker_client()
    try:
        containers = client.containers.list(all=True)
        result = []
        for c in containers:
            info = c.attrs
            state = c.status  # running, exited, created, etc.

            # Get ports
            ports = []
            port_mappings = c.ports or {}
            for container_port, host_bindings in port_mappings.items():
                if host_bindings:
                    for binding in host_bindings:
                        ports.append({
                            "container": str(container_port),
                            "host_ip": binding.get("HostIp", ""),
                            "host_port": binding.get("HostPort", ""),
                        })
                else:
                    ports.append({"container": str(container_port), "host_ip": "", "host_port": ""})

            # Uptime / since
            since = info.get("State", {}).get("StartedAt", "")
            if since and state == "running":
                uptime = since
            elif since and state == "exited":
                uptime = since
            else:
                uptime = ""

            result.append({
                "name": c.name,
                "id": c.short_id,
                "state": state,
                "image": c.image.tags[0] if c.image.tags else c.image.short_id,
                "ports": ports,
                "started_at": uptime,
                "health": info.get("State", {}).get("Health", {}).get("Status", "unknown") if state == "running" else "n/a",
                "exit_code": info.get("State", {}).get("ExitCode", None) if state == "exited" else None,
            })
        return result
    except docker.errors.DockerException as exc:
        logger.error("Failed to list containers: %s", exc)
        raise RuntimeError(f"Failed to list containers: {exc}") from exc


@mcp.tool(
    name="service_status",
    description="Check the status of a specific container by name. Returns running state, health, and resource usage if available.",
)
def service_status(service_name: str) -> dict:
    """Check if a specific container is running and healthy.

    Args:
        service_name: The container name to check.

    Returns:
        Dict with name, state, health status, uptime, and resource stats.
    """
    client = _get_docker_client()
    try:
        container = client.containers.get(service_name)
        info = container.attrs
        state = container.status

        health_status = "unknown"
        if state == "running":
            health_info = info.get("State", {}).get("Health", {})
            health_status = health_info.get("Status", "unknown") if health_info else "no-healthcheck"

        # Get stats snapshot for running containers
        cpu_usage = None
        memory_usage = None
        if state == "running":
            try:
                stats = container.stats(stream=False)
                cpu_delta = stats.get("cpu_stats", {}).get("cpu_usage", {}).get("total_usage", 0) - \
                            stats.get("precpu_stats", {}).get("cpu_usage", {}).get("total_usage", 0)
                system_delta = stats.get("cpu_stats", {}).get("system_cpu_usage", 0) - \
                               stats.get("precpu_stats", {}).get("system_cpu_usage", 0)
                if system_delta > 0:
                    cpu_usage = round(cpu_delta / system_delta * 100, 2)
                mem_stats = stats.get("memory_stats", {})
                mem_usage = mem_stats.get("usage", 0)
                mem_limit = mem_stats.get("limit", 0)
                memory_usage = {
                    "used_bytes": mem_usage,
                    "limit_bytes": mem_limit,
                    "percent": round(mem_usage / mem_limit * 100, 2) if mem_limit > 0 else None,
                }
            except Exception:
                pass

        return {
            "name": service_name,
            "id": container.short_id,
            "state": state,
            "health": health_status,
            "image": container.image.tags[0] if container.image.tags else container.image.short_id,
            "cpu_percent": cpu_usage,
            "memory": memory_usage,
            "started_at": info.get("State", {}).get("StartedAt", ""),
            "exit_code": info.get("State", {}).get("ExitCode", None) if state == "exited" else None,
        }
    except docker.errors.NotFound:
        return {
            "name": service_name,
            "state": "not_found",
            "health": "unknown",
            "message": f"Container '{service_name}' not found.",
        }
    except docker.errors.DockerException as exc:
        logger.error("Failed to get status for %s: %s", service_name, exc)
        raise RuntimeError(f"Failed to get status for '{service_name}': {exc}") from exc


@mcp.tool(
    name="system_info",
    description="Get system resource usage: CPU utilization, memory usage, and disk usage per mount point.",
)
def system_info() -> dict:
    """Gather system resource metrics using psutil.

    Returns:
        Dict with cpu (percent), memory (used, total, percent), and disk list.
    """
    cpu_percent = psutil.cpu_percent(interval=1)
    memory = psutil.virtual_memory()
    disk_partitions = psutil.disk_partitions(all=False)

    disks = []
    for part in disk_partitions:
        try:
            usage = psutil.disk_usage(part.mountpoint)
            disks.append({
                "device": part.device,
                "mountpoint": part.mountpoint,
                "fstype": part.fstype,
                "total_bytes": usage.total,
                "used_bytes": usage.used,
                "free_bytes": usage.free,
                "percent": usage.percent,
            })
        except PermissionError:
            disks.append({
                "device": part.device,
                "mountpoint": part.mountpoint,
                "fstype": part.fstype,
                "error": "Permission denied",
            })

    return {
        "cpu": {
            "percent": cpu_percent,
            "cores": psutil.cpu_count(logical=True),
        },
        "memory": {
            "total_bytes": memory.total,
            "used_bytes": memory.used,
            "available_bytes": memory.available,
            "percent": memory.percent,
        },
        "disk": disks,
        "uptime_seconds": psutil.boot_time(),
    }


@mcp.tool(
    name="container_logs",
    description="Get the last N lines of logs from a specific container.",
)
def container_logs(service_name: str, tail: int = 100) -> dict:
    """Retrieve recent logs from a container.

    Args:
        service_name: The container name.
        tail: Number of lines to retrieve (default 100, max 5000).

    Returns:
        Dict with container name, line count, and log lines list.
    """
    if tail < 1:
        tail = 1
    elif tail > 5000:
        tail = 5000

    client = _get_docker_client()
    try:
        container = client.containers.get(service_name)
        raw_logs = container.logs(tail=tail, stdout=True, stderr=True)
        if isinstance(raw_logs, bytes):
            raw_logs = raw_logs.decode("utf-8", errors="replace")
        lines = [line for line in raw_logs.strip().split("\n") if line.strip()]
        return {
            "name": service_name,
            "lines_requested": tail,
            "lines_returned": len(lines),
            "logs": lines,
        }
    except docker.errors.NotFound:
        return {
            "name": service_name,
            "message": f"Container '{service_name}' not found.",
            "logs": [],
        }
    except docker.errors.DockerException as exc:
        logger.error("Failed to get logs for %s: %s", service_name, exc)
        raise RuntimeError(f"Failed to get logs for '{service_name}': {exc}") from exc


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Run the MCP homelab_status server over streamable-http transport (0.0.0.0:8000)."""
    logging.basicConfig(level=logging.INFO)
    logger.info("Starting mcp_homelab_status, docker=%s", DOCKER_HOST)
    mcp.run(transport="streamable-http")  # defaults to 0.0.0.0:8000


if __name__ == "__main__":
    main()
