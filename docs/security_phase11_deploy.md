# SEC Phase 11 deploy — public-surface security monitoring

**Date:** 2026-11-27 (built on `task/security-phase11`; branch base `b60c01b`)
**Status:** DEPLOYED 2026-11-27 — merged to `main` (`edd1c51`); all 6
steps executed and verified: 4 timers live (surface daily ~01:15 /
weekly Sun 04:40, offset from Phase 10's 00:30 / 04:30), first daily
scan 7 notes / 0 anomalies (2026-11-27 14:01 UTC), first weekly run
BASELINE CAPTURED (26 tables / 244 cols / 18 privs), `security
surface` status verified, surface metrics scrape-verified via the
auto-synced copy (post-deploy fixes: `9d229df` — status marker EACCES
+ node_exporter symlink blind spot).
**Design source of truth:** `security_todo.md` §Phase 11.
**Task report (evidence):** `docs/security_phase11_report.md`.

## What this deploys

- `security/public-surface.yml` — the public-surface registry (single source
  of truth; 8 domains incl. reserved `test.choukalos.com`; live-verified
  stack versions feed the CVE cross-check)
- `scripts/security-surface-scan.sh` — daily registry-driven scan (17 probes
  with auth-gate canaries, TLS floor/expiry, security headers, CVE
  cross-check vs `KNOWN_CVES`, registry lint: Caddyfile hosts + optional CF
  tunnel ingress vs registry) → daily report + `alerts.log` + Prometheus
  textfile metrics + retention pruning
- `scripts/security-surface-scan.conf` — thresholds/known values (post-
  observation tuning is a config edit, not a code change)
- `scripts/security-surface-weekly.sh` — weekly check: InvestHub
  `investorhub` schema-diff (information_schema tables/columns + app-user
  privileges; any change = critical P0) + digest of the last 7 daily scans
- `scripts/systemd/security-surface-daily.{service,timer}` — 01:15 UTC
  (after the Phase 10 host scan at 00:30)
- `scripts/systemd/security-surface-weekly.{service,timer}` — Sun 04:40 UTC
  (after the Phase 10 weekly digest at 04:30)
- `scripts/security-surface-install-timers.sh` — idempotent unit installer
- `./homelab.sh security surface` — on-demand status (latest daily/weekly
  verdicts, observation mode, alert counts, schema-snapshot age)

Nothing here changes existing services or containers. All probes are
read-only (GET + TLS handshake + `information_schema` SELECTs); the only
writes are under `/home/chuck/data/security-surface/`. Observation mode is
**ON by default** (`OBSERVATION_MODE=1` in the conf): report only, nothing
escalated, for the first 2 weeks.

## Prerequisites

- `task/security-phase11` merged into `main` and pulled on the host
  (`/home/chuck/homelab`) — the units run the deployed copies at
  `/home/chuck/homelab/scripts/...` and
  `/home/chuck/homelab/security/public-surface.yml`.
- Phase 10 already deployed (its pipeline is the reporting target; the
  surface scan keeps its own data dir `/home/chuck/data/security-surface`).
- `LITELLM_KEY_CHUCK` in `/home/chuck/homelab/.env` (the `with: chuck-key`
  probes; if absent those probes are honestly marked SKIPPED, not failed).
- `INVEST_DATABASE_URL` in `.env` (weekly schema-diff; the app's own DB
  credential — the script resolves the compose-template `${...}` refs and
  falls back to the LAN IPv4 `192.168.4.54` when `thor.local` is
  unreachable from the host, per the `.env` note).
- Optional: `CF_API_TOKEN` (+ `CF_ACCOUNT_ID`, `CF_TUNNEL_ID` in `.env`) —
  enables the CF tunnel ingress side of the registry lint (11.1). Without
  it that side is honestly skipped with a note.

## Steps

### 1. Install the timers

```bash
cd /home/chuck/homelab
sudo scripts/security-surface-install-timers.sh
```

Expected: 4 units installed, `security-surface-daily.timer` next run ~01:15
UTC, `security-surface-weekly.timer` next run Sunday 04:40 UTC.

### 2. First on-demand daily scan

```bash
sudo scripts/security-surface-scan.sh
```

Expected: `surface scan complete: verdict=...` — on a healthy surface expect
`CLEAN` or notes only (the first real run notes missing HSTS on 6 domains —
CF terminates TLS, HSTS is an edge concern tracked at `note` severity — plus
the CF-lint skip note when `CF_API_TOKEN` is unset). 17/17 probes OK, 8×
TLSv1.3, registry lint 8=8 were the 2026-11-27 build-time results.

The data dir is created root-owned by the root scan — make it writable by
`chuck` so `./homelab.sh security surface` can write its unread marker:

```bash
sudo chown -R chuck:chuck /home/chuck/data/security-surface
```

Verify the artifacts:

```bash
head -30 /home/chuck/data/security-surface/reports/security-surface-report-$(date -u +%Y-%m-%d).md
cat /home/chuck/data/security-surface/metrics/security_surface.prom
ls -la /home/chuck/data/security-surface/
```

### 3. First weekly run (schema-diff baseline)

```bash
sudo scripts/security-surface-weekly.sh
```

Expected: `schema-diff: BASELINE CAPTURED` (first run captures
`db-snapshots/investorhub-YYYY-MM-DD.txt` — 26 tables / 244 columns /
18 privilege rows at build time — and reports a note, no diff). Subsequent
weekly runs diff against the newest prior snapshot; **any schema or
privilege change is a critical P0** in `alerts.log`.

### 4. On-demand status

```bash
./homelab.sh security surface
```

Expected: latest daily report + verdict + observation-mode line, latest
weekly digest + verdict, alert counts (`unread` resets on each status run —
marker `/home/chuck/data/security-surface/.last-status-ts`), schema-snapshot
age (`STALE` after 8 days = a full missed weekly cycle).

### 5. Optional: CF ingress lint + node-exporter metrics

```bash
# CF tunnel ingress side of the registry lint (11.1 hostname diff):
export CF_API_TOKEN=...        # or add CF_API_TOKEN=... to /home/chuck/homelab/.env

# Surface metrics into the Phase 10 node-exporter textfile collector:
# the daily scan auto-syncs a REAL copy to /home/chuck/data/security/metrics/
# (node_exporter's textfile collector does NOT follow symlinks — a manual
# symlink is invisible to it; the scan keeps the copy fresh every run).
# Verify after the first scan:
curl -s http://192.168.4.54:9100/metrics | grep '^security_surface_'
```

Expected: `security_surface_anomalies_total`, `security_surface_notes_total`,
`security_surface_last_run_timestamp_seconds`, and
`security_probe_failures_total{domain=...}` per domain.

### 6. Record the observation-mode start date

`OBSERVATION_MODE=1` in `scripts/security-surface-scan.conf` is already the
default. Record the start date here and in `security_todo.md` §Phase 11:

- **Observation mode started: 2026-11-27** (deploy day; first real scans
  land when sudo steps 2–3 are run — the 2-week tuning window runs from
  the first completed daily+weekly cycle)

For the first 2 weeks: reports only, nothing escalated. Then:

1. Review the accumulated reports/notes for stable noise (the HSTS notes are
   the expected first candidate — decide per domain whether to suppress via
   `NOISE_PATTERNS`, lower the header expectation, or actually add HSTS at
   the CF edge).
2. Tune thresholds/known values in `scripts/security-surface-scan.conf`
   (`CERT_EXPIRY_*`, `EXPECT_HEADERS`, `KNOWN_CVES`, `NOISE_PATTERNS`,
   `PROBE_TIMEOUT`) — config edits only, no code changes.
3. When the CF-API side is wired (step 5), confirm the lint shows the CF
   ingress hostnames and they match the registry.
4. Flip `OBSERVATION_MODE=0` once the noise is baselined.

## Rollback

```bash
sudo systemctl disable --now security-surface-daily.timer security-surface-weekly.timer
sudo rm /etc/systemd/system/security-surface-{daily,weekly}.{service,timer}
sudo systemctl daemon-reload
rm -f /home/chuck/data/security/metrics/security_surface.prom   # if the step-5 copy exists
```

The registry + scripts are additive (new files + one `homelab.sh`
subcommand); deleting them is the full rollback. Host data under
`/home/chuck/data/security-surface/` can be kept or removed at will. No
service or container changes were made, so there is nothing else to undo.
