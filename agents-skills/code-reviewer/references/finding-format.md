# Finding format, severity definitions, and verdict rules

Read this when emitting code-review findings (S10 `code-reviewer`). Grounded in
R5 (`docs/research/R5-llm-code-review.md`) — Qodo's finding anatomy
(what/why/how + evidence), Sourcery's per-line labels, CodeRabbit's severity
definitions, and the R5 anti-false-positive evidence rules.

## Severity levels

| Level | Definition | Routing |
|-------|-----------|---------|
| **blocker** | Would cause a production failure — crash, data loss, broken contract, security hole — AND the failure path is reachable and the harm is concrete | Inline; forces `request-changes` |
| **major** | Significant problem that impacts functionality or performance; important but non-blocking | Inline; forces at least `approve-with-notes` |
| **minor** | Should be addressed but doesn't critically impact the system — maintainability, small perf, a real comprehension cost | Summary section only |
| **nit** | Low-impact suggestion for code quality | Summary section only, capped; default-suppressed |

**Blocker gate:** a blocker requires a demonstrated consequence — reachable
code + concrete input/state → observable harm + a statement of what was checked
to confirm reachability. A pattern match without a reachable path is not a
blocker (R5: severity labels set by pattern are the measured noise source).

## Finding format

Every finding uses this exact shape:

```
[blocker|major|minor|nit] file:line — <one-line title>
What: <the problem, quoting the offending code>
Why: <concrete failure scenario — input/state → bad outcome; reachability stated>
Fix: <minimal suggested change (code block where useful)>
Evidence: <what was read to verify this — files/lines; rule quoted + path if a repo rule is violated>
```

Rules:

- `file:line` is mandatory and must be verified against the actual file —
  read it; never cite a line you have not seen.
- `What` quotes the code; it does not paraphrase it.
- `Why` is a scenario, not an adjective ("could be confusing" is not a Why).
- `Fix` is minimal. A fix that adds abstraction for a one-line bug is a smell —
  say so (R5: adopted AI fixes measurably increase complexity/size).
- `Evidence` is what makes the finding checkable. A finding that asserts a
  preference is not a finding.
- If a finding violates a stated repo rule (AGENTS.md, a skill, a standards
  file), quote the rule and its path — rule-cited findings are checkable.
- If you cannot verify a suspected issue from the code available, it goes under
  `Could not verify` in the report — never as a finding.

## Verdict rules

| Verdict | Condition |
|---------|-----------|
| `request-changes` | ≥ 1 blocker |
| `approve-with-notes` | no blockers, ≥ 1 major |
| `approve` | no blockers or majors |

Minors and nits never change the verdict; they are reported in the summary so
they are visible but not load-bearing.

## Volume control

- Inline (blocker + major) capped at 20 — beyond that, the highest-severity
  findings stay inline and the rest collapse into the summary (R5: CodeRabbit's
  structural volume control — the cap is the volume control, not the prompt).
- Minor/nit findings are never dropped; they route to the summary section.
- The summary always lists skipped files (with reasons) and any
  `Could not verify` items — the operator must see the coverage boundaries.
