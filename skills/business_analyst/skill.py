#!/usr/bin/env python3
"""
business_analyst skill — natural-language business/product data analysis.

Purpose:
  Given a natural-language question and a database, analyze the data via
  the mcp_mysql MCP server (NL->SQL + execution), synthesize insights via
  LLM, and produce a Markdown report that includes the SQL used, the
  results, key insights, and suggested Grafana queries/dashboards.

  This is the "Business/Product Analyst" agent. It uses the existing
  databases as-is (homelab operational data, investorhub financial data).

Workflow:
  1. Validate inputs; resolve the target database.
  2. Fetch schema overview via mcp_mysql.schema_overview.
  3. Translate the question to SQL and execute via mcp_mysql.
     - Primary: nl_to_sql_then_run (NL->SQL + execute).
     - Fallback: run_query (retry the generated SQL) / explain_sql.
  4. Synthesize insights via LiteLLM (schema + SQL + results).
  5. Save the analysis as a Markdown artifact.
  6. Return summary, full report, SQL, row count, and artifact path.

Constraints:
  - Max runtime: 300 seconds.
  - Read-only: only SELECT queries (enforced by mcp_mysql), no writes.
  - All MCP calls go through LiteLLM — never direct MCP server access.
  - Output format: Markdown.
  - Artifacts saved to /home/chuck/data/media/analyses/

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
    os.environ.get("BUSINESS_ANALYST_ARTIFACT_DIR", "/home/chuck/data/media/analyses")
)
MAX_RUNTIME_SECS = int(os.environ.get("BUSINESS_ANALYST_MAX_RUNTIME", "300"))

LITELLM_BASE_URL = os.environ.get("LITELLM_BASE_URL", "http://localhost:4000")
LITELLM_API_KEY = os.environ.get("LITELLM_API_KEY", "")
MODEL_ALIAS = os.environ.get("BUSINESS_ANALYST_MODEL_ALIAS", "matrix-coder")

KNOWN_DATABASES = ["homelab", "investorhub"]
MAX_ROWS_FOR_LLM = 50
MAX_SCHEMA_CHARS = 6000

logger = logging.getLogger("skill.business_analyst")

# ---------------------------------------------------------------------------
# Timeout enforcement
# ---------------------------------------------------------------------------


class TimeoutError(Exception):
    """Raised when the skill exceeds its maximum runtime."""


def _timeout_handler(signum, frame):
    raise TimeoutError(f"business_analyst exceeded {MAX_RUNTIME_SECS}s max runtime")


def _install_timeout():
    if sys.platform != "win32" and threading.main_thread() is threading.current_thread():
        signal.signal(signal.SIGALRM, _timeout_handler)
        signal.alarm(MAX_RUNTIME_SECS)


def _cancel_timeout():
    if sys.platform != "win32" and threading.main_thread() is threading.current_thread():
        signal.alarm(0)


# ---------------------------------------------------------------------------
# LiteLLM client abstraction
# ---------------------------------------------------------------------------


class _SyncLiteLLMClient:
    """Synchronous LiteLLM client for standalone/CLI use."""

    def __init__(self, base_url: Optional[str] = None, api_key: Optional[str] = None) -> None:
        self.base_url = (base_url or LITELLM_BASE_URL).rstrip("/")
        self.api_key = api_key or LITELLM_API_KEY

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def chat_completion(self, model: str, messages: list[dict[str, str]], **kwargs: Any) -> dict[str, Any]:
        import urllib.request
        import urllib.error

        payload: dict[str, Any] = {"model": model, "messages": messages}
        payload.update(kwargs)
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/v1/chat/completions",
            data=data, headers=self._headers(), method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=240) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace") if exc.fp else str(exc)
            raise RuntimeError(f"LiteLLM HTTP error {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Cannot reach LiteLLM at {self.base_url}: {exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Invalid JSON from LiteLLM: {exc}") from exc

    def mcp_call(self, tool_name: str, arguments: dict[str, Any],
                 server_id: Optional[str] = None, **kwargs: Any) -> dict[str, Any]:
        import urllib.request
        import urllib.error

        payload: dict[str, Any] = {"name": tool_name, "arguments": arguments}
        if server_id:
            payload["server_id"] = server_id
        payload.update(kwargs)
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/mcp-rest/tools/call",
            data=data, headers=self._headers(), method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
            logger.warning("MCP tool call via LiteLLM failed (%s): %s", tool_name, body)
            return {}
        except urllib.error.URLError as exc:
            logger.warning("Cannot reach LiteLLM for MCP tool %s: %s", tool_name, exc)
            return {}
        except json.JSONDecodeError as exc:
            logger.warning("Invalid JSON from LiteLLM MCP call: %s", exc)
            return {}


class _SyncAsyncWrapper:
    """Wraps an async LiteLLMClient from the runner so skill code can call it sync."""

    def __init__(self, async_client):
        self._client = async_client
        self.base_url = getattr(async_client, "base_url", LITELLM_BASE_URL)

    def chat_completion(self, model, messages, **kwargs):
        import asyncio
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(self._client.chat_completion(model, messages, **kwargs))
        finally:
            loop.close()

    def mcp_call(self, tool_name, arguments, server_id=None, **kwargs):
        import asyncio
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(
                self._client.mcp_call(tool_name, arguments, server_id=server_id, **kwargs)
            )
        finally:
            loop.close()


def _resolve_litellm_client(litellm_client=None) -> Any:
    if litellm_client is None:
        return _SyncLiteLLMClient()
    if hasattr(litellm_client, "chat_completion") and hasattr(litellm_client, "mcp_call"):
        import inspect
        if inspect.iscoroutinefunction(litellm_client.chat_completion):
            return _SyncAsyncWrapper(litellm_client)
        return litellm_client
    return _SyncLiteLLMClient()


# ---------------------------------------------------------------------------
# Robust MCP response parsing
# ---------------------------------------------------------------------------


def _parse_text_payload(result: Any) -> Optional[dict]:
    """Parse the primary JSON payload from an mcp_mysql MCP response."""
    if not result:
        return None

    res = result.get("result")
    if isinstance(res, dict):
        return res
    if isinstance(res, list) and res and isinstance(res[0], dict):
        return res[0]

    for key in ("output", "content"):
        items = result.get(key)
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict) and item.get("type") == "text":
                    text = item.get("text", "")
                    try:
                        parsed = json.loads(text)
                    except (json.JSONDecodeError, TypeError):
                        continue
                    if isinstance(parsed, dict):
                        return parsed
                    if isinstance(parsed, list) and parsed and isinstance(parsed[0], dict):
                        return parsed[0]

    if isinstance(result, dict) and ("sql" in result or "rows" in result
                                     or "results" in result or "data" in result):
        return result
    return None


def _extract_rows(payload: Optional[dict]) -> list[dict]:
    if not payload:
        return []
    for key in ("rows", "results", "data", "items"):
        val = payload.get(key)
        if isinstance(val, list):
            return [r for r in val if isinstance(r, dict)]
    return []


def _extract_sql(payload: Optional[dict]) -> Optional[str]:
    if not payload:
        return None
    sql = payload.get("sql")
    if isinstance(sql, str) and sql.strip():
        return sql.strip()
    return None


def _extract_error(payload: Optional[dict]) -> Optional[str]:
    if not payload:
        return None
    for key in ("error", "execution_error"):
        val = payload.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return None


def _mcp(client: Any, tool: str, arguments: dict, server_id: str = "mcp_mysql") -> dict:
    """Call an mcp_mysql tool and return the parsed payload dict (or {})."""
    raw = client.mcp_call(tool, arguments, server_id=server_id)
    return _parse_text_payload(raw) or {}


# ---------------------------------------------------------------------------
# Database resolution
# ---------------------------------------------------------------------------


def _resolve_database(client: Any, requested: Optional[str]) -> Optional[str]:
    """Resolve the target database name."""
    if requested and requested.strip():
        return requested.strip()
    try:
        payload = _mcp(client, "list_databases", {})
        names = []
        res = payload.get("result") if isinstance(payload, dict) else None
        if isinstance(res, list):
            names = [r.get("name") for r in res if isinstance(r, dict) and r.get("name")]
        elif isinstance(payload, list):
            names = [r.get("name") for r in payload if isinstance(r, dict) and r.get("name")]
        if not names:
            for name in KNOWN_DATABASES:
                if name in json.dumps(payload):
                    names = [name]
                    break
        for preferred in ("investorhub", "homelab"):
            if preferred in names:
                return preferred
        return names[0] if names else None
    except Exception as exc:
        logger.warning("Could not list databases: %s", exc)
        return KNOWN_DATABASES[0]


# ---------------------------------------------------------------------------
# Schema overview
# ---------------------------------------------------------------------------


def _get_schema_overview(client: Any, database: str) -> str:
    """Fetch and compact the schema overview for the LLM context."""
    try:
        payload = _mcp(client, "schema_overview", {"database": database})
        if not payload:
            return "(schema overview unavailable)"
        text = json.dumps(payload, indent=2, default=str)
        if len(text) > MAX_SCHEMA_CHARS:
            text = text[:MAX_SCHEMA_CHARS] + "\n…(truncated)"
        return text
    except Exception as exc:
        logger.warning("schema_overview failed: %s", exc)
        return "(schema overview unavailable)"


# ---------------------------------------------------------------------------
# Query execution (with fallback)
# ---------------------------------------------------------------------------


def _run_analysis_query(client: Any, database: str, question: str) -> dict:
    """Translate the question to SQL and execute it. Returns {sql, rows, error, method}."""
    payload = _mcp(client, "nl_to_sql_then_run",
                   {"database": database, "question": question})
    sql = _extract_sql(payload)
    rows = _extract_rows(payload)
    error = _extract_error(payload)

    if rows:
        return {"sql": sql, "rows": rows, "error": None, "method": "nl_to_sql_then_run"}

    if sql:
        try:
            retry = _mcp(client, "run_query", {"database": database, "sql": sql})
            retry_rows = _extract_rows(retry)
            retry_error = _extract_error(retry)
            if retry_rows:
                return {"sql": sql, "rows": retry_rows, "error": None,
                        "method": "run_query (retry)"}
            return {"sql": sql, "rows": [], "error": retry_error or error,
                    "method": "run_query (retry)"}
        except Exception as exc:
            logger.warning("run_query retry failed: %s", exc)

    if not sql:
        payload2 = _mcp(client, "explain_sql",
                        {"database": database, "natural_language": question})
        sql = _extract_sql(payload2)
        rows = _extract_rows(payload2)
        error = _extract_error(payload2) or error
        if rows:
            return {"sql": sql, "rows": rows, "error": None, "method": "explain_sql"}

    return {"sql": sql, "rows": rows, "error": error, "method": "nl_to_sql_then_run"}


# ---------------------------------------------------------------------------
# LLM synthesis
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = textwrap.dedent("""\
    You are a business/product data analyst. You interpret SQL query results
    and turn them into clear, actionable insights. You are rigorous about
    what the data actually shows vs. what is assumed.

    You will be given:
      1. The natural-language question.
      2. The database and schema overview.
      3. The SQL that was executed.
      4. The query results (rows).

    Produce a Markdown analysis report with these sections:

    ## Key Insights
    - 3-5 bullet points of the most important takeaways. Be specific with
      numbers from the data. Highlight trends, outliers, or anomalies.

    ## Interpretation
    - 2-4 sentences of plain-English interpretation of what this means.
      Distinguish fact (from the data) from inference.

    ## Suggested Follow-ups
    - 2-3 follow-up questions or deeper analyses worth running next.

    ## Grafana Suggestions
    - 1-3 concrete Grafana panel/query ideas to visualize this data
      (metric, dimensions, chart type). Keep them specific to the schema.

    Rules:
    - Ground every claim in the actual result rows.
    - If the query returned an error or no rows, say so clearly and suggest
      how to fix it (better WHERE clause, different table, etc.).
    - Output ONLY the Markdown report body (the sections above) — no H1
      title, no preamble, no JSON wrapper.
""")


def _format_rows(rows: list[dict], max_rows: int = 20) -> str:
    """Format result rows as a Markdown table."""
    if not rows:
        return "(No rows returned.)"
    cols = list(rows[0].keys())
    for r in rows[1:]:
        for k in r.keys():
            if k not in cols:
                cols.append(k)
    lines = ["| " + " | ".join(cols) + " |",
             "| " + " | ".join(["---"] * len(cols)) + " |"]
    for r in rows[:max_rows]:
        cells = []
        for c in cols:
            val = r.get(c, "")
            val = "" if val is None else str(val)
            if len(val) > 40:
                val = val[:37] + "…"
            val = val.replace("|", "\\|").replace("\n", " ")
            cells.append(val)
        lines.append("| " + " | ".join(cells) + " |")
    if len(rows) > max_rows:
        lines.append(f"\n_(showing {max_rows} of {len(rows)} rows)_")
    return "\n".join(lines)


def _synthesize_report(client: Any, question: str, database: str, schema: str,
                       sql: Optional[str], rows: list[dict],
                       error: Optional[str]) -> str:
    """Synthesize the analysis report body via LLM."""
    rows_block = _format_rows(rows, max_rows=MAX_ROWS_FOR_LLM)

    user_content = textwrap.dedent(f"""\
        # Question
        {question}

        # Database
        {database}

        # Schema Overview
        {schema}

        # SQL Executed
        {sql or "(no SQL generated)"}

        # Query Error
        {error or "(none)"}

        # Query Results
        {rows_block}

        Write the analysis report now. Output ONLY the Markdown sections.
    """)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]

    result = client.chat_completion(
        MODEL_ALIAS,
        messages,
        max_tokens=4000,
        temperature=0.3,
        stream=False,
    )

    choices = result.get("choices", [])
    if not choices:
        return "## Key Insights\n\n*(No analysis generated — LLM returned no content.)*\n"
    content = (choices[0].get("message") or {}).get("content")
    if not content:
        return "## Key Insights\n\n*(No analysis generated — LLM returned empty content.)*\n"
    return content.strip()


# ---------------------------------------------------------------------------
# Artifact generation
# ---------------------------------------------------------------------------


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9\-]+", "-", value).strip("-").lower()
    return slug[:60] or "analysis"


def _write_artifact(report: str, slug: str) -> Optional[str]:
    try:
        ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
        filename = f"analysis_{ts}_{slug}.md"
        path = ARTIFACT_DIR / filename
        path.write_text(report, encoding="utf-8")
        logger.info("Artifact written: %s", path)
        return str(path)
    except OSError as exc:
        logger.error("Could not write artifact: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------


def run(params: dict[str, Any], job, litellm_client=None) -> dict[str, Any]:
    """
    Execute the business_analyst skill.

    Args:
        params: Skill parameters (prompt, database).
        job: The runner Job object for logging.
        litellm_client: Optional LiteLLM client from the runner.

    Returns:
        Dict with 'summary', 'report', 'sql', 'row_count', 'rows',
        'database', 'query_method', 'query_error', 'artifact_path',
        'model_alias'.
    """
    client = _resolve_litellm_client(litellm_client)

    question = str(params.get("prompt") or "").strip()
    if not question:
        if hasattr(job, "add_log"):
            job.add_log("Validation failed: missing 'prompt' (question)")
        return {"error": "Missing required 'prompt' parameter (question)"}

    database = _resolve_database(client, str(params.get("database") or "").strip() or None)
    if not database:
        if hasattr(job, "add_log"):
            job.add_log("Could not resolve a database")
        return {"error": "Could not resolve a target database"}

    if hasattr(job, "add_log"):
        job.add_log(f"Executing business_analyst: database='{database}'")
        job.add_log(f"Question: {question[:80]}")
        job.add_log(f"Model alias: {MODEL_ALIAS}")
        job.add_log(f"LiteLLM: {client.base_url}")

    _install_timeout()

    try:
        # Phase 1: Schema overview
        if hasattr(job, "add_log"):
            job.add_log("Phase 1: fetching schema overview...")
        schema = _get_schema_overview(client, database)
        if hasattr(job, "add_log"):
            job.add_log(f"Schema overview: {len(schema)} chars")

        # Phase 2: NL->SQL + execute
        if hasattr(job, "add_log"):
            job.add_log("Phase 2: translating question to SQL and executing...")
        query_result = _run_analysis_query(client, database, question)
        sql = query_result.get("sql")
        rows = query_result.get("rows", [])
        error = query_result.get("error")
        if hasattr(job, "add_log"):
            job.add_log(f"Query method: {query_result.get('method')}")
            job.add_log(f"SQL: {sql or '(none)'}")
            job.add_log(f"Rows: {len(rows)}; error: {error or '(none)'}")

        # Phase 3: Synthesize insights via LLM
        if hasattr(job, "add_log"):
            job.add_log("Phase 3: synthesizing insights via LLM...")
        report_body = _synthesize_report(
            client, question, database, schema, sql, rows, error
        )

        # Assemble the full report
        header = (
            f"# Analysis — {question[:70]}\n\n"
            f"> Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} · "
            f"Database: {database} · Model: {MODEL_ALIAS} · Rows: {len(rows)}\n\n"
        )
        query_section = (
            "## Query\n\n"
            f"```sql\n{sql or '(no SQL generated)'}\n```\n\n"
        )
        if error:
            query_section += f"> **Query error:** {error}\n\n"
        results_section = f"## Results\n\n{_format_rows(rows, max_rows=20)}\n\n"
        full_report = header + query_section + results_section + report_body

        if hasattr(job, "add_log"):
            job.add_log(f"Report generated ({len(full_report)} chars)")

        # Phase 4: Save artifact
        artifact_path = _write_artifact(full_report, _slugify(question))
        if hasattr(job, "add_log"):
            job.add_log(f"Artifact saved: {artifact_path or '(inline only)'}")

        summary_lines = [l for l in full_report.strip().split("\n") if l.strip()][:5]
        summary = " ".join(l.strip() for l in summary_lines).strip()

        if hasattr(job, "add_log"):
            job.add_log(f"business_analyst completed: {len(full_report)} chars")

        return {
            "summary": summary,
            "report": full_report,
            "sql": sql,
            "row_count": len(rows),
            "rows": rows[:MAX_ROWS_FOR_LLM],
            "database": database,
            "query_method": query_result.get("method"),
            "query_error": error,
            "artifact_path": artifact_path,
            "model_alias": MODEL_ALIAS,
        }

    except TimeoutError as exc:
        msg = str(exc)
        if hasattr(job, "add_log"):
            job.add_log(f"Timeout: {msg}")
        return {
            "summary": f"Analysis timed out after {MAX_RUNTIME_SECS}s.",
            "error": msg,
            "model_alias": MODEL_ALIAS,
        }

    except RuntimeError as exc:
        msg = str(exc)
        if hasattr(job, "add_log"):
            job.add_log(f"Runtime error: {msg}")
        return {"summary": f"Analysis failed: {msg}", "error": msg, "model_alias": MODEL_ALIAS}

    except Exception as exc:
        msg = f"Unexpected error: {exc}"
        if hasattr(job, "add_log"):
            job.add_log(msg)
        return {"summary": f"Analysis failed: {msg}", "error": msg, "model_alias": MODEL_ALIAS}

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


def main():
    """Standalone test entrypoint."""
    import argparse

    parser = argparse.ArgumentParser(description="business_analyst standalone test")
    parser.add_argument("--prompt", required=True, help="Natural-language question")
    parser.add_argument("--database", default=None, help="Target database (default: auto-detect)")
    parser.add_argument("--dry-run", action="store_true", help="Print params without calling services")
    parser.add_argument("--base-url", default=None, help=f"LiteLLM base URL (default: {LITELLM_BASE_URL})")
    parser.add_argument("--api-key", default=None, help="LiteLLM API key")
    args = parser.parse_args()

    if args.dry_run:
        print("=== DRY RUN ===")
        print(f"  Question: {args.prompt}")
        print(f"  Database: {args.database or '(auto-detect)'}")
        print(f"  Model: {MODEL_ALIAS}")
        print(f"  Max runtime: {MAX_RUNTIME_SECS}s")
        print(f"  Artifact dir: {ARTIFACT_DIR}")
        print(f"  LiteLLM: {LITELLM_BASE_URL}")
        print(f"  Known databases: {KNOWN_DATABASES}")
        return

    client = _SyncLiteLLMClient(base_url=args.base_url or LITELLM_BASE_URL,
                                api_key=args.api_key or LITELLM_API_KEY)
    params = {"prompt": args.prompt, "database": args.database}
    result = run(params, _MockJob(), litellm_client=client)

    print("\n--- business_analyst response ---")
    print(f"Summary: {result.get('summary', 'N/A')[:300]}")
    print(f"Database: {result.get('database', 'N/A')}")
    print(f"SQL: {result.get('sql', 'N/A')}")
    print(f"Rows: {result.get('row_count', 0)}")
    if result.get("query_error"):
        print(f"Query error: {result['query_error']}")
    if result.get("artifact_path"):
        print(f"Artifact: {result['artifact_path']}")
    if result.get("error"):
        print(f"Error: {result['error']}")
    print(f"Report length: {len(result.get('report', ''))} chars")


if __name__ == "__main__":
    main()