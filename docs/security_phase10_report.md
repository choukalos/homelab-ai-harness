# SEC Phase 10 task report — host security monitoring & reporting

**Date:** 2026-11-27
**Branch:** `task/security-phase10` (worktree `/home/chuck/homelab-worktrees/security-phase10`)
**Spec:** `security_todo.md` §Phase 10 (baseline-diff design)
**Deploy runbook:** `docs/security_phase10_deploy.md`
**Status:** DEPLOYED 2026-11-27 (timers live ~00:30 / Sunday 04:30 UTC, root
baseline captured, node-exporter textfile collector live; `security_scan_*`
metrics confirmed scraping from VictoriaMetrics).

## Context: the 2026-11-26 crash

The first attempt at this work (pi-long-task run `2026-11-26T20-03-59`)
died because the worker's `security-baseline.sh` was missing `shift` in its
arg-parse loop — `--update` spun the `case` loop forever (4h46m hung
verification run, session aborted). All 3 worker attempts hit the 900s
timeout (model health was degraded in that window — `health_timed_out`
rotations). This session reproduced the hang, fixed the missing `shift`
(+ a second bug: `cron_dir` mislabeled the root-only cron spool `EMPTY`
instead of `UNREADABLE`), and completed TODO 1–6.

## Deliverables

| Item | File(s) |
|---|---|
| Baseline capture (TODO 1) | `scripts/security-baseline.sh`, `scripts/security-scan.conf` |
| Daily baseline-diff scan (TODO 2) | `scripts/security-scan.sh` |
| Weekly digest (TODO 3) | `scripts/security-digest-weekly.sh` |
| Timers + installer + status (TODO 4) | `scripts/systemd/security-scan-daily.{service,timer}`, `scripts/systemd/security-digest-weekly.{service,timer}`, `scripts/security-install-timers.sh`, `homelab.sh` (`security status`) |
| Metrics wiring + runbook (TODO 5) | `compose/compose.monitoring.yml` (node-exporter textfile collector), `docs/security_phase10_deploy.md` |
| Status + report (TODO 6) | `security_todo.md` §Phase 10, this file |

## Verification (evidence per claim)

### TODO 1 — baseline capture

- **Syntax:** `bash -n scripts/security-baseline.sh` → no output (OK).
- **Capture:** `scripts/security-baseline.sh --update` →
  `baseline written: /home/chuck/data/security/baseline.txt (3352 bytes,
  captured 2026-11-27T01:46:21Z)`. All 7 sections present (header,
  LISTENERS, USERS, CRON, TIMERS, CONTAINERS, MAIL_TOOLS).
- **Content:** USERS = `chuck` only (UID≥1000, nobody excluded);
  MAIL_TOOLS = all 7 ABSENT; CRON = `/etc/crontab` +
  `/etc/cron.d/e2scrub_all` hashed, `/var/spool/cron/crontabs`
  `UNREADABLE` (non-root — correct per the "honest, never silent" contract);
  19 timers, 49 containers.
- **No auto-refresh:** `stat -c %Y` before/after a plain run → identical
  (`PLAIN-RUN-DID-NOT-REFRESH`); plain run prints status only.
- **`--file`:** `--update --file /tmp/.../x.txt` wrote the alternate path.
- **Infinite-loop bug:** reproduced (script hung with zero output;
  `bash -x` trace showed the arg-parse `case` loop spinning on `--update`
  with no `shift`), fixed, re-verified with the runs above.
- **`:3000` listener:** `192.168.4.54:3000` (not on the Phase 4 survivors
  list) = mcp_kanban LAN-only web UI — `compose/compose.mcp.yml:403`
  (`${THOR_IP:-192.168.4.54}:3000:3000`, "LAN-only web UI" comment).
  Legitimate; the Phase 4 list predates it.

### TODO 2 — daily scan

- **Syntax:** `bash -n scripts/security-scan.sh` → OK.
- **Live end-to-end run:** `scripts/security-scan.sh` (real baseline) →
  `scan complete: verdict=2 notes` (both `sensitive-files` notes: 4 files
  under /etc modified in 24h — snap hwctl units + `ld.so.cache` — with
  dpkg-activity context note; 0 anomalies). Report well-formed: header,
  `verdict:` machine line, Anomalies/Notes with evidence blocks, full
  baseline-diff tables (all items `OK`), auth.log section
  (`auth-total: 1`, `auth-unknown: 0` — the one in-window failure was from
  known-IP `192.168.4.56`).
- **Synthetic-baseline anomaly test** (mutated copy of the real baseline in
  `/tmp/sec-test`, live host state unchanged): all required detectors fired —
  `new listener 0.0.0.0:80`, `removed listener 192.168.4.54:9999`,
  `new UID>=1000 user: chuck`, `cron state changed: FILE /etc/cron.d/e2scrub_all
  …`, `new/renamed container: mcp_kanban`. Verdict `5 anomalies, 2 notes`;
  `alerts.log` got 5 lines in `ts | severity | check | detail` format.
- **SMTP immediate anomaly:** real port 25 needs root (no passwordless
  sudo), so the same code path was exercised via a conf override
  (`SMTP_PORTS=(12345)` in a `/tmp` copy) with a held ESTAB connection to
  `127.0.0.1:12345` → `[critical] outbound-smtp: ESTAB connections on SMTP
  port(s) 12345` in the report + `… | critical | outbound-smtp | …` in
  `alerts.log`.
- **Missing-baseline path:** scan with no baseline file →
  `baseline-missing` anomaly, diff tables `SKIPPED`, all non-baseline
  checks still ran.
- **Metrics:** `metrics/security_scan.prom` contains all three gauges
  (`security_scan_anomalies_total`, `security_scan_notes_total`,
  `security_scan_last_run_timestamp_seconds`) with HELP/TYPE lines.
- **Retention:** temp data dir with reports aged 100d/300d + weekly 400d +
  recent 7d/10d files → after a scan run, only the recent files + today's
  report remained (`-mtime +90` / `+364` pruning).
- **Zero writes outside allowed paths:** writes go to the data dir
  (reports/alerts.log/metrics) + a `mktemp -d /tmp/security-scan.XXXXXX`
  findings dir (removed on exit). Host state untouched by the scan itself.

### TODO 3 — weekly digest

- **Syntax:** `bash -n scripts/security-digest-weekly.sh` → OK.
- **Synthetic 14-day test** (`/tmp/sec-digest`, 7 "this week" + 7 "last
  week" sample reports): produced
  `security-weekly-2026-W48.md` with the 7-day verdict table (per-day
  anomalies/notes), totals (7 anomalies / 14 notes), recurring notes
  (`outbound: 7 day(s)`, `sensitive-files: 7 day(s)` — seen on ≥2 days),
  and auth.log trend with week-over-week
  (`192.168.4.56: 14 this week (7 last week)`).
- **Real-data run:** against `/home/chuck/data/security` (1 daily report
  so far) → well-formed digest, 1 report covered, no crash on sparse data.

### TODO 4 — timers, installer, `homelab.sh security status`

- **Units:** `security-scan-daily.{service,timer}` +
  `security-digest-weekly.{service,timer}` mirror the `backup-nas-daily`
  pattern (OnCalendar, `Persistent=true`, `RandomizedDelaySec=300`,
  `AccuracySec=1min`, `WantedBy=timers.target`; root service,
  `TimeoutStartSec`, `Nice=10`). Daily 00:30 UTC, weekly Sun 04:30 UTC.
  **Not installed/started on the host** (deploy step 1, per the task
  constraints).
- **Installer:** `scripts/security-install-timers.sh` mirrors
  `scripts/backup-install-timers.sh` (root check, copy 4 units,
  daemon-reload, enable + restart, idempotent, on-demand hints). Not run
  (deploy step 1).
- **`bash -n homelab.sh`** → OK.
- **`./homelab.sh security status`** (from the worktree) →
  ```
  latest report: /home/chuck/data/security/reports/security-report-2026-11-27.md
    verdict: 2 notes
  alerts: 0 total, 0 unread since last status
  baseline: 0 days old (2026-11-27T01:46:21Z)
  ```
  Reads `/home/chuck/data/security` (host data path) so it works from any
  checkout; "unread" = alerts newer than the last status marker
  (`/home/chuck/data/security/.last-status-ts`).
- **Edge paths:** `./homelab.sh security` → usage (exit 0);
  `./homelab.sh security bogus` → error (exit 2).

### TODO 5 — compose metrics + deploy runbook

- **YAML:** `python3 -c 'yaml.safe_load(...)'` on `compose.monitoring.yml`
  → parses; node-exporter gains the ro volume
  `/home/chuck/data/security/metrics:/host/security-metrics` +
  `--collector.textfile.directory=/host/security-metrics`. **Not applied**
  (no container recreate — deploy step 4).
- **Runbook:** `docs/security_phase10_deploy.md` covers install → root
  baseline → first scan → node-exporter recreate + scrape check →
  `security status` → observation-mode start date + 2-week tuning, with a
  full rollback section.

## Could-not-verify (declared, not simulated)

- **Full `docker compose config` render** of `compose.monitoring.yml` —
  the worktree has no `.env` (gitignored; lives in the main repo). YAML
  parse + section inspection done instead; the render check is deploy
  step 4 on the host.
- **Timer install/enable** — deploy step 1 (constraint: units are written,
  not activated).
- **Root-capture fidelity** — LISTENERS process column and
  `/var/spool/cron/crontabs` hashes require root; the non-root captures
  above are honest but less complete. Deploy step 2 captures the official
  root baseline.
- **Live node-exporter scrape** of `security_scan_*` — deploy step 4.
- **SMTP on real port 25** — needs root to bind; the detection code path
  was verified on a non-privileged port via conf override.
- **shellcheck** — not installed on the host (`bash -n` used instead).
- **2-week observation/tuning** — post-deploy (runbook §6).

## Observations (out of scope, noted for the record)

- **Pre-existing `homelab.sh` usage bug:** the `usage()` heredoc is
  unquoted (`<<EOF`) and contains backticked words (`` `rebuild` ``,
  `` `restart` ``), so `./homelab.sh` with no args prints
  `line 31: rebuild: command not found` (×6) on stderr before the usage
  text. Reproduced on the unmodified main copy — pre-existing, not
  introduced here. Fix would be quoting the heredoc (`<<'EOF'`) — left
  untouched to keep this diff security-scoped.
- **Phase 4 expected-survivors list** in `security_todo.md` predates the
  mcp_kanban `:3000` LAN bind — the scan's baseline (not the Phase 4 list)
  is now the source of truth for listener expectations.
