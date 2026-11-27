#!/usr/bin/env python3
"""plausible_kpi_report.py — generate a Plausible product-KPI report.

Queries the self-hosted Plausible ClickHouse (plausible.events_v2) for a
lookback window and writes a Markdown KPI report: overview (per site),
daily trend, per-site breakdown, top pages, top countries, and custom
events. Designed for non-interactive agent use — flags (not prompts),
structured stdout, useful errors.

This is the KPI/report step (BA-1) of the Plausible workstream. It reads the
source of truth (ClickHouse) directly; the data-hub `hub.ds_plausible`
table + Grafana dashboard are the path-A derived surface for the same data.

Usage:
  plausible_kpi_report.py [--days N] [--out PATH] [--sites a.com,b.com] [--top N]

Defaults: --days 30, --top 10,
  --out /home/chuck/data/media/plausible_kpi/plausible-kpi-YYYY-MM-DD.md
"""
import argparse
import datetime as dt
import json
import os
import subprocess
import sys

CH_CONTAINER = os.environ.get("PLAUSIBLE_CH_CONTAINER", "plausible-events-db")
CH_DB = os.environ.get("PLAUSIBLE_CH_DB", "plausible")
PG_CONTAINER = os.environ.get("PLAUSIBLE_PG_CONTAINER", "plausible-db")
PG_USER = os.environ.get("PLAUSIBLE_PG_USER", "plausible")
PG_DB = os.environ.get("PLAUSIBLE_PG_DB", "plausible")
DEFAULT_OUT_DIR = "/home/chuck/data/media/plausible_kpi"


def ch_query(sql: str):
    """Run a ClickHouse query via docker exec; return a list of dicts (JSONEachRow)."""
    sql = sql.rstrip().rstrip(";")
    cmd = ["docker", "exec", CH_CONTAINER, "clickhouse", "client",
           "--query", sql + " FORMAT JSONEachRow"]
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.PIPE, timeout=90).decode()
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"ClickHouse query failed: {e.stderr.decode()[:400]}")
    except subprocess.TimeoutExpired:
        raise RuntimeError("ClickHouse query timed out (90s)")
    rows = []
    for line in out.splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def pg_site_map():
    """site_id -> domain map from Plausible Postgres (best-effort)."""
    cmd = ["docker", "exec", PG_CONTAINER, "psql", "-U", PG_USER, "-d", PG_DB,
           "-t", "-A", "-F", "\t", "-c", "SELECT id, domain FROM sites ORDER BY id"]
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.PIPE, timeout=30).decode()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return {}
    m = {}
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) == 2 and parts[0].strip():
            m[parts[0].strip()] = parts[1].strip()
    return m


def domain(site_id, site_map):
    return site_map.get(str(site_id), f"site-{site_id}")


def coerce(rows, fields):
    """Coerce ClickHouse UInt64/Int64 fields (strings in JSON) to int."""
    for r in rows:
        for f in fields:
            if f in r and r[f] is not None:
                try:
                    r[f] = int(r[f])
                except (ValueError, TypeError):
                    pass
    return rows


def pct(n, d):
    return f"{(100.0 * n / d):.1f}%" if d else "—"


def md_table(headers, rows):
    if not rows:
        return "_(no data)_\n"
    out = ["| " + " | ".join(headers) + " |",
           "|" + "|".join([" --- "] * len(headers)) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(c) for c in r) + " |")
    return "\n".join(out) + "\n"


def main():
    ap = argparse.ArgumentParser(description="Generate a Plausible product-KPI report.")
    ap.add_argument("--days", type=int, default=30, help="Lookback window in days (default 30).")
    ap.add_argument("--top", type=int, default=10, help="Rows for top-pages/countries (default 10).")
    ap.add_argument("--sites", default=None,
                    help="Comma-separated domains to include (default: all sites).")
    ap.add_argument("--out", default=None, help="Output markdown path.")
    args = ap.parse_args()

    days = max(1, args.days)
    site_map = pg_site_map()

    # Optional domain filter -> restrict to matching site_ids.
    site_filter = None
    if args.sites:
        wanted = {s.strip() for s in args.sites.split(",") if s.strip()}
        ids = [sid for sid, dom in site_map.items() if dom in wanted]
        if not ids:
            print(json.dumps({"status": "error",
                              "error": f"no sites match --sites {sorted(wanted)} "
                                       f"(known: {sorted(site_map.values())})"}))
            sys.exit(2)
        site_filter = ",".join(ids)
        where_site = f"AND site_id IN ({site_filter})"
    else:
        where_site = ""

    W = f"WHERE timestamp >= now() - INTERVAL {days} DAY {where_site}"

    # --- queries -------------------------------------------------------------
    overview = ch_query(f"""
        SELECT site_id,
               countIf(name = 'pageview')   AS pageviews,
               uniq(session_id)             AS unique_visitors,
               countIf(name != 'pageview')  AS custom_events,
               count()                      AS total_events
        FROM {CH_DB}.events_v2 {W}
        GROUP BY site_id ORDER BY pageviews DESC""")
    overview = coerce(overview, ["pageviews", "unique_visitors", "custom_events", "total_events"])

    trend = ch_query(f"""
        SELECT toString(toDate(timestamp)) AS date,
               countIf(name = 'pageview') AS pageviews,
               uniq(session_id)           AS visitors
        FROM {CH_DB}.events_v2 {W}
        GROUP BY date ORDER BY date""")
    trend = coerce(trend, ["pageviews", "visitors"])

    top_pages = ch_query(f"""
        SELECT pathname, count() AS views
        FROM {CH_DB}.events_v2
        WHERE name = 'pageview' AND timestamp >= now() - INTERVAL {days} DAY {where_site}
        GROUP BY pathname ORDER BY views DESC LIMIT {args.top}""")
    top_pages = coerce(top_pages, ["views"])

    top_countries = ch_query(f"""
        SELECT country_code, count() AS views
        FROM {CH_DB}.events_v2
        WHERE name = 'pageview' AND country_code != ''
          AND timestamp >= now() - INTERVAL {days} DAY {where_site}
        GROUP BY country_code ORDER BY views DESC LIMIT {args.top}""")
    top_countries = coerce(top_countries, ["views"])

    custom_events = ch_query(f"""
        SELECT name, count() AS events
        FROM {CH_DB}.events_v2
        WHERE name != 'pageview' AND timestamp >= now() - INTERVAL {days} DAY {where_site}
        GROUP BY name ORDER BY events DESC LIMIT 15""")
    custom_events = coerce(custom_events, ["events"])

    # --- assemble the report -------------------------------------------------
    now = dt.datetime.now(dt.timezone.utc)
    total_pv = sum(r["pageviews"] for r in overview)
    total_uv = sum(r["unique_visitors"] for r in overview)
    total_ce = sum(r["custom_events"] for r in overview)
    n_sites = len(overview)
    active_days = len(trend)
    avg_pv = (total_pv / active_days) if active_days else 0

    L = []
    L.append(f"# Plausible Product KPI Report")
    L.append("")
    L.append(f"- **Window**: last {days} days (through {now:%Y-%m-%d %H:%M} UTC)")
    L.append(f"- **Sites**: {', '.join(domain(r['site_id'], site_map) for r in overview) or '—'}")
    L.append(f"- **Generated**: {now:%Y-%m-%d %H:%M} UTC by `plausible-kpi` skill")
    L.append("")
    L.append("## Overview")
    L.append("")
    L.append(md_table(["Metric", "Value"], [
        ["Pageviews", f"**{total_pv:,}**"],
        ["Unique visitors", f"**{total_uv:,}**"],
        ["Custom events", f"**{total_ce:,}**"],
        ["Sites tracked", n_sites],
        ["Active days (with traffic)", active_days],
        ["Avg pageviews / active day", f"{avg_pv:,.0f}"],
    ]))
    L.append("")
    L.append("## Per-site breakdown")
    L.append("")
    ov_rows = [[domain(r["site_id"], site_map), f"{r['pageviews']:,}",
                f"{r['unique_visitors']:,}", f"{r['custom_events']:,}",
                pct(r["pageviews"], total_pv)] for r in overview]
    L.append(md_table(["Site", "Pageviews", "Unique visitors", "Custom events", "Share of PV"], ov_rows))
    L.append("")
    L.append(f"## Daily trend (last {days} days)")
    L.append("")
    tr_rows = [[r["date"], f"{r['pageviews']:,}", f"{r['visitors']:,}"] for r in trend]
    L.append(md_table(["Date", "Pageviews", "Visitors"], tr_rows))
    L.append("")
    L.append(f"## Top pages (by pageviews, last {days} days)")
    L.append("")
    tp_rows = [[r["pathname"] or "/", f"{r['views']:,}", pct(r["views"], total_pv)] for r in top_pages]
    L.append(md_table(["Path", "Views", "Share"], tp_rows))
    L.append("")
    L.append(f"## Top countries (by pageviews)")
    L.append("")
    tc_rows = [[r["country_code"], f"{r['views']:,}", pct(r["views"], total_pv)] for r in top_countries]
    L.append(md_table(["Country", "Views", "Share"], tc_rows))
    L.append("")
    L.append("## Custom events (goals / named events)")
    L.append("")
    ce_rows = [[r["name"], f"{r['events']:,}"] for r in custom_events]
    L.append(md_table(["Event", "Count"], ce_rows))
    L.append("")
    L.append("## Notes")
    L.append("")
    L.append("- Source: self-hosted Plausible ClickHouse `plausible.events_v2` "
             "(the path-A data also lands in data-hub `hub.ds_plausible` and the "
             "Grafana **Product KPIs** dashboard).")
    L.append("- `unique_visitors` = distinct sessions; `custom_events` = non-pageview events.")
    L.append("- Country data depends on Plausible's GeoIP enrichment (may be sparse "
             "for low-traffic windows).")
    L.append("")

    report = "\n".join(L)

    # --- write the artifact --------------------------------------------------
    if args.out:
        out_path = args.out
    else:
        out_path = os.path.join(DEFAULT_OUT_DIR, f"plausible-kpi-{now:%Y-%m-%d}.md")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        f.write(report)

    print(json.dumps({
        "status": "ok",
        "artifact_path": out_path,
        "window_days": days,
        "sites": [domain(r["site_id"], site_map) for r in overview],
        "totals": {"pageviews": total_pv, "unique_visitors": total_uv,
                   "custom_events": total_ce, "sites": n_sites},
        "report": report,
    }, indent=2))


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as e:
        print(json.dumps({"status": "error", "error": str(e)}))
        sys.exit(1)
