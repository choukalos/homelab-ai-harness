# Content QA checklist

The full checklist of `content-qa` (CM-1). Run in order (factualness → voice
→ alignment/conformance → completeness → topical fit → information gain →
quality → SEO → honesty). Per check: the procedure, the pass criterion, and
the severity of a finding.

Severity: **BLOCKER** = the draft cannot be finalized (correction required,
no exception path) · **MAJOR** = correction required before finalize (the
strategist may sign off the exception, recorded on the card) · **MINOR** =
fix recommended; may ship with the strategist's sign-off.

## 1. Factualness — BLOCKER

**Procedure.** List every factual claim (names, numbers, dates, quotes,
technical statements, "first/only/best" superlatives). For each: verify
against a source — the draft's cited sources first (read the relevant
section), then `mcp_search` (search_web / crawl_page) or a direct fetch
(curl) when MCP web tools are unavailable (note the method). A claim is
verified when the source was read and it supports the claim (R3: evidence,
not belief).

**Pass.** Every factual claim has a verified source, and the source is cited
in the draft (or the claim is cut / reworded to what the source supports).

**Finding.** Unverified claim → BLOCKER: fix the claim, add the citation, or
cut it. "I'm confident it's right" is not a verdict.

## 2. Brand voice — MAJOR

**Baseline.** The strategy doc's voice section
(`docs/roles/marketing-strategist/strategy/<site>.md`): the 3–5 attributes
with do/don't examples per content type, the "who we are not" list, the tone
rules per context.

**Procedure.** For each attribute: check the draft against its do examples
(does it read like them?) and its don't examples (does it trip any?). Check
the "who we are not" list for avoided words/phrases. Check the tone against
the context's rule (tutorial / promo / incident). Run the one-line test:
"Would a real person say this?" (R9 Q1).

**Pass.** No attribute's don't-example patterns present; the draft reads like
the do examples for its content type; the tone matches the context.

**Finding.** Voice drift → MAJOR: name the attribute, quote the offending
passage, give the required fix (reword to match the do example). Missing
voice section in the strategy doc → BLOCKER (the QA baseline is missing —
route to the strategist; do not run the check against taste).

## 3. Strategy alignment + ask conformance — MAJOR

**Baseline.** The ask (board card) + the strategy doc (pillar/cluster,
funnel mapping, internal-link plan).

**Procedure.** Check: pillar + funnel stage match the ask; the CTA /
conversion action matches the ask (BOFU → the conversion action, e.g. the
lead form for Bluebovine); the draft's type/format/angle matches the dominant
SERP for the target query (the three Cs — re-run the SERP check if the ask's
three Cs are stale or missing); the required structure matches the ask's
constraint fields (subheadings, word count, target keywords, avoid-list,
internal links, meta).

**Pass.** Every field the ask carries is satisfied; the intent match holds.

**Finding.** Mismatch → MAJOR: name the field, the ask's value, the draft's
value, the required fix. No ask at all → BLOCKER (unbriefed draft — route
back to the strategist; the org rule: never a vague "write something").

## 4. Subtopic completeness — MAJOR

**Procedure.** Pull the expected subtopics for the target query (the
strategy doc's cluster section / the content-gap list; if absent, the
top-ranking pages for the query via `mcp_search`). Check the draft covers
each (a section, a paragraph, or an explicit deferral).

**Pass.** Every expected subtopic covered or explicitly deferred with a
reason.

**Finding.** Missing subtopic → MAJOR: list the missing subtopics; the draft
under-satisfies intent (R7 Q3: subtopic coverage = intent satisfaction).

## 5. Topical fit — BLOCKER

**Procedure.** The site-radius test (R7 Q2): would a first-time visitor to
this page immediately understand it belongs on this site? Check against the
strategy doc's topical lane.

**Pass.** The page is inside the topical lane.

**Finding.** Off-topic → BLOCKER: reject or reroute (to the strategy doc's
exclusion list / a different site). Publishing off-lane content dilutes the
authority signal — it's not a judgement call.

## 6. Information gain — MAJOR

**Procedure.** Check the draft for at least one element of original data /
firsthand experience / real effort (R7 Q4): a measurement, a config, an
incident, an experiment, a primary observation — something that is not a
synthesis of what's already out there.

**Pass.** ≥1 genuine information-gain element, and it's load-bearing (the
draft isn't just "the same as the top 10 + a new intro").

**Finding.** Pure synthesis / thin AI content → MAJOR: name what's missing
and what the site can contribute (the homelab's structural advantage: real
measurements, real configs, real incidents).

## 7. Quality — MAJOR / MINOR

**Procedure.** Structure: logical order, descriptive headings, each section
one point. Length: within the ask's range; no fluff (every section earns its
place — cut the section that could be cut without losing information).
Readability (the 2026 written-content bar, R9 S10): leading with answers
(each section answers what its heading asks, then supports); unfamiliar terms
defined in one short sentence; entities named clearly (no ambiguous
"it/they/this"); claims supported.

**Pass.** Structure holds; length in range; no fluff; readability bar met.

**Finding.** Fluff / structure break → MAJOR (name the section, the cut);
readability nits → MINOR (list the fixes).

## 8. SEO basics — MAJOR / MINOR

**Procedure.** Title tag + meta description present and on-target (the
target query / the intent); internal links to the pillar + related clusters
per the strategy doc's link plan (the link plan is part of the strategy —
check against it, R7); no orphaned page (the draft is linked from at least
one existing page, or the plan names the link).

**Pass.** Title/meta on-target; the link plan satisfied (or the plan's
link is scheduled and named).

**Finding.** Missing title/meta or broken link plan → MAJOR; suboptimal
title/meta → MINOR.

## 9. Honesty check on "best" content — MAJOR

**Procedure.** If the draft is a comparison / "best X" list: check for
self-ranking #1 on the own domain without a disclosed basis (R7 Q4: the 67.6%
self-promo pattern is being penalized).

**Pass.** No undisclosed self-ranking; any self-placement has a disclosed,
honest basis.

**Finding.** Undisclosed self-ranking → MAJOR: disclose the basis or rework
the list.

## Gate

All checks clean → **QA-clean** (finalizable). Any BLOCKER or MAJOR → the
draft is **not finalizable**: the fix list goes to the writer (factualness
and topical-fit findings have no exception path); the strategist may sign off
MAJOR/MINOR exceptions (recorded on the card: check, exception, signer,
date). The verdicts + the gate decision are written to the board card — the
publish step (CM workflow step 6) requires the gate evidence, verifies the
live URL after publishing, and adds the CM-2 inventory row.
