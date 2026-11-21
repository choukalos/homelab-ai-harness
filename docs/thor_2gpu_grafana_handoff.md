# Thor Handoff — Matrix 2-GPU (Grafana / Prometheus)

> Created 2026-11-14 (add_card_plan.md Phase 2). Matrix now has **two GPUs**:
> GPU 0 = RTX PRO 5000 72 GB Blackwell (daily LLM, vLLM `qwen38`),
> GPU 1 = RTX PRO 4000 24 GB Blackwell (media pipeline XOR Ollama copywriter,
> `device_ids: ['1']`).
>
> **Status: DONE 2026-11-21** — all three steps below verified from thor.

## What changed on Matrix

- dcgm-exporter (`:9400`) now exports the full DCGM field set **per GPU index**
  (`gpu="0"` / `gpu="1"` labels): util, `FB_USED`/`FB_FREE` (VRAM), power, temp,
  clocks, XID errors.
- No exporter config change — `NVIDIA_VISIBLE_DEVICES=all` already covers both.

## What Thor needed to do

### 1. Prometheus — nothing to change ✅

The existing `matrix:9400` scrape target automatically picked up the new
per-GPU series. **Verified 2026-11-21:** `DCGM_FI_DEV_GPU_UTIL` and
`DCGM_FI_DEV_FB_USED` (and POWER_USAGE / GPU_TEMP / XID_ERRORS) each return
two series in VictoriaMetrics — `gpu="0"`
(`modelName="NVIDIA RTX PRO 5000 72GB Blackwell"`) and `gpu="1"`
(`modelName="NVIDIA RTX PRO 4000 Blackwell"`), job `dcgm-matrix`,
instance `matrix`.

### 2. Grafana — 2-GPU dashboard ✅

`docs/thor_2gpu_grafana_dashboard.json` (this repo) — **imported 2026-11-21**
and provisioned from `grafana/dashboards/matrix-2gpu.json` (uid
`matrix-2gpu`, `/d/matrix-2gpu`), so it survives Grafana restarts like the
other dashboards. Datasource: Prometheus (`PBFA97CFB590B2093` →
`victoria-metrics:8428`), via the `DS_PROMETHEUS` variable. Panels:

| Panel | Query (per GPU) |
|---|---|
| GPU Utilization % | `DCGM_FI_DEV_GPU_UTIL{instance=~"matrix.*"}` |
| VRAM Used (MiB) | `DCGM_FI_DEV_FB_USED{instance=~"matrix.*"}` |
| Power (W) | `DCGM_FI_DEV_POWER_USAGE{instance=~"matrix.*"}` |
| Temperature (°C) | `DCGM_FI_DEV_GPU_TEMP{instance=~"matrix.*"}` |
| XID Errors (stat) | `DCGM_FI_DEV_XID_ERRORS{instance=~"matrix.*"}` (0 = healthy) |

Legends: GPU 0 = "RTX PRO 5000 — daily LLM", GPU 1 = "RTX PRO 4000 —
media/copywriter". All 5 panel queries verified live through the Grafana
query API (2 series each, 2026-11-21).

### 3. Existing single-GPU panels — fixed ✅

Audited every provisioned dashboard for `DCGM_FI_DEV_*` queries without a
`gpu` matcher (2026-11-21):

- **NVIDIA DCGM Exporter Dashboard** (`Oxed_c6Wz`) — already parameterized
  with a `gpu` template variable (default All); no change.
- **Homelab Overview** (`homelab-overview.json`) — panels 18–25 (util, temp,
  VRAM, power, over-time, ROI) now carry per-GPU legends
  (`GPU {{gpu}}`, `GPU {{gpu}} — Used`, …).
- **AI Work & Spend** (`ai-work-spend.json`) — panels 43/44 (power, util) now
  `GPU {{gpu}} (W)` / `GPU {{gpu}} (%)`; power panel description updated to
  name both cards.

## Not in this handoff

- **No LiteLLM change** — the `qwen38-27b` alias on `:8000` is unchanged (GPU 0).
- The **copywriter alias** (`matrix-copywriter`, gemma4:31b on `:11434`) is a
  Phase 3/4 item — separate handoff when it lands. Note for that time:
  gemma4:31b is a **reasoning model** — short `num_predict`/max-tokens budgets
  return empty content (the text lands in the `thinking` field); the alias
  needs a generous output budget.

## Verification (from Thor)

```bash
curl -s 'http://matrix:9400/metrics' | grep -E '^DCGM_FI_DEV_(GPU_UTIL|FB_USED)'
# expect 4 lines: gpu="0"/gpu="1" × util/FB_USED  (verified 2026-11-21)
```
