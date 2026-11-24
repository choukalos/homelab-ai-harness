# Agent Org Framework — Managing a Team of Agents to a Goal with OKRs

> v1.0 — synthesized from four research lanes (full notes in `docs/agent-org-research/`):
> OKR theory, organizational design theory, multi-agent LLM evidence, and
> control/feedback theory. Confidence tags: **[H]** validated / well-established,
> **[M]** sound structural analogy (agent-specific, not yet empirically proven),
> **[V]** verified against Anthropic's published multi-agent system post (Jun 2025).

---

## The Core Insight

Managing agents is **not** managing humans. The levers change:

| Human org | Agent org |
|---|---|
| Motivation, incentives, trust | Prompt, context, tools, verification |
| Communication bandwidth is the bottleneck | Context window + signal-to-noise is the bottleneck |
| Errors are rare and recoverable | Errors compound silently and fast **[V]** |
| Feedback is social (reviews, 1:1s) | Feedback must be **machine-checkable** |
| Span of control 3–7 for coaching | Span bounded by **verification capacity**, not coaching **[M]** |
| "Good enough" is a personal judgment | Agents are natural **satisficers** — the bar must be external (Simon) **[M]** |

One sentence: **An agent org is a control system, not a social system.**
Design the sensors (verification), the setpoints (OKRs), and the loops (cadence) —
everything else is plumbing.

A key economic fact: multi-agent systems cost **~15× the tokens** of chat
(single agent ~4×) **[V]**. The org must buy real wall-clock or quality wins —
default to the smallest structure that works.

---

## 1. GOALS — OKRs as the Setpoints

### 1.1 Mechanics (high confidence, decades of practice) **[H]**

- **Objective (O):** one qualitative, aspirational, time-bound statement of *direction*.
- **Key Results (KRs):** 3–5 measurable outcomes, each with a **baseline and a target**.
  KRs are *outcomes*, not activities ("Ship feature X" is a ticket, not a KR).
- **Scoring:** each KR scored 0.0–1.0. Stretch KRs: 0.6–0.7 is a *good* result;
  consistently hitting 1.0 means the target was too easy. Committed KRs target 1.0.
  Healthy mix: ~70% committed / 30% stretch.
- **OKR ≠ KPI ≠ ticket.** KPIs are always-on health metrics (dashboard).
  OKRs are bounded directional bets. Tickets are the work that moves KRs.

### 1.2 The agent-specific rule that matters most

> **Every KR must be machine-measurable.** An agent org can only close the loop
> on what it can measure. If a KR can't be reduced to a check (test, metric,
> artifact state, resolvable citation), it's not a KR for agents — it's a hope.

This single rule absorbs most of the classic OKR failure modes:

| Classic failure mode | Agent translation |
|---|---|
| Too many KRs | Agent over-decomposes, loses coherence → cap at 3–5 sub-goals per level |
| No measurement | Agent can't evaluate its own progress → every sub-goal needs a checkable predicate |
| To-do list | Agent plans activities, not outcomes → enforce outcome-language |
| Annual-only cadence | Agent runs **open-loop** → enforce periodic scoring checkpoints |
| No consequence to scoring | Orchestrator never calibrates → scores must drive reallocation |

### 1.3 Goal structure

```
Org Goal (user's ask)
  └─ Objective (qualitative, 1 sentence)
       ├─ KR1: <measurable outcome, baseline → target, check>
       ├─ KR2: ...
       └─ KR3: ...
            └─ Workstreams (org units)
                 └─ Tasks (atomic, each with an acceptance check)
```

The 3–5 KRs per level discipline prevents combinatorial explosion in agent
planning — it's the same constraint that keeps human orgs aligned.

---

## 2. ORG — Structure Design Rules

Nine rules, each grounded in validated org theory + agent-specific evidence:

1. **Match configuration to task** (Mintzberg) **[H→M].**
   Repetitive, well-defined work → pipeline agents with fixed prompts + validation
   gates. Specialist knowledge work → specialist agents + peer review.
   Novel, high-ambiguity work → multi-perspective/debate patterns.
   Scale by **divisional replication** (independent pods), not by deepening one hierarchy.

2. **Bound span by verification capacity** **[M].** Human span (3–7) comes from
   cognitive bandwidth; for agents the binding constraint is whether each output
   can be *verified*, not read. Practical range: **3–7 when outputs need judgment,
   10–20 when outputs are machine-verifiable** (schema-conformant, testable).
   High span only pairs with automated verification gates — because without
   verification, 95%-fidelity outputs compound to ~60% aggregate fidelity at span 10.

3. **Design the communication graph first** (Conway's Law, inverted) **[H].**
   The org's communication topology *becomes* the system architecture.
   Want modular output? Isolated pods with narrow interfaces. Want a coherent
   narrative? Single orchestrator with deep context. Decide the shape before assigning work.

4. **No agent is its own verifier** (principal-agent problem) **[H].**
   LLMs are optimized to produce *plausible* output, not *correct* output, and
   they look confident either way. Without external verification, "plausible" is
   the equilibrium. Every output needs an independent check: test execution,
   schema validation, a fresh-context critic, or ground-truth cross-check.

5. **Encode satisficing thresholds externally** (Simon) **[M].**
   Agents accept the first plausible completion. The bar must live in the task
   spec ("pass all tests", "cite 3+ resolvable sources", "match this schema"),
   not in the agent's internal "good enough" judgment. The org defines the bar;
   the agent meets it.

6. **Use the cheapest sufficient coordination mechanism** (Galbraith) **[H].**
   Ladder: direct supervision → standardized processes (prompt templates) →
   standardized **outputs** (schemas + tests) → standardized inputs (system
   prompts, tool access) → standardized skills (fine-tunes, RAG) → mutual
   adjustment (debate). Standardize outputs before adding debate. Over-coordination
   burns tokens; under-coordination produces garbage.

7. **Layer as platform + product** (Team Topologies) **[M].**
   Extract stable, reusable capabilities into **platform** agents (tool wrappers,
   memory, retrieval). Keep **product** agents thin — orchestrating, not
   implementing. Reduces per-agent cognitive load and enables independent scaling.

8. **Scale by divisional replication, not by adding agents to one loop** (Brooks's Law) **[M].**
   Adding agents doesn't linearly add capacity: context is shared and finite,
   integration cost is superlinear, and agents sharing model + prompt style make
   **correlated errors** (more agents ≠ more diverse errors). A pod of 3 on
   isolated sub-problems beats 9 in one shared context.

9. **Depth ≤ 2 by default, hard cap 3** **[V/M].**
   Anthropic runs exactly two levels (lead → subagents) in production and notes
   deeper async coordination adds result-coordination, state-consistency, and
   error-propagation complexity **[V]**. Each level adds latency, intent
   distortion ("game of telephone"), and a single point of failure.
   Flatten deeper structures by promoting capabilities into platform services.

### 2.1 When to use a team at all **[V]**

Default to **one agent + strong tools**. Fan out only when:
- the work is **parallelizable breadth** (multi-agent beat single-agent by
  **90.2%** on Anthropic's research eval — for breadth tasks), or
- the information exceeds **one context window**, or
- the task needs **many heterogeneous tools**.

**Right-size effort** (Anthropic's effort-scaling rules, which fixed their early
over-delegation — agents "spawned 50 subagents for simple queries"):
simple lookup ≈ 1 agent / 3–10 tool calls; comparisons ≈ 2–4 subagents;
genuinely complex ≈ 10+. Encode these rules in the supervisor's prompt.

### 2.2 The delegation contract **[V]**

The delegation prompt is the dominant reliability lever. Every subtask brief carries:
**(a) objective, (b) output format, (c) tool/source guidance, (d) explicit task
boundaries.** Vague briefs caused duplicated work and gaps in production.
Workers start cold — a bad brief is a guaranteed bad output.

**Pass by reference, not by content:** workers write structured outputs to
disk/store and return lightweight references. Passing full content through the
coordinator loses fidelity and burns tokens (the "game of telephone" failure).

---

## 3. LOOPS — The Feedback Mechanism

### 3.1 The stack (Beer's Viable System Model) **[M, classical theory H]**

An org is **viable only if all five layers are present and nested**:

```
┌──────────────────────────────────────────────────────────┐
│ 5. POLICY        (per objective / quarter or milestone)  │
│    Set & revise OKRs · arbitrate trade-offs · "viable?"  │
├──────────────────────────────────────────────────────────┤
│ 4. ADAPTATION    (per workstream / weekly or per batch)  │
│    Review KR trajectory · re-prioritize · re-architect   │
├──────────────────────────────────────────────────────────┤
│ 3. REGULATION    (per task / every attempt)              │
│    Tests · linters · schema checks · deterministic gates │
├──────────────────────────────────────────────────────────┤
│ 2. COORDINATION  (continuous)                            │
│    Task routing · dependency resolution · conflict       │
├──────────────────────────────────────────────────────────┤
│ 1. OPERATION     (per action)                            │
│    LLM agents execute · emit structured state · act      │
└──────────────────────────────────────────────────────────┘
```

Each layer is a closed loop with its own **sensor, setpoint, and authority to
act**: the inner layer fixes code, the mid layer re-prioritizes, the outer
changes goals. Missing regulation → errors accumulate silently. Missing
adaptation → the org can't respond to regime change.

### 3.2 The three cadences

| Layer | Cadence | Sensor | Setpoint | Corrective action |
|---|---|---|---|---|
| **Fast** (task) | seconds–minutes | unit tests, type checks, linters, schema validation | task acceptance criteria | worker retries / fixes / escalates (bounded) |
| **Mid** (workstream) | daily–weekly | KR metrics (leading indicators: tasks done, PRs merged, coverage) | KR target trajectory | supervisor reassigns, re-scopes, re-decomposes |
| **Slow** (objective) | per milestone / quarter | KR scores 0–1, objective achievement | strategic objective | policy layer revises OKRs or declares done |

Rules of engagement:
- The outer layer must **not** micromanage the inner (causes thrashing);
  the inner must not override the outer's objectives (causes drift).
- Add **leading indicators** so the mid loop is weekly, not quarterly
  (Senge: feedback delay is the killer — "fixes that fail").

### 3.3 The key variable: detection latency

In control theory, detection-to-correction delay determines stability:
**fast detection + small corrections = stable; slow detection + large
corrections = oscillation or divergence.** The fast loop catches ~90% of
failures with a 2-minute correction; skip it and the slow loop must correct
100× larger errors at 100× the cost. Make the fastest possible check run at
the fastest possible cadence (OODA tempo: test after every increment, not
after every batch).

### 3.4 Making feedback objective

- **External predicates, never self-grades.** The agent proposes; the pipeline
  disposes. Self-graded agents have sensor and actuator in the same component —
  a conflict of interest. No task is "done" without passing at least one
  external check. If none exists, the task is **open-loop and must be flagged**.
- **Fresh context per reviewer.** A critic that saw *how* you reached the
  answer is biased toward agreeing (sycophancy is documented between LLMs).
  Spawn the critic clean: artifact + rubric only, no original reasoning.
  Anthropic spawns fresh subagents with clean contexts at phase boundaries **[V]**.
- **Deterministic checks first, LLM-judge second.** Where correctness is
  checkable, tests/linters/schemas are ground truth. For free-form output,
  use a rubric-scored judge (0.0–1.0 + pass/fail on factual accuracy,
  completeness, source quality, efficiency) — the most consistent method
  Anthropic found — but pair it with deterministic safeguards **[V]**.
- **Sensors are structured state, not self-reports.** Every agent emits
  machine-readable state: task status + timestamps, versioned artifacts,
  metrics (tokens, iterations, pass/fail counts), and a causal trace from
  objective → task → action → result. Natural-language self-reports are
  opinions, not sensors.

---

## 4. Operating Process (the runbook)

### Phase 0 — Set the goal
1. Write the Objective + 3–5 KRs. **Reject any KR without a baseline, a target,
   and a machine check.** Mix ~70% committed / 30% stretch.
2. Define each KR's acceptance check (script, metric, artifact state).
3. Name the leading indicator for each KR so the mid loop can run weekly.

### Phase 1 — Design the org
4. Pick the configuration for the task type (pipeline / specialist / debate).
5. Split KRs into workstreams along natural seams; write each workstream's
   **contract**: inputs, outputs (schema), interface, done-criteria.
6. Decide parallel vs sequential: only *independent* workstreams run in
   parallel. Right-size the team (1 / 2–4 / 10+ subagents by complexity).
7. Verify depth ≤ 2 (≤ 3 hard cap) and that every output has an independent
   verifier. If a workstream has no external predicate, redesign it.

### Phase 2 — Run
8. Supervisor decomposes workstreams into bounded tasks; each brief carries the
   4-element delegation contract (objective, output format, tools, boundaries).
9. Workers execute; **fast loop runs on every task**: check → fix → recheck,
   bounded retries (e.g., 3). Same error > N times → stop and escalate
   (hysteresis — prevents thrashing).
10. Workers write structured outputs to disk; return references, not content.
11. Failed tasks get a **fresh-context retry or a different decomposition** —
    not the same worker with the same brief (correlated errors).

### Phase 3 — Review
12. **Mid loop:** supervisor scores workstream progress against KR trajectory
    using leading indicators; fresh-context reviewer on quality gates;
    reassign / re-scope / escalate.
13. **Slow loop:** score KRs 0–1; write a short retro (what the loops caught,
    what they missed); adapt the objective or plan. 0.6–0.7 on stretch KRs is
    a *success* — don't punish ambition.
14. **Evaluate outcomes + process, not steps.** Agents take different valid
    paths; grade end-state against a rubric (start with ~20 real tasks as the
    eval set) **[V]**.

### Standing rules
- **No self-grading at the gate.** Final check on any task is external.
- **Fresh eyes on quality gates.** Reviewer context ≠ worker context.
- **State in artifacts, not context.** Any agent that dies is replaceable
  because everything it knew is on disk (also the resume-from-error mitigation
  for cascading failures **[V]**).
- **Bounded delegation.** Every task has a done-check and a stop condition;
  a worker that can't converge reports up with evidence instead of thrashing.
- **Bounded correction authority.** Workers may retry/fix/rerun within scope;
  escalation only beyond scope — never a dead end waiting for an unavailable human.
- **Cost awareness.** Budget ~15× tokens for multi-agent; spend it only where
  parallelism or breadth genuinely pays **[V]**.
- **Instrument.** Full tracing + decision-pattern monitoring; non-determinism
  means a single bad roll can cascade and be hard to debug without it **[V]**.

---

## 5. Failure Modes (what to watch for)

| Failure | Symptom | Loop that catches it | Fix |
|---|---|---|---|
| Cascading errors | one bad step sends downstream agents astray **[V]** | fast | external check at every interface contract; checkpoints + resume-from-error |
| Context loss at handoff | worker "forgets" constraints; telephone game **[V]** | fast | self-contained briefs; outputs by reference; fresh context at phase boundaries |
| Sycophantic review | critic rubber-stamps the worker's narrative | mid | fresh-context critic, artifact-only, backed by deterministic check |
| Over-delegation | 50 subagents for a simple query **[V]** | mid | effort-scaling rules in supervisor prompt; right-size |
| Role confusion / duplicate work | two workers do the same search **[V]** | fast | explicit task boundaries in every brief |
| Unmeasurable KR | "improve quality" | — (caught at Phase 0) | reject: no KR without a check |
| Thrashing | fix A breaks B, fix B breaks A | fast | hysteresis: same error > N → stop & escalate |
| Open-loop task | output ships, nobody checked | fast | no task is "done" without an external predicate |
| No correction authority | worker detects error, dead-ends on human | mid | bounded correction authority; escalate only beyond scope |
| Goal drift | work is done, objective missed | slow | slow loop re-scores KRs against the objective |
| Non-determinism | same prompt, different runs, cascading bad roll | all | full tracing; evaluate outcomes, not steps |

---

## 6. Minimal Viable Version — the 5 Rules (start here, discuss these)

The irreducible core. Each rule below states the rule, the finding it rests on,
and what breaks if you drop it. These five are the ones to argue about —
everything else in the doc is elaboration.

### Rule 1 — One objective, 3–5 machine-measurable KRs

> Every KR has a baseline, a target, and a machine check. No check → not a KR.

- **Why:** OKRs are the setpoints of the control system. The 3–5 cap is the
  validated human-team heuristic that prevents combinatorial explosion in agent
  planning; the *machine-measurable* requirement is the agent-specific add —
  an org can only close the loop on what it can measure.
- **Breaks without it:** open-loop execution. Agents optimize toward plausible
  activity instead of measured outcomes; by the end you can't tell if the
  objective was met. This is the #1 documented OKR failure mode ("no
  measurement") with an agent-specific twist.

### Rule 2 — One supervisor, N workers, depth 1. Default N=1.

> Add workers only for parallelizable, machine-verifiable work. Right-size:
> 1 agent for lookups, 2–4 for comparisons, 10+ for genuinely parallel breadth.

- **Why:** Anthropic's production system runs exactly 2 levels deep and warns
  that deeper async coordination multiplies state-consistency and
  error-propagation problems **[V]**. Multi-agent costs ~15× tokens **[V]** and
  only pays off on parallelizable breadth (90.2% win on their research eval).
  Handoffs lose fidelity ("game of telephone"), and agents sharing model +
  prompt make correlated errors — more workers ≠ more diverse errors.
- **Breaks without it:** over-delegation (their early failure: 50 subagents
  for a simple query **[V]**), cascading errors across deep hierarchies, and
  token spend that doesn't buy wall-clock or quality.

### Rule 3 — Every task has a deterministic done-check; no self-grading at the gate

> The final check on any task is external: test, linter, schema validation,
  or a fresh-context critic backed by a rubric. The agent proposes; the
  pipeline disposes.

- **Why:** the principal-agent problem, amplified: LLMs are optimized for
  *plausible* output, not *correct* output, and look confident either way.
  A self-graded agent has sensor and actuator in the same component — a
  conflict of interest. Where correctness is checkable, a deterministic
  pass/fail is ground truth; LLM self-grades are noisy and self-biased.
- **Breaks without it:** "plausible" becomes the equilibrium. Broken work
  ships with a confident success report, and the org has no error signal to
  regulate on — the control loop doesn't exist.

### Rule 4 — Three loops: per-task (seconds), per-batch (fresh-context review), per-milestone (KR scoring + adapt)

> Fast loop: check → fix → recheck with bounded retries + hysteresis
> (same error > N → escalate, don't thrash). Mid loop: trajectory vs KR
> leading indicators, reviewed by a critic that did *not* see the work. Slow
> loop: score KRs 0–1, retro, and the only place the goal itself may change.

- **Why:** detection-to-correction delay determines stability in control
  theory: the fast loop catches ~90% of failures with a 2-minute correction;
  skip it and the slow loop corrects 100× bigger errors at 100× the cost.
  Fresh-context review exists because critics who saw the reasoning rubber-stamp
  it (documented sycophancy between LLMs). Beer's VSM: missing the regulation
  layer → silent error accumulation; missing the adaptation layer → no
  response to regime change.
- **Breaks without it:** errors compound silently until the only feedback is
  the final result — expensive, late, and too large to correct cheaply. Or,
  with only a too-tight loop: thrashing (fix A breaks B, fix B breaks A).

### Rule 5 — All state in files; every agent replaceable at any time

> Org state (what's done, what's blocked, KR scores, contracts, artifacts)
> lives in durable artifacts any agent can read — never only in an agent's
> context. Workers write structured outputs to disk and pass references,
> not content.

- **Why:** context is ephemeral and finite; agents die, hit context limits,
  and return bad rolls (non-determinism means a single bad run can cascade
  **[V]**). Durable external state is Anthropic's resume-from-error mitigation
  and the precondition for bounded, right-sized workers (each starts cold
  from a file, not from inherited context).
- **Breaks without it:** single point of failure in any agent's context
  window. A crashed or swapped agent takes its workstream's state with it;
  handoffs degrade because full content must pass through the coordinator.

### The 5 rules as a pre-flight check

Before launching any agent org, answer yes to all five:

1. Can I write a machine check for every KR?
2. Is every worker's work parallelizable *and* verifiable — and is N right-sized?
3. Does every task have an external done-check the worker can't grade itself against?
4. Do I have all three loops running, with the fast one in seconds?
5. If any agent dies right now, can a fresh one pick up from files alone?

If any answer is no, fix the design before spending tokens.

---

## 7. Design Checklist

**Goals**
- [ ] 1 objective, 3–5 KRs, each with baseline + target + machine check
- [ ] ~70/30 committed/stretch mix; leading indicators named per KR

**Org**
- [ ] Configuration matched to task type (pipeline / specialist / debate)
- [ ] Communication graph designed before task assignment (Conway inverse)
- [ ] Span bounded by verification capacity (3–7 judgment, 10–20 machine-checked)
- [ ] Every output has an independent verifier (no self-verification)
- [ ] Acceptance thresholds encoded in task specs, not left to the agent
- [ ] Cheapest sufficient coordination mechanism (outputs standardized before debate)
- [ ] Platform/product layering; product agents thin
- [ ] Depth ≤ 2 (≤ 3 cap); scale by pods, not by deepening
- [ ] Team right-sized (1 / 2–4 / 10+); 15× token cost justified

**Loops**
- [ ] All five VSM layers present (operation, coordination, regulation, adaptation, policy)
- [ ] Fast loop: external predicate on every task, bounded retries + hysteresis
- [ ] Mid loop: leading indicators, weekly, fresh-context reviewer
- [ ] Slow loop: 0–1 KR scoring, retro, authority to change the objective
- [ ] Structured state emitted by every agent (status, artifacts, metrics, trace)
- [ ] Deterministic checks first; rubric-scored LLM-judge only for free-form output
- [ ] Full tracing; outcomes + process evaluated, not steps

---

## Sources & Confidence

- **OKR:** Grove, *High Output Management* (1983); Doerr, *Measure What Matters* (2018).
  Core mechanics/cadence/failure modes: **[H]**. Agent-OKR mapping: **[M]** (no
  peer-reviewed literature on agent OKRs exists yet — this is an emerging space).
- **Org theory:** Mintzberg (1979), Conway (1967), Jensen & Meckling (1976),
  Simon (1947), Galbraith (1967/1994), Skelton & Pais (2019), Brooks (1975).
  Classical theory **[H]**; agent transfers **[M]** (reasoned analogy; no
  published empirical study of LLM agent org design exists as of the research date).
- **Multi-agent:** Anthropic, "How we built our multi-agent research system"
  (Jun 2025) — **[V]** claims verified against the post; Reflexion (Shinn et al.
  2023) **[H]** for iterative tasks with clear success signals; debate/sycophancy
  **[M]**.
- **Feedback:** Beer's VSM (1972), Boyd's OODA, Senge (1990), classical control
  theory, SRE observability (Beyer et al., 2016). Classical theory **[H]**;
  agent transfers **[M]** (structurally sound, not yet empirically validated at scale).

**Honest caveat:** the classical layers (OKR, org design, control theory) are
deeply validated for human organizations; the agent-specific transfers are
well-reasoned analogies with strong practitioner evidence (Anthropic) but no
peer-reviewed empirical base yet. Treat the **[M]** rules as strong priors to
test against your own runs — the runbook's retro step (Phase 3) is where you
convert them into your own evidence.

Full research notes: `docs/agent-org-research/okrs.md`, `docs/agent-org-research/org-theory.md`,
`docs/agent-org-research/multi-agent.md`, `docs/agent-org-research/feedback.md`.
