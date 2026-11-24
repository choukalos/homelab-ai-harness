# Multi-Agent Orchestration: What's Actually Validated

**Method & confidence.** The centerpiece (§2) is verified against Anthropic's engineering post *"How we built our multi-agent research system"* (published Jun 13, 2025), fetched directly. Other claims are synthesized from the broader literature and practitioner reports and tagged **[high]** / **[med]** / **[low]**. Anthropic-verified claims are tagged **[verified]**.

## 1. Orchestration patterns

**Orchestrator-worker / supervisor-worker.** A lead agent decomposes the goal into subtasks, spawns parallel workers, and aggregates condensed results. This is the pattern Anthropic shipped in production **[verified]**. Their lead agent ("LeadResearcher") analyzes the query, saves its plan to external memory, spawns specialized subagents, each acting as an "intelligent filter" — running searches in its own context window and returning only the important tokens. The orchestrator's *delegation prompt* is the dominant lever: each subagent needs (a) an objective, (b) an output format, (c) tool/source guidance, and (d) explicit task boundaries; vague instructions caused duplicated work and gaps **[verified]**.

**Hierarchical teams.** Two levels (lead → subagents) is what Anthropic runs; deeper hierarchies are possible but they run subagents *synchronously* and note async, deeper coordination adds result-coordination, state-consistency, and error-propagation complexity **[verified]**. Deeper-than-2-level hierarchies have weak public evidence **[low]**.

**Peer / debate.** Same-level agents critique or debate to surface errors. Useful for increasing *diversity of answer candidates* — the same mechanism behind self-consistency (sample N reasonings, majority vote) **[med]**. But fragile: agents tend to converge (see sycophancy, §3.6) and debate adds token cost without guaranteed accuracy gains **[med]**.

**Reflection (Reflexion).** An agent generates a self-critique after a trial and uses it to improve the next attempt (Shinn et al. 2023, verbal reinforcement). Strong evidence it helps on *iterative, trial-based* tasks (coding, decision-making) where a clear success/failure signal exists **[high]**. Anthropic's version is "interleaved thinking" — subagents evaluate tool results, identify gaps, refine the next query **[verified]**. Caveat: self-reflection with no external signal can be self-reinforcing (the agent rationalizes) **[med]**.

**Planner–executor–critic splits.** Separate planning, execution, and evaluation into distinct roles. Anthropic's Research maps to this: LeadResearcher = planner, subagents = executors, CitationAgent = a post-hoc verifier **[verified]**. The split helps when each role has genuinely different tools/context, but it multiplies coordination cost **[med]**.

## 2. Anthropic's multi-agent research system (strongest public evidence)

- **Breadth research wins.** A multi-agent system (Opus 4 lead + Sonnet 4 subagents) **outperformed single-agent Opus 4 by 90.2%** on their internal research eval **[verified]**. Example: "identify all board members of S&P 500 IT companies" — multi-agent decomposed it into parallel subtasks; single agent failed via slow sequential search **[verified]**.
- **Why it works = token spend.** Three factors explained 95% of performance variance on BrowseComp: token usage (80%), tool-call count, model choice. Multi-agent "helps spend enough tokens to solve the problem" by giving parallel subagents their own context windows **[verified]**.
- **Cost: ~15×.** Agents use ~4× the tokens of chat; multi-agent systems ~15×. So multi-agent is only economically viable when task value is high enough to pay for it **[verified]**.
- **When NOT to use.** Tasks where all agents must share one context, or with many inter-agent dependencies, are a poor fit. "Most coding tasks involve fewer truly parallelizable tasks than research," and LLMs "are not yet great at coordinating and delegating to other agents in real time." Use multi-agent for: heavy parallelization, information exceeding a single context window, and interfacing with many complex tools **[verified]**.
- **Effort scaling.** Simple fact-finding ≈ 1 agent / 3–10 tool calls; comparisons ≈ 2–4 subagents / 10–15 calls; complex ≈ 10+ subagents. Encoding these rules in the prompt prevented over-investment in simple queries — a common early failure **[verified]**.
- **Self-improvement.** Given a prompt + a failure mode, Claude can diagnose and rewrite prompts; a "tool-testing" agent that rewrites bad tool descriptions cut task-completion time ~40% **[verified]**.
- **Evaluation.** Agents take different valid paths, so you can't check "correct steps" — evaluate outcomes + process. Start with ~20 real queries. A single LLM-as-judge call with a rubric (factual accuracy, citation accuracy, completeness, source quality, tool efficiency) scoring 0.0–1.0 + pass/fail was the most consistent; human testing still catches edge cases (e.g., agents preferred SEO content farms over authoritative sources) **[verified]**.

## 3. Known failure modes

1. **Cascading / compounding errors.** "Agents are stateful and errors compound… minor system failures can be catastrophic"; one failed step sends downstream agents down different trajectories. Mitigations: resume-from-error, retry logic, checkpoints, and telling the agent when a tool failed so it adapts **[verified]**.
2. **Context loss / handoff degradation ("game of telephone").** Passing large outputs through the coordinator loses fidelity and burns tokens. Fix: subagents write structured outputs (code, reports) to a filesystem/external store and pass back *lightweight references*, not the full content **[verified]**.
3. **Role confusion / mis-scoped work.** With vague delegation, subagents misinterpret the task or duplicate each other's searches (one studied the 2021 chip crisis while two duplicated 2025 supply-chain work) **[verified]**.
4. **Over-delegation.** Early agents "spawned 50 subagents for simple queries" and over-invested in trivial tasks; fixed by explicit effort-scaling rules and clear task boundaries **[verified]**.
5. **Non-determinism.** Even with identical prompts, runs differ; a single bad "roll" can cascade and debugging is hard. Requires full production tracing + monitoring decision/interaction patterns **[verified]**.
6. **Sycophantic agreement between agents.** When agents critique each other, they tend to converge and rubber-stamp rather than genuinely disagree — LLMs are documented to agree with stated positions (sycophancy literature) **[med]**. This makes peer-debate and self-critique less reliable than they look; the fix is to *not* share the original reasoning with the critic (§4.1) **[med]**.

## 4. What improves reliability

1. **Fresh context per reviewer.** Spawn the critic with a clean context and only the artifact to judge, not the original chain of reasoning. An agent that saw *how* you reached an answer is biased toward agreeing. Anthropic explicitly spawns "fresh subagents with clean contexts" at context limits and for new phases **[verified]**; the independent-critic framing is **[med]**.
2. **Independent verification.** Multiple agents verify via diverse paths; subagents do "thorough, independent investigations" rather than one shared trajectory **[verified]**.
3. **Deterministic checks as the feedback layer.** Prefer tests, linters, compilers, type-checkers, and schema validation over LLM self-assessment wherever correctness is checkable. LLM self-grades are noisy and self-biased; a deterministic pass/fail is ground truth. Anthropic still leans on LLM-as-judge for *free-form* research output, but pairs it with deterministic safeguards (retry, checkpoints) and rubric grading **[verified for the deterministic-safeguard part; the general principle is high-confidence practitioner consensus]**.
4. **Small bounded tasks.** Smaller scope = smaller error surface and easier verification. Anthropic's effort-scaling (right-size subagent count/tool calls to complexity) is exactly this **[verified]**.
5. **Explicit contracts/interfaces between agents.** Each subtask carries an objective, output format, tool guidance, and boundaries; structured outputs passed by reference. The most-cited reliability lever in the Anthropic post **[verified]**.

## 5. When a single agent + tools beats a team

- The task is **sequential / deeply interdependent** (each step depends on the previous) **[verified]**.
- It needs **one shared context** (agents can't be cleanly partitioned) **[verified]**.
- **Coding** and other low-parallelism work — "fewer truly parallelizable tasks than research" **[verified]**.
- A single context window **holds the whole problem** and good tools let one agent do it all.
- **Coordination overhead > parallelism benefit** — default to a single agent with strong tools; add agents only when the task is parallelizable, breadth-heavy, or exceeds one context window **[verified + med]**.

## 6. Decision heuristics (synthesis)

- **Default to one agent + tools.** Add agents only for parallelizable breadth, >1-context-window info, or many heterogeneous tools.
- **Right-size**: 1 agent for lookups, 2–4 for comparisons, 10+ only for genuinely parallel research.
- **Contract-first**: objective + output format + tools + boundaries on every subtask; pass structured outputs by reference.
- **Isolate the critic**: fresh context, artifact-only, ideally backed by a deterministic check.
- **Budget for ~15× tokens** and only spend it on high-value tasks.
- **Instrument**: full tracing, decision-pattern monitoring, end-state (not step-by-step) evaluation.
