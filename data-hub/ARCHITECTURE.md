# Data-Hub + Report-Hub — Architecture & Scope

Status: **phase 0 built** (2026-10-17); phases 1–2 waiting on sample files
Access: homelab LAN only, **no auth** (by design)
Code: two GitHub repos cloned at `/home/chuck/workspace/code/{data-hub,report-hub}`
Ports: data-hub `:8100`, report-hub `:8101` (LAN only, not on cloudflared)

## 1. Goals

1. Ingest CSV/XLSX exports (bank transactions, tax records; later: generic
   datasets) into MySQL.
2. ETL with provenance, idempotency, validation, and **issue-surfacing at
   ingest time** (manual ingest on purpose — problems get caught and
   reviewed as they happen).
3. Code-managed schema migrations.
4. A **generic** reporting UI: dashboards composed of labeled text, charts
   (bar/column/pie), and paginated tables (250 rows/page) — usable for any
   data in MySQL, not just finance.
5. **Read-only contract**: the reporting UI has no login and no editing.
   All report content (queries, dashboards, cards) is created/managed by
   the AI inserting rows into the `reports` database. Documented in the
   report-hub README.
6. AI Q&A over the data via the existing `mcp_mysql` MCP server (any LLM
   client).
7. Two containers, two repos: **data-hub** (data plane: ingest/ETL/
   migrations — the only writer) and **report-hub** (presentation plane:
   swappable read-only renderer).

## 2. Component diagram

```
 Bank CSVs / tax XLSX / (future datasets)
      │  doors:
      │   • POST http://thor.local:8100/api/ingest  (curl from any machine)
      │   • drop files into /home/chuck/data/finance/{bank,bank-raw,tax}/
      │     (watched; processed files moved to processed/)
      ▼
┌────────────────────────────────────────────────────────┐
│ CONTAINER 1: data-hub  (Python 3.14 / FastAPI, :8100) │  repo: data-hub
│  • inbox watcher + ingest API                          │
│  • source adapters: bank_csv, tax_xlsx (+ generic v2)  │
│  • staging → canonical, idempotent upserts             │
│  • validation + load_log (provenance, issues)          │
│  • categorization rules + AI suggestions + review API  │
│  • versioned SQL migrations (auto-apply on start)      │
└────────────────────────────────────────────────────────┘
      │ writes (dh_app — ONLY writer)   ▲ reads (dh_reports, SELECT-only)
      ▼                                 │
┌──────────────┐              ┌─────────┴──────────────────────────┐
│ MySQL 8.4    │              │ CONTAINER 2: report-hub (:8101)    │  repo: report-hub
│ • finance db │              │  (FastAPI + Jinja2 + ECharts)      │
│ • reports db │              │  • dashboards = cards on one page  │
└──────────────┘              │  • cards: label | table | chart    │
      ▲                       │  • saved SQL queries               │
      │ reads (ai@%)          │  • strictly READ-ONLY: no login,   │
┌─────┴──────────────┐        │    no edit endpoints; content is   │
│ mcp_mysql (exists) │        │    AI-managed via reports.* rows   │
│ AI Q&A, NL→SQL     │        └────────────────────────────────────┘
└────────────────────┘
      ▲
      │ any LLM client (LiteLLM proxy)
```

Key decisions:
- **Report metadata (queries/dashboards/cards) lives in MySQL** (`reports`
  db), not in the container → report-hub is a stateless renderer, fully
  swappable later.
- **Read-only contract** (documented in report-hub README): the UI performs
  no writes; the AI is the editor. The query engine still enforces
  SELECT-only, row caps, and timeouts as defense in depth.
- **data-hub is the only writer** to `finance.*`.
- **Manual ingest** in v1: every ingest returns a report (rows
  new/updated/skipped, date range, amounts, issues) and queues pending
  category suggestions for review — our categorization loop.

## 3. Container 1: data-hub (repo: `data-hub`)

### 3.1 Responsibilities
- **Ingest doors**: `POST /api/ingest` (multipart; optional source hint) and
  a watcher on the finance data dirs (see `sources.yaml`); processed files
  moved to `processed/` with a timestamp.
- **Source adapters** (registry, one per file format):
  - `bank_csv` — current categorized exports **and** older raw historical
    CSVs (poor/missing categories load fine; categorized later via rules +
    AI suggestions).
  - `tax_xlsx` — one sheet, one row per year → `tax_years` (upsert by year).
  - `generic` (v2) — CSV/TSV → flexible import into tables in a database.
- **ETL pipeline**: raw rows → validation (counts, date ranges, amount
  sanity, in-file dups) → transform → canonical upsert. Idempotency:
  `content_hash = sha256(account_id|txn_date|amount_cents|payee)`; newer
  exports win for mutable fields (description, external_txn_id). Overlapping
  files are safe.
- **load_log**: file, sha256, adapter, rows total/new/updated/skipped, date
  range, status, `issues[]` JSON — the ingest report.
- **Categorization**: rules (`payee pattern → category`), AI-suggested
  categories for unmatched payees (via LiteLLM), review API; approved
  suggestions become rules and backfill prior uncategorized transactions.
- **Migrations**: versioned SQL (`migrations/finance/0001_init.sql`, …),
  tracked in `schema_migrations`, auto-applied at container start.

### 3.2 API
| Method | Path | Purpose |
|---|---|---|
| POST | `/api/ingest` | upload file (multipart) — phase 1 |
| GET | `/api/loads` | load log (`?limit=`) |
| GET | `/api/loads/{id}` | load detail incl. issues |
| GET | `/api/categories` | category tree — phase 2 |
| GET | `/api/categories/pending` | AI suggestions awaiting review — phase 2 |
| POST | `/api/categories/review` | approve / reject / edit — phase 2 |
| POST | `/api/migrate` | apply pending migrations |
| GET | `/api/health` | liveness + counts + last load |

### 3.3 finance schema (v1, `migrations/finance/0001_init.sql`)
- `accounts(id, name, institution, type, currency, is_active)`
- `transactions(id, account_id, txn_date, amount_cents, payee, description,
  category_id, external_txn_id, content_hash UNIQUE, source_file,
  imported_at, updated_at)` — integer cents; dedupe via content_hash.
- `categories(id, name, parent_id, bucket, sort_order)` — buckets: Housing,
  Utilities, Kids, Food, Transport, Health, Leisure, Savings, Income, Taxes,
  Other.
- `category_rules(id, pattern, match_type, category_id, source manual|ai)`
- `category_suggestions(id, payee, suggested_category_id, confidence,
  rationale, status pending|approved|rejected, reviewed_at)`
- `tax_years(year PK, income_cents, income_tax_paid_cents,
  savings_est_cents, savings_rate, notes)`
- `load_log(id, ts, source_file, sha256, adapter, rows_*, date_min/max,
  status, issues JSON)`
- `monthly_category_summary(year, month, category_id, amount_cents,
  txn_count)` — materialized, rebuilt after each ingest.

### 3.4 Ingest report (example, surfaced to chuck after each ingest)
```
Ingest: bank/chase_2026-01..2026-06.csv (sha256: 9f2c…)
  Rows: 1,204 | New: 312 | Updated: 0 | Skipped (dup): 892
  Date range: 2026-01-02 → 2026-06-30
  Cash flow: −$8,412.23 spend / +$4,100.00 deposits
  Issues:
    - 3 rows missing payee → Uncategorized
    - 14 new payees → pending category suggestions
```

## 4. Container 2: report-hub (repo: `report-hub`)

### 4.1 Tech
Python/FastAPI, server-rendered Jinja2 (minimal JS), **ECharts** vendored
locally (offline). No SPA build step. No auth. LAN only.

### 4.2 Generic capabilities (v1)
- **Saved query**: named SQL (SELECT-only, enforced row cap + timeout) with
  optional params.
- **Card types**:
  - `label` — heading/text or KPI (single-value query + optional MoM/YoY
    delta), levels 1–4.
  - `table` — query → paginated table, **250 rows/page** (configurable to
    1000), per-column format (currency/date/number/text) and hide.
  - `chart` — query → ECharts bar / column / pie (option JSON; legend
    show/hide, series names/colors/visibility all in the option).
- **Dashboard**: ordered cards on one page, title + description.
- **Swappable**: all state in MySQL `reports` db.

### 4.3 reports schema (v1, `migrations/reports/0001_init.sql`)
- `queries(id, name UNIQUE, sql_text, params JSON, description, timestamps)`
- `dashboards(id, slug UNIQUE, title, description, layout JSON, is_active)`
- `cards(id, dashboard_id, position, type label|table|chart, title,
  query_id, config JSON, timestamps)` — config shapes documented in the
  migration + report-hub README.

### 4.4 API (all read-only)
| Method | Path | Purpose |
|---|---|---|
| GET | `/` | dashboard index |
| GET | `/d/{slug}?page=N` | render dashboard |
| GET | `/api/health` | liveness |
| GET | `/api/dashboards` | list dashboards |
| GET | `/api/dashboards/{slug}/cards` | card list + config |
| GET | `/api/queries` | saved queries |
| POST | `/api/queries/{id}/run` | run saved query (`page`, `page_size`, `sort`) |
| POST | `/api/preview` | ad-hoc SELECT, AI scratch work (500-row cap) |

## 5. v1 dashboards (finance, built on the generic engine)

1. **Overview** — KPI labels (month spend, YoY %, savings rate, kid spend),
   monthly spend bar (24 mo), top-category pie, monthly totals table.
2. **Category drill-down** — category filter → monthly trend, payee table
   (paginated 250), category totals.
3. **Kid costs** — college + HS-senior buckets; monthly + cumulative; YoY.
   Answers "is it the kids?": kid-bucket share of total spend over time.
4. **Tax & savings** — from `tax_years`: income, tax paid, savings est.,
   savings rate.
5. **Data health** — load_log table, pending category suggestions (review
   list), MoM/YoY watch metrics with threshold highlighting (v1 stand-in
   for alerts; n8n push = v2).

## 6. MySQL users & grants (one-time: `provision.sh`)

| User | Access | Used by |
|---|---|---|
| `dh_app` | ALL on `finance.*` | data-hub (only writer to finance data) |
| `dh_reports` | SELECT on `finance.*`, ALL on `reports.*` | report-hub |
| `ai` (existing) | + SELECT on `finance.*` | mcp_mysql (AI Q&A) |

Passwords in `homelab/.env` (`DH_APP_PASS`, `DH_REPORTS_PASS`).
Run: `bash /home/chuck/homelab/data-hub/provision.sh` (renders SQL from
`homelab/.env`, pipes to `sudo mysql`; no plaintext password file on disk).

## 7. AI integration

- **Q&A**: existing `mcp_mysql` (NL→SQL, read-only) — `finance` granted to
  `ai`; add `finance` entries to `schema_hints.json` (cents units, buckets,
  kid categories, `tax_years`, prefer `monthly_category_summary` for
  trends) — phase 4.
- **Management**: AI drives data-hub + report-hub via their REST APIs and
  direct SQL on `reports.*` (the read-only contract makes the AI the sole
  editor).
- **Categorization**: data-hub calls LiteLLM for payee→category suggestions.
- **v2**: `mcp_datahub` MCP server wrapping ingest/loads/review.

## 8. Security / ops

- No auth (LAN only; not on cloudflared in v1).
- SQL safety: `dh_reports` is SELECT-only on finance; query engine enforces
  SELECT-only, row caps, timeouts. Card queries are AI-authored.
- Bank data stays local. Backups: add `finance` + `reports` to the existing
  mysqldump backup job (v1.1).
- Code home: GitHub repos → `/home/chuck/workspace/code/{data-hub,report-hub}`;
  compose: `homelab/compose/compose.data-hub.yml` (builds from the checkouts).

## 9. Scope

### v1
- finance + reports schemas, migrations, MySQL users/grants
- data-hub: inbox watcher, ingest API, `bank_csv` + `tax_xlsx` adapters,
  staging/upsert, load_log + ingest reports, categorization + review flow
- report-hub: query engine, saved queries, cards (label/table/chart),
  bar/column/pie, dashboards, 250-row pagination, read-only contract
- 5 v1 dashboards; mcp_mysql grants + schema hints; docs

### v2
- **Generic-dataset ETL adapter**: CSV/TSV → flexible import into tables in
  a database (dataset registry, column inference, configurable target
  schema; the daily-ingest-into-MySQL pattern for future data)
- **MCP wrapper for data-hub** (`mcp_datahub`): ingest_file, list_loads,
  load_detail, pending_categories, review_category — so any LLM client can
  drive ingestion/review
- alert push (n8n), backups for finance/reports, more chart types
- blog/site engagement + work app analytics (separate projects, same stack)

### Out
- auth/multi-user, public exposure, budgets (per chuck's call)

## 10. Build phases

| Phase | Work | Status |
|---|---|---|
| 0 | schemas, migrations, MySQL users/grants (provision.sh), compose, repo skeletons, docs | **done 2026-10-17** (provisioning + first `compose up` pending root + files) |
| 1 | data-hub core: watcher, ingest, staging, upsert, load_log | waiting on files |
| 2 | categorization + AI suggestions + review flow | waiting on files |
| 3 | report-hub UI: engine, cards, dashboards, pagination | skeleton done; dashboards in phase 4 |
| 4 | 5 v1 dashboards + mcp_mysql hints + docs | waiting on 1–3 |
| 5 | first real ingest + categorization review with chuck | waiting on files |
| v2-a | generic CSV/TSV dataset adapter | later |
| v2-b | mcp_datahub MCP wrapper | later |