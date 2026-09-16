# DIGEST — whitepaper
# source: <path or title>
# type: whitepaper | downstream task: implement the algorithm / answer
#                "how does it work" / reproduce the result
# sections read: <which sections of the paper were read>

## problem
<!-- What problem does the paper solve, and why do prior approaches fail? -->

## prior_work
<!-- Prior approaches and their limitations (1-3 lines each). -->
- <approach> (<authors/years>): <limitation>

## algorithm
<!-- THE section an implementer consumes. Capture the rules in
     machine-checkable form (formulas, pseudocode, shapes), not prose. -->
name: <algorithm name>
core_primitive: <the key operation>

inputs:
  <symbol> : <meaning, shape/dim>

steps:
  1. <step, with the exact formula>
  2. <step>

params:
  <param> = <value in the paper>

invariants:
  - <a property that must hold (e.g. "attention weights sum to 1")>

data_structures:
  - <tensor/matrix: name, shape>   <!-- exact shapes are load-bearing -->

complexity:
  - <e.g. O(n^2 * d) — note if the paper's motivation is not complexity>

## claims
<!-- The paper's claims, with the numbers. -->
- <claim> (<metric>: <value>)

## implementation_notes
<!-- Practical notes for implementing it correctly. -->
- <e.g. "use optimized matmul for dot-product attention">

## gotchas
<!-- Easy-to-get-wrong details (scaling, masking, shape conventions). -->
- <gotcha>

## Verification
<!-- For each load-bearing claim, the independent check. e.g.:
     - implement the core primitive from this digest alone;
     - assert shapes/invariants on a small input;
     - compare a known output (e.g. a hand-computed attention matrix). -->
- claim: <...> → check: <...>

## page_refs
<!-- Where each section was grounded. -->
- <section>: p.X-Y