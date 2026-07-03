# Thor Presenton Integration Plan

> Phase 11 — Use Presenton both LAN-only and through a controlled skill.
> Date: 2026-07-03
> Status: Documentation complete. Implementation exists in `skills/presentation_build/`.

---

## Current State

Presenton is already deployed and working:

| Property | Value |
|---|---|
| **Compose file** | `compose/compose.ai-core.yml` |
| **Container port** | `:80` (internal Docker network) |
| **Host port** | `:5000` (LAN-only) |
| **Network** | `ai-net` (internal) |
| **Auth** | HTTP Basic Auth |
| **LLM backend** | LiteLLM (internal) |
| **Search** | SearXNG (internal) |
| **Public exposure** | **None** — no Caddy route, no Cloudflare Tunnel |

---

## Architecture

```
                    LAN / Remote
                       │
                  Skill Runner (:8091)
                       │
              presentation_build skill
                       │
              ┌────────┴────────┐
              │                  │
        LiteLLM (outline)   Presenton (slides)
        :4000               :5000 (LAN) / :80 (Docker)
              │                  │
         vLLM/Ollama          Artifact Storage
         :8000/:11434          /data/media/presentations/
```

### LAN-Only Constraint

**The Presenton web UI (port 5000) is intentionally NOT exposed through Caddy or Cloudflare Tunnel.** There is no public URL for Presenton.

### Remote Access Path

The `presentation_build` skill is the **only** remote access path to Presenton. Users trigger presentations through:

1. **Skill Runner API** (`POST /skills/presentation_build`) — available on LAN
2. **Siri path** — via the skill runner's Siri channel adapter
3. **CLI** — direct invocation

Remote users never interact with Presenton directly.

---

## Integration Decisions

| Decision | Rationale |
|---|---|
| **Presenton stays LAN-only** | The UI is a presentation editor — not suited for remote exposure. Skill handles generation. |
| **Portal may link to Presenton** | LAN users can access the UI directly via `http://thor:5000`. Portal can embed or link to it. |
| **`presentation_build` skill is the remote facade** | Generates outlines via LLM, submits to Presenton, downloads artifact. No Presenton UI exposure. |
| **Remote use goes through Siri/skill path** | iOS users get presentation links, not direct Presenton access. |
| **Artifacts in `/home/chuck/data/media/presentations/`** | Consistent with the artifact strategy. Accessible on LAN, retrievable through skill runner. |

---

## Skill: presentation_build

Already implemented in `skills/presentation_build/`:

| File | Purpose |
|---|---|
| `skill.py` | Implementation — outline generation, Presenton async API, artifact download |
| `skill.yml` | Manifest — inputs, tools, model alias, channels, runtime |
| `README.md` | Full documentation — workflow, security, testing, rollback |

### Channels

| Channel | Access | Notes |
|---|---|---|
| **CLI** | Direct | Full control, all parameters |
| **Siri** | Via skill runner | Short topic → presentation artifact link |
| **n8n** | Scheduled/automated | Recurring reports, automated presentations |
| **Open WebUI** | Not directly | Would go through skill runner API |

### Security

- **No public Presenton exposure** — LAN-only by design
- **Skill-mediated access** — All Presenton interaction through skill runner
- **Artifact isolation** — Generated files use opaque timestamps and slugs
- **Timeout enforcement** — 300s total max runtime, 240s Presenton polling timeout
- **No sensitive data** — Unless `content_source` contains it

---

## Manual Tasks

### Presenton Auth Hardening

```text
MANUAL TASK FOR CHUCK:
Reason:
Presenton uses default auth credentials (presenton/changeme123). These should be changed.
Command:
Edit Presenton environment variables in compose/compose.ai-core.yml and restart Presenton container only.
Expected impact:
Brief Presenton downtime during restart. Skill runner will reconnect on next request.
Rollback:
Restore previous credentials in compose file and restart Presenton.
Validation:
Presenton UI loads with new credentials. Skill runner generates presentations successfully.
```

---

## Rules

1. **Presenton UI remains LAN-only** — No Caddy route, no Cloudflare Tunnel.
2. **Portal may link to Presenton** — For LAN users only.
3. **`presentation_build` skill is the remote facade** — All remote access goes through it.
4. **No direct public Presenton exposure** — Ever.
5. **Skill is already implemented** — No additional coding needed for Phase 11.
6. **Auth credentials need hardening** — Manual task for Chuck.

---

## Future Enhancements (Not in scope)

- **Gallery mode** — Browse past presentations via skill runner
- **Template library** — Pre-defined presentation templates
- **Collaborative editing** — Multiple users editing the same presentation
- **PDF export** — Alternative export format in addition to PPTX
