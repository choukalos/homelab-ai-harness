# Organizational Design Theory → Agent Org Design Rules

A structured distillation of validated organizational theory into actionable design rules for organizations of LLM agents. Confidence: **[H]** = well-established theory, direct transfer; **[M]** = theory applies but agent-specific adaptation required; **[L]** = speculative, needs empirical validation.

---

## 1. Mintzberg's Five Configurations

Mintzberg (1979) identifies five organizational archetypes by coordination mechanism. **[H]**

| Configuration | Agent Analogue | Fit |
|---|---|---|
| **Simple Structure** | Single orchestrator directing a few workers | Small tasks, low ambiguity |
| **Machine Bureaucracy** | Pipeline agents with fixed prompts + validation gates | Repetitive, well-defined work |
| **Professional Bureaucracy** | Specialist agents with domain-specific prompts + peer review | Knowledge work requiring depth |
| **Divisional** | Independent project pods, each a mini-team | Parallel independent deliverables |
| **Adhocracy** | Swarm/debate patterns, multi-perspective reasoning | Novel problems, high ambiguity |

**Design Rule:** Match configuration to task structure. Repetitive → machine bureaucracy. Novel → adhocracy. Scale by divisional replication, not by deepening a single hierarchy. **[H]**

---

## 2. Span of Control

Human span (3–7) derives from cognitive bandwidth: a manager must hold subordinates' state in working memory. **[H]**

**What changes for agents:**
- **Context windows are large but effective attention degrades** with token count. The binding constraint is signal-to-noise ratio, not raw capacity.
- **Error compounding is the real cost.** If sub-agents produce 95% fidelity outputs, a span of 10 compounds to ~60% aggregate fidelity without verification.
- **Verification is the bottleneck, not comprehension.** Agents can read all outputs instantly; the constraint is whether the orchestrator can *verify* each meaningfully.

**Design Rule:** Bound span by **verification capacity**, not context capacity. Practical range: 3–7 when outputs require judgment; 10–20 when outputs are machine-verifiable (schema-conformant, testable). Pair high-span with automated verification gates. **[M]**

---

## 3. Conway's Law and Its Inverse

**Conway's Law (1967):** "Any organization that designs a system will produce a design whose structure is a copy of the organization's communication structure." **[H]**

**Agent-specific reading:** The communication topology of your agent org *is* your system architecture. A flat team of 10 agents produces monolithic output. A 3-level hierarchy produces layered, modular output.

**Inverse Conway's Law (Wernick 2011):** "Design your org structure to match the system architecture you want." **[M]**

**Design Rule:** Design the agent communication graph *before* assigning tasks. Want modular, independently deployable components? Structure agents as isolated pods with narrow interfaces. Want a coherent narrative? Use a single orchestrator with deep context. The org structure is the architecture. **[H]**

---

## 4. Principal-Agent Problem & Verification Asymmetry

Jensen & Meckling (1976): the agent has information and incentives the principal cannot fully observe. Moral hazard follows. **[H]**

**Agent-specific amplification:**
- LLMs appear confident regardless of actual competence (no reliable "I don't know" signal).
- The orchestrator observes only output, not internal reasoning.
- **Incentive asymmetry:** A sub-agent is optimized to produce *plausible* output, not *correct* output. Without external verification, "plausible" is the equilibrium.

**Design Rule:** Every agent output must be **independently verifiable** by a mechanism that does not trust the producing agent: test execution, schema checking, a separate critic agent, or cross-checking against ground truth. No agent is its own verifier. **[H]**

---

## 5. Bounded Rationality & Satisficing (Simon, 1947)

Simon: decision-makers don't optimize; they *satisfice*—accept the first option meeting a threshold. Rational under cognitive and information constraints. **[H]**

**Agent-specific reading:** LLMs are *naturally* satisficers. They produce the first plausible completion, not the optimal one. The design question is: *what is the threshold, and who enforces it?*

**Design Rule:** Make satisficing thresholds **explicit and external**. Encode acceptance criteria in the task specification ("pass all tests," "cite 3+ sources," "match this schema") rather than relying on the agent's internal "good enough" judgment. The org defines the bar; the agent meets it. **[M]**

---

## 6. Galbraith's Coordination Mechanisms

Galbraith (1967, 1994) ranks coordination by increasing complexity:

| Mechanism | Agent Form | Fit |
|---|---|---|
| **Direct supervision** | Orchestrator reads all outputs | Small teams, high-stakes |
| **Standardization of processes** | Fixed prompt templates, pipeline stages | Repetitive tasks |
| **Standardization of outputs** | Schemas, type signatures, test suites | Scalable production |
| **Standardization of inputs** | System prompts, tool access, context curation | Onboarding agents |
| **Standardization of skills** | Domain-specific fine-tuning, RAG grounding | Specialist agents |
| **Mutual adjustment** | Multi-agent debate, shared blackboard | Novel/complex problems |

**Design Rule:** Use the **cheapest sufficient** mechanism. Standardize outputs (schemas + tests) before adding mutual adjustment (debate). Reserve debate for problems with no standard solution. Over-coordinating wastes tokens; under-coordinating produces garbage. **[H]**

---

## 7. Team Topologies (Skelton & Pais, 2019)

Four types: **Product** (user-facing), **Platform** (enabling infrastructure), **Enabling** (improvement), **Complicated Subsystem** (deep expertise). Key principle: cognitive load per team should fit in one mind.

**Agent-specific mapping:**
- **Platform agents:** Tool wrappers, memory systems, retrieval pipelines—stable, high-reuse.
- **Product agents:** Task-specific orchestrators composing platform services.
- **Enabling agents:** Meta-agents that improve prompts, detect drift, propose refactors.

**Design Rule:** Structure as **platform + product layers**. Extract stable, reusable capabilities into platform agents. Keep product agents thin—orchestrating, not implementing. This reduces cognitive load per agent and enables independent scaling. **[M]**

---

## 8. Brooks's Law & Non-Linear Capacity

Brooks (1975): "Adding manpower to a late project makes it later." Communication overhead grows O(n²). **[H]**

**Agent-specific reading:** Adding agents does *not* linearly add capacity because:
- **Context is shared and finite.** Each output consumes the orchestrator's context budget.
- **Integration cost is superlinear.** Merging n outputs requires O(n²) consistency checks or an O(n) pass that degrades.
- **Error correlation.** Agents sharing the same model and prompt style produce *correlated* errors—adding agents doesn't diversify the error distribution.

**Design Rule:** Scale by **divisional replication** (independent pods with separate contexts), not by adding agents to one orchestration loop. A pod of 3 on isolated sub-problems outperforms 9 in one shared context. Add coordination only when pods must integrate. **[M]**

---

## 9. Hierarchy Depth vs. Communication Cost

Each level adds: latency (sequential calls), distortion (re-encoding loses information), and bottleneck risk (single point of failure). **[H]**

**Agent-specific reading:**
- **Latency is wall-clock time.** A 4-level hierarchy means 4+ sequential LLM calls per decision.
- **Distortion compounds.** By level 3, original intent may be unrecognizable.
- **Bottleneck risk is amplified.** A single orchestrator failure halts the entire subtree.

**Design Rule:** Keep depth ≤ 3 levels (goal decomposition → domain orchestration → atomic work). Flatten deeper structures by promoting capabilities into platform services. Use asynchronous message passing to reduce latency; structured interfaces (schemas) to reduce distortion. **[M]**

---

## Summary: Agent Org Design Checklist

1. **Match configuration to task** (Mintzberg): repetitive → pipeline; novel → debate.
2. **Bound span by verification capacity**, not context capacity.
3. **Design the communication graph first**; it becomes the architecture (Conway's inverse).
4. **No agent is its own verifier**; every output needs an independent check.
5. **Encode satisficing thresholds externally** in task specs (Simon).
6. **Use the cheapest sufficient coordination mechanism** (Galbraith).
7. **Layer as platform + product**; keep product agents thin (Team Topologies).
8. **Scale by divisional replication**, not by adding agents to one loop (Brooks).
9. **Depth ≤ 3 levels**; flatten via platform extraction.

---

*Confidence summary: Core organizational theory is well-established [H]. Transfers to agent contexts are reasoned analogies [M] requiring empirical validation. No published empirical study of LLM agent org design exists yet (as of early 2025); all agent-specific claims are extrapolations.*
