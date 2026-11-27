# SEC Phase 10 deploy — host security monitoring & reporting

**Date:** 2026-11-27 (built on `task/security-phase10`; branch base `49faa59`)
**Status:** READY TO DEPLOY — all steps below are the deploy stage.
**Design source of truth:** `security_todo.md` §Phase 10.
**Task report (evidence):** `docs/security_phase10_report.md`.

## What this deploys

- `scripts/security-scan.sh` — daily baseline-diff scan (8 checks → daily
  report + `alerts.log` + Prometheus textfile metrics + retention pruning)
- `scripts/security-digest-weekly.sh` — weekly digest of the last 7 dailies
- `scripts/systemd/security-scan-daily.{service,timer}` — root, 00:30 UTC
- `scripts/systemd/security-digest-weekly.{service,timer}` — root, Sun 04:30 UTC
- `scripts/security-install-timers.sh` — idempotent unit installer
- `./homelab.sh security status` — on-demand verdict / unread alerts /
  baseline age
- `compose/compose.monitoring.yml` — node-exporter textfile collector
  (ro mount of `/home/chuck/data/security/metrics`)

Nothing here changes existing services: the only container touched is
node-exporter (recreated with one extra flag + one ro volume).

## Prerequisites

- `task/security-phase10` merged into `main` and pulled on the host
  (`/home/chuck/homelab`) — the units run the deployed copies at
  `/home/chuck/homelab/scripts/...`.
- `scripts/security-baseline.sh` + `scripts/security-scan.conf` already
  committed on the branch (TODO 1).

## Steps

### 1. Install the timers

```bash
cd /home/chuck/homelab
sudo scripts/security-install-timers.sh
```

Expected: 4 units installed, `security-scan-daily.timer` next run ~00:30
UTC, `security-digest-weekly.timer` next run Sunday 04:30 UTC.

### 2. Official baseline capture (as root)

```bash
sudo scripts/security-baseline.sh --update
```

The deploy baseline is captured **as root** on purpose: root sees the
`ss -tlnp` process names (LISTENERS process column) and can read
`/var/spool/cron/crontabs` (CRON section gets real hashes instead of
UNREADABLE). A non-root capture is honest but less complete — refresh via
`sudo --update` after any intentional host change (new service, new
container, new timer).

Inspect: `scripts/security-baseline.sh --show | head -40`.

### 3. First on-demand scan (as root)

```bash
sudo scripts/security-scan.sh
```

Expected: `scan complete: verdict=...` — on a fresh baseline expect
`CLEAN` or notes only (the first real run may note dpkg/snap churn and
external peers; that is the observation-mode signal, not a failure).

Verify the artifacts:

```bash
head -20 /home/chuck/data/security/reports/security-report-$(date -u +%Y-%m-%d).md
cat /home/chuck/data/security/metrics/security_scan.prom
ls -la /home/chuck/data/security/
```

### 4. node-exporter textfile metrics

```bash
cd /home/chuck/homelab
docker compose -f compose/compose.monitoring.yml up -d node-exporter
curl -s http://192.168.4.54:9100/metrics | grep '^security_scan_'
```

Expected: `security_scan_anomalies_total`, `security_scan_notes_total`,
`security_scan_last_run_timestamp_seconds` all present. (Optional: add a
Grafana panel on `security_scan_anomalies_total` — D7 option (c); the
metric is scrape-ready now.)

### 5. On-demand status

```bash
./homelab.sh security status
```

Expected: latest report + verdict, alert counts, baseline age. Run it
again — the "unread since last status" count resets (marker file
`/home/chuck/data/security/.last-status-ts`).

### 6. Record the observation-mode start date

`OBSERVATION_MODE=1` in `scripts/security-scan.conf` is already the
default. Record the start date here and in `security_todo.md` §Phase 10:

- **Observation mode started: ____ (fill in on deploy day)**

For the first 2 weeks: reports only, nothing escalated. Then:

1. Review the accumulated reports/notes for stable noise (apt upgrades,
   container recreates, Chuck's own LAN logins, the pi agent's `node`
   processes, known external peers such as GitHub/npm/LLM-provider IPs).
2. Add suppressors to `NOISE_PATTERNS` (process/log evidence) and/or
   extend `CDN_CIDRS` (peer IPs) in `scripts/security-scan.conf` — config
   edits only, no code changes.
3. Set thresholds from observed noise, then flip `OBSERVATION_MODE=0`.

## Rollback

```bash
sudo systemctl disable --now security-scan-daily.timer security-digest-weekly.timer
sudo rm /etc/systemd/system/security-{scan-daily,digest-weekly}.{service,timer}
sudo systemctl daemon-reload
docker compose -f compose/compose.monitoring.yml up -d node-exporter   # back to pre-Phase-10 flags
```

The scripts are additive (new files + one homelab.sh subcommand + one
compose block); deleting them is the full rollback. Host data under
`/home/chuck/data/security/` can be kept or removed at will.
