# Business Analyst artifacts

Durable BA artifacts (G12 conventions — see `../README.md`):

- `report-contract.md` — **the G4 BA→role report contract** (defined
  2026-11-27 when the G3 wiring landed): report location + naming, the
  report format, insight routing (board card = the only routing that creates
  work), cadence, the KPI registry, and the grounding rules (one source /
  every numeric claim referenced / missing ≠ estimated / small windows say
  so). Every BA report follows it.
- `reports/<topic>-<YYYY-MM-DD>.md` — BA reports (BA-1 `kpi-reporting`,
  Phase 3). The report file is the record; a board card routes the insight to
  the owning role (PM, strategist, CM). The reporting surface (data-hub /
  report-hub + Grafana) carries the dashboards; durable markdown analysis
  notes live here for the record (G11 decision 2026-11-22).

The standing measurement record is the **weekly KPI digest** at
`docs/org/kpi/<YYYY>-W<WW>.md` (analyst O1 KR1 — the W48 baseline issue
fixed the format; the G4 contract governs its routing).

**Data sources (G3 closed 2026-11-27):** Plausible (self-hosted, all 3 sites
wired — `plausible-kpi` skill for the KPI report), the kanban `usage` table
(spend by owner/model), board state (mcp_kanban), the finance DB, and the
role artifacts. The Grafana **Product KPIs** dashboard carries the live
trend (fed from the daily data-hub export).
