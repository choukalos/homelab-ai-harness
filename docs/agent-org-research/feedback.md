# Feedback & Control Theory for Agent Organizations

*Research note — synthesized from control theory, cybernetics, and organizational learning literature. Confidence: high for classical control/cybernetics claims; medium for direct transfer to LLM agent orgs (no validated empirical base yet, but structural analogy is sound).*

---

## 1. The Basic Control Loop

**Theory.** Any regulator operates a closed loop: sense the controlled variable → compare to setpoint → compute error → apply corrective action → re-sense. Open-loop systems act without feedback (e.g., a timer); they drift. Closed-loop systems (thermostat, autopilot) self-correct because the output feeds back into the input.

**Design rule.** Every agent task must have a **measurable output** and a **setpoint** (acceptance criterion). An agent that produces output with no automated check is open-loop. Wire every deliverable to at least one machine-evaluable predicate (test passes, schema validates, linter clean, diff size within budget).

---

## 2. Cybernetics & Beer's Viable System Model (VSM)

**Theory.** Stafford Beer's VSM (1972) decomposes any viable system into five subsystems:

| # | Subsystem | Function | Agent-org analog |
|---|-----------|----------|-----------------|
| 1 | **Operation** | Executes the work | Individual LLM agents running tasks |
| 2 | **Coordination** | Arbitrates between ops, prevents conflict | Orchestrator / task router that assigns, sequences, resolves dependencies |
| 3 | **Regulation (Quality)** | Monitors outputs, feeds error signals back | CI/CD gates, automated review, OKR dashboards |
| 4 | **Intelligence (Adaptation)** | Scans environment, models system, proposes structural change | Meta-agent or human-in-loop reviewing OKR trajectories, re-prioritizing |
| 5 | **Policy (Executive)** | Sets goals, resolves conflicts, maintains viability | OKR owner / product lead who sets objectives, arbitrates trade-offs |

Beer's key insight: a system is **viable** only if all five are present and properly nested. Missing regulation means errors accumulate silently; missing adaptation means the system cannot respond to regime change.

**Design rule.** An agent org needs all five layers: (a) agents execute, (b) an orchestrator coordinates, (c) automated quality gates regulate, (d) a periodic meta-review adapts the plan, (e) a human or top-level policy agent sets and updates OKRs. If any layer is absent, the org is not viable.

---

## 3. OODA Loop & Tempo

**Theory.** Boyd's OODA (Observe → Orient → Decide → Act) is a decision cycle. The critical variable is **tempo**: the side that completes its OODA cycle faster than the environment gains advantage. A slow OODA loop means reacting to stale information.

**Design rule.** Minimize **full-cycle latency** of each agent's observe-decide-act loop: (a) fast observation (live logs, test results in <30 s), (b) constrained orientation (clear task spec, bounded context), (c) cheap decisions (small increments, reversible actions), (d) immediate action (commit, push, merge) rather than batching. An agent running a 2-hour batch before checking results has a 2-hour OODA cycle; one testing after every 10-minute increment has a 10-minute cycle.

---

## 4. Senge's Learning Organization & Feedback Delays

**Theory.** Senge (1990) identifies **systems thinking** as the core discipline: organizations fail not from lack of intelligence but from **feedback delays** and **local rationality**. A lever pulled today may not show effect for weeks; by then the operator has pulled another lever, compounding the error. This is the "fixes that fail" archetype.

**Design rule.** **Make feedback delays explicit and short.** For each OKR key result, document: (a) what metric measures it, (b) update frequency, (c) lag between action and measurable effect. If a metric only updates quarterly, the effective control loop is quarterly—too slow. Add **leading indicators** (e.g., "PRs merged this week" as a leading indicator for "feature shipped by Friday") so the inner loop is weekly, not quarterly.

---

## 5. Error-Detection Latency: The Key Variable

**Theory.** In control theory, the **detection-to-correction delay** determines stability. Fast detection + small corrections = stable. Slow detection + large corrections = oscillation or divergence. Same principle as "shift-left": catch bugs early, fix them cheaply.

**Design rule.** **Detect failure fast; correct in small increments.** Run tests/linters after every agent action (seconds), integration checks per task (minutes), OKR measurement per week (days), strategic review per quarter (weeks). The inner layer catches 90% of failures with a 2-minute correction; the outer catches the remaining 10% requiring re-planning. Skip the inner layer and the outer must correct 100× larger errors at 100× higher cost.

---

## 6. Layered Feedback Architecture

| Layer | Cadence | Sensor | Setpoint | Corrective action |
|-------|---------|--------|----------|-------------------|
| **Inner (per-task)** | Seconds–minutes | Unit tests, type checks, linters, schema validation | Task acceptance criteria | Agent retries, fixes, or escalates |
| **Mid (per-OKR)** | Daily–weekly | Key-result metrics (PRs merged, coverage, latency) | OKR target trajectory | Orchestrator re-assigns, re-prioritizes |
| **Outer (per-strategy)** | Monthly–quarterly | Objective achievement rate, market signals, org health | Strategic objectives | Policy layer revises OKRs, re-architects |

**Design rule.** Each layer has its own **sensor, setpoint, and authority to act**. The inner layer fixes code; the mid layer re-prioritizes; the outer changes goals. Do not let the outer layer micromanage the inner (causes thrashing) or the inner override the outer's objectives (causes drift).

---

## 7. Observability: Logs, State, Artifacts as Sensors

**Theory.** A control system is only as good as its sensors. In an agent org, the "physical plant" is the codebase, task queue, and pipeline. **Observability** (metrics, logs, traces) is the sensor layer.

**Design rule.** Every agent must emit **structured, machine-readable state**:
- **Task state**: status, timestamps, error messages.
- **Artifacts**: code diffs, test reports, generated docs—versioned and inspectable.
- **Metrics**: tokens consumed, iterations, success/failure counts.
- **Traces**: causal chain from objective → task → action → result.

If the orchestrator cannot *read* the agent's state programmatically, the feedback loop is broken. Natural-language self-reports are opinions, not sensors.

---

## 8. Machine-Checkable Outputs

**Theory.** Feedback is only objective if the signal is generated by something other than the agent being evaluated. Self-graded agents have a conflict of interest: sensor and actuator are the same component.

**Design rule.** For every task, define at least one **external predicate** that an independent process evaluates:
- Code: tests pass, type-checks, lint clean, diff size < N lines.
- Docs: structure valid, links resolve, word count in range.
- Data: schema conforms, row count within bounds, no nulls in required fields.
- Research: citations resolve, claims traceable to source.

The agent proposes; the pipeline disposes. If no external predicate exists, the task is **not closed-loop** and must be flagged.

---

## 9. Anti-Patterns

| Anti-pattern | Symptom | Fix |
|---|---|---|
| **End-of-sprint feedback only** | Errors compound for weeks; correction is expensive | Add inner-loop checks (per-task, per-commit) so 90% of errors are caught in minutes |
| **Self-graded agents** | Agent reports "success" but output is broken | Require external predicates; the agent cannot approve its own work |
| **No correction authority** | Agent detects error but cannot fix it; escalates to unavailable human | Grant bounded correction authority: retry, fix, re-run. Escalate only beyond scope |
| **Thrashing (too-tight loop)** | Agent oscillates: fix A breaks B, fix B breaks A | Add **stability constraint**: same error >N times → stop and escalate. Use hysteresis (deadband) on setpoint |
| **Missing adaptation layer** | Org hits regime change and cannot pivot | Schedule periodic meta-reviews; give policy layer authority to change OKRs |
| **Open-loop tasks** | Agent produces output, no one checks, it ships broken | No task is "done" without passing at least one external predicate |

---

## 10. Summary: The Feedback Stack

```
┌─────────────────────────────────────────────────────┐
│  POLICY (Quarterly)                                  │
│  Set/revise OKRs · Arbitrate trade-offs · Viable?    │
├─────────────────────────────────────────────────────┤
│  ADAPTATION (Weekly)                                 │
│  Review OKR trajectory · Re-prioritize · Re-arch     │
├─────────────────────────────────────────────────────┤
│  REGULATION (Per-task / Per-commit)                 │
│  Tests · Linters · Schema checks · OKR dashboards    │
├─────────────────────────────────────────────────────┤
│  COORDINATION (Continuous)                           │
│  Task routing · Dependency resolution · Conflict     │
├─────────────────────────────────────────────────────┤
│  OPERATION (Per-action)                              │
│  LLM agents execute tasks · Emit state · Act         │
└─────────────────────────────────────────────────────┘
```

Each layer is a closed loop with its own sensor, setpoint, and corrective authority. The system is viable only if all layers are present, properly nested, and the feedback delay at each layer is shorter than the timescale of the errors it must catch.

---

*Sources: Beer (1972) "Platform for Time"; Boyd (1996) "Strategic Dominance"; Senge (1990) "The Fifth Discipline"; classical control theory (Franklin, Powell & Workman); SRE observability literature (Beyer et al., 2016). Transfer to LLM agent orgs is structural analogy—validated in principle, not yet empirically at scale.*
