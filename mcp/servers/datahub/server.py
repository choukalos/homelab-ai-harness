#!/usr/bin/env python3
"""MCP Data-Hub Server — LLM access to the data-hub ingest/ETL API.

Thin REST wrapper over data-hub (LAN only, no auth by design) so any LLM
client can drive ingestion and the categorization review loop:

  - health()                     data-hub liveness + counts + last load
  - ingest_file(filename)        ingest a CSV/TSV from the generic inbox dir
  - list_loads(db, limit)        recent load_log rows (finance | hub)
  - load_detail(load_id)         full finance load report incl. issues
  - pending_categories()         AI suggestions awaiting review
  - list_categories()            category tree (ids needed for review edits)
  - suggest_categories()         trigger one LiteLLM suggestion pass
  - review_category(...)         approve / reject / edit a suggestion
  - list_datasets()              generic dataset registry (hub db, v2a)
  - dataset_preview(name, limit) latest rows from a dataset's target table

Backend: data-hub REST API at DATAHUB_URL (default http://data-hub:8100).
Inbox: files are read from INBOX_DIR (host /home/chuck/data/finance/inbox,
mounted read-only) and POSTed to data-hub, which runs the full ETL pipeline
(validation, idempotent upsert, load_log) and moves the file to processed/.
Transport: SSE (HTTP, default 0.0.0.0:8000, path /sse)
"""

import logging
import os
import re
from typing import Optional

import httpx
from mcp.server import FastMCP

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DATAHUB_URL: str = os.environ.get("DATAHUB_URL", "http://data-hub:8100").rstrip("/")
INBOX_DIR: str = os.environ.get("INBOX_DIR", "/inbox")
HTTP_TIMEOUT: float = float(os.environ.get("HTTP_TIMEOUT", "60"))
INGEST_TIMEOUT: float = float(os.environ.get("INGEST_TIMEOUT", "600"))
MCPS_HOST: str = os.environ.get("MCPS_HOST", "0.0.0.0")

# Sanitized filenames: alnum plus dot, dash, underscore (matches data-hub's
# ingest_upload sanitization). Also blocks path traversal.
_FILENAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

logger = logging.getLogger("mcp_datahub")


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _request(method: str, path: str, *, timeout: Optional[float] = None,
             json_body: Optional[dict] = None,
             files: Optional[dict] = None,
             params: Optional[dict] = None) -> dict:
    """Call the data-hub API; return parsed JSON body.

    Raises RuntimeError with a clear message on connection failure or
    non-2xx responses (the message includes the API's error detail).
    """
    url = f"{DATAHUB_URL}{path}"
    try:
        with httpx.Client(timeout=timeout or HTTP_TIMEOUT) as client:
            r = client.request(method, url, json=json_body, files=files,
                                params=params)
    except httpx.HTTPError as e:
        raise RuntimeError(f"cannot reach data-hub at {url}: {e}") from e

    try:
        body = r.json()
    except ValueError:
        body = {"raw": r.text[:2000]}
    if r.status_code >= 400:
        detail = body if isinstance(body, dict) else {"raw": body}
        err = detail.get("detail", detail)
        raise RuntimeError(f"data-hub {method} {path} -> {r.status_code}: {err}")
    return body


# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------

mcp = FastMCP(
    name="mcp_datahub",
    instructions=(
        "Data-hub: the homelab's ingest/ETL service for finance exports "
        "(bank CSVs, tax XLSX) and generic CSV/TSV datasets. Use ingest_file "
        "to load a new export from the inbox and check the returned load "
        "report (rows new/updated/skipped, issues). Use list_loads / "
        "load_detail to inspect past ingests. The categorization loop: "
        "suggest_categories -> pending_categories -> review_category "
        "(approve/reject/edit; call list_categories first to get category "
        "ids). list_datasets / dataset_preview cover the generic (hub db) "
        "datasets. LAN-only, no auth by design; bank data stays local."
    ),
    host=MCPS_HOST,
    port=8000,
)


@mcp.tool()
def health() -> dict:
    """Check data-hub liveness and current state.

    Returns: status, transaction count, total loads, last load summary
    (timestamp, file, status), pending files, and migration status.
    Use to verify data-hub is up before/after ingesting.
    """
    return _request("GET", "/api/health")


@mcp.tool()
def ingest_file(filename: str) -> dict:
    """Ingest a CSV/TSV file from the generic inbox into MySQL (data-hub ETL).

    Reads <INBOX_DIR>/<filename> (host: /home/chuck/data/finance/inbox/) and
    POSTs it to data-hub, which runs the full pipeline: adapter resolution
    (bank/tax adapters claim first, then active generic-dataset patterns),
    validation, idempotent upsert, load_log row. The file is moved to
    processed/ by data-hub.

    Args:
        filename: basename of the file in the inbox (e.g. "workapp-2026-10-18.csv").

    Returns:
        The load report: file, adapter, status (ok/partial/error),
        rows_total/rows_new/rows_updated, date range, and issues[] —
        review issues before considering the ingest clean.
        Status "pending" means no adapter/dataset claimed the file (it stays
        in the inbox; register a dataset or fix the source_pattern).
    """
    if not _FILENAME_RE.match(filename):
        raise RuntimeError(
            f"invalid filename {filename!r}: use alnum plus dot/dash/underscore"
        )
    path = os.path.join(INBOX_DIR, filename)
    if not os.path.isfile(path):
        available = sorted(os.listdir(INBOX_DIR)) if os.path.isdir(INBOX_DIR) else []
        raise RuntimeError(
            f"file {filename!r} not found in {INBOX_DIR}. Available: {available}"
        )
    with open(path, "rb") as f:
        data = f.read()
    logger.info("ingesting %s (%d bytes)", filename, len(data))
    return _request(
        "POST", "/api/ingest",
        timeout=INGEST_TIMEOUT,
        files={"file": (filename, data, "text/csv")},
        params={"source": "inbox"},
    )


@mcp.tool()
def list_loads(db: str = "finance", limit: int = 20) -> dict:
    """List recent load_log rows (ingest history).

    Args:
        db: "finance" (bank/tax loads, default) or "hub" (generic datasets).
        limit: max rows, most recent first (1-500, default 20).

    Returns:
        {"loads": [...]} — each row: id, ts, source_file, sha256, adapter,
        rows_total/new/updated/skipped, date range, status, issues (JSON).
    """
    if db not in ("finance", "hub"):
        raise RuntimeError("db must be 'finance' or 'hub'")
    limit = max(1, min(int(limit), 500))
    return _request("GET", "/api/loads", params={"db": db, "limit": limit})


@mcp.tool()
def load_detail(load_id: int) -> dict:
    """Get the full load report for one finance load (incl. issues).

    Args:
        load_id: the load_log id from list_loads(db="finance").

    Returns:
        The full load_log row: file, sha256, adapter, row counts, date
        range, status, and the issues[] JSON array.
        For hub (generic dataset) loads, use list_loads(db="hub") — those
        rows already carry the full report.
    """
    return _request("GET", f"/api/loads/{int(load_id)}")


@mcp.tool()
def pending_categories() -> dict:
    """AI category suggestions awaiting review (the review queue).

    Returns:
        Pending suggestions: each with suggestion id, payee, suggested
        category name + bucket, confidence, rationale, and the affected
        uncategorized txn count/amount. Feed these to review_category.
    """
    return _request("GET", "/api/categories/pending")


@mcp.tool()
def list_categories() -> dict:
    """Category tree with ids (needed to pick a category_id for edits).

    Returns:
        Nested tree (bucket roots -> children); each node has id, name,
        bucket, parent_id, txn_count, children, plus top-level totals and
        the uncategorized txn count.
    """
    return _request("GET", "/api/categories")


@mcp.tool()
def suggest_categories() -> dict:
    """Trigger one AI (LiteLLM) categorization suggestion pass.

    Asks the LLM to categorize payees that have uncategorized transactions
    and no pending suggestion yet; inserts pending rows for review. Can take
    a while (LLM batches). Call pending_categories afterwards.

    Returns:
        {"payees_found", "batches", "suggestions_inserted",
        "suggestions": [...], "llm": {calls, failures, model, errors}}.
    """
    return _request("POST", "/api/categories/suggest", timeout=INGEST_TIMEOUT)


@mcp.tool()
def review_category(suggestion_id: int, action: str,
                    category_id: Optional[int] = None) -> dict:
    """Review one pending category suggestion (approve / reject / edit).

    approve -> creates an exact-payee rule (source=ai), backfills prior
        uncategorized txns for that payee, rebuilds the monthly summary.
    reject  -> marks the suggestion rejected (no rule).
    edit    -> change the suggested category, then behaves like approve.
        category_id is REQUIRED for edit (see list_categories).

    Args:
        suggestion_id: id from pending_categories.
        action: "approve" | "reject" | "edit".
        category_id: target category id (required when action="edit").

    Returns:
        {"suggestion_id", "action", "status", "payee", "rule_id",
        "rows_backfilled", "summary_rebuilt"}.
    """
    if action not in ("approve", "reject", "edit"):
        raise RuntimeError("action must be 'approve', 'reject', or 'edit'")
    body = {"suggestion_id": int(suggestion_id), "action": action}
    if category_id is not None:
        body["category_id"] = int(category_id)
    return _request("POST", "/api/categories/review", json_body=body)


@mcp.tool()
def list_datasets() -> dict:
    """List the generic dataset registry (hub db, v2a).

    Returns:
        {"datasets": [...]} — each: name, description, source_pattern
        (filename glob the watcher matches), target_table, delimiter,
        has_header, column_map (frozen after first import), key_columns,
        is_active, and current row_count of the target table.
    """
    return _request("GET", "/api/datasets")


@mcp.tool()
def dataset_preview(name: str, limit: int = 50) -> dict:
    """Preview the latest rows of a generic dataset's target table.

    Args:
        name: dataset name from list_datasets.
        limit: max rows (1-500, default 50), newest first.

    Returns:
        {"dataset", "target_table", "count", "rows": [...]} — the most
        recent rows from the hub.ds_<name> table.
    """
    limit = max(1, min(int(limit), 500))
    return _request(
        "GET", f"/api/datasets/{name}/preview", params={"limit": limit}
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Run the mcp_datahub server over SSE transport (0.0.0.0:8000, /sse)."""
    logging.basicConfig(level=logging.INFO)
    logger.info("Starting mcp_datahub, datahub=%s, inbox=%s", DATAHUB_URL, INBOX_DIR)
    mcp.run(transport="sse")


if __name__ == "__main__":
    main()