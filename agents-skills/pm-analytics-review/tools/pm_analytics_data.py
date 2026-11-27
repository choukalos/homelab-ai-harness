#!/usr/bin/env python3
"""PM-6 pm-analytics-review — the analytics data pack.

Collects the deterministic half of the PM analytics review in one JSON
object, so the review step spends LLM turns on synthesis, not plumbing:

  - plausible: headline numbers from the latest plausible-kpi report
    artifact (pageviews / unique visitors / custom events, per-site).
    If no artifact exists yet, says so — the agent runs the
    `plausible-kpi` skill first (BA-1) and re-runs this tool.
  - kpi_digest: the latest weekly KPI digest path (docs/org/kpi/) — the
    standing BA measurement record (G4 contract).
  - kanban_7d: board task counts by state + per-owner and per-model spend
    for the window (the `usage` table, via docker exec mcp_kanban).

Sources (all read-only):
  - /home/chuck/data/media/plausible_kpi/plausible-kpi-*.md (BA-1 artifacts)
  - /home/chuck/homelab/docs/org/kpi/*.md (weekly digests)
  - kanban MySQL `usage` + `tasks` tables (thor.local:3306, reachable from
    the mcp_kanban container only)

Usage:
  python3 pm_analytics_data.py            # 7-day kanban window
  python3 pm_analytics_data.py --days 14
  python3 pm_analytics_data.py --help
"""
import glob
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone

HOMELAB = '/home/chuck/homelab'
KPI_ARTIFACTS = '/home/chuck/data/media/plausible_kpi/plausible-kpi-*.md'
KPI_DIGESTS = os.path.join(HOMELAB, 'docs', 'org', 'kpi', '*.md')


def latest_plausible():
    files = sorted(glob.glob(KPI_ARTIFACTS))
    if not files:
        return {'status': 'missing',
                'note': 'no plausible-kpi artifact yet — run the plausible-kpi '
                        'skill (BA-1) first, then re-run this tool'}
    path = files[-1]
    with open(path) as f:
        text = f.read()
    data = {'status': 'ok', 'artifact': path, 'generated': os.path.basename(path)}

    def grab(pattern):
        m = re.search(pattern, text)
        return m.group(1).strip() if m else None

    # Overview table rows: | Pageviews | **2** |
    data['pageviews'] = grab(r'\|\s*Pageviews\s*\|\s*\*\*([\d,]+)\*\*')
    data['unique_visitors'] = grab(r'\|\s*Unique visitors\s*\|\s*\*\*([\d,]+)\*\*')
    data['custom_events'] = grab(r'\|\s*Custom events\s*\|\s*\*\*([\d,]+)\*\*')
    # per-site table rows: | domain | pv | uv | events | share% |
    sites = {}
    for m in re.finditer(
            r'\|\s*([a-z0-9-]+(?:\.[a-z0-9-]+)+)\s*\|\s*([\d,]+)\s*\|\s*([\d,]+)\s*\|\s*([\d,]+)\s*\|',
            text):
        domain = m.group(1)
        if domain.startswith(('site-',)):
            continue
        sites[domain] = {'pageviews': m.group(2), 'unique_visitors': m.group(3),
                         'custom_events': m.group(4)}
    data['per_site'] = sites
    # window line, e.g. "- **Window**: last 7 days (through 2026-11-27 23:44 UTC)"
    m = re.search(r'\*\*Window\*\*[:\s]*([^\n]+)', text)
    if m:
        data['window'] = m.group(1).strip()
    return data


def latest_digest():
    files = sorted(glob.glob(KPI_DIGESTS))
    if not files:
        return {'status': 'missing', 'note': 'no weekly KPI digest yet'}
    path = files[-1]
    return {'status': 'ok', 'path': path, 'name': os.path.basename(path)}


KANBAN_QUERY = r"""
const mysql = require('/app/node_modules/mysql2/promise');
(async () => {
  const c = await mysql.createConnection({ host: 'thor.local', user: 'ai-kanban',
    password: process.env.KANBAN_DB_PASS, database: 'ai_kanban', connectTimeout: 5000 });
  // `tasks.state_changed_at` and `usage.ts` are epoch MILLISECONDS — the
  // boundary is computed in Python and passed as a literal int.
  const [states] = await c.query('SELECT state, COUNT(*) n FROM tasks GROUP BY state');
  const [recent] = await c.query(
    'SELECT id, owner, LEFT(spec, 80) spec FROM tasks WHERE state = \'done\' '
    + 'AND state_changed_at >= %s ORDER BY state_changed_at DESC LIMIT 15', [%s]);
  const [byOwner] = await c.query(
    'SELECT owner, COUNT(*) calls, COALESCE(SUM(tokens_in),0)+COALESCE(SUM(tokens_out),0) tokens, '
    + 'COALESCE(SUM(cost),0) cost FROM `usage` WHERE ts >= %s '
    + 'GROUP BY owner ORDER BY SUM(cost) DESC', [%s]);
  const [byModel] = await c.query(
    'SELECT model, COUNT(*) calls, COALESCE(SUM(cost),0) cost FROM `usage` '
    + 'WHERE ts >= %s GROUP BY model ORDER BY SUM(cost) DESC LIMIT 10', [%s]);
  console.log(JSON.stringify({ states: states, recent_done: recent, byOwner: byOwner, byModel: byModel }));
  await c.end();
})().catch(e => { console.error(e.message); process.exit(1); });
"""


def kanban(days):
    since_ms = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp() * 1000)
    js = KANBAN_QUERY % tuple([since_ms] * 6)
    out = subprocess.run(
        ['docker', 'exec', 'mcp_kanban', 'node', '-e', js],
        capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        return {'error': out.stderr.strip() or f'exit {out.returncode}'}
    try:
        data = json.loads(out.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {'error': f'unparseable: {out.stdout[:200]!r}'}
    for key in ('byOwner', 'byModel'):
        for row in data.get(key, []):
            row['cost'] = round(float(row['cost'] or 0), 2)
    return data


def main():
    days = 7
    args = sys.argv[1:]
    if '-h' in args or '--help' in args:
        print(__doc__)
        return
    if '--days' in args:
        days = int(args[args.index('--days') + 1])
    result = {'as_of': datetime.now(timezone.utc).isoformat(timespec='seconds'),
              'window_days': days,
              'plausible': latest_plausible(),
              'kpi_digest': latest_digest()}
    try:
        result['kanban_7d'] = kanban(days)
    except subprocess.TimeoutExpired:
        result['kanban_7d'] = {'error': 'kanban query timed out (60s)'}
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
