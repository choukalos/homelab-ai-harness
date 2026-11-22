# Agent Skill Authoring — Best Practices (R1 research digest)

> Research item **R1** of the agent-skills plan (`todo_agent_skills.md`), run
> 2026-11-22. Method: every load-bearing claim below was verified by direct fetch of
> the primary source on that date (digest discipline — a structured model with
> verified claims, not a summary). The sanctioned `deep_research` pass (job
> `d38da3aa1042`, artifact `data/media/research_reports/
> deep_research_2026-11-22T23-11-34_Best-practices-for-authoring-AGENT-SKILLS*.md`)
> returned only empty KB entries and declared the source gap; the findings rest on
> the primary sources below.
>
> **Sources (all fetched 2026-11-22):**
>
> - [1] Anthropic, *Skill authoring best practices* —
>   `platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices`
> - [2] Agent Skills open specification — `agentskills.io/specification`
>   (page updated 2026-08-04)
> - [3] Agent Skills, *Best practices for skill creators* —
>   `agentskills.io/skill-creation/best-practices`
> - [4] Agent Skills, *Optimizing skill descriptions* —
>   `agentskills.io/skill-creation/optimizing-descriptions`
> - [5] Agent Skills, *Evaluating skill output quality* —
>   `agentskills.io/skill-creation/evaluating-skills`
> - [6] Agent Skills, *Using scripts in skills* —
>   `agentskills.io/skill-creation/using-scripts`
> - [7] Destefanis (UCL), *Authoring Agent Skills: A Software-Engineering Approach* —
>   `arxiv.org/abs/2607.25032`
> - [8] `anthropics/skills` repo — `skills/skill-creator/SKILL.md` (485 lines),
>   `template/SKILL.md`, repo layout (19 example skills)
> - [9] Agent Skills overview — `agentskills.io` (open standard, client showcase)

## Contents

- [The loading model (why everything else follows)](#the-loading-model)
- [The description (the trigger)](#the-description-the-trigger)
- [The body (concise, structured)](#the-body-concise-structured)
- [Split vs merge (granularity)](#split-vs-merge-granularity)
- [Choosing the mechanism (skill vs hook vs memory vs subagent vs MCP)](#choosing-the-mechanism)
- [Patterns for effective instructions](#patterns-for-effective-instructions)
- [Bundling scripts](#bundling-scripts)
- [Evaluation and iteration (the process)](#evaluation-and-iteration)
- [Failure modes (consolidated)](#failure-modes-consolidated)
- [Ecosystem and tooling](#ecosystem-and-tooling)

## The loading model

Skills load in **three tiers** (progressive disclosure) [2][9][8]:

1. **Metadata** — `name` + `description`, loaded at startup for *all* skills
   (~100 tokens each). This is the only part the selector reads.
2. **Instructions** — the full SKILL.md body, loaded when the skill is activated
   (< 5000 tokens recommended; < 500 lines) [2][1].
3. **Resources** — `references/`, `scripts/`, `assets/`, loaded only when needed.
   Scripts can be *executed* without their source entering context — only the
   output consumes tokens [1][2].

Consequences that drive all other guidance [1][3]:

- The context window is a **public good** — the skill shares it with the system
  prompt, conversation history, other skills' metadata, and the actual request.
- The description carries the **entire burden of triggering** [4].
- Once the body is loaded, **every token competes** with conversation history —
  conciseness matters even though loading is lazy.

## The description (the trigger)

Rules, consolidated across [1][2][4][7][8]:

- **What it does + when to use it** — both, always. "Each skill has exactly one
  description field… Claude uses it to choose the right skill from potentially 100+
  available skills" [1]. Vague descriptions ("Helps with documents", "Handles
  releases") give the model nothing to match against [1][7].
- **Third person** — it's injected into the system prompt; first/second person
  ("I can help…", "You can use this…") degrades matching [1][7].
- **Specific, with key terms** — include the concrete terms a relevant task would
  contain, and specific triggers/contexts. Good example from [1]:
  `Extract text and tables from PDF files, fill forms, merge documents. Use when
  working with PDF files or when the user mentions PDFs, forms, or document
  extraction.`
- **A little pushy** — models have a tendency to **under-trigger**; explicitly list
  contexts, including cases where the user doesn't name the domain directly
  ("even if they don't explicitly mention 'CSV' or 'analysis'") [4][8].
- **User intent, not implementation** — describe what the user is trying to achieve,
  not the skill's internal mechanics [4].
- **Concise** — a few sentences to a short paragraph; hard limit **1024 characters**
  [2][4]. It costs tokens in *every* session even when the skill never fires.
- **Nuance** — agents typically consult skills only for tasks beyond what they can
  handle alone; a simple one-step request may not trigger even a perfectly described
  skill [4].

Good vs bad (from [7], with [1] examples):

```
Bad:  Handles releases.
Good: Drafts release notes from the pull requests merged between two version tags.
      Use when cutting a release, updating a changelog, or summarising what
      changed in a version.
```

**Triggering is testable, not vibes** — see `trigger-eval.md` (query set, near-miss
negatives, trigger rate, train/validation split) [4].

## The body (concise, structured)

- **Concise is key** — default assumption: the model is already very smart. Only add
  context it doesn't have [1]. Challenge each piece: "Does this paragraph justify its
  token cost?" [1] / "Would the agent get this wrong without this instruction? If no,
  cut it" [3]. Concrete contrast from [1]: a 150-token PDF explanation vs a 50-token
  "Use pdfplumber: …" — the concise version wins.
- **Under 500 lines**; split into reference files when approaching the limit [1][2].
- **References one level deep** — link every reference file directly from SKILL.md;
  no reference chains. Nested references cause **partial reads** (the model previews
  with `head -100` and acts on incomplete information) [1][2][7].
- **Table of contents** on any reference file longer than ~100 lines (the skill-creator
  example uses ~300) so the model sees the full scope even on a partial read [1][8].
- **Tell the model *when* to load each file** — "Read `references/api-errors.md` if
  the API returns a non-200 status code" beats a generic "see references/ for
  details" [3].
- **Consistent terminology** — one term per concept throughout; mixing synonyms
  ("endpoint / URL / route / path") makes instructions harder to follow [1][7].
- **Forward slashes** in all paths (Windows-style paths break on Unix) [1][7].
- **No time-sensitive information** — "before August 2025 use the old API" dates
  itself; put legacy behaviour in a clearly marked "Old patterns" section [1][7].
- **Degrees of freedom** — match specificity to the task's fragility [1][3][7]:
  - *High freedom* (text instructions, principles + why): multiple approaches valid,
    context-dependent decisions. "Explain why — an agent that understands the purpose
    makes better context-dependent decisions" [3].
  - *Medium* (pseudocode / parameterized scripts): a preferred pattern exists, some
    variation acceptable.
  - *Low* (exact script, "Do not modify the command or add additional flags"):
    fragile operations, consistency critical, exact sequence required.
  - Most skills have a mix — **calibrate each part independently** [3].
- **Defaults, not menus** — presenting multiple approaches as equal options leaves the
  model to choose without grounds; give one default and name the exception [1][3][7].
- **Procedures over declarations** — teach how to approach a *class* of problems, not
  what to produce for one specific instance; the approach should generalize even when
  individual details are specific [3].
- **Aim for moderate detail** — overly comprehensive skills can *hurt*: the model
  struggles to extract what's relevant and may pursue unproductive paths triggered by
  instructions that don't apply to the current task [3].

## Split vs merge (granularity)

- **Single responsibility** — one coherent capability. The description is matched
  against the task: a skill scoped to one class of task is selected more reliably; a
  multi-purpose skill has a diffuse description that matches less well [7].
- **Like a function** — encapsulate a coherent unit of work that composes well.
  Scoped too narrowly → multiple skills load for a single task (overhead + conflicting
  instructions); scoped too broadly → hard to activate precisely [3].
- **Low coupling** — a skill that depends on the internal behaviour or output format
  of another skill is coupled to it; keep such dependencies few and explicit (state
  them as composition) [7]. Cohesion: each reference file groups content serving a
  single concern [7].
- **The adding-value test** — if the agent already handles the entire task well
  without the skill, the skill may not be adding value [3].
- **When to merge instead** — if two "skills" are really one workflow the model must
  run together (one would be useless without the other), they are one skill with
  sections. If a step repeats across roles/workflows (e.g. QA), it is one shared skill
  consumed by many (this is the plan's S-series design).

## Choosing the mechanism

Skills are one of several mechanisms that shape agent behaviour. Choosing the wrong
one is a common source of unreliable behaviour — "a requirement that must hold every
time is written as advisory prose in a place that only sometimes takes effect" [7].
Two questions separate them: **who decides it runs**, and **what guarantee it
provides** [7]:

| Mechanism | Who decides it runs | What it provides | Reach for it when |
|---|---|---|---|
| Memory file (AGENTS.md / CLAUDE.md) | The runtime, always | Standing context, present every turn | Short, general instruction that should stay in view at all times |
| **Skill** | The model (description match) or the user (by name) | Procedural knowledge + bundled resources, loaded in stages | The task needs domain procedure or reference material the model should find on its own |
| Slash command | The user, by typing /name | A saved prompt run on demand | You want to decide exactly when it runs |
| Subagent | The model or the user, by delegating | A separate instance with its own context window | Work should run in isolation to keep the main context focused |
| External tool (MCP) | The model, by calling the tool | A connection to an external service/data | The model must act in the outside world |
| Hook | The runtime, on a lifecycle event | Deterministic execution that can **block** an action | A step must happen every time, or an action must be prevented |

**The decision rule** [7]: judgement-dependent procedure → skill. A requirement that
must hold every time → hook (or harness enforcement). "A standing instruction in a
skill body, however firmly worded, is something the model may read, defer, or skip.
The same instruction expressed as a hook runs unconditionally."

**Implication for this org** (plan cross-ref): the plan's "hard gates" (S11 security
gate, per-project deploy gates) are only as strong as the harness that enforces them
— the kanban QA stage, project `constraints`, deploy gates. The skills *teach the
procedure*; the harness *enforces the guarantee*. Skill prose alone cannot guarantee a
gate.

## Patterns for effective instructions

Reusable techniques — not every skill needs all of them [1][3][7]:

- **Gotchas section** — often the highest-value content: environment-specific facts
  that defy reasonable assumptions (soft deletes, ID field name mismatches across
  systems, a `/health` endpoint that lies). Keep them in SKILL.md — the model reads
  them before encountering the situation. **When the agent makes a mistake you have to
  correct, add the correction to the gotchas section** — the most direct iterative
  improvement [3].
- **Templates for output format** — agents pattern-match well against concrete
  structures; a template is more reliable than describing the format in prose. Match
  strictness to need ("ALWAYS use this exact template" vs "sensible default, adapt as
  needed") [1][3].
- **Checklists for multi-step workflows** — an explicit copy-and-tick checklist
  prevents skipped steps, especially with validation gates [1][3].
- **Validation loops** — do the work → run a validator (script, reference checklist,
  or self-check) → fix → repeat until it passes. A reference document can be the
  "validator" [1][3].
- **Plan-validate-execute** — for batch or destructive operations: write the plan to a
  structured file, validate it against a source of truth with a script, only then
  execute. Verbose validation errors ("Field 'signature_date' not found — available
  fields: …") let the model self-correct [1][3].
- **Examples over abstract style** — worked input/output pairs convey style and
  detail more clearly than descriptions of style [1][7].
- **Conditional workflows** — guide the model through decision points ("Creating new
  content? → follow the Creation workflow; Editing? → follow the Editing workflow")
  [1].
- **Domain organization** — for multi-domain skills, one reference file per variant
  (`references/aws.md`, `references/gcp.md`) so only the relevant file loads [1][8].
- **Explain the why, not just MUSTs** — reasoning-based instructions ("Do X because Y
  tends to cause Z") are followed more reliably than heavy-handed directives [3][8].

## Bundling scripts

- **When**: deterministic or repetitive logic; operations that are fragile to
  generate fresh; anything the model keeps reinventing across runs — "if you notice
  the agent independently reinventing the same logic each run… that's a signal to
  write a tested script once and bundle it" [3]. Scripts are more reliable than
  generated code, save tokens and time, and ensure consistency [1].
- **Run vs read** — make the intent explicit: "Run `scripts/validate.py` to check X"
  (execute; source never enters context) vs "See `scripts/extract.py` for the
  extraction algorithm" (read as reference) [1].
- **Design for non-interactive agent use** [6]:
  - **No interactive prompts** (hard requirement — agents run in non-interactive
    shells; a TTY prompt hangs the run). Input via flags, env, or stdin.
  - **`--help`** is the primary way the agent learns the interface — description,
    flags, examples; keep it concise (it enters context).
  - **Helpful error messages** — what went wrong, what was expected, what to try.
  - **Structured output** — JSON/CSV to stdout (composable with `jq`/`awk`);
    diagnostics to stderr.
  - **Idempotency** (agents retry; "create if not exists" beats "create and fail"),
    reject ambiguous input rather than guessing, `--dry-run` for destructive ops,
    distinct documented exit codes, safe defaults (confirmation flags for destructive
    operations), **predictable output size** (harnesses truncate ~10–30K chars —
    default to a summary/limit or an `--output` file).
- **Solve, don't defer** — scripts handle their own error conditions instead of
  failing and leaving the model to recover; justify every constant (no "voodoo
  constants" — `TIMEOUT = 47 # why 47?` is a bug) [1].
- **Dependencies**: state prerequisites in SKILL.md (or the `compatibility`
  frontmatter field) rather than assuming the environment [1][6]. Pin versions for
  one-off commands (`npx eslint@9.0.0`, `uvx ruff@0.8.0`); self-contained Python
  scripts can declare inline dependencies (PEP 723, run with `uv run`) [6].

## Evaluation and iteration

The process is **eval-driven**, not documentation-first [1][3][5][7]:

1. **Build evaluations first.** Run the model on representative tasks *without* the
   skill; record where it fails or lacks context. Turn failures into a small set of
   test cases (start with 2–3) with expected behaviours. Establish the baseline, write
   the **minimum** instructions to pass, iterate [1][5][7]. "This keeps the skill
   aimed at real gaps rather than imagined ones" [7].
2. **Test cases** = realistic prompt + expected output + input files, stored in
   `evals/evals.json` inside the skill dir. Vary phrasing/detail/formality; include at
   least one edge case; use realistic context (file paths, names, casual language) [5].
3. **Run each case with and without the skill** (or against the previous version as
   baseline). Clean context per run (fresh session/subagent). Record timing
   (tokens, duration) [5].
4. **Assertions** — verifiable statements, added *after* the first run ("The output
   file is valid JSON", "The report includes at least 3 recommendations" — not "The
   output is good"). Mechanical checks via scripts; grade PASS/FAIL **with concrete
   evidence** — no benefit of the doubt [5].
5. **Aggregate** — pass rate / time / tokens with and without, plus the **delta**:
   "what the skill costs (more time, more tokens) and what it buys (higher pass
   rate)" [5].
6. **Analyze patterns** — drop assertions that always pass (model handles them
   without the skill; they inflate the pass rate); investigate always-fail
   assertions; study pass-with-skill/fail-without (that's the skill's value —
   understand *why*); tighten instructions when results are inconsistent across runs
   (ambiguity) [5].
7. **Human review** — assertion grading catches only what you thought to assert;
   review actual outputs and record *actionable* feedback ("missing axis labels", not
   "looks bad") [5].
8. **Iterate** — feed the three signals (failed assertions, human feedback, execution
   transcripts) + the current SKILL.md back to the drafting model; **generalize** from
   feedback, **keep the skill lean** (if pass rates plateau despite adding rules, try
   removing instructions), explain the why, bundle repeated work. Stop when feedback
   is consistently empty or improvement plateaus [5].
9. **Two-instance loop** — draft/refine with one instance (the expert), test with a
   fresh instance that has only the skill loaded (the worker), bring specific
   observations back to the drafter [1][7].
10. **Observe navigation** — unexpected file-read order (structure not intuitive),
    missed reference links (make them more prominent), overreliance on one file
    (promote it into SKILL.md), ignored bundled files (unnecessary or poorly
    signaled) [1].
11. **Test with all models you plan to use** — what works for a strong reasoning model
    may need more detail on a faster/cheaper one [1].
12. **Read execution traces, not just final outputs** — wasted steps usually mean
    instructions that are too vague, don't apply to the task, or offer too many
    options without a default [3].

## Failure modes (consolidated)

| Failure | Cause | Fix |
|---|---|---|
| Never triggers | Description too narrow, missing key terms, not pushy enough | Fix the description first; trigger eval with near-miss positives [4][7] |
| Triggers when it shouldn't | Description too broad | Add specificity about what it does *not* do; clarify the boundary with adjacent skills [4] |
| Verbose body dilutes attention | Explains what the model already knows | "Would it get this wrong without this?" — cut no [1][3] |
| Incomplete information from references | Deeply nested reference chains → partial reads | One level deep; TOC on long files [1][7] |
| Model picks arbitrarily | Menu of equal options | One default + named exception [1][7] |
| Fails on a fresh environment | Assumes a package/tool is installed | State dependencies explicitly [1][7] |
| Script hangs the run | Interactive prompt in a non-interactive shell | Flags/env/stdin only [6] |
| Opaque failures waste turns | Script errors without guidance | What went wrong / expected / what to try [6] |
| Inconsistent behaviour across runs | Ambiguous instructions | Tighten; add examples; explain the why [5] |
| Unreliable "guarantees" | Must-hold-every-time requirement written as skill prose | Move to hook / harness enforcement [7] |
| Skill adds no value | No baseline; model already handles the task | Eval with/without; drop or narrow the skill [3][5] |
| Description overfits the eval set | Optimizing against all queries | 60/40 train/validation split; select best by validation pass rate [4] |
| Stale content | Time-sensitive statements | "Old patterns" section; keep current state current [1][7] |
| Third-party skill surprise | Unreviewed instructions/scripts/external URLs | Read the skill in full before use; treat it as a software dependency [7] |

## Ecosystem and tooling

- **Open standard** — the Agent Skills format was developed by Anthropic, released as
  an open standard, and adopted by a growing number of agent products; open to
  contributions (`github.com/agentskills/agentskills`) [9]. Confirmed adopters
  (search-verified 2026-11-22): Claude Code, pi, OpenAI Codex, Gemini CLI, and others
  in the client showcase [9].
- **Validation** — the spec ships a reference validator: `skills-ref validate
  ./my-skill` checks frontmatter validity and naming conventions [2].
- **`anthropics/skills` repo** — 19 example skills (pdf, docx, xlsx, pptx,
  mcp-builder, webapp-testing, …) + a `skill-creator` meta-skill that automates the
  eval loop and description optimization (splits the eval set, evaluates trigger rates
  in parallel, proposes description improvements, live HTML report) [4][5][8]. The
  repo's `template/SKILL.md` is the canonical minimal skeleton [8].
- **Naming** — consistent naming patterns aid selection as well as readability;
  gerund form (`processing-pdfs`) is the recommended default; avoid vague names
  (`helper`, `utils`, `tools`) and inconsistent patterns within a collection [1][7].
