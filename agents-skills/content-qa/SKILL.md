---
name: content-qa
description: The content QA pass — the content analog of S3/S11 for code. Verifies every factual claim against sources (mcp_search), checks brand voice against the strategy doc's do/don't examples, checks strategy alignment and ask conformance (pillar, funnel stage, intent, CTA, required structure), and grades quality (structure, length, readability, no fluff, intent match, subtopic completeness, information gain, SEO basics). Use at the 'review drafts & QA' step of the Content Marketer workflow (step 5), before any draft is finalized or published, or when asked to fact-check or review a content draft. Hard gate — a draft cannot be finalized until the QA pass is clean or the strategist signs off on the exceptions. Grounded in R7 + R9 (docs/research/) and R3 (docs/research/R3-agent-self-verification.md).
---

# Content QA

The content QA checklist — step 5 of the Content Marketer workflow, the
content analog of S3 `qa-verify` / S11 `security-code-review` for code. A
draft cannot be finalized until the QA pass is clean (or the strategist signs
off on the exceptions). Grounded in R7
(`docs/research/R7-content-marketing-organic-traffic.md` — the
intent/coverage/topical-fit/information-gain/SEO checks), R9
(`docs/research/R9-marketing-strategy-operating-cadence.md` — the voice
check against do/don't examples, brief conformance, the
review-before-launch gate), and R3
(`docs/research/R3-agent-self-verification.md` — the factualness discipline:
evidence-based verification, no confident-but-wrong claims).

## When to use

- **Use it:** a draft exists and is headed for finalize/publish (the CM
  workflow step 5); a strategist or the operator asks to fact-check or review
  a content draft; a draft comes back from the publish path with a suspected
  error.
- **Skip it:** the piece is a pure repurpose of an already-QA'd piece with no
  new factual claims and no voice change (re-run only the voice + conformance
  checks, and say so); or the ask is to *write* the content (that's
  `content-writer` — this skill reviews, it doesn't draft).

## Inputs

1. **The draft** — the content to review (file or card body).
2. **The ask** — the board card it was written against (the conformance
   baseline: goal, funnel stage, intent/three Cs, format, constraints, CTA).
   No ask? The draft is unbriefed — flag it as a finding (the org rule: never
   a vague "write something").
3. **The strategy doc** — `docs/roles/marketing-strategist/strategy/<site>.md`
   (the voice section's do/don't examples, the topical lane, the
   pillar/cluster + internal-link plan). No strategy doc? The voice and
   strategy-alignment checks can't run — that's a BLOCKER finding (the QA
   baseline is missing), not a pass.
4. **The sources the draft cites** — the writer's source links (the brief
   asks for them — R9 S8: "links to any other sources they've used to assist
   with any light fact-checking").
5. **Web research tools** — `mcp_search` (search_web / crawl_page) for
   verification. If unavailable, verify by direct fetch (curl) of the cited
   sources and say so; if a claim can't be verified at all, it stays
   unverified — it does not get a pass by default.

## Method

Run the checklist in order — `references/qa-checklist.md` (read it when
running the pass). The order matters: factualness first (a factually wrong
draft is unfixable by polish), then voice, then strategy/ask conformance,
then quality/SEO.

1. **Factualness** — every factual claim (name, number, date, quote,
   technical statement) verified against a source: the draft's cited sources
   first, then `mcp_search` (R3 discipline: the claim is verified when you've
   read the source and it supports the claim — not when you believe it).
   Unverified claim → correction required before finalize (fix the claim, add
   the citation, or cut it). No unverified factual claims ship.
2. **Brand voice** — against the strategy doc's voice section: each of the
   3–5 attributes checked via its do/don't **examples** (the "well-defined"
   rule — the check runs against the examples, not the adjectives); the
   "who we are not" list (any avoided words/phrases present?); the tone for
   the context (does it match the context's tone rule?); the one-line test —
   "Would a real person say this?" (R9 Q1).
3. **Strategy alignment + ask conformance** — pillar and funnel stage match
   the ask; the CTA/conversion action matches the ask (BOFU pieces point at
   the conversion action — the lead form for Bluebovine); the draft's
   type/format/angle matches the dominant SERP for the target query (the
   three Cs — intent match, R7); the required structure (subheadings, word
   count, keywords, internal links, meta) matches the ask's constraint fields
   (R9 Q3: the brief is the contract).
4. **Subtopic completeness** — does the draft cover the expected subtopics
   for the target query (the content-gap list from the strategy doc's cluster
   section / the SERP check)? Missing subtopics = the draft under-satisfies
   intent (R7 Q3).
5. **Topical fit** — would a first-time visitor immediately understand this
   page belongs on this site (the site-radius test, R7 Q2)? Off-topic =
   reject or reroute (to the exclusion list), don't publish.
6. **Information gain** — at least one element of original data / firsthand
   experience / real effort (not a synthesis of what's already out there —
   the anti-copycat and anti-thin-AI-content check in one, R7 Q4). For the
   homelab this is the structural advantage: real measurements, real configs,
   real incidents.
7. **Quality** — structure (logical order, descriptive headings), length
   (matches the ask's range; no fluff — every section earns its place),
   readability (the 2026 written-content bar, R9 S10: leading with answers,
   one point at a time, unfamiliar terms defined, entities named clearly).
8. **SEO basics** — title/meta present and on-target; internal links to the
   pillar + related clusters per the strategy doc's link plan (the link plan
   is part of the strategy, so QA checks against it — R7); no orphaned page.
9. **Honesty check on "best" content** — if it's a comparison/list: no
   self-ranking #1 on the own domain without a disclosed basis (the 67.6%
   self-promo pattern is being penalized — R7 Q4).
10. **Apply the gate.** All checks clean → the draft is **QA-clean** (the
    gate evidence: the checklist result with per-check verdicts). Any finding
    → the draft is **not finalizable**: required fixes are listed (the
    factualness and voice findings are hard — corrections required before
    finalize); the strategist may sign off on exceptions (recorded on the
    card: which check, what exception, who signed off).

## Rules

- **The gate is hard** — a draft cannot be finalized or published until the
  QA pass is clean or the strategist signs off on the exceptions. Same
  semantics as S11 for code: the skill teaches the procedure and produces the
  evidence; the enforcement point is the publish step (the CM workflow) —
  publish without the gate evidence is a process violation.
- **No pass without evidence** (R3) — a check is "clean" only with the
  evidence (the verified sources, the matched examples, the SERP check).
  "Looks fine" is not a verdict.
- **Factualness is non-negotiable** — unverified factual claims are
  corrections-required, full stop. The exception path (strategist sign-off)
  applies to judgement calls (voice, angle, quality), never to facts.
- **Check against the doc, not against taste** — voice runs against the
  strategy doc's examples; conformance runs against the ask's fields; the
  link plan runs against the strategy doc. If the baseline is missing, that's
  a finding (BLOCKER: the QA baseline is missing), not a reason to skip the
  check.
- **The QA result rides on the card** — the checklist verdicts (per check:
  clean / finding + severity + the required fix) are written to the board
  card; the publish step (CM workflow step 6) verifies the live URL after
  publishing (S3 discipline: check the published URL, don't assume).

## Output

1. **The QA result** — per-check verdicts (clean / finding + severity +
   required fix) + the gate decision (QA-clean → finalizable; or the fix
   list / the signed-off exceptions). Written to the board card; no durable
   file by default (the card is the artifact; the strategy doc and the
   inventory carry the durable record).
2. **The corrections** (when findings are required fixes) — the corrected
   draft, or the fix list for the writer to apply, with the verification
   evidence for each fixed claim.

## Handoff

- **→ the publish step (CM workflow step 6):** a QA-clean draft goes to
  publish via the project's path (blog `deploy.sh`, `publish-file`); the
  publish step verifies the live URL.
- **→ Content Marketer (the writer):** the fix list for non-clean drafts.
- **→ Strategist:** exception sign-offs (judgement calls only — never facts);
  findings that point at a strategy-doc gap (a voice attribute without
  examples, a missing link plan) get routed back as strategy-doc updates.
- **→ CM-2 `content-inventory`:** at publish time, the inventory row gets
  added (the QA-clean verdict is part of the published record).
