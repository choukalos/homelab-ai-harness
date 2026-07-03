# Thor Artifact Strategy

> Phase 4.3 — Define where skill artifacts live and how they are accessed.
> Date: 2026-07-03
> Status: Documentation only. No service changes.

---

## Artifact Root

```
/home/chuck/data/media/
```

All skill-generated artifacts are stored under this root, organized by type.

---

## Artifact Directories

| Directory | Artifact Type | Examples |
|---|---|---|
| `research_reports/` | Deep research outputs | Research briefs, fact sheets, summaries |
| `investment_briefs/` | Investment analysis | Stock briefs, portfolio analysis, risk assessments |
| `presentations/` | Generated presentations | Slide decks, visual presentations (via Presenton) |
| `code_reviews/` | Code review reports | Review summaries, findings, recommendations |
| `homelab_reports/` | Homelab status/health reports | System health, usage stats, incident logs |
| `siri_outputs/` | Siri skill outputs | Short responses, quick results, status artifacts |

Future directories can be added as new skills are created.

---

## Naming Convention

```
{skill_name}_{timestamp}_{slug}.{ext}
```

Examples:
- `deep_research_2026-07-03T10-30-00_qwen32b-release.md`
- `investment_brief_2026-07-03T09-00-00_aapl-q2-earnings.md`
- `siri_output_2026-07-03T14-22-00_status-check.txt`

---

## Access Rules

| Access Path | Allowed | Auth |
|---|---|---|
| LAN (direct file access) | All artifacts | Local user permissions |
| Siri `/media/files/*` | Selected artifacts | Public (opaque filenames prevent guessing) |
| Open WebUI | Upload + retrieval | LAN only |
| CLI | Full read/write | LAN only |
| n8n | Read + write (curated) | LAN only |

---

## Artifact Lifecycle

1. **Created** — Skill generates artifact and writes to its directory
2. **Registered** — Skill records artifact path in job metadata
3. **Retrieved** — User fetches via skill API (`GET /skills/jobs/{id}/artifact`) or direct LAN access
4. **Promoted (optional)** — Chuck may manually promote an artifact into the KB
5. **Archived (future)** — Old artifacts may be rotated or compressed

---

## Key Rules

- **Artifacts are NOT automatically added to the KB.** They live in the media directory until Chuck promotes them.
- **Artifacts are accessible on LAN** by default.
- **Selected artifacts can be retrieved publicly** through the Siri `/media/files/*` endpoint. Siri returns both a short summary and the artifact link when available.
- **Chuck manually promotes** artifacts into the KB when appropriate.
- Artifact filenames use opaque or timestamped slugs to prevent enumeration.
