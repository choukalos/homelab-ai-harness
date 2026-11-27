---
name: security-review
description: Light any-change pre-push security checklist for the homelab — run the deterministic scanner (secrets in the diff, secret-ish file permissions, untagged compose images) plus the judgement checks (auth surface — who can reach a new endpoint, compose env interpolation, mounted-config reload). Use before pushing any branch or publishing any change in the homelab repo. The deep code-vulnerability pass is security-code-review (S11, the kanban QA hard gate); this is the quick checklist for ANY change, including docs and config.
---

# Security Review (S6) — the light any-change checklist

The fast security pass before pushing or publishing a change in the homelab
repo. Complements `security-code-review` (S11) — S11 is the deep
code-vulnerability review (OWASP Top 10, the kanban QA hard gate); this is the
30-second any-change checklist, including docs, config, and compose changes
that S11 never sees.

## Step 1 — run the deterministic scanner

```bash
cd /home/chuck/homelab
python3 agents-skills/security-review/tools/pre_push_security_check.py          # staged diff
python3 agents-skills/security-review/tools/pre_push_security_check.py --working # working tree
```

It checks (same pattern set as `.githooks/pre-commit`):
- **secrets in added lines** — `sk-…` / `ghp_…` / `AKIA…` / Slack / private-key
  blocks / Basic-auth blobs + high-entropy literals assigned to secret-looking
  variable names
- **permissions** — new secret-ish files must be `600` (the presenton
  `userConfig.json` lesson: a world-readable credentials file is a leak)
- **image pinning** — `image: <name>` without a version tag in compose files
  (housekeeping H1: untagged images drift silently)

`blocker` findings: fix before pushing (a secret in the diff must come out —
if it was ever committed, treat it as leaked: rotate it, don't just delete the
line). `major`/`minor`: fix or consciously accept with a note.

## Step 2 — the judgement checks (the scanner can't see these)

### Auth surface — who can reach what
For every new or changed endpoint, port, or route:
- **LAN vs public.** Public surface goes through Caddy (`caddy/Caddyfile`) —
  check the route against the public-access model
  (`docs/thor_public_access_model.md`). A service that should be LAN-only must
  bind the LAN IP, not `0.0.0.0` (Phase 4 rebind discipline).
- **Removing UI ≠ removing the endpoint** (the kanban read-only UI lesson):
  if the change hides a capability, verify the underlying route/tool still
  enforces its own gate.
- **Key gates.** New public routes need the Caddy key gate (the `@llmNoAuth`
  pattern) or an explicit decision that they're open. The 401 gate is what
  Phase 6 monitoring watches — don't add a public route you won't monitor.

### Config review
- **Compose env interpolation** — values with shell metacharacters must be
  quoted (the `KANBAN_MCP_KEY_CAPABILITIES` lesson: an unquoted value with
  spaces/semicolons breaks container startup).
- **`.env` is the single source** — new secrets go in `/home/chuck/homelab/.env`
  (gitignored); never hardcode a key in compose/Caddyfile/code.
- **Mounted configs don't hot-reload.** Editing a mounted file (Caddyfile,
  `litellm/config.yml`, skill files) does NOT affect the running container —
  the deploy step must `docker compose up -d --force-recreate <service>` (or
  the service's own reload path) and verify with `md5sum` host-vs-container.
- **Docker log rotation** — a service that logs a lot (especially access
  logs) needs `logging: json-file` with `max-size`/`max-file` (the Caddy
  Phase 6 lesson: it was unbounded).

### Grounding
- `security_todo.md` — the phase register; if the change touches a phase's
  surface (public access, keys, firewall, monitoring), re-read that phase's
  decisions before shipping.
- Phase 9 conventions (when they land) — the secrets-management program.
  Until then: `.env` single source, per-key aliases, `./homelab.sh key …`
  for LiteLLM key ops, `scripts/key-sync-check.sh` after any key change.

## Output

A short note in the task report / commit body:
- scanner result (clean / findings + dispositions)
- auth-surface delta (new public routes? new LAN binds? none)
- config-reload step taken (recreate / reload / n/a)

If a blocker is found and can't be fixed in this change: say so loudly in the
report — do not push and mention it in passing.
