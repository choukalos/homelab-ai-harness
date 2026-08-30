# Per-User Keys & LiteLLM Attribution — Plan (v2)

> **Fresh plan, 2026-08-29.** Replaces the old auth plan (Phases 0–9, mostly
> stale). The **identity layer (key → user_id) is already built** by the memory
> work — this plan wires **per-user LiteLLM keys** through Siri/skills so usage
> is attributed per user, and folds in the surviving Phase-9 tooling items.
>
> **No secret values here — ever.** (Key names/paths yes; key contents no.)
> **The implementing model never runs container lifecycle commands** — restarts
> / rebuilds are manual steps (B / G) run by Chuck between turns.

## 0. Requirements (from Chuck, 2026-08-29)

1. **One key per user** (chuck, dylan) — the *same* value for LiteLLM **and**
   Siri/skills. Chuck + Dylan already have LiteLLM keys.
2. **Delete the `simba`** test key.
3. **Key-management scripts** work per-user (one key per user).
4. **OWUI: hold off** on removal (owner decision 2026-08-29).
5. **Grafana: open to the family** (no per-user Grafana auth); keep + verify
   the per-user key reporting (already in place).
6. **Device + legacy-key migration: owner, later** (manual).
7. **Tooling uses appropriate keys** (old Phase 9): fix stale model aliases;
   **Presenton passwordless** (not password rotation) for family use.

## 1. Current state (verified live 2026-08-29)

### Identity layer (already built — memory work)
- `skills/runner/memory/identity.py`: `resolve_user_id()` maps `X-API-Key` →
  `user_id` via the `MEMORY_USER_KEYS` env map (env-var-name → value,
  constant-time compare). `RequestContext` contextvar. `USER_SERVICE` /
  `USER_UNKNOWN` defaults.
- `MEMORY_USER_KEYS=chuck=SKILL_RUNNER_API_KEY,service=SIRI_KEY_SERVICE`
  (2 pairs). A referenced env var may hold a comma-separated key list — every
  listed value maps to that user. Multiple entries may map to the same user.
- **Inbound allow-list** (`main.py:2038`): `SKILL_RUNNER_API_KEY` (comma
  list). Currently only Chuck's legacy `SIRI_API_KEY`. Dylan's key would 403.
- **Outbound to LiteLLM**: runner always sends the master key
  (`LITELLM_API_KEY=${LITELLM_MASTER_KEY}`) → all Siri/skill usage attributed
  to `default_user_id` / master. **No key threading** (0 refs to
  `LiteLLM-User-Id` / `AUTH_KEY_THREADING`).
- **⚠ Discovery (2026-08-29, during mcp_skills Phase B):** the service key
  `SIRI_API_KEY` (= `SKILL_RUNNER_API_KEY` in the container, 64-char) resolves
  to `user_id=service`, **not** `chuck` — even though `MEMORY_USER_KEYS`
  lists `chuck=SKILL_RUNNER_API_KEY` first and `SKILL_RUNNER_API_KEY`=`SIRI_API_KEY`
  (same value, verified by hash). `SIRI_KEY_SERVICE` (32-char, the `service`
  pair) is a different value. So the `chuck` pair's env var (`SKILL_RUNNER_API_KEY`)
  currently holds the **service** key, not a personal Chuck key — meaning the
  `chuck` mapping is effectively dormant until Phase 1 points it at Chuck's
  personal LiteLLM key. **Action for Phase 1:** when the raw Chuck key value is
  supplied (Q1), set the `chuck` pair's env var to that value (or add a new
  `LITELLM_KEY_CHUCK`-backed pair) so `resolve_user_id()` maps Chuck's key →
  `chuck`. Investigate why `service` wins the match (iteration order vs. key
  value) so the per-user attribution is unambiguous.

### LiteLLM key inventory (live, 8 rows)
| key (alias) | user_id | status |
|---|---|---|
| `simba` | (test) | **delete** (budget $200) |
| `dylan` | dylan | keep (son) |
| `chuck-remote` | chuck | keep (Chuck) |
| 3× `default_user_id` (expired) | default | cleanup |
| `sk-…M4Wg` (2026-08-28) | — | = `MEMORY_LITELLM_KEY` (memory service key) — keep |
| `sk-…nned` (2026-08-28) | — | unidentified test key — cleanup candidate |

### Key values (the blocker)
- The raw values of `chuck-remote` and `dylan` are **NOT in `.env`** or
  anywhere on the host (LiteLLM never returns raw keys after creation). Only
  `SIRI_API_KEY`, `SIRI_KEY_SERVICE`, `MEMORY_LITELLM_KEY` are stored.
- → To make "Siri key = LiteLLM key" work we need the values: either
  **regenerate** both keys (one-time value → `.env`) or have the owner
  **supply the existing values** out-of-band. (Open question **Q1**.)

### Edge (Caddy)
- Single-key gate: `@noAuth not header X-API-Key {$SIRI_API_KEY}` on
  `/siri/*` and `/api/*` (`siri.choukalos.com`). Dylan's key would 401 at the
  edge.

### Grafana (per-user reporting — already in place)
- `grafana/dashboards/llm-gpu-monitor.json` → "Key Usage" row: Spend by User,
  Tokens by User (In/Out), Requests by User, Budget Utilization, Spend /
  Requests Over Time by User, Key Detail Table, Active Keys, Keys with Budget
  (all grouped by `api_key_alias`, master remapped). **The panels exist; the
  missing piece is attribution** (today all skill traffic =
  master / default_user_id).

### Models (old Phase 9)
- `local/qwen-coder` is **NOT in the live model list** (studio-gemma4-4b,
  matrix-coder, matrix-gemma4-moe, embeddings, homelab-embedding-v1, hf-sd3).
- 6 `skill.yml` + 2 `skill.py` defaults + 1 docstring still pin it → broken.

### Presenton (old Phase 9 — passwordless)
- Deployed `:latest` (2026-08-28) has a **native `DISABLE_AUTH` env var**
  (truthy → auth middleware skipped entirely; verified in the running image).
- LAN-only :5000. Currently Basic auth (`AUTH_USERNAME` / `AUTH_PASSWORD`).
- Skill code (`main.py:1745`, `presentation_build/skill.py:63`) always sends a
  Basic header — must skip it when passwordless.

### Scripts
- `cli/run-skill.sh`: hardcodes `SIRI_API_KEY` (no per-user selection).
- `cli/memory-admin.sh`: `MEMORY_ADMIN_API_KEY` (admin — fine as-is).
- **No LiteLLM key-management script exists** (create / list / delete).

### Docs
- `README_SIRI.md` documents `POST /siri/chat`, but skill-runner only exposes
  `POST /api/chat` (Caddy strips `/siri` → `/chat` → 404). Stale.

## 2. Target model

| Principal | One key (same value) | user_id | Stored in |
|---|---|---|---|
| chuck | LiteLLM key (alias `chuck`) | chuck | `.env LITELLM_KEY_CHUCK` |
| dylan | LiteLLM key (alias `dylan`) | dylan | `.env LITELLM_KEY_DYLAN` |
| service | `SIRI_KEY_SERVICE` (inbound) + (Q2: LiteLLM `service` key?) | service | `.env SIRI_KEY_SERVICE` |

- **Siri `X-API-Key` = LiteLLM `Bearer` = the same value.**
- `MEMORY_USER_KEYS=chuck=SKILL_RUNNER_API_KEY,chuck=LITELLM_KEY_CHUCK,dylan=LITELLM_KEY_DYLAN,service=SIRI_KEY_SERVICE`
  (legacy `SKILL_RUNNER_API_KEY` kept during migration).
- `SKILL_RUNNER_API_KEY` (inbound list) =
  `${SIRI_API_KEY},${LITELLM_KEY_CHUCK},${LITELLM_KEY_DYLAN}`.
- **Caddy OR-gate** over the 3 keys.
- **skill-runner key threading**: caller's key → LiteLLM `Bearer` (when it's a
  known per-user virtual key), else master + `LiteLLM-User-Id`. Flag
  `AUTH_KEY_THREADING_ENABLED` (default false).

## 3. Phases

### Phase 1 — Key foundation (no restart) — **DONE 2026-08-29**
- 1.1 Create / rotate the `chuck` + `dylan` LiteLLM keys. ✅
  - **chuck**: kept existing key (owner supplied raw value out-of-band →
    `.env LITELLM_KEY_CHUCK`). Verified 200 on `/v1/chat/completions`.
  - **dylan**: created new key (alias `dylan-v2`, `user_id=dylan`) because the
    old `dylan` alias already exists (test key, raw value unrecoverable).
    One-time value captured → `.env LITELLM_KEY_DYLAN`. Verified 200.
- 1.2 `.env`: `LITELLM_KEY_CHUCK` ✅ (owner-supplied), `LITELLM_KEY_DYLAN` ✅
  (generated). `LITELLM_KEY_SERVICE` — pending Q2.
- 1.3 Delete `simba`. ⚠️ **Blocked**: LiteLLM `/key/list` returns masked
  tokens (not raw values); `/key/info` rejects non-`sk-` tokens. Cannot delete
  by alias/token via API. Owner must delete manually (LiteLLM UI or by
  supplying the raw value). **Noted; deferred to Phase 7.**
- 1.4 Verify: chuck 200 ✅, dylan 200 ✅. Metrics per-user series — pending
  Phase 2 (key threading) + skill-runner restart.

### Phase 2 — skill-runner key threading (code + manual rebuild B)
- 2.1 `.env`: `MEMORY_USER_KEYS` += dylan ✅; `SKILL_RUNNER_API_KEY` list +=
  dylan's key ✅. (2026-08-29: `MEMORY_USER_KEYS` now has 4 pairs;
  `SKILL_RUNNER_API_KEY` = `${SIRI_API_KEY},${LITELLM_KEY_CHUCK},${LITELLM_KEY_DYLAN}`
  in both compose files.)
- 2.2 Code: `LiteLLMClient` key threading (optional `api_key` / `user_id`),
  flag `AUTH_KEY_THREADING_ENABLED`.
- 2.3 Tests (unit + disposable container).
- 2.4 Commit; **manual step B** (rebuild skill-only).
- 2.5 Live: T5–T8 (per-user attribution, isolation).

### Phase 3 — Caddy OR-gate (hot reload, no manual step)
- 3.1 `@noAuth not header X-API-Key (chuck|dylan|legacy)`.
- 3.2 `caddy reload` + verify.

### Phase 4 — Grafana (verify + small add)
- 4.1 Verify the per-user panels show chuck / dylan after threading (grouped
  by `api_key_alias`).
- 4.2 (optional) add a cached-tokens panel (small JSON edit, auto-provisioned).

### Phase 5 — Tooling & scripts (old Phase 9)
- 5.1 `cli/litellm-keys.sh` helper (list / generate / delete; one-time value
  display; no raw values in logs).
- 5.2 `run-skill.sh`: `--user` flag / `SKILL_USER` env → per-user key.
- 5.3 Fix the 6 `skill.yml` aliases + 2 `skill.py` defaults + `main.py`
  docstring (`local/qwen-coder` → `matrix-coder`).
- 5.4 `PRESENTON_BASE_URL` → `PRESENTON_URL` rename.
- 5.5 **Presenton passwordless**: `DISABLE_AUTH=true`, drop `AUTH_*`,
  recreate [**manual step G**].
- 5.6 Rebuild skill-only (manual step B) + e2e (`create-demo`).

### Phase 6 — Device migration (owner, later)
- 6.1 Siri shortcut: `X-API-Key` = chuck's key; verify URL (`/api/chat` vs
  `/siri/chat` — fix `README_SIRI.md`).
- 6.2 Son's laptop (opencode): dylan's key → `llm.choukalos.com/v1`.
- 6.3 Mac pi: new chuck key (if regenerated).
- 6.4 Observe 24–48h.

### Phase 7 — Legacy key retirement (owner, after migration)
- 7.1 Remove `SIRI_API_KEY` from the list + Caddy; update the Siri shortcut
  first.
- 7.2 Delete the old `chuck-remote` / `dylan` keys (if regenerated).
- 7.3 Docs: `README_SIRI.md`, `README.md`.

## 4. Flags & rollback
- `AUTH_KEY_THREADING_ENABLED` (default false) — off = master key (today's
  behaviour).
- Rollback: revert the flag / Caddy / `.env` list; no data migration.

## 5. Test matrix
- **T1**: no key → 401 (edge + skill-runner).
- **T2**: chuck key → 200, user=chuck (memory + LiteLLM metrics).
- **T3**: dylan key → 200, user=dylan.
- **T4**: legacy SIRI key → 200, user=chuck (during migration).
- **T5**: invalid key → 403 (skill-runner) / 401 (edge).
- **T6**: threading on → LiteLLM metrics show per-user series.
- **T7**: threading off → master / default_user_id (today).
- **T8**: memory isolation (chuck vs dylan) — no cross-read.

## 6. Success criteria
- One key per user works for both LiteLLM + Siri/skills.
- Usage attributed per user (Grafana Key Usage shows chuck / dylan).
- `simba` gone; no stray test keys.
- Scripts work per-user.
- Presenton passwordless; stale model aliases fixed.
- OWUI untouched (held off).

## 7. Non-negotiables
- No secrets in git / logs / chat (key names / paths yes; values no).
- Master key stays the master key (never a user key).
- Identity is a single map (`MEMORY_USER_KEYS`) — no parallel key logic.
- The model never runs container lifecycle commands (manual steps B / G).
- OWUI stays (owner decision).
- Nominal pricing stays (no per-user budgets this round).

## 8. Deferred / out of scope
- **OWUI removal** (owner: hold off).
- **Per-user budgets / ROI** (old Phase 8) — deferred; nominal pricing stays.
- **Qdrant D9** (0.0.0.0:6333 + TLS) — owner: leave as-is.
- **MCP memory tools** (memory work Phase 6) — gated on a week of production
  use.

## 9. Questions for Chuck
1. **Q1 — key values (ANSWERED 2026-08-29):**
   - **chuck**: keep the existing key (owner has the value; does NOT want to
     change it). Owner will **supply the raw value out-of-band** when Phase 1
     is reached (→ `.env LITELLM_KEY_CHUCK`). Do NOT regenerate.
   - **dylan**: **regenerate** (owner does not have the raw value). One-time
     value capture → `.env LITELLM_KEY_DYLAN`.
   - **Constraint (owner):** do NOT touch/restart the LiteLLM proxy from the
     implementing agent (kills its own session); batch manual steps.
2. **Q2 — service key**: a dedicated LiteLLM `service` key for scheduler
   attribution, or keep the scheduler on the master key?
3. **Q3 — Presenton**: `DISABLE_AUTH=true` is verified in the deployed image —
   confirm go (fallback: a shared family password if a future image update
   regresses it).
4. **Q4 — Siri shortcut URL**: is it `/api/chat` or `/siri/chat`? (verify on
   the device in Phase 6; `README_SIRI.md` is fixed either way.)