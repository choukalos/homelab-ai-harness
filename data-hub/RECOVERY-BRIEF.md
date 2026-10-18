# Recovery brief — data-hub / report-hub v2 (TODO 1)

Written: 2026-10-18 ~17:45 UTC by the Pi Long Task worker for TODO 1
("Locate where the data-hub/report-hub v2 work left off").
Read this cold: it names what is done, what is broken, why it got stuck, and
the ordered remaining work, with evidence for every claim.

## 1. TL;DR

**v2 is code-complete and unit-tested; it is stuck on exactly one
operational step: the `hub` MySQL database has never been provisioned
because `provision.sh` needs root (`sudo mysql`), and non-interactive agent
sessions cannot authenticate sudo on this host.** Everything else
(adapters, pipeline, API, MCP server, containers, tests) is in place and
verified live.

One-line status: *v2-a + v2-b code done & unit-tested; production E2E
blocked on `hub` db provisioning (root) + data-hub restart.*

## 2. Path note (ambiguity recorded, resolved by observation)

The task text references `/home/chuck/homelab/data-hub/architecture.md` and
`/home/chuck/workspace/code/reporting-hub`. The actual paths are:

- `/home/chuck/homelab/data-hub/ARCHITECTURE.md` (uppercase — no lowercase
  `architecture.md` exists)
- `/home/chuck/workspace/code/report-hub` (no "ing";
  `/home/chuck/workspace/code/` contains `data-hub/`, `report-hub/`,
  `invest-hub/`, `homelab-blog/` only)

No separate `reporting-hub` repo exists. All findings below use the real
paths.

## 3. Intended v2 scope (authoritative sources)

From `/home/chuck/homelab/data-hub/ARCHITECTURE.md` §9 (Scope) and §10
(Build phases), plus `/home/chuck/workspace/code/data-hub/docs/v2-generic-datasets.md`:

- **v2-a — generic-dataset ETL adapter** (data-hub repo): CSV/TSV →
  idempotent import into tables in a new `hub` database (dataset registry
  `hub.datasets`, column inference, `hub.load_log`, watcher + API).
- **v2-b — MCP wrapper** (homelab repo): `mcp_datahub` FastMCP/SSE server
  with 10 tools wrapping the data-hub REST API.
- **Explicitly later / out of v2 scope** (ARCHITECTURE.md §9): n8n alert
  push, finance/reports backups, more chart types. Do not treat these as
  missing v2 work.
- v1 is complete (phases 0–4 done 2026-10-17; phase 5 ingest done — 7 loads,
  9,810 txns; categorization review pass 1 done 2026-10-17, pending queue
  now empty).

## 4. Git state (all three repos)

### homelab repo (`/home/chuck/homelab`, branch `main`, clean tree)
- **4 commits ahead of `origin/main`** (unpushed): `9e5ee43` (phase 0),
  `afafcff` (mcp_mysql finance hints), **`346db9b`** (v2-b: hub db
  provisioning in `provision.sh` + `mcp/servers/datahub/` + compose +
  litellm), `8a4ee57` (unrelated todo web app).
- v2-b commit `346db9b` message states the hand-off point verbatim:
  *"Remaining: run provision.sh (root), restart data-hub, production E2E."*
- `data-hub/RECOVERY-BRIEF.md` (this file) is new and uncommitted (harness
  commits are disabled for this long task; Pi Long Task owns commits).

### data-hub repo (`/home/chuck/workspace/code/data-hub`, branch `main`, clean tree)
- **1 commit ahead of `origin/main`** (unpushed): `b611d86` (docs only —
  v2b status notes in `docs/v2-generic-datasets.md`).
- v2-a commits (both **pushed**):
  - `792224e` v2a: hub schema (`migrations/hub/0001_init.sql`) + hub
    migration wiring (config `HUB_DB`, startup + `/api/migrate`)
  - `fef962c` v2a: generic CSV/TSV dataset adapter
    (`server/adapters/generic_csv.py` 305 lines,
    `server/etl/pipeline.py` +132, `server/ingest.py`, `server/main.py`
    +171, `sources.yaml` inbox→generic_csv, `tests/test_generic_csv.py`
    379 lines / 19 tests)
- No stashes; no other branches.

### report-hub repo (`/home/chuck/workspace/code/report-hub`, branch `main`)
- In sync with `origin/main` (0 ahead / 0 behind), clean tree.
- Last commits are v1 phase 3/4 work (live charts, 5 dashboards,
  category drill-down selector). **No v2 work is assigned to report-hub** —
  v2 only touches the data plane (data-hub) + MCP (homelab). report-hub
  will read `hub.*` later via `dh_reports` SELECT grants (ARCHITECTURE.md
  §6), which `provision.sh` already includes.

## 5. What is DONE (verified live, 2026-10-18 17:2x–17:4x UTC)

| Item | Evidence |
|---|---|
| v2-a code in data-hub repo | commits `792224e`, `fef962c` (§4); `migrations/hub/0001_init.sql` exists |
| v2-a unit tests green | `python3.14 -m tests.test_generic_csv` → **19/19 tests passed** (re-run 2026-10-18 17:3x UTC). `test_upsert_idempotent` prints SKIP (no mysql-connector in system python) but counts as pass; per `fef962c` message it was verified on scratch MySQL 8.4. `.pytest_cache/v/cache/lastfailed` = `{}`. |
| Running data-hub container has v2-a code | `sha256sum` of `/app/server/{main.py,adapters/generic_csv.py,etl/pipeline.py,ingest.py}` in container `data-hub` **identical** to repo HEAD `b611d86`. (Image built 01:48 UTC, before `fef962c` at 01:58 UTC — image was built from the working tree before the commit; no drift.) |
| v2-b code in homelab repo | commit `346db9b`: `mcp/servers/datahub/{server.py,Dockerfile,pyproject.toml,README.md}`, `compose/compose.mcp.yml` service, `litellm/config.yml` registration (`transport: sse`, `url: http://mcp_datahub:8000/sse`, `allow_all_keys`) |
| `mcp_datahub` running & functional | container `mcp_datahub` up (started 13:54 UTC); logs show real MCP tool calls (list_loads, categories, pending, datasets→503, ingest_file scratch); SSE endpoint answers `event: endpoint` (HTTP 200); registered in litellm |
| data-hub v1 runtime healthy | `GET :8100/api/health` → `status: ok`, 9,810 txns, 8 loads, last load ok |
| report-hub v1 runtime healthy | `GET :8101/api/health` → ok; `/api/dashboards` returns live dashboards (overview, categories, …); no errors in 48 h of logs |
| `provision.sh` includes `hub` db + grants | `/home/chuck/homelab/data-hub/provision.sh` (commit `346db9b`): `CREATE DATABASE IF NOT EXISTS hub`, `GRANT ALL ON hub.* TO dh_app`, `GRANT SELECT ON hub.* TO dh_reports` and `TO 'ai'@'%'` |
| v2-a graceful degradation works as designed | `/api/datasets` → HTTP 503 `hub db unavailable: 1044 (42000): Access denied for user 'dh_app'@'%' to database 'hub'`; watcher leaves unresolvable files `pending` (data-hub logs: `hub db unavailable, cannot resolve dataset for zz-mcp-test-scratch.csv`) |

## 6. What is INCOMPLETE / BROKEN (the stuck point)

1. **`hub` database does not exist / `dh_app` has no access to it.**
   - Probed from inside the `data-hub` container as `dh_app`: visible
     databases = `['finance', 'information_schema', 'performance_schema']`
     — no `hub`.
   - `/api/health` → `"hub_migrations_applied_on_start": []`.
   - data-hub startup log: `hub db unreachable, skipping hub migrations:
     1044 (42000): Access denied for user 'dh_app'@'%' to database 'hub'`.
   - Cause: `provision.sh` has **never been run** — it requires
     `sudo mysql`, and on this host `sudo` demands interactive
     authentication (`sudo -n` → "A terminal is required to authenticate").
     This is exactly the step the prior worker flagged in commit `346db9b`
     and stopped at.
2. **Production E2E for v2-a never ran** (design doc
   `docs/v2-generic-datasets.md` §"Tests / verification" E2E bullet:
   register scratch dataset → drop CSV in inbox → watcher ingest →
   idempotent re-drop → changed-file update → verify `hub.load_log`,
   `/api/loads?db=hub`, preview → cleanup).
3. **Production E2E for v2-b ingest path**: `ingest_file` was only verified
   with a scratch file (`zz-mcp-test-scratch.csv`, 12 bytes) while `hub`
   was unprovisioned → returned `status=pending` (by design). The scratch
   file is since removed from `/home/chuck/data/finance/inbox/` (dir is
   empty; `/api/health` `pending_files: []`). A real ingest into `hub` has
   not happened.
4. **Unpushed commits** (GitHub mirror drift): data-hub `b611d86`
   (1 ahead of origin/main); homelab `9e5ee43`, `afafcff`, `346db9b`,
   `8a4ee57` (4 ahead).
5. **Docs status lines** in `ARCHITECTURE.md` header / §10 and
   `docs/v2-generic-datasets.md` still say "production E2E pending" —
   correct as of this writing, but must be flipped after the E2E below.

## 7. Why it got stuck

The prior session (2026-10-18, commits `792224e`→`b611d86` in data-hub and
`346db9b` in homelab) completed all code + unit tests + MCP handshake
verification, then hit the one step that needs **root on the host**:
`bash /home/chuck/homelab/data-hub/provision.sh` (pipes SQL to `sudo
mysql`). Agent sessions here cannot authenticate sudo non-interactively, so
the work was parked with the blocker documented in the commit message and
in `docs/v2-generic-datasets.md` ("production E2E pending `hub` db
provisioning — `provision.sh` needs root"). No code bug; no failing test;
purely an ops/permissions gate.

## 8. Ambiguities / drift recorded (do not silently resolve)

1. **Path mismatches in the task text** — see §2 (`architecture.md` vs
   `ARCHITECTURE.md`; `reporting-hub` vs `report-hub`).
2. **`ai` user assumption**: `provision.sh` grants
   `GRANT SELECT ON hub.* TO 'ai'@'%'` but does **not** create the `ai`
   user (ARCHITECTURE.md §6 calls it "existing"). If `ai`@'%' does not
   exist in MySQL, that GRANT line will error and abort the script
   (`set -euo pipefail`). Verify `ai` exists before running (e.g.
   `sudo mysql -e "SELECT user,host FROM mysql.user WHERE user='ai'"`);
   if missing, create it first or split the grant. Not verifiable from
   this session (needs root).
3. **Image/commit timestamp inversion** (data-hub image built 01:48 UTC vs
   `fef962c` at 01:58 UTC): benign — container code is byte-identical to
   repo HEAD (sha256-verified), i.e. the image was built from the working
   tree before the commit was made.
4. **v1 phase 5 "review walk-through pending with chuck"** (ARCHITECTURE.md
   §10): the categorization review log
   (`/home/chuck/workspace/code/data-hub/docs/categorization-review-log.md`)
   records pass 1 done 2026-10-17, and `/api/categories/pending` now
   returns `{"pending":[],"count":0}`. Treated as closed for v2 purposes;
   if chuck still wants a walk-through, it is a v1 follow-up, not a v2
   blocker.
5. **`hub` grants for report-hub**: `dh_reports` SELECT on `hub.*` is in
   `provision.sh`, but no report-hub dashboard over `hub` data exists yet —
   that is post-v2 ("report-hub can build dashboards over generic data",
   design doc §Database). Not a v2 gap.

## 9. Ordered remaining work (TODO 2 checklist)

Each item maps to a concrete diff/doc/test above.

1. **Provision the `hub` db (root required — the stuck point).**
   - Pre-check ambiguity #2: confirm `ai`@'%' exists.
   - Run: `bash /home/chuck/homelab/data-hub/provision.sh`
     (idempotent; renders SQL from `homelab/.env` `DH_APP_PASS` /
     `DH_REPORTS_PASS`, pipes to `sudo mysql`).
   - Needs an interactive root session (chuck, or a shell with a TTY).
2. **Restart data-hub** so it applies `migrations/hub/0001_init.sql` at
   startup: `docker restart data-hub` (or compose restart from
   `homelab/compose/compose.data-hub.yml`).
3. **Verify provisioning**:
   - `curl -s http://192.168.4.54:8100/api/health` →
     `hub_migrations_applied_on_start` non-empty (hub 0001).
   - `curl -s http://192.168.4.54:8100/api/datasets` → HTTP 200 `[]`
     (no more 503).
   - `hub.datasets` + `hub.load_log` tables exist.
4. **v2-a production E2E** (per `docs/v2-generic-datasets.md`
   §"Tests / verification" E2E): register a scratch dataset
   (`POST /api/datasets`), drop a CSV into `/home/chuck/data/finance/inbox/`
   (watcher polls every 10 s per `sources.yaml`), confirm ingest; re-drop
   the same file → 0 new / N updated; drop a changed file → updated;
   verify `hub.load_log` + `GET /api/loads?db=hub` +
   `GET /api/datasets/{name}/preview`; then clean up the scratch dataset
   (`DELETE /api/datasets/{name}`) and table.
5. **v2-b production E2E**: via `mcp_datahub` (litellm-registered,
   SSE `http://mcp_datahub:8000/sse`): `ingest_file` a small CSV,
   `list_loads(db="hub")`, `list_datasets()`, `dataset_preview(name)` —
   confirm a real `hub` load lands (not `status=pending`).
6. **Push the unpushed commits** (when pushing is allowed): data-hub
   `b611d86`; homelab `9e5ee43`, `afafcff`, `346db9b`, `8a4ee57` (+ this
   brief once committed by Pi Long Task).
7. **Update docs to finished state**: flip the v2 status lines in
   `/home/chuck/homelab/data-hub/ARCHITECTURE.md` (header + §10 rows
   v2-a/v2-b) and `/home/chuck/workspace/code/data-hub/docs/v2-generic-datasets.md`
   from "production E2E pending" to verified-with-dates; commit.

## 10. Commands cheat-sheet for the next worker

```bash
# stuck-point probe (expect no 'hub' in the list before step 1):
docker exec data-hub python -c "
import os, mysql.connector
c = mysql.connector.connect(host=os.environ.get('MYSQL_HOST','thor.local'),
                            user='dh_app', password=os.environ['MYSQL_PASSWORD'])
cur = c.cursor(); cur.execute('SHOW DATABASES')
print('DBs visible to dh_app:', [r[0] for r in cur.fetchall()])"

# provision (root):
bash /home/chuck/homelab/data-hub/provision.sh

# restart + health:
docker restart data-hub
curl -s http://192.168.4.54:8100/api/health
curl -s http://192.168.4.54:8100/api/datasets

# unit tests (repo root):
cd /home/chuck/workspace/code/data-hub && python3.14 -m tests.test_generic_csv
```