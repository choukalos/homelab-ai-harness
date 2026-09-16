---
name: digest-algo
description: Implement an algorithm from a whitepaper digest — read the machine-checkable algorithm spec (inputs, steps, params, invariants, data_structures, complexity), write a working implementation, and verify it against the digest's invariants and Verification checks. Ships a reference checker (transformer_from_digest.py) as the pattern.
---

# Algo implement (whitepaper applier)

Implement the algorithm a `whitepaper` digest describes, then verify it
against the digest's invariants. The digest's `algorithm` section is the
machine-checkable spec; the `Verification` section is the acceptance test.

**Prerequisite:** a `whitepaper` digest (via `/skill:digest` or
`kb_digest_get(slug, "whitepaper")`).

## When to use
- "Implement the algorithm from <whitepaper>".
- "Turn this paper's method into working code".
- "Reproduce the paper's core result".

## Workflow

### 1. Load the spec
`kb_digest_get(slug, "whitepaper")` → read the `algorithm` section:
- **inputs** (with shapes/types), **steps** (the procedure), **params**
  (hyperparameters), **invariants** (what must hold), **data_structures**
  (shapes/keys), **complexity**.
Also read the `Verification` section (the acceptance checks) and `gotchas`.

### 2. Implement
Write a working implementation (Python + numpy is the default). Follow the
spec's steps exactly. Honor the `data_structures` (shapes/keys) and `params`
(defaults). Keep it minimal and readable — the goal is a correct core, not a
production library.

### 3. Verify (the load-bearing step)
Run the digest's invariants + Verification checks against the implementation:
- **Invariants**: assert each one holds (e.g. "attention weights sum to 1
  over keys", "output shape == (B, T, d)").
- **Verification checks**: the digest's `Verification` section lists concrete
  checks (e.g. "on a known input, output == X"). Run them.
- **Known-answer test**: if the paper gives a worked example, reproduce it.

If a check fails, the bug is either in the implementation OR in the digest.
Fix the implementation; if the digest looks wrong, flag it (the digest is a
model, not gospel — verify against the source if needed).

### 4. Report
- The implementation (file path).
- Verification results (each invariant/check: PASS/FAIL).
- Any deviations from the spec (and why).
- The lossy boundary: what the implementation does NOT cover (e.g. "core
  attention only; no multi-head, no positional encoding").

## The reference checker
`references/transformer_from_digest.py` is a worked example: it implements
scaled dot-product attention from the "Attention Is All You Need" digest and
runs 8 invariant/known-answer checks. Use it as the pattern:
1. Transcribe the digest's algorithm spec into code.
2. Transcribe the digest's invariants into assertions.
3. Run; all checks must pass.

Adapt it to the target paper: swap the spec (inputs/steps/params/invariants)
and the checks. The structure (implement → assert invariants → known-answer)
is the same for any algorithm.

## Grounding rules
- **Implement the spec, not your memory of the paper.** The digest is the
  source; if it's missing a detail, read the source page (the digest's
  `page_refs`) before guessing.
- **Invariants are the contract.** A correct implementation satisfies them.
  If you can't satisfy an invariant, the implementation (or digest) is wrong.
- **Report the boundary.** Say clearly what the implementation covers and
  what it doesn't.

## Notes
- numpy is available; torch is not (in this environment). Use numpy.
- Keep the implementation small and verifiable. A 100-line correct core beats
  a 1000-line incomplete one.