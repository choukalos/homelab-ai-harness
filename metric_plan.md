# LiteLLM Key Metrics — Grafana Dashboard Plan

## Data Source & Limitations

**Available in Prometheus** (filtered by `api_key_alias` and `user` labels):
- `litellm_proxy_total_requests_metric_total` — requests per key
- `litellm_proxy_failed_requests_metric_total` — failed requests per key
- `litellm_spend_metric_total` — spend ($) per key (by model)
- `litellm_total_tokens_metric_total` / `input` / `output` — tokens per key
- `litellm_request_total_latency_metric` — latency histogram per key
- `litellm_api_key_max_budget_metric` — budget cap per key (gauge)
- `litellm_remaining_api_key_budget_metric` — remaining budget per key (gauge; `+Inf` = unlimited)

**NOT in Prometheus** (skipped; use `./homelab.sh key info <user>`):
- `blocked` status, `expires`, `models` allowed, `rpm_limit`, `tpm_limit`, `created_at`, `last_active`

### Naming Convention

| `api_key_alias` | Display Name |
|---|---|
| `""` (empty) | **master** |
| `litellm-internal-health-check` | **health-check** |
| anything else (e.g. "simba", "dylan") | as-is |

Grafana queries use `label_replace` or legend formatting to handle the empty-string master key.

### Key Filtering

For queries scoped to "real" keys (not health-check), filter:
```
api_key_alias != "litellm-internal-health-check"
```

The master key (`api_key_alias=""`, `user="default_user_id"`) IS included in all stats — it represents system/ai-harness activity.

---

## Dashboard 1: LLM & GPU Monitor

**New "Key Usage" row** inserted between "Model Breakdown" (ends y=14) and "GPU Metrics" (starts y=15).

All GPU and below panels shift down by 28 rows.

### Row: "Key Usage" (y=15, h=1 for the row title)

#### Stats Row (y=16, h=5)
| Panel ID | Title | Type | Width | X | Query |
|---|---|---|---|---|---|
| 26 | Active Keys | stat | 4 | 0 | `count(count by (api_key_alias) (litellm_proxy_total_requests_metric_total{api_key_alias!=""})) - 1` (subtract health-check) |
| 27 | Keys with Budget | stat | 4 | 4 | `count(litellm_api_key_max_budget_metric{api_key_alias!="litellm-internal-health-check"})` |
| 28 | Keys Budget Exhausted | stat | 4 | 8 | `count(litellm_remaining_api_key_budget_metric{api_key_alias!="litellm-internal-health-check"} < 0.01)` |
| 29 | Total Keys Spend (range) | stat | 4 | 12 | `sum(increase(litellm_spend_metric_total{api_key_alias!="litellm-internal-health-check"}[$__range]))` |
| 30 | Avg Latency by Key | stat | 4 | 16 | `rate(litellm_request_total_latency_metric_sum{api_key_alias!="litellm-internal-health-check"}[$__rate_interval]) / rate(litellm_request_total_latency_metric_count{api_key_alias!="litellm-internal-health-check"}[$__rate_interval])` by `api_key_alias` |

#### Bar Charts Row (y=21, h=8)
| Panel ID | Title | Type | Width | X | Query |
|---|---|---|---|---|---|
| 31 | Spend by User | bargauge | 8 | 0 | `increase(litellm_spend_metric_total{api_key_alias!="litellm-internal-health-check"}[$__range])` grouped by `api_key_alias`. Legend: `{{api_key_alias}}` with label_replace for master. |
| 32 | Tokens by User (In/Out) | barchart | 8 | 8 | `increase(litellm_input_tokens_metric_total{api_key_alias!="litellm-internal-health-check"}[$__range])` + `increase(litellm_output_tokens_metric_total{api_key_alias!="litellm-internal-health-check"}[$__range])` by `api_key_alias`. |
| 33 | Requests by User | bargauge | 8 | 16 | `increase(litellm_proxy_total_requests_metric_total{api_key_alias!="litellm-internal-health-check"}[$__range])` grouped by `api_key_alias`. |

#### Budget Utilization Row (y=29, h=8)
| Panel ID | Title | Type | Width | X | Query |
|---|---|---|---|---|---|
| 34 | Budget Utilization % | bargauge | 12 | 0 | `(1 - litellm_remaining_api_key_budget_metric{api_key_alias!="litellm-internal-health-check"} / litellm_api_key_max_budget_metric{api_key_alias!="litellm-internal-health-check"}) * 100`. Only keys with budgets. Color thresholds: green <80%, yellow 80-95%, red >95%. |
| 35 | Budget Status Table | table | 12 | 12 | Columns: User, Budget Cap, Spent, Remaining, Utilization %, Status. Status column: "OK" <80%, "Warning" 80-95%, "Critical" 95-99.9%, "Exhausted" >=100%. |

#### Time Series Row (y=37, h=6)
| Panel ID | Title | Type | Width | X | Query |
|---|---|---|---|---|---|
| 36 | Spend Over Time by User | timeseries | 12 | 0 | `rate(litellm_spend_metric_total{api_key_alias!="litellm-internal-health-check"}[5m])` by `api_key_alias` |
| 37 | Requests Over Time by User | timeseries | 12 | 12 | `rate(litellm_proxy_total_requests_metric_total{api_key_alias!="litellm-internal-health-check"}[5m])` by `api_key_alias` |

#### Key Detail Table (y=43, h=8)
| Panel ID | Title | Type | Width | X | Query |
|---|---|---|---|---|---|
| 38 | Key Detail Table | table | 24 | 0 | Multi-query table with columns: User, Requests, Spend ($), Input Tokens, Output Tokens, Budget Cap, Budget Remaining, Utilization %, Status. Uses `increase(...[$__range])` for counters, gauges for budget info. |

### GPU Metrics Row Shift

All panels in "GPU Metrics" row and below shift **+28 rows**:
- Row "GPU Metrics" (panel 12): y=15 → y=43
- GPU Utilization (panel 13): y=16 → y=44
- GPU Temperature (panel 14): y=16 → y=44
- GPU Power Usage (panel 15): y=16 → y=44
- VRAM Usage (panel 16): y=16 → y=44
- GPU Utilization Over Time (panel 17): y=16 → y=44
- Prompt Processing Rate (panel 18): y=24 → y=52
- LLM API Latency Over Time (panel 19): y=24 → y=52
- Input Tokens Over Time (panel 20): y=30 → y=58
- Output Tokens Over Time (panel 21): y=30 → y=58

---

## Dashboard 2: Homelab Overview

**New "API Keys" row** inserted after "LLM Metrics" section (ends y=42).

All panels below shift down by 12 rows.

### Row: "API Keys" (y=43, h=1 for the row title)

#### Stats Row (y=44, h=5)
| Panel ID | Title | Type | Width | X | Query |
|---|---|---|---|---|---|
| 26 | Active Keys | stat | 4 | 0 | `count(count by (api_key_alias) (litellm_proxy_total_requests_metric_total{api_key_alias!=""})) - 1` |
| 27 | Keys w/ Budget | stat | 4 | 4 | `count(litellm_api_key_max_budget_metric{api_key_alias!="litellm-internal-health-check"})` |
| 28 | Total Spend (30d) | stat | 4 | 8 | `sum(increase(litellm_spend_metric_total{api_key_alias!="litellm-internal-health-check"}[30d]))` |
| 29 | Budget Exhausted | stat | 4 | 12 | `count(litellm_remaining_api_key_budget_metric{api_key_alias!="litellm-internal-health-check"} < 0.01)` |
| 30 | Top Spend Key | stat | 4 | 16 | `topk(1, increase(litellm_spend_metric_total{api_key_alias!="litellm-internal-health-check"}[30d]))` |

#### Top 3 Table Row (y=49, h=7)
| Panel ID | Title | Type | Width | X | Query |
|---|---|---|---|---|---|
| 31 | Top 3 Spend by Key (30d) | table | 24 | 0 | `topk(3, sum by (api_key_alias) (increase(litellm_spend_metric_total{api_key_alias!="litellm-internal-health-check"}[30d])))` with columns: User, Spend ($), Total Tokens. Tokens from: `topk(3, sum by (api_key_alias) (increase(litellm_total_tokens_metric_total{api_key_alias!="litellm-internal-health-check"}[30d])))` |

### Panels Below Shift

All "GPU Metrics" row and below shift **+12 rows**:
- Row "GPU Metrics" (panel 17): y=42 → y=54
- GPU Utilization % (panel 18): y=43 → y=55
- GPU Temperature (panel 19): y=43 → y=55
- VRAM Usage (panel 20): y=43 → y=55
- GPU Power (panel 21): y=43 → y=55
- GPU Utilization Over Time (panel 22): y=43 → y=55
- GPU Temp & Power Over Time (panel 23): y=50 → y=62
- VRAM Usage Over Time (panel 24): y=50 → y=62
- GPU Investment ROI (panel 25): y=50 → y=62

---

## Implementation Status: ✅ COMPLETE

### Dashboard 1: LLM & GPU Monitor — Final Layout

```
  [10] LLM Overview                            y=0  h=1
  [ 1-6] Stats row                              y=1  h=5
  [11] Model Breakdown                          y=6  h=1
  [ 7-9] Model panels                           y=7  h=8
  [26] Key Usage                                y=15 h=1
  [27-31] Key stats                             y=16 h=5
  [32-34] Key bar charts                        y=21 h=8
  [35-36] Budget utilization + status           y=29 h=8
  [37-38] Spend/requests over time              y=37 h=6
  [39] Key Detail Table                         y=43 h=8
  [12] GPU Metrics (Matrix)                     y=51 h=1
  [13-17] GPU stats + over time                 y=52 h=8
  [18-19] Prompt rate + LLM latency             y=60 h=6
  [20-21] Input/output tokens over time         y=66 h=6
  Total height: 72 rows
```

### Dashboard 2: Homelab Overview — Final Layout

```
  [ 1] Servers                                  y=0  h=1
  [ 2-4] Server stats                           y=1  h=5
  [ 5-6] CPU/Memory over time                   y=6  h=7
  [ 7] Services                                 y=13 h=1
  [ 8] Container Overview                       y=14 h=12
  [10] LLM Metrics                              y=36 h=1
  [11-16] LLM panels                            y=37 h=5
  [26] API Keys                                 y=43 h=1
  [27-31] Key stats                             y=44 h=5
  [32] Top 3 Spend by Key (30d)                 y=49 h=7
  [17] GPU Metrics                              y=56 h=1
  [18-22] GPU stats                             y=57 h=7
  [23-25] GPU over time + ROI                   y=64 h=7
  Total height: 71 rows
```

Both JSON files validated as well-formed JSON. Grafana will pick up the changes on next dashboard refresh.

---