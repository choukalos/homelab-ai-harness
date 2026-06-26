# Data Module — Implementation Plan

## Overview

A new `data/` feature module that lets family members ask natural-language questions
about their data (expenses, investments, any future datasets) and get SQL-backed
answers with optional charting. The module auto-discovers available databases/tables
so new datasets just "show up" when added.

---

## Phase 1: Core Module Structure

Create the module under `ai-harness/data/`:

```
data/
├── __init__.py
├── plan.md            # ← this file
├── future.md          # ← future data functions & connector roadmap
├── router.py           # FastAPI: /data/health, /data/datasets, /data/schema, /data/query, /data/ask, /data/chart
├── schemas.py          # Pydantic request/response models
├── service.py          # Text-to-SQL pipeline, query execution, result interpretation
├── prompts.py          # LLM prompt templates (SQL generation + result explanation)
└── connectors/
    ├── __init__.py
    ├── base.py          # Abstract connector interface (connect, query, discover_schema, is_readonly)
    ├── mysql.py         # MySQL connector with read-only enforcement
    └── registry.py      # Data source registry (auto-discovery + Redis caching)
```

### Endpoints

| Endpoint | Method | Purpose |
|---|---|---|
| `/data/health` | GET | Verify MySQL connectivity |
| `/data/datasets` | GET | List available databases, tables, and column summaries |
| `/data/schema` | POST | Return schema for a specific dataset (table list + columns + sample rows) |
| `/data/query` | POST | Execute a raw SQL query (read-only, with validation) |
| `/data/ask` | POST | Natural language → SQL → results → plain-language answer |
| `/data/chart` | POST | Natural language → SQL → results → chart image (uses existing `creative/charts`) |

---

## Phase 2: Connector & Safety Layer

### `data/connectors/mysql.py`

1. **Read-only user** — Dedicated MySQL user with `SELECT`-only privileges:
   ```sql
   CREATE USER 'ai_readonly'@'%' IDENTIFIED BY 'password';
   GRANT SELECT ON homelab.* TO 'ai_readonly'@'%';
   GRANT SELECT ON investorhub.* TO 'ai_readonly'@'%';
   FLUSH PRIVILEGES;
   ```

2. **Query validation** — Belt-and-suspenders:
   - Parse/regex confirm query starts with `SELECT` (or `EXPLAIN`)
   - Reject `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `CREATE`, `TRUNCATE`, `LOAD DATA`, `INTO OUTFILE/DUMPFILE`
   - Reject semicolons (SQL injection prevention)

3. **Row limits** — Enforce `LIMIT` if not present (default 10,000 max)

4. **Query timeout** — Kill queries after 30 seconds (`SET STATEMENT max_statement_time=30000`)

5. **Connection pool** — Reuse connections via `pymysql`

### `data/connectors/registry.py`

- On init (or cache refresh), query `INFORMATION_SCHEMA` to discover all databases/tables the read-only user can access
- Build a cached schema map: `{dbname: {tablename: [columns, types, sample]}}`
- Cache in Redis (existing `infra/core/cache`) with TTL ~5 min so new tables are picked up automatically

---

## Phase 3: Text-to-SQL Pipeline

### `data/service.py`

```
User: "How much did we spend on groceries last month?"

Step 1 — Dataset selection:
  → If user specifies a dataset ("in the expenses table"), use that
  → Otherwise, search all discovered schemas for relevant tables
  → Cache the schema context

Step 2 — Text-to-SQL (LLM call):
  → Feed the LLM: schema context + user question
  → Use prompts from prompts.py (MySQL-specific, safety-conscious)
  → Return validated SQL

Step 3 — Validation:
  → Parse SQL → confirm SELECT-only → check for injection → add LIMIT

Step 4 — Execution:
  → Run against MySQL with timeout + row limits
  → Return rows as list of dicts

Step 5 — Interpretation (LLM call):
  → Feed the LLM: original question + query results
  → Return plain-language answer with numbers highlighted
  → Suggest follow-up questions

Step 6 — Optional charting (for /data/chart):
  → If user asked for a chart, pipe results into creative/charts
  → Return chart URL + explanation
```

### `data/prompts.py`

Two prompt templates:
1. **SQL Generation** — Schema context + question → structured SQL
2. **Result Interpretation** — Question + results → plain English answer

---

## Phase 4: Config & Env Vars

### `infra/core/config.py` additions:

```python
DATA_MYSQL_HOST = os.getenv("DATA_MYSQL_HOST", "thor.local")
DATA_MYSQL_PORT = os.getenv("DATA_MYSQL_PORT", "3306")
DATA_MYSQL_USER = os.getenv("DATA_MYSQL_USER", "ai_readonly")
DATA_MYSQL_PASS = os.getenv("DATA_MYSQL_PASS", "")
DATA_MYSQL_DATABASES = os.getenv("DATA_MYSQL_DATABASES", "homelab,investorhub")
DATA_MAX_ROWS = int(os.getenv("DATA_MAX_ROWS", "10000"))
DATA_QUERY_TIMEOUT_MS = int(os.getenv("DATA_QUERY_TIMEOUT_MS", "30000"))
```

### `.env` additions:

```bash
DATA_MYSQL_USER=ai_readonly
DATA_MYSQL_PASS=<secure_password>
```

### `compose.ai-harness.yml` additions:

Add `DATA_MYSQL_*` env vars to all service blocks.

---

## Phase 5: OpenWebUI Integration

`channels/openwebui/data_tools.py` — following the existing HarnessBase pattern:

```python
class Tools(HarnessBase):
    def query_data(self, question: str, data_source: str = "") -> str:
        """Query family data using natural language."""
        # POST /data/ask

    def list_datasets(self) -> str:
        """List available data sources and tables."""
        # GET /data/datasets

    def chart_data(self, question: str, chart_type: str = "bar") -> str:
        """Query data and generate a chart in one step."""
        # POST /data/chart
```

Register in `channels/openwebui/README.md` alongside existing tool files.

---

## Phase 6: Siri Integration

Update `channels/siri/service.py`:

- Add intent detection patterns for expense/investment questions
- Add handler in `handle_siri_chat()` that calls `/data/ask`, `/data/datasets`, or `/data/chart`
- Format response for voice + display (short voice text, full display text)

---

## Phase 7: Tests

### `tests/smoke/test_data.sh`

- Health check (`GET /data/health`)
- Dataset listing (`GET /data/datasets`)
- Schema lookup (`POST /data/schema`)
- Raw query (`POST /data/query` with simple SELECT)
- Natural language ask (`POST /data/ask`)
- Chart generation (`POST /data/chart`)
- Safety: reject non-SELECT queries
- Safety: reject SQL injection patterns

### `tests/channels/test_openwebui.sh`

- Add data_tools endpoint tests

### `tests/channels/test_siri.sh`

- Add data-related Siri intent tests

### `tests/harness-smoke-test.sh`

- Add `test_data.sh` to the orchestrator

---

## Phase 8: Wiring It All Up

1. `app.py` — `app.include_router(data_router, prefix="/data", tags=["data"])`
2. `requirements.txt` — `pymysql` already present; may add `sqlparse` for AST validation
3. `compose.ai-harness.yml` — Add `DATA_MYSQL_*` env vars to all service blocks
4. `.env` — Add `DATA_MYSQL_USER` and `DATA_MYSQL_PASS`
5. MySQL — Create `ai_readonly` user with SELECT grants
6. `README.md` + `STRATEGY.md` — Document the new `data/` group

---

## Estimated Effort

| Step | Effort |
|---|---|
| Connector layer (base, mysql, registry) | 2-3h |
| Schemas + prompts | 1h |
| Service (text-to-SQL pipeline) | 3-4h |
| Router + app.py wiring | 1h |
| Config + env + compose | 1h |
| OpenWebUI data_tools.py | 2h |
| Siri intent + handler | 2h |
| Tests (smoke + channels + orchestrator) | 2h |
| MySQL ai_readonly user setup | 15min |
| Docs (README + STRATEGY) | 30min |
| **Total** | **~15-18 hours** |
