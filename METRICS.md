# Homelab Metrics

This document describes the metrics infrastructure: what's instrumented, how data flows, naming conventions, and what the Grafana dashboards show.

---

## Architecture

```
LiteLLM (port 4000)  ──Prometheus callback──►  /metrics/
                                                            │
Node Exporter ──────────────────────────────────────────────┼──► Prometheus/VictoriaMetrics
cAdvisor  ─────────────────────────────────────────────────┤
DCGM (NVIDIA) ─────────────────────────────────────────────┘
                                                              │
                                                      Grafana (dashboards)
```

### Data Sources

| Source | Host | Port | What It Measures |
|---|---|---|---|
| LiteLLM | `host.docker.internal` | 4000 | LLM proxy: requests, tokens, spend, latency, key budgets |
| Node Exporter | `thor`, `matrix`, `athena` | 9100 | CPU, memory, disk, network per host |
| cAdvisor | `thor`, `athena` | 8080/9080 | Container resource usage |
| DCGM | `matrix` | 9400 | GPU utilization, temperature, power, VRAM (live since DCGM fix 2026-09-09) |
| vLLM | `matrix` | 8000 | LLM engine: tokens, cache, queue, latency (operational, engine-wide) |
| Media pipeline | `matrix` | 8189 | Media work meter: jobs, work units, cost $, per user (live 2026-09-09) |

Prometheus scrapes all sources every **15 seconds** and feeds Grafana for visualization.

---

## LiteLLM Metrics

LiteLLM acts as the LLM proxy for the homelab. It exposes metrics via the `prometheus` callback configured in `litellm/config.yml`. All metrics are labeled by `api_key_alias` (user) and `user` for per-key tracking.

### Available Metrics

| Metric | Type | Description |
|---|---|---|
| `litellm_proxy_total_requests_metric_total` | counter | Total requests per key |
| `litellm_proxy_failed_requests_metric_total` | counter | Failed requests per key |
| `litellm_spend_metric_total` | counter | Spend ($) per key, broken down by model |
| `litellm_total_tokens_metric_total` | counter | Total tokens per key |
| `litellm_input_tokens_metric_total` | counter | Input tokens per key |
| `litellm_output_tokens_metric_total` | counter | Output tokens per key |
| `litellm_request_total_latency_metric` | histogram | Request latency per key (sum/count for avg) |
| `litellm_api_key_max_budget_metric` | gauge | Budget cap per key (absent = no budget) |
| `litellm_remaining_api_key_budget_metric` | gauge | Remaining budget per key (`+Inf` = unlimited) |

### Not in Prometheus

The following key properties are **not** exposed as Prometheus metrics. Use `./homelab.sh key info <user>` instead:

- `blocked` status
- `expires` date
- `models` allowed
- `rpm_limit` (requests per minute)
- `tpm_limit` (tokens per minute)
- `created_at`
- `last_active`

### Naming Convention

| `api_key_alias` value | Display Name |
|---|---|
| `""` (empty string) | **master** |
| `litellm-internal-health-check` | **health-check** |
| anything else (e.g. "simba", "dylan") | as-is |

Grafana queries use `label_replace()` in the PromQL expression itself to map the empty-string master key to "master". Legend formatting uses `{{api_key_alias}}` so Grafana interpolates the label after PromQL evaluation.

### Key Filtering

To exclude the internal health-check key from stats:
```
api_key_alias != "litellm-internal-health-check"
```

The master key (`api_key_alias=""`, `user="default_user_id"`) **is included** in all stats — it represents system/skill-runner activity.

### Budget Pricing

Self-hosted models have nominal pricing so key budgets are meaningful without real dollar costs:

| Model | Cost/token | Rough equivalence |
|---|---|---|
| LLM models | $0.000001 | $1 budget ≈ 1M tokens (~3-5k chat turns) |
| Embeddings | $0.0000001 | 10x cheaper (short vectors) |

The "cost" is just GPU time — adjust in `litellm/config.yml` if needed.

---

## Deployed Models

| Model Name | Backend | Host | Description |
|---|---|---|---|
| `studio-gemma4-4b` | LMStudio | `macstudio:1234` | Gemma 4B on Mac Studio M1 |
| `matrix-coder` | vLLM | `matrix:8000` | Qwen3.6-27B |
| `matrix-gemma4-moe` | Ollama | `matrix:11434` | Gemma 4 26B MoE |
| `embeddings` | Ollama | `matrix:11434` | Nomic embed-text |

---

## Media Work Metering (v2)

GPU work from the media pipeline (ComfyUI diffusion: Flux images, LTXV video,
SeedVR2 upscale, ACE-Step music, MMAudio SFX) is priced as **deterministic
work units × a rate table** (energy-based synthetic tokens were abandoned —
the GPU/driver has no NVML energy counter).

**Status (2026-09-09): LIVE end-to-end.** Identity threading, pipeline
`/metrics` + `jobs.jsonl`, scrape, and the `AI Work & Spend` dashboard are
all operational. Rates calibrated on Matrix (energy-based full cost):
images ≈ $5.3e-5/mpix-step, audio ≈ $3.1e-5/s (placeholder defaults were
~20× higher).

**Cost model (per user):**
- **LLM $** = `litellm_spend_metric_total{user=...}` — the canonical LLM cost
  source. **Includes the pipeline's storyboard LLM**, which routes through
  this proxy with the caller's key (verified 2026-09-09).
- **Media $** = `media_cost_usd_total{user, stage}` — work-unit pricing
  (steps×MP, frames×MP, audio-seconds) at full cost (electricity + GPU
  amortization). Storyboard stage = real vLLM tokens at matrix-coder rates
  ($0.75/M in, $4.50/M out — mirrors the live LiteLLM config; permanent rule:
  if the LiteLLM rate changes, `MEDIA_MATRIX_CODER_IN_USD`/`_OUT_USD` follow).
- **Total work $ = LLM $ + Media ${stage != "storyboard"}** — the storyboard
  exclusion avoids double counting (it is already inside LLM $). The
  pipeline's storyboard cost remains a cross-check panel only.
- **No double-counting rule:** vLLM engine metrics (`vllm:*_tokens`) are
  operational (engine-wide, not per-user) — never sum them into $ totals.

**Identity chain:** pi → LiteLLM `/mcp-rest/tools/call` (caller's key) →
mcp_media (key → user via `GET /key/info`, `MEDIA_USER=chuck` fallback) →
pipeline job POST (`user` + `client` fields; JSON body or multipart form).

---

## Grafana Dashboards

### Dashboard 3: AI Work & Spend (uid `ai-work-spend`)

Total work $ = LLM + media, by user, plus GPU payback. File:
`grafana/dashboards/ai-work-spend.json` (generator: `grafana/dashboards/gen_ai_work_spend.py`).
Variables: `user` (multi), `ELEC_USD_PER_KWH=0.15`, `GPU_AVG_W=200`,
`GPU_COST_USD=4000`, `GPU_LIFETIME_HOURS=43800`.

```
  Row 1  LLM — via LiteLLM proxy (per user): spend/tokens/requests (range),
         spend by user (5m), vLLM engine tokens (operational cross-check)
  Row 2  Media — pipeline metering (per user): cost/jobs/tokens (range),
         media_up online indicator, cost by user×stage, work units by kind
  Row 3  Total work $ (LLM + media, by user): range total (storyboard
         excluded from media side, `or` fallback while media metric absent),
         by user (range barchart + 5m rate)
  Row 4  GPU $ & payback: GPU $ (range, MEASURED DCGM power with GPU_AVG_W
         fallback), amortization $/h, payback ratio (work $ / GPU $), DCGM
         power/util
  Row 5  Pipeline operational: queue depth, active jobs, duration by stage,
         jobs by status
```

**DCGM note:** DCGM field polling was frozen on Matrix (driver/DCGM bug) and
showed stale values; fixed 2026-09-09 (pinned older dcgm-exporter image,
DCGM 3.x). Power now moves live (≈14 W idle → ~300 W under load). Row 4's
GPU $ uses measured power with a `GPU_AVG_W` estimate fallback. Legacy
dashboards' DCGM panels (dcgm.json, llm-gpu-monitor.json,
homelab-overview.json incl. "GPU Investment ROI") are live again.

### Dashboard 1: LLM & GPU Monitor

A detailed operational dashboard combining LLM proxy metrics, per-key usage, and GPU hardware metrics.

```
  [10] LLM Overview                            y=0   h=1
  [ 1-6] Stats row                              y=1   h=5
  [11] Model Breakdown                          y=6   h=1
  [ 7-9] Model panels                           y=7   h=8
  [26] Key Usage                                y=15  h=1
  [27-31] Key stats                             y=16  h=5
  [32-34] Key bar charts                        y=21  h=8
  [35] Budget Utilization % (full width)        y=29  h=8
  [37-38] Spend/requests over time              y=37  h=6
  [39] Key Detail Table                         y=43  h=8
  [12] GPU Metrics (Matrix)                     y=51  h=1
  [13-17] GPU stats + over time                 y=52  h=8
  [18-19] Prompt rate + LLM latency             y=60  h=6
  [20-21] Input/output tokens over time         y=66  h=6
  Total height: 72 rows
```

**Key Usage section highlights:**
- **Active Keys** — count of keys with traffic (excludes health-check)
- **Keys with Budget** — count of keys that have a budget cap set
- **Keys Budget Exhausted** — keys where remaining < $0.01
- **Total Keys Spend** — sum of spend over selected time range
- **Avg Latency by Key** — per-key average latency (sum/count from histogram)
- **Spend by User** — bar gauge of spend per key
- **Tokens by User (In/Out)** — bar chart of input/output tokens per key
- **Requests by User** — bar gauge of request count per key
- **Budget Utilization %** — full-width bar gauge with color thresholds (green <80%, yellow 80-95%, red >95%)
- **Spend Over Time / Requests Over Time** — 5-minute rate time series per key
- **Key Detail Table** — comprehensive table: User, Requests, Spend ($), Input/Output Tokens, Budget Cap, Remaining, Utilization %, Status

### Dashboard 2: Homelab Overview

A high-level infrastructure dashboard covering servers, services, LLM metrics, API keys, and GPUs.

```
  [ 1] Servers                                  y=0   h=1
  [ 2-4] Server stats                           y=1   h=5
  [ 5-6] CPU/Memory over time                   y=6   h=7
  [ 7] Services                                 y=13  h=1
  [ 8] Container Overview                       y=14  h=12
  [10] LLM Metrics                              y=36  h=1
  [11-16] LLM panels                            y=37  h=5
  [26] API Keys                                 y=43  h=1
  [27-31] Key stats                             y=44  h=5
  [32] Top 3 Spend by Key (30d)                 y=49  h=7
  [17] GPU Metrics                              y=56  h=1
  [18-22] GPU stats                             y=57  h=7
  [23-25] GPU over time + ROI                   y=64  h=7
  Total height: 71 rows
```

**API Keys section highlights:**
- **Active Keys** — keys with traffic (excludes health-check)
- **Keys w/ Budget** — keys with a budget cap
- **Total Spend (30d)** — 30-day spend total
- **Budget Exhausted** — keys near or past budget
- **Top Spend Key** — highest spender over 30 days
- **Top 3 Spend by Key (30d)** — table of top 3 spenders with spend ($) and total tokens

---

## Key Query Patterns

### Average Latency (from histogram)
```promql
rate(litellm_request_total_latency_metric_sum{...}[$__rate_interval])
  / rate(litellm_request_total_latency_metric_count{...}[$__rate_interval])
```

### Budget Utilization %
```promql
(1 - litellm_remaining_api_key_budget_metric{...}
    / litellm_api_key_max_budget_metric{...}) * 100
```

### Spend Over a Range
```promql
increase(litellm_spend_metric_total{...}[$__range])
```

### Active Key Count (excluding health-check)
```promql
count(count by (api_key_alias)
  (litellm_proxy_total_requests_metric_total{api_key_alias!=""})) - 1
```

---

## Files

| File | Purpose |
|---|---|
| `litellm/config.yml` | LiteLLM model definitions, pricing, prometheus callback |
| `prometheus/prometheus.yml` | Scrape configs for all data sources |
| `grafana/dashboards/llm-gpu-monitor.json` | Dashboard 1 JSON |
| `grafana/dashboards/homelab-overview.json` | Dashboard 2 JSON |
| `grafana/dashboards/ai-work-spend.json` | Dashboard 3 (AI Work & Spend) JSON |
| `compose/compose.ai-core.yml` | LiteLLM + Prometheus + Grafana stack |
| `compose/compose.mcp.yml` | MCP servers (incl. `mcp_media` identity threading) |
| `homelab.sh` | CLI for key management (`key info`, `key list`, etc.) |

(Metering plan files `thor_media_work.md` / `matrix_media_work.md` were
completed 2026-09-09 and deleted — state lives in this file + `TODO.md`.)
