# Todo — agentic framework + agents (workstreams 3–4)

- date: 2026-11-24
- status: open (planning in progress — goal model decided 2026-11-24; OKR skill
  proposal S13 staged below, awaiting chuck's review)
- source: workstreams 3–4 of `todo_agent_skills.md` (decomposed 2026-11-22);
  this is the own-TODO-doc that doc proposed for WS3+WS4
- companions: `todo_agent_skills.md` (WS2 — the role/step skills the agents
  follow), `todo_plausible.md` (WS1 — the instrumentation the KRs measure against)

## Scope

- **WS3 — the agentic framework**: the system that runs the role agents —
  identity/keys, goal model, projects, constraints, tasking, periodic review
  protocol, state/memory, scheduling, reporting, guardrails, spend.
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
- **Per domain, not one flat set** (chuck 2026-11-24). Three domains so far:
  - **Homelab** — learning by building: the custom harness itself, research,
    personal-interest content (old arcade games, guitar, creating songs/clips,
    teenage-chuck RPGs & war games, cars).
  - **Bluebovine Group** — commercial: consulting, a product (TBD), and content
    that drives traffic + credibility for the site.
  - **InvestHub** — personal investment interest, teaching the son,
    discussion/analysis with buddies. *Open: does it stand alone or sit under
    Bluebovine Group?*
- **Home**: `docs/org/goals.md` — one file, per-domain sections (split into
  per-domain files later if they grow).
- **Authorship**: chuck, with the S13 skill. **Cadence**: open (monthly vs
  quarterly).

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
  4. **Projects** — the kanban projects this agent works.
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
  debt, organization/clean-up) is legitimate and recurring — gets the `bau`
  tag so it isn't flagged as unmapped. *Open: keep it a tag, or make it a
  standing "org health" objective per domain?*

### Quality metrics (OPEN)

- chuck 2026-11-24: **not decided** — he wants to monitor/metric quality per
  agent, mechanism TBD. The charter carries the slot; when defined, the BA
  consumes the same data (one source, no duplicate reporting).
- Research input (OKR Institute): every agent OKR should carry **at least one
  quality/safety KR** so the agent can't optimize volume at the expense of
  trust. Candidate examples: CM "0 published pieces that failed content QA";
  PM "0 PRDs without acceptance criteria".

### Research grounding (2026-11-24, via mcp_search)

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

## S13 — `okr` skill (PROPOSAL — awaiting chuck's review)

**Purpose**: help chuck (or an agent) write org + agent OKRs, and verify the
ladder — that agent OKRs line up to the org's OKRs.

**When to use**: setting or updating org goals (per domain); drafting or
reviewing an agent charter's objectives + KRs from the org goals; a ladder
alignment check ("is the work actually serving the goals?"); an OKR cycle
closeout (progress review → next cycle's draft).

**Inputs**: `docs/org/goals.md` (or `homelab_vision.md` + domain context when
org goals don't exist yet); board state (what work exists / is in flight); BA
reports + KPI data (once G3 wiring lands); prior-cycle records
(`docs/agents/<agent>/reviews/`).

**Steps**:

1. **Frame the domain** — which domain(s) (homelab / bluebovine / investhub);
   what changed since the last cycle (board movement, BA data, chuck's
   direction).
2. **Draft org objectives** — 1–3 per domain. Objective in outcome language
   ("make X feel effortless for Y", not "deploy Z"). 2–4 KRs each.
3. **Write KRs** — each KR gets **definition, source, target, cadence**.
   Rules:
   - **Outcomes over activity** — "N posts written" is a leading indicator,
     not the KR; the KR is the outcome the posts drive (labeled leading
     indicators allowed alongside).
   - **No data? Guess** — mark `proxy` with a validation note ("validate when
     Plausible/data-hub lands"). First pass is guesses by design.
   - **Quality/safety KR slot** on every domain + every agent (mandatory or
     not — open with chuck).
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

**Status**: proposal — not yet built, not yet in the S1–S12 library. Belongs
to WS3 (the org/agent goal system), not workstream 2. If chuck wants it in the
formal `proposals/` lifecycle (md + MySQL row + CLI), it moves there.

## Remaining open design questions

(From the 2026-11-22 seed list; goal model — Q2 — is now decided above.)

1. **Identity** — per-agent LiteLLM keys: capability scoping (read/control/
   admin sets exist), per-agent spend visibility/budgets.
2. ~~Goal model~~ — **decided 2026-11-24** (above).
3. **Tasking** — how work reaches an agent: kanban board, direct TODOs from
   chuck, periodic self-generated plans? Precedence between the three.
4. **Periodic review protocol** — cadence, format (plan → feedback → execute →
   report), where the record lives (`docs/agents/<agent>/reviews/` proposed).
5. **State/memory** — per-agent workspace, durable state across sessions
   (memory skills exist: `memory-conventions`, `session-memory`, `session-sync`);
   per-agent memory namespaces.
6. **Scheduling** — what triggers an agent run (cron? kanban events? chuck?).
7. **Guardrails** — autonomy tiers per action class; persistent trust grants
   (bounded, revocable, logged); agent-level gates beyond per-project deploy
   gates.
8. **Reporting** — accomplishments/learnings → chuck + board + BA (BA
   *consumes* agent reports, doesn't duplicate them).

New from the 2026-11-24 interview:

9. **Org goal cadence** — monthly vs quarterly review of `docs/org/goals.md`.
10. **InvestHub placement** — standalone domain or under Bluebovine Group?
11. **BAU framing** — `bau` tag vs a standing "org health" objective per domain.
12. **Quality metrics** — mechanism for monitoring/metric-ing agent quality
    (charter slot exists; mandatory quality KR — yes/no).
13. **First agent** — which agent stands up first (skills-doc Q1, deferred
    here).

## Next steps

1. chuck reviews the S13 `okr` proposal (this doc) — accept/revise.
2. First org-goals pass: run the OKR workflow (ad-hoc or built skill) to
   produce `docs/org/goals.md` for the 3 domains.
3. Agent charter drafts: first agent suggests its charter from the org goals →
   chuck approves (first agent = Q13).
4. Then the remaining framework questions in suggested order: identity/keys →
   tasking + review protocol (the operating loop) → scheduling/guardrails →
   memory/reporting.
