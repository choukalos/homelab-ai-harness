---
name: code-reviewer
description: Static code review of a diff or file set — correctness bugs, project-idiom violations, needless complexity, and adherence to the project's own architectural conventions. Severity-ranked findings (blocker / major / minor / nit), every one verified against the actual code, and a verdict (approve / approve-with-notes / request-changes). Use in the kanban QA stage (the static half of the pass, before qa-verify proves the change runs), before pushing a task branch, or when asked to review code for quality or simplicity. Dynamic verification (does it run right) is qa-verify; the security pass is security-code-review.
---

# Code Reviewer

Static scrutiny of a change — does it *look* right? Correctness, idioms,
simplicity, and the project's own conventions. The complement is dynamic
verification (does it *run* right — S3 `qa-verify`); the security pass is
S11 `security-code-review`. Grounded in R5
(`docs/research/R5-llm-code-review.md` — what makes LLM code review useful vs.
noisy; vendor review-prompt structures, severity calibration, anti-false-positive
design, diff-scoping heuristics).

**Role in the QA stage (kanban):** this skill is the *static* half of the pass.
Full QA = S3 `qa-verify` (functionality) + S11 `security-code-review` (hard
gate) + this skill (static quality). Static review is **advisory** — it produces
findings and a verdict; it does not block deploy on its own. Also usable
standalone on any diff (family pi sessions, pre-push review).

## Input

- A diff — task branch vs. base (`git diff <base>...<task-branch>`) — the kanban
  case, or
- A set of files (named or a path).

Plus context: the task spec/PRD or board card (intent), and the S2
`codebase-recon` note if one exists for this repo (consume it — conventions,
gotchas, build/test commands; if absent, do a quick convention scan first:
AGENTS.md/README, a couple of sibling modules, the test layout).

## Workflow

Run the review in a **fresh context** — a session/subagent that has not seen
the author's reasoning (R5: the author and a reviewer sharing context share
blind spots).

### Step 0 — Scope the diff (R5 scoping procedure)

1. **Filter first.** Skip: lockfiles, binaries/images, generated code
   (`*.generated.*`, `dist/`, `build/`, `__pycache__`), vendored deps,
   i18n/locale, snapshots, docs (unless the task *is* docs). Exclusions only —
   never an accidental allowlist.
2. **Detect programmatic diffs.** Formatter/renamer mass changes (prettier-style)
   are reviewed as a class or skipped with a note — not line-by-line.
3. **Size-check.** Baseline real change ≈ 3 files / ~40 lines. Far above that:
   raise effort rather than depth-per-line, and prioritize by risk — new logic,
   money/auth/security paths, cross-module changes get full review; the rest
   gets a summary pass. State the prioritization in the summary.

### Step 1 — Mechanical grounding first

Run the project's linters / typecheck / test suite (the recon note says how).
Their findings are attached as context; **do not re-emit linter output** — the
review's job is correctness/security/logic linters cannot see. A finding that
duplicates a mechanical result is dropped.

### Step 2 — Pass 1: change summary (whole diff)

What the change does, a per-file "what and why" table, where the risk is, and
the overall risk level. This pass is cheap and reads the whole diff.

### Step 3 — Pass 2: per-file findings (with context)

One analysis unit per in-scope changed file: the changed hunks + the enclosing
function/file + direct callers/callees + the repo rule/spec for that area.
Minimum viable context for a finding: the hunk, the enclosing function, direct
callers/callees, and the project convention for that area (R5 — a finding about
code you never read is a guess).

Review dimensions, in order:

1. **Correctness** — bugs, edge cases, error handling, resource leaks,
   null/undefined handling, off-by-one/boundary, races, error-swallowing,
   API-contract breaks.
2. **Language/framework idioms + security** — the project's stack, not generic
   lint (deep security findings go to S11; note the obvious ones).
3. **Conciseness & simplicity** — the simplest approach that works. YAGNI, no
   over-engineering, dead code, needless abstraction. A suggested fix that adds
   abstraction for a one-line bug is a smell — flag it (R5: AI-adopted fixes
   measurably bloat code).
4. **The project's own architectural conventions** — grounded in the actual
   repo (how similar things are done *here*), not a generic style guide.
   Violations of a stated rule quote the rule and its path.
5. **Testability + is it actually tested** — does the change come with the
   tests its acceptance criteria imply (stories carry their tests)?
6. **Naming/readability** — only as Minor/Nit, and only when it causes a real
   comprehension cost.

### Step 4 — Severity-rank, then verdict

Severity: **blocker / major / minor / nit** (definitions + the finding format
in `references/finding-format.md` — read it when emitting findings).

Calibration rules (R5 — the make-or-break):

- **Scope fence.** Report only issues that block merging or cause observable
  harm: bugs, security, data loss, broken contracts. Skip style and formatting —
  linters own those. Mention a repeated pattern once, at summary level.
- **No nitpicks.** A reviewer asked to find problems always finds something;
  flooding with nits makes the worker ignore everything (R5: 79% nits was the
  measured baseline failure).
- **Critical/blocker requires a proven consequence** — reachable code +
  concrete input/state → harm, not a pattern match. "Code that nothing calls,
  labelled critical" is the canonical false positive.
- **Every finding cites `file:line` and is verified against the actual code** —
  read the file; never guess at lines that don't exist.
- **Could-not-verify escape hatch.** If you cannot verify a suspected issue
  from the code available, emit it under `Could not verify` with what you'd
  need — do not emit it as a finding.
- **Cap the inline view.** Blocker + Major inline (≤ 20); Minor/Nit go to a
  collapsed summary section — never dropped entirely (the operator must see
  what was suppressed).
- **Minimal-fix bias.** Suggested fixes are minimal; prefer the one-line fix
  over the refactor.

Verdict:

| Verdict | When |
|---------|------|
| `request-changes` | ≥ 1 blocker |
| `approve-with-notes` | no blockers, ≥ 1 major |
| `approve` | no blockers or majors (minors/nits noted in summary) |

### Step 5 — Output

```
## Code review — <branch/diff id>
Verdict: approve | approve-with-notes | request-changes
Summary: <what changed, per-file what/why, where the risk is, risk level>
Findings:
  [blocker|major|minor|nit] file:line — <title>
  What / Why (failure scenario) / Fix (minimal) / Evidence (what was read)
Could not verify: <suspected issues + what's needed, or "none">
Skipped: <files skipped + reasons; "none">
```

## Incremental re-reviews

When the worker pushes fixes: re-review only the newly added/changed hunks,
maintain context with prior findings, and **do not re-emit unchanged
findings** (R5: "keeps finding new bugs every time it runs instead of
reporting everything at once" is the naive-agent failure). Close fixed findings
with the evidence; re-open with a new scenario if the fix doesn't hold.

## Anti-noise self-check (before emitting)

- Signal ratio ≥ 60% (blocker+major+minor-with-harm over total) — below that,
  you are a noise generator (R5's Jet-Xu rule).
- Every finding: verified `file:line` + quoted code + concrete harm?
- Any finding a linter already emits? Drop it.
- Any finding that's really a style preference? Drop it or Nit.
- Any blocker without a reachable failure path? Demote or drop.
