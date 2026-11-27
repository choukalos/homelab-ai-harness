#!/usr/bin/env python3
"""S7 spend-awareness — budget picture before a long job.

Pulls the LLM-spend data an agent needs before committing to an expensive
run, and prints one JSON object:

  - keys: per-LiteLLM-key totals from /spend/keys (alias, total_usd,
    24h_usd when the Phase 6 spend-watch state exists, limit_usd, headroom)
  - kanban_7d: per-owner + per-model spend/calls from the kanban `usage`
    table for the last 7 days (the agent org's actual burn)
  - limits: the Phase 6 thresholds (scripts/key-watch.conf)

Sources (all read-only):
  - LiteLLM proxy /spend/keys (LITELLM_MASTER_KEY from /home/chuck/homelab/.env)
  - kanban MySQL `usage` table via `docker exec mcp_kanban node` (mysql2 is
    in the container; thor.local:3306 is not reachable from the host)
  - /home/chuck/data/security/state/key-spend-state.json (Phase 6 24h window)
  - /home/chuck/homelab/scripts/key-watch.conf (limits)

Usage:
  python3 spend_check.py            # full picture
  python3 spend_check.py --days 14  # kanban window (default 7)
  python3 spend_check.py --help
"""
import json
import os
import re
import subprocess
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

HOMELAB = '/home/chuck/homelab'
ENV_FILE = os.path.join(HOMELAB, '.env')
WATCH_CONF = os.path.join(HOMELAB, 'scripts', 'key-watch.conf')
SPEND_STATE = '/home/chuck/data/security/state/key-spend-state.json'
LITELLM_URL = 'http://192.168.4.54:4000'


def env_get(name):
    try:
        with open(ENV_FILE) as f:
            for line in f:
                line = line.strip()
                if line.startswith(f'{name}='):
                    return line.split('=', 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return os.environ.get(name, '')


def watch_limits():
    limits = {'default': 20.0, 'overrides': {}}
    try:
        with open(WATCH_CONF) as f:
            for line in f:
                m = re.match(r'^SPEND_LIMIT_DEFAULT=(\d+(?:\.\d+)?)', line)
                if m:
                    limits['default'] = float(m.group(1))
                m = re.match(r'^\s*"([^"]+)=(\d+(?:\.\d+)?)"', line)
                if m:
                    limits['overrides'][m.group(1)] = float(m.group(2))
    except OSError:
        pass
    return limits


def litellm_spend(master_key):
    req = urllib.request.Request(
        f'{LITELLM_URL}/spend/keys',
        headers={'Authorization': f'Bearer {master_key}'})
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.loads(r.read())
    rows = data if isinstance(data, list) else data.get('data', data.get('keys', []))
    # Phase 6 24h rolling window (deltas vs the watch state file)
    state = {}
    try:
        with open(SPEND_STATE) as f:
            state = json.load(f)
    except (OSError, ValueError):
        pass
    limits = watch_limits()
    keys = []
    for row in rows:
        alias = row.get('key_alias') or (row.get('token') or '?')[:12]
        total = float(row.get('spend', 0) or 0)
        limit = limits['overrides'].get(alias, limits['default'])
        entry = {
            'alias': alias,
            'total_usd': round(total, 2),
            'limit_usd': limit,
        }
        # state file: {alias: {"total": X, "ts": epoch}} — 24h = total - total_24h_ago
        s = state.get(alias)
        if isinstance(s, dict) and 'total' in s:
            entry['spend_24h_usd'] = round(max(total - float(s['total']), 0.0), 2)
        keys.append(entry)
    keys.sort(key=lambda k: k['total_usd'], reverse=True)
    return keys


KANBAN_QUERY = r"""
const mysql = require('/app/node_modules/mysql2/promise');
(async () => {
  const c = await mysql.createConnection({ host: 'thor.local', user: 'ai-kanban',
    password: process.env.KANBAN_DB_PASS, database: 'ai_kanban', connectTimeout: 5000 });
  // `usage.ts` is epoch MILLISECONDS (not a datetime) — the boundary is
  // computed in Python and passed as a literal int (no injection surface).
  const [byOwner] = await c.query(
    'SELECT owner, COUNT(*) calls, COALESCE(SUM(tokens_in),0)+COALESCE(SUM(tokens_out),0) tokens, '
    + 'COALESCE(SUM(cost),0) cost FROM `usage` WHERE ts >= %s '
    + 'GROUP BY owner ORDER BY SUM(cost) DESC', [%s]);
  const [byModel] = await c.query(
    'SELECT model, COUNT(*) calls, COALESCE(SUM(tokens_in),0)+COALESCE(SUM(tokens_out),0) tokens, '
    + 'COALESCE(SUM(cost),0) cost FROM `usage` WHERE ts >= %s '
    + 'GROUP BY model ORDER BY SUM(cost) DESC LIMIT 10', [%s]);
  console.log(JSON.stringify({ byOwner: byOwner, byModel: byModel }));
  await c.end();
})().catch(e => { console.error(e.message); process.exit(1); });
"""


def kanban_usage(days):
    since_ms = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp() * 1000)
    js = KANBAN_QUERY % (since_ms, since_ms, since_ms, since_ms)
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
            row['tokens'] = int(row['tokens'])
    return data


def main():
    days = 7
    args = sys.argv[1:]
    if '-h' in args or '--help' in args:
        print(__doc__)
        return
    if '--days' in args:
        days = int(args[args.index('--days') + 1])
    result = {'as_of': datetime.now(timezone.utc).isoformat(timespec='seconds'), 'window_days': days}
    master_key = env_get('LITELLM_MASTER_KEY')
    if not master_key:
        result['keys'] = {'error': 'LITELLM_MASTER_KEY not found in .env'}
    else:
        try:
            result['keys'] = litellm_spend(master_key)
        except Exception as e:  # noqa: BLE001 — report, don't crash
            result['keys'] = {'error': str(e)}
    try:
        result['kanban_7d'] = kanban_usage(days)
    except subprocess.TimeoutExpired:
        result['kanban_7d'] = {'error': 'kanban query timed out (60s)'}
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
