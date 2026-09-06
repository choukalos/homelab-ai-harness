#!/usr/bin/env python3
"""Generate the 'AI Work & Spend' Grafana dashboard.

Cost model (v2.2, see /home/chuck/homelab/METRICS.md "Media Work Metering
(v2)" — the old plan file thor_media_work.md was completed + deleted
2026-09-09):
  LLM $   = litellm_spend_metric_total  (per user; includes pipeline storyboard
              LLM, which routes through LiteLLM with the user's key)
  Media $ = media_cost_usd_total        (per user/stage; full cost:
              electricity + GPU amortization, work-unit pricing)
  Total work $ = LLM $ + Media ${stage != "storyboard"}
              (storyboard LLM is already inside LLM $ — excluded from media
               to avoid double counting; the pipeline's storyboard cost
               remains visible in Row 2 as a cross-check)
"""
import json

DS = {"type": "prometheus", "uid": "${DS_PROMETHEUS}"}
SCHEMA = 39

# ---------------------------------------------------------------- helpers
def stat(pid, title, expr, unit="currencyUSD", w=6, x=0, y=0, legend="A",
         decimals=4, thresholds=None, desc=None):
    p = {
        "id": pid, "title": title, "type": "stat", "datasource": DS,
        "gridPos": {"h": 5, "w": w, "x": x, "y": y},
        "targets": [{"expr": expr, "legendFormat": legend, "refId": "A"}],
        "fieldConfig": {"defaults": {
            "unit": unit, "decimals": decimals,
            "thresholds": {"mode": "absolute", "steps": [
                {"color": "green", "value": None}]},
            "color": {"mode": "thresholds"},
        }},
        "options": {"colorMode": "background", "graphMode": "area",
                    "justifyMode": "auto", "orientation": "auto",
                    "reduceOptions": {"calcs": ["lastNotNull"], "fields": "",
                                      "values": False}, "textMode": "auto"},
    }
    if thresholds:
        p["fieldConfig"]["defaults"]["thresholds"] = thresholds
    if desc:
        p["description"] = desc
    return p


def ts(pid, title, targets, unit="short", w=12, x=0, y=0, desc=None,
       fill="0.1"):
    p = {
        "id": pid, "title": title, "type": "timeseries", "datasource": DS,
        "gridPos": {"h": 8, "w": w, "x": x, "y": y},
        "targets": targets,
        "fieldConfig": {"defaults": {
            "unit": unit, "custom": {"fillOpacity": int(float(fill) * 100),
                                      "lineWidth": 2, "spanNulls": False},
            "thresholds": {"mode": "absolute", "steps": [
                {"color": "green", "value": None}]},
            "color": {"mode": "palette"},
        }},
        "options": {"legend": {"displayMode": "list", "placement": "bottom",
                               "calcs": []}, "tooltip": {"mode": "multi"}},
    }
    if desc:
        p["description"] = desc
    return p


def row(pid, title, y, desc=None):
    p = {"id": pid, "type": "row", "title": title, "collapsed": False,
         "gridPos": {"h": 1, "w": 24, "x": 0, "y": y}, "panels": []}
    if desc:
        p["description"] = desc
    return p


def tgt(expr, legend, ref):
    return {"expr": expr, "legendFormat": legend, "refId": ref}


# ---------------------------------------------------------------- queries
LLM_SPEND = 'sum(increase(litellm_spend_metric_total{user=~"$user"}[$__range]))'
LLM_IN = 'sum(increase(litellm_input_tokens_metric_total{user=~"$user"}[$__range]))'
LLM_OUT = 'sum(increase(litellm_output_tokens_metric_total{user=~"$user"}[$__range]))'
LLM_REQ = ('sum(increase(litellm_proxy_total_requests_metric_total'
           '{user=~"$user", route="/v1/chat/completions"}[$__range]))')
MEDIA_COST = 'sum(increase(media_cost_usd_total{user=~"$user"}[$__range]))'
MEDIA_JOBS = ('sum(increase(media_jobs_total{user=~"$user", status="done"}'
              '[$__range]))')
MEDIA_TOK = 'sum(increase(media_tokens_total{user=~"$user"}[$__range]))'
# Total work $: LLM (incl. storyboard) + media excluding storyboard (no double count).
# `or` fallback: while media_cost_usd_total doesn't exist yet (Matrix v2 not
# shipped), the A+B vector op yields empty — `or A` keeps the panel alive with
# the LLM-only value. Drop the fallback once media metrics are live (optional;
# it is a no-op then).
TOTAL_RANGE = (f'({LLM_SPEND} + '
               'sum(increase(media_cost_usd_total{user=~"$user", stage!="storyboard"}[$__range]))) '
               f'or {LLM_SPEND}')
TOTAL_BY_USER_RANGE = (
    '(sum by (user) (increase(litellm_spend_metric_total[$__range])) + '
    'sum by (user) (increase(media_cost_usd_total{stage!="storyboard"}[$__range]))) '
    'or sum by (user) (increase(litellm_spend_metric_total[$__range]))')
TOTAL_BY_USER_5M = (
    '(sum by (user) (increase(litellm_spend_metric_total[5m])) + '
    'sum by (user) (increase(media_cost_usd_total{stage!="storyboard"}[5m]))) '
    'or sum by (user) (increase(litellm_spend_metric_total[5m]))')
GPU_USD_EST = ('($__range_s / 3600) * ($GPU_AVG_W / 1000) * $ELEC_USD_PER_KWH')
GPU_USD_RANGE = ('(sum(avg_over_time(DCGM_FI_DEV_POWER_USAGE{instance="matrix"}[$__range])) '
                 '/ 1000 * ($__range_s / 3600) * $ELEC_USD_PER_KWH) '
                 f'or ({GPU_USD_EST})')
PAYBACK = (f'((sum(increase(litellm_spend_metric_total[$__range])) + '
           f'sum(increase(media_cost_usd_total' + '{stage!=\"storyboard\"}' + '[$__range]))) '
           f'or sum(increase(litellm_spend_metric_total[$__range]))) '
           f'/ {GPU_USD_RANGE}')

# ---------------------------------------------------------------- panels
panels = []

# --- Row 1: LLM
panels.append(row(1, "LLM — via LiteLLM proxy (per user)", 1,
                  "litellm_spend_metric_total is the canonical LLM cost source: "
                  "it is per-user (user label from /key/info) and includes the "
                  "pipeline storyboard LLM, which routes through the proxy with "
                  "the caller's key. vLLM engine metrics below are operational "
                  "cross-checks only (engine-wide, not per-user) — never sum "
                  "vllm:*_tokens into $ totals."))
panels.append(stat(10, "LLM spend (range)", LLM_SPEND, w=6, x=0, y=2,
                   desc="All LLM work billed through the proxy, selected users."))
panels.append(stat(11, "LLM input tokens (range)", LLM_IN, unit="short",
                   w=6, x=6, y=2, decimals=0))
panels.append(stat(12, "LLM output tokens (range)", LLM_OUT, unit="short",
                   w=6, x=12, y=2, decimals=0))
panels.append(stat(13, "LLM chat requests (range)", LLM_REQ, unit="short",
                   w=6, x=18, y=2, decimals=0))
panels.append(ts(14, "LLM spend by user (5m)",
                 [tgt('sum by (user) (increase(litellm_spend_metric_total[5m]))',
                      "{{user}}", "A")], unit="currencyUSD", w=12, x=0, y=7,
                 desc="Per-user LLM spend rate. Storyboard LLM shows up here "
                      "(model qwen38-27b) — that is why Row 3 excludes "
                      "stage=storyboard from the media side."))
panels.append(ts(15, "vLLM engine tokens (operational cross-check)",
                 [tgt('sum(increase(vllm:prompt_tokens_total{instance="matrix"}[5m]))',
                      "prompt", "A"),
                  tgt('sum(increase(vllm:generation_tokens_total{instance="matrix"}[5m]))',
                      "generation", "B")],
                 unit="short", w=12, x=12, y=7,
                 desc="Engine-wide (all users incl. non-proxy work). Should "
                      "roughly track the LiteLLM token panels; divergence = "
                      "work bypassing the proxy."))

# --- Row 2: Media
panels.append(row(2, "Media — pipeline metering (per user)", 15,
                  "Work-unit pricing (steps×MP, frames×MP, audio-seconds) × "
                  "calibrated rates = full cost (electricity + GPU "
                  "amortization). Panels light up once Matrix ships the "
                  "pipeline /metrics endpoint (media_up = 1)."))
panels.append(stat(20, "Media cost (range)", MEDIA_COST, w=6, x=0, y=16,
                   desc="All media stages incl. storyboard LLM cost as "
                        "measured by the pipeline (cross-check vs Row 1)."))
panels.append(stat(21, "Media jobs done (range)", MEDIA_JOBS, unit="short",
                   w=6, x=6, y=16, decimals=0))
panels.append(stat(22, "Media LLM tokens (range)", MEDIA_TOK, unit="short",
                   w=6, x=12, y=16, decimals=0,
                   desc="storyboard stage only (kind=prompt|completion)."))
panels.append(stat(23, "Metering online", "media_up", unit="short", w=6, x=18,
                   y=16, decimals=0,
                   thresholds={"mode": "absolute", "steps": [
                       {"color": "red", "value": None},
                       {"color": "green", "value": 1}]},
                   desc="1 = pipeline /metrics endpoint up (Matrix v2 "
                        "metering live)."))
panels.append(ts(24, "Media cost by user & stage (5m)",
                 [tgt('sum by (user, stage) (increase(media_cost_usd_total[5m]))',
                      "{{user}} / {{stage}}", "A")],
                 unit="currencyUSD", w=12, x=0, y=21))
panels.append(ts(25, "Media work units by user & kind (5m)",
                 [tgt('sum by (user, kind) (increase(media_work_units_total[5m]))',
                      "{{user}} / {{kind}}", "A")],
                 unit="short", w=12, x=12, y=21,
                 desc="mpix_steps (images), mpix_frames (video), "
                      "audio_seconds (TTS/music/SFX)."))

# --- Row 3: Total work $
panels.append(row(3, "Total work $ (LLM + media, by user)", 29,
                  "Total work $ = litellm_spend (all LLM, per user) + "
                  "media_cost{stage != storyboard}. The storyboard LLM is "
                  "already inside litellm_spend (routed via the proxy with the "
                  "user's key) — excluding it from the media side avoids "
                  "double counting. If the pipeline ever stops routing "
                  "storyboard through LiteLLM, drop the stage filter."))
panels.append(stat(30, "Total work $ (range)", TOTAL_RANGE, w=8, x=0, y=30,
                   desc="Everything the AI stack produced, priced."))
panels.append(ts(31, "Total work $ by user (range)",
                 [tgt(TOTAL_BY_USER_RANGE, "{{user}}", "A")],
                 unit="currencyUSD", w=8, x=8, y=30,
                 desc="Bar-style: use a barchart view for a per-user split."))
panels[ -1]["type"] = "barchart"
panels.append(ts(32, "Total work $ by user (5m rate)",
                 [tgt(TOTAL_BY_USER_5M, "{{user}}", "A")],
                 unit="currencyUSD", w=8, x=16, y=30))

# --- Row 4: GPU $ & payback
panels.append(row(4, "GPU $ & payback", 38,
                  "Denominator uses MEASURED DCGM power (avg over range) "
                  "since the DCGM fix (2026-09-09); falls back to the "
                  "GPU_AVG_W estimate if no samples in range."))
panels.append(stat(40, "GPU $ (range, measured)", GPU_USD_RANGE, w=6, x=0, y=39,
                   desc="avg_over_time(DCGM_FI_DEV_POWER_USAGE) × range × "
                        "ELEC_USD_PER_KWH; falls back to GPU_AVG_W estimate."))
panels.append(stat(41, "GPU amortization $/h",
                   "$GPU_COST_USD / $GPU_LIFETIME_HOURS", w=6, x=6, y=39,
                   desc="$4,000 GPU / 5 yr (43,800 h) = $0.0913/h."))
panels.append(stat(42, "Payback ratio (range)", PAYBACK, unit="none",
                   w=6, x=12, y=39,
                   desc="Total work $ / GPU $. >1 = the AI work in the range "
                        "out-earned the GPU's cost (at retail LLM rates)."))
panels.append(ts(43, "GPU power (DCGM)",
                 [tgt('DCGM_FI_DEV_POWER_USAGE{instance="matrix"}', "W", "A")],
                 unit="watt", w=12, x=18, y=39,
                 desc="Live since the DCGM fix (2026-09-09). Idle ≈ 14 W; "
                      "spikes to ~300 W under diffusion/audio load."))
panels.append(ts(44, "GPU util (DCGM)",
                 [tgt('DCGM_FI_DEV_GPU_UTIL{instance="matrix"}', "%", "A")],
                 unit="percent", w=12, x=0, y=47))

# --- Row 5: Pipeline operational
panels.append(row(5, "Pipeline operational", 55,
                  "Queue/active/duration from the pipeline metering endpoint. "
                  "max_concurrent=1, max_queue=5."))
panels.append(stat(50, "Queue depth", "media_queue_depth", unit="short",
                   w=6, x=0, y=56, decimals=0))
panels.append(stat(51, "Active jobs", "media_jobs_active", unit="short",
                   w=6, x=6, y=56, decimals=0))
panels.append(ts(52, "Job duration avg by stage (5m)",
                 [tgt('sum by (stage) (rate(media_job_duration_seconds_sum[5m])) '
                      '/ sum by (stage) (rate(media_job_duration_seconds_count[5m]))',
                      "{{stage}}", "A")],
                 unit="s", w=12, x=12, y=56))
panels.append(ts(53, "Jobs by status (5m)",
                 [tgt('sum by (status) (increase(media_jobs_total[5m]))',
                      "{{status}}", "A")],
                 unit="short", w=12, x=0, y=64))

# ---------------------------------------------------------------- dashboard
dash = {
    "annotations": {"list": []},
    "editable": True,
    "fiscalYearStartMonth": 0,
    "graphTooltip": 1,
    "id": None,
    "links": [],
    "liveNow": False,
    "panels": panels,
    "refresh": "30s",
    "schemaVersion": SCHEMA,
    "tags": ["ai", "cost", "llm", "media", "gpu"],
    "templating": {"list": [
        {"name": "DS_PROMETHEUS", "label": "Datasource", "type": "datasource",
         "query": "prometheus", "current": {}, "hide": 0},
        {"name": "user", "label": "User", "type": "query",
         "datasource": DS,
         "query": "label_values(litellm_spend_metric_total, user)",
         "refresh": 2, "includeAll": True, "multi": True,
         "current": {"text": "All", "value": "$__all"}, "hide": 0},
        {"name": "ELEC_USD_PER_KWH", "label": "Elec $/kWh", "type": "constant",
         "query": "0.15", "current": {"text": "0.15", "value": "0.15"},
         "hide": 1},
        {"name": "GPU_AVG_W", "label": "GPU avg W (est.)", "type": "constant",
         "query": "200", "current": {"text": "200", "value": "200"}, "hide": 1},
        {"name": "GPU_COST_USD", "label": "GPU cost $", "type": "constant",
         "query": "4000", "current": {"text": "4000", "value": "4000"},
         "hide": 1},
        {"name": "GPU_LIFETIME_HOURS", "label": "GPU lifetime h",
         "type": "constant", "query": "43800",
         "current": {"text": "43800", "value": "43800"}, "hide": 1},
    ]},
    "time": {"from": "now-1h", "to": "now"},
    "timepicker": {},
    "timezone": "browser",
    "title": "AI Work & Spend",
    "uid": "ai-work-spend",
    "version": 1,
    "weekStart": "",
}

out = "/home/chuck/homelab/grafana/dashboards/ai-work-spend.json"
with open(out, "w") as f:
    json.dump(dash, f, indent=1)
print(f"wrote {out} ({len(panels)} panels)")