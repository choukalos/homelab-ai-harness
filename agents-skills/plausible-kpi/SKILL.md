---
name: plausible-kpi
description: Generate a Plausible product-KPI report from the self-hosted Plausible analytics (ClickHouse events_v2) — pageviews, unique visitors, custom events, per-site breakdown, daily trend, top pages, top countries. Use when asked for a Plausible analytics or product-KPI report, a web-traffic / engagement summary, a Plausible workstream review, or to produce the KPI report step (BA-1). Runs a bundled script and writes a Markdown artifact.
---

# Plausible KPI Report

Produce a Plausible product-KPI report from the self-hosted Plausible
analytics. A single deterministic script queries Plausible's ClickHouse
(`plausible.events_v2`) for a lookback window and writes a Markdown report:
overview, per-site breakdown, daily trend, top pages, top countries, and
custom events. This is the KPI/report step (BA-1) of the Plausible
workstream — the data it reads is the same that flows into data-hub
(`hub.ds_plausible`) and the Grafana **Product KPIs** dashboard.

## When to use

- Asked for a Plausible analytics / product-KPI report or a web-traffic /
  engagement summary (pageviews, unique visitors, custom events).
- Reviewing the Plausible workstream (how are the 3 tracked sites doing?).
- Producing the KPI report artifact for the measurement / feedback loop.

## How to run

Runs on **thor** (it queries Plausible via `docker exec`). Run the bundled
script:

```bash
python3 /home/chuck/homelab/agents-skills/plausible-kpi/tools/plausible_kpi_report.py --days 30
```

Flags:

| Flag | Default | Description |
|------|---------|-------------|
| `--days N` | 30 | Lookback window in days. |
| `--sites a.com,b.com` | all | Restrict to specific domains (matched against Plausible's `sites` table). |
| `--top N` | 10 | Row count for top-pages / top-countries. |
| `--out PATH` | `/home/chuck/data/media/plausible_kpi/plausible-kpi-YYYY-MM-DD.md` | Output artifact path. |

The script prints a JSON object to stdout: `status` (`ok`/`error`),
`artifact_path`, `sites`, `totals` (pageviews / unique_visitors /
custom_events / sites), and `report` (the full Markdown). On `status: error`
read the `error` field (usually a ClickHouse/Postgres query failure) and
surface it — don't fabricate numbers.

## Presenting the result

- Lead with the headline numbers (total pageviews, unique visitors, custom
  events) and the per-site breakdown.
- Call out the trend (is traffic up/down/flat over the window?) and the top
  pages / countries.
- Link the artifact (`artifact_path`) so the durable report is on disk.
- For low-traffic windows (the sites are new), say so plainly rather than
  over-interpreting small numbers.

## Notes / gotchas

- **Source of truth is ClickHouse** (`plausible.events_v2`), queried via
  `docker exec plausible-events-db clickhouse client`. The data-hub
  `hub.ds_plausible` table is a derived daily aggregate (path A) for the
  dashboard; this skill reads ClickHouse directly for the full detail.
- `unique_visitors` = distinct sessions; `custom_events` = non-pageview
  events (goals / named events).
- Country data depends on Plausible's GeoIP enrichment — sparse for
  low-traffic windows.
- An orphaned `site_id` from a previous Plausible instance (if present) shows
  as `site-<id>`; the 3 live sites are `choukalos.com`,
  `invest.choukalos.com`, `bluebovinegroup.com`.
- The tracker snippet is live on all 3 sites (see `todo_plausible.md`, P3);
  real traffic accumulates from there.
