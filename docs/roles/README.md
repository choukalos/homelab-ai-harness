# G12 — Artifact conventions: where durable role artifacts live

The org's durable artifacts (the things that outlive the session) live in the
repo under `docs/roles/<role>/`. The board is the coordination surface (cards,
specs, status); the repo is the record. Rule of thumb: **the board carries the
work item, the repo carries the artifact** — a board spec may *contain* the PRD
while it's in flight, but the durable, versioned copy lands here when the work
lands (filed with S5 `docs-housekeeping` discipline).

Established 2026-11-23 (Phase 2, gap G12 from the workflow audit in
`todo_agent_skills.md`). The `pm/` layout was locked first by the five PM step
skills (PM-1/2/3/4/5, built 2026-11-23); the rest of the tree follows the same
shape.

## The tree

```
docs/roles/
├── pm/                        # Product Manager
│   ├── market-analysis-<area>-<YYYY-MM-DD>.md   # PM-1 opportunity briefs
│   ├── analytics-review-<YYYY-MM-DD>.md         # PM-6 analytics reviews (prioritization input)
│   ├── prioritization-<YYYY-MM-DD>.md           # PM-5 prioritization passes
│   ├── prds/<feature>.md                        # PM-2 PRDs (durable copy)
│   └── pitches/<opportunity>-<YYYY-MM-DD>.md    # PM-3 exec pitches
├── marketing-strategist/      # Marketing Strategist
│   ├── strategy/<site>.md     # MKT-1/S12 — the durable versioned strategy doc (one per site/brand)
│   └── impact-reviews/<site>-<YYYY-MM-DD>.md    # MKT-1 goal-vs-actual impact reviews
├── content-marketer/          # Content Marketer
│   └── inventory.md           # CM-2 — the registry of published content (single table)
└── business-analyst/          # Business Analyst
    ├── report-contract.md     # G4 — the BA→role report contract (format, location, routing, cadence)
    └── reports/<topic>-<YYYY-MM-DD>.md          # BA reports (BA-1, Phase 3)
```

## Rules

1. **One durable home per artifact type.** If an artifact type has a home here,
   it lives there — not in `tmp/`, not only on the board, not in a chat
   transcript. A session that produces a durable artifact files it (or names
   the home in its report when filing is another step's job).
2. **Naming.** Point-in-time artifacts are date-stamped
   (`<YYYY-MM-DD>`, the date the artifact was produced); living docs are
   named by the thing they describe (`<feature>.md`, `<site>.md`) and carry an
   "updated <date>" note inside instead of a new file per revision.
3. **Board specs carry in-flight PRDs.** The grooming finalize produces the
   structured spec on the board; the durable copy is filed to
   `docs/roles/pm/prds/<feature>.md` when the work lands.
4. **BA reports live in the repo + are routed via the board.** The report file
   under `business-analyst/reports/` is the record; a board card routes the
   insight to the owning role (the insight delivery contract — G4 formalizes the
   report format when the G3 data lands).
5. **Strategy docs are living, versioned docs.** One per site/brand
   (`strategy/<site>.md`); updates are edits with an "updated <date>" note, not
   new files. The point-in-time siblings are the impact reviews.
6. **The content inventory is a single file.** One table, one home
   (`content-marketer/inventory.md`), updated at publish time (CM-2).

## Out of scope (not role artifacts — they have their own homes)

- Research digests (R1–R10) → `docs/research/`
- Proposals → `proposals/`
- Coding Team durable state (recon notes, architecture docs) → per-project docs
  under S5 `docs-housekeeping` discipline (the `docs/roles/` tree is for
  org-role artifacts, not code-repo docs)
- Skill-runner job artifacts (GTM strategies, research reports, …) → their
  `artifact_path` (e.g. `/home/chuck/data/media/…`), per each `skills/*/skill.yml`
