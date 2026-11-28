# Todo — agentic framework + agents (workstreams 3–4)

- date: 2026-11-24
- status: **LIVE — verification window (2026-11-27)** (planning complete
  2026-11-25 — all framework design
  questions decided; S13 `okr` skill built + registered 2026-11-25; Q15
  domain knowledge decided 2026-11-26; **first org-goals pass done 2026-11-26**
  — `docs/org/goals.md` (cycle 2026-12: homelab O1 content; bluebovine O1
  trust+traffic, O2 product-define), alignment report
  `docs/org/alignment/2026-11-26-first-pass.md`, 4 charters
  `docs/agents/<slug>/charter.md` — **ALL 4 APPROVED 2026-11-27** (product
  first — all 7 sections, no changes requested; strategist/marketing/analyst
  completed + approved the same day at activation — "get that done & in
  place"); Q13 decided
  2026-11-26, **revised 2026-11-27 (chuck): stand up `product` first** (product
  first; `strategist`/`marketing`/`analyst` stood up but stayed OFF — keys +
  workspaces only, no cron targeting, no board cards, charters not approved —
  **until chuck activated them 2026-11-27: all 4 agents now ACTIVE** —
  charters complete + approved, cron targeting all 4 (hot-reload verified),
  first-work cards on the board (tasks 20–23, project 12, agent-owned),
  global switch ON); **agents master switch built 2026-11-27** —
  fail-safe OFF, admin-only `agents_switch` MCP tool, **live state ON
  (all 4 agents active)**;
  **switch v2 (hard-kill + per-agent switches) + mission-brief hardening
  done 2026-11-27**;
  **agent-key model access fix 2026-11-27** — the first live agent run
  exposed the work-type key vs kanban pipeline model mismatch (strategist/
  marketing keys 403'd on KANBAN_MODEL=matrix-coder → empty sessions → QA
  no-verdict → needs_attention on tasks 21/22); both live keys now have
  work-type + pipeline model access, `key add-agent` mints both for future
  agents, tasks 21/22 restarted (item 12). **Board improvements decided
  2026-11-27 (chuck): `merge_task` admin MCP tool (item 13 — the merge
  path for agent artifacts), session loud-fail hardening (item 14 — with
  item 13), per-owner pipeline models (item 15 — `KANBAN_OWNER_MODELS`),
  per-model usage surfacing (item 16 — `byModel` alongside `byRole`),
  fresh-context QA reviewer DECIDED (item 17 — separate-reviewer item
  DROPPED: one model with capacity; the QA gate itself made fresh-context
  + requirements-only instead); no agent-to-agent delegation (item 18 —
  permanent, depth-1 topology). **Items 13-16 + the item-17 QA change
  BUILT + LIVE 2026-11-27** (dev clone `task/19` — `c47f87b`/`7df1c1e`/
  `f3a8d36`/`625206d`, pushed; `mcp_kanban` rebuilt, 29 MCP tools, 288-test
  suite green); merge_task E2E'd (admin gate + merge commit + idempotency
  + audit); **all 4 first-run agent artifacts merged to main** (task/21
  strategist strategy during the E2E; task/20 + task/22 + task/23 merged
  via merge_task 2026-11-27 — market analysis, content inventory, KPI
  digest); QA now a fresh-context requirements-only reviewer (worker's
  completion summary removed from the QA prompt). **Monthly org review
  updated 2026-11-27 (item 19)**: consumes the board's `byModel` usage
  data (LLM payload + deterministic doc footer), and a window-semantics
  bug found in the E2E was fixed before the 2026-12-04 first live fire
  (the review now covers the JUST-ENDED month per the org's documented
  design — a Dec 4 run reviews November and proposes the 2026-12 cycle;
  the first full-cycle review is Jan 8 for December); LLM timeout
  120s → 300s (live synthesis took 180s); live E2E green (12 KRs scored
  with real evidence refs + real byModel footer). Goal model + S13 acceptance
  2026-11-24; decisions 2026-11-25; Q15 2026-11-26; **WS3 step-6 build layer
  done 2026-11-27** (product-first): slot gate (harness `task/17`, pushed),
  4 agent keys + workspaces (product active; strategist/marketing/analyst
  OFF), review crons registered + hot-reload verified, product charter
  completed as DRAFT (pending chuck's review) — evidence below (per-item
  "done" notes carry the commit refs; the run's build report was retired
  2026-11-28); **review skill
  modules BUILT 2026-11-27** (`weekly_agent_reviews` + `monthly_org_review`
  — conservative-apply: the monthly goals rewrite + `kb_forget` are
  PROPOSALS by default, applied only with explicit params) — bootstrap
  weekly review `docs/agents/product/reviews/2026-W48.md`, both skills
  registered in the Skill Hub, the first real cron fire (2026-11-27 15:00
  CT) will now run the real skills — evidence below (per-item notes carry
  the commit refs; the run's build report was retired 2026-11-28).
  **FRAMEWORK LIVE — VERIFICATION WINDOW (2026-11-27):** all 4 agents
  ACTIVE (chuck activated strategist/marketing/analyst 2026-11-27 — the
  "product first, rest OFF" state above is superseded), all 4 first-run
  artifacts merged to main (tasks 20–23), board clean (20 done, 0 open),
  board items 13–17 live (merge_task, loud-fail, per-owner models, byModel
  usage, fresh-context QA), monthly org review consumes byModel + window
  fixed. This doc is now a **verification-period record, not an active
  build plan** — chuck's call 2026-11-27: keep it, verify the org over the
  first week/month (W49 weekly reviews + the 2026-12-04 first monthly org
  review), then retire it to `proposals/archive/`-style docs if the org is
  holding. Nothing here is a pending build; the open questions below are
  the ones that survive into the verification window.
- source: workstreams 3–4 of `todo_agent_skills.md` (decomposed 2026-11-22);
  this is the own-TODO-doc that doc proposed for WS3+WS4
- companions: `todo_agent_skills.md` (WS2 — the role/step skills the agents
  follow), `docs/plausible_ops.md` (WS1 — the instrumentation the KRs measure against; own plan retired 2026-11-28)

## Scope

- **WS3 — the agentic framework**: the system that runs the role agents —
  identity/keys, goal model, projects, constraints, tasking, periodic review
  protocol, state/memory, domain knowledge (Q15), scheduling, reporting,
  guardrails, spend.
- **WS4 — the agents**: one standing agent per role. The agents are the
  framework's first instances, so they're planned together.

## Decisions (2026-11-22 conversation)

- Agents are "kanban workers with separate keys/identities" — a per-agent
  LiteLLM key (the `USER_KEYS` pattern exists for users; extend it to agents)
  → per-agent spend attribution.
- Per agent: **goals**, **projects**, **constraints**.
- **Goal ladder**: org goals → agent goals → task goals; goals drive behavior.
- **Periodic reviews with chuck**: agent presents upcoming plans → chuck gives
  feedback/direction or TODOs → agent executes → agent reports
  accomplishments/learned.
- **Roster (WS4)**: PM, BA, marketing strategist, content marketer, (maybe)
  researcher — "to feed the group". **No standing coding agent** — coding stays
  task-driven (specs from PM/chuck; kanban task workers).

## Goal model (decided 2026-11-24 interview)

### Org goals

- **Not written yet** — step 1 of this workstream (the S13 `okr` skill below is
  the tool for the first pass).
- **Per domain, not one flat set** (chuck 2026-11-24). Two in-scope domains:
  - **Homelab** — learning by building: the custom harness itself, research,
    personal-interest content (old arcade games, guitar, creating songs/clips,
    teenage-chuck RPGs & war games, cars).
  - **Bluebovine Group** — commercial: consulting, a product (TBD), and content
    that drives traffic + credibility for the site.
  - **InvestHub** — **out of scope for agents** (chuck 2026-11-24): chuck's own
    thing; he'll use the board to build but won't hand it to an agent now. No
    org goals, no agents. (May re-enter scope later.)
- **Home**: `docs/org/goals.md` — one file, per-domain sections (split into
  per-domain files later if they grow).
- **Authorship**: chuck, with the S13 skill.
- **Cadence (chuck 2026-11-24)**: org goals reviewed **monthly**; agent
  reviews **weekly to start** (agent presents the prior week's work + upcoming
  plan → chuck's feedback/direction) — move to monthly as chuck grows confident
  in the framework/agents.

### Org-goal anchoring (decided 2026-11-25 interview)

- **Homelab — one objective this cycle**: the **personal-interest content is
  the main goal** (arcade/guitar/songs/RPGs/cars). "The virtual team ships
  real work" (harness/agents) is the means, not the goal — harness upkeep is
  **BAU** (tagged), not an objective. "Learning by building" lives inside the
  content (the content is the vehicle). Early warning: if the work-mix check
  shows `bau` eating the content ratio, promote the harness to a second
  objective at the first monthly review.
- **Bluebovine — two objectives this cycle**: (O1) credible/traffic content,
  (O2) defining the product (research/etc.). O2 is **phased**: define →
  iterate toward product-market fit; the monthly org review is the shift
  point — rewrite the objective at the cycle boundary, don't append a third.
- **Scale rule**: default **1–2 objectives per domain per cycle**; 3 only
  with an explicit justification (surfaced in the okr alignment report).
  Objectives are a cycle decision, not a fixed constant — the monthly cadence
  is the growth mechanism.
- **Draft shape** (to be redone by the S13 skill's first run):
  - Homelab O: "personal-interest content ships on a steady rhythm and is
    worth coming back to" — KRs: pieces/mo (proxy), pillar spread (≥2 of
    arcade/guitar/songs/RPGs/cars active per month), quality KR (0 pieces
    failing content QA), revisit/traffic (proxy until Plausible wiring).
  - Bluebovine O1: "the site compounds trust and traffic" — content volume,
    traffic growth (proxy), engagement.
  - Bluebovine O2: "the product is defined and validated, ready to iterate"
    — market analysis done, opportunity selected + pitched, PRD/spec drafted,
    validation signal (phase: define).

### Agent charters

- **Home**: `docs/agents/<agent>/charter.md` — living, versioned doc (G12 rule
  5: edits with an "updated <date>" note, not new files).
- **Sections**:
  1. **Identity** — one-line mission. Short, purpose-only, outcome-oriented,
     no methods/specifics (Webex do's/don'ts; one goal per statement).
  2. **Objectives** — 1–2 per agent, each **explicitly laddered** to a domain
     org goal (cites the org goal it serves).
  3. **Key results** — 2–4 per objective. Each KR: definition, source, target,
     cadence.
  4. **Projects** — the kanban projects this agent works + the domain KB(s)
     it owns (Q15).
  5. **Constraints** — must-not-without-approval list (feeds the guardrails
     question).
  6. **Autonomy tiers** — autonomous / single-approval / never, per action
     class (feeds the guardrails question; AWS risk-tiering pattern).
  7. **Quality metrics** — open slot (see below).
- **Authorship (chuck 2026-11-24)**: the **agent suggests its charter**
  (derived from the org goals) → chuck edits/reviews/accepts. Alternative:
  chuck drafts and they iterate. Either way chuck approves.
- **KRs (chuck 2026-11-24)**: **proxy/guess KRs are fine for the first pass** —
  startup mode: no data, so guess. Mark them (`source: guess — validate when
  <data> lands`) so they get replaced with real measurements when the data
  exists (G3 wiring / Phase 3).

### Ladder, tags, and precedence

```
ORG GOAL (per domain) → AGENT OBJECTIVE (linked) → KR → TASK
```

- Every task (kanban card or direct TODO) carries a `serves:` tag:
  - `org/<domain>/<O#>-KR#` — serves an org goal
  - `agent/<agent>/<O#>-KR#` — serves an agent objective/KR
  - `exec` — chuck's direct directive
  - `bau` — business-as-usual (see below)
- **Precedence (chuck 2026-11-24)**: chuck's direct TODOs **always win** and are
  tagged `exec`. But an agent **may push back** with a compelling argument;
  chuck takes the feedback and either cancels the directive or adjusts it.
- **Enforcement (chuck 2026-11-24)**: **soft** — unmapped work is *flagged* at
  review, never blocked.
- **BAU (chuck 2026-11-24)**: business-as-usual work (cyber security, tech
  debt, organization/clean-up) is legitimate and recurring — **tag** approach
  (the `bau` tag) so it isn't flagged as unmapped. The periodic review
  includes a **work-mix check**: the ratio of `bau` vs OKR-serving vs `exec`
  work, so the mix is visible and can be steered.

### Quality metrics

- **Mandatory (chuck 2026-11-24)**: a **quality/safety KR is mandatory** on
  every agent charter (and on the org goals) — "for now, mandatory quality
  should be part of our goals." Research basis (OKR Institute): without it an
  agent can optimize volume at the expense of trust.
- **Monitoring mechanism** (still open): how quality is measured/metric'd per
  agent (the KR sets the bar; the measurement plumbing — e.g., BA consuming
  QA/publish records — is TBD). The charter carries the slot; the BA consumes
  the same data (one source, no duplicate reporting).
- Candidate KRs: CM "0 published pieces that failed content QA"; PM "0 PRDs
  without acceptance criteria".

### Tasking + review protocol (decided 2026-11-25 interview)

**Tasking (Q3):**

- **Single work queue**: the kanban board is the single source of truth for
  agent-managed work — one queue, no shadow queues (MVV rule 5).
- **Chuck's direct TODOs — board cards (option a, confirmed 2026-11-25)**:
  all agent work — including chuck's direct TODOs — becomes a board card
  (tagged `exec`), so the board is the single queue *and* the concurrency
  gate. (Started as option b "lightweight + logged in review"; promoted to
  (a) the same day with the board-as-gate decision.)
- **Clarifying questions on exec TODOs (chuck 2026-11-25)**: when chuck hands
  an agent a TODO directly, the agent asks clarifying questions (one bounded
  round) before executing, so it has a complete brief — the exec-TODO mirror
  of the flag-don't-guess rule.
- **Self-plans flow through the review**: agents don't silently create work.
  The weekly review's upcoming-plan section is where an agent proposes next
  week's cards; chuck approves/adjusts; then they're pulled like normal cards.
- **Task brief standard**: every agent-authored card carries the 4-element
  delegation contract (objective, output format, tools, boundaries). At
  pickup, an agent with an incomplete brief **flags it, doesn't guess**.
  Applies to agent-authored cards; chuck's direct TODOs are his channel (no
  enforcement — but see clarifying questions above).
- **Capacity / concurrency (3.5) — decided 2026-11-25 (chuck)**:
  - **No model separation** (rejected). Instead **model assignment by work
    type**: `matrix-coder` for the majority of work (product, analyst,
    generic board workers, interactive chats); `matrix-copywriter` for
    marketing/strategist content work (per-key default model in LiteLLM).
    Side benefit: the two content agents never contend with interactive chats
    on the coder model — combined with the session budget below, most
    contention is solved without formal separation.
  - **Concurrency budget**: the board orchestrator's existing per-category
    slot gate gets a third category — `AGENT_CONCURRENT_TASKS` (default
    **1**), alongside `MEDIA_CONCURRENT_TASKS` (1) and
    `NON_MEDIA_CONCURRENT_TASKS` (2) — so **1 agent run + 2 board workers =
    3 concurrent LLM sessions** to start. Each is an env var chuck can tune
    (same pattern as the board's concurrent work items).
  - **Interactive-first is a hard rule**: interactive chats never queue
    behind agent work; the budget bounds contention. v2 option: admission
    hold — defer new agent/board starts while an interactive session is
    active (in-flight runs finish).
  - **In-run sub-agent fanout**: v1 = agent runs are **single-session**;
    fanout requires **chuck's explicit ask** (2026-11-25) — it is a
    single-approval action class (feeds Q7 autonomy tiers). Right-sizing
    (1 / 2–4 / 10+) stays the discipline for when chuck authorizes fanout.
  - **Board as the gate**: all agent work is a board card (transparency), so
    the orchestrator's dependency + slot gate is the single admission point
    for all agent-driven LLM sessions. Slot classification: by **executor
    identity** — cards assigned to a standing agent count against
    `AGENT_CONCURRENT_TASKS` regardless of work kind (confirmed 2026-11-25).

**Review protocol (Q4) — confirmed:**

- **Weekly review**: one file per agent per week at
  `docs/agents/<slug>/reviews/YYYY-WW.md`, 7 parts: (1) prior-week
  accomplishments with evidence/links, (2) KR progress vs trajectory, (3)
  work-mix check (`bau` vs OKR vs `exec` + spend line), (4) quality KR
  status, (5) upcoming plan (proposed cards), (6) learnings / what the loops
  caught or missed — incl. the domain-KB line: facts added/corrected/
  forgotten + collision log (Q15), (7) chuck's feedback (appended after he
  responds).
  Mechanics: the agent generates the doc from board state + its own
  artifacts, presents it, chuck responds in chat, response appended to the
  file.
- **Monthly org review**: KR scoring 0–1, retro, the **only place goals may
  change** (incl. the bluebovine define→iterate shift). Record at
  `docs/org/reviews/YYYY-MM.md`; `docs/org/goals.md` updated in the same
  pass.

### Scheduling (Q6) — decided 2026-11-25 interview

- **Trigger set** (confirmed):
  1. **Kanban events** (existing orchestrator pickup): eligible agent cards
     auto-start when deps are done + the agent slot is free.
  2. **chuck**: direct TODOs → cards; interactive chat on demand.
  3. **Cron** (new jobs in `schedules.json`, skill-runner scheduler —
     hot-reload, America/Chicago):
     - `weekly-agent-reviews` — one job generating all four agents' weekly
       review docs. **Friday 15:00 CT.**
     - `monthly-org-review` — KR scoring + retro + goal adaptation + the
       domain-KB staleness pass (`kb_forget` superseded facts, Q15).
       **First Friday 15:00 CT** (after that week's agent reviews land, so
       it can consume them).
     - Nothing else for now (BA data consumption rides inside the weekly
       reviews). Keep the periodic set minimal.
- **Self-plan card lifecycle** (confirmed): agent-created cards start as
  **idea/grooming** (the orchestrator only auto-starts from backlog → no
  auto-start); chuck approves at the weekly review → promoted to backlog.
- **Review delivery + non-stacking rule** (chuck 2026-11-25): no push
  notification — chuck checks for reviews himself. **Scheduled reviews are
  non-stacking**: if a review goes unanswered (no feedback, nothing promoted
  to backlog), the next scheduled cycle for that agent (or the monthly org
  review) is **skipped** until chuck interacts (accept / reject / request
  another pass / promote cards). Mechanism: each review doc carries a status
  (pending until chuck's part-7 feedback or explicit ack is appended) —
  file-based state, consistent with MVV rule 5.

### Guardrails (Q7) — decided 2026-11-25 interview

- **Autonomy tiers** (chuck-approved 2026-11-25; AWS risk-tiering pattern —
  read-only autonomous, low-risk writes single-approval, high-risk stricter).
  Living table — tiers can be re-granted/revoked at review:

  | Action class | Tier |
  |---|---|
  | Read (board, files, KB, memory, search) | Autonomous |
  | Own workspace — drafts/artifacts under `docs/agents/<slug>/` | Autonomous |
  | Create board cards in own project | Autonomous (no auto-start — idea/grooming, per Q6) |
  | **Publish to blog (publish-file)** | **Autonomous** (chuck 2026-11-25 — quality-gated: the content QA pass is the external predicate; first autonomous external-facing action) |
  | Write/correct shared domain KB — **own domain** (Q15) | **Autonomous** (chuck 2026-11-26 — correctable store; enables ad-hoc distillation at discovery time) |
  | Write/correct shared domain KB — other domains (Q15) | Single-approval |
  | Promote own cards to backlog (auto-start) | Single-approval (chuck, at the weekly review) |
  | Edit org/charter docs (`docs/org/`, `charter.md`) | Single-approval |
  | Deploy (existing per-project deploy gates) | Single-approval |
  | Spend beyond soft threshold | Single-approval (threshold set after first data) |
  | Sub-agent fanout | Explicit ask (decided 2026-11-25) |
  | External comms (email, social) | Explicit ask (v1: nothing external without chuck) |
  | Delete durable state (files, board history) | Explicit ask |
  | Change framework config (skills, orchestrator, keys) | Explicit ask |

- **Trust grants — design now, use later** (confirmed): v1 runs pure
  single-approval; after 2–3 weekly reviews, repeated safe approvals can be
  granted as bounded patterns (specific command/parameter/resource — no
  wildcards; revocable; logged in the weekly review).
- **No new agent-level gates** beyond this table + the existing pipeline
  gates (QA, security, deploy) (confirmed).

### State/memory (Q5) — decided 2026-11-25 interview

- **Per-agent workspace** (confirmed): the existing per-identity pattern —
  `pi-agent-<slug>` (alongside `pi-agent-chuck` / `pi-agent-dylan`) for
  session state, plus the durable home `docs/agents/<slug>/` (charter +
  reviews).
- **Per-agent memory namespaces** (confirmed): each agent's LiteLLM key =
  its own mcp_memory identity, **private to that agent**. No cross-access to
  chuck's private memory (agents aren't family — the `household` scope stays
  family-only). Context about chuck flows through task briefs and files
  (charter, docs), not memory reads.
- **Shared domain KB** (Q15, decided 2026-11-26): the third store —
  org-level, per-domain `mcp_knowledge` collections, correctable +
  forgettable. Private memory = what *this agent* learned; the domain KB =
  what *the org* knows. MVV rule-5 test (updated): *if any agent dies, a
  fresh one picks up from files + its own namespace + the shared domain KB
  alone.*
- **Session sync** (confirmed): agents ship session transcripts via
  `session-sync` to the reflection pipeline, same as chuck's sessions.

### Reporting (Q8) — decided 2026-11-25 interview

- **Three surfaces** (settled by earlier decisions): → chuck via the weekly
  review docs; → board via cards + movement; → BA by *consuming* the same
  underlying records (QA/publish logs, board state, spend) — one source, no
  duplicate reporting.
- **BA's org-level KPI digest** (confirmed): weekly cross-agent digest
  (spend per agent, pieces published, QA results, work-mix ratios) at
  `docs/org/kpi/YYYY-WW.md`, alongside the weekly reviews, feeding the
  monthly org review.
- **Learnings flow** (confirmed): learnings that change *how work gets done*
  are promoted to the durable doc at review time (charter "updated <date>"
  note, skill edits via proposals) — no separate learnings repo. Domain
  knowledge is the exception to "at review time": durable facts are
  distilled to the shared KB **ad hoc at discovery time** (Q15).
- **Domain KB activity** (Q15): the weekly review's part-6 KB line (facts
  added/corrected/forgotten per agent + collision log) feeds the BA's KPI
  digest; collisions escalate per Q15 (repeated same-fact collisions or
  >3/week → raised to chuck in the review).

### Domain knowledge (Q15) — decided 2026-11-26

**Question**: where do org/industry domain knowledge live — what the org
knows about a domain (bluebovine positioning/product, the market,
competitors) — and how does it flow?

**Three tiers (decided):**

| Tier | Store | Scope | Mutability |
|---|---|---|---|
| Long-form, durable | Files — goals, charters, briefs, digests, reviews | Org | Edit with "updated <date>" note |
| Distilled, queryable facts | Shared domain KB — `mcp_knowledge` collections per domain (`kb_bluebovine`, `kb_market-smarthome`, …) | Org — all agents read | Correctable + forgettable (`kb_correct`/`kb_forget`) |
| Agent working knowledge | Per-agent private `mcp_memory` namespace (Q5) | Agent | Add-only |

- **Boundary**: private memory = what *this agent* learned; domain KB = what
  *the org* knows. Forcing function: the MVV rule-5 replaceability test — if
  market knowledge lived only in one agent's private namespace, a fresh
  replacement would lose the org's domain model.
- **Why the KB, not memory**: domain knowledge changes (competitor launches,
  revised numbers); memory is add-only, the KB supports correction/forget.
- **Acquisition**: the existing research skills are the pipeline
  (market-research-brief, deep-research, pm-market-analysis) — knowledge
  enters via the platform layer (implication (f)), not agent prompts.
- **Ingestion — ad hoc (chuck 2026-11-26)**: agents distill durable domain
  facts **at discovery time**, not only at review — a research pass that
  yields a durable fact writes it to the domain KB immediately, with
  provenance (source + date). The monthly org review additionally runs the
  **staleness pass** (`kb_forget` superseded facts). No new cron jobs.
- **Contradictions (chuck 2026-11-26)**: when a new fact contradicts an
  existing KB fact, the **owning agent arbitrates** (correct, or keep + note
  the conflict). Every collision is logged in the weekly review.
  **Escalation**: repeated collisions on the same fact, or >3 collisions in
  a week, get raised to chuck in the weekly review for his judgment
  (threshold is a working default — tunable at review).
- **Consumption**: agents `kb_search` at task start (the memory-conventions
  "retrieve before asking" pattern); briefs cite KB facts with provenance.
  Pass by reference, not content.
- **Ownership**: the agent whose charter covers the domain owns its KB —
  named in the charter (Projects section). Own-domain writes are
  autonomous; cross-domain writes are single-approval (Q7 table).

## Research grounding (2026-11-24, via mcp_search)

1. **OKR-driven agentic pattern** (OKR Institute, via
   tarikdavis.co.uk/blog/how-to-write-effective-okrs-for-ai-agents): objectives
   ("what success looks like", business language) + key results ("how success
   is measured") built into the agent's design; the agent owns the outcome and
   plans/self-corrects against the measures. Rules: **outcomes, not activity**
   (no "N prompts written" KRs); **≥1 quality/safety KR per agent OKR**;
   **agents participate in measurement** (track progress, flag at-risk KRs)
   while **humans keep decision rights on direction**; **close the loop** —
   each cycle's results feed the next cycle's OKRs.
2. **Goal-statement writing** (Webex, "Guidelines and best practices for
   automating with AI agent"): the agent's goal/mission line should be short,
   purpose-focused, user-benefit-oriented; no methods, no specifics, no
   multiple unrelated goals, no ambiguity.
3. **Risk-tiered autonomy** (AWS Well-Architected Agentic AI Lens,
   AGENTSEC04-BP02): don't route everything through human review (rubber-stamp
   fatigue) and don't route nothing. Baseline: read-only autonomous, low-risk
   writes single-approval, high-risk (spend, deletion, external comms)
   stricter. **Persistent trust grants**: approve a bounded pattern once
   (specific command/parameter/resource — no wildcards), revocable, auditable,
   tiered by risk. Approval context must include the reasoning chain +
   consequences; timeouts + escalation so agents never stall on a missing
   reviewer.
4. **Goal → task mechanism** (arXiv 2402.02716, LLM-agent planning survey):
   task decomposition is the standard goal→plan→task mechanism with reflection
   loops. The kanban board already *is* the task layer — the goal model plugs
   in above it.

## Framework research (2026-11-24) — `docs/agent-org-framework.md`

A 4-lane research pass (OKR theory, org-design theory, multi-agent LLM
evidence, control/feedback theory) was distilled into
`docs/agent-org-framework.md` (full notes in `docs/agent-org-research/`). Core
thesis: **an agent org is a control system, not a social system** — design the
sensors (verification), setpoints (OKRs), loops (cadence). Its Minimal Viable
Version is 5 rules; here's how they map to what we've already decided:

1. **One objective, 3–5 machine-measurable KRs** — already the S13 design:
   every KR has definition/source/target/cadence, and `proxy` KRs carry a
   validation note. The framework's one hardening: a KR with *no* machine
   check (not even a deferred one) is rejected at goal-setting time.
2. **One supervisor, N workers, depth 1; default N=1** — consistent with the
   roster: chuck is the supervisor, the 4–5 standing agents are peers, and no
   agent spawns its own sub-team. Anthropic evidence (verified in the research
   pass): production systems run exactly 2 levels deep; multi-agent costs ~15×
   tokens and only pays off on parallelizable, verifiable breadth. Right-sizing
   (1 agent for lookups, 2–4 for comparisons, 10+ for parallel breadth) should
   go in the tasking design (open question 3).
3. **Deterministic done-checks; no self-grading at the gate** — this is the
   answer to open question 12 (quality-metrics monitoring mechanism): every
   artifact class gets an external predicate (content QA pass, tests, schema,
   resolvable citations), and the BA consuming QA/publish records is exactly
   the "one source, no duplicate reporting" the plan already chose. Agents
   propose; the pipeline disposes.
4. **Three loops: per-task (seconds), per-batch (fresh-context review),
   per-milestone (KR scoring + adapt)** — the decided cadence already *is*
   this: kanban QA stage = fast loop, weekly agent review = mid loop, monthly
   org-goal review = slow loop. Two additions worth adopting: (a) **bounded
   retries + hysteresis** in tasking (same failure > N → escalate, don't
   thrash); (b) **fresh-context reviewer** for quality gates — critics who saw
   the worker's reasoning rubber-stamp it (documented LLM sycophancy).
5. **All state in files; every agent replaceable** — consistent with open
   question 5 (state/memory): charters, `docs/agents/<agent>/reviews/`, and the
   memory skills are the mechanism. The framework's test: *if any agent dies
   right now, can a fresh one pick up from files alone?* Use it when designing
   the per-agent workspace.

New implications not yet in the plan: (a) the **delegation contract** — every
task brief carries objective + output format + tools + explicit boundaries
(Anthropic's dominant reliability lever); (b) **pass by reference, not
content** — agents write structured outputs to disk and hand over references;
(c) **per-agent spend attribution** (open question 1) is the right cost control
given the ~15× multi-agent token multiplier; (d) evaluate agent **outcomes +
process, not steps** — agents take different valid paths.

**Status**: research done 2026-11-24; the 5-rule MVV is the proposed
pre-flight check for standing up the first agent (Q13) — discuss before build.

### New implications from the org-theory lane (discussed 2026-11-25)

From the org-theory research lane (`docs/agent-org-research/org-theory.md`,
9 rules; full distillation in `docs/agent-org-framework.md` §2). Four
implications not yet in the plan — to be folded into the tasking design:

- **(e) The communication graph is a tasking decision (Conway's inverse)** —
  the agents' interaction topology *becomes* the system architecture. Ours:
  agents interact via the kanban board + files, **not with each other**
  (depth 1, no agent-to-agent delegation). State this topology explicitly in
  the tasking design.
- **(f) Name the platform/product layering (Team Topologies)** — skills +
  MCP tools = platform layer; role agents = thin product layer. Consequence:
  new capabilities go into the platform (skills/tools), **not** into agent
  prompts.
- **(g) Per-task-type configuration (Mintzberg)** — content production =
  pipeline with QA gates (the kanban QA stage); research = specialist; novel
  problems = multi-perspective. Mostly a property of role + task type,
  encoded in the role skills (WS2), not new machinery.
- **(h) Standardize outputs before debate (Galbraith)** — agent artifact
  outputs get schemas/structure before we ever consider agent-to-agent
  debate or mutual adjustment.

## S13 — `okr` skill (ACCEPTED 2026-11-24 — BUILT 2026-11-25, registered)

**Purpose**: help chuck (or an agent) write org + agent OKRs, and verify the
ladder — that agent OKRs line up to the org's OKRs.

**When to use**: setting or updating org goals (per domain); drafting or
reviewing an agent charter's objectives + KRs from the org goals; a ladder
alignment check ("is the work actually serving the goals?"); an OKR cycle
closeout (progress review → next cycle's draft).

**Inputs**: `docs/org/goals.md` (or `homelab_vision.md` + domain context when
org goals don't exist yet); board state (what work exists / is in flight); BA
reports + KPI data (once G3 wiring lands); prior-cycle records
(`docs/agents/<agent>/reviews/`); shared domain KB (domain context for the
monthly pass — Q15).

**Steps**:

1. **Frame the domain** — which domain(s) (homelab / bluebovine — investhub
   out of scope, chuck-only); what changed since the last cycle (board
   movement, BA data, chuck's direction).
2. **Draft org objectives** — 1–3 per domain. Objective in outcome language
   ("make X feel effortless for Y", not "deploy Z"). 2–4 KRs each.
3. **Write KRs** — each KR gets **definition, source, target, cadence**.
   Rules:
   - **Outcomes over activity** — "N posts written" is a leading indicator,
     not the KR; the KR is the outcome the posts drive (labeled leading
     indicators allowed alongside).
   - **No data? Guess** — mark `proxy` with a validation note ("validate when
     Plausible/data-hub lands"). First pass is guesses by design.
   - **Mandatory quality/safety KR** on every domain + every agent (decided
     2026-11-24).
4. **Derive agent objectives** — for each agent in scope: 1–2 objectives,
   each explicitly laddered to a domain org goal (cites the goal it serves);
   2–4 KRs per objective.
5. **Alignment check** (the verification step — the skill's core value):
   - every agent objective maps to a domain org goal (no orphans)
   - every KR has definition/source/target/cadence (or is explicitly
     `proxy`/guess)
   - no activity-metric KR dressed up as an outcome
   - **coverage**: every org goal is served by ≥1 agent (or explicitly marked
     "chuck-only" / "no agent yet")
   - emit an **alignment report**: table of org goal → agents serving it →
     KRs → data-source status
6. **Emit artifacts** — updated `docs/org/goals.md` (per-domain sections,
   "updated <date>" note), agent charter drafts (objectives/KRs sections) for
   chuck's review, the alignment report.

**Quality bar**: objectives in outcome language; 2–4 KRs per objective; every
KR has the four fields; proxy KRs flagged; ladder links explicit; alignment
report ships with every pass.

**Grounding**: OKR Institute OKR-driven agentic pattern (outcomes over
outputs; quality KR; human decision rights; close the loop); Webex goal-writing
do's/don'ts (short purpose-only mission lines); chuck's 2026-11-24 decisions
(per-domain org goals; agent-suggested charters; proxy KRs OK; exec override
with pushback; soft enforcement + BAU).

**Status**: **accepted 2026-11-24 (chuck); built + registered 2026-11-25**
(`agents-skills/okr/` — 7/7 YAML guard tests pass; Skill Hub live, gateway
list verified). Belongs to WS3 (the org/agent goal system), not workstream 2.

## Remaining open design questions

(From the 2026-11-22 seed list; goal model — Q2 — is now decided above.)
**All questions decided** (Q13 first agent decided 2026-11-26, revised
2026-11-27 — product first). Q15 (domain knowledge) decided 2026-11-26.

1. ~~**Identity**~~ — **decided 2026-11-25 (chuck)**: one LiteLLM key per
   agent (the `USER_KEYS` pattern extended to agents), created when the agent
   stands up. All agents start with the **same tool set** — no per-role
   capability scoping yet (keys structured so scoping can be added later; it
   remains a guardrails/Q7 decision). Spend: **per-agent visibility from day
   one, no hard caps** — soft thresholds in the weekly review (spend line in
   the work-mix check); consider budget caps after a few iterations with real
   data. **Slugs**: `product` (PM), `analyst` (BA), `strategist` (marketing
   strategist), `marketing` (content marketer). **Researcher out of the
   roster for now** (the research skill exists; add a key when/if it stands
   up). Slugs drive key names, charter paths
   (`docs/agents/<slug>/charter.md`), and future memory namespaces.
2. ~~Goal model~~ — **decided 2026-11-24** (above).
3. ~~**Tasking**~~ — **decided 2026-11-25** (single queue; **all agent work
   incl. exec TODOs = board cards**; self-plans via review; 4-element brief +
   flag-don't-guess; clarifying questions on exec TODOs; sub-agent capacity
   decided — item 14).
4. ~~**Periodic review protocol**~~ — **decided 2026-11-25** (weekly 7-part
   review at `docs/agents/<slug>/reviews/YYYY-WW.md`; monthly org review at
   `docs/org/reviews/YYYY-MM.md` — the only place goals change).
5. ~~**State/memory**~~ — **decided 2026-11-25** (`pi-agent-<slug>`
   workspaces; per-agent private mcp_memory namespaces, no cross-access to
   chuck's memory; context via briefs/files; agents use `session-sync`).
6. ~~**Scheduling**~~ — **decided 2026-11-25** (kanban events + chuck + cron:
   `weekly-agent-reviews` Fri 15:00 CT, `monthly-org-review` first Fri 15:00
   CT; self-plan cards idea/grooming → review → backlog; non-stacking
   reviews — skip the next cycle if the previous one is unanswered).
7. ~~**Guardrails**~~ — **decided 2026-11-25** (autonomy tier table approved
   — blog publish = autonomous, quality-gated; trust grants design-now/
   use-later; no new agent-level gates beyond the table + existing pipeline
   gates).
8. ~~**Reporting**~~ — **decided 2026-11-25** (chuck via weekly reviews,
   board via cards, BA consumes the same records — one source; BA's weekly
   org KPI digest at `docs/org/kpi/YYYY-WW.md`; learnings promoted to
   durable docs at review time).

New from the 2026-11-24 interview:

9. ~~Org goal cadence~~ — **decided 2026-11-24**: org goals monthly; agent
   reviews weekly to start → monthly as confidence grows.
10. ~~InvestHub placement~~ — **decided 2026-11-24**: out of scope for agents
    (chuck's own; board for building, no agent handover).
11. ~~BAU framing~~ — **decided 2026-11-24**: `bau` tag + work-mix check
    (BAU vs OKR vs exec) in the periodic review.
12. ~~**Quality metrics**~~ — mandatory quality/safety KR decided
    (2026-11-24); **monitoring mechanism decided 2026-11-25** (via the 4.1
    + 8.1 decisions): external predicates per artifact class (QA pass,
    tests, schema, resolvable citations — MVV rule 3), quality-KR status in
    the weekly review (part 4), and the BA's KPI digest consuming the same
    records.
13. ~~**First agent**~~ — **decided 2026-11-26, revised 2026-11-27 (chuck):
    stand up `product` first** (product first — the 2026-11-27 revision
    supersedes the 2026-11-26 strategist-first order; `strategist`/
    `marketing`/`analyst` stand up alongside but stay OFF — keys + workspaces
    only, no cron targeting, no board cards, charters not approved — until
    chuck activates them). Was deferred to the first org-goals pass
    (2026-11-25): the goals show which agent has the sharpest starting KR
    (candidates: `marketing` for the homelab content goal, `product` for the
    bluebovine product-definition goal).
14. ~~**Sub-agent capacity / concurrency**~~ — **decided 2026-11-25** (model
    assignment, not separation; `AGENT_CONCURRENT_TASKS=1` + existing
    `NON_MEDIA_CONCURRENT_TASKS=2` = 3-session budget, env-var tunable;
    interactive-first hard rule; v1 single-session agent runs, fanout only on
    chuck's explicit ask; board as the gate; slots classified by executor
    identity).
15. ~~**Domain knowledge**~~ — **decided 2026-11-26 (chuck)**: three tiers —
    files (long-form), shared per-domain KB (distilled facts, correctable +
    forgettable), per-agent private memory (working knowledge); agents
    distill ad hoc at discovery time; the owning agent arbitrates
    contradictions, with repeated collisions (>3/week or same-fact repeats)
    raised to chuck in the weekly review; own-domain KB writes autonomous,
    cross-domain single-approval (Q7 table). See "Domain knowledge (Q15)".

## Pending — all resolved 2026-11-25

- ~~**Draft vs build first**~~ — **decided 2026-11-25 (chuck)**: build the S13
  `okr` skill first, then run it for the first org-goals pass.
- **Org-goals anchoring questions (chuck)**:
  1. ~~Homelab~~ — **decided 2026-11-25 (chuck)**: the **personal-interest
     content is the main goal** (arcade/guitar/songs/RPGs/cars). "The virtual
     team ships real work" (harness/agents) is the means, not the goal —
     its upkeep is BAU, not an objective (resolved 2026-11-25: "learning by
     building" lives inside the content; see "Org-goal anchoring").
  2. ~~Bluebovine~~ — **decided 2026-11-25 (chuck)**: **both** — credible/
     traffic content **and** defining the product (research/etc.) this cycle.
     The product track is a **phase**: define → iterate toward product-market
     fit; the monthly org review is the shift point (rewrite the objective at
     the cycle boundary, don't append a third).
  3. ~~Scale~~ — **decided 2026-11-25 (chuck)**: 1 objective for homelab,
     2 for bluebovine this cycle; default 1–2 per domain per cycle, 3 only
     with explicit justification (okr alignment report surfaces it). Harness/
     learning-by-building = BAU for now (see "Org-goal anchoring").
- ~~**Phase 2 exit smoke** (tipcalc E2E test project, commits `dc13a0a` /
  `0ddd3f1`)~~ — **done 2026-11-24**: board 6/6 done, pipeline validated
  (build + security gate + content skills); test infra torn down 2026-11-24
  (`c5f989e`/`6fec099`); `todo_agent_skills.md` status line updated.

## Next steps (build order confirmed 2026-11-25)

1. ~~chuck reviews the S13 `okr` proposal~~ — **accepted 2026-11-24**.
2. ~~Build S13 `okr`~~ — **done 2026-11-25** (`agents-skills/okr/SKILL.md`;
   7/7 YAML guard tests pass; registered + enabled in the Skill Hub via
   `skill-hub-register.sh` — "1 added, 0 failed"; gateway list verified).
3. ~~First org-goals pass~~ — **done 2026-11-26** (`docs/org/goals.md` cycle
   2026-12; alignment report `docs/org/alignment/2026-11-26-first-pass.md`;
   4 charters `docs/agents/<slug>/charter.md` — product **APPROVED
   2026-11-27**; the other 3 pending activation — **activated 2026-11-27,
   see item 11**).
   The monthly cycle starts; Q13 first-agent decision pending (recommendation:
   `product`).
4. ~~First agent (Q13)~~ — **decided 2026-11-26, revised 2026-11-27 (chuck):
   stand up `product` first** (product first — the 2026-11-27 revision
   supersedes the 2026-11-26 strategist-first order; `strategist`/
   `marketing`/`analyst` stand up alongside but stay OFF — keys + workspaces
   only, no cron targeting, no board cards, charters not approved — until
   chuck activates them). Charter drafts in `docs/agents/<slug>/charter.md` —
   reviewed with chuck 2026-11-26 (slow-burn targets, 6-pillar set, market =
   PM consulting, O2-before-O1); **product charter completed (all 7 sections)
   + APPROVED 2026-11-27**.
   **Prerequisite: security Phase 13 (automated key management) lands first**
   (chuck 2026-11-26) — **MET 2026-11-26** (Phase 13 DONE 2026-11-26): agent
   keys via the new `key add-agent`/`key rotate` ops layer, not the manual
   5-step loop.
5. ~~First agent's charter draft~~ — **done 2026-11-27**: product charter
   completed (all 7 sections) and **approved by chuck 2026-11-27** (no changes
   requested) — `docs/agents/product/charter.md`.
6. Stand up the first agent: `pi-agent-<slug>` workspace, LiteLLM key
   (model assignment per work type), `AGENT_CONCURRENT_TASKS` slot,
   `weekly-agent-reviews` + `monthly-org-review` cron jobs, its domain KB
   ownership named in the charter (collection creates on first write — Q15).

   **Step-6 build checklist** (added 2026-11-26 — the thin WS3 build layer;
   everything else in the framework reuses existing infrastructure):

   - [x] `AGENT_CONCURRENT_TASKS` slot category (default **1**) — env var in
         `data/ai-kanban/harness/mcp/servers/kanban/.env` (+ `.env.example`),
         read in `src/config.ts`; slot classification by **executor identity**
         (cards assigned to a standing agent count against this slot regardless
         of work kind) in the orchestrator (`src/mcp/server.ts`) — **done
         2026-11-27**: dev clone `task/17` (`626eb61` + `4a67b91` +
         `5266831`, pushed to GitHub); live build context synced (file-diff
         clean); `mcp_kanban` rebuilt + healthy with the env vars live in the
         container; full suite green (237 tests — 236 pass, 1 skip, 0 fail,
         `npm test`)
   - [x] Per-agent LiteLLM key — mint via `./homelab.sh key add-agent <slug>
         [--work-type coding|writing] [--capability read|control|admin]`
         (Phase 13 delivered `key add-agent` 2026-11-26; proxy API; token →
         `.env` as `LITELLM_KEY_<SLUG>`); per-key model access = work-type
         model (`matrix-coder` for product/analyst, `matrix-copywriter` for
         strategist/marketing) **plus the kanban pipeline model**
         (`KANBAN_MODEL`, default `matrix-coder` — the pipeline runs all
         sessions on it; see item 12 for the 403 bug this prevents); key
         lifecycle per security_todo.md **Phase 13**
         (one `.env`, `key rotate`, alias-based kanban capability map,
         `MEMORY_USER_KEYS` entry) — **done 2026-11-27**: 4 keys active in
         LiteLLM (product/analyst → matrix-coder; strategist/marketing →
         matrix-copywriter + matrix-coder); `.env` wired; skill-runner +
         mcp_kanban in sync per key-sync-check (20 pre-existing drifts in 8
         other containers — see build report)
   - [x] Cron jobs in `scheduler/schedules.json` (hot-reload,
         America/Chicago): `weekly-agent-reviews` Fri 15:00, `monthly-org-review`
         first Fri 15:00 — **done 2026-11-27**: both jobs registered (12
         schedules total), hot-reload verified via the skill-runner API
         (enabled, next_run_at set). **GAP CLOSED 2026-11-27**: the
         `weekly_agent_reviews` / `monthly_org_review` skill modules are
         BUILT (`skills/weekly_agent_reviews/` + `skills/monthly_org_review/`
         — 75/75 + 108/108 unit tests; real bootstrap weekly review
         `docs/agents/product/reviews/2026-W48.md`; monthly gate-skip proof
         + forced temp run; both registered in the Skill Hub) — the first
         real cron fire (2026-11-27 15:00 CT) will now run the real skills;
         conservative-apply design: the monthly goals rewrite + `kb_forget`
         are PROPOSALS by default, applied only with explicit params
         (`apply_goals` / `apply_kb_forget`, default false) — the run's
         build report (retired 2026-11-28) carried the per-item evidence
   - [x] `pi-agent-<slug>` workspace under `data/ai-kanban/` (alongside
         `pi-agent-chuck` / `pi-agent-dylan`) — **done 2026-11-27**:
         `pi-agent-{product,analyst,strategist,marketing}` created
   - [x] Charter names the agent's domain KB ownership (Q15) — the collection
         creates on first write, nothing to pre-create — **done 2026-11-27**:
         product charter completed (all 7 sections; owns `kb_bluebovine` —
         creates on first write) and **APPROVED by chuck 2026-11-27**
7. First weekly review cycle — and the monthly clock starts.
   **Review skill modules BUILT 2026-11-27** (`skills/weekly_agent_reviews/`
   + `skills/monthly_org_review/`): the weekly skill generates the 7-part
   review per active agent (non-stacking gate; bootstrap runs
   unconditionally — the product bootstrap review
   `docs/agents/product/reviews/2026-W48.md` exists, all 7 parts, honest
   content: agent stood up 2026-11-27, 0 board cards, spend $0.00); the
   monthly skill gates on first-Friday-of-month (2026-11-27 = 4th Friday →
   real invocation skips, nothing written) and uses the **conservative-
   apply design**: the goals rewrite + `kb_forget` are PROPOSALS by default
   (sidecar `docs/org/goals.proposed-YYYY-MM.md` + candidates list),
   applied only with explicit params `apply_goals` / `apply_kb_forget`
   (default false — org-doc edits are single-approval per the Q7 table).
   Both registered in the Skill Hub ("2 added, 0 failed"); the first real
   cron fire — **today 2026-11-27 15:00 CT** (both jobs enabled,
   `next_run_at` 2026-11-27T15:00 CT per the skill-runner API) — will now
   run the real skills. Evidence: the per-item "done" notes above (the run's
   build report was retired 2026-11-28).
8. **Agents master switch (chuck's ask, 2026-11-27)** — one global on/off
   for ALL standing agents, flippable from any client session via MCP.
   **DONE 2026-11-27** (dev clone `task/18`, `03f08dc`, pushed; live build
   context synced; `mcp_kanban` rebuilt + healthy):
   - Durable kv state (`agents_master_switch`), **fail-safe default OFF** —
     a missing or malformed row means agents are disabled; only an
     explicit `on` enables them. Survives restarts.
   - Admin-only MCP tool `agents_switch` (28th tool): no args reads the
     state; `state: on|off` sets it, stamped with the caller's USER_KEYS
     alias (`setBy`) for the audit trail. Flippable from any client
     session through the LiteLLM proxy.
   - Orchestrator gate: when OFF the agent slot is zeroed on tick (no
     agent-owned cards picked up) and explicit `start_task` on an agent
     card → 409. In-flight agent tasks run to completion (v1: the switch
     gates starts, not mid-session kills). Non-agent board work is
     unaffected.
   - **Initial state: OFF** (chuck's ask) — live-verified 2026-11-27:
     read → `{state: off, setBy: chuck}`; a probe agent card (owner=product)
     stayed in backlog across 3 ticks with the switch OFF and an explicit
     `start_task` was rejected with the switch message; flip ON → the card
     started (backlog → running); probe data cleaned up, board back to
     16 done. Full suite green (244 pass, 0 fail, 1 pre-existing skip).
   - To activate the agent org: `agents_switch({state: "on"})` from a
     client session (admin key).
9. **Switch v2 — hard-kill semantics + per-agent switches (chuck's ask,
   2026-11-27)** — extends item 8: (a) flipping OFF now also STOPS
   in-flight agent work (session abort + task back to the backlog, where
   it auto-resumes when the switch is on); (b) per-agent (per-slug)
   switches alongside the global. **DONE 2026-11-27** (dev clone
   `task/18`, `c056d6f` + `e03e26c`, pushed; `mcp_kanban` rebuilt +
   healthy):
   - kv document is now `{global, slugs}` — a per-slug entry overrides the
     global for that agent only (global OFF dominates; absent slug entry
     -> global governs; malformed slug entry -> OFF, fail-closed). v1 rows
     read as the global entry — no migration.
   - `agents_switch({slug, state})` — per-slug set; the slug must be a
     known AGENT_SLUGS entry (no phantom entries). No args still reads the
     full state (global + slugs).
   - Hard-kill: the orchestrator's tick runs a kill pass — running,
     non-paused agent tasks with a live pipeline whose effective switch is
     OFF get their session aborted and are returned to the backlog (audit
     event with the scope-specific reason). A missed kill (session not yet
     launched) is retried on the next tick — the gate is enforced every
     pass.
   - Live-verified 2026-11-27: the v1 row read as global (backward
     compat); global + slug round-trip with cross-preservation; unknown
     slug rejected; a running probe task killed by a per-slug OFF (backlog
     + audit reason), auto-resumed on the slug ON, then killed again by a
     global OFF (global reason). Full suite: 254 pass, 0 fail, 1
     pre-existing skip.
10. **Mission-brief hardening (bug fix, 2026-11-27)** — the live probe
    (item 9's E2E) exposed the unguarded spec-field pattern in three
    consumers: `buildMissionBrief` (sessions.ts), `buildQaPrompt` (qa.ts —
    the probe's task session ran fine, then crashed in QA with the same
    `Cannot read properties of undefined (reading 'length')`), and
    `slugify(spec.goal)` in the blog deploy handler. All now treat the DB
    spec as runtime-untrusted (Array.isArray guards + placeholder
    degradation) — a minimal spec ({goal} only) or corrupt
    steps/acceptance no longer crashes the session pipeline or the QA
    gate. **DONE 2026-11-27** (same commits as item 9).
11. **Activate the other 3 agents (chuck: "get that done & in place",
    2026-11-27)** — the Q13-revised hold is lifted: `strategist` /
    `marketing` / `analyst` are now ACTIVE alongside `product`.
    **DONE 2026-11-27**:
   - Charters completed (all 7 sections — Identity / Projects /
     Constraints / Autonomy tiers / Quality metrics added; Objectives +
     Key results unchanged from the 2026-11-26 okr first pass, reviewed
     with chuck that day) and **APPROVED 2026-11-27**:
     `docs/agents/{strategist,marketing,analyst}/charter.md`. Domain-KB
     allocation (Q15): strategist owns `kb_market-pm-consulting`,
     marketing owns `kb_homelab-content`, analyst owns no domain KB
     (measurement layer). Product charter got a one-line clarification:
     role artifacts land in the homelab repo via the project-12 workspace
     (G12).
   - `weekly_agent_reviews` skill: `INACTIVE_AGENTS` is now empty (all 4
     active; the gate is retained for future deactivations), `AGENT_KB`
     maps all 4 (analyst → None, handled with an honest KB line),
     `DEFAULT_AGENTS` = all 4; `skill.yml` description + defaults updated.
     Suite 84/84 (3 tests updated for the new activation state).
   - `scheduler/schedules.json`: `weekly-agent-reviews` `agents` param now
     `[product, strategist, marketing, analyst]` — hot-reload verified via
     the skill-runner API (all 4 targeted, next fire 2026-11-27 15:00 CT).
   - First-work cards on the board (project 12 — the G12 role-artifact
     repo; task owner = idea owner per `services/icebox.ts`): task 20
     product (Bluebovine market analysis — O1 KR1), task 21 strategist
     (homelab content strategy — O2 first per the 2026-11-26 sequencing),
     task 22 marketing (content inventory bootstrap — O1 KR3
     prerequisite), task 23 analyst (KPI digest baseline — O1 KR1). All
     backlog with full specs (goal + serves: tag, 5 steps, 5 acceptance
     criteria, notes with charter/goals/G12 context). The agent slot (1)
     serializes them — task 20 (product) started running on the first tick
     after the switch flip.
   - Agents switch: **global ON** (setBy: chuck) — all 4 agents active;
     per-slug switches available for pausing any single agent
     (`agents_switch({slug, state})`).
12. **Agent-key model access — kanban pipeline model (bug fix, 2026-11-27)**
    — the first live agent run exposed a key-model mismatch: the
    strategist/marketing keys were minted with `models=[matrix-copywriter]`
    only (work-type default), but the kanban pipeline runs **all** sessions
    (task work + QA) on `KANBAN_MODEL=matrix-coder`. Every LLM call for
    those two agents 403'd (`key_model_access_denied`); the session SDK
    swallowed the error and returned empty content, so the task "completed"
    with nothing and QA got "no parseable verdict" → 2 rounds →
    needs_attention (tasks 21 + 22; product/analyst — matrix-coder keys —
    were unaffected). **Fix** (2026-11-27):
   - Live keys: `key update strategist|marketing --models
     matrix-copywriter,matrix-coder` — the work-type model stays for direct
     (non-kanban) key usage; the pipeline model is added for the kanban
     pipeline. Verified: both keys now complete a matrix-coder chat call.
   - `key add-agent` (lib/litellm-keys.sh): the mint payload now includes
     the work-type model **plus** the kanban pipeline model (`KANBAN_MODEL`
     env, default `matrix-coder`), deduped when they're the same — future
     agent keys can't hit this again.
   - Tasks 21 + 22 restarted via `restart_task` with a resolution note
     (root cause + fix); no work was done on the failed runs (empty
     sessions), so they resumed fresh from the mission brief.
   - Design note: the work-type model assignment governs the agent's
     **direct** key usage (skill-runner, etc.); the kanban pipeline is a
     coding pipeline (git/commits/QA/deploy) and runs on matrix-coder for
     every agent. Per-owner pipeline models (writing agents' task work on
     matrix-copywriter inside the pipeline) would be a harness change
     (per-profile model selection in `sessions.ts`) — not built; the keys
     have access to both models either way.
   - Secondary robustness gap (not fixed — noted): a session whose first
     LLM call fails with an auth error should fail loudly (needs_attention
     with the real error) rather than surface as an empty completion. The
     key fix removes the trigger; the loud-fail hardening is a follow-up
     harness improvement. **→ item 14 (chuck: build it alongside item 13).**
13. **`merge_task` MCP tool (chuck's decision 2026-11-27 — option b of the
    merge-path question, item after the first live agent run)** — the
    deploy stage pushes the task branch; nothing merges to main. Agent
    artifacts (e.g. task 20's `docs/roles/pm/market-analysis-bluebovine-*.md`,
    task 23's `docs/org/kpi/2026-W48.md`) sit on pushed branches until
    someone merges. **Decision (chuck): build an admin `merge_task` MCP
    tool** — chuck merges from any client session after reviewing the diff
    (the Q7 single-approval gate for org-doc edits, made mechanical). NOT
    auto-merge (violates the git-flow hard rule — main is only touched
    through the project's explicit deploy gate — and Q7).
    **BUILT + LIVE 2026-11-27** (dev clone `task/19`, `f3a8d36`, pushed;
    synced + `mcp_kanban` rebuilt; 29th MCP tool, admin-only):
   - Admin-only (capability gate, same pattern as `agents_switch`).
   - Input: `task_id` + optional `note` (recorded in the merge commit +
     audit event).
   - Eligibility: task state `done` (QA passed + deploy pushed the
     branch), kind `code`, project has `repo_url` + `default_branch`.
   - Behavior: in the task workspace (fresh clone if the workspace was
     cleaned up): fetch origin's default branch, merge the task branch
     with a merge commit (`merge task/<id>: <idea text>` + note), push the
     default branch. A merge commit (not squash) keeps the task branch's
     history attributable; the task id in the message is the audit link.
   - Idempotent: if the branch is already merged into the default branch
     (`git merge-base --is-ancestor`), return a no-op "already merged" —
     never a failure.
   - Conflict → rejected with a clear message (the task stays `done`; the
     branch stays pushed; chuck resolves manually or restarts the task
     with a resolution note). Never a partial merge.
   - Audit: a `merge` task_event (`{branch, defaultBranch, mergeCommit,
     note, by}`) + the merge commit message.
   - The first real uses: task/20 (product market analysis) + task/23
     (analyst KPI digest) — pending chuck's review of the diffs. **task/21
     (strategist content strategy) merged into main 2026-11-27 during the
     E2E** (the task was done — QA passed; the merge was a legitimate
     eligibility pass, not a gate bypass) — the strategy doc is now at
     `docs/roles/marketing-strategist/strategy/homelab.md` on main.
   - **Live E2E 2026-11-27** (probe task 24 / branch probe/merge-e2e,
     torn down after): dylan (control) rejected with the capability
     message; the real merge produced a merge commit on main
     (`a4766ca`); the repeat call returned `{alreadyMerged: true}` (no-op,
     never a failure); audit `merge` task_events recorded
     (`{by, note, branch, mergeCommit, defaultBranch}`).
14. **Session loud-fail hardening (chuck: with item 13, 2026-11-27)** —
    item 12's root-cause chain showed the failure mode: an LLM API error
    (403) inside a session is swallowed by the SDK and surfaces as an
    empty assistant message → the task "completes" with nothing → QA gets
    "no parseable verdict" → 2 rounds → needs_attention with a
    misleading reason. **Fix: the session pipeline must distinguish an
    API error from a normal completion** — a failed LLM call (auth/4xx/
    5xx/stream error) throws a typed error out of the session runner; the
    orchestrator catches it and moves the task to needs_attention with
    the REAL error (the HTTP status + message), for task sessions AND QA
    sessions. An empty-but-successful response (HTTP 200, no content —
    the matrix-copywriter reasoning quirk) is a separate case: the
    session runner retries once before treating it as completion.
    Test: a mock session that throws an auth error → task ends in
    needs_attention with the error text (not "no parseable verdict").
    **BUILT 2026-11-27** (dev clone `task/19`, `7df1c1e`, pushed; live in
    the rebuilt `mcp_kanban`): `SessionApiError` (status + message) from
    error-bearing SDK events / a rejecting prompt; 200-empty → one
    `EMPTY_RETRY_PROMPT` retry; orchestrator → needs_attention with the
    real error for task AND QA (a QA API error consumes one round, not
    two silent ones); 10 new tests (sessions x8 + orchestrator x2).
15. **Per-owner pipeline models (chuck's board improvement, 2026-11-27)**
    — the pipeline currently runs every session on `KANBAN_MODEL`
    (matrix-coder) regardless of the agent. The work-type model assignment
    (item 12's design note) only governs direct key usage. **Decision:
    the pipeline honors a per-owner model map.**
    Design (decided 2026-11-27):
   - New env `KANBAN_OWNER_MODELS` — `alias:model` pairs (same parsing
     style as `AGENT_SLUGS` / `KANBAN_MCP_KEY_CAPABILITIES`), e.g.
     `strategist:matrix-copywriter,marketing:matrix-copywriter`. Empty /
     absent → current behavior (every session on `KANBAN_MODEL`).
   - `sessions.ts`: each owner KeyProfile gets its own model (the profile
     already has its own ModelRuntime + agent dir — the models.json is
     built per profile with that model + its /model/info cost rates).
     All sessions for an owned task (task work + QA + retries) run on the
     owner model, billed to the owner key; service sessions (summary,
     deploy, non-owned) run on `KANBAN_MODEL`.
   - Safety: item 12 already granted every agent key access to BOTH
     models, so a mapped model can't 403; an unknown model name in the
     map fails at boot (config validation), not mid-session.
   - `/health` surfaces the owner-model map (alongside agentSlugs).
   - Live wiring: `KANBAN_OWNER_MODELS=strategist:matrix-copywriter,
     marketing:matrix-copywriter` (product/analyst omitted = default
     matrix-coder) — wired in `compose/compose.mcp.yml` + `.env`.
   - Interaction with item 17: a writer's task work on
     matrix-copywriter + QA on the service model (matrix-coder) IS the
     cross-model review — the Phase-1 sycophancy mitigation falls out of
     this design. **CORRECTION (see item 17): as built, QA runs on the
     owner model too — cross-model QA is not automatic.**
   - **LIVE 2026-11-27** (same `task/19` commit; `mcp_kanban` rebuilt +
     healthy; `/health` reports `ownerModels: {strategist:
     matrix-copywriter, marketing: matrix-copywriter}`; boot validation of
     the mapped models passed). Note: the first live agent run (tasks
     20-23) completed on the PRE-rebuild container — all matrix-coder per
     the usage rows; the mapping applies from the next owned run.
16. **Per-model usage surfacing (chuck's board improvement, 2026-11-27)**
    — the `usage` table already records `model` per row (plus `role`,
     `owner`, `thinking`); the gap is surfacing: reports + `task_status`
    aggregate by role only. **Decision: add the model dimension to the
    existing aggregates.**
    Design (decided 2026-11-27):
   - `reports.ts`: `byModel` alongside `byRole` (task-level + project-
     level report shapes) — tokens in/out + cost per model.
   - `task_status`: usage total + by role + **by model**.
   - No schema change (the column exists); the existing `task_id` index
     covers the per-task aggregates. Skill-side consumption: the monthly
     org review consumes `byModel` from 2026-11-27 (item 19); the weekly
     review skill still reads per-key totals from LiteLLM `/spend/keys`
     (per-key, not per-model — fine for its work-mix check).
   - **BUILT + LIVE 2026-11-27** (dev clone `task/19`, `c47f87b`, pushed;
     live in the rebuilt `mcp_kanban`): `byModel` (tokensIn/tokensOut/
     cost) at every `byRole` level in reports + task_status + GUI report;
     the first live agent run's usage rows (tasks 20-23: task/qa roles,
     per-model split) confirm the recording path end-to-end.
17. **Fresh-context QA reviewer (DECIDED 2026-11-27: item dropped — the
    QA gate itself made fresh-context + requirements-only)** — research
    implication 4b: critics who saw the worker's reasoning rubber-stamp it
    (documented LLM sycophancy). **chuck's decision 2026-11-27: drop the
    separate-reviewer item for now** (one model with capacity to do a lot
    at once — a second reviewer session doubles the cost for marginal
    benefit), **but make sure QA is a separate turn with fresh context —
    just the requirements for what's being built**, so it isn't biased by
    the worker's claims.
    **DONE 2026-11-27** (dev clone `task/19`, `625206d`, pushed; synced +
    `mcp_kanban` rebuilt): the QA gate was already a separate turn (a
    fresh session per round, its own `QA_SYSTEM_PROMPT`, no worker
    transcript) — the one bias vector was the worker's **completion
    summary** in the QA prompt. Now:
   - `buildQaPrompt`: the prompt carries ONLY the requirements (spec:
     goal/steps/acceptance/kind) + the diff. The diff is the evidence;
     the spec is the requirements. The completion-summary section is
     gone; `QaRunContext.completionSummary` removed (the orchestrator no
     longer passes it — a dead field carrying the worker's claims invites
     re-adding them; the task's own summary still flows to `completeTask`).
   - `QA_SYSTEM_PROMPT` states the fresh-context contract explicitly:
     the reviewer was given only requirements + diff, has NOT seen the
     task agent's reasoning or claims, and must judge the work on the
     evidence in the diff alone.
   - Tests: buildQaPrompt asserts requirements + diff present AND the
     summary/claims absent; the orchestrator-deploy test asserts QA
     received the spec (not the summary). Suite green (288 tests).
   - The separate-reviewer-session design (Phase 2 below) is RETIRED
     with the item — if revisited, it would be a new decision.
    **Retired design (for the record) — two phases, decision point
    between them.**
    **Design — two phases, decision point between them.**
    **CORRECTION 2026-11-27 (item 15 as built):** the Phase-1(a) cross-model
    claim does NOT hold — item 15 routes ALL sessions for an owned task
    (work + QA + retries) to the owner model, so QA runs on the SAME model
    as the worker (strategist/marketing QA on matrix-copywriter, verified
    in the first live run's usage rows). Cross-model QA would be a
    deliberate routing change (QA on the service model) — not built. Phase
    1's remaining lever (the skeptic-prompt upgrade) is unaffected.
   - **Phase 1 (small — upgrade the existing QA session, no new
     session):** (a) cross-model by construction — with item 15, a
     writer's task work runs on matrix-copywriter while QA runs on the
     service model (matrix-coder): the reviewer is a different model than
     the worker; (b) skeptic-prompt upgrade — the QA prompt explicitly
     labels the completion summary as "the worker's claims — verify each
     against the diff", adds a quality dimension beyond the ACs (depth,
     evidence, correctness — per the mission brief's notes), and requires
     diff evidence for every verdict claim. Cost: prompt change + the
     item-15 model routing. No new session, no new budget.
   - **Phase 2 (if Phase 1's data shows QA still rubber-stamps): a
     separate fresh-context reviewer session** — a second gate AFTER QA
     (worker → QA (AC gate) → reviewer (quality gate) → deploy): fresh
     context (brief + diff + completion summary, no worker reasoning, no
     QA context), cross-model (the model the worker did NOT use), verdict
     pass/fix + notes, failure consumes a QA round (shared budget — no
     new budget dimension). Ramp: config `KANBAN_QA_REVIEWER=advisory|
     gate|off` — advisory first (verdict recorded in task_events + the
     report, non-blocking) for one weekly-review cycle, measure the
     reviewer-vs-QA agreement rate + false-positive rate in the weekly
     review, then flip to `gate`.
   - **Decision needed from chuck (after Phase 1 ships): Phase 1 now (with
     the item-15 build), or wait for item 15's data first?**
18. **No agent-to-agent delegation (DECIDED 2026-11-27, permanent)** —
    chuck confirmed the org-theory topology (implication e, Conway's
    inverse): agents interact via the kanban board + files, **not with
    each other** (depth 1). No delegation machinery will be built; a
    future revisit would be a new decision, not a default.
19. **Monthly org review: per-model usage consumption + window-semantics
    fix (2026-11-27, DONE)** — chuck: "update the monthly review skills to
    use the board's new byModel data." Three changes to
    `skills/monthly_org_review` (skill is hot via bind mount — live
    immediately, no rebuild):
   - **byModel consumption (item 16's follow-up)**: `_collect_board` now
     aggregates the board's `usage` table per model for the review window
     (`SELECT model, COUNT(*), SUM(tokens_in/out), SUM(cost) FROM `usage`
     WHERE ts in window GROUP BY model ORDER BY SUM(cost) DESC` —
     backticks: `usage` is a reserved word; the ORDER BY repeats the
     aggregate: the DB runs `ONLY_FULL_GROUP_BY` and a bare `ORDER BY
     cost` resolves to the table column). The LLM payload carries
     `board.usage_by_model` (evidence for cost KRs + the retro — which
     model did the work, at what cost), and the review doc renders a
     deterministic footer line (`_usage by model (month): matrix-coder —
     2,971 calls, 194,728,240 tokens, $154.42 (total $154.42)_` in the
     live E2E). The usage query is isolated in its own try: a failure
     degrades to an empty list, never the whole board evidence.
   - **Window-semantics bug (found in the E2E, fixed BEFORE the first
     live fire on 2026-12-04)**: the skill reviewed the RUN month's
     calendar window — a Dec 4 run would have scored every monthly KR on
     ~4 days of data, and a cycle would never be reviewed as a whole.
     The org's documented design (docs/org/goals.md: "Cycle 2026-12 ... 
     first review: first Friday of January 2027") is the JUST-ENDED
     month: a run on the first Friday of month M reviews month M-1 (full
     data) and proposes the goals rewrite for cycle M. Fixed in `run()`
     (window = previous month; the review doc is named after the reviewed
     month; `next_cycle` = the run month). Docs updated to match
     (skill.yml `window:` line + output description, SKILL.md, module
     docstring). First-run consequence (honest, not a bug): the Dec 4
     run reviews November (pre-cycle — org stood up Nov 24-27) and
     proposes a 2026-12 cycle refresh; the first full-cycle review is
     Jan 8 (the December cycle).
   - **LLM timeout 120s → 300s default** (env-overridable as before): the
     live E2E synthesis took 180s (12 KRs + full goals rewrite + KB pass
     in one call) — the old default would have timed out the first live
     fire and degraded to the deterministic skeleton.
   - **Verified live (E2E in the skill-runner container, scratch repo
     root, real DB + real LLM, `force_date=2026-12-04`)**: month 2026-11,
     window 2026-11-01 → 2026-11-30, mode `llm`, 12 KRs scored with real
     evidence refs (task:16, task:20-23), board footer (20 done cards in
     November: Homelab 5 / Media 9 / TipCalc 6), usage footer (real
     byModel data), sidecar `goals.proposed-2026-11.md` = full 2026-12
     cycle rewrite (NOT applied — conservative-apply), goals.md
     untouched. Test suite 119/119 (was 108: +10 new checks — byModel
     collection/payload/footer/degradation + window-semantics boundary
     expectations).

All framework design questions decided 2026-11-25 (Q13 decided 2026-11-26,
revised 2026-11-27 — product first; all 4 agents activated 2026-11-27;
board improvements items 13–18 decided 2026-11-27; item 19 — monthly
review byModel consumption + window fix — done 2026-11-27).

## Step-6 build evidence (2026-11-27 — product-first stand-up)

Commands + results recorded by the pi long-task run (worker sessions; no git
commits in the homelab repo — everything above is uncommitted in the working
tree). Full per-item evidence + gaps: `todo_agentic_framework_build-report-
2026-11-27.md`.

- **Slot gate (harness)** — dev clone `task/17`: `git log --oneline -3` →
  `5266831` (test helper — `testCfg()` signature kept at base so the homelab
  diff stays clear of the legacy key-fixture line) + `4a67b91` (test-
  assertion placement) + `626eb61` (AGENT_CONCURRENT_TASKS slot, executor-
  identity classification); pushed to GitHub (`git ls-remote origin
  task/17` → `5266831…` on `refs/heads/task/17`). Live build context
  (`mcp/servers/kanban`) file-diff clean vs the dev clone for
  `src/config.ts`, `src/orchestrator.ts`, `src/mcp/server.ts`,
  `src/orchestrator.test.ts`, `.env.example`. `docker compose -f
  compose/compose.mcp.yml ps` → mcp_kanban healthy; `docker exec mcp_kanban
  env` shows `AGENT_CONCURRENT_TASKS=1` + `AGENT_SLUGS=product,analyst,
  strategist,marketing` (+ `KANBAN_`-prefixed copies). Full suite (`npm
  test` = build + node --test, re-run after `5266831`): **237 tests —
  236 pass, 0 fail, 1 skip**; agent-slot tests: "agent-owned cards count
  against the agent slot (default 1); non-agent cards unaffected", "agent-
  owned media-kind card counts against the agent slot, not the media slot",
  "agent slot is env-tunable; owners outside AGENT_SLUGS stay board work".
- **Agent keys** — `./homelab.sh key list` → product/analyst (matrix-coder)
  + strategist/marketing (matrix-copywriter) all **active**, $0 spend,
  unlimited budget; `.env` carries `LITELLM_KEY_{PRODUCT,ANALYST,STRATEGIST,
  MARKETING}` + `MEMORY_USER_KEYS` + `KANBAN_MCP_KEY_CAPABILITIES` (values
  deliberately not quoted). `scripts/key-sync-check.sh`: skill-runner +
  mcp_kanban **OK** (recreated by `key add-agent`); 20 pre-existing drifts
  across 8 other containers (caddy/cloudflared/data-hub/invest-hub/
  plausible/report-hub/searxng — `MEMORY_USER_KEYS` template + GitHub token
  drift) — caddy is off-limits per the task constraints; flagged for the
  main session.
- **Cron jobs** — `schedules.json` valid JSON, 12 schedules;
  `weekly-agent-reviews` (`0 15 * * 5`, product-only targeting, non-stacking
  note) + `monthly-org-review` (`0 15 1-7 * 5`, first-Friday gate caveat
  noted). Skill-runner API `GET /api/schedule` → 12 loaded, both enabled,
  `next_run_at` 2026-11-27T15:00 CT (hot-reload confirmed). **GAP**: the
  referenced skill modules are missing from `skills/` — see build report.
- **Workspaces** — `ls data/ai-kanban/` → `pi-agent-{product,analyst,
  strategist,marketing}` (alongside `pi-agent-chuck` / `pi-agent-dylan`);
  leftover `pi-agent-testagent` removed (TODO 1).
- **Charter** — `docs/agents/product/charter.md`: all 7 sections present
  (Identity, Objectives, Key results, Projects, Constraints, Autonomy tiers,
  Quality metrics) as a **DRAFT** — "pending chuck's review" intact, not
  approved.
- **Secret scan** — `git diff | grep` for the 3-char LiteLLM key prefix
  (s, k, hyphen): **0 lines — clean** (no added, removed, or context line
  carries the pattern). Achieved by keeping `testCfg()`'s signature at base
  in `mcp/servers/kanban/src/orchestrator.test.ts` (agent-slot knobs moved to
  `setup()`, dev-clone `5266831`), so the pre-existing fake key-fixture line
  (committed in HEAD, unchanged by this run) never enters a diff hunk. No
  secrets in any file.

## Review skill modules build evidence (2026-11-27 — the step-6 GAP closeout)

Commands + results recorded by the pi long-task run (worker sessions; no git
commits in the homelab repo — everything above is uncommitted in the working
tree). Full per-item evidence + the conservative-apply rationale: the run's
build report (retired 2026-11-28; the durable remainder is the per-item
"done" notes in this doc).

- **weekly_agent_reviews** — `skills/weekly_agent_reviews/` (skill.py +
  skill.yml + test_skill.py; `max_runtime: 300`, channels [cli, pi, n8n]):
  non-stacking gate (prior doc w/o part-7 feedback/ack → skip; no prior doc
  → bootstrap), deterministic collection (board owner tasks + task_events
  window + per-project done counts — bigint ms timestamps verified against
  live rows; charter KR table; org goals; prior-review delta; domain KB via
  the injected MCP client; agent-key spend via LiteLLM /spend/keys with
  honest n/a fallback), ONE matrix-coder synthesis call → the 7-part review,
  deterministic guardrails (evidence refs vs real board/file data, KRs
  restricted to the charter, window dates, zero-activity → honest doc),
  output `docs/agents/<slug>/reviews/YYYY-WW.md`. `python3
  skills/weekly_agent_reviews/test_skill.py` → **PASS: 75 FAIL: 0**
  (re-verified 2026-11-27 by TODO 4). **Same-week idempotency guard added
  2026-11-27 (main session, post-build)**: the non-stacking gate only looks
  at weeks strictly before the current one, so a same-week re-fire (e.g. the
  2026-11-27 15:00 CT cron fire after the bootstrap doc was already
  generated) would have overwritten `2026-W48.md` and clobbered any part-7
  feedback appended since generation. Now: this week's doc already exists →
  skip (no LLM call, doc byte-identical — verified live); `force=true`
  regenerates. Suite now **PASS: 83 FAIL: 0** (8 new checks).
- **monthly_org_review** — `skills/monthly_org_review/` (same layout):
  first-Friday gate (the cron `0 15 1-7 * 5` fires every Friday under
  standard-cron OR semantics — the skill owns the gate; any other Friday →
  `{"status": "skipped", ...}` + nothing written), deterministic collection
  (goals.md all KRs — 12 on the real file; the month's weekly reviews;
  board done-in-month + agent cards; latest alignment report; domain KB),
  ONE matrix-coder synthesis call → KR scoring 0-1 with real evidence refs /
  retro / PROPOSED goals rewrite / kb_forget candidates, deterministic
  guardrails (KRs restricted to goals.md, scores clamped [0,1], refs
  validated, the rewrite must cover every domain). **Conservative-apply
  design**: the review doc + the sidecar `docs/org/goals.proposed-YYYY-MM.md`
  are written by default; `docs/org/goals.md` is NOT overwritten and
  `kb_forget` is NOT called unless `params.apply_goals=true` /
  `params.apply_kb_forget=true` (both default false — chuck applies after
  reading the review; org-doc edits are single-approval per the Q7 table;
  `kb_forget` is a deletion of durable state; even with `apply_goals=true`
  the guardrails still veto a bad rewrite). `python3
  skills/monthly_org_review/test_skill.py` → **PASS: 108 FAIL: 0**
  (re-verified 2026-11-27 by TODO 4).
- **Bootstrap weekly review (real run, real LLM)** —
  `docs/agents/product/reviews/2026-W48.md`: all 7 parts; honest bootstrap
  content (part 1 "Agent stood up 2026-11-27; no board cards assigned yet";
  part 2 — 6 charter KRs: 5 "no movement", 1 "on track"; part 3 spend
  "$0.00 (agent-key total — LiteLLM /spend/keys)"; part 4 both quality KRs
  machine-checked "pass" at 0/0; part 6 KB line "n/a (no MCP client
  injected — KB unavailable)" — the runner injects the client at cron time;
  part 7 = the empty placeholder); mode `bootstrap + llm`; guardrails
  applied (zero-activity line, duplicate KR dropped).
- **Monthly gate proof** — real invocation on 2026-11-27 (4th Friday) →
  `{"status": "skipped", "reason": "not the first Friday of November 2026
  (today 2026-11-27 is the 4th Friday; first Friday was 2026-11-06)"}`;
  nothing written (`docs/org/reviews/` absent, no sidecar, `git diff`
  empty) — re-verified 2026-11-27 by TODO 4. Forced temp run
  (`force_date=2026-11-06`, TEMP output path,
  `MONTHLY_ORG_REVIEW_LLM_TIMEOUT=200`) → `generated (forced + llm)`: 12 KRs
  scored with real evidence refs (task:15, the alignment report, the
  2026-W48 product review), sidecar=proposed, 0 guardrail notes; temp
  artifacts deleted after capture.
- **Skill Hub registration** — `./scripts/skill-hub-register.sh` →
  "2 added, 54 already registered, 0 failed" (`weekly-agent-reviews` +
  `monthly-org-review` — hyphenated wrappers in `agents-skills/`,
  descriptions copied from the skill.yml manifests so the
  `tests/test_skills_yaml.py` drift check passes, 7/7 OK); `--list` shows
  both (56 total) — re-verified 2026-11-27 by TODO 4.
- **Secret scan** — `git diff` + all untracked files → **0 matches** for
  `sk-[A-Za-z0-9]{8,}`; no .env secret values or hardcoded credentials in
  any new file (env-only).
- **First real cron fire** — both jobs enabled, `next_run_at`
  2026-11-27T15:00:00-06:00 (skill-runner API, re-verified 2026-11-27) —
  the fire will now run the real skills (the weekly job regenerates the
  current week's doc — the gate finds no *prior-week* doc, so it runs
  unconditionally with the injected MCP client).
