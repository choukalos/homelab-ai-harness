# Kill the 524s: raise Cloudflare proxy read timeout for llm.choukalos.com

- slug: tier1-cloudflare-524-read-timeout
- date: 2026-11-19
- status: open
- tier: 1
- target user: chuck
- source: workspace/ideas/2026-11-17-media-pipeline-improvements.md (A1) + autonomous_agents_ideas.md §6.12 (Phase 1 exit criterion)

## What
1. Raise the Cloudflare **Proxy Read Timeout** for the `llm.choukalos.com` zone to ≥300 s (zone-wide, or per-path for `/v1/chat/completions` if the zone supports it).
2. Optionally also make long generations stream (the CF read timeout applies to gaps between bytes, not total time — streaming turns a 150 s generation into small chunks and the 524 disappears). Streaming is client/proxy-side; the timeout raise is the reliable fix and should land regardless.

## Why (evidence)
- 2026-11-16/17 SW Holiday Spoof run: **11 of 36 shot-director children died on `524 origin_response_timeout` (120 s)** in one wave (23:54–00:15Z). Each first turn = read ~150 KB + write a card, which takes >120 s on a loaded origin. The 524 is retryable but the *run* dies; cards were sometimes written before the death (work done, run failed).
- Cost: 11 manual retries, ~90 min of parent attention, production started with missing cards.
- `autonomous_agents_ideas.md` §6.12 now makes this a **Phase 1 exit criterion**: long worker turns behind `llm.choukalos.com` die on the 120 s read timeout, and unattended headless board workers are not trustworthy until it lands.
- Still open as of 2026-11-19 (no repo/config change; CF zone settings are not in this repo).

## Risk + rollback
Low. A longer read timeout only changes how long Cloudflare waits on the origin. Rollback = set back to 120 s.

## Files touched
- Cloudflare zone config for `llm.choukalos.com` (not in repo). `.env` has `CF_ACCOUNT_ID`/`CF_TUNNEL_*` (tunnel token only — zone settings need a CF API token with zone:settings permission, or a manual dashboard change).
- `docs/thor_public_access_model.md` — note the new timeout after the change.

---
_Drafted 2026-11-19 (pi, thor) from the workspace/ideas review. Review with `cli/proposals.sh`; applying is a human decision._
