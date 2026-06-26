# Data Module — Future Capabilities

This document captures the roadmap for features that can grow under `data/`
beyond Phase 1 (MySQL text-to-SQL + query execution).

---

## Connector Roadmap

Each new data source is a connector class implementing the same 3-4 methods
(`connect`, `discover_schema`, `execute_query`, `is_readonly`). The registry
wires them together so `/data/ask` can pick the right source or join across sources.

```
data/connectors/
├── base.py           # AbstractConnector
├── registry.py       # DataSourceRegistry (auto-discovery + Redis caching)
├── mysql.py          # ✅ Phase 1
├── postgres.py       # Phase 2 (LiteLLM spend, n8n runs, Ghost blog)
├── prometheus.py     # Phase 3 (homelab monitoring metrics → PromQL → tabular)
├── csv.py            # Phase 3 (local CSV/Excel → virtual table)
└── http_api.py       # Phase 4 (REST APIs → virtual tables)
```

---

## Data Sources — Existing in Your Stack

| Data Source | Database | Family Relevance | Example Query |
|---|---|---|---|
| invest-hub | MySQL | Portfolio holdings, transactions, stock prices, gains/losses | "How is AAPL doing?", "Show my returns this quarter" |
| Family expenses | MySQL | Groceries, dining, utilities, subscriptions | "What did we spend on food this month?" |
| LiteLLM spend | Postgres | API spend per user/key/model | "How much did we spend on AI this month?" |
| Prometheus | TSDB | CPU/memory/network for every container | "Which container uses the most RAM?" |
| n8n | Postgres | Workflow executions, success/failure rates | "Did the market research run yesterday?" |
| Ghost | Postgres | Blog posts, views, engagement | "How many people read my latest post?" |

## Data Sources — Future

| Source | Connector | Example Query |
|---|---|---|
| Home Assistant | postgres | "How much energy did we use this week?" |
| Enphase/SolarEdge | http_api | "How many kWh did we produce today?" |
| Plaid | http_api | "What's our net worth trend?" |
| Apple Health / Fitbit | http_api | "How many steps did we walk this month?" |
| GitHub | http_api | "Which repos had the most commits?" |
| OpenWebUI chat logs | mysql | "What topics does the family ask about most?" |
| UniFi/Network | http_api | "Who's hogging the bandwidth?" |

---

## Feature Roadmap

### 1. Data Upload / Ingestion (`/data/upload`)

- CSV/Excel upload → auto-create table + load data
- "Here's my grocery receipts, load them" → creates `grocery_receipts` table
- Auto-detect column types, create indexes
- Uses `csv.py` connector as a virtual table bridge

### 2. Data Transformation (`/data/transform`)

- "Pivot this data by month and category"
- "Normalize these currency values to USD"
- LLM describes the transform → harness generates SQL/Python → executes

### 3. Cross-Source Joining (`/data/join`)

- "Show my expenses vs. my solar savings by month" → joins family_expenses + solar data
- Registry understands how to query across multiple databases
- Results merged into unified tabular response

### 4. Time-Series Aggregation (`/data/timeseries`)

- Pre-built aggregations: daily/weekly/monthly rolling averages, YoY comparisons, moving averages
- Critical for investment + expense data (inherently time-series)
- Could be a connector method or service-level helper

### 5. Anomaly Detection (`/data/anomalies`)

- "Show me unusual spending this month" → statistical outlier detection
- "Did any stock drop more than expected?" → volatility-based anomaly on investments
- LLM suggests which anomalies look worth investigating

### 6. Scheduled Reports (`/data/reports`)

- Leverage existing Celery Beat scheduler
- "Every Monday morning, email the family a summary of last week's spending"
- "Monthly investment performance report as a PDF" (uses `creative/layout` engine)
- Could integrate with `creative/presentation` for slide decks

### 7. Data Governance / Audit (`/data/audit`)

- Log all queries run (who asked what, when)
- Rate limiting per user
- Query cost tracking (LLM tokens + DB query cost)
- Useful for monitoring family AI usage

### 8. Dashboard Builder (`/data/dashboards`)

- Combine multiple queries + charts into a single view
- "Build a family finance dashboard" → grid of charts (spending by category, trend line, investment returns)
- Reuses `creative/charts` + `creative/layout`
- Could be a persisted dashboard config in the DB

### 9. Natural Language Filtering (`/data/filter`)

- "Show only expenses over $100 from the last 3 months"
- Converts relative time expressions ("last month", "Q1", "year to date") into SQL date filters
- Could be built into the text-to-SQL prompt or a separate preprocessing step

### 10. Data Quality Checks (`/data/quality`)

- "Are there any duplicates in the expenses table?"
- "Show me rows where amount is negative"
- Auto-detect data issues and suggest fixes
- Useful after data upload or periodic maintenance

---

## Design Principles (Carried Forward)

1. **Read-only by default** — All connectors connect with read-only credentials. Write access requires explicit opt-in per connector + per query.
2. **Connector parity** — Every connector implements the same interface. The service layer doesn't care which backend is used.
3. **Auto-discovery** — The registry polls `INFORMATION_SCHEMA` (or equivalent) to find new tables. New data sources just "show up."
4. **Composability** — Data module works with existing `creative/charts`, `creative/layout`, `infra/scheduler`, and `channels/*`.
5. **Safety first** — Row limits, query timeouts, SQL injection validation, and audit logging are non-negotiable.
