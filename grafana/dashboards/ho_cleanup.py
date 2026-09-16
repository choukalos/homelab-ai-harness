#!/usr/bin/env python3
"""Homelab Overview cleanup pass (2026-09-16).

1. Servers row: add per-host Disk Usage % + Disk Available stats (CPU-style).
2. LLM Metrics row -> "AI Usage": replace detailed by-model panels with
   overview stats (Total $ Spend, Total Tokens, Avg Latency, Failed Requests)
   + Requests by user over time. (By-model detail lives in AI Work & Spend.)
3. API Keys row: drop the two dead budget panels (litellm_api_key_max_budget_metric
   no longer emits; litellm_remaining_api_key_budget_metric is all +Inf).
4. Reflow all rows to fix the overlap bug (Cached Tokens panel sat on top of
   the Container Overview table).
"""
import copy, json

PATH = "/home/chuck/homelab/grafana/dashboards/homelab-overview.json"
d = json.load(open(PATH))
by_id = {p.get("id"): p for p in d["panels"]}

DISK_FS = 'fstype!~"tmpfs|overlay|squashfs|cifs|rootfs|iso9660|vfat", device!~"loop.*"'
THRESH = lambda steps: {"mode": "absolute", "steps": steps}
G = {"color": "green", "value": None}

def stat(template, pid, title, expr, unit, x, w, y=1, h=5,
         thresholds=None, decimals=None, legend="{{instance}}"):
    p = copy.deepcopy(by_id[template])
    p["id"] = pid
    p["title"] = title
    p["gridPos"] = {"h": h, "w": w, "x": x, "y": y}
    p["targets"] = [{"expr": expr, "legendFormat": legend, "refId": "A"}]
    fc = p["fieldConfig"]["defaults"]
    fc["unit"] = unit
    fc["color"] = {"mode": "thresholds"}
    if thresholds is not None:
        fc["thresholds"] = thresholds
    if decimals is not None:
        fc["decimals"] = decimals
    return p

def ts(template, pid, title, expr, x, w, y, h, legend):
    p = copy.deepcopy(by_id[template])
    p["id"] = pid
    p["title"] = title
    p["gridPos"] = {"h": h, "w": w, "x": x, "y": y}
    p["targets"] = [{"expr": expr, "legendFormat": legend, "refId": "A"}]
    p["fieldConfig"]["defaults"]["unit"] = "short"
    return p

# ---------- 1. Servers row: disk stats ----------
disk_usage = stat(3, 40, "Disk Usage %",
    f"100 * (1 - (sum by (instance) (node_filesystem_avail_bytes{{{DISK_FS}}}) / "
    f"sum by (instance) (node_filesystem_size_bytes{{{DISK_FS}}})))",
    "percent", 15, 5,
    thresholds=THRESH([G, {"color": "yellow", "value": 80}, {"color": "red", "value": 90}]))
disk_avail = stat(3, 41, "Disk Available",
    f"sum by (instance) (node_filesystem_avail_bytes{{{DISK_FS}}})",
    "bytes", 20, 4)

# ---------- 2. LLM row -> AI Usage ----------
ai_spend = stat(3, 42, "Total $ Spend (range)",
    "sum(increase(litellm_spend_metric_total[$__range]))",
    "currencyUSD", 0, 6, y=14, decimals=2, legend="")
ai_tokens = stat(3, 43, "Total Tokens (range)",
    "sum(increase(litellm_input_tokens_metric_total[$__range]) + "
    "increase(litellm_output_tokens_metric_total[$__range]))",
    "short", 6, 6, y=14, legend="")
ai_latency = stat(3, 44, "Avg Latency (range)",
    "sum(rate(litellm_request_total_latency_metric_sum[$__range])) / "
    "sum(rate(litellm_request_total_latency_metric_count[$__range]))",
    "s", 12, 6, y=14, decimals=2, legend="",
    thresholds=THRESH([G, {"color": "yellow", "value": 15}, {"color": "red", "value": 30}]))
ai_failed = stat(3, 45, "Failed Requests (range)",
    "sum(increase(litellm_proxy_failed_requests_metric_total[$__range]))",
    "short", 18, 6, y=14, legend="")
ai_req_user = ts(5, 46, "AI requests by user over time (5m)",
    "sum by (user) (increase(litellm_proxy_total_requests_metric_total[5m]))",
    0, 24, 19, 8, "{{user}}")

# ---------- 3. Drop dead + replaced panels ----------
DROP = {11, 12, 13, 14, 15, 16, 33, 34, 28, 30}
panels = []
for p in d["panels"]:
    if p.get("id") in DROP:
        continue
    if p.get("id") is None and p.get("title") == "Cached Tokens (per-user)":
        continue
    panels.append(p)

# ---------- 4. Reposition ----------
def pos(pid, y=None, x=None, w=None, h=None):
    gp = by_id[pid]["gridPos"]
    if y is not None: gp["y"] = y
    if x is not None: gp["x"] = x
    if w is not None: gp["w"] = w
    if h is not None: gp["h"] = h

# Servers row: 5 stats (w=5,5,5,5,4)
pos(2, y=1, x=0, w=5); pos(3, y=1, x=5, w=5); pos(4, y=1, x=10, w=5)
pos(5, y=6, x=0, w=12); pos(6, y=6, x=12, w=12)
# LLM row
by_id[10]["title"] = "AI Usage"
pos(10, y=13)
# Services row: fix overlap (was y=25, table y=26)
pos(7, y=27); pos(8, y=28)
# API Keys row: 3 surviving stats at w=8
pos(26, y=40)
pos(27, y=41, x=0, w=8); pos(29, y=41, x=8, w=8); pos(31, y=41, x=16, w=8)
pos(32, y=46, x=0, w=24, h=7)
# GPU row
pos(17, y=53)
for pid in (18, 19, 20, 21): pos(pid, y=54)
pos(22, y=54, x=16, w=8)
pos(23, y=61, x=0, w=8); pos(24, y=61, x=8, w=8); pos(25, y=61, x=16, w=8)

# Append new panels
panels += [disk_usage, disk_avail, ai_spend, ai_tokens, ai_latency, ai_failed, ai_req_user]

d["panels"] = panels
json.dump(d, open(PATH, "w"), indent=1)
print(f"wrote {PATH} ({len(panels)} panels)")