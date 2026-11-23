---
name: exec-problem-brief
description: Generate a McKinsey-style board-ready Problem-Solving Brief from a structured problem statement — Minto answer-first executive summary, SCQ framing, a 3-5 branch MECE issue tree with falsifiable hypotheses, an evidence and falsification matrix, exactly 3 strategic pillars, a phased roadmap (0-2w / 2-8w / 2-6m) with owner and KPI on every item, and a risk and control matrix with trigger thresholds. Use when pitching a high-stakes business problem to an exec, board, or investor, for a deep-dive opportunity pitch, or when asked for an executive problem brief.
---

# Exec Problem Brief

A McKinsey-style executive problem-solving brief — board-ready
"Problem-Solving Brief" from a structured problem statement. Built from the
spec provided by chuck 2026-11-22, preserved verbatim at
`references/source-prompt.md` — **read it when producing a brief**; it is the
authoritative pipeline definition (step names, per-step requirements,
constraints, output format). This skill makes that spec a repeatable,
verifiable agent workflow: input template → 7-step pipeline → 7-section
brief.

Family-agent skill (brief family alongside `investment-brief` /
`market-research-brief`), not kanban-specific. No tools required beyond what
the agent has — `mcp_search` for market context is optional, and the
no-fabrication rule means research is an option, not a dependency.

## Input — the structured problem template

Collect the five fields **before running** the pipeline. If fields are
missing, ask for them — do not guess (the no-fabrication rule applies to
inputs too):

1. **Corporate Profile** — industry & business model; scale & footprint.
2. **Core Challenge & Context** — primary symptom/bottleneck; urgency
   catalyst.
3. **Known Baseline Data & Financials** — current run-rate metrics; available
   hypotheses.
4. **Structural Constraints** — capital/budget limits; governance/operational
   boundaries.
5. **Core Decision Required** — the specific board/leadership approval being
   asked for.

## Hard constraints (never violate)

- **Never fabricate figures, benchmarks, or operational metrics.** When data
  is missing, state the economic equation + the fastest empirical test that
  would fill the gap — never a plausible-sounding number.
- **Answer-first.** No background narrative or contextual preamble before
  stating the answer (Minto Pyramid Principle).
- **Strict economic/operational causality** across every diagnostic finding
  and recommendation — every claim transmits to a financial lever (growth,
  margin, cash flow, enterprise value).
- **Decisive action titles, no generic headers.** Open every section with a
  full-sentence analytical insight, not a category label.
- Authoritative, objective, boardroom-ready tone. Dense bulleted scaffolding,
  no introductory fluff, no speculative commentary.

## The pipeline (7 steps)

Run in order; Step 0 is an internal diagnostic gate — if it fails, go back to
the input and collect the missing data before generating anything.

1. **Step 0 — Pre-execution diagnostic check.** Isolate the single governing
   strategic question. Identify the primary economic metric impacted (ROIC,
   EBITDA margin, free cash flow, valuation multiple). Verify the issue-tree
   decomposition is strictly MECE with complete causal transmission logic.
   Ensure every proposed initiative links to an accountable role, delivery
   timeframe, and measurable KPI.
2. **Step 1 — Executive summary (one-page board memo).** Lead immediately with
   the Primary Strategic Recommendation (one bold, unambiguous declarative
   statement). Three supporting action titles as full-sentence analytical
   insights. Value at Stake quantified — if baseline figures are missing,
   define the explicit economic equation + measurement method. Required
   Leadership Decisions (concrete capital/structural/governance approvals).
   Economic Value Pathway (the transmission mechanism: actions → margins /
   cash / multiple expansion).
3. **Step 2 — SCQ framing.** Situation (factual baseline, trajectory,
   constraints, observable market signals). Complication (the catalyst
   forcing action, explicit cost/risk of inaction, time horizon, downside
   exposure). Governing Question (one precise core question + 2–3 MECE
   sub-questions).
4. **Step 3 — Diagnostic MECE issue tree.** 3–5 MECE analytical branches. Per
   branch: Governing Hypothesis (testable, falsifiable), Sub-Driver
   Decomposition, Required Data to Validate, Fastest Validation Test (the
   80/20 test), Economic Transmission Mechanism.
5. **Step 4 — Evidence & falsification matrix.** For the top 3–5 high-impact
   uncertainties: the hypothesis under test, the exact data sets/metrics
   required, the falsification criteria (what specific finding refutes it),
   and the **binary decision fork** (Action A if validated vs. Action B if
   refuted).
6. **Step 5 — Strategic recommendation pillars.** **Exactly 3** pillars. Per
   pillar: Action-Oriented Header (full-sentence imperative insight), Core
   Initiatives strictly as [Action Verb] + [Specific Operational Object] +
   [Target Metric/Outcome], Implementation Timeline, Accountable Executive
   Role, Critical Enabling Conditions, Direct Economic Contribution
   (measurable EBITDA / working capital / revenue impact).
7. **Step 6 — Phased implementation roadmap.** Immediate (0–2 weeks:
   mobilization, governance, stop-loss) → Short-Term (2–8 weeks: core
   redesign, pilots, capability) → Medium-Term (2–6 months: scale, value
   realization, institutionalization). Every action item as
   **[Verb] + [Object] + [Target KPI] + [Single Owner] + [Deadline]**, tagged
   Impact (H/M/L), Effort (H/M/L), Execution Feasibility (H/M/L).
8. **Step 7 — Risk & control matrix.** Per material risk: Risk Description &
   Failure Mode, Probability (L/M/H) & Impact (L/M/H), Leading Detection
   Indicator (early quantifiable signal), Trigger Threshold (the metric
   boundary that mandates intervention), Pre-Planned Mitigation Action,
   Fragility Exposure (which recommendation pillar this failure mode hits).

## Output — the 7-section brief

1. Executive Summary (Minto Answer-First Board Memorandum)
2. Strategic Context (Situation – Complication – Governing Question)
3. Diagnostic MECE Issue Tree & Hypotheses
4. Evidence & Falsification Matrix
5. Strategic Recommendation Pillars
6. Phased Implementation Roadmap (with metric & owner traceability)
7. Risk, Trigger, & Control Matrix

## Self-check before delivering

- Answer appears in the first sentence of the Executive Summary?
- Every figure traceable to the input, or explicitly flagged as an equation +
  test (nothing fabricated)?
- Issue tree MECE — zero overlap, zero gaps?
- Exactly 3 pillars? Every roadmap item has a single owner + deadline + KPI?
- Every risk has a leading indicator *and* a trigger threshold?
- Every section opens with a decisive action title, not a category header?
- Logical traceability: root-cause diagnosis → pillar → roadmap initiative,
  no orphan claims?
