# Data Structure Audit — Fix Plan

**Date:** 2026-09-21 (updated 2026-09-22)
**Scope:** Audit of `/home/chuck/{homelab,data,workspace}` against the intended structure:

| Directory | Intent |
|---|---|
| `homelab/` | All code, config, scripts — versioned, checked into GitHub |
| `data/` | All data for containers, output media, output files — backed up |
| `workspace/` | Temporary working data for LLMs/tools — NOT backed up |

**Verdict:** The core layout is mostly right (container data in `data/`, code in `homelab/`, staging in `workspace/media`), but there are **10 concrete violations** and **3 security issues** worth fixing.

**Status (2026-09-23):** Core audit COMPLETE. Follow-up round: cleanups done, all 6 output-writing containers run as chuck and verified (F3 done). F1 resolved 2026-09-23 (CF token rotation confirmed; live token now passed via env at run time, not stored in `.env`). **All items complete.**

---

## Priority 1 — Security (do first)

### 1.1 Cloudflare API token hardcoded in `~/rotate-cf-tunnel.sh` `[x]`
- **Problem:** Script at home root contains a live CF API token + account ID in plaintext, mode 755 (world-readable). Not in any of the three directories.
- **Done:**
  1. Moved to `homelab/scripts/rotate-cf-tunnel.sh` (700), reads `CF_API_TOKEN`/`CF_ACCOUNT_ID`/`CF_TUNNEL_ID` from `homelab/.env` (verified values match the old script).
  2. Old `~/rotate-cf-tunnel.sh` deleted.
  3. **Still to do:** rotate the CF token in the Cloudflare dashboard — it sat world-readable in home for weeks.

### 1.2 GitHub PAT embedded in invest-hub remote URL `[x]`
- **Problem:** `workspace/code/invest-hub` had `https://x-access-token:github_pat_...@github.com/...` as its origin URL.
- **Done:**
  1. Insurance first: `data/backups/invest-hub-local-2026-09-21.bundle` (full history, verified) + `-uncommitted.patch` + `-POOL-TIMEOUT-FIX.md` + `-status.txt`.
  2. `workspace/code/` and the stale wrapper `workspace/.git` removed — the PAT is gone from disk (note: the token also appears in one old pi session log under `~/.pi/agent/sessions/`; harmless local history, but the PAT is dead anyway — GitHub rejected it: "Invalid username or token").

### 1.3 `~/lab-keys/dylan.txt` is world-readable (664) and outside the structure `[x]`
- **Problem:** Credential/key file for user `dylan` sitting at home root, mode 664, not in `homelab`/`data`/`workspace`.
- **Done:** `chmod 600` (chuck-only). Kept at `~/lab-keys/` per user decision (not in the three zones — documented exception).

---

## Priority 2 — Code in the wrong zone (high risk: uncommitted work in non-backed-up area)

### 2.1 `workspace/code/invest-hub` is a live repo with UNCOMMITTED changes `[x]`
- **Problem:** The invest-hub checkout (a versioned code repo) lived in `workspace/` (temp, not backed up) with uncommitted work (3 modified files + 1 untracked doc).
- **Done:** Per user: the repo was superseded by code from another machine already in git, so the local checkout is stale and not worth migrating. Insurance saved to `data/backups/` (bundle + patch + doc), then `workspace/code/` removed.
- **Follow-up (RESOLVED 2026-09-22 — investigated, no action needed):** the `build.context` lines are **not a real build path — they are a sed anchor for CI.** `.github/workflows/deploy.yml` in the invest-hub repo (runs on the self-hosted `github-runner`) copies this compose file, rewrites the two `context:` lines to the fresh GitHub checkout via `sed`, builds from that copy, then `up -d --no-build` from the original. Verified: remote `main` (3826195d) is 24 commits **ahead** of the deleted checkout (0 unique local commits), the last CI deploy (2026-09-04) succeeded, the runner is online, and the sed anchors still match exactly. The uncommitted pool-timeout work was independently re-implemented (better) on the remote — see `data/backups/invest-hub-local-2026-09-21-uncommitted.patch` for the original. Contract now documented in the compose file comments (committed `26698902`). **Hardening DONE 2026-09-22:** the invest-hub repo's `deploy.yml` now pre-checks both sed anchors and post-verifies the rewrite, failing the deploy loudly on drift (invest-hub commit `2089264b`, pushed via API; the push-triggered deploy run succeeded and validated the guards end-to-end). **Runner log prune DONE 2026-09-22:** `data/invest-hub-runner/_diag` held 49,105 files / 856 MB — a restart-storm from 2026-08-29→09-04 (runner registration had been deleted server-side; the supervisor re-spawned every ~70s, each spawn logging the same failure). Pruned everything before 2026-09-05 via `docker exec github-runner` (no host sudo needed; container runs as root): 856 MB → 3.2 MB, kept the 4 post-incident logs (Sep 6/12/20). The live runner logs to container-internal `/actions-runner/_diag`, so the mounted volume is historical only.

### 2.2 `workspace/` itself is a git wrapper repo (choukalos/invest-hub) `[x]`
- **Problem:** `workspace/` had its own `.git` (remote `choukalos/invest-hub`) tracking a committed `.DS_Store`, 3 HTML test files, and the invest-hub repo as a submodule — a stale wrapper around the real repo.
- **Done:** `workspace/.git` removed (all its tracked content was junk/stale; the real repo is on GitHub). `workspace/` is now a plain scratch dir. `.DS_Store` left on disk (harmless).
- **Remaining `[sudo]`:** DONE 2026-09-22 (user) — `workspace/documents/` moved to `data/documents/` (2 real outputs kept, 2 smoke-test HTMLs dropped); `workspace/build_qwen38_experiment.py` deleted.

### 2.3 `workspace/documents/` and `workspace/build_qwen38_experiment.py` are root-owned `[x]`
- **Problem:** Output files and a script created by a container running as root; ownership is `root:root` (chuck can't safely edit/delete).
- **Done (sudo batch, 2026-09-22):** both handled — see 2.2. Long-term: containers should write outputs as the `chuck` uid or to a dedicated drop dir.

---

## Priority 3 — Data/ephemera in the code repo (`homelab/`)

### 3.1 `homelab/logs/skill_runner/` — 99 MB of runtime logs in the code tree `[x]`
- **Problem:** Root-owned logs inside the versioned repo dir. Gitignored (good) but violates the structure: runtime data belongs in `data/`.
- **Done:** `compose/compose.skill-runner.yml` now points `SKILL_RUNNER_LOG_DIR` + the volume mount at `/home/chuck/data/logs/skill_runner/` (dir created). Sudo batch executed 2026-09-22: old logs moved to `data/logs/skill_runner/skill_runner.log.1` (102 MB), `homelab/logs/` removed. skill-runner (recreated) is writing to the new path.

### 3.2 `homelab/tmp/` — scratch scripts and logs (working files) `[x]`
- **Problem:** ~20 scratch files (`kb_e2e.py`, `vision_part1-3.py`, `architecture-summary-for-frontier.md`, …) — LLM working files, not versioned code. Gitignored, so no leak risk, but wrong zone.
- **Done:** moved to `/home/chuck/workspace/homelab-scratch`.

### 3.3 Empty leftover dirs: `homelab/data/`, `homelab/runner-data/` `[x]`
- **Problem:** Empty data dirs inside the repo; not referenced by any compose file or script. (`data/` contained only an empty root-owned dir oddly named `jobs.db`.)
- **Done:** both removed.

### 3.4 Backup files tracked in git `[x]`
- **Problem:** `siri-script.sh.bak` and 4 grafana dashboards (`.bak`, `.bak2`, `.bak3`) are **committed** to the repo.
- **Done:** `git rm --cached` all five; `*.bak` added to `.gitignore`; committed. (Files kept on disk; history retains them.)

### 3.5 Untracked litellm config variants `[x]`
- **Problem:** `litellm/config.yml.llmonly` and `litellm/config.yml.mcp_broken` were untracked.
- **Done:** moved to tracked `litellm/draft/` and committed (reference variants).

### 3.6 `homelab/.pytest_cache/` `[x]`
- **Problem:** Test cache in the repo (untracked, harmless).
- **Done:** removed (regenerates on next pytest run).

---

## Priority 4 — Ephemera in the backed-up zone (`data/`)

### 4.1 `data/workspace/vision/` — 387 MB of ephemeral vision artifacts `[x]`
- **Problem:** 83 root-owned artifact dirs (frames + reports) from the vision MCP. The vision tool itself documents these as **ephemeral, non-public** and self-cleans via `vision_cleanup`. They lived in `data/` (backed up) and were included in `backup-kb.sh`'s source tarball — so ephemeral scratch was being backed up.
- **Done:**
  1. `mv /home/chuck/data/workspace/vision /home/chuck/workspace/vision` (the `vision` tree itself was chuck-owned; leaf dirs remain root-owned, which is fine — the vision container writes as root). `data/workspace/` removed.
  2. `compose/compose.mcp.yml`: `VISION_OUTPUT_ROOT=/workspace/vision`, rw mount `/home/chuck/workspace/vision:/workspace/vision` nested in ro `/home/chuck/workspace:/workspace:ro`; mcp_knowledge now mounts `/home/chuck/workspace:/workspace:ro` with `KB_ALLOWED_ROOTS=/data/media,/workspace,/data/ai-kb/raw`.
  3. `scripts/cleanup-vision.sh` `ROOT=` updated.
  4. `scripts/backup-kb.sh` mapping updated (`/workspace` → `/home/chuck/workspace`) — KB sources ingested from workspace are still backed up, scratch that's never ingested is not.
  5. Code defaults updated: `mcp/servers/vision/server.py`, `mcp/servers/knowledge/server.py`; docs updated (vision README, knowledge README, thor_mcp_architecture.md, main README).
  6. **Done:** `mcp_vision` + `mcp_knowledge` rebuilt and force-recreated; end-to-end test frame extraction verified writing to `/workspace/vision/<slug>/` (host: `workspace/vision/`); test artifacts cleaned via in-container `vision_cleanup`.

---

## Priority 5 — Home-root strays (outside all three dirs)

### 5.1 `~/metrics/` — 3 planning docs, one a full duplicate `[x]`
- **Problem:** `metrics/strategy.md` is byte-identical to `homelab/APP-METRICS-STRATEGY.md`; `invest-hub-metrics-plan.md` and `platform-metrics-plan.md` are unique planning docs.
- **Done:** the two unique docs moved to `homelab/docs/metrics/`; duplicate deleted; `~/metrics/` removed.

### 5.2 `~/invest-plausible-script.txt` — snippet scratch `[x]`
- **Done:** moved to `homelab/docs/`.

### 5.3 `~/logs/` — empty dir `[x]`
- **Done:** removed.

### 5.4 `~/lab-keys/`
- Handled in 1.3 (kept, chmod 600).

---

## Verification checklist (after fixes)

- [x] `cd /home/chuck/homelab && git status` → only intentional changes (committed)
- [x] `find /home/chuck/homelab -maxdepth 1 -type d \( -name data -o -name tmp -o -name runner-data \)` → empty (logs/ pending sudo move)
- [x] `du -sh /home/chuck/data/workspace 2>/dev/null` → gone
- [x] `docker compose -f compose/compose.invest-hub.yml build` → **not a valid local operation** (contexts are CI sed anchors; CI builds from the GitHub checkout). `homelab.sh invest up/restart` is safe (no build step).
- [x] skill-runner writes logs to `/home/chuck/data/logs/skill_runner/` (verified after sudo move + container recreate)
- [x] vision test extraction writes to `/home/chuck/workspace/vision/<slug>/` (verified after container rebuild)
- [x] No plaintext CF token in `~/rotate-cf-tunnel.sh` (script moved + token in `.env`); invest-hub PAT gone from disk
- [x] `ls -la /home/chuck/` → only `data`, `homelab`, `lab-keys`, `workspace` + dotfiles
- [x] Rotate the CF API token in the Cloudflare dashboard (1.1) — confirmed 2026-09-22 (old token rejected by CF verify API); live token kept out of `.env` per F1 design decision (2026-09-23)

## Follow-up round (2026-09-22 afternoon)

### F1. CF API token — rotation confirmed; token now passed via env, NOT stored in `.env` `[x]`
- **Verified 2026-09-22:** the token that was in `homelab/.env` was byte-identical to the OLD token that had sat world-readable in `~/rotate-cf-tunnel.sh` (matched against the 2026-09-21 session log), and CF's `GET /user/tokens/verify` rejected it (code 1000 "Invalid API Token"). The dashboard rotation WAS done (the exposed token is dead — good).
- **Design decision (2026-09-23):** rather than paste the live token into `.env` (a second copy on disk), the token is now supplied **only at run time via the environment** — the live value never touches disk. The user keeps it in their secure notes.
- **Done:**
  1. `scripts/rotate-cf-tunnel.sh` rewritten: `CF_ACCOUNT_ID`/`CF_TUNNEL_ID` still load from `.env`; `CF_API_TOKEN` is read from the environment first (a `CF_API_TOKEN=` line in `.env` remains a legacy fallback but is not recommended). Missing token → clear error + usage hint, exit 1.
  2. Dead `CF_API_TOKEN=` line removed from `homelab/.env` (mode 600 unchanged; `CF_TUNNEL_TOKEN`/`CF_ACCOUNT_ID`/`CF_TUNNEL_ID` intact).
  3. Verified: no token → clean error exit 1; dummy token → reaches CF and gets HTTP 400 (invalid token), proving the request path works.
- **Usage (user):** `CF_API_TOKEN='<token-from-secure-notes>' ./scripts/rotate-cf-tunnel.sh` → copy the `result` field (new tunnel token) into `compose/compose.edge.yml` `TUNNEL_TOKEN` (or the cloudflared container env) and `docker compose up -d` the edge stack. Verify the token itself with: `curl -s -H "Authorization: Bearer $CF_API_TOKEN" https://api.cloudflare.com/client/v4/user/tokens/verify` → `"success": true`.

### F2. Optional cleanups `[x]`
- `workspace/tm_test/` removed; `workspace/.DS_Store` removed.
- Vision artifacts: in-container `vision_cleanup` (7-day retention) deleted 72 dirs / 395 MB. 10 dirs from 2026-09-16 remain (just under the cutoff, 5.2 MB) — auto-clean in ~1 day.

### F3. Containers run as chuck (uid/gid 1000) `[x]`
- **Why:** skill-runner + 5 MCP servers wrote root-owned files into chuck-owned zones (data/logs, data/media, data/scheduler, data/backups/kb, data/ai-kb/digests, workspace/).
- **Done (compose, committed):** `user: "1000:1000"` added to `skill-runner`, `mcp_knowledge`, `mcp_media`, `mcp_filesystem`, `mcp_mysql`, `mcp_vision`. No Dockerfile has a `USER` directive, so the compose override is clean.
- **Done (user, 2026-09-22):** chown batch executed — all 7 targets (incl. nested) now chuck-owned, verified with `find -not -user chuck` = 0.
- **Done (recreate + verify, 2026-09-22 15:31 UTC):** all 6 containers force-recreated. Verified: `docker inspect User=1000:1000` on all; functional write tests land `1000:1000` (vision→workspace/vision, knowledge→ai-kb/digests, media→workspace/media, mysql→data/media/csv, filesystem→workspace/, skill-runner→data/scheduler); skill-runner log appends chuck-owned; all 5 MCP servers HTTP 200 on SSE; skill-runner `/health` 200.
- **Fix needed during recreate:** mem0's `setup.py` does `os.makedirs(~/.mem0)` at import time; with no HOME, `~` = `/` → `PermissionError` as chuck (as root it had silently written `/.mem0` into the ephemeral image layer). Fixed with `MEM0_DIR=/tmp/.mem0` in the skill-runner env; then made it **durable**: `/tmp/.mem0` is now a bind mount to `data/mem0` (chuck-owned, backed up) so a drive update/recreate doesn't lose mem0's local state (config.json + history.db). The actual memories live in Qdrant (`data/qdrant`) — already persistent. Verified: mount present, mem0 init clean, history.db preserved across the recreate.
- **Not changed (intentional):** `github-runner` + the pure-data containers (qdrant, mysql, grafana, …) — their writes stay in `data/` container dirs where root/UID ownership is normal. `mcp_homelab_status` reads docker.sock:ro — works as chuck via the docker group.

## SUDO batch — EXECUTED 2026-09-22 ~02:17 UTC (user)

```bash
# 1. skill-runner logs: homelab (code zone) -> data (backed-up zone)
sudo mv /home/chuck/homelab/logs/skill_runner/* /home/chuck/data/logs/skill_runner/
sudo rmdir /home/chuck/homelab/logs/skill_runner /home/chuck/homelab/logs
sudo chown -R chuck:chuck /home/chuck/data/logs/skill_runner

# 2. root-owned workspace leftovers: keep the 2 real outputs, drop smoke-test junk
sudo mv /home/chuck/workspace/documents/kaelen-thornwood-gurps-150.md /home/chuck/data/documents/
sudo mv /home/chuck/workspace/documents/presentation-outline-the-foundation-of-agility.html /home/chuck/data/documents/
sudo rm -f /home/chuck/workspace/documents/smoke-test-ow.html /home/chuck/workspace/documents/url-test.html
sudo rmdir /home/chuck/workspace/documents
sudo chown -R chuck:chuck /home/chuck/data/documents

# 3. root-owned scratch script in workspace (delete; or chown chuck:chuck to keep)
sudo rm /home/chuck/workspace/build_qwen38_experiment.py
```

Then recreate the affected containers — **DONE** (mcp_vision/mcp_knowledge rebuilt + force-recreated; skill-runner force-recreated; all healthy).

**Optional cosmetic (not required):** the moved files are still root-owned in `data/` (world-readable, backups work): `sudo chown -R chuck:chuck /home/chuck/data/logs/skill_runner /home/chuck/data/documents`.

```bash
cd /home/chuck/homelab
docker compose -f compose/compose.mcp.yml build mcp_vision mcp_knowledge
docker compose -f compose/compose.mcp.yml up -d mcp_vision mcp_knowledge
docker compose -f compose/compose.skill-runner.yml up -d --force-recreate skill-runner
```

## Explicitly OK (no action)

- `data/` container dirs (victoria-metrics, open-webui, invest-hub-runner, postgres, qdrant, grafana, prometheus, redis, searxng, …) — correct zone. Root/UID ownership is normal for container data.
- `data/mysql-mcp-csv/`, `data/media/*` — output files, correct zone.
- `data/backups/` — backup output, correct zone.
- `workspace/media/` — mcp_media staging dir (wired in `compose.mcp.yml` + `cleanup-media-staging.sh`), correct zone.
- `workspace/tm_test/` — scratch test artifacts in the right zone (optional cleanup, 4 days old).
- `homelab/.env` — gitignored, not tracked. Good.