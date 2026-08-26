# Homelab User Authentication & Per-User Usage Tracking — Implementation Plan

> **Created:** 2026-08-25 (live-verified against Thor 192.168.4.54)
> **Companion doc:** `memory_todo.md` (long-term memory plan — shares the key→user
> identity layer; see §2.2 and §9).
> **Method:** one phase at a time; each phase ends with tests + updated state.
> **Operational constraint (inherited from `memory_todo.md` §3.0):** the
> implementing model **never runs container lifecycle commands**. All
> restarts/rebuilds are manual steps run by Chuck between model turns.

---

## 0. Requirements (from Chuck, 2026-08-25)

1. **Remove Open WebUI** — no longer used (supersedes the OWUI work in `TODO.md`).
2. **One key per person** (Chuck + son) that works with **both** Siri/skills
   (`siri.choukalos.com` → skill-runner) **and** LiteLLM (`llm.choukalos.com`) —
   ideally the **same key** for both.
3. **Track usage in Grafana per user**: total tokens input, cached, generated,
   etc.

### Decisions (answered by Chuck, 2026-08-25)

| # | Question | Decision |
|---|---|---|
| Q1 | Provenance of `simba`/`dylan` keys (2026-06-21)? | **Unknown — blow them away.** Delete both in Phase 1 (step 6). |
| Q2 | Per-user budgets / rate limits? | **Yes — implement as Phase 8.** Keep the existing nominal pricing in `litellm/config.yml` (verified live, see §1.3) — it powers budget tracking and **ROI on the AI workstation investment** (nominal $ = GPU-time proxy). |
| Q3 | What URL + key does the **live Siri shortcut** actually use? (`README_SIRI.md` says `POST /siri/chat`, but skill-runner only has `/api/chat` — Caddy strips `/siri` → `/chat`, which 404s. Verify on device.) | **Still open** — verify in Phase 5; if it's `/siri/chat`, either fix the shortcut to `/api/chat` or add a `/chat` alias route in skill-runner. |
| Q4 | Son's own device? | **Yes — his own laptop, and he uses `opencode`.** His key hits the homelab via `llm.choukalos.com` (OpenAI-compatible `/v1`), his stated preference. Phase 5 step 2. |

---

## 1. Comprehension check — verified current state (2026-08-25)

> Facts below were verified live (API calls, DB queries, file reads). No secret
> values are recorded — only hashes (sha256, first 16 hex chars) and names.

### 1.1 Key inventory (live)

| .env var | sha256 (16) | Role today | Notes |
|---|---|---|---|
| `LITELLM_MASTER_KEY` | `69aecee1800ef43d` | LiteLLM master key | `general_settings.master_key` in `litellm/config.yml` |
| `LITELLM_API_KEY` | — (line is `LITELLM_API_KEY=${LITELLM_MASTER_KEY}`) | skill-runner → LiteLLM outbound | compose interpolates → **skill-runner calls LiteLLM with the master key** |
| `HARNESS_API_KEY` | `69aecee1800ef43d` | OWUI → skill-runner | **== master key value**; only consumer is OWUI (grep-verified) |
| `SIRI_API_KEY` | `4a264e668b63ebed` | Siri → Caddy → skill-runner inbound | 64-char hex; enforced **twice**: Caddy edge gate + skill-runner list |
| `LITELLM_PUBLIC_API_KEY` | `4fd66240c8ca4627` | public key for `llm.choukalos.com` docs | not in the virtual-key DB (legacy) |

**LiteLLM virtual keys** (`LiteLLM_VerificationToken`, 6 rows):

| key_name (masked in DB) | key_alias | user_id | budget | created | status |
|---|---|---|---|---|---|
| `sk-...WlwQ` | `simba` | `simba` | 200 | 2026-06-21 | active (Q1) |
| `sk-...WeqQ` | `dylan` | `dylan` | — | 2026-06-21 | active (Q1) |
| `sk-...y3ew` | — | — | — | 2026-07-03 | **expired** 2026-07-04 |
| `sk-...OoHA` | — | `default_user_id` | 0.25 | 2026-07-15 | **expired** 2026-07-16 |
| `sk-...ggJw` | `chuck-remote` | `chuck` | — | 2026-07-17 | **active — in use** (see 1.3) |
| `sk-...jF1g` | — | `default_user_id` | 0.25 | 2026-08-15 | **expired** 2026-08-16 |

**There is no `son` key and no `service` key.**

### 1.2 Auth flows today

```
Siri/device ──X-API-Key: SIRI_API_KEY──▶ Caddy (single-key gate)
             ──▶ skill-runner (list-validates same key)
             ──▶ LiteLLM with MASTER key          ⇒ metrics user="default_user_id"

Mac (pi) ──Bearer: chuck-remote key──▶ llm.choukalos.com ──▶ Caddy (no key check)
             ──▶ LiteLLM                        ⇒ metrics user="chuck"  ✓ already works

OWUI ──Bearer: MASTER key──▶ LiteLLM (direct, bypasses skill-runner)
OWUI ──X-API-Key: HARNESS_API_KEY (== master)──▶ skill-runner
Scheduler (dispatch_job, requester="siri") ──▶ skill-runner → LiteLLM (master key)
```

### 1.3 Monitoring (live-verified)

- **VictoriaMetrics** (promscrape mode, `prometheus/prometheus.yml`) **already
  scrapes `litellm-proxy:4000/metrics/` every 15s** (job `litellm`, via
  `host.docker.internal`).
- **Grafana** on `:3001`, datasource `Prometheus` → `http://victoria-metrics:8428`
  (provisioned), dashboards folder auto-provisioned with **30s polling**
  (`grafana/provisioning/dashboards/dashboards.yml`) → **dropping a new JSON file
  in `grafana/dashboards/` is picked up without any restart**.
- Existing dashboard `llm-gpu-monitor.json` already has per-key panels
  ("Tokens by User (In/Out)", "Spend by User", "Key Detail Table" — grouped by
  `api_key_alias` via `label_replace`).
- **Spend logs are intentionally disabled** in `litellm/config.yml`
  (`disable_spend_logs: true`, `disable_spend_updates: true`, comment:
  "unnecessary for self-hosted homelab"). The `LiteLLM_SpendLogs` table stopped
  at 2026-07-04. **Prometheus metrics are the source of truth — do NOT
  re-enable spend logs for this project.**
- LiteLLM version: **1.92.0**.

**Per-user metrics available** (all carry `user`, `api_key_alias`, `model`,
`requested_model`, `route`, `status_code` labels — verified live):

| Metric | Meaning |
|---|---|
| `litellm_input_tokens_metric_total` | input tokens |
| `litellm_input_cached_tokens_metric_total` | **provider-side cached input tokens** |
| `litellm_input_cache_creation_tokens_metric_total` | tokens written to prompt cache |
| `litellm_output_tokens_metric_total` | output tokens |
| `litellm_output_reasoning_tokens_metric_total` | reasoning tokens |
| `litellm_total_tokens_metric_total` | input + output |
| `litellm_spend_metric_total` | spend (**nominal** USD — see §1.3 pricing) |
| `litellm_proxy_total_requests_metric_total` / `litellm_proxy_failed_requests_metric_total` | requests / errors |
| `litellm_remaining_api_key_budget_metric` / `litellm_api_key_max_budget_metric` | key budget |
| `litellm_remaining_user_budget_metric` / `litellm_user_max_budget_metric` | user budget |

**Evidence the `user` label works:** `litellm_input_tokens_metric_total{user="chuck",
api_key_alias="chuck-remote", model="qwen38-27b"} = 2.34M` (Chuck's Mac pi
session, via Caddy 172.18.0.2). Everything else shows `user="default_user_id"`
(master key).

**Nominal pricing is live (verified 2026-08-25):** `litellm/config.yml` sets
per-model `model_info` costs ("Custom pricing for budget tracking") so
budgets work on self-hosted models — `matrix-coder` $0.00000075 in /
$0.0000045 out per token; `matrix-gemma4-moe` $0.00000025 / $0.000002;
`studio-gemma4-4b` $0.000001 / $0.000001; `embeddings` $0.0000001 (convention:
**$1 ≈ 1M tokens**; "the real cost is just your GPU time"). Confirmed loaded:
`litellm_spend_metric_total` is non-zero (chuck ≈ $2.31, default_user_id
≈ $20.30). **Keep this pricing** (non-negotiable #9) — it powers Phase 8
budgets + ROI tracking.

### 1.4 OWUI footprint (for removal)

- Service: `compose/compose.ai-core.yml` lines 60–83 (image
  `ghcr.io/open-webui/open-webui:latest`, port `3000:8080`, data
  `/home/chuck/data/open-webui`).
- Env consumers (grep-verified, **only** OWUI): `WEBUI_SECRET_KEY`,
  `HARNESS_API_KEY`.
- **No Caddy route** (LAN-only `:3000`) — removing it breaks no public site.
- OWUI talks to LiteLLM with the **master key** → its usage pollutes
  `default_user_id`; removal also cleans up attribution.

### 1.5 Caddy edge (verified)

- Caddy runs in the **separate `homelab` compose project** (Caddy + cloudflared,
  `compose/compose.core.yml` + `compose/compose.edge.yml`); `homelab.sh` does
  **not** manage it.
- `caddy/Caddyfile` is bind-mounted **read-only**; **Caddy hot-reloads the
  Caddyfile on change** (in-process graceful reload, no container restart, no
  dropped connections) → Caddyfile edits need **no manual step**, only log
  verification.
- `siri.choukalos.com` enforces `@noAuth not header X-API-Key {$SIRI_API_KEY}`
  (single key) on `/siri/*` and `/api/*` → **blocks per-user keys at the edge**.
- `llm.choukalos.com` has **no edge key check** (LiteLLM enforces its own keys).

### 1.6 skill-runner code facts (verified)

- `skills/runner/main.py:127-128` — `LITELLM_API_KEY` (outbound),
  `SKILL_RUNNER_API_KEY` (inbound).
- `main.py:1835-1855` — `api_chat` validates `x_api_key` against the
  **comma-separated** `SKILL_RUNNER_API_KEY` list (403 otherwise) — **but never
  threads the key downstream** (`_chat_direct(body.text, model)`).
- `main.py:391-460` — `LiteLLMClient`: single `self.api_key` for all requests;
  `chat_completion()` posts to `/v1/chat/completions`.
- Call sites: global `litellm_client` (~987), `_chat_direct` (~1914),
  media/MCP (~1389), `dispatch_job` (233, hardcodes `requester="siri"`).
- `cli/run-skill.sh` reads `SIRI_API_KEY` from `.env` for `X-API-Key`.
- `skills/siri_ask/skill.py:320` supports `--api-key` override.

### 1.7 Deltas vs. requirements

| # | Delta | Fix (phase) |
|---|---|---|
| D1 | skill-runner → LiteLLM uses master key ⇒ all Siri/skill usage attributed to `default_user_id` | Ph 2 (key pass-through) |
| D2 | Caddy edge enforces a single key ⇒ per-user keys can't reach skill-runner | Ph 3 (Caddyfile) |
| D3 | No `son` key; `simba`/`dylan` provenance unknown | Ph 1 (create `son`) |
| D4 | No `service` key for scheduler jobs | Ph 1 (create `service`) |
| D5 | No per-user **cached-tokens** panel in Grafana (metric exists) | Ph 4 (dashboard) |
| D6 | OWUI bypasses per-user attribution (master key) and is unused | Ph 6 (remove) |
| D7 | No key→user map in skill-runner (needed by this plan **and** the memory plan) | Ph 2 (map) |
| D8 | `api_chat` doesn't thread the caller key to LiteLLM | Ph 2 (code) |

---

## 2. Target architecture

### 2.1 Key model — one key per principal

| Principal | LiteLLM virtual key | key_alias / user_id | Used by |
|---|---|---|---|
| Chuck | existing `chuck-remote` key (or regenerated, see Ph 1.3) | `chuck` | Siri, Mac pi, CLI |
| Son | **new** key | `son` | son's device / Mac / CLI |
| Service | **new** key | `service` | scheduler jobs, automation |
| (admin) | master key (unchanged) | — | admin API, key management |

**The same key value is the single credential for both entry points:**

- `siri.choukalos.com` (skill-runner): sent as `X-API-Key`
- `llm.choukalos.com` (LiteLLM): sent as `Authorization: Bearer`

skill-runner validates the key (inbound list), maps it to a user, and **passes
the same key through to LiteLLM** as the outbound Bearer token — so LiteLLM
natively attributes every token to the right `user` label. No separate
"skill key" and "LLM key" per person.

### 2.2 Identity map (shared with the memory plan)

New env var in `.env` (gitignored), **referencing env var names — no secret
values in the map itself**:

```
AUTH_USER_MAP=LITELLM_KEY_C:chuck,LITELLM_KEY_S:son,LITELLM_KEY_SERVICE:service,SIRI_API_KEY:chuck
```

skill-runner resolves each name to its `.env` value at startup and builds
`{key_value: user_id}`. Unknown key → `unknown` (still served, but: no memory
retrieval/writeback per the memory plan, logged).

**user_ids are identical to the memory plan:** `chuck`, `son`, `service`,
`unknown`. The memory plan's Phase 3 (identity) **consumes this exact map** —
build it here once, reuse it there.

### 2.3 Request flows (target)

```
Siri/device ──X-API-Key: <chuck|son key>──▶ Caddy (allows any known key)
             ──▶ skill-runner (validates list → maps user_id)
             ──▶ LiteLLM  Authorization: Bearer <same key>
                            + LiteLLM-User-Id: <user_id>
             ⇒ metrics user="chuck" / "son"  ✓

Scheduler ──▶ skill-runner dispatch_job ──▶ LiteLLM with SERVICE key, user="service"
Mac/CLI   ──▶ llm.choukalos.com with own key (unchanged, already works)
```

- `LiteLLM-User-Id` header is sent on **every** skill-runner→LiteLLM request as
  a second attribution signal (harmless when the key already carries the
  user_id; covers any fallback to the master key).
- Fallback: if the caller key is not a known LiteLLM virtual key (e.g. legacy
  paths), skill-runner uses `LITELLM_API_KEY` (master) + `LiteLLM-User-Id`.

### 2.4 Usage tracking in Grafana

- **Source:** Prometheus metrics via VictoriaMetrics (already scraped). No new
  exporters, no DB changes, spend logs stay disabled.
- **Dashboard:** new `grafana/dashboards/ai-usage-by-user.json` (auto-provisioned
  in ≤30s, no restart). Panels (exact PromQL in §3 Phase 4):
  - Tokens by user: input / **cached** / output / reasoning / total
  - Requests by user (success + failed), error rate
  - Spend by user (stat), budget remaining per key
  - Model breakdown per user (optional row)
- **Caveats (documented on the dashboard):**
  - `user="default_user_id"` = unattributed traffic (master key) — shown as its
    own row until D1/D6 are fixed.
  - **Cached tokens:** only populated when the provider reports
    `prompt_tokens_details.cached_tokens` (OpenAI/Anthropic-style). Local
    vLLM/ollama backends may report 0 — the panel is still correct, just flat.
  - Counters reset when `litellm-proxy` restarts; `increase()`/`rate()` handle
    this (VictoriaMetrics PromQL semantics).

---

## 3. Phased implementation

> **Manual-step protocol, post-checks, and rollback: `memory_todo.md` §3.0.**
> Manual step **B** (`./homelab.sh rebuild skill-only`) is shared with the
> memory plan — batch skill-runner rebuilds across both plans when phases
> overlap.

### Phase 0 — Inventory & delta design ✅ (done 2026-08-25)

- [x] Live inventory (§1): key DB, .env key roles, auth flows, monitoring
      stack, Caddy edge, OWUI footprint, skill-runner code.
- [x] Delta design: §1.7 + §2.
- [ ] **Create `docs/auth/IMPLEMENTATION_STATE.md`** (compact handoff file,
      same pattern as `docs/memory/IMPLEMENTATION_STATE.md`; < ~5K tokens; no
      secret values) — first step of the implementing session.

### Phase 1 — Key foundation (no container changes, no restarts)

1. **Create the `son` key** (LiteLLM API, master key required; key value is
   shown **once** — capture it immediately):
   ```bash
   curl -s -X POST http://localhost:4000/key/generate \
     -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
     -H "Content-Type: application/json" \
     -d '{"key_name":"son","key_alias":"son","user_id":"son"}'
   ```
2. **Create the `service` key** the same way
   (`key_name/service`, `user_id/service`).
3. **Chuck key:** keep the existing `chuck-remote` key (it's in active use on
   the Mac — regenerating would break that client mid-migration). Its alias is
   `chuck-remote`, not `chuck`; Grafana groups by the `user` label (`chuck`),
   so this is cosmetic. (Optional: `/key/update` alias to `chuck` — only if
   nothing breaks; verify the Mac still works after.)
4. **Store values in `.env`** (gitignored): `LITELLM_KEY_C`, `LITELLM_KEY_S`,
   `LITELLM_KEY_SERVICE`. Hand the son's key to Chuck out-of-band (never via
   chat logs / Git).
5. **Verify each key end-to-end** (read-only + one test chat each):
   - `POST http://localhost:4000/v1/chat/completions` with each key → 200.
   - `curl -s http://localhost:4000/metrics/ | grep 'user="son"'` (and
     `service`) → new series appear with correct labels.
   - **Negative test:** random key → 401.
6. **Delete stale keys** (Q1 answered 2026-08-25: "blow them away"):
   `POST /key/delete` for the `simba` and `dylan` keys (master key required).
   Verify: DB row soft-deleted, key no longer authenticates (401), and no
   `user="simba"`/`user="dylan"` series in metrics. Optional tidy-up: also
   delete the 3 expired `default_user_id` keys.

**Acceptance tests**
- [ ] `son` + `service` keys exist (DB check, no raw values logged).
- [ ] Each key returns 200 on a test chat; metrics show `user="son"` /
      `user="service"` series.
- [ ] No container was restarted; no config file changed.

**Gate to Phase 2:** all three principals have working keys with correct
metric attribution; state file created + updated.

### Phase 2 — skill-runner key pass-through + user map (code)

1. **`AUTH_USER_MAP` loader** (`skills/runner/main.py`): parse
   `name:value` pairs, resolve names via `os.environ`, build
   `{key_value: user_id}`; log the resolved user_ids (never key values).
   Unknown/absent map → empty dict (behavior unchanged).
2. **Inbound:** `api_chat` + `/skills/{skill_name}` + schedule endpoints
   resolve `x_api_key` → `user_id` (fallback `unknown`). Thread `user_id`
   (and the raw key) into the request context.
3. **Outbound:** `LiteLLMClient.chat_completion()` / `embeddings()` accept an
   optional `api_key` + `user_id` override; send
   `Authorization: Bearer <caller key>` when the caller key is a known
   LiteLLM virtual key, else the default `LITELLM_API_KEY`; always send
   `LiteLLM-User-Id: <user_id>`.
4. **Scheduler:** `dispatch_job()` → `requester`/user `service`, service key
   (replaces hardcoded `requester="siri"` — memory plan D10).
5. **`.env`:** `SKILL_RUNNER_API_KEY` is already wired as
   `${SIRI_API_KEY}`; change compose to
   `SKILL_RUNNER_API_KEY=${LITELLM_KEY_C},${LITELLM_KEY_S},${LITELLM_KEY_SERVICE},${SIRI_API_KEY}`
   (legacy key stays for the migration window). Add `AUTH_USER_MAP` to
   `compose/compose.skill-runner.yml` + `.env`.
6. **Flag:** `AUTH_KEY_THREADING_ENABLED` (default `false` → today's behavior;
   `true` → pass-through). Set it to `true` in `.env` **before** the rebuild —
   env vars are injected at container creation, so flipping it later would
   need another manual step B.
7. **Tests (pre-rebuild, throwaway container per §3.0):** unit tests for map
   resolution (each key → user_id; unknown → `unknown`; empty map → no-op).
8. Commit. **MANUAL STEP B (Chuck):** `./homelab.sh rebuild skill-only`
   (see `memory_todo.md` §3.0 — litellm stays up).
9. **Live tests (post-rebuild):** T5–T8 from §5 — son/chuck/legacy keys via
   `:8091/api/chat` → 200 with LiteLLM metrics showing the right `user` label;
   scheduler job → `service`; flag off → `default_user_id` (old behavior).
9. **Tests (post-rebuild, live):** T5–T8 from §5 — son/chuck/legacy keys via
   `:8091/api/chat`, verify LiteLLM metrics show the right `user` label;
   scheduler job → `service`.

**Gate to Phase 3:** flag-on requests with chuck/son keys appear in metrics as
`user="chuck"`/`user="son"`; legacy `SIRI_API_KEY` still works (mapped to
`chuck`); flag-off reproduces old behavior; post-checks green.

### Phase 3 — Caddy edge update (no manual step — Caddy hot-reloads)

1. **Caddyfile** (`caddy/Caddyfile`, `@siri` block): replace the single-key
   gate with an OR over the known keys (defense-in-depth; skill-runner still
   returns 403 for anything else):
   ```
   @noAuth not expression (
       header X-API-Key {$LITELLM_KEY_C} or
       header X-API-Key {$LITELLM_KEY_S} or
       header X-API-Key {$LITELLM_KEY_SERVICE} or
       header X-API-Key {$SIRI_API_KEY}
   )
   ```
   (Apply to both `/siri/*` and `/api/*` handles. Alternative: drop the gate
   entirely and rely on skill-runner's 403 — acceptable, but the edge check
   keeps bad keys out of the app logs.)
2. **Caddy reloads automatically** (bind-mounted Caddyfile, in-process
   graceful reload — **not** a container lifecycle command). Verify:
   `docker logs --tail 20 caddy` shows the reload + no errors.
3. **Tests:** curl `https://siri.choukalos.com/api/chat` (or `/health` + one
   chat) with each of the 4 keys → 200; with a bogus key → 401.

**Gate to Phase 4:** all known keys pass the edge; bogus key rejected at edge;
other Caddy sites (ghost/invest/plausible) unaffected; caddy logs clean.

### Phase 4 — Grafana per-user dashboard (no restart — 30s auto-provision)

Create `grafana/dashboards/ai-usage-by-user.json` (datasource `Prometheus`).
Base it on `llm-gpu-monitor.json` panel styling. Panels + queries:

| Panel | Type | Query |
|---|---|---|
| Tokens by user (input) | timeseries | `sum by (user) (increase(litellm_input_tokens_metric_total[$__interval]))` |
| Tokens by user (cached) | timeseries | `sum by (user) (increase(litellm_input_cached_tokens_metric_total[$__interval]))` |
| Tokens by user (output) | timeseries | `sum by (user) (increase(litellm_output_tokens_metric_total[$__interval]))` |
| Tokens by user (total) | timeseries | `sum by (user) (increase(litellm_total_tokens_metric_total[$__interval]))` |
| Reasoning tokens | timeseries | `sum by (user) (increase(litellm_output_reasoning_tokens_metric_total[$__interval]))` |
| Requests by user | timeseries | `sum by (user) (increase(litellm_proxy_total_requests_metric_total[$__interval]))` |
| Failed requests by user | timeseries | `sum by (user) (increase(litellm_proxy_failed_requests_metric_total[$__interval]))` |
| Tokens (range, by user) | stat/table | `sum by (user) (increase(litellm_total_tokens_metric_total[$__range]))` |
| Input/Cached/Output split | pie/bar | `sum by (user) (increase(litellm_input_tokens_metric_total[$__range]))` + cached + output |
| Spend by user (range) | stat | `sum by (user) (increase(litellm_spend_metric_total[$__range]))` |
| Requests by key (alias) | table | `sum by (api_key_alias) (increase(litellm_proxy_total_requests_metric_total[$__range]))` |
| Budget remaining per key *(required once Phase 8 sets budgets)* | gauge | `litellm_remaining_api_key_budget_metric` |
| Model breakdown by user | table | `sum by (user, requested_model) (increase(litellm_total_tokens_metric_total[$__range]))` |

Add a dashboard description noting the caveats from §2.4 (default_user_id =
unattributed; cached tokens may be 0 for local backends).

**Acceptance tests**
- [ ] Dashboard appears in Grafana within ~30s (no restart).
- [ ] Panels render with real data (chuck series present from 1.3 evidence).
- [ ] `user` variable (or legend) distinguishes chuck / son / service /
      default_user_id.

**Gate to Phase 5:** dashboard live and correct.

### Phase 5 — Device migration (manual, Chuck + son)

1. **Chuck's Siri shortcut:** set `X-API-Key` to the chuck key
   (`$LITELLM_KEY_C`). While at it, answer **Q3** (which URL the shortcut
   calls — `/api/chat` vs `/siri/chat`); fix accordingly.
2. **Son's laptop** (per Q4): he uses **opencode** — configure it with the
   son's key (`$LITELLM_KEY_S`) against `https://llm.choukalos.com/v1`
   (OpenAI-compatible; his stated preference is to hit the homelab via
   LiteLLM). Verify: one opencode session → LiteLLM metrics show
   `user="son"`. (The key also works on `siri.choukalos.com` if he ever
   uses Siri/skills.)
3. **CLI:** `cli/run-skill.sh` — document per-user key selection (env override
   `SIRI_API_KEY` already works; add a comment + README note).
4. **Mac pi / other clients:** already on the chuck key — no change.
5. **Scheduler:** now on the service key (Phase 2) — verify one scheduled job
   runs and metrics show `user="service"`.
6. **Observe 24–48h:** skill-runner logs (no 403 spikes), metrics (per-user
   series growing, `default_user_id` shrinking).

**Gate to Phase 6:** 24–48h clean observation; all devices on per-user keys.

### Phase 6 — Open WebUI removal (manual step)

1. **Archive data:** `tar -czf /home/chuck/data/backups/open-webui-$(date +%Y%m%d).tar.gz
   /home/chuck/data/open-webui` (keep it; deletion later is a separate manual
   decision).
2. **Compose:** remove the `open-webui` service block from
   `compose/compose.ai-core.yml`.
3. **`.env`:** remove `WEBUI_SECRET_KEY` and `HARNESS_API_KEY` (grep-verified:
   OWUI was the only consumer).
4. Commit. **MANUAL STEP F (Chuck)** (new step for this plan — not in the
   `memory_todo.md` A–D table):
   ```bash
   docker stop open-webui && docker rm open-webui
   ```
   (Surgical: stops/removes only OWUI — no other ai-core service is touched.
   `docker compose up` is unnecessary since no other service config changed.)
5. **Post-checks (model, read-only):** `docker ps` (no `open-webui`);
   `curl -s http://localhost:4000/health/liveliness`;
   `curl -s http://192.168.4.54:8091/health`; `docker logs --tail 20
   litellm-proxy` (OWUI's master-key traffic disappears from new metrics).

**Gate to Phase 7:** OWUI gone; litellm + skill-runner healthy; no other
service affected.

### Phase 7 — Cleanup & hardening

1. **Legacy key:** block `SIRI_API_KEY` in skill-runner's list **only after**
   the migration window is proven (all devices on per-user keys). Keep it
   mapped to `chuck` until then. (Blocking = remove from
   `SKILL_RUNNER_API_KEY` list + Caddyfile OR; manual step B.)
2. **Stale LiteLLM keys:** if Q1 confirmed `simba`/`dylan` obsolete and they
   weren't blocked in Phase 1, block now (`POST /key/block`).
3. **Docs:** `README_SIRI.md` (key section: per-user keys, where each is
   used), `README.md` (auth + usage-tracking section), `TODO.md` (mark OWUI
   items done/removed).
4. **MCP access model (decided 2026-08-25):** `allow_all_keys: true` is the
   **intended** design — every valid key may call every MCP tool (incl.
   `mcp_filesystem` write + `mcp_mysql`). No scoped grants planned; the old
   "Per-Key Access Hardening" deferral in `TODO.md` is closed as not-needed.

**Gate (to Phase 8):** docs current; legacy key blocked; all green; state
file updated.

### Phase 8 — Per-user budgets & rate limits (ROI tracking)

> **Prerequisite (verified 2026-08-25, already live):** `litellm/config.yml`
> sets **nominal pricing** per model so budgets work on self-hosted models
> ("the real cost is just your GPU time"): `matrix-coder` $0.00000075 in /
> $0.0000045 out per token; `matrix-gemma4-moe` $0.00000025 / $0.000002;
> `studio-gemma4-4b` $0.000001 / $0.000001; `embeddings` $0.0000001.
> Convention: **$1 budget ≈ 1M tokens** (chat-heavy mix). Spend metrics
> already accumulate (live: chuck ≈ $2.31, default_user_id ≈ $20.30).
> **Do not modify or zero out this pricing** (non-negotiable #9).

1. **Choose budget/limit values with Chuck** (documented here, no secrets):
   | Key | `max_budget` (nominal $) | `tpm_limit` | `rpm_limit` |
   |---|---|---|---|
   | `chuck` | e.g. 100 (= ~100M tokens/mo) | — | — |
   | `son` | e.g. 50 | — | — |
   | `service` | e.g. 20 | — | — |
   (Values are placeholders — fill in with Chuck; rate limits optional in v1,
   set only if a runaway loop is a realistic risk.)
2. **Apply key budgets + rate limits** (API-level, **no restart**):
   ```bash
   curl -s -X POST http://localhost:4000/key/update \
     -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
     -H "Content-Type: application/json" \
     -d '{"key":"<chuck key>","max_budget":100}'
   ```
   (Same for `son`/`service`; `tpm_limit`/`rpm_limit` in the same payload if
   set.) Verify: `GET /key/info` shows the budget; metrics
   `litellm_api_key_max_budget_metric` / `litellm_remaining_api_key_budget_metric`
   appear for the key. If values don't take effect (cache staleness),
   **MANUAL STEP A (Chuck):** `docker restart litellm-proxy`.
3. **ROI dashboard additions** (extend `ai-usage-by-user.json`, auto-provisioned
   ≤30s — no restart):
   - Budget utilization per key: gauge on
     `litellm_remaining_api_key_budget_metric / litellm_api_key_max_budget_metric`
   - Monthly nominal spend by user (ROI trend): `sum by (user)
     (increase(litellm_spend_metric_total[30d]))` (nominal $ = GPU-time proxy)
   - Cost per 1K output tokens by model: `sum by (requested_model)
     (increase(litellm_spend_metric_total[$__range])) / (sum by
     (requested_model) (increase(litellm_output_tokens_metric_total[$__range])) / 1000)`
   - Spend vs. budget table: `sum by (user) (litellm_spend_metric_total)` vs.
     key max budgets (static ref line from the table in step 1)
   - Dashboard description: **values are nominal** (pricing in
     `litellm/config.yml`), a proxy for GPU time — not real dollars.
4. **Exhaustion behavior test (throwaway key, never a real key):** generate a
   test key with `max_budget: 0.001` + `tpm_limit: 10`; run requests until it
   429s (`Budget exceeded` / rate-limit error); delete the test key.

**Acceptance tests**
- [ ] `chuck`/`son`/`service` keys show budgets in `/key/info` + metrics.
- [ ] Grafana budget-utilization + ROI panels render with real data.
- [ ] Throwaway key 429s at budget/tpm limit; real keys unaffected.
- [ ] Nominal pricing in `litellm/config.yml` untouched (git diff clean).

**Gate (to Phase 9):** budgets + (optional) rate limits live per key; ROI
panels rendering; no container restarts needed (manual step A only if
stale); state file updated.

### Phase 9 — Skill model-alias fixes, Presenton hygiene, repo hygiene

> **Can run any time — independent of Phases 1–8; recommended early** because
> 7 of 11 skills are currently broken by a stale alias. (Folded in from the
> old `TODO.md` 2026-08-25.)

1. **Fix stale `model_alias` in 7 skills** (verified 2026-08-25: live LiteLLM
   has only `matrix-coder`, `matrix-gemma4-moe`, `studio-gemma4-4b`,
   `embeddings`, `hf-sd3` — `local/qwen-coder` does not exist, so every skill
   pinned to it fails its LLM call):
   - `skills/deep_research/skill.yml`
   - `skills/demo_workflow/skill.yml` (the old "C8 create-demo NOT WORKING")
   - `skills/family_kb_ingest/skill.yml`
   - `skills/homelab_report/skill.yml`
   - `skills/presentation_build/skill.yml`
   - `skills/presentation_update/skill.yml`
   - `skills/siri_ask/skill.yml`
   Change `model_alias: local/qwen-coder` → `model_alias: matrix-coder`
   (matches the memory plan's extraction-LLM decision). Leave
   `demo_browse` (`none`) and the 4 already-on-`matrix-coder` skills alone.
   Verify: `grep -rn "local/qwen-coder" skills/` → no hits.
2. **Presenton env var name mismatch:** code reads `PRESENTON_URL` (default
   `http://presenton:80`) but `.env` defines `PRESENTON_BASE_URL` — it only
   works because the default happens to match. Rename the `.env` line to
   `PRESENTON_URL=http://presenton:80` (no code refs to the old name —
   grep-verified).
3. **Rotate the Presenton password:** `PRESENTON_AUTH_PASSWORD` in `.env` is
   a default-looking value (visible via `docker inspect`). Generate a new
   value, update `.env`, and recreate the `presenton` container so its own
   env matches:
   **MANUAL STEP G (Chuck):**
   ```bash
   docker compose -f compose/compose.ai-core.yml up -d --force-recreate presenton
   ```
   (Only `presenton` is recreated; `--force-recreate` on a single named
   service leaves all other ai-core services untouched.)
4. **Untrack the git-committed log files** (tracked before `logs/` was
   gitignored — gitignore doesn't untrack): `git rm --cached
   logs/skill_runner/skill_runner.log logs/skill_runner/skill_runner.log.1`
   + commit. (`.gitignore` already covers `logs/`.)
5. **Rebuild skill-runner** for the skill.yml + `.env` changes (skills are
   baked into the image): **MANUAL STEP B (Chuck):** `./homelab.sh rebuild
   skill-only`.
6. **Tests:** end-to-end run of one previously-broken skill via
   `--public` (e.g. `create-demo` or `deep-research`) → job completes with a
   real artifact; `list-presentations` intent still returns Presenton data
   (HTTP 200 path re-verified post-recreate); `git status` shows no tracked
   log files.

**Acceptance tests**
- [ ] All 11 `skill.yml` files reference valid aliases (or `none`).
- [ ] `create-demo` (demo_workflow) completes end-to-end via `--public`.
- [ ] Presenton fetch path 200 after password rotation + recreate.
- [ ] `logs/skill_runner/*` untracked; `.gitignore` covers them.

**Gate (final):** all four fixes verified; post-checks green; state file
updated.

---

## 4. Feature flags & rollback

| Flag | Where | Default | Effect |
|---|---|---|---|
| `AUTH_KEY_THREADING_ENABLED` | `.env` → skill-runner | `false` | `false` = today's behavior (master key outbound); `true` = per-user pass-through |
| `AUTH_USER_MAP` | `.env` | empty | empty = no mapping (all `unknown` for memory purposes) |

**Rollback per phase**
- Ph 1: `POST /key/delete` for new keys; remove `.env` lines. (No restarts.)
- Ph 2: `AUTH_KEY_THREADING_ENABLED=false` → manual step B. Code rollback:
  `git checkout <last-good>` → manual step B.
- Ph 3: revert Caddyfile → Caddy hot-reloads (no restart).
- Ph 4: delete the dashboard JSON → auto-unprovisioned within 30s.
- Ph 5: revert device key values (manual, per device).
- Ph 6: restore `open-webui` block in compose + `docker compose -f
  compose/compose.ai-core.yml up -d open-webui` (manual step F); data
  un-tarred from backup.
- Ph 7: re-add legacy key to list (manual step B) / `POST /key/unblock`.
- Ph 8: `POST /key/update` with `max_budget: null` (and `tpm_limit`/
  `rpm_limit` null) per key; delete ROI panels from the dashboard JSON.
- Ph 9: `git checkout` the 7 `skill.yml` files; restore old `.env` values;
  `git add logs/...` to re-track (rarely wanted); manual step B to roll back
  the rebuild.

---

## 5. Test matrix

| # | Test | Phase | Expected |
|---|---|---|---|
| T1 | Each new key → `POST /v1/chat/completions` (localhost:4000) | 1 | 200 + completion |
| T2 | Metrics show `user="son"` / `user="service"` after test chats | 1 | new series with correct labels |
| T3 | Bogus key → LiteLLM | 1 | 401 |
| T4 | Map resolution: each key → correct user_id; unknown → `unknown` | 2 | unit tests green |
| T5 | `X-API-Key: <son key>` → `:8091/api/chat` (flag on) | 2 | 200; LiteLLM metrics `user="son"` |
| T6 | Legacy `SIRI_API_KEY` → `:8091/api/chat` | 2 | 200; attributed `chuck` |
| T7 | Flag off → outbound uses master key (old behavior) | 2 | metrics `default_user_id` |
| T8 | Scheduled job runs under `service` | 2/5 | metrics `user="service"`; no personal memories (memory plan) |
| T9 | Caddy edge: 4 known keys → 200; bogus → 401 | 3 | per-key pass/reject |
| T10 | Other Caddy sites (ghost, invest, plausible) unaffected | 3 | 200 on each |
| T11 | Dashboard auto-provisions ≤30s; panels show real data | 4 | renders |
| T12 | 24–48h: no 403 spikes; per-user series grow | 5 | clean observation |
| T13 | After OWUI removal: litellm + skill-runner health; OWUI traffic gone from metrics | 6 | healthy / declining `default_user_id` |
| T14 | Legacy key blocked: old key → 401 at edge + 403 at skill-runner | 7 | rejected |
| T15 | `son`/`chuck`/`service` keys show budgets in `/key/info` + budget metrics | 8 | values present |
| T16 | Throwaway key with `max_budget: 0.001` + `tpm_limit: 10` → 429 on exhaustion | 8 | 429, real keys unaffected |
| T17 | ROI panels (budget utilization, monthly spend, $/1K tokens) render with real data | 8 | renders |
| T18 | All `skill.yml` `model_alias` values valid (grep for `local/qwen-coder` → 0 hits); `create-demo` end-to-end via `--public` | 9 | job completes |
| T19 | Presenton fetch 200 after password rotation + recreate; `list-presentations` intent works | 9 | 200 / data |
| T20 | `git status` clean re: `logs/` (untracked, gitignored) | 9 | no tracked logs |

---

## 6. Success criteria

- [ ] Chuck and son each have **one key** that works identically on
      `siri.choukalos.com` and `llm.choukalos.com`.
- [ ] Grafana shows **per-user** input / cached / output / total tokens,
      requests, errors, spend — no restarts required to maintain it.
- [ ] Scheduler traffic attributed to `service`; no personal usage hidden in
      `default_user_id` (residual unattributed traffic explained + minimal).
- [ ] Open WebUI removed; no dead references (compose/.env/docs).
- [ ] All 11 skills reference valid model aliases; `create-demo` works
      end-to-end (old TODO.md C8 closed); Presenton env/password hygiene
      done; log files untracked from git.
- [ ] Per-user budgets (+ optional rate limits) live on `chuck`/`son`/
      `service` keys; Grafana shows **ROI**: nominal spend per user, budget
      utilization, $ per 1K tokens — built on the existing nominal pricing in
      `litellm/config.yml` (untouched).
- [ ] Memory plan's identity layer (user_ids `chuck`/`son`/`service`/
      `unknown`) is served by this plan's `AUTH_USER_MAP` — no duplicate map.
- [ ] All changes reversible; every phase gated; no secrets in Git/logs/docs.

---

## 7. Non-negotiables

1. No secret values (raw keys) in Git, logs, dashboards, or this doc — hashes
   (sha256 prefix) and env var names only.
2. LiteLLM stays the only model gateway; per-user keys are LiteLLM virtual
   keys — no side channels.
3. Memory + usage identity is one map (`AUTH_USER_MAP`), one set of user_ids
   (`chuck`, `son`, `service`, `unknown`) — shared with the memory plan.
4. Unknown keys: served, but `unknown` user (no memory writeback per memory
   plan), logged.
5. The implementing model **never runs container lifecycle commands**
   (`memory_todo.md` §3.0); Caddyfile hot-reload is the only "no manual step"
   exception (in-process reload, verified in logs).
6. OWUI data is archived before removal (reversible).
7. Spend logs stay disabled (deliberate homelab decision); metrics are the
   source of truth.
8. Every phase reversible + gated; stop a phase if a required assumption is
   disproved.
9. **Keep the nominal pricing in `litellm/config.yml`** (per-model
   `model_info` costs) — it powers budgets and ROI tracking; never zero it
   out or delete it (adjust only with Chuck, deliberately).

---

## 8. Known gaps & risks

- **Q3 (Siri shortcut URL):** `README_SIRI.md` documents `POST /siri/chat`,
  but skill-runner exposes `/api/chat` only (Caddy strips `/siri` → `/chat`
  would 404). The shortcut likely calls `/api/chat`; verify on device in
  Phase 5. If `/siri/chat` is real, add a `/chat` alias route in skill-runner
  (small code change, manual step B).
- **Cached tokens for local models:** vLLM/ollama may not report
  `prompt_tokens_details.cached_tokens` → the cached panel may stay flat at 0.
  Not a defect; revisit if a caching-capable backend is added.
- **Counter resets:** litellm-proxy restarts reset metric counters;
  `increase()`/`rate()` cope, but very short windows right after a restart can
  look odd.
- **`chuck-remote` alias:** the active chuck key's alias is `chuck-remote`
  (cosmetic mismatch vs `user="chuck"`); Grafana uses the `user` label, so no
  functional impact.
- **simba/dylan keys:** provenance unknown (Q1 answered 2026-08-25: delete —
  Phase 1 step 6). `simba` carried a $200 nominal budget; deletion removes
  it. If any unknown client still uses them, it will 401 and be visible in
  LiteLLM logs.
- **Caddy OR-expression:** long key values in the Caddyfile come from env
  (`{$LITELLM_KEY_C}` etc.) — Caddy env expansion is standard, but test in
  Phase 3 (T9/T10) before relying on it.
- **Spend is nominal, not real dollars:** `litellm/config.yml` sets nominal
  per-token pricing (e.g. `matrix-coder` $0.00000075 in / $0.0000045 out) so
  budgets work — spend panels are a **GPU-time proxy** for ROI, not cash cost.
  Dashboard + docs must say so.
- **`user="None"` series:** some request paths (certain MCP/embedding calls)
  emit `user="None"` instead of `default_user_id`; treat both as unattributed
  in dashboards (filter/merge `user=~"None|default_user_id"`).

---

## 9. Relationship to `memory_todo.md`

- **Shared identity:** this plan's Phase 2 builds `AUTH_USER_MAP` + the
  key→user resolution that the memory plan's Phase 3 (identity) consumes.
  **Recommended order:** this plan's Phases 1–2 **before** memory Phase 3.
- **Shared user_ids:** `chuck`, `son`, `service`, `unknown` — memory
  isolation (per-user memory namespaces) is only as good as this plan's
  attribution.
- **Shared manual step B:** batch skill-runner rebuilds if phases overlap.
- **OWUI:** memory plan treats OWUI as deprecated/out-of-scope; this plan
  executes the removal (Phase 6).
- **State files:** `docs/auth/IMPLEMENTATION_STATE.md` (this workstream) and
  `docs/memory/IMPLEMENTATION_STATE.md` (memory workstream) — keep both
  updated; cross-reference at phase gates.

---

## Appendix A — Verified inventory evidence (2026-08-25)

- `docker exec litellm-db psql`: 6 rows in `LiteLLM_VerificationToken`
  (aliases simba/dylan/chuck-remote + 3 default/expired); `LiteLLM_UserTable`
  has only `default_user_id` (key-level `user_id` is sufficient — no user rows
  needed).
- `litellm/config.yml`: `general_settings.master_key:
  os.environ/LITELLM_MASTER_KEY`; `disable_spend_logs: true`;
  `disable_spend_updates: true`; `litellm_settings.callbacks: [prometheus]`;
  `require_auth_for_metrics_endpoint: false`.
- `curl localhost:4000/metrics/`: per-user label sets verified (chuck series:
  2.34M input / 122K output tokens on `qwen38-27b` via `chuck-remote`);
  metric names in §1.3.
- `prometheus/prometheus.yml`: job `litellm` → `host.docker.internal:4000`,
  path `/metrics/`, 15s interval.
- `grafana/provisioning/datasources/datasources.yml`: `Prometheus` →
  `http://victoria-metrics:8428` (default).
- `grafana/provisioning/dashboards/dashboards.yml`: file provider,
  `updateIntervalSeconds: 30`.
- `caddy/Caddyfile`: single-key gate on `siri.choukalos.com` (`/siri/*`,
  `/api/*`); `llm.choukalos.com` unauthenticated at edge; Caddy in `homelab`
  compose project (not managed by `homelab.sh`), Caddyfile bind-mounted ro.
- `compose/compose.ai-core.yml` L60–83: `open-webui` service (env:
  `WEBUI_SECRET_KEY`, `OPENAI_API_KEY=${LITELLM_MASTER_KEY}`,
  `HARNESS_API_KEY=${HARNESS_API_KEY}`; data `/home/chuck/data/open-webui`).
- `.env` (names only): `LITELLM_API_KEY=${LITELLM_MASTER_KEY}` (compose
  interpolates → skill-runner outbound = master key); `HARNESS_API_KEY` ==
  master key value (sha256 match); `SIRI_API_KEY` 64-char hex.
- `skills/runner/main.py`: L127-128 (key envs), L1835-1855 (inbound list
  validation, no downstream threading), L391-460 (`LiteLLMClient` single key),
  L987/1389/1914 (call sites), L233 (`dispatch_job`, `requester="siri"`).
- `cli/run-skill.sh`: reads `SIRI_API_KEY` for `X-API-Key`.
- `litellm/config.yml` (working tree, 2026-08-25): **nominal pricing block**
  ("Custom pricing for budget tracking"): `matrix-coder` input $0.00000075 /
  output $0.0000045 / cache-creation $0.000000075 / cache-read $0.0000000075
  per token; `matrix-gemma4-moe` $0.00000025/$0.000002; `studio-gemma4-4b`
  $0.000001/$0.000001; `embeddings` $0.0000001. Convention: $1 ≈ 1M tokens.
  **Loaded live** — spend metric non-zero: chuck ≈ $2.31 (`chuck-remote`,
  `qwen38-27b`), default_user_id ≈ $20.30 (master-key traffic incl. pi linux
  + skill-runner), MCP calls $0.0. Key budgets (DB): `simba` $200, all others
  null; no `tpm_limit`/`rpm_limit` set on any key.
- LiteLLM admin API: `/key/generate`, `/key/update`, `/key/delete`,
  `/key/info`, `/key/block`, `/key/unblock`, `/budget/new|update|list` all
  present (1.92.0).
- **Stale skill model aliases (verified 2026-08-25):** `GET /v1/models` →
  `studio-gemma4-4b`, `matrix-coder`, `matrix-gemma4-moe`, `embeddings`,
  `hf-sd3` only; 7 `skill.yml` files pin `model_alias: local/qwen-coder`
  (deep_research, demo_workflow, family_kb_ingest, homelab_report,
  presentation_build, presentation_update, siri_ask) → broken LLM calls.
  `HARNESS_MODEL=matrix-coder` in `.env`.
- **Presenton (verified 2026-08-25):** container `presenton:80` on `ai-net`,
  env `PRESENTON_AUTH_USERNAME`/`PRESENTON_AUTH_PASSWORD` (default-looking
  password) + `PRESENTON_BASE_URL` (code reads `PRESENTON_URL` — mismatch);
  `GET /api/v1/ppt/presentation/all` (Basic auth, throwaway container) →
  HTTP 200 with real presentation data. `HARNESS_LLM_API_BASE`/`_KEY` point
  at litellm-proxy:4000 (master key).
- **Tracked log files (verified 2026-08-25):** `git ls-files logs/` →
  `skill_runner.log` + `skill_runner.log.1` (committed before `logs/` was
  gitignored).