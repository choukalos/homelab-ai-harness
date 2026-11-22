# Todo — agent skills: the virtual team (roles) + shared skill library

- date: 2026-11-22
- status: open (draft for review)
- target: chuck + pi
- source: post-kanban-setup conversation 2026-11-22 (board live with 4 projects;
  workers have 25 kanban MCP tools + 119 proxy tools + 29 existing skills)
- reframe 2026-11-22: chuck's org model — skills organized **in terms of roles**:
  Product Manager, Coding Team, Marketing Strategist, Content Marketer, Business
  Analyst, with chuck as the human exec.

## Vision

The kanban board is the **coordination substrate** for a virtual team of agent
roles. Each role is an agent that follows a **role skill** — a playbook for that
job — built on a **shared skill library** (S1–S12 below + the 29 existing skills).
The human **exec (chuck)** is the decision node: he receives pitches, strategy, and
status; he gives decisions, priorities, and feedback.

**Three layers (chuck's decision 2026-11-22, open question 7):**

1. **Role skills / playbooks** — one per role (PM, Coding Team, Marketing
   Strategist, Content Marketer, Business Analyst). "How to be a <role>": mission,
   the ordered workflow, handoffs, and *which step skill to run at each step*. The
   playbook is the evolving document — steps can be added, reordered, or retired as
   the role or the agent evolves, without rewriting the step skills.
2. **Step skills** — one per workflow step (PM-1…, DEV-1…, etc. below). The
   concrete playbook for a single step: inputs, method, output artifact, quality
   bar. Reusable across roles where a step repeats (e.g. S3 `qa-verify` serves
   both code QA and content QA).
3. **Shared skill library** — the S1–S12 playbooks + the 29 existing skills,
   reusable by any role/step.

**The feedback loop is the point:** the Business Analyst measures what shipped and
what published, synthesizes insights, and routes them back to PM / Strategist /
Content Marketer / Coding Team to iterate and improve.

## Org model

```
                 ┌────────────────────────────────────────┐
                 │  EXEC (chuck) — decisions, priorities, │
                 │  approvals, feedback                   │
                 └────────────────────────────────────────┘
      ↑ opportunity pitches (PM)   ↑ strategy + impact (MKT)   ↑ status + insights (BA)
      ↓ decisions / feedback (routed to the owning role via the board)

  ┌───────────────┐  PRD/spec   ┌──────────────────────┐  shipped  ┌───────────────────┐
  │ PRODUCT       │────────────▶│ CODING TEAM          │──────────▶│ BUSINESS ANALYST  │
  │ MANAGER       │◀────────────│ arch → stories →     │           │ KPIs, reports,    │
  │ research →    │  status/    │ code → QA → security │           │ dashboards, exec  │
  │ analytics →   │  feedback   │ review → docs →      │           │ status, feedback  │
  │ ideas → spec  │             │ deploy               │           │ routing           │
  └───────────────┘             └──────────────────────┘           └───────────────────┘
  ┌───────────────┐  strategy + ┌──────────────────────┐ published │
  │ MARKETING     │  asks       │ CONTENT MARKETER     │──────────▶│
  │ STRATEGIST    │─────────────▶ pitch → flesh out →  │           │
  │ market →      │◀───────────── draft → QA → publish │           │
  │ strategy,     │  impact     └──────────────────────┘           │
  │ voice, brand  │                                                 │
  └───────────────┘                                                 │
  BA insights route back to EVERY role (the iteration loop) ────────┘

  KANBAN BOARD = shared state + coordination substrate for all roles
  (ideas, specs, tasks, QA, deploys). All roles read/write it.
```

## Roles

### Role 1 — Product Manager

**Mission:** turn market signal + analytics into well-specified, prioritized
product work; sell the best opportunities to the exec.

**Workflow:**

1. **Analyze research / competitive market** — what competitors do, where the gaps
   and opportunities are (uses: `deep-research`, `market-research-brief`,
   `research-brief`)
2. **Analyze analytics** — what the data says about the product (usage, traffic,
   leads, spend) (uses: `business-analyst`, BA reports)
3. **Ideate features / solve issues** — generate candidate ideas from (1) + (2) +
   user feedback; each idea lands on the board (`add_idea` on the product project)
4. **Choose ideas** — prioritize (value vs. effort vs. strategy fit); groom the
   chosen ones interactively (S1 grooming loop)
5. **Create product requirements** — the groomed spec **is** the PRD: problem,
   goals/non-goals, user stories, acceptance criteria, success metrics, scope,
   dependencies (PM-2)
6. **Pass off to development** — spec ready → coding team picks it up as a task
7. **Pitch new opportunities to execs** — board-ready pitch: opportunity, value at
   stake, evidence, the ask (PM-3; deep-dive version = S9 `exec-problem-brief`)

**Role skill (playbook):** `pm` — the workflow above, step by step, with the
handoffs; the evolving document (new steps land here first).

**Step skills to build:**

- **PM-1 — `pm-market-analysis` (P1).** Competitive/market analysis workflow →
  opportunity brief + board ideas. Input: product area + question. Output:
  competitive landscape (what they do, positioning, gaps), market signals, an
  opportunity list — each opportunity becomes a kanban idea with its evidence
  attached. Grounding: `deep-research` / `market-research-brief` for the research;
  S9's no-fabrication discipline (never invent figures — state the equation +
  fastest test when data is missing).
- **PM-2 — `pm-product-requirements` (P1).** Idea → PRD. The PM's side of the
  kanban grooming loop (S1): which questions to ask, which assumptions to state,
  and the PRD template — problem statement, goals/non-goals, user stories with
  acceptance criteria, success metrics, scope, dependencies, deploy path. Output:
  a spec the coding team can build **without guessing**.
- **PM-3 — `pm-exec-pitch` (P2).** Opportunity pitch to the exec. Structure:
  one-line opportunity → value at stake (quantified, or the equation + measurement
  method) → evidence (research/data) → options (2–3, with a recommendation) → the
  ask (the decision needed + by when). Deep-dive version delegates to S9. Output:
  a 1-page pitch artifact + the board idea it supports.
- **PM-4 — `pm-ideation` (P1, from the workflow audit — gap G1).** Turning signal
  into candidate ideas: problem-first (the user's problem before the solution),
  each idea linked to evidence (from PM-1 / PM-2 / BA), a **dedupe check** against
  `list_ideas` before `add_idea`, and the idea template (value hypothesis, target
  user, success metric, rough size). Output: board ideas ready for grooming.
- **PM-5 — `pm-prioritization` (P1, from the audit — gap G2).** Choosing which
  ideas to groom: an explicit framework (RICE/ICE/Kano — pick one, keep it
  consistent) + strategy fit + a written rationale per choice; losing ideas get a
  reason (icebox vs. discard vs. "not now"), not silence. Output: a prioritized
  shortlist + the rationale, recorded on the board.
- **PM-6 — `pm-analytics-review` (P2, wiring blocked — gap G3).** Consuming the
  product analytics (traffic, engagement, leads from Plausible; spend from kanban
  `/reports`) to inform ideation/prioritization. The data source is decided
  (Plausible → data-hub); the step skill + the BA→PM report contract get defined
  when the wiring lands.

**Handoffs:** ideas/specs → Coding Team (via the board); pitches → chuck; market
insights → BA (feeds the strategy loop) + Marketing Strategist.

### Role 2 — Coding Team

**Mission:** turn approved specs into shipped, verified, secure production work.

**Workflow (chuck's list, 2026-11-22):**

1. **Define architecture** (DEV-1) — for new systems / big changes: system design
   doc *before* coding
2. **Groom epics → break epics into stories → groom stories → identify
   dependencies** (DEV-2) — spec → buildable stories with acceptance criteria, a
   dependency map, and sizing
3. **Code stories** — the task agent: S2 `codebase-recon` → implement → S4
   `git-flow`
4. **QA stories** — S3 `qa-verify` (functionality; honest "can't QA" declaration)
5. **Review cyber security of stories/work** — S11 `security-code-review`
   (**hard gate**: fix requests → fixes → re-verify before QA finishes)
6. **Code review** — S10 `code-reviewer` (static quality: best practices,
   conciseness, simplest approach, project conventions)
7. **Update documentation / publish / push to production** — S5
   `docs-housekeeping` + S4 deploy gates (S1)

**Role skill (playbook):** `coding-team` — the workflow above (chuck's 7-step
list), with the QA-stage gate order: S3 (functionality) → S11 (security, hard
gate) → S10 (static review) → S4/S5/S1 (docs + deploy).

**Step skills to build:**

- **DEV-1 — `architecture` (P1).** System design doc. Input: spec/PRD +
  constraints. Output: context & goals, component diagram (ASCII), data flow,
  interfaces/contracts, data model, tech choices **with rationale** (why X over Y),
  constraints & trade-offs, ADRs (decision + context + alternatives), rollout plan.
  Rules: match the project's existing conventions (S2 recon first); the simplest
  architecture that meets the constraints (no over-engineering); every component
  maps to an owned story.
- **DEV-2 — `story-breakdown` (P1).** Spec → stories. Rules: stories are
  independently shippable (vertical slices, not "all the database work"); each
  story has testable acceptance criteria, a size estimate (S/M/L with rationale),
  and explicit dependencies (with a dependency map); a "ready" definition (no
  unresolved questions). Output: a story backlog on the board (ideas/tasks) + the
  dependency map.

**Audit notes (gaps found in the workflow audit):**

- **G5 — test-writing is not an explicit step.** Acceptance criteria → tests
  *during* implementation (tests are part of the story's definition of done), not
  just post-hoc QA. Resolution: fold into DEV-2 (stories carry their tests) + S3.
- **G6 — "update documentation" is under-specified.** S5 covers repo hygiene
  (proposals/todos), not *feature* docs. Resolution: extend S5 with a ship-docs
  checklist (README/API/user docs that must change when a feature ships).
- **G7 — no post-deploy watch window.** S3 verifies the live surface changed, but
  nothing says "watch the logs/health for N minutes after deploy before closing
  the task." Resolution: extend S3 with a post-deploy watch step.

**Handoffs:** shipped work → BA (measure impact); incidents/blockers → PM + BA;
architecture decisions → BA (durable docs).

### Role 3 — Marketing Strategist

**Mission:** own the brand's market position — strategy, voice, brand image — turn
it into actionable content direction; measure impact and update.

**Workflow:**

1. **Review market / reports / analytics** — market research + what the content is
   actually doing (uses: `deep-research`, `market-research-brief`,
   `business-analyst`, BA reports)
2. **Come up with strategy / content constraints / guidance, voice, brand image**
   (MKT-1; core artifact = S12 `content-marketing`)
3. **Ideate asks for the content marketer** — specific, briefed asks (topic,
   angle, format, goal, constraints) — never a vague "write something"
4. **Assess impact** — after content ships: what did it do (traffic, engagement,
   leads) vs. the goal; what worked and why
5. **Update ideas/strategy** — iterate the strategy doc + the ask pipeline based
   on (4)

**Role skill (playbook):** `marketing-strategist` — the workflow above; owns the
strategy doc as the durable artifact.

**Step skills to build:**

- **MKT-1 — `brand-strategy` (P1).** The strategy artifact step (wraps S12
  `content-marketing`). Adds: brand/voice definition (voice attributes + do/don't
  examples, calibrated against existing brand materials — gap G8), the strategy
  doc structure (positioning → voice/brand image → content constraints/guidance →
  pillars → measurement), the **content-ask template** (the contract with the
  Content Marketer: topic, angle, format, funnel stage, goal, constraints,
  deadline), and the **impact-review template** (goal vs. actual, learnings,
  strategy deltas — blocked on the Plausible wiring, gap G3). Output: a durable
  versioned strategy doc + asks on the board (content project) + periodic impact
  reviews.

**Handoffs:** strategy + asks → Content Marketer; strategy/impact → chuck (exec
visibility) + BA (feeds the loop).

### Role 4 — Content Marketer

**Mission:** turn strategy + asks into published content that is factually sound,
on-brand, and on-strategy.

**Workflow:**

1. **Take direction from strategy** — read the strategy doc + the ask (constraints,
   voice, goal)
2. **Pitch ideas** — for open asks: propose 2–3 angles with a one-line rationale
   each (strategist picks)
3. **Flesh out ideas** — outline: structure, key points, sources to verify, CTA
4. **Draft** — uses `content-writer` (blog/social/video formats)
5. **Review drafts & QA** — the content QA pass (CM-1 checklist):
   **factualness** (verify claims via `mcp_search`/sources — no unverified
   factual claims; cite sources), **brand image alignment** (voice check against
   the strategy doc's do/don't examples), **strategy alignment** (does it serve
   the pillar / funnel stage / goal of the ask?), SEO basics (title, meta,
   internal links per S12)
6. **Finalize and publish** — publish via the project's path (blog `deploy.sh`,
   `publish-file`, social channels); verify the live surface (S3 discipline: check
   the published URL, don't assume)

**Role skill (playbook):** `content-marketer` — the pipeline above (direction →
pitch → flesh out → draft via `content-writer` → QA → publish per project → verify
live).

**Step skills to build:**

- **CM-1 — `content-qa` (P1).** The content QA checklist (the content analog of
  S3/S11 for code): factualness (every factual claim verified or sourced via
  `mcp_search` — corrections required before finalize), brand voice (does it read
  like the brand, per the strategy doc's do/don't examples?), strategy alignment
  (pillar, funnel stage, CTA match the ask), quality (structure, length,
  readability, no fluff). **Gate:** a draft cannot be finalized until the QA pass
  is clean (or the strategist signs off on the exceptions).
- **CM-2 — `content-inventory` (P2, from the audit — gap G10).** The registry of
  published content (URL, publish date, pillar, format, goal, performance when
  available) — a repo artifact the BA measures against, the strategist reviews
  (impact), and the CM checks before pitching (dedupe/repurpose). Updated at
  publish time (step 6).

**Handoffs:** published content → BA (analytics); drafts/exceptions → Strategist;
performance questions → BA.

### Role 5 — Business Analyst

**Mission:** measure what the org is doing against business goals, and close the
loop — insights to the exec and to every role.

**Workflow:**

1. **Look at code/blogs and create reports/dashboards** to analyze based on
   business goals — data sources: finance DB (transactions), kanban `/reports` +
   usage (spend), blog/site analytics, board state, deploy history (BA-1 defines
   the KPI set per business goal)
2. **Periodically analyze** — recurring cadence (e.g. weekly): what moved, vs.
   goal, vs. prior period
3. **Synthesize analysis and share** — routed to: execs (status + decisions
   needed), Marketing Strategist (what content is working), Content Marketer
   (what to do more/less of), PM (feature signals), Coding Team (tech signals:
   performance, incidents, spend)
4. **Present to execs on project status** — board-ready: what shipped, what's
   running, what's blocked, spend, risks (uses: `presentation-build`, S9 for
   deep-dives)
5. **Take feedback to the team** — exec decisions/feedback → the right role's
   backlog (board ideas/notes)

**Data & reporting architecture (decided 2026-11-22):**

- **Plausible** — the data engine for product web/mobile apps (invest-hub, both
  blogs/websites: Homelab Blog, Bluebovine). Traffic, engagement, leads per site.
- **data-hub / report-hub + Grafana** — the reporting/data surface. Grafana:
  platform/service status, engineering-centric. report-hub: product/business KPIs
  (fed from Plausible + finance DB + kanban).
- Flow: Plausible → (feed into) data-hub → report-hub/Grafana dashboards → BA
  reads → insights routed to the roles.
- Wiring (install Plausible on the sites, feed its data into data-hub) is the
  outstanding work — gap G3.

**Role skill (playbook):** `business-analyst-role` — the workflow above; owns the
KPI set + the insight-routing log. (Distinct from the existing `business-analyst`
skill, which is the NL→SQL tool skill this role uses.)

**Step skills to build:**

- **BA-1 — `kpi-reporting` (P1).** The KPI + report artifact step. Input:
  business goals (from chuck/strategy) + data sources. Output: KPI definitions
  (each KPI: definition, source, target, cadence), reports on the **reporting
  surface (decided 2026-11-22): data-hub/report-hub + Grafana** — platform/
  service status and engineering-centric in Grafana, product/business KPIs in
  report-hub — plus durable markdown analysis notes in the repo for the record,
  periodic analysis notes (what moved, why, so-what), exec status presentations
  (`presentation-build`, S9), feedback-routing log. Grounding: `business-analyst`
  (NL→SQL), `homelab-report`, `investment-brief`. **Data sources (decided
  2026-11-22):** Plausible = product web/mobile apps (invest-hub, both
  blogs/websites); data-hub/report-hub + Grafana = platform/service status +
  engineering-centric; plus the finance DB, kanban `/reports`, board state
  (available now). **Wiring is TBD** (gap G3): Plausible install + feed into
  data-hub.

**Handoffs:** insights → all roles + chuck; feedback → routed to the owning role's
board.

**The feedback loop (the iteration cycle):**

```
dev ships / content publishes
        ↓
BA measures (KPIs vs. goals) → synthesizes
        ↓
insights → PM (feature ideas) · Strategist (strategy update) ·
           Content Marketer (what to do more of) · Coding Team (tech signals)
        ↓
new ideas / updated strategy → board → grooming → dev → ship
        ↑
exec (chuck) receives status + pitches, decides; feedback routes via BA
```

## Workflow audit (2026-11-22)

Audit of each role's workflow steps against skill coverage (existing 29 + S1–S12 +
planned step skills). Gap register at the end.

**Product Manager**

| Step | Coverage | Status |
|------|----------|--------|
| 1. Analyze research / competitive market | PM-1 (planned) + `deep-research` + `market-research-brief` | ✅ planned |
| 2. Analyze analytics | — data source decided (Plausible via data-hub) but not wired; no step skill/contract to consume BA output | ⚠️ G3 (wiring) |
| 3. Ideate features / solve problems | — no ideation skill (frameworks, dedupe, idea template) | ⚠️ G1 → PM-4 |
| 4. Select ideas | — no prioritization framework; grooming covered by S1/PM-2 | ⚠️ G2 → PM-5 |
| 5. Create product requirements | PM-2 (planned) + S1 grooming loop | ✅ planned |
| 6. Pass off to development | S1 (`start_task`) + PM-2 output contract (PRD + acceptance criteria + deploy path) | ✅ |
| 7. Pitch opportunities to execs | PM-3 (planned) + S9 | ✅ planned |

**Coding Team**

| Step | Coverage | Status |
|------|----------|--------|
| 1. Define architecture | DEV-1 (planned) + S2 recon | ✅ planned |
| 2. Groom/break down stories + dependencies | DEV-2 (planned) | ✅ planned |
| 3. Code stories | S2 + S4 + S8 — **no explicit test-writing step** (tests as part of the story's DoD) | ⚠️ G5 |
| 4. QA stories | S3 (hard rule: can't QA → say so) | ✅ |
| 5. Cyber security review | S11 (hard gate) | ✅ |
| 6. Code review | S10 | ✅ |
| 7. Update docs / publish / push | S5 + S4 + S1 — **S5 = repo hygiene only, no feature docs (G6); no post-deploy watch (G7)** | ⚠️ G6, G7 |

**Marketing Strategist**

| Step | Coverage | Status |
|------|----------|--------|
| 1. Review market / reports / analytics | `deep-research`, `market-research-brief`, `business-analyst`, BA reports — **content analytics not yet wired (G3: Plausible)** | ⚠️ G3 (wiring) |
| 2. Strategy / voice / brand image | MKT-1 (planned) + S12 — **no brand asset inventory to calibrate voice against (G8)** | ⚠️ G8 (low) |
| 3. Ideate content asks | MKT-1 (ask template) | ✅ planned |
| 4. Assess impact | MKT-1 (impact template) — **blocked on the Plausible wiring (G3)** | ⚠️ G3 (wiring) |
| 5. Update ideas / strategy | MKT-1 + S5 (durable state) | ✅ planned |

**Content Marketer**

| Step | Coverage | Status |
|------|----------|--------|
| 1. Take direction from strategy | `marketing-strategist` playbook's strategy doc + the ask (file read) | ✅ |
| 2. Pitch ideas | `content-marketer` playbook | ✅ |
| 3. Flesh out ideas | `content-marketer` playbook (outline) | ✅ |
| 4. Draft | `content-writer` | ✅ |
| 5. Review drafts & QA | CM-1 `content-qa` (planned: factualness via `mcp_search`, brand, strategy) | ✅ planned |
| 6. Finalize and publish | Per-project path (Q10): blog `deploy.sh`, `publish-file` — **no social media capability (G9); no content inventory (G10)** | ⚠️ G9, G10 |

**Business Analyst**

| Step | Coverage | Status |
|------|----------|--------|
| 1. Reports/dashboards from code/blogs | BA-1 (planned) + `business-analyst` + `homelab-report`; surface = data-hub/report-hub + Grafana (decided) — **analytics wiring outstanding (G3)** | ⚠️ G3 (wiring) |
| 2. Periodic analysis | BA-1 (cadence deferred — Q11, tied to the agent work) | ✅ (deferred) |
| 3. Synthesize and share | BA-1 — **no insight delivery contract (G12)** | ⚠️ G12 |
| 4. Present to execs | `presentation-build` + S9 | ✅ |
| 5. Take feedback to the team | BA-1 (routing to the board) | ✅ |

### Gap register

| ID | Gap | Severity | Resolution |
|----|-----|----------|------------|
| G1 | No ideation step skill (frameworks, problem-first, dedupe, idea template) | High — PM step 3 uncovered | New step skill PM-4 `pm-ideation` (research: R8) |
| G2 | No prioritization framework (value/effort/strategy fit; RICE/ICE/Kano) | High — PM step 4 uncovered | New step skill PM-5 `pm-prioritization` (R8) |
| G3 | Product/content analytics not yet wired (blog traffic, invest-hub, leads, usage) | High — PM step 2, strategist impact, BA step 1, and the whole feedback loop | **Decided 2026-11-22**: Plausible = data engine for product web/mobile apps (invest-hub, both blogs/websites); data-hub/report-hub + Grafana = reporting surface (platform/service status, engineering-centric). Remaining: wire it up (Plausible install + feed into data-hub) — later |
| G4 | No BA→role analytics handoff contract (report format + location) | Medium | Defined together with G3 when the data lands |
| G5 | No explicit test-writing step (acceptance criteria → tests during implementation) | Medium | Fold into DEV-2 (stories carry their tests) + S3 |
| G6 | "Update documentation" under-specified — S5 covers repo hygiene, not feature docs | Medium | Extend S5 with a ship-docs checklist |
| G7 | No post-deploy watch window (logs/health/smoke test after deploy) | Medium | Extend S3 with a post-deploy watch step |
| G8 | No brand asset inventory (voice calibration against existing brand artifacts) | Low | MKT-1 input: point at existing brand materials (logo, past content) |
| G9 | No social media publishing capability | Medium — CM step 6 partial | **Later (chuck, Q10)** — separate item |
| G10 | No content inventory (registry of published content: URL, date, pillar, format, performance) | Medium — feeds BA + strategist + dedupe | New step skill CM-2 `content-inventory` + a repo artifact |
| G11 | Reporting surface undecided | Medium | **Decided 2026-11-22**: data-hub/report-hub + Grafana (platform/service status, engineering-centric); durable markdown analysis notes in the repo for the record |
| G12 | No artifact-location conventions (PRDs, strategy docs, reports, pitches) + no insight delivery contract | Medium | Define a `docs/` tree convention (e.g. `docs/roles/<role>/`); board specs carry PRDs; BA reports live in the repo + are routed via the board |
| G13 | The feedback loop cannot close until the G3 wiring lands | Systemic | The Plausible → data-hub wiring is the loop's enabler — everything else is buildable now |

**Audit verdict.** The *production* half of the org (PM spec → dev → QA → ship;
strategist → content → publish) is fully covered by planned skills and can start
building now. The *measurement* half (analytics → BA → feedback loop) has its
architecture decided (Plausible for product web/mobile apps; data-hub/report-hub
+ Grafana for platform/engineering) and is blocked only on the wiring (G3). Cheap
wins to fold into existing skills: G5, G6, G7, G12.

---

## Development plan & phases

The 24 planned skills (P0–P3) build in **4 phases**. Phases are sequential
(each phase's exit criteria must hold before the next starts); research runs in
parallel within a phase. Priority (P0–P3) ≠ phase — cheap P2s get pulled forward
when the first real tasks need them (S4/S5 in Phase 1).

### Phase 0 — Research kickoff

- **Build**: nothing — research only
- **Research**: **R1** (skill-authoring best practices — shapes how *all* skills
  get written; run first) + R4 (public skill collections, light, optional)
- **Exit criteria**: R1 findings captured in a `references/` note (authoring
  conventions: description style, progressive disclosure, split/merge rules) that
  every Phase 1+ build cites

### Phase 1 — Board + engineering foundation

**Goal:** the first real tasks (Bluebovine, Invest Hub) run end-to-end with full
discipline: recon → architecture → stories → code → QA (functionality + security
gate + static review) → docs → deploy → post-deploy watch.

- **Build** (9 skills):

  | Skill | Note |
  |-------|------|
  | S1 `kanban-board` (P0) | foundation — every role touches the board; build first |
  | S2 `codebase-recon` (P1) | |
  | S3 `qa-verify` (P1) | + G5 (tests as story DoD) + G7 (post-deploy watch) |
  | S4 `git-flow` (P2, pulled to Phase 1) | first tasks need branch discipline; no research needed |
  | S5 `docs-housekeeping` (P2, pulled to Phase 1) | + G6 (ship-docs checklist); no research needed |
  | S10 `code-reviewer` (P1) | needs R5 first |
  | S11 `security-code-review` (P1) | needs R6 first; the hard gate |
  | DEV-1 `architecture` (P1) | |
  | DEV-2 `story-breakdown` (P1) | needs R8 (the story-breakdown half) |

- **Research** (parallel): R2 (S2), R3 (S3), R5 (S10), R6 (S11), R8 (DEV-2 now,
  PM-4/5 later)
- **Prereq**: S1 first — everything else assumes board ops work
- **Exit criteria**: one real task on Bluebovine or Invest Hub completes the full
  loop — recon note → architecture (where needed) → story breakdown → code → QA
  pass (functionality + security gate with 0 open blockers + static review) →
  docs updated → deploy via the project's gate → post-deploy watch → verified
  live. All 8 step skills exercised in that one task.

### Phase 2 — PM + content production

**Goal:** the org can ideate → prioritize → spec → pitch (PM side) and
strategize → ask → draft → QA → publish (marketing side), with durable artifacts
in agreed locations.

- **Build** (10 skills + the artifact conventions):

  | Skill | Note |
  |-------|------|
  | PM-4 `pm-ideation` (P1) | |
  | PM-5 `pm-prioritization` (P1) | |
  | PM-1 `pm-market-analysis` (P1) | |
  | PM-2 `pm-product-requirements` (P1) | the PRD artifact |
  | PM-3 `pm-exec-pitch` (P2) | |
  | S9 `exec-problem-brief` (P1) | spec complete — buildable any time; lands here (PM deep-dive + exec-facing) |
  | MKT-1 `brand-strategy` (P1) | + G8 (brand asset inventory as input) |
  | S12 `content-marketing` (P2) | MKT-1's core artifact |
  | CM-1 `content-qa` (P1) | |
  | CM-2 `content-inventory` (P2) | |

  + **G12** — artifact conventions (`docs/roles/<role>/` tree; board specs carry
  PRDs; BA reports in the repo + the reporting surface)
- **Research** (parallel): R7 (S12/MKT-1/CM-1), R9 (MKT-1/CM-1); R8 findings
  reused for PM-4/5
- **Prereq**: Phase 1 (PRDs groom on the board; content publishes via the
  projects' deploy flows = S1/S4)
- **Exit criteria**:
  - PM: a real idea goes signal → ideation (dedupe-checked) → prioritized with
    written rationale → groomed → PRD in `docs/roles/pm/`
  - Strategist: strategy doc (voice/brand/pillars) + ≥2 briefed content asks on
    the board
  - CM: ≥1 piece of content published that passed content QA (factualness
    verified via search) + content inventory updated
  - Exec: ≥1 opportunity pitch delivered (PM-3; S9 for the deep-dive)

### Phase 3 — Measurement / feedback loop

**Goal:** close the loop — the BA measures shipped/published work against KPIs
and routes insights back to every role.

- **Build** (5 skills + the wiring, in this order):
  1. **G3 wiring (prerequisite — engineering task)**: Plausible live on the 3 web
     properties (invest-hub, Homelab Blog, Bluebovine) + feed into data-hub +
     report-hub/Grafana dashboards (platform/service status, engineering-centric)
  2. BA-1 `kpi-reporting` (P1) — the KPI set + reports on the decided surface
  3. PM-6 `pm-analytics-review` (P2) — unblocks once data flows
  4. S6 `security-review` (P3), S7 `spend-awareness` (P3), S8 `debugging` (P3 —
     or fold into S3 per open question 3)
  + **G4** — the BA→role report contract (defined when the data lands)
- **Research**: R10 (BA / exec reporting)
- **Prereq**: the G3 wiring (BA-1/PM-6 are data-blocked until it lands)
- **Exit criteria**: Plausible feeding data-hub on all 3 properties; ≥1 KPI
  defined per business goal (definition, source, target, cadence); first periodic
  BA report produced with insights routed to at least one of each role (PM,
  strategist, CM); exec status presentation delivered (board state + spend + KPIs)

### Dependency map

```
R1 (authoring) ──▶ every skill build
S1 ──▶ everything (board ops)
R2 ──▶ S2        R3 ──▶ S3        R5 ──▶ S10        R6 ──▶ S11
R8 ──▶ DEV-2 (Phase 1) ──▶ PM-4/PM-5 (Phase 2)
MKT-1 ──▶ CM-1 (the brand check needs the strategy doc)
G3 wiring ──▶ BA-1 ──▶ PM-6 ──▶ feedback loop closed
S9: spec complete — buildable in any phase
```

### Deferred / out of scope (explicit)

- **The "agents" concept** (separate keys/identities, goals + projects per
  worker) — chuck, separate item (Q8); the role/step skills work regardless of
  who runs them
- **Social media publishing** (G9) — later, separate item
- **BA cadence / scheduling** (Q11) — tied to the agent work
- **Cost guardrails** — decided 2026-11-21: not for now
- **G3 wiring specifics** (Plausible install details, data-hub feed design) —
  scoped when the Phase 3 engineering task starts

---

## Shared skill library (S1–S12)

Playbooks any role can use. "Used by" maps each to the roles above.

### S1 — `kanban-board` (P0)

Playbook for operating the board via the 25 `mcp_kanban-*` tools.

- **Triage**: reading `board_status` (task counts, `ideaCounts`, `needsAttention`,
  `running`); what each signal means; when to act vs. wait
- **Grooming etiquette**: the interactive loop (`start_grooming` → `groom_message` →
  `groom_status` → `groom_accept`/`groom_cancel`/`groom_re_groom`); asking good
  questions; stating assumptions explicitly; what a *good* spec looks like
  (testable, scoped, deploy path named); when to re-groom vs. discard vs. icebox
- **Task lifecycle**: `start_task`, monitoring via `task_status` (events, log tail),
  `pause/resume/stop/restart`, `retry_deploy`; what "needs attention" states mean
- **Project ops**: `create_project` / `update_project` / `delete_project` (refuses
  while a task is running/deploy), `edit_idea` (state gate: `idea` only),
  `discard_idea`, `move_to_backlog`
- **Deploy gates** (the per-project rules live in project `constraints`; this skill
  teaches the *pattern*): human-gated deploys (Invest Hub "push to production"
  only), two-branch publish flows (Homelab Blog main/deploy + `deploy.sh`),
  two-tier media publishing (NAS archive always; public only when asked)
- **Owner attribution**: work runs under the caller's key; items stamp the owner —
  don't assume the service key's identity

Used by: **all roles** (board ops); PM (grooming = the PRD process); Coding Team
(task lifecycle + deploy gates); BA (board state as a data source).
Research needed: none (internal system — codify from the kanban README +
proposals).
Status: not started.

### S2 — `codebase-recon` (P1)

Systematic orientation in an unfamiliar repo at task start (Bluebovine, Invest
Hub, future projects).

- Read order: README → docs/ → repo map (tree, not cat) → framework/build files
  (package.json / pyproject / compose) → test config → deploy config (workflows,
  deploy scripts)
- Produce a short **recon note** in the task workspace: conventions, test command,
  build command, deploy path, gotchas — so later steps (and resumed sessions) build
  on it instead of re-deriving
- Bound the recon: time/step budget; "enough to work safely", not exhaustive

Used by: Coding Team (every new repo; also DEV-1/DEV-2 grounding).
Research needed: **R2** (how SWE agents orient in unfamiliar repos; repo-map
patterns; what recon artifacts actually help downstream).
Status: not started.

### S3 — `qa-verify` (P1) — QA: make sure the generated code actually works

Scrutinize the *behavior* of generated code: does it work correctly, and is it
doing something erroneous or not working at all? (Complement to S10:
code-reviewer is static scrutiny — does the code *look* right; qa-verify is
dynamic verification — does it *run* right.) Consumed by both the task agent
(self-check before claiming done) and the kanban QA stage (independent pass over
the task's diff).

- **Honest capability declaration (hard rule — chuck's requirement):** when the
  skill doesn't have the tooling to QA something, it **must say it can't QA it.**
  Every QA report ends with a *Could not verify* section: what wasn't verified,
  why (missing tooling), and what would be needed. Examples: no browser → can't
  verify UI rendering; no GPU → can't verify model inference; no test database →
  can't verify a migration end-to-end; no access to an external service → can't
  verify the integration. Never simulate a check, never silently skip one, never
  let "couldn't verify" be read as "verified fine."
- **No "should work" claims**: every verification claim carries evidence (test
  output, curl response, before/after diff)
- **Verification methods** (use everything available, in this order):
  1. The project's test suite — find the command via recon (S2); run it (full if
     fast, targeted if slow); if the project has no tests, say so explicitly and
     verify by other means
  2. Build → run the service → hit the real endpoint (LAN URLs where applicable) —
     check the response, not just the exit code
  3. Behavior checks for the specific change: does the new path do what the spec
     says? Do the old paths still work (regression spot-checks)?
  4. Deploy verification: after a deploy, verify the *live* surface changed
     (publish → wait → curl the public site)
- **"Not doing something erroneous" means**: no new errors in the logs after
  exercising the change; no data corruption (check the DB rows the change
  touches); no resource leaks on the paths exercised; error paths behave (feed bad
  input and observe the failure mode)
- **Failure handling**: what "verified failing" looks like (reproduce, capture,
  report — don't silently retry forever)

Used by: Coding Team (QA stories — the functionality half of the QA step); Content
Marketer (adapted: content QA — factualness/brand/strategy, see CM-1); BA
(verification of report data).
Research needed: **R3** (agent self-verification practices; self-check loops;
avoiding confident-but-wrong completion).
Status: not started.

### S4 — `git-flow` (P2)

Git discipline for task branches.

- Branch naming (`task/<id>`), commit message style (the repo's convention:
  imperative subject, body with evidence), when to push (the deploy stage pushes —
  don't push mid-task unless the project says so)
- **Never** merge/push to `main` without the project's explicit gate (Invest Hub:
  only on "push to production"); no force-push to shared branches
- Conflict/rebase handling: stop and report, don't force
- Clean working tree at task end (no stray artifacts; `.gitignore` awareness)

Used by: Coding Team (code stories → publish/push to production).
Research needed: none (internal convention — codify from the repo's commit history
+ project constraints).
Status: not started.

### S5 — `docs-housekeeping` (P2)

Keep the repo's durable state clean — codify the 2026-11-22 proposal cleanup.

- Proposal lifecycle: `open → accepted → applied` / `dismissed`; **two-place
  state** (markdown file in `proposals/` + row in the `proposals` MySQL table —
  both must agree); applied/dismissed files move to `proposals/archive/`
- "Current state" sections (proposals README, skill docs) get refreshed when work
  lands; stale references get fixed or deliberately marked historical
- Retire completed todo files (durable content moves to proposals/docs first — see
  the `todo_mcp_kanban.md` retirement)
- Verification records: significant work gets a short "applied + verified" note in
  the proposal (what was verified, how, when)

Used by: Coding Team (update documentation step); all roles (durable state —
strategy docs, PRDs, and reports live here too).
Research needed: none (internal convention — `proposals/README.md` is the spec).
Status: not started.

### S6 — `security-review` (P3)

Pre-publish / pre-push security checklist for agent-produced changes.

- Secrets in diffs (the repo has real keys in `.env` patterns — never copy one into
  code/docs/commits); ownership/permission checks on new files (the presenton
  `userConfig.json` 600/chown lesson)
- Auth surface review: new endpoints → who can reach them (LAN vs. public; the
  kanban read-only UI lesson: removing buttons ≠ removing endpoints)
- Config review: compose env interpolation, quoted values with shell metachars
  (the `KANBAN_MCP_KEY_CAPABILITIES` lesson), image pinning (housekeeping H1)
- Grounding: `security_todo.md` findings + Phase 9 conventions

Used by: Coding Team (quick any-change checklist before push; complements S11's
deep code-vulnerability review).
Research needed: light (OWASP-style checklists for agent-generated code — fold into
R1 if convenient).
Status: not started.

### S7 — `spend-awareness` (P3, optional)

Work within LLM cost budgets (per-user spend attribution is live on `/reports`).

- Before a long job: check the user's spend trend (`/reports` per-user section or
  the LiteLLM spend log); batch operations; prefer the cheap model for exploration,
  spend the good model on the hard parts
- Long tasks: checkpoint durable progress (workspace is swept after 7 days) so a
  restart doesn't burn the budget twice

Used by: all roles (meta); BA (spend is a KPI source).
Research needed: none (internal; the data plumbing already exists).
Status: not started.

### S8 — `debugging` (P3, candidate)

Systematic debugging playbook for when a task hits a wall.

- Reproduce → isolate (bisect commits / configs) → fix → verify (S3)
- Log-reading paths: `docker logs <container>`, `journalctl -u`, task event stream
  (`task_status`), app logs in the workspace
- Homelab service health: `homelab-report` skill already covers infra; this skill
  is the *code* debugging loop

Used by: Coding Team.
Research needed: **R3** partially covers this (agent debugging loops).
Status: candidate — may fold into S3 rather than stand alone.

### S9 — `exec-problem-brief` (P1, spec received)

McKinsey-style executive problem-solving brief generator — board-ready
"Problem-Solving Brief" from a structured problem statement.

- **Spec provided by chuck 2026-11-22** — preserved verbatim at
  `agents-skills/exec-problem-brief/references/source-prompt.md` (versioned in the
  repo; SKILL.md is built from it)
- **Input**: the structured problem template (corporate profile, core challenge +
  urgency catalyst, baseline data/financials, structural constraints, core
  decision required) — the skill collects missing template fields before running
- **Pipeline** (7 steps): pre-execution diagnostic check (governing question,
  primary economic metric, MECE verification, initiative→owner/KPI linkage) →
  Minto answer-first executive summary → SCQ framing → 3–5 branch MECE issue tree
  with falsifiable hypotheses → evidence & falsification matrix (binary decision
  forks) → exactly 3 strategic pillars → phased roadmap (0–2w / 2–8w / 2–6m, every
  item as Verb+Object+KPI+Owner+Deadline, H/M/L tags) → risk & control matrix
  (leading indicators + trigger thresholds)
- **Hard constraints**: never fabricate figures/benchmarks — when data is missing,
  state the economic equation + fastest empirical test; answer-first (no
  preamble); strict economic/operational causality; decisive action titles, no
  generic headers
- **Output**: the 7-section brief (exec summary, SCQ, issue tree, evidence matrix,
  pillars, roadmap, risk matrix)
- Family-agent skill (brief family alongside investment-brief /
  market-research-brief), not kanban-specific; no tools required beyond what the
  agent has (optionally `mcp_search` for market context — but the spec's
  no-fabrication rule means research is optional, not a dependency)

Used by: PM (deep-dive opportunity pitches), BA (exec presentations / deep-dive
status), any role pitching a high-stakes question to the exec.
Research needed: none for the core (spec is complete) — R1 polish only.
Status: spec received 2026-11-22; build pending.

### S10 — `code-reviewer` (P1, prompt to be written)

Scrutinize code for best practices, conciseness, the simplest approach, and
adherence to the project's architectural conventions.

- **No spec yet — the prompt needs to be written** (chuck, 2026-11-22). Research
  first: **R5** (what makes LLM code review useful vs. noisy)
- **Input**: a diff (task branch vs. base — the kanban case) or a set of files
- **Review dimensions**:
  1. Correctness (bugs, edge cases, error handling, resource leaks)
  2. Language/framework idioms + security (the project's stack, not generic lint)
  3. Conciseness & simplicity — the simplest approach that works (YAGNI, no
     over-engineering, dead code, needless abstraction)
  4. **Architectural conventions of the project itself** — grounded in the actual
     repo (how similar things are done here), not a generic style guide; ties into
     S2's recon note (consume it if present, else do a quick convention scan)
  5. Testability + whether the change is actually tested
  6. Naming/readability
- **Anti-noise design** (the make-or-break for this skill):
  - Severity-ranked findings (blocker / major / minor / nit) with a verdict
    (approve / approve-with-notes / request-changes) — so a worker isn't buried in
    nits
  - Every finding cites `file:line` and must be verified against the actual code
    (read the file — never guess at lines that don't exist)
  - Scope discipline for large diffs: prioritize high-risk files (new logic,
    money/auth/security paths, cross-module changes); summarize the rest
- **Natural consumer**: the kanban **QA stage** (`src/agent/qa.ts`) — this skill
  can become the QA agent's playbook for the *static* half of the pass (reviewing
  the task's diff before deploy); the *dynamic* half (does it run right) is S3
  `qa-verify`; also usable standalone on any diff (family pi sessions, pre-push
  review)

Used by: Coding Team (code review step; static half of the QA stage).
Research needed: **R5** (LLM code-review prompt design) + R1 polish.
Status: not started — prompt to be written after R5.

### S11 — `security-code-review` (P1, hard gate) — cyber security reviewer

Scan code to make sure it is secure and not vulnerable to attack; at a minimum,
protect against the **OWASP Top 10** (https://owasp.org/projects/top-ten).

- **Scope**: code changes (task diff or file set). Complementary to S6
  `security-review` (the light pre-publish checklist for *any* change: secrets in
  diffs, file ownership/permissions, auth surface, env/compose config) — S11 is
  the deep code-vulnerability review; S6 is the quick any-change checklist.
- **Checklist core — OWASP Top 10 (2021), at the code level**:
  1. Broken Access Control — authz on every route/handler, IDOR, path traversal
  2. Cryptographic Failures — secrets in code, weak algorithms, plaintext
     storage/transport
  3. Injection — SQL/NoSQL/command/LDAP/template; parameterized queries
     everywhere
  4. Insecure Design — threat-model-level flaws (business logic, rate limiting)
  5. Security Misconfiguration — default creds, verbose errors, permissive CORS,
     debug endpoints
  6. Vulnerable & Outdated Components — new deps, known-vulnerable versions
  7. Identification & Auth Failures — session handling, password storage, MFA gaps
  8. Software & Data Integrity Failures — insecure deserialization, unverified
     updates
  9. Security Logging & Monitoring Failures — auth events logged, tamper
     resistance
  10. SSRF — outbound requests to user-controlled URLs
  Plus homelab-specific: secrets/credentials in code (real keys live in `.env`
  patterns — never in code), unsafe file operations (the presenton 600/chown
  lesson), container/compose security (exposed ports, root user, docker-socket
  mounts — the kanban lesson)
- **Gate behavior (chuck's requirement 2026-11-22)**: findings are **fix
  requests**, not notes. Code cannot finish the full QA step until every
  blocker/major security finding is fixed **and the fix is re-verified**. Flow:
  scan → findings (severity + requested fix) → task agent applies fixes → re-scan
  the changed code → pass/fail. Minor/nit findings: noted, not blocking (severity
  calibration per R5).
- **QA step composition (chuck's model 2026-11-22)**: full QA =
  **S3 `qa-verify` (functionality — does it run right) + S11 (security — is it
  safe) + S10 `code-reviewer` (static quality — does it look right)**. Security is
  a hard gate; functionality gate vs. advisory is open (question 5); static review
  advisory.
- **Anti-hallucination**: every finding cites `file:line` + the vulnerable pattern
  + a concrete 1–2 line exploit scenario + the required fix; verify against the
  actual code (read the file, trace the data flow — is the tainted value actually
  reaching the sink?)
- **Trust-boundary awareness**: the homelab runs a LAN-trust model (some services
  are unauthenticated by design — e.g. the media pipeline; public auth is the
  Caddy layer). The reviewer must respect the documented trust boundary (project
  constraints / docs) rather than flagging every unauthenticated LAN endpoint —
  but anything reachable from the public domain is held to the full standard.

Used by: Coding Team (cyber security review step — the hard gate of the QA stage).
Research needed: **R6** (OWASP Top 10 2021 code-level detection patterns for LLM
reviewers + complementary checklists — OWASP ASVS, dependency/secret scanning) +
R5 (severity calibration, gate design).
Status: not started.

### S12 — `content-marketing` (P2) — content marketing / traffic strategy

The "what to write and why" layer — content marketing strategy for driving traffic
(and conversions). Fills the gap between the two existing skills:
`marketing-strategy` is GTM/**launch** planning (product market-entry);
`content-writer` is **execution** (writes a given topic). Neither answers:
*"what guiding principles/areas should we be writing content to drive traffic?"*

- **Input**: a brand/site + goal (e.g. "Homelab Blog — grow organic traffic",
  "Bluebovine — drive qualified leads"; Bluebovine has a `leads` D1 table, so its
  funnel ends in lead capture)
- **Output** (content-strategy artifact):
  1. **Audience & intent** — who the reader is; what they actually search for
     (search-intent mapping; the queries behind the demand)
  2. **Positioning & guiding principles** — the content principles/voice the site
     stands on (the "guiding principles" question, answered explicitly)
  3. **Content pillars** — 3–5 thematic areas covering brand authority + audience
     demand; mutually exclusive, collectively covering the strategy (no overlap,
     no gaps)
  4. **Topic clusters** — pillar → cluster → concrete article topics, each with
     search intent + rough demand; SEO notes (target keywords, on-page, internal
     linking between cluster pages)
  5. **Funnel mapping** — TOFU (awareness/traffic) / MOFU (consideration) / BOFU
     (conversion — e.g. lead capture for Bluebovine)
  6. **Distribution** — channels (blog, social, newsletter, YouTube),
     repurposing via `content-writer` formats, promotion
  7. **Measurement** — KPIs (organic sessions, rankings, CTR, leads), review
     cadence
  8. **Content calendar** — first 30/60/90 days of topics, sequenced
- **Downstream**: feeds `content-writer` (strategy produces the *what*; the writer
  produces the *how*) — the two skills compose
- **Research**: **R7** (content marketing + organic-traffic strategy best
  practices — pillars, topic clusters, search-intent frameworks, SEO for 2025–2026
  *including AI search/answer engines changing discovery*, funnel mapping, KPIs)
- **Format**: follow the sibling pattern (SKILL.md wrapper + skill-runner job with
  `mcp_search` research) or a pure pi-native skill — decide at build time

Used by: Marketing Strategist (the core strategy artifact; MKT-1 wraps it).
Status: not started.

---

## Existing skills by role (the 29)

| Role | Existing skills it leans on |
|------|------------------------------|
| Product Manager | `deep-research`, `market-research-brief`, `research-brief`, briefs (competitive/market analysis), `business-analyst` (analytics) |
| Coding Team | the S-series above; `homelab-report` (infra context when a task touches the homelab) |
| Marketing Strategist | `marketing-strategy` (GTM/launch), `deep-research`, `market-research-brief`, `business-analyst` (analytics) |
| Content Marketer | `content-writer` (drafts), `publish-file` (publishing), `media-film` / `video-analyze` / `song-transcribe` (video/audio content) |
| Business Analyst | `business-analyst` (NL→SQL), `homelab-report`, `investment-brief`, `morning-brief`, `presentation-build` / `presentation-update`, digest layer (comprehension of source material) |
| Exec-facing (any role) | S9 `exec-problem-brief`, `investment-brief`, `morning-brief`, `presentation-build` |

## Conventions (how skills get added)

- Location: `agents-skills/<name>/SKILL.md` (pi-native workflow guide — the agent
  reads it and does the work; distinct from skill-runner `skill.yml` one-shot jobs
  in `skills/`)
- Structure (per existing skills): `SKILL.md` + optional `references/`
  (contracts, checklists), `templates/`, `tools/` (helper scripts)
- SKILL.md frontmatter: `name` + `description` (the description is what the agent
  matches on — write it as "when to use this", not "what it is")
- Role skills reference the shared library + existing skills at each workflow step
  (composition, not duplication)
- Research-first: R1–R10 below feed the skill designs; run them with the existing
  `deep-research` / `research-brief` skills before writing each skill

---

## Research workstream (run with existing web/research skills)

| # | Question | Feeds | Suggested skill |
|---|----------|-------|-----------------|
| R1 | Agent skill authoring best practices — description quality, progressive disclosure, when to split vs. merge skills, common failure modes | All | `deep-research` (Anthropic skill-authoring guidance + ecosystem patterns) |
| R2 | How SWE agents orient in unfamiliar repos — repo-map generation, recon artifacts that help downstream, time-boxing | S2, DEV-1/2 | `deep-research` |
| R3 | Agent self-verification practices — self-check loops, evidence-based completion, avoiding confident-but-wrong claims, debugging loops | S3, S8, CM-1 | `deep-research` |
| R4 | Public agent-skill collections worth mining for patterns (not copying) | All | `research-brief` (light) |
| R5 | What makes LLM code review useful vs. noisy — severity calibration, anti-false-positive design, how review agents (CodeRabbit / Graphite / Greptile) structure review prompts, diff-scoping heuristics for large diffs | S10 | `deep-research` |
| R6 | OWASP Top 10 (2021) code-level detection patterns for an LLM reviewer — per-category code patterns to look for, common false positives, complementary checklists (OWASP ASVS, dependency/secret scanning) | S11 | `deep-research` |
| R7 | Content marketing & organic-traffic strategy best practices — content pillars, topic clusters, search-intent mapping, SEO for 2025–2026 (incl. AI search/answer engines), funnel mapping, measurement KPIs | S12, MKT-1, CM-1 | `deep-research` |
| R8 | Product-management artifacts — PRD format, story breakdown / acceptance criteria / ready definition, dependency mapping, competitive-analysis frameworks, opportunity sizing, **ideation frameworks + prioritization (RICE/ICE/Kano)** | PM-1/2/3/4/5, DEV-2 | `deep-research` |
| R9 | Marketing strategy operating cadence — brand/voice frameworks, strategy-doc structure, content ops (ask → brief → draft → QA → publish), content impact measurement | MKT-1, CM-1 | `deep-research` |
| R10 | BA / exec reporting — KPI definition, dashboard practices, periodic analysis cadence, exec status-report format, feedback routing | BA-1 | `deep-research` |

Order: R1 first (it shapes how we write everything), then the rest in parallel,
grouped by the role whose build is next.

## Open questions (chuck)

1. **Priorities** — with the role framing: which role do we stand up first?
   (Coding Team skills are exercised immediately by the first real tasks —
   Bluebovine, Invest Hub; PM/BA have no board traffic yet.)
2. **Scope of "workers"** — just the kanban workers, or should the playbooks be
   written for *any* pi agent (they'd live in `agents-skills/` and be usable by
   family pi sessions too)?
3. **S8** — standalone `debugging` skill or fold into `qa-verify` (S3)?
4. **Per-project depth** — S1 teaches the *pattern* of deploy gates; the specifics
   live in project `constraints`. Right split, or do you want a per-project
   reference file per skill (e.g. `kanban-board/references/invest-hub.md`)?
5. **QA stage composition** — security (S11) is a hard gate (confirmed 2026-11-22:
   fix requests must be resolved and re-verified before QA finishes). Remaining:
   is functionality (S3) a gate or advisory, and is static review (S10) a gate or
   advisory? And: are all three wired into the kanban QA stage as the QA agent's
   playbook (static review + dynamic verification + security scan before deploy)?
6. **S12 (content-marketing)** — which site do we pilot it on first: the Homelab
   Blog (traffic goal) or Bluebovine (lead-gen goal)?
7. ~~Role skill format~~ — **answered 2026-11-22**: a role skill (playbook) that
   makes the playbook explicit, *plus* a skill per workflow step. Steps can be
   added and the playbook updated as the role/agent evolves. (The doc is now
   structured this way: three layers.)
8. ~~Who runs which role~~ — **deferred 2026-11-22**: chuck is building a new
   concept ("agents") — kanban workers with separate keys/identities, tasked with
   goals + projects. Out of scope for this doc; the role/step skills work
   regardless of who runs them.
9. ~~BA data sources~~ — **decided 2026-11-22 (wiring TBD, gap G3)**:
   **Plausible** = the data engine for product web/mobile apps (invest-hub, both
   blogs/websites); **data-hub/report-hub + Grafana** = the reporting/data
   surface for platform/service status + engineering-centric data. Remaining work
   (later): install Plausible on the sites + feed its data into data-hub. The
   feedback loop (G13) is blocked on the wiring, not the decision.
10. ~~Content publish paths~~ — **answered 2026-11-22**: publish paths are
    **per project** (the project's own deploy flow — blog `deploy.sh`, etc.).
    Social media capability doesn't exist yet — separate item (G9, later).
11. ~~BA cadence~~ — **deferred 2026-11-22**: tied to the agent work (Q8), a
    separate item. Not a skills concern for now.

## Definition of done (per skill)

- `agents-skills/<name>/SKILL.md` (+ references/templates/tools as needed)
- Description written as "when to use this"
- Research findings (if any) cited in the skill's header or a `references/` note
- Committed + pushed; picked up on next `mcp_kanban` container start
- Smoke test: a kanban task (or local pi session) actually follows the playbook on
  a real board item
- Role skills additionally: the smoke test is the role running its workflow
  end-to-end on a real item and producing the handoff artifact (PM → PRD, Coding
  Team → shipped story, Strategist → strategy doc + ask, Content Marketer →
  published piece, BA → report + routed insights)
