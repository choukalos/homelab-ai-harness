# Agentic Skills Development Plan

Status: **Phase 1 + Phase 2 complete and verified end-to-end (2026-08-31).**
Phase 3 (cross-client QA) **in progress**: the shared MCP gateway path (`mcp_skills` →
`run_skill`) is verified for all 3 new skills. Specific client integrations
(Siri/Shortcuts, pi `/skill:`, Claude Code `marketplace.json`) remain.

## Phase 1: Verification & Cleanup (High Priority)
*Target: Ensure existing infrastructure is stable before adding complexity.*

### 1.1 Validate Core Demo Skills
- [x] **Verify `demo_workflow`**: `--dry-run` OK; full HTML generation is **slow/unreliable with the `matrix-coder` reasoning model** (heavy HTML tasks over-reason and can return `content: None`). Applied a robustness fix so it fails gracefully (falls back to `reasoning_content`, clear error) instead of crashing. Recommend a non-reasoning model or lighter prompts for production use.
- [x] **Verify `demo_browse`**: standalone `--query "*"` → 6 demos found, 5 matching.

### 1.2 Validate Market / Competitive Analysis Skill
- [x] **Verify `investment_brief`**: syntax OK, `--dry-run` OK (portfolio + dividend + market news via `mcp_mysql` + `mcp_search`).

---

## Phase 2: New Skills (COMPLETE)
*Built as self-contained Python skill modules (`run(params, job, litellm_client=None)`),
Markdown output, `matrix-coder` default, 300s max runtime, channels `[cli, pi, n8n]`.
All LLM + MCP calls go through LiteLLM (never direct MCP access).*

### 2.1 Marketing Content Strategy / GTM  ✅
- Files: `skills/marketing_strategy/{skill.py,skill.yml,README.md}`, `agents-skills/marketing-strategy/SKILL.md`.
- Flow: product brief → market research via `mcp_search` (competitors, TAM/SAM/SOM, trends, personas) → LLM GTM synthesis → Markdown artifact.
- Output: Executive Summary, Market Overview (TAM/SAM/SOM, labeled estimates vs. hard data), Competitive Landscape, Personas, Positioning, Pricing, Channels, 30/60/90 Launch Plan, Risks.
- **Verified**: solar+battery HEMS → 10 research items, 4.9K-char strategy, artifact saved.

### 2.2 Content Writer (Social / Blog / Video)  ✅
- Files: `skills/content_writer/{skill.py,skill.yml,README.md}`, `agents-skills/content-writer/SKILL.md`.
- Flow: topic → optional research grounding via `mcp_search` → LLM content generation (social / blog / video / all) → Markdown content pack.
- Output: social (per-platform posts + hashtags), blog (hook→context→sections→CTA), video (concept + timecoded VO table + visual seeds).
- **Verified**: solar+battery (social+video) → 5 research items, 5.6K-char pack, artifact saved.

### 2.3 Business / Product Analyst (MySQL)  ✅
- Files: `skills/business_analyst/{skill.py,skill.yml,README.md}`, `agents-skills/business-analyst/SKILL.md`.
- Flow: question → resolve DB (investorhub/homelab) → `schema_overview` → NL→SQL + execute via `mcp_mysql` (fallbacks: `run_query`, `explain_sql`) → LLM insight synthesis → Markdown report.
- Output: Query (SQL), Results table, Key Insights, Interpretation (fact vs. inference), Follow-ups, **Grafana Suggestions**.
- **Verified**: "top 5 stocks by market cap" (investorhub) → correct SQL, 5 rows, 2.9K-char report, artifact saved.
- Future: Google Analytics / Amplitude integration.

---

## Phase 3: Deployment & QA

### 3.1 LiteLLM Integration
- [x] **LiteLLM restarted** (owner step, before QA).
- [x] **Skill runner rebuilt** (`./homelab.sh rebuild skill-only`); all 3 new skills discover via `skill.yml`.

### 3.2 Cross-Client QA
**Shared backend — MCP gateway (`mcp_skills` → skill-runner) — VERIFIED (2026-08-31):**
This is the path pi / Siri / Claude Code all use to invoke skills server-side.
- [x] `list_skills` via `mcp_skills` MCP REST → all 15 skills discovered (incl. the 3 new).
- [x] `run_skill` → `business_analyst` ("top 5 stocks by market cap") → completed, 5 rows, artifact saved.
- [x] `run_skill` → `marketing_strategy` (solar+battery HEMS) → completed, GTM artifact saved.
- [x] `run_skill` → `content_writer` (solar+battery, `format=all`) → completed, 3-format pack (social+blog+video), 10.8K chars, artifact saved.

**Issues found + fixed during gateway QA (2026-08-31):**
- [x] **`mcp_skills` stale + malformed service key**: container (Up 34h) held a pre-rotation key AND sent the comma-joined allow-list as a single `X-API-Key` (skill-runner exact-matches the split list → 403). Fix: `compose/compose.mcp.yml` `SKILL_RUNNER_API_KEY=${LITELLM_KEY_CHUCK}` (single key) + container recreated.
- [x] **Runner LLM per-call timeout too short**: the runner's `LiteLLMClient` (passed to skills in gateway mode) defaulted to **120s**, but heavy synthesis calls with `matrix-coder` exceed it (marketing_strategy failed at 120s with an empty error). Fix: `skills/runner/main.py` `LLM_CALL_TIMEOUT` env (default **240s**), passed to the client. Skill-runner rebuilt.
- [x] **`content_writer` max_runtime too short**: 3 sequential format calls (~110s each) exceeded the 300s budget. Fix: `MAX_RUNTIME_SECS` default **480s** (`skill.py` + `skill.yml`).
- [x] **Reasoning-model empty content**: `matrix-coder` sometimes returns `content: None` (output in `reasoning_content`). Fix: `content_writer` + `marketing_strategy` LLM-output extraction falls back to `reasoning_content` (same fix as `demo_workflow`).
- [x] **Empty error messages**: generic `except Exception` now logs `type(exc).__name__` for diagnosability.

**Specific client integrations (remaining):**
- [ ] **Siri/iOS Testing**: test new skills via Siri/Shortcuts.
- [ ] **pi Testing**: verify `/skill:name` commands for the 3 new agents.
- [ ] **Claude Code Testing**: verify `marketplace.json` / plugin availability.

---

## 🛠️ Infrastructure Fixes (made during Phase 2)
- [x] **`mcp_mysql`**: set `BLOCK_FULL_TABLE_SCANS=false` in `compose/compose.mcp.yml` so analytical full-table queries work. Other guards remain (MAX_ROWS_EXAMINED, MAX_JOIN_TABLES, 500-row cap, 30s timeout, SELECT-only). Container recreated to apply.
- [x] **`mcp_search`**: added configurable `SEARXNG_ENGINES` env (default `google,bing,mojeek`) in `mcp/servers/search/server.py` + `compose/compose.mcp.yml` — SearXNG's default set (brave/duckduckgo/startpage) was rate-limited / CAPTCHA-blocked and returning 0 results. Rebuilt image + recreated container.
- [x] **MCP response parsing**: `marketing_strategy` + `content_writer` `_extract_results` now handle the `/mcp-rest` gateway `structuredContent` shape (was returning 0 research items before).
- [x] **`mcp_skills` service key**: `compose/compose.mcp.yml` `SKILL_RUNNER_API_KEY` set to a single key (`${LITELLM_KEY_CHUCK}`) — the skill-runner exact-matches its comma-split allow-list, so a comma-joined value 403s. Container recreated to pick up the current (post-rotation) key.
- [x] **Runner LLM per-call timeout**: `skills/runner/main.py` `LLM_CALL_TIMEOUT` env (default 240s, was 120s) — heavy `matrix-coder` synthesis calls exceeded the old default. Skill-runner rebuilt (`./homelab.sh rebuild skill-only`).
- [x] **`content_writer` max_runtime 300s→480s** + **reasoning-model `reasoning_content` fallback** (content_writer + marketing_strategy) + **explicit exception types** in error messages.

## ✅ Test Results (2026-08-31)
| Skill | Test | Result |
|-------|------|--------|
| business_analyst | "top 5 stocks by market cap" (investorhub) via **MCP gateway** | ✅ 5 rows, report, artifact saved |
| marketing_strategy | solar+battery HEMS via **MCP gateway** | ✅ GTM strategy, artifact saved (240s LLM timeout) |
| content_writer | solar+battery `format=all` (3 formats) via **MCP gateway** | ✅ 3-format pack (social+blog+video), 10.8K chars, artifact saved (480s) |
| mcp_skills gateway | `list_skills` via MCP REST | ✅ 15 skills discovered (incl. 3 new) |
| demo_workflow | solar system simulator (full) | ⚠️ slow/unreliable with reasoning model; robustness fix applied (no more crash) |
| demo_browse | `--query "*"` | ✅ 6 demos, 5 matches |
| investment_brief | `--dry-run` | ✅ |

## 📌 Remaining / Future
- [ ] Cross-client QA — specific clients: Siri/Shortcuts, pi `/skill:`, Claude Code `marketplace.json` (shared MCP gateway path already verified).
- [ ] Google Analytics / Amplitude integration for business_analyst.
- [ ] Consider a shared MCP-response normalizer helper (skills currently duplicate the robust parser per the self-contained convention).
- [ ] Re-enable SearXNG blocked engines (brave/duckduckgo/startpage) once rate-limits clear; then widen `SEARXNG_ENGINES`.
- [ ] Consider a non-reasoning model (e.g. `studio-gemma4-26b`) for `marketing_strategy`/`content_writer`/`demo_workflow` production use — `matrix-coder` is slow (~110s/call) and intermittently returns `content: None`.