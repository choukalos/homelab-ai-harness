#!/usr/bin/env python3
"""
litellm_health_check skill — LiteLLM proxy outage poller.

Purpose:
  Request metrics only show model health while traffic flows. This skill
  probes the proxy's GET /health endpoint (with a key) on a 5-minute
  schedule so a dead upstream surfaces even with zero traffic — the
  macstudio OMLX outage (dead since at least 2026-11-17) sat undetected
  for days because nothing polled /health (tier2-litellm-health-visibility).

Workflow:
  1. GET {proxy_url}/health with the LiteLLM key (the runner's
     LITELLM_API_KEY by default; `api_key` param overrides).
  2. Healthy (HTTP 200 + empty unhealthy_endpoints): SILENT — remove any
     existing alert file from the public drop zone.
  3. Unhealthy (unhealthy_endpoints non-empty, non-200, unparseable
     payload, or proxy unreachable): write/refresh the alert file in the
     public drop zone — the existing notify path used by morning_brief's
     publish (/home/chuck/data/media/public/briefs/, served at
     https://choukalos.com/files/briefs/). The file keeps the FIRST
     detection timestamp and refreshes the last-confirmed timestamp on
     every subsequent unhealthy check.

Constraints:
  - No LLM, no MCP — stdlib urllib only (works standalone and via runner).
  - Writes only the alert file (atomic tmp+replace) and its own logs.
  - Fail-closed: any probe error is treated as unhealthy (an outage
    detector that goes quiet when it cannot verify is worse than one
    that over-alerts).
  - Max runtime: 60 seconds.

See skill.yml for the manifest and README.md for usage.
"""

import argparse
import json
import logging
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("skill.litellm_health_check")

# ---------------------------------------------------------------------------
# Configuration (env-overridable; params override env)
# ---------------------------------------------------------------------------

DEFAULT_PROXY_URL = os.environ.get("LITELLM_BASE_URL", "http://litellm-proxy:4000")
# The public drop zone (notify path): same zone morning_brief publishes to.
DEFAULT_ALERT_PATH = os.environ.get(
    "LITELLM_HEALTH_ALERT_PATH",
    "/home/chuck/data/media/public/briefs/litellm-health-alert.md",
)
DEFAULT_TIMEOUT_SECS = 30
ERROR_TRUNCATE_CHARS = 300  # per-endpoint error detail in the alert file
_FIRST_DETECTED_RE = re.compile(r"\*\*first_detected:\*\*\s*(\S+)")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _log(job: Any, msg: str) -> None:
    """Log to the job (when running via the runner) and the logger."""
    logger.info(msg)
    if job is not None and hasattr(job, "add_log"):
        job.add_log(msg)


def _truncate(text: str, limit: int = ERROR_TRUNCATE_CHARS) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit] + " …(truncated)"


def _md_cell(text: str) -> str:
    """Make a string safe for a markdown table cell (single line)."""
    return _truncate(text).replace("|", "\\|").replace("\n", " ").strip()


def _probe_health(
    proxy_url: str, api_key: str, timeout: int
) -> tuple[bool, dict[str, Any]]:
    """
    GET {proxy_url}/health with a Bearer key.

    Returns (healthy, detail). On healthy: detail carries the endpoint
    lists. On unhealthy: detail carries `reason` (and the endpoint lists
    when the payload was parseable). Fail-closed: any error -> unhealthy.
    """
    url = proxy_url.rstrip("/") + "/health"
    req = urllib.request.Request(url, method="GET")
    if api_key:
        req.add_header("Authorization", f"Bearer {api_key}")
    req.add_header("Accept", "application/json")

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.status
            body = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail_body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        return False, {
            "reason": f"proxy /health returned HTTP {exc.code}",
            "detail": _truncate(detail_body),
        }
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        reason = getattr(exc, "reason", None) or str(exc)
        return False, {
            "reason": f"proxy unreachable at {url}: {reason}",
        }

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return False, {
            "reason": "proxy /health returned HTTP 200 but an unparseable payload",
            "detail": _truncate(body),
        }
    if not isinstance(payload, dict):
        return False, {
            "reason": "proxy /health returned an unexpected payload shape",
            "detail": _truncate(body),
        }

    healthy_eps = payload.get("healthy_endpoints") or []
    unhealthy_eps = payload.get("unhealthy_endpoints") or []
    if status != 200:
        return False, {
            "reason": f"proxy /health returned HTTP {status}",
            "healthy_endpoints": healthy_eps,
            "unhealthy_endpoints": unhealthy_eps,
        }
    if unhealthy_eps:
        return False, {
            "reason": f"{len(unhealthy_eps)} unhealthy endpoint(s) reported by /health",
            "healthy_endpoints": healthy_eps,
            "unhealthy_endpoints": unhealthy_eps,
        }
    return True, {
        "reason": "all endpoints healthy",
        "healthy_endpoints": healthy_eps,
        "unhealthy_endpoints": [],
    }


def _render_alert(
    detail: dict[str, Any],
    proxy_url: str,
    now: datetime,
    first_detected: str,
) -> str:
    """Render the alert markdown for the public drop zone."""
    lines = [
        "# ⚠️ LiteLLM proxy health alert",
        "",
        f"- **status:** UNHEALTHY — {detail.get('reason', 'unknown')}",
        f"- **first_detected:** {first_detected}",
        f"- **last_confirmed:** {now.isoformat()}",
        f"- **proxy:** {proxy_url}",
        "",
    ]
    unhealthy = detail.get("unhealthy_endpoints") or []
    if unhealthy:
        lines += [
            "## Unhealthy endpoints",
            "",
            "| api_base | model | error |",
            "|---|---|---|",
        ]
        for ep in unhealthy:
            if not isinstance(ep, dict):
                continue
            lines.append(
                "| {} | {} | {} |".format(
                    _md_cell(ep.get("api_base", "")),
                    _md_cell(ep.get("model", "")),
                    _md_cell(ep.get("error", "")),
                )
            )
        lines.append("")
    if detail.get("detail"):
        lines += ["## Detail", "", "```", _truncate(detail["detail"], 1000), "```", ""]
    healthy = detail.get("healthy_endpoints") or []
    if healthy:
        lines += [
            "## Healthy endpoints (for reference)",
            "",
            "| api_base | model |",
            "|---|---|",
        ]
        for ep in healthy:
            if not isinstance(ep, dict):
                continue
            lines.append(
                f"| {_md_cell(ep.get('api_base', ''))} | {_md_cell(ep.get('model', ''))} |"
            )
        lines.append("")
    lines += [
        "_Checked every 5 minutes by the `litellm_health_check` scheduled job",
        "(proposals/2026-11-19-tier2-litellm-health-visibility). This file is removed",
        "automatically on the next healthy check._",
        "",
    ]
    return "\n".join(lines)


def _write_alert(
    alert_path: Path, detail: dict[str, Any], proxy_url: str, now: datetime
) -> str:
    """
    Write/refresh the alert file (atomic). Preserves the original
    first_detected timestamp when the file already exists.
    """
    first_detected = now.isoformat()
    try:
        if alert_path.is_file():
            existing = alert_path.read_text(encoding="utf-8", errors="replace")
            m = _FIRST_DETECTED_RE.search(existing)
            if m:
                first_detected = m.group(1)
    except OSError as exc:
        logger.warning("Could not read existing alert file (%s) — using now.", exc)

    content = _render_alert(detail, proxy_url, now, first_detected)
    alert_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = alert_path.with_name(alert_path.name + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, alert_path)
    return first_detected


def _remove_alert(alert_path: Path) -> bool:
    """Remove the alert file if present (healthy -> silent). Returns True if removed."""
    try:
        if alert_path.is_file():
            alert_path.unlink()
            return True
    except OSError as exc:
        logger.warning("Could not remove alert file %s: %s", alert_path, exc)
    return False


# ---------------------------------------------------------------------------
# Skill entry point
# ---------------------------------------------------------------------------


def run(
    params: Optional[dict[str, Any]] = None,
    job: Any = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """
    Probe the LiteLLM proxy /health endpoint and alert via the public
    drop zone when unhealthy. See module docstring for the contract.
    """
    params = params or {}
    proxy_url = str(
        params.get("proxy_url") or os.environ.get("LITELLM_BASE_URL") or DEFAULT_PROXY_URL
    ).rstrip("/")
    api_key = str(
        params.get("api_key")
        or os.environ.get("LITELLM_API_KEY")
        or os.environ.get("LITELLM_MASTER_KEY")
        or ""
    )
    alert_path = Path(
        str(params.get("alert_path") or os.environ.get("LITELLM_HEALTH_ALERT_PATH") or DEFAULT_ALERT_PATH)
    )
    try:
        timeout = int(params.get("timeout_seconds") or DEFAULT_TIMEOUT_SECS)
    except (TypeError, ValueError):
        timeout = DEFAULT_TIMEOUT_SECS

    now = datetime.now(timezone.utc)
    _log(job, f"Probing {proxy_url}/health (timeout={timeout}s)")

    healthy, detail = _probe_health(proxy_url, api_key, timeout)
    report: dict[str, Any] = {
        "healthy": healthy,
        "reason": detail.get("reason", ""),
        "proxy_url": proxy_url,
        "checked_at": now.isoformat(),
        "healthy_endpoints": len(detail.get("healthy_endpoints") or []),
        "unhealthy_endpoints": [
            {
                "api_base": ep.get("api_base", "") if isinstance(ep, dict) else str(ep),
                "model": ep.get("model", "") if isinstance(ep, dict) else "",
                "error": _truncate(ep.get("error", "")) if isinstance(ep, dict) else "",
            }
            for ep in (detail.get("unhealthy_endpoints") or [])
        ],
        "alert_path": str(alert_path),
        "alert_written": False,
        "alert_removed": False,
    }

    if healthy:
        report["alert_removed"] = _remove_alert(alert_path)
        summary = (
            f"LiteLLM proxy healthy ({report['healthy_endpoints']} endpoint(s)) — "
            "no alert."
            + (" Alert removed." if report["alert_removed"] else "")
        )
        _log(job, summary)
    else:
        first_detected = _write_alert(alert_path, detail, proxy_url, now)
        report["alert_written"] = True
        report["first_detected"] = first_detected
        bad = ", ".join(
            f"{e['api_base']} ({e['model']})" for e in report["unhealthy_endpoints"]
        )
        summary = f"ALERT: {detail.get('reason')}" + (f" — {bad}" if bad else "")
        _log(job, summary)
        _log(job, f"Alert written to {alert_path} (first_detected={first_detected})")

    return {
        "summary": summary,
        "artifact_path": str(alert_path) if report["alert_written"] else None,
        "report": report,
    }


# ---------------------------------------------------------------------------
# Standalone CLI (testing / manual runs outside the runner)
# ---------------------------------------------------------------------------


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Probe the LiteLLM proxy /health endpoint and manage the "
        "public alert file (see skill docstring)."
    )
    parser.add_argument("--proxy-url", default=None, help="Override the proxy base URL.")
    parser.add_argument("--api-key", default=None, help="Override the LiteLLM key.")
    parser.add_argument("--alert-path", default=None, help="Override the alert file path.")
    parser.add_argument("--timeout", type=int, default=None, help="HTTP timeout seconds.")
    parser.add_argument("--quiet", action="store_true", help="Print only the summary.")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.WARNING if args.quiet else logging.INFO)

    params: dict[str, Any] = {}
    if args.proxy_url:
        params["proxy_url"] = args.proxy_url
    if args.api_key:
        params["api_key"] = args.api_key
    if args.alert_path:
        params["alert_path"] = args.alert_path
    if args.timeout:
        params["timeout_seconds"] = args.timeout

    result = run(params)
    if args.quiet:
        print(result["summary"])
        return 0 if result["report"]["healthy"] else 1
    print(json.dumps(result, indent=2))
    return 0 if result["report"]["healthy"] else 1


if __name__ == "__main__":
    sys.exit(main())
