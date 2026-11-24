# OKRs for Managing LLM Agent Teams

*Research note — synthesized from training knowledge (no live search available). Confidence marked per section.*

---

## Core Mechanics

**Confidence: High** (well-documented, stable literature)

**Origin.** Andy Grove codified OKRs at Intel in the 1970s (documented in *High Output Management*, 1983). John Doerr brought the framework to Google in 1999 after visiting Intel; he popularized it publicly in *Measure What Matters* (2018). Google's early "75/20" structure (75% committed, 25% stretch) is the canonical corporate example.

**Structure.**

- **Objective (O):** A qualitative, aspirational, time-bound statement of *what* you want to achieve. Should be memorable and directionally clear. Example: "Deliver the best onboarding experience in our category."
- **Key Results (KRs):** 3–5 measurable, quantitative indicators that define *how you'll know* the objective is met. Each KR has a baseline and a target. Example: "Reduce time-to-first-value from 14 min to <4 min."

**Scoring.**

- Each KR is scored 0.0–1.0 on a linear scale (0.0 = no progress, 1.0 = target fully met).
- A "good" quarter for stretch OKRs lands at **0.6–0.7**. Consistently hitting 1.0 on stretch OKRs signals the target was too conservative.
- Committed OKRs (must-hits) target 1.0; missing them is a problem to investigate.

**Stretch vs. Committed.**

- *Committed* OKRs are non-negotiable business goals (e.g., "Ship v2.0 by Q3"). Missing is a failure.
- *Stretch* (or "aspirational") OKRs push the frontier. Hitting 0.7 is a success; 1.0 is exceptional.
- A healthy mix is roughly 70% committed / 30% stretch at the team level.

**Differentiation from KPIs and Tickets.**

| Dimension | OKR | KPI | Ticket/Task |
|-----------|-----|-----|-------------|
| Purpose | Direction & alignment | Health monitoring | Execution tracking |
| Timeframe | Quarterly (or annual for org) | Continuous | Per-task |
| Count | 3–5 KRs per O | Many (dashboards) | Unlimited |
| Scoring | 0–1, target 0.6–0.7 | Threshold-based (RAG) | Done / not done |
| Ownership | Team-level | Org-level | Individual |

KPIs are *always-on* metrics you watch (latency, churn). OKRs are *directional bets* you commit to for a bounded period. Tickets are the *work items* that help you move KRs; they are not KRs.

---

## Cadence & Feedback Loop

**Confidence: High** (standard practice at Google, Intel, and Doerr's consulting clients)

- **Quarterly cycle.** OKRs are set at the start of a quarter (or fiscal quarter). They are *not* annual-only; the quarter is the atomic unit of commitment.
- **Weekly check-in (15–30 min).** Each team member updates KR scores. The leader asks: "What moved? What's blocked? What do we need?" This is a *scoring* ritual, not a status report.
- **Mid-quarter pulse.** A lighter sync to confirm direction hasn't drifted. Adjust KRs if the landscape changed materially (rare; Doerr warns against mid-quarter edits that signal low commitment).
- **Quarter-end review.** Score all KRs (0.0–1.0). Write a 1–2 paragraph narrative: what worked, what didn't, what we learned. This becomes input to next quarter's OKR-setting.
- **Cascade, don't cascade-down.** OKRs are set top-down for *direction* and bottom-up for *specifics*. Each team owns 3–5 OKRs that align to the org's 3–5.

**Anti-pattern:** Treating the weekly check-in as a task-status meeting. The question is always "what is the score on each KR?" not "what did you work on?"

---

## Failure Modes

**Confidence: High** (repeatedly documented in Doerr, Intel post-mortems, and practitioner literature)

1. **Too many KRs.** More than 5 KRs per Objective dilutes focus. More than 3 Objectives per team per quarter means no alignment.
2. **No measurement.** A KR without a number, a baseline, and a target is not a KR. "Improve code quality" is not measurable.
3. **Treating OKRs as a to-do list.** If every KR is "Ship feature X," you've written a sprint backlog. KRs should be *outcomes*, not activities.
4. **Annual-only cadence.** Without quarterly reset and weekly scoring, OKRs become wall art. The feedback loop is the mechanism; the document is not.
5. **Conflating KPIs with KRs.** "Maintain 99.9% uptime" is a KPI. It belongs on a dashboard, not in an OKR set, unless the *objective* is specifically about reliability.
6. **No consequence to scoring.** If 0.7 is never discussed, nobody calibrates. The 0.6–0.7 target must be named explicitly so teams calibrate ambition.
7. **Cascading only downward.** If every OKR is assigned top-down, teams lose ownership and the bottom-up signal that makes OKRs work.

---

## Agent-System Implications

**Confidence: Medium** (emerging practice; limited peer-reviewed literature as of early 2025)

Direct literature on "OKRs for LLM agents" is sparse. However, the structural principles map cleanly onto multi-agent orchestration:

**Goal decomposition.** OKRs are a form of hierarchical goal decomposition: Org Objective → Team Objective → Key Results → Tasks. This mirrors how agent systems decompose a user goal into sub-goals and atomic actions (cf. ReAct, HuggingGPT, AutoGen patterns). The OKR discipline of *3–5 measurable sub-goals per level* is a useful constraint that prevents combinatorial explosion in agent planning.

**Scoring as a feedback signal.** The 0–1 KR score is a natural reward/progress signal for an orchestrator agent. An orchestrator can:
- Read KR scores after each "sprint" (analogous to weekly check-in).
- Reallocate agent effort toward KRs scoring < 0.5 (lagging).
- Detect when all KRs are at 1.0 and the objective is met (termination condition).

**Stretch vs. committed maps to exploration vs. exploitation.** Committed KRs are the "must-ship" path; stretch KRs are the "try something ambitious" path. An orchestrator can set a 70/30 split to balance reliability and discovery in agent behavior.

**Failure-mode transfer.**
- *Too many KRs* → agent over-decomposes, loses coherence. Cap sub-goals.
- *No measurement* → agent cannot evaluate its own progress. Every sub-goal needs a checkable predicate.
- *To-do list* → agent plans activities without linking them to outcomes. Enforce outcome-language.
- *No cadence* → agent runs open-loop. Enforce periodic scoring checkpoints.

**Practical pattern for LLM agent teams:**

```
Org Goal (user's ask)
  └─ Objective (qualitative, 1 sentence)
       └─ KR1: <measurable outcome, target, baseline>
       └─ KR2: ...
       └─ KR3: ...
            └─ Agent tasks (atomic, assigned)
```

Each agent reports a 0–1 score on its KR at each checkpoint. The orchestrator reviews scores, reassigns, or terminates. The quarterly cadence becomes a "sprint" (e.g., 5–10 agent turns or a timebox).

**Open questions / research gaps:**
- No standardized literature on optimal KR count for agent sub-goals (3–5 is the human-team heuristic; agents may handle more).
- Unclear whether the 0.6–0.7 "good" target transfers (agents don't have the same risk-aversion bias humans do).
- Whether stretch OKRs improve agent exploration vs. just adding variance is untested.

---

## Sources / Notes

| Source | Type | Notes |
|--------|------|-------|
| Grove, *High Output Management* (1983) | Primary | Origin of OKRs at Intel |
| Doerr, *Measure What Matters* (2018) | Primary | Google adoption, 75/20, 0.6–0.7 target |
| Doerr, "The Secrets of Google's Success" (Stanford GSB, 2012) | Talk | Early public exposition |
| Intel / Google internal practice (as described by Doerr) | Anecdotal | Cadence, scoring rituals |
| ReAct (Yao et al., 2023), AutoGen (Wu et al., 2023), HuggingGPT (Shen et al., 2023) | Research | Agent goal-decomposition patterns; structural analogy only |
| No peer-reviewed "OKRs for agents" paper found in training data | Gap | This is an emerging practice space |

**Confidence summary:** Core mechanics and failure modes are high-confidence (decades of practitioner documentation). Cadence is high-confidence. Agent-system implications are medium-confidence (structural analogy, no direct empirical validation yet).
