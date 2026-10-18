# MCP Data-Hub Server

LLM access to the **data-hub** ingest/ETL service — a thin REST wrapper so any
LLM client (via the LiteLLM proxy) can drive ingestion and the categorization
review loop. LAN only, no auth (matches data-hub's by-design contract).

## Tools (10)

| Tool | Description | Parameters |
|---|---|---|
| `health` | data-hub liveness + counts + last load + pending files | _(none)_ |
| `ingest_file` | Ingest a CSV/TSV from the generic inbox (full ETL pipeline; file moved to `processed/`) | `filename` |
| `list_loads` | Recent load reports (ingest history) | `db` ("finance" default \| "hub"), `limit` (20) |
| `load_detail` | Full finance load report incl. issues | `load_id` |
| `pending_categories` | AI category suggestions awaiting review | _(none)_ |
| `list_categories` | Category tree with ids (for review edits) | _(none)_ |
| `suggest_categories` | Trigger one LiteLLM categorization suggestion pass | _(none)_ |
| `review_category` | Approve / reject / edit a pending suggestion | `suggestion_id`, `action`, `category_id?` |
| `list_datasets` | Generic dataset registry (hub db, v2a) | _(none)_ |
| `dataset_preview` | Latest rows from a dataset's target table | `name`, `limit` (50) |

### The categorization loop

`suggest_categories` → `pending_categories` → `review_category`
(`list_categories` first when editing to a different category). Approving a
suggestion creates an exact-payee rule, backfills prior uncategorized
transactions, and rebuilds the monthly summary.

### Ingest

`ingest_file` reads the file from the mounted inbox
(host `/home/chuck/data/finance/inbox/`, container `/inbox:ro`) and POSTs it to
`data-hub /api/ingest?source=inbox`. Adapter resolution: bank/tax adapters
claim first, then active `hub.datasets` `source_pattern` globs; unmatched
files come back `status="pending"` (left in the inbox). The returned load
report (rows new/updated/skipped, issues) is the thing to review.

## Configuration

| Environment Variable | Default | Description |
|---|---|---|
| `DATAHUB_URL` | `http://data-hub:8100` | data-hub base URL (ai-net service name) |
| `INBOX_DIR` | `/inbox` | Inbox dir mounted into the container (read-only) |
| `HTTP_TIMEOUT` | `60` | Default request timeout (s) |
| `INGEST_TIMEOUT` | `600` | Timeout for ingest + suggest (s) — LLM passes are slow |
| `MCPS_HOST` | `0.0.0.0` | Bind host |

## Verification

```bash
# handshake + tool list
docker compose -f compose/compose.mcp.yml up -d mcp_datahub
curl -sN http://localhost:8000/sse | head   # (or via the LiteLLM proxy)

# one read-only tool call each (safe): health, list_loads, list_datasets
# ingest_file with a scratch file only — never real bank exports during verification
```