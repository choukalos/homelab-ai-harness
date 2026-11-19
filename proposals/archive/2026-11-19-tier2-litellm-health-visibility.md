# LiteLLM model health: Grafana dashboard + /health outage poller

- slug: tier2-litellm-health-visibility
- date: 2026-11-19
- status: applied
- tier: 2
- applied: 2026-11-19 (pi, thor) — dashboard `grafana/dashboards/litellm-model-health.json`
  (7 panels, provisioned, all queries verified live against VictoriaMetrics —
  metric names adjusted to live reality: uptime % uses success_responses, p95
  latency/TTFT + token throughput grouped by requested_model since histograms
  lack model_group) + 5-min outage poller skill `skills/litellm_health_check/`
  (schedule `litellm-health-check`, */5 * * * *) alerting via the public briefs
  drop-zone. Verified live: scheduler fired on schedule, alert surfaced the real
  macstudio outage (https://choukalos.com/files/briefs/litellm-health-alert.md),
  healthy branch + recovery verified via mock tests; alert auto-removes when healthy.
- target user: chuck
- source: workspace/ideas/2026-11-17-litellm-model-info-and-uptime.md (Group 2c/2d)

## What
The scrape side is already working — verified live 2026-11-19: `/metrics/` returns 200 unauthenticated (the 401 issue from the 2026-11-17 audit no longer reproduces), `up{job="litellm"}=1` in VictoriaMetrics, `litellm-proxy` container healthy. What's missing is **visibility and alerting**:

1. **Grafana dashboard "LiteLLM Model Health"** (provisioned under `grafana/dashboards/`), MetricsQL on the existing metrics (filter `model_group != ""` to exclude MCP rows):
   - Uptime % (5m): `1 - sum by (model_group) (increase(litellm_deployment_failure_responses_total[5m])) / sum by (model_group) (increase(litellm_deployment_total_requests_total[5m]))`
   - Request rate: `sum by (model_group) (rate(litellm_deployment_total_requests_total[5m]))`
   - p95 latency: `histogram_quantile(0.95, sum by (le, model_group) (rate(litellm_llm_api_latency_metric_bucket[5m])))`
   - p95 TTFT: `histogram_quantile(0.95, sum by (le, model_group) (rate(litellm_llm_api_time_to_first_token_metric_bucket[5m])))`
   - In-flight: `sum(litellm_in_flight_requests)`
   - Proxy uptime: `time() - process_start_time_seconds`
   - Token throughput: `sum by (model_group) (rate(litellm_total_tokens_metric_total[5m]))`
2. **Outage alerting without traffic.** Metrics only show health when requests flow. Add a small scheduled job (`scheduler/` + `schedules.json`) calling `GET /health` with a key every 5 min, alerting via the existing notify path when `unhealthy_endpoints` is non-empty. This is what would have surfaced the macstudio outage immediately instead of days later.

Note (no action now): request metrics carry `client_ip` / `user_agent` / `hashed_api_key` labels — bounded for a single-user homelab with VM's retention, but watch series growth if new clients/agents appear (dashboard queries already aggregate by `model_group`).

## Why (evidence)
- The macstudio OMLX outage (dead since at least 2026-11-17, verified down 2026-11-19) was only discovered by accident via a manual `/health` call — nothing alerts on a dead upstream when no traffic flows through it.
- "Only 13 failed 500s buried in metrics" was the full extent of the signal for a week-long dead backup LLM.

## Risk + rollback
Low; internal-only, no public surface change. Rollback = remove the dashboard file / schedule entry.

## Files touched
- `grafana/dashboards/litellm-model-health.json` (new)
- `scheduler/schedules.json` (+ the poller job under `scheduler/`)

---
_Drafted 2026-11-19 (pi, thor) from the workspace/ideas review. Review with `cli/proposals.sh`; applying is a human decision._
