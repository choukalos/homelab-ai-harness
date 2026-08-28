# MCP MySQL Server

Read-only MySQL database access with schema intelligence and natural-language-to-SQL translation via LiteLLM. Runs as an MCP server over streamable-http transport.

## Tools (11)

| Tool | Description | Parameters |
|---|---|---|
| `list_databases` | List user-accessible databases (excludes system DBs) | _(none)_ |
| `list_tables` | List tables in a given database | `database` (str) |
| `describe_table` | Show column definitions for a table | `database` (str), `table` (str) |
| `sample_table` | Sample rows from a table (≤100 rows) | `database` (str), `table` (str), `limit` (int, default 10) |
| `schema_overview` | **Full schema intelligence for a database**: every table with all columns, indexes, row counts, declared FKs, inferred soft relations, join graph, curated domain hints, and sample rows | `database` (str) |
| `run_query` | Execute a read-only SELECT query (EXPLAIN pre-flight) | `database` (str), `sql` (str) |
| `run_query_to_csv` | Execute a read-only SELECT and save results to a CSV file | `database` (str), `sql` (str), `output_path` (str) |
| `nl_to_sql_then_run` | Translate natural language to SQL via LiteLLM, then execute it | `database` (str), `natural_language` (str) |
| `explain_sql` | Run `EXPLAIN` on a query (read-only plan inspection) | `database` (str), `sql` (str) |
| `list_indexes` | List indexes on a table | `database` (str), `table` (str) |
| `foreign_keys` | List foreign keys for a table (outgoing + incoming) | `database` (str), `table` (str) |

## Schema intelligence (2026-08-28)

The NL-to-SQL prompt is built from `_build_schema_context()`, which gathers:

- **All tables, all columns** (no 15-column truncation), with types, NULL-ability, and defaults
- **Declared FKs** — the join graph the LLM uses to build multi-table queries
- **Inferred soft relations** — ORM-style `xxxId` reference columns that have no declared FK constraint (common in Prisma/TypeORM apps). These are surfaced as "soft relations" so join queries still work on FK-less databases
- **Join graph** — per-table list of joinable neighbors
- **Curated domain hints** — from `schema_hints.json` (see below)
- **Sample rows** — up to `SAMPLE_MAX_ROWS` (20) from each table (tables ≤100 rows) so the LLM sees real data shapes (tickers, date formats, fraction vs percent scales)

### Curated hints (`schema_hints.json`)

`mcp/servers/mysql/schema_hints.json` (mounted read-only at `/app/schema_hints.json`; edit + `docker compose up -d` to apply, no rebuild) holds per-database, per-table/domain hints the app owner curates. `investorhub` currently has 14 hints, e.g.:

- Returns are stored as **fractions** (0.31 = 31%), not percentages
- Use `adjClose` for return/performance calculations, not `close`
- Prefer the precomputed return tables (`SymbolYearReturn`, `SymbolAnnualReturn`, `SymbolDecadeReturn`) over recomputing from `PriceHistory`
- `year`/`decade` columns are integers, not dates
- Timestamps carry a 13:30/14:30 ET offset artifact — use `DATE()`
- `` `Index` `` is a MySQL reserved word — backtick it
- Portfolio value formulas (quantity × costBasis, etc.)
- App-internal tables to ignore (migrations, caches)

## Configuration

| Environment Variable | Default | Description |
|---|---|---|
| `MYSQL_HOST` | `thor.local` | MySQL hostname |
| `MYSQL_PORT` | `3306` | MySQL port |
| `MYSQL_USER` | `ai` | MySQL username |
| `MYSQL_PASSWORD` | _(required)_ | MySQL password |
| `MYSQL_DATABASE` | _(none)_ | Default database |
| `LITELLM_API_BASE` | `http://litellm-proxy:4000` | LiteLLM API base URL |
| `LITELLM_API_KEY` | `${LITELLM_API_KEY}` | LiteLLM API key |
| `LITELLM_MODEL` | `matrix-coder` | LiteLLM model for NL-to-SQL (Qwen3.6-27B via vLLM on Matrix) |
| `LITELLM_MAX_TOKENS` | `2000` | Max completion tokens for NL-to-SQL |
| `LITELLM_DISABLE_THINKING` | `true` | Pass `chat_template_kwargs: {enable_thinking: false}` — Qwen3 thinking models otherwise burn the token budget on reasoning and return empty content. Set `false` for models whose chat template rejects the kwarg |
| `SCHEMA_HINTS_PATH` | `/app/schema_hints.json` | Path to the curated hints file |
| `SAMPLE_MAX_ROWS` | `20` | Max sample rows per table in the NL-to-SQL context |
| `MCPS_HOST` | `0.0.0.0` | Bind address for streamable-http |

## Safety

- **Read-only enforcement (two layers)**:
  1. App-level regex blocks INSERT, UPDATE, DELETE, DROP, ALTER, CREATE, TRUNCATE, REPLACE, GRANT, REVOKE, SET (case-insensitive)
  2. `SET SESSION transaction_read_only=1` per session — the MySQL server itself rejects any write
- **EXPLAIN pre-flight** (on `run_query` / `nl_to_sql_then_run`): runs `EXPLAIN` first and rejects queries that are catastrophically expensive:
  - estimated total rows examined > `MAX_ROWS_EXAMINED` (default 100,000)
  - distinct tables joined > `MAX_JOIN_TABLES` (default 5)
  - any full-table-scan (`type='ALL'`) row with >100 estimated rows, when `BLOCK_FULL_TABLE_SCANS=true` (default)
- **Row limit**: Max 500 rows per query (`MAX_ROWS`)
- **Query timeout**: 30 seconds (`QUERY_TIMEOUT`)
- **System DB exclusion**: information_schema, mysql, performance_schema, sys excluded from listing
- **NL-to-SQL guard**: System prompt restricts output to SELECT-only queries; output is re-validated by the same regex before execution

### Safety knobs (env)

| Variable | Default | Description |
|---|---|---|
| `MAX_ROWS` | `500` | Max rows returned per query |
| `QUERY_TIMEOUT` | `30` | Query timeout (seconds) |
| `MAX_ROWS_EXAMINED` | `100000` | EXPLAIN pre-flight row-estimate cap |
| `MAX_JOIN_TABLES` | `5` | EXPLAIN pre-flight max distinct joined tables |
| `BLOCK_FULL_TABLE_SCANS` | `true` | Reject `type='ALL'` scans on tables >100 rows |

## Usage

### Docker Compose

Configured in `compose/compose.mcp.yml` (actual values):

```yaml
mcp_mysql:
  build:
    context: ../mcp/servers/mysql
  container_name: mcp_mysql
  environment:
    - MYSQL_HOST=thor.local
    - MYSQL_PORT=3306
    - MYSQL_USER=${AI_DB_USER}
    - MYSQL_PASSWORD=${AI_DB_PASS}
    - LITELLM_API_BASE=http://litellm-proxy:4000
    - LITELLM_API_KEY=${LITELLM_API_KEY}
    - LITELLM_MODEL=matrix-coder
    - CSV_OUTPUT_DIR=/home/chuck/data/media/csv
  volumes:
    - /home/chuck/data/media/csv:/home/chuck/data/media/csv
    - ../mcp/servers/mysql/schema_hints.json:/app/schema_hints.json:ro
  networks:
    - ai-net
```

### Local Development

```bash
cd mcp/servers/mysql
pip install -e .
MYSQL_PASSWORD=... LITELLM_API_KEY=... python server.py
```

### Python API

```python
from server import mcp  # FastMCP instance

# List databases
result = await mcp.call_tool("list_databases", {})

# Full schema intelligence
result = await mcp.call_tool("schema_overview", {"database": "investorhub"})

# NL-to-SQL
result = await mcp.call_tool("nl_to_sql_then_run", {
    "database": "investorhub",
    "natural_language": "Top 5 positions in the Growth Portfolio by cost basis?",
})
```

## Architecture

- FastMCP server over streamable-http (`/mcp` endpoint)
- `mysql.connector` for DB access (read-only session)
- `litellm.completion()` for NL-to-SQL (provider-prefixed model name, thinking disabled by default)
- Schema context built per NL-to-SQL call (introspection queries against the live DB)
- No public exposure — `ai-net` only