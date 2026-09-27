# Thor Data Audit + NAS Backup Plan

> Date: 2026-09-26 (v4 — multi-machine NAS design + recovery tooling + CIFS hardening. v2 decisions: weekly cadence, 2-week retention + one-off, no encryption, orphans deleted. **v4 corrections (2026-09-27): Lego is a QNAP NAS (not macOS), hostname-dir structure confirmed, VM (Victoria Metrics) mirror kept — the metrics are valuable**)
> Scope: `/home/chuck/homelab`, `/home/chuck/data`, `/home/chuck/workspace` (+ critical out-of-scope gaps)
> Goal: validate the 3-dir classification, establish a storage-kind NAS backup strategy, and de-risk the SSD upgrade.

---

## 0. Executive Summary

| Dir | Size | Intended role | Verdict |
|---|---|---|---|
| `homelab/` | 203M | Code + config, checked into GitHub | ✅ **Yes** — git repo `choukalos/homelab-ai-harness`, clean tree, in sync with `origin/main`. `.env` (secrets) is correctly *not* in git and gets its own backup path. |
| `workspace/` | 91M | Temporal/scratch data | ✅ **Yes** — vision artifacts (91M), media staging, scratch scripts. All regenerable. |
| `data/` | 6.0G | Service data, backup to NAS | ✅ **Yes, mostly** — all Docker bind-mounted service state. ~4.5G is regenerable (metrics, caches, diag logs) and excluded from the NAS payload. |

**Decisions locked in (2026-09-26):**
1. NAS share/creds: **resolved** — share `backup` + user `backup`; creds live in `~/.smbcredentials` (mode 600) on each host — never in the repo, docs, logs, or summaries. Lego is a **QNAP NAS** (QTS) with T's of GB free.
2. Victoria Metrics: **keep history, minimize backup cost** → weekly rsync *mirror* (one copy, ~3G one-time + ~50MB/wk), no retention change, no snapshot series.
3. `media/generated`: **skipped** entirely.
4. Orphans `data/postgres` (67M) + `data/prometheus` (57M): **delete** (safety-checked first).
5. `lab-keys/`: sensitive — **excluded**, Chuck backs up separately.
6. `.env`: **plain archive, no encryption** (homelab-trust environment; avoids recovery hassle).
7. **Multi-machine**: one NAS share (`backup`) + one non-admin backup user, shared by all machines (Thor, Matrix, future hosts). Each host writes only to its own subdirectory (`thor/`, `matrix/`, …); `HOST_ID` comes from `/etc/hostname` (Matrix's proven approach), not the config. Collision rules in §3.5.
8. **Recovery tooling**: `scripts/backup-restore.sh` — partial recovery (any single item from any run) and full recovery (fresh-disk rebuild = the SSD-swap runbook), sha256-verified against run manifests, dry-run by default. §3.6.
9. **NAS-failure hedge**: the daily run also keeps the last 2 daily tiers locally in `data/backups/nas-hedge/` (~50 MB) — insurance against NAS share loss/deletion.
10. **Backup chain (offsite covered downstream)**: Thor/Matrix → **Lego** (`backup` share) → **Athena** (192.168.5.110, second NAS) → USB drives, plus a fire-safe for critical files (`.env`, `lab-keys`). Athena is *downstream* in the chain, not a backup host — offsite is out of scope for the Thor/Matrix build.

**Build status (2026-09-26):** all scripts built and **tested end-to-end against a local staging dir** (no NAS mount needed): `backup-nas.sh` (daily/weekly/change-detect/prune, 0 failures), `backup-restore.sh` (every item type, `--full --target` staging + generated RUNBOOK, `--test` disposable containers), `backup-verify.sh` (mysql/qdrant/pg all PASS). ClickHouse native backup/restore verified live. Only remaining blocker is the NAS credential (C1).

**Strategy (the short version):**
- **Daily 03:00** — Qdrant (memory + KB) + `.env` + `ai-kb` sources. ~25 MB/run.
- **Weekly Sun 04:00** — everything else (DB dumps, ClickHouse, media, VM, misc), with **change detection**: unchanged dumps are not re-stored. At most one update/week, and only when something actually changed.
- **One-off (manual)** — `backup-nas.sh --one-off <label>`: full run, tagged, never auto-pruned. This is the SSD-swap snapshot.
- **Retention: 2 weeks + one-off** — 14 daily, 2 weekly, 1+ tagged one-off. Mirrors (ai-kb, media, documents, victoria-metrics) are single copies with no retention growth.
- **Multi-machine**: one `backup` share + one user on Lego (QNAP); per-host subdirs, per-host config, collision rules in §3.5.
- **Recovery**: `backup-restore.sh` — partial (any item, any run) or full (fresh-disk rebuild), verified, dry-run by default (§3.6).
- **Estimated NAS footprint: ~4.6 GB total, bounded by the 2-week retention** (Thor; Matrix TBD pending inventory). The VM (Victoria Metrics) mirror is 3.0 GB of the total — the metrics are valuable, so it's kept. Lego has T's of GB free — footprint is not a constraint.

**Backup chain (offsite covered):** Thor/Matrix → **Lego** (primary NAS, QNAP, share `backup`) → **Athena** (second NAS, 192.168.5.110) → **USB drives**, plus a **fire-safe** for critical files (`.env`, `lab-keys/`). Athena is a downstream copy target, *not* a backup host. Building the offsite copy is out of scope today — the chain already exists.

**Verified backup mechanics (tested 2026-09-26):**

| Item | Method | Size (uncompressed) |
|---|---|---|
| MySQL `homelab` (8 tables) | `mysqldump -h thor.local -u ai` (creds from `.env`, via `MYSQL_PWD`) | 42 MB |
| MySQL `investorhub` | `mysqldump -h thor.local -u investor` | 578 MB |
| litellm-postgres | `docker exec litellm-db pg_dumpall -U litellm` | 29 MB |
| plausible-db | `docker exec plausible-db pg_dumpall -U plausible` | 1.3 MB |
| ClickHouse (plausible events) | native `BACKUP DATABASE` — **needs one config addition** (`backups.allowed_disk`) | 32 MB |
| Qdrant (15 collections) | existing snapshot pattern from `backup-kb.sh`/`backup-memory.sh` | 23 MB |
| `.env` | plain tar | 8 KB |

> Note: MySQL users are `ai@%` / `investor@%` — dumps must connect via `thor.local:3306` (TCP), **not** `localhost` (no localhost host entry).

---

## 1. Directory Audit

### 1.1 `/home/chuck/homelab` (203M) — code/config ✅

**Git status:** repo `choukalos/homelab-ai-harness`, branch `main`, working tree clean, `0 ahead / 0 behind origin/main` (verified 2026-09-26). 277 tracked files, ~2.8 MB of actual content.

| Path | What | Notes |
|---|---|---|
| `compose/` | 9 compose files (core, ai-core, mcp, monitoring, edge, invest-hub, n8n, portal, skill-runner) | Single source of truth for all containers |
| `mcp/servers/` | 10 MCP server implementations | Built into containers |
| `skills/`, `agents-skills/` | Skill definitions + runner | |
| `grafana/` | Provisioning + dashboards (JSON) | Dashboards versioned in git |
| `caddy/`, `litellm/`, `prometheus/`, `searxng/`, `plausible/` | Service configs | Bind-mounted into containers |
| `scripts/` | Ops scripts incl. `backup-kb.sh`, `backup-memory.sh`, cleanup scripts | |
| `docs/` | Architecture + planning docs | |
| `homelab/scheduler/` | `schedules.json` (config) | Runtime state lives in `data/scheduler/state.json` |
| `.env` (untracked) | **All secrets: DB passwords, API keys, tokens** (8.6 KB, mode 600) | Gitignored by design. Most important non-code file on the box. |

**Findings:**
- ✅ Classification holds: everything that matters is in git and pushed.
- ⚠️ `.git` is **198M** because history contains: three 102 MB `skill_runner.log` files, `ai-harness.zip` (8.9 MB), and `node_modules/` (all since removed from HEAD). Not a data-loss risk (GitHub has it), but slow to clone. *Optional* one-time cleanup via `git filter-repo` + force-push.
- ⚠️ `siri-script.sh.bak` and `grafana/dashboards/*.bak*` are ignored scratch — dead weight.

### 1.2 `/home/chuck/workspace` (91M) — temporal ✅

| Path | Size | What | Disposition |
|---|---|---|---|
| `vision/` | 91M | Frames + reports from `mcp_vision` analysis | Ephemeral — `scripts/cleanup-vision.sh` exists |
| `media/` | 156K | Media-pipeline **staging dir** (7-day retention, `cleanup-media-staging.sh`) | Ephemeral. Contains stale `media-mcp-client/` scratch copy (canonical: `mcp/servers/media/`) + `HANDOFF.md` notes not in the repo → move to `docs/` |
| `homelab-scratch/` | 264K | Scratch Python, pi-long-task results | Ephemeral |

**Findings:** classification holds; nothing load-bearing.

### 1.3 `/home/chuck/data` (6.0G) — service data ✅ (with gaps)

Classification key: **CRITICAL** = irreplaceable, must back up · **KEEP** = worth keeping, cheap · **REGEN** = regenerable, excluded from NAS

| Dir | Size | Service (container) | Class | What's in it |
|---|---|---|---|---|
| `qdrant/` | 23M | `qdrant` | **CRITICAL** | 15 collections: `mem0_memories` (long-term memory), `mem0migrations`, 13 `kb_*` (house, gaming, family, vehicles, guitar, travel, literature, ai, user, homelab, media, music, media_test) |
| `ai-kb/` | 317M | `mcp_knowledge`, `mcp_vision` | **CRITICAL** | `raw/` = KB source documents (ingest allowlist roots), `digests/` |
| `media/` | 504M | `portal`, `mcp_media`, `mcp_mysql` (csv) | **CRITICAL** (parts) | `public/` 179M = **published website content** (video 169M, images, audio); `images/` 19M + `presentations/` 18M = generated user artifacts; briefs/reports/csv ~1M; `generated/` 284M = **SKIPPED per decision** |
| `open-webui/` | 910M | `open-webui` | **CRITICAL** (parts) | `webui.db` 4.2M (accounts/chats/config) **CRITICAL**; `uploads/` 16M **KEEP**; `cache/` 889M **REGEN** (skip) |
| `victoria-metrics/` | 3.0G | `victoria-metrics` | **KEEP (mirror)** | Metrics TSDB, `--retentionPeriod=1y` — the metrics are valuable, so the mirror is kept. Weekly rsync mirror, single copy, ~50 MB/wk increment. Excludes root-owned `cache/`/`tmp/`. |
| `invest-hub-runner/` | 425M | `github-runner` | **REGEN** | `_diag/` diagnostic logs |
| `logs/` | 99M | `skill-runner` | **REGEN** | `skill_runner/` logs |
| `backups/` | 495M | — (ops) | staging | Existing **local** backups (Qdrant + `.env`), 2026-08-26…29. Same-disk, stale — superseded by the NAS plan. Thin out after first NAS backup lands. |
| `prometheus/` | 57M | — (orphan) | **DELETE** | Old Prometheus WAL — no such container (VM replaced it) |
| `postgres/` | 67M | — (orphan) | **DELETE** | Old Postgres data dir, untouched since 2026-05-22, no compose reference |
| `plausible-events-db/` | 32M | `plausible-events-db` (ClickHouse 24.12) | **CRITICAL** | Website analytics events |
| `plausible-db/` | ~4M | `plausible-db` (Postgres 16) | **CRITICAL** | Plausible app DB |
| `litellm-postgres/` | ~29M dump | `litellm-db` (Postgres 16) | **CRITICAL** | LiteLLM proxy DB: API keys, spend tracking |
| `presenton/` | 38M | `presenton` | **KEEP** | `exports/` 31M (decks), `fastapi.db` 2M, userConfig |
| `grafana/` | 56M | `grafana` | **KEEP** | `grafana.db` 3.2M (users/alerts; dashboards in git), `plugins/` 49M REGEN |
| `mem0/` | 28K | `skill-runner` | **CRITICAL** | mem0 local state |
| `documents/` | 20K | — | **CRITICAL** | Personal docs (GURPS character, presentation outline) |
| `n8n/` | 20K | `n8n` (stopped) | KEEP (cheap) | n8n workflows (service currently off, data retained) |
| `portal/` | 3M | `portal-git-sync` | REGEN | clone of `choukalos/homelab-blog` (GitHub is source of truth) |
| `caddy/`, `searxng/`, `searxng-valkey/`, `redis/`, `scheduler/`, `mysql-mcp-csv/`, `litellm/`, `crawl4ai/`, `invest-hub/`, `plausible-app/`, `plausible-events-logs/` | <100K total | various | KEEP (cheap) | Tiny state/cache — one rsync for completeness |

**Out-of-scope gaps (not in the 3 dirs):**

| Item | Location | Class |
|---|---|---|
| **MySQL 8.0 data** (databases `homelab`, `investorhub`) | `/var/lib/mysql` — **host systemd service, not Docker** | **CRITICAL** — covered by weekly dumps (verified working, §0 table) |
| Docker images + layers | `/var/lib/docker` (root) | REGEN — `docker compose` + `git clone` rebuilds everything |
| `~/.ssh/`, `~/.gitconfig`, shell config, `~/.pi` (116M) | `/home/chuck/*` | KEEP — small dotfiles tar in the weekly run |
| `lab-keys/` | `/home/chuck/lab-keys` | **EXCLUDED** — sensitive; Chuck backs up separately (decision 5) |

---

## 2. Current Backup State (what exists today)

| Mechanism | Coverage | Destination | Freshness |
|---|---|---|---|
| GitHub (`homelab-ai-harness`, `homelab-blog`) | All code/config | GitHub | ✅ in sync |
| `scripts/backup-memory.sh` | `.env` + Qdrant `mem0_memories` | `data/backups/` (**same disk**) | 2026-08-28 (stale) |
| `scripts/backup-kb.sh` | All `kb_*` snapshots + `ai-kb` sources tar | `data/backups/kb/` (**same disk**) | 2026-08-29 (stale) |

**Problems the new plan fixes:** local-only (dies with the SSD), manual (already drifted a month), coverage stops at Qdrant + `.env` (no MySQL/Postgres/ClickHouse/media/documents).

---

## 3. Backup Strategy (revised — storage-kind)

### 3.1 Cadence

| Run | When | What | Typical payload |
|---|---|---|---|
| **Daily** | 03:00 | Qdrant snapshots (all 15 collections) + `.env` tar + `ai-kb` rsync | ~25 MB + deltas |
| **Weekly** | Sun 04:00 | MySQL dumps ×2, litellm-postgres, plausible-db, ClickHouse backup, media/documents/presenton/open-webui/grafana/mem0/n8n/misc rsync, **VM rsync mirror**, dotfiles tar, git bundle | ~150 MB changed (700 MB raw dumps gzipped to ~150 MB) |
| **One-off** | manual: `backup-nas.sh --one-off <label>` | Full run (daily + weekly classes) + tag the snapshot dir; **excluded from auto-prune** | ~200 MB (dumps+snapshots; mirrors already current) |

**Change detection (weekly, per decision "only if there are changes"):**
- Each DB dump is hashed (sha256); if identical to the previously stored dump → **not re-stored** (log "unchanged — skipped").
- Mirrors: rsync is naturally incremental (only changed files transfer).
- Git: bundle stored only if HEAD moved since last weekly run.
- Net effect: quiet weeks cost ~0 MB; active weeks cost ~150 MB.

**Retention (2 weeks + one-off):**
- Daily (Qdrant/.env/ai-kb): keep **14** (~350 MB).
- Weekly: keep **2** (~300 MB).
- One-off: **never pruned** (manual delete only).
- Mirrors (ai-kb, media, VM, documents): **single copy, no retention** — always current, zero growth beyond the source data itself.
- **Local hedge (decision 9)**: the last 2 daily tiers are also kept locally in `data/backups/nas-hedge/` (~50 MB) — if the NAS share is lost, the freshest memory/`.env`/ai-kb state survives on the SSD.

### 3.2 NAS layout (multi-host)

NAS = **Lego, 192.168.5.100** — a **QNAP NAS** (QTS) with T's of GB free. **One share: `backup`. One backup user** (`backup`, non-admin) — shared by every machine. Each host mounts the same share at its own local `/mnt/lego` (CIFS; per-machine creds in `~/.smbcredentials`, mode 600) and writes only to its own subdirectory.

> **CIFS / QNAP-SMB quirks (measured on Matrix 2026-09-26 — see `scripts/backup/README.md` on Matrix for the full write-up):**
> 1. **SMB 2.1 only.** SMB3 → `EOPNOTSUPP`, SMB 2.0.2 → `EINVAL`. Pin `vers=2.1` in fstab.
> 2. **Idle sessions killed fast** (~18 s–3 min). Continuous I/O keeps the session alive; a stale mount must be remounted. Mount + work in **one continuous invocation** (a ~1 min gap risks a dead session).
> 3. **Dead session on a hard mount = fatal** (D-state zombies, unkillable). Mounts use **`soft:`** so a dead session errors out instead of wedging the kernel.
> 4. **Login rate-limiting after session churn** (transient `NT_STATUS_LOGON_FAILURE`, clears in minutes). Never retry faster; the self-heal waits it out.
> 5. **No real Unix modes** — the server reports 755 for everything. rsync uses **`-rt`** (not `-a`), and `--modify-window=1` for `--link-dest` hardlinks (CIFS truncates mtime to 100 ns).
> 6. **D-state `cifsd`/`umount` in `ps` → reboot the host.** Nothing else clears it.
>
> Mitigations in the scripts: `ensure_mounted` (bounded self-heal: probe → `umount -l` → remount), `RSYNC_FLAGS` (`-rt --modify-window=1 --timeout=60`), a post-run sha256 integrity verify, and a free-space guard.

```
//lego/backup/
├── thor/                            # ← per-host dir = /etc/hostname (HOST_ID)
│   ├── daily-<YYYYMMDD-HHMMSS>/     # keep 14 (2 weeks)
│   │   ├── manifest.json            # commit marker: items, sha256, sizes, duration, skips
│   │   ├── qdrant/<collection>-<stamp>.snapshot (×15)
│   │   └── env-<stamp>.tar.gz
│   ├── weekly-<YYYYMMDD-HHMMSS>/    # keep 2 (2 weeks)
│   │   ├── manifest.json
│   │   ├── mysql/homelab-<stamp>.sql.gz
│   │   ├── mysql/investorhub-<stamp>.sql.gz
│   │   ├── litellm-postgres-<stamp>.sql.gz
│   │   ├── plausible-db-<stamp>.sql.gz
│   │   ├── clickhouse-<stamp>.tar
│   │   ├── presenton/  open-webui/  grafana.db  mem0/  n8n/
│   │   ├── misc-<stamp>.tar.gz  dotfiles-<stamp>.tar.gz
│   │   └── homelab-git-<stamp>.bundle
│   ├── one-off-<label>-<stamp>/     # never pruned; same layout, tagged
│   ├── mirrors/                     # single copy, always current, no retention
│   │   ├── ai-kb/  media/  documents/  victoria-metrics/
│   └── restore-log/                 # every restore op logged here (audit trail)
├── matrix/                          # same shape; items TBD (open item 6)
└── <future-host>/                   # e.g. athena — add a dir + config, nothing else
```

> **Structure = hostname dir on the share.** Each host writes only under `<share>/<hostname>/` (HOST_ID from `/etc/hostname` — Matrix's proven approach). The run dirs are timestamped (`daily-<YYYYMMDD-HHMMSS>`); a run dir without `manifest.json` is uncommitted and ignored by prune/restore.

- Mirrors live in one place per host (`<host>/mirrors/`) — not duplicated across retention tiers.
- **Staging + commit**: each run writes to `<host>/.staging-<stamp>/` and moves (commits) items into place only after all succeed; the manifest is written last. Pruning and restore only consider committed runs (manifest present) — a crashed run can never leave a half-written artifact that looks complete.
- **Concurrency**: one `flock` per host (local lockfile) — a timer run and a manual one-off can never interleave on the same host.

### 3.3 Estimated NAS footprint

| Class | One-time | Growth |
|---|---|---|
| Qdrant daily ×14 | 350 MB | ~25 MB/day (pruned at 14) |
| Weekly ×2 (dumps etc.) | 300 MB | ~150 MB/week (pruned at 2) |
| ai-kb mirror | 317 MB | only on new KB docs |
| media mirror (excl. generated) | 250 MB | only on new published/generated-kept files |
| documents mirror | ~50 MB | only on new documents |
| VM mirror (Victoria Metrics) | 3.0 GB | ~50 MB/week (1y retention) |
| One-off | 200 MB | per manual run (not recurring) |
| **Total** | **~4.5 GB** | **~100–150 MB/week steady-state** |

> **Lego has T's of GB free — footprint is not a constraint.** The VM mirror (Victoria Metrics, 3.0 GB) is **kept** — the metrics are valuable (confirmed 2026-09-27; initially mistaken for docker images, which live in `/var/lib/docker` and were never in the backup). Retention on the daily/weekly runs is capped at **2 weeks** (14 daily + 2 weekly); the mirrors are single always-current copies. A `min_free_kb` guard (default 5 GB) still aborts a run if the NAS ever fills up.

### 3.4 Verification

- Every run writes `manifest-<stamp>.json` (items, sha256, sizes, duration, skips) to the NAS + `~/.local/state/backup-nas.log`.
- **Monthly restore test** (`scripts/backup-verify.sh`): restore latest MySQL dump + one Qdrant snapshot into throwaway containers, run smoke queries, log result to NAS. **This is the gate before the SSD swap.**
- Failure handling: non-zero exit + flag file; the weekly run re-runs everything it skipped if a previous run failed (manifest-driven).

### 3.5 Multi-machine design (collision avoidance)

**Model:** one share, one user, per-host subdirectories. Every host runs the *same* `backup-nas.sh` engine, driven by a per-host config file `scripts/backup-hosts/<host>.json` in the shared repo.

| Concern | Rule |
|---|---|
| Namespace | Host `thor` writes only to `backup/thor/`. `HOST_ID` comes from **`/etc/hostname`** (Matrix's proven approach — no per-host config value to drift). The script validates `HOST_ID` against `^[a-z0-9][a-z0-9-]*$` and builds every path as `backup/<HOST_ID>/…`; prune/restore refuse to touch anything outside that prefix. |
| Filename collisions | Every artifact is stamped (`<YYYYMMDD-HHMM>`); one-offs are labeled. Two hosts can never collide — different subdirs, unique stamps. |
| Shared mutable state | None. Manifests are per-run, per-host. No lockfile, counter, or index is shared across hosts. |
| Creds | Per-machine local (`~/.smbcredentials`, mode 600). Same NAS user on every host is fine — SMB auth is per-connection. |
| Mount point | Local per host (`/mnt/lego`). The NAS sees one share; there is no NAS-side per-host mount concept. |
| Adding a machine | (1) clone the repo, (2) add `scripts/backup-hosts/<host>.json`, (3) create `~/.smbcredentials`, (4) mount + timer. No NAS-side change needed — the first run creates its subdir. |
| Host-ID registry | `thor` (192.168.4.54) · `matrix` (192.168.4.55) · future: `athena`? — recorded here so IDs never duplicate. |

**Deliberately NOT doing:** per-machine shares (`backup-thor`, `backup-matrix`) or per-machine NAS users — more QNAP share objects, no real isolation gain; the script enforces the namespace.

**Optional hardening (Q4):** a per-share quota on the `backup` share (QNAP QTS supports share quotas) as a backstop. The backup script's `min_free_kb` guard (default 5 GB) is the primary control; a QNAP share quota would be a second line of defense.

### 3.6 Recovery tooling (partial + full)

New script: `scripts/backup-restore.sh` (same repo → available on every host; can restore any host's backups from any host).

**Interface:**

| Command | What |
|---|---|
| `backup-restore.sh --list [host]` | Available runs (daily/weekly/one-off) + items, sizes, manifest sha256, age |
| `backup-restore.sh --item <item> [--from <run>] [--dry-run]` | **Partial recovery** — one item from a chosen run (default: latest) |
| `backup-restore.sh --full [--from <run>] [--target <dir>]` | **Full recovery** — fresh-disk rebuild (the SSD-swap runbook, §4.3) |

**Partial recovery semantics:**
- Every restore verifies the artifact's sha256 against the run's manifest **before** touching anything.
- **Dry-run by default** for anything that overwrites live state — it shows exactly what would change; `--yes` executes.
- Per-item methods:

| Item | Method | Destructive? |
|---|---|---|
| MySQL dump | pipe into a throwaway container (test) or `mysql < dump` into a named DB (`--yes`, writers stopped first) | yes (DB) |
| Postgres dump (litellm/plausible) | `psql < dump` into a fresh or named DB | yes (DB) |
| ClickHouse backup | restore into a fresh container's data dir, or `RESTORE` into a live CH | yes (DB) |
| Qdrant snapshot | `snapshots/recover` API, per-collection (existing procedure, `priority: "snapshot"`) | yes if the collection has data |
| `.env` | extract to temp dir + diff against live; never overwritten without `--yes` | no by default |
| rsync mirrors (ai-kb, media, documents, VM, …) | `rsync -a` back to the source path (dry-run by default) | yes (files) |
| dotfiles / git bundle | extract to temp dir; `git bundle` → `git fetch` into a clone | no by default |
| one-offs | same as any item — one-offs are just tagged runs | |

- Every restore op (item, run, sha256 check, target, outcome) is appended to `~/.local/state/backup-restore.log` **and** `<host>/restore-log/` on the NAS — an audit trail of everything ever restored.

**Full recovery semantics (fresh disk):**
- `--full` orchestrates the §4.3 runbook end-to-end: repo + `.env` → mirrors → DBs (fresh containers, users recreated from `.env`) → Qdrant snapshots → `docker compose up -d` → verification checklist.
- `--target <dir>` stages the rebuild out-of-place (e.g. onto the new SSD before cutover), so the physical swap is the last, trivial step.
- Point-in-time: `--from one-off-ssd-upgrade-<stamp>` picks the exact run; default = latest committed run.

**Restore test (monthly + pre-swap gate):** `scripts/backup-verify.sh` becomes a thin wrapper: `backup-restore.sh --item mysql/homelab --item qdrant/mem0_memories --from latest --test` → throwaway containers, smoke queries, result logged to NAS. No live state touched.

**Worst-case coverage matrix:**

| Failure | Recovered by |
|---|---|
| Thor SSD dies | Full recovery from latest run + one-off (§4.3 runbook) |
| One DB corrupted/deleted on a live system | Partial: `--item mysql/investorhub --from weekly-<last-good>` |
| A Qdrant collection wiped | Partial: snapshot restore for just that collection |
| `.env` lost/corrupted | Partial: extract + diff (14 daily copies available) |
| Published media files deleted | Partial: rsync from `thor/mirrors/media/` |
| NAS share deleted/failed | GitHub (code) + 2-day local hedge (decision 9); recreate share, re-run backup (mirrors rebuild from source) |
| NAS + SSD both fail (same power event) | GitHub + local hedge only — offsite copy is **out of scope today** (Q7) |

---

## 4. Implementation — who does what

### 4.1 Chuck (human-only)

| # | Item | Status |
|---|---|---|
| C1 | **NAS share + backup user on Lego**: share `backup` + one non-admin user (`backup`) shared by all machines (per §3.5) + `~/.smbcredentials` (mode 600) on each host. | ✅ resolved — share `backup` + user `backup`; creds in `~/.smbcredentials`; one-time mount setup via `sudo scripts/backup-setup.sh` (cifs-utils + fstab `vers=2.1,soft,noauto` + scoped sudoers) |
| C2 | SSD swap (physical) | ⏳ after one-off + verify |
| C3 | `lab-keys/` backup (separate process) | ⏳ Chuck's call |
| C4 | Approve one-time system changes I make: (a) ClickHouse `backups.allowed_disk` config + `plausible-events-db` restart (~10 s) — **done + tested 2026-09-26**; (b) delete `data/postgres` (67M) + `data/prometheus` (57M) — **`data/postgres` deleted; `data/prometheus` is root-owned → needs `sudo rm -rf /home/chuck/data/prometheus`**; (c) `apt install cifs-utils` + fstab mount + systemd timers (needs sudo) | ✅ a done; b partial (sudo needed for prometheus); c at implementation time |

### 4.2 Me (agent)

| # | Item | Notes |
|---|---|---|
| A1 | `scripts/backup-nas.sh` — single host-agnostic engine: `daily` / `weekly` / `--one-off <label>` modes, per-host config (`scripts/backup-hosts/<host>.json`), change detection, retention prune, manifest, staging+commit, flock | ✅ built + tested (daily/weekly/change-detect/prune, 0 failures) |
| A2 | `scripts/backup-verify.sh` — monthly restore test (throwaway containers, smoke queries) | ✅ built + tested (mysql/qdrant/pg all PASS) |
| A3 | `plausible/clickhouse/backups.xml` + compose mount (`backups.allowed_disk: default`) | ✅ done + tested (BACKUP/RESTORE cycle live) |
| A4 | Safety-check + delete orphans `data/postgres`, `data/prometheus` | ✅ `data/postgres` deleted (no compose refs, no open handles); `data/prometheus` root-owned → sudo needed |
| A5 | Move `workspace/media/media-mcp-client/HANDOFF.md` → `docs/media-mcp-handoff.md` | ✅ done |
| A6 | After C1 lands: mount, first full backup, **one-off**, restore test, timers | the SSD-swap gate |
| A7 | Thin out stale `data/backups/` local snapshots (after first NAS backup verified) | frees ~450 MB |
| A8 | `scripts/backup-restore.sh` + `scripts/backup-lib.sh` — partial + full recovery (manifest-verified, dry-run by default, restore-log) + per-host config layout `scripts/backup-hosts/` | ✅ built + tested (all item types, `--full --target` staging + RUNBOOK, `--test` disposable containers) |

### 4.3 SSD upgrade runbook (ordered)

1. **Pre-flight:** A1–A5 done; C1 done; latest backup <24 h old; `git status` clean + pushed; `backup-verify.sh` passed.
2. **Snapshot:** `backup-nas.sh --one-off ssd-upgrade` (final, tagged, protected).
3. **Swap SSD** (fresh Ubuntu 24.04 recommended over disk-clone — clean slate, and the restore path is exactly what we just tested). Automated by `backup-restore.sh --full --from one-off-ssd-upgrade-<stamp> --target <new-disk>`; the manual steps below are what it does:
   - `git clone homelab-ai-harness` → restore `.env` (plain tar, `chmod 600`)
   - rsync mirrors back (`ai-kb`, `media`, `documents`, `VM`, misc)
   - MySQL: `mysql < homelab-<stamp>.sql.gz` + `investorhub-<stamp>.sql.gz` (recreate `ai`/`investor` users from `.env`)
   - Postgres: fresh `postgres:16-alpine` containers + `pg_restore`/`psql < dump`
   - ClickHouse: fresh container + restore backup files into the data dir
   - Qdrant: restore snapshots (existing `priority: "snapshot"` restore procedure from `backup-kb.sh` header)
   - `docker compose up -d` (all 9 files)
4. **Verification checklist:**
   - `docker ps` — all 35 containers up/healthy
   - Siri e2e question (exercises litellm → qdrant → memory)
   - `kb_search` + `memory_search` known-fact checks
   - `mcp_mysql` SELECT from both DBs
   - Media pipeline e2e: `media_generate_image` (small) → `media_pull`
   - Portal + blog load; Plausible test event; Grafana dashboards render
5. **Post-swap:** re-run `backup-nas.sh daily` (fresh baseline), confirm timers fire.

---

## 5. Open Items

| # | Item | Owner | Status |
|---|---|---|---|
| 1 | NAS share name + backup user/creds on Lego | Chuck | ✅ **resolved** — share `backup`, user `backup`; creds in `~/.smbcredentials` (mode 600) on each host, never in the repo |
| 2 | Git history cleanup (`git filter-repo` + force-push, drops 3×102 MB logs + zip + node_modules) | Chuck | ✅ **done** (2026-09-27) — `git filter-repo` dropped `logs/skill_runner/` + `ai-harness.zip` + `node_modules/` from all 216 commits; force-pushed (new HEAD `74c5d6c9`). `.git` shrank 198M → 3.2M. Rollback bundle: `/tmp/homelab-pre-filter.bundle`. |
| 3 | Thin `data/backups/` local snapshots after first NAS backup | Me | ✅ **done** — hedge in place (daily/weekly runs copied to `data/backups/nas-hedge/`, keep 2) |
| 4 | VM (Victoria Metrics) in the backup? | Chuck | ✅ **yes — kept** (confirmed 2026-09-27) — the metrics are valuable. Mirror excludes root-owned `cache/`/`tmp/` (VM runs as root); `data/` is the real 3.1G. |
| 5 | Daily vs weekly for Qdrant (daily recommended — memory writes happen most days) | Chuck | ✅ **daily** (default) |
| 6 | **Matrix inventory**: what on Matrix is irreplaceable? (ComfyUI fine-tunes/LoRAs, custom TTS voice refs, outputs, `.env`, other services?) | Chuck | ✅ **resolved** — Matrix is backed up by its **own separate backup script/process** (different data sets + change cadence), not the shared multi-host scripts. Inventory is handled there. |
| 7 | Does Matrix use the shared `homelab-ai-harness` backup scripts (clone + per-host `matrix.json`)? | Chuck | ✅ **resolved** — **no**: Matrix runs its own separate backup process (see item 6). The shared multi-host scripts remain for Thor (and any future host that wants them); `matrix.json` is retained only as a reference placeholder. |
| 8 | Confirm NAS naming: share `backup`, single user `backup` for all machines (§3.5)? | Chuck | ✅ **yes** |
| 9 | Per-host subfolder quota (e.g. 10 GB each)? | Chuck | ❌ **no** (declined; QNAP has ample disk + per-share quotas if ever needed — the script's `min_free_kb` guard is the control) |
| 10 | Is Athena (192.168.5.110) a future backup host? | Chuck | ✅ **clarified** — Athena is a *second NAS downstream in the chain*, not a backup host: **Thor/Matrix → Lego → Athena → USB drives**, plus a fire-safe for critical files. Offsite copy is covered by this chain (out of scope to build today). |
| 11 | Matrix cadence: same daily/weekly, or weekly-only? | Chuck | ✅ **weekly-only** until inventory lands (placeholder) |
| 12 | Offsite copy of the NAS itself (e.g. B2, second drive)? | Chuck | ✅ **out of scope** — the Lego→Athena→USB + fire-safe chain covers it |

### 5.1 Build status (2026-09-26, updated 2026-09-27 for CIFS + QNAP corrections)

All scripts are **built, tested end-to-end, and running live on the real NAS.** They were first validated against a local staging dir (`--root /tmp/nas-test`, no NAS mount required), then **hardened for Lego's real QNAP-SMB/CIFS interface** (measured on Matrix): `RSYNC_FLAGS` = `-rt --modify-window=1 --timeout=60` (no more `-a`), `ensure_mounted` self-heal, a free-space guard, and a post-run sha256 integrity verify. **v4 corrections:** Lego is a QNAP NAS (not macOS), retention is capped at 2 weeks, and the VM mirror (Victoria Metrics) is kept (valuable metrics).

**Live status (2026-09-27):** `backup-setup.sh` has been **run on Thor** — the `backup` share is mounted at `/mnt/lego` (QNAP, `uid=1000,forceuid`, 19T free) and the write test passes. The **first real daily + weekly backups completed with 0 failures and `verify OK`** (`daily-20260927-111418`, `weekly-20260927-111509`; 4.0 GB on the NAS). Restore paths were **verified against the live NAS**: `.env` restored byte-identical, a Qdrant collection recovered 15 points into a disposable container, a MySQL dump loaded 8 tables into a disposable MySQL, and a full restore staged 33 items. **Systemd timers are installed and enabled** (daily 03:00, weekly Sun 04:00, both `Persistent=true`).

| Script | Role | Status |
|---|---|---|
| `scripts/backup-lib.sh` | shared helpers (config, manifest discovery, run/item resolution, unchanged-chain, `ensure_mounted` self-heal, `require_free_space`, CIFS-safe `RSYNC_FLAGS`) | ✅ tested |
| `scripts/backup-setup.sh` | **one-time root setup**: fstab (`vers=2.1,soft,noauto,x-systemd.automount,_netdev`), scoped sudoers, `/mnt/lego/<host>`, capacity check, write test. Resolves the backup user from `SUDO_USER` (not root). | ✅ **run + verified on Thor** (mount live, write test OK) |
| `scripts/backup-install-timers.sh` | installs + enables the systemd timers (copies units to `/etc/systemd/system`) | ✅ **run** (both timers live) |
| `scripts/systemd/backup-nas-{daily,weekly}.{service,timer}` | oneshot services + `Persistent` timers (daily 03:00, weekly Sun 04:00) | ✅ **installed + enabled** |
| `scripts/backup-nas.sh` | host-agnostic backup engine (daily/weekly/one-off, change detection, staging+commit, prune, hedge, flock, **post-run sha256 verify**, **free-space guard**) | ✅ tested (daily + weekly, 0 failures, verify OK) |
| `scripts/backup-restore.sh` | partial (`--item`) + full (`--full [--target]`) recovery, sha256-verified, dry-run default, `--test` disposable containers, `--full --target` staging + RUNBOOK.md, **additive mirror restore** | ✅ tested (all item types + full staging) |
| `scripts/backup-verify.sh` | disposable restore tests for key items | ✅ tested (mysql, qdrant, litellm-postgres PASS) |
| `scripts/backup-hosts/thor.json` | full thor config (daily: qdrant/env/ai-kb; weekly: 16 items incl. VM mirror; `min_free_kb`) | ✅ in repo |
| `scripts/backup-hosts/matrix.json` | reference placeholder only — **Matrix uses its own separate backup process** (item 6/7), not the shared scripts | ✅ in repo (not used) |

**Known limitations (documented):**
- **Caddy** `data/caddy` + `config/caddy` are `root:root 700` — unreadable without sudo; ACME certs are reissuable and the Caddyfile is in the repo, so this is accepted. The `misc` tar uses `--ignore-failed-read` to skip unreadable files.
- **Grafana** `grafana.db` is `472:root 640` — backed up/restored via `docker cp` (container `grafana`), not the host file.
- **Victoria Metrics** runs as root; `cache/`/`tmp/` are excluded from the mirror (root-owned 700, ephemeral). Real data in `data/` is world-readable.
- **Redis/Valkey** `dump.rdb` are uid 999 mode 600 — skipped by the `misc` tar (`--ignore-failed-read`).
- **ClickHouse** restore needs `chown -R 101:101` after `docker cp` (server runs as uid 101).
- **MySQL** users are `@%`-only; dumps connect via `thor.local`, not `localhost`.

**Root-owned cleanup (done):** `data/postgres` (67M) and `data/prometheus` (57M) — both deleted (confirmed 2026-09-27).

---

## Appendix: Inventory Snapshot (2026-09-26)

- Thor: 192.168.4.54/22 · Matrix (GPU): 192.168.4.55 (no SSH key from thor; inventory pending) · **Lego (NAS): 192.168.5.100** · Athena: 192.168.5.110
- Root FS: 221G total, 173G used (82%) — `/home/chuck` = 7.9G; rest is system + Docker
- 35 containers running, 65 anonymous Docker volumes (all regenerable), MySQL 8.0 host service (`/var/lib/mysql`, users `ai@%`, `investor@%`)
- `homelab` git: clean, in sync with GitHub · 277 tracked files
- Qdrant: 15 collections, 23M · MySQL: `homelab` (42 MB dump), `investorhub` (578 MB dump)
- VM: `--retentionPeriod=1y`, ~50 MB/week growth
- Largest data dirs: victoria-metrics 3.0G (mirror — kept, valuable metrics) · open-webui 910M (889M cache REGEN) · media 504M (284M generated SKIPPED) · invest-hub-runner 425M (REGEN) · ai-kb 317M (mirror)