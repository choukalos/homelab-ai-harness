# SEC Phase 11 task report — public-surface security monitoring

**Date:** 2026-11-27
**Branch:** `task/security-phase11` (worktree `/home/chuck/homelab-worktrees/security-phase11`, base `b60c01b`)
**Spec:** `security_todo.md` §Phase 11 (registry-driven design)
**Deploy runbook:** `docs/security_phase11_deploy.md`
**Status:** DEPLOYED 2026-11-27 (timers live ~01:15 / Sunday 04:40 UTC, first
daily + weekly scans run, `security_surface_*` metrics confirmed scraping from
VictoriaMetrics; observation mode on for the 2-week tuning window).

## Scope of this build

The standing registry-driven probe layer for the internet-facing surface:

**In:** 11.0 registry + registry lint (Caddyfile side; CF side token-gated),
11.2 black-box probes + negative-path canaries (P0 semantics), 11.3 DB
state diff (weekly), 11.4 Plausible admin block (probe), 11.5 daily CVE
cross-check (config-driven), 11.6 reporting into the Phase 10 pipeline +
add-a-site runbook.

**Not in this build (still open in `security_todo.md`):** 11.1 tunnel layer
(CF-API ingress audit, cloudflared version check, tunnel health, CF account
hygiene), 11.3 API anomaly detection (Caddy/invest-hub-server log analysis)
+ WAF decision + dependency scan, 11.4 deployed-content integrity +
read-only posture check + Hugo pin check, the D8 off-LAN vantage point, and
the 11.5 monthly §9 process (human cadence; the daily scan only matches the
conf `KNOWN_CVES` list that the monthly pass updates).

## Deliverables

| Item | File(s) |
|---|---|
| Registry (11.0) | `security/public-surface.yml` |
| Daily scan + conf (11.2/11.5/11.6) | `scripts/security-surface-scan.sh`, `scripts/security-surface-scan.conf` |
| Weekly check (11.3 DB diff + 11.6 digest) | `scripts/security-surface-weekly.sh` |
| Timers + installer + status | `scripts/systemd/security-surface-daily.{service,timer}`, `scripts/systemd/security-surface-weekly.{service,timer}`, `scripts/security-surface-install-timers.sh`, `homelab.sh` (`security surface`) |
| Deploy runbook | `docs/security_phase11_deploy.md` |
| Status + report | `security_todo.md` §Phase 11, this file |

## Verification (evidence per claim)

All runs 2026-11-27. Test artifacts routed to `/tmp/sec-surface-*` temp
dirs (one kept: `/tmp/sec-surface-clean.YzVPVo`); no host state changed —
no units installed, no containers touched, `/home/chuck/homelab` and
`/home/chuck/data` untouched (the prod data dir
`/home/chuck/data/security-surface` was confirmed absent after all runs).

### Registry — `security/public-surface.yml`

- **Parse:** `python3 yaml.safe_load` → 8 domains (the spec's 7 + reserved
  `test.choukalos.com` — the Caddyfile has a `host` matcher for it, so the
  lint requires registry coverage; 502 expected, a change = signal).
- **Versions live-verified 2026-11-27** (docker exec / host): litellm
  1.104.0, caddy 2.11.7, fastapi 0.165.0, express 5.2.1, prisma 7.8.0,
  nginx 1.31.7, mysqld 8.4.13 — all match the registry.
- **2 deviations from the spec seed, documented in the registry:**
  1. `/ui/` on `llm.choukalos.com` — the spec assumed no admin UI (404);
     live LiteLLM 1.104.0 serves its admin UI at `/ui/` (200 with the chuck
     key, 401 without — the Caddy gate holds). Expectation set to the
     verified live state with a risk note.
  2. `/api/schedule` on `siri.choukalos.com` — Caddy strips the `/api`
     prefix before proxying while skill-runner routes live under `/api/*`,
     so public `/api/schedule` is 404 even with a valid key.
     `/api/skills` is the live-verified gated route (401 none / 200
     chuck-key / 401 wrong-key).
- **P12-A cutover reflected:** `/media/*` backends are mcp_filebridge:8000
  (2026-11-26), not the spec's 2026-11-24 Matrix 192.168.4.55:8189 snapshot.

### Daily scan — `scripts/security-surface-scan.sh`

- **Syntax:** `bash -n` → OK (also on the conf).
- **Real read-only run** (temp data dir, live public surface):
  `surface scan complete: verdict=7 notes` (0 anomalies). 17/17 registry
  probes OK — canaries hold: llm 401 none / 401 wrong-key / 200 chuck-key;
  siri 401 none / 200 chuck-key / 401 wrong-key; api 401 none / 401
  expired-jwt; plausible `/admin/` 404 (block holds); www 301 with
  `Location` containing `choukalos.com` (redirect-intact); reserved test
  502. TLS 8× TLSv1.3, 69 days to expiry. CVE cross-check: all clean
  (MySQL 8.4.13 outside the seeded CVE-2026-101679 range 8.4.10–12).
  Registry lint: Caddyfile hosts 8 = registry domains 8 (no anomalies).
- **Report:** well-formed — header, verdict line + machine `verdict:` line,
  Anomalies/Notes with evidence blocks, per-domain probe tables, TLS/CVE/lint
  sections, observation-mode line.
- **Negative canary P0 path (re-proven this session):** synthetic registry
  flipping plausible `/js/script.js` to `expect: 404` (live returns 200) →
  `verdict=1 anomalies`, and `alerts.log` gained
  `… | critical | probe:plausible.choukalos.com | NEGATIVE CANARY FAILED:
  /js/script.js (with=none) expected 404, got 200 — … (P0 per spec 11.2)`
  — the exact `ts | severity | check | detail` format.
- **Metrics:** `metrics/security_surface.prom` —
  `security_probe_failures_total{domain=…}` (8 domains) +
  `security_surface_anomalies_total` / `_notes_total` /
  `_last_run_timestamp_seconds`, all with HELP/TYPE lines.
- **Retention:** temp dir with a 100d-old daily report + 400d-old weekly
  report + 400d-old snapshot + a 3d-old report → after a run, only the 3d
  file + today's report survived (`-mtime +90` / `+364`); the keep-newest
  snapshot guard held (a lone 400d-old snapshot was kept by the daily run's
  prune, then honestly diffed as a 288-line P0 by the weekly — drift
  detection against a stale baseline works).
- **Read-only:** GET probes only (`curl -o /dev/null`), `openssl s_client`
  handshake, Caddyfile/registry reads; no mutating requests, no auth bypass
  beyond the spec's negative tests (wrong-key / expired-jwt canaries).

### Weekly check — `scripts/security-surface-weekly.sh`

- **Syntax:** `bash -n` → OK.
- **Real run (baseline):** `schema-diff: BASELINE CAPTURED` —
  `db-snapshots/investorhub-2026-11-27.txt`, 290 lines (26 TABLE / 244
  COLUMN / 18 PRIV rows; matches the 26-table `investorhub` live count).
  Digest section well-formed (daily verdict table, recurring notes).
- **P0 change path (synthetic prior snapshot):** one removed column + one
  changed privilege vs the baseline → `CHANGED (3 lines)`,
  `alerts.log` line `… | critical | db-schema-diff | SCHEMA/PRIVILEGE CHANGE
  on investorhub: 3 line(s) differ vs … (P0 — malicious DDL or accidental
  drift)`, full diff rendered in the report.
- **Bugs found + fixed via the real run** (the DB connection was
  unreachable as first written):
  1. `.env` `INVEST_DATABASE_URL` is a compose **template** with unexpanded
     `${INVEST_DB_USER}`/`${INVEST_DB_NAME}` refs (compose interpolates at
     container start; the running container sees the literal URL). The
     script now resolves `${NAME}` refs against `.env` (loop terminates on
     an unresolvable ref — no infinite loop).
  2. Port parse kept the `/dbname` suffix (`3306/investorhub`); fixed, and
     the cred/host split now uses the **last** `@` (passwords with `@`
     still parse).
  3. `thor.local` resolves IPv6-only on the host while MySQL binds
     `192.168.4.54:3306` (documented in `.env`) → config-driven
     `DB_HOST_FALLBACK=192.168.4.54` in the conf with a one-time retry; the
     fallback connection is reported as a note, both attempts as evidence
     if the fallback also fails.
  4. `echo "```"` (three backticks in double quotes) opened an unterminated
     command substitution that swallowed later script lines — a bug
     `bash -n` cannot catch (it finds a "matching" backtick far later in
     the file). Replaced with single quotes; the CHANGED path re-verified
     clean after the fix.

### Timers, installer, `homelab.sh security surface`

- **Units:** `security-surface-daily.{service,timer}` (01:15 UTC, after the
  Phase 10 00:30 host scan) + `security-surface-weekly.{service,timer}`
  (Sun 04:40, after the Phase 10 04:30 digest) mirror the Phase 10 unit
  structure (oneshot, `WorkingDirectory=/home/chuck/homelab`,
  `TimeoutStartSec` headroom, `Nice=10`, `Persistent=true`,
  `RandomizedDelaySec=300`, `WantedBy=timers.target`).
  `systemd-analyze verify` → exit 0 on all 4 (only the expected
  pre-deploy "ExecStart script not found" warning — the scripts don't
  exist at the prod path until merge).
- **Installer:** `scripts/security-surface-install-timers.sh` mirrors the
  Phase 10 installer (root guard, copy-with-missing-check, daemon-reload,
  enable + restart, `list-timers` + on-demand hints). Self-contained per
  phase — Phase 10's installer untouched. Real run as non-root →
  `must run as root (sudo)`, exit 1 (no install, no host state change).
- **`bash -n homelab.sh`** → OK.
- **`./homelab.sh security surface`** — real runs:
  - default prod path (data dir absent pre-deploy): honest
    `none yet` / `MISSING` output, exit 0, **no writes** (marker write is
    guarded on the dir existing; the prod data dir stayed absent).
  - test-scratch dir: full output — latest daily report + `verdict: 7
    notes` + `mode: observation (report only, nothing escalated)`, latest
    weekly digest + verdict, `alerts: 0 total, 0 unread`, `schema snapshot:
    0 days old (investorhub-2026-11-27.txt)`.
  - unread counter proven: a planted post-marker alert line → `alerts: 1
    total, 1 unread since last status`.
  - `security help` → `Usage: ./homelab.sh security status|surface`;
    `security bogus` → error, exit 2. Phase 10's `security status` case is
    byte-identical (diff-verified).
- **`git diff homelab.sh`:** +64/−2, only the usage line + the `surface`
  case + help/unknown text.

## Could-not-verify (declared, not simulated)

- **CF tunnel ingress audit (11.1)** — needs `CF_API_TOKEN` (intentionally
  not in `.env`). The Caddyfile side of the registry lint is verified; the
  CF side emits an honest skip note and activates automatically when the
  token is available (deploy step 5).
- **Live-tunnel end-to-end from an off-LAN vantage (D8)** — probes run from
  the host via public DNS: the full public chain (CF edge → tunnel →
  Caddy) is exercised except the external resolver. A true outside-LAN
  vantage is a follow-up.
- **Timer install/enable + first scheduled runs** — deploy steps 1–3
  (constraint: units are written, not activated; no root deploy in the
  build session).
- **2-week observation window / threshold tuning** — post-deploy (runbook
  §6); `OBSERVATION_MODE=1` is the default until then.
- **node-exporter scrape of `security_surface_*`** — the metrics file is
  emitted and scrape-ready; the optional symlink into the Phase 10
  textfile dir is deploy step 5.
- **shellcheck** — not installed on the host (`bash -n` + real runs used
  instead).

## Observations (out of scope, noted for the record)

- **`.env` `INVEST_DATABASE_URL` is a compose template** with unexpanded
  `${...}` refs; host-side tools must resolve them (the weekly script does).
  The `.env` comment (2026-11-21) already documents the `thor.local`
  IPv6-only-on-host / MySQL-binds-LAN-IPv4 gotcha.
- **Spec seed staleness (2026-11-24 → 2026-11-27):** fastapi 0.156.8 →
  0.165.0; the P12-A cutover moved `/media/*` off Matrix;
  `test.choukalos.com` reserved hostname not in the seed. The registry
  reflects the live Caddyfile/containers, with the deviations documented
  inline.
- **hugo 0.165.0 deployed vs ≥0.168.0 requirement** (9.3-H1 open) — noted
  in the registry; the 11.4 Hugo pin check is still open.
- **HSTS absent on 6 domains** — CF terminates TLS (Caddy `auto_https`
  off); tracked at `note` severity by default, first observation-mode
  tuning candidate (runbook §6).
- **Pre-existing `homelab.sh` usage() heredoc bug** (backticked words in an
  unquoted heredoc print `command not found` lines on bare invocation) —
  noted in the Phase 10 report, still pre-existing, untouched to keep this
  diff security-scoped.

## Morning summary (2026-11-27)

**What was built** (SEC Phase 11, all in the worktree, uncommitted):
the `security/public-surface.yml` registry (8 domains, live-verified
versions, runbook contract), the registry-driven daily scan
(`scripts/security-surface-scan.sh` + conf — 17 probes with auth-gate
canaries, TLS, headers, CVE cross-check, registry lint; observation mode ON
by default), the weekly InvestHub schema-diff + digest
(`scripts/security-surface-weekly.sh`), 4 systemd units + installer
(written, not installed), and `./homelab.sh security surface` on-demand
status.

**Verification evidence per claim:** see the per-section evidence above —
`bash -n` on every script, real read-only runs against the live public
surface (17/17 probes OK, 8× TLSv1.3, lint 8=8, baseline 26 tables /
244 columns / 18 privileges), synthetic P0 proofs for both critical paths
(negative-canary fail + schema/privilege change), retention pruning
proven, metrics + alerts format verified, units `systemd-analyze verify`
clean, installer root-guard proven, status subcommand run against real
artifacts.

**What could NOT be verified:** CF tunnel ingress lint (needs
`CF_API_TOKEN`), off-LAN vantage (D8), timer install + first scheduled
runs (needs root; deploy steps), the 2-week observation window,
node-exporter scrape of the new metrics.

**What is uncommitted** (11 new files + 2 modified, branch
`task/security-phase11` at `b60c01b`): `security/public-surface.yml`,
`scripts/security-surface-scan.{sh,conf}`, `scripts/security-surface-weekly.sh`,
`scripts/security-surface-install-timers.sh`,
`scripts/systemd/security-surface-{daily,weekly}.{service,timer}`,
`docs/security_phase11_{deploy,report}.md`, `security_todo.md` (Phase 11
closeout), `homelab.sh` (+64/−2, `security surface`).

**Exact next steps for the user:**

```bash
# 1. Review the uncommitted work
cd /home/chuck/homelab-worktrees/security-phase11
git status --short && git diff homelab.sh

# 2. Commit on the branch (commits were disabled during the build)
git add security/ scripts/security-surface-* scripts/systemd/security-surface-* \
        docs/security_phase11_deploy.md docs/security_phase11_report.md \
        homelab.sh security_todo.md
git commit -m "security: Phase 11 public-surface monitoring (registry, daily/weekly scans, timers, status)"

# 3. Merge into main on the host (main is at b60c01b — clean merge)
cd /home/chuck/homelab
git merge task/security-phase11

# 4. Deploy (runbook steps 1–4)
sudo scripts/security-surface-install-timers.sh
sudo scripts/security-surface-scan.sh      # first daily scan (observation mode)
sudo scripts/security-surface-weekly.sh    # schema-diff baseline capture
./homelab.sh security surface

# 5. Optional (runbook step 5): CF_API_TOKEN for the CF ingress lint +
#    the node-exporter metrics symlink

# 6. Observation mode: OBSERVATION_MODE=1 is the conf default — record the
#    start date in docs/security_phase11_deploy.md §6 and security_todo.md;
#    2-week tuning due ~2026-12-11, then flip OBSERVATION_MODE=0.
```

## Deploy closeout (2026-11-27, post-hoc)

Deployed the same day: merged to `main` (`edd1c51`), all runbook steps
executed and verified — 4 timers live (surface daily ~01:15 / weekly Sun
04:40 UTC, offset from Phase 10's 00:30 / 04:30), first daily scan
`verdict=7 notes, 0 anomalies` (6 HSTS header notes + 1 CF-lint skip),
first weekly run `schema-diff: BASELINE CAPTURED` (26 tables / 244 cols /
18 privileges), `security surface` status verified, observation mode
started 2026-11-27 (tuning due ~2026-12-11).

Two post-deploy failures found on first live use and fixed (`9d229df`):
1. `security surface` exited 1 on the root-owned data dir (unread-marker
   write not best-effort) — now best-effort with correct redirect order;
   `sudo chown -R chuck:chuck /home/chuck/data/security-surface` (runbook
   step 2) makes the marker writable so the unread count resets.
2. node-exporter served 0 `security_surface_*` metrics — the step-5
   symlink was invisible to the textfile collector (it does not follow
   symlinks); the daily scan now auto-syncs a real copy to the Phase 10
   collector dir (`SEC_METRICS_SYNC_DIR`), scrape-verified.

Worktree/branch cleanup done 2026-11-27; status lines flipped to
DEPLOYED (`aaf46e7`).
