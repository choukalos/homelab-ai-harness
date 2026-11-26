# Todo — P12-B/C file-bridge deploy (SEC-12)

- date: 2026-11-26
- status: open (P12-B/C implemented + verified 2026-11-26 — pending commit/deploy;
  queued behind chuck's other running job; deploy requires a litellm-proxy
  restart, which severs active proxy sessions — schedule deliberately)
- source: P12-B (board idea 29) + P12-C (board idea 30) of `security_todo.md`
  Phase 12; implemented by pi-long-task 2026-11-26 (run
  `tmp/pi-long-task/2026-11-26T19-07-07-203Z-10f37f65/`)
- companions: `docs/filebridge_p12bc_deploy.md` (the runbook — exact commands +
  rollback anchors A–E), `docs/filebridge_p12bc.md` (design doc incl. the 1b
  media-pipeline compatibility confirmation), `docs/filebridge_p12bc_final_report.md`
  (test evidence), `security_todo.md` Phase 12 (P12-B/P12-C lines =
  implemented-pending-deploy)

## What the deploy does

Brings the P12-B/C work live on thor:

1. Recreate `mcp_filebridge` (new image: MCP face at `POST /mcp`, 5 tools,
   full registry + boot lint, 1b path-bound TTL tokens at
   `/media/files/dl/{token}`, publish engine + `POST /publish`).
2. Restart `litellm-proxy` (applies the `mcp_filebridge` entry in
   `litellm/config.yml` mcp_servers — the tools become visible to agents).
   **Severs active proxy sessions — pick the timing.**
3. Update the family-mcp-full access group (fetch-union-PUT — verified
   against litellm v1.104.0 source) so the chuck/dylan keys can see the new
   server.
4. Recreate `skill-runner` (the `publish-file` skill is now a thin wrapper
   over the bridge's `POST /publish`).
5. Public E2E battery (token route via Caddy — the existing
   `handle /media/files/*` route already exposes it, no Caddyfile change —
   plus the full P12-A regression battery + kill switch + `ss` port diff).

## Checklist

- [ ] Commit + push the P12-B/C working-tree changes (done 2026-11-26 —
      see git log; this todo file rides in that commit)
- [ ] Read `docs/filebridge_p12bc_deploy.md` end-to-end (rollback anchors A–E)
- [ ] Pick a litellm-restart window (severs active proxy sessions)
- [ ] Step 1: build + recreate `mcp_filebridge` (env gate 0, healthy,
      ai-net smoke incl. `POST /mcp` initialize)
- [ ] Step 2: restart `litellm-proxy` (config applies; verify
      `mcp_filebridge` in the proxy's MCP server list)
- [ ] Step 3: access-group update (exact command in the runbook; verify
      chuck key sees `mcp_filebridge-*` tools via litellm tools/list)
- [ ] Step 4: recreate `skill-runner`; verify `publish-file` wrapper E2E
      (publish a test file via the skill → 200 + URL + sha256; duplicate
      no-op)
- [ ] Step 5: public E2E battery (1b token: mint → public fetch 200 +
      sha256, bad token 404; P12-A regression: dl relay sha256, Range 206,
      upload 401/401/200, /media/files policy both hosts; kill switch;
      `ss -tlnp` diff — no new host port)
- [ ] Mark `security_todo.md` Phase 12 P12-B/P12-C lines DONE + live
      (replace "PENDING DEPLOY")
- [ ] Kanban: close ideas 29/30 (P12-B/P12-C) — create task + mark done,
      or move ideas to done with the evidence note
- [ ] Retire this file (move to archive per docs-housekeeping)

## Rollback (summary — full anchors in the runbook)

- A: rebuild the bridge image from the pre-P12-B/C commit + recreate
- B: revert the `litellm/config.yml` mcp_servers entry + restart
- C: access-group revert (the PUT is full-replacement — the runbook carries
  the pre-change snapshot)
- D: skill-runner recreate from the pre-change image (the wrapper has no
  fallback — if the bridge is down, the skill fails loudly by design)
- E: the 1b token route is additive (no Caddy rollback needed); Face 1
  behavior is unchanged by the new image (regression battery proves it)

## Notes

- Live state before deploy: `mcp_filebridge` runs the P12-A image
  (`POST /mcp` → 404); litellm + caddy untouched.
- Side-container E2E already passed 43/43 (see final report) — the deploy
  battery is the live confirmation.
- NAS: `published/` dir exists (chuck:chuck 755, write-verified);
  `@Recently-Snapshot` (102B) still on the NAS — CIFS read-only from thor,
  optional manual cleanup from the NAS admin UI (`docs/nas_cleanup_2026-11-26.md`).
