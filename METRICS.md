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
| DCGM | `matrix` | 9400 | GPU utilization, temperature, power, VRAM |

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

## Grafana Dashboards

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
| `compose/compose.ai-core.yml` | LiteLLM + Prometheus + Grafana stack |
| `homelab.sh` | CLI for key management (`key info`, `key list`, etc.) |
