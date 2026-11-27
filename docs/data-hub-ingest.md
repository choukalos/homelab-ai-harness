# Feeding data into data-hub (generic datasets)

Status: **live 2026-11-27.** The Plausible daily-analytics feed is the first
non-finance consumer of this pattern and is running (daily 02:00 UTC).

## The one-paragraph version

data-hub has a **generic-datasets** ingest framework (v2a) that lets you land
**any** CSV/TSV — from any project, report, or source — into a stable MySQL
table (`hub.ds_<name>`) **idempotently** (re-dropping the same data updates in
place, never duplicates). You don't write an ETL per source; you **register a
dataset** (name + filename pattern + optional schema + dedupe key) and then
**drop CSVs** into the inbox (or POST them). The data-hub watcher picks them
up and upserts them. This is the robust, reusable way to pass data into
data-hub for a variety of projects/reports/etc.

Design doc: `data-hub/docs/v2-generic-datasets.md` (in the data-hub repo).
This doc is the **operational** guide — how to add a new dataset from the
homelab side.

## The three moving parts

1. **A dataset** — a row in `hub.datasets` (the registry):
   - `name` (slug, e.g. `plausible`) → target table `hub.ds_<name>`
   - `source_pattern` — filename glob the watcher matches (e.g. `plausible-*.csv`)
   - `delimiter` (`,` or `\t`), `has_header` (0/1)
   - `column_map` — optional explicit schema `{"csv_col": "target_col TYPE"}`;
     when NULL the schema is **inferred on first import** and frozen
   - `key_columns` — the columns forming the dedupe key (NULL = all columns)
2. **An exporter** — anything that produces a CSV matching `source_pattern`
   and drops it into the inbox (a script, a cron, an agent, a manual `cp`).
3. **The watcher** — data-hub polls the inbox every 10 s, matches the
   `source_pattern`, runs the generic adapter, and upserts into the target
   table (bank/tax adapters claim first; unmatched files stay `pending`).

Inbox (host): `/home/chuck/data/finance/inbox/` (container: `/data/inbox`).

## How to add a new dataset (the recipe)

1. **Register it** (idempotent — safe to re-run):
   ```bash
   curl -sf -X POST http://192.168.4.54:8100/api/datasets \
     -H 'Content-Type: application/json' \
     -d '{
       "name": "<slug>",
       "description": "<what it is + source>",
       "source_pattern": "<slug>-*.csv",
       "delimiter": ",",
       "has_header": 1,
       "column_map": { "col": "col TYPE", ... },   # optional; omit to infer
       "key_columns": ["col_a", "col_b"]            # optional; dedupe key
     }'
   ```
   - **Tip: set `column_map` + `key_columns` explicitly** for anything that
     will be re-exported (idempotent upserts) or queried (stable schema).
     Leave them NULL only for one-off exploratory drops.
2. **Produce the CSV** — your exporter writes a CSV (header row + data) whose
   basename matches `source_pattern`, into `/home/chuck/data/finance/inbox/`.
3. **The watcher ingests it** within ~10 s → `hub.ds_<slug>`. Verify:
   ```bash
   curl -s "http://192.168.4.54:8100/api/loads?db=hub" | jq '.loads[0]'
   curl -s "http://192.168.4.54:8100/api/datasets/<slug>/preview?limit=5" | jq
   ```
   The source file is moved to `processed/` with a timestamp prefix.

### Idempotency / dedupe

- With `key_columns` set, the dedupe key is `sha256(target_table | key cols)`.
  Re-exporting the same rows → `ON DUPLICATE KEY UPDATE` (updates in place,
  preserves `ingested_at`). Verified for Plausible: re-run = `new=0, upd=N`.
- Without `key_columns`, the key is the hash of all normalized values (a
  changed row = a new row).
- Reserved columns (`id`, `content_hash`, `ingested_at`) are added by the
  adapter; if your CSV has a column named `id`, it's renamed to `col_id`.

## The Plausible feed (first non-finance example)

- **Dataset**: `plausible` → `hub.ds_plausible`, pattern `plausible-*.csv`,
  key `(date, site_id)`, explicit schema.
- **Exporter**: `scripts/plausible-export.sh` — queries Plausible ClickHouse
  `events_v2` for daily aggregates (pageviews, unique visitors, custom events)
  per site, joins the `site_id → domain` map from Plausible Postgres, writes
  `plausible-daily-YYYY-MM-DD.csv` into the inbox.
- **Timer**: `plausible-export-daily.timer` (02:00 UTC, `Persistent=true`),
  installed by `scripts/plausible-install-timer.sh`.
- **Schema** (`hub.ds_plausible`):
  `date DATE, site_id BIGINT, domain VARCHAR(255), pageviews BIGINT,
   unique_visitors BIGINT, custom_events BIGINT` (+ `id`, `content_hash`,
   `ingested_at`).
- **Note**: an orphaned `site_id=2` (from a previous Plausible instance) shows
  `domain='unknown'` — harmless; dashboards filter `domain <> 'unknown'`.

## Viewing the data

- **Grafana** — the `MySQL` datasource (read-only `dh_reports` on `hub.*`) +
  the **Product KPIs** dashboard (`grafana/dashboards/product-kpis.json`).
  Product/business KPIs live here (or in report-hub); platform/service status
  stays on the Prometheus datasource.
- **API** — `/api/datasets/<name>/preview`, `/api/loads?db=hub`.
- **report-hub** — `dh_reports` has SELECT on `hub.*`, so report-hub dashboards
  can read generic datasets too (UX organization is a separate follow-up).

## Adding a different kind of source

The pattern is source-agnostic. Examples:
- **Another ClickHouse/API source** — copy `plausible-export.sh`, change the
  query + `name`/`source_pattern`/`column_map`.
- **A scheduled DB dump** — `mysqldump`/`pg_dump` → CSV → inbox.
- **An agent-produced report** — the agent writes a CSV to the inbox (or uses
  the `mcp_datahub` `ingest_file` tool).
- **A one-off drop** — `cp report.csv /home/chuck/data/finance/inbox/` after
  registering a dataset for it.

## Ops

- **Register a dataset**: `bash scripts/plausible-register-dataset.sh` (or the
  `curl` above for a new one).
- **Run an export now**: `bash scripts/plausible-export.sh`.
- **Install the timer**: `sudo bash scripts/plausible-install-timer.sh`.
- **Deactivate a dataset**: `DELETE /api/datasets/<name>` (rows kept; the
  watcher stops claiming its files).
