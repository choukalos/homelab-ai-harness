---
name: architecture
description: Write the system design doc before coding for new systems or big changes — context and goals, ASCII component diagram, data flow, interfaces/contracts, data model, tech choices with rationale, constraints and trade-offs, ADRs, rollout plan. Use at the "define architecture" step of the Coding Team workflow (step 1, before story breakdown), when a task introduces a new service/pipeline or changes the shape of the system. Small features that fit the existing shape skip this and go straight to story-breakdown.
---

# Architecture

System design doc *before* coding — step 1 of the Coding Team workflow, for
new systems / big changes. The output is the input to DEV-2
`story-breakdown` (every component maps to an owned story). Grounded in R2
(`docs/research/R2-swe-agent-recon.md` — how to ground a design in an
unfamiliar repo) and R8 (`docs/research/R8-pm-artifacts.md` — spec-driven
development: Kiro's `design.md`, spec-kit's plan step, Requirements-First vs
Design-First).

## When to use

- **Use it:** a new service/pipeline, a new data store, a change that touches
  the system shape (new trust boundary, new public surface, new deployment
  unit), or any task the board card marks as architectural.
- **Skip it:** a feature that fits the existing shape — go straight to
  `story-breakdown` (the recon note + existing docs are enough).

## Inputs

1. **The spec/PRD** (or board card) — what is being built and why.
2. **Project constraints** — the kanban project `constraints` (deploy gates,
   trust boundary, what is public vs. LAN) + existing docs.
3. **The repo itself** — S2 `codebase-recon` note first (consume it: existing
   services, conventions, build/test/deploy paths, gotchas). If no recon note
   exists, do the recon pass before designing — a design that ignores how the
   system actually works today is fiction.

## The doc (sections, in order)

Template in `references/architecture-doc-template.md` — read it when writing
the doc.

1. **Context & goals** — what exists today, what the change is, what "done"
   means. 1–2 pages max; no org/stakeholder apparatus (one-operator shop).
2. **Component diagram** — ASCII. Existing components + new ones, with the
   trust boundary drawn (public / LAN / internal).
3. **Data flow** — where data enters, how it moves, where it lands (stores,
   caches, logs). Mark untrusted→trusted crossings explicitly.
4. **Interfaces/contracts** — every new or changed interface: endpoint/CLI/
   message shape, auth, error contract. Existing interfaces it touches.
5. **Data model** — new/changed tables/collections/documents, with the
   migration story (how existing data is handled).
6. **Tech choices with rationale** — every non-obvious choice as *why X over Y*
   (the alternatives considered + why rejected). Prefer the boring option and
   the homelab's existing patterns (containers on thor, Caddy at the edge, the
   existing deploy flows) — a new technology needs a stated reason.
7. **Constraints & trade-offs** — what the design gives up (latency,
   complexity, ops burden) and which project constraints it must respect
   (deploy gates, LAN trust model, resource limits).
8. **ADRs** — for each consequential decision: decision + context +
   alternatives considered + consequences. One ADR per decision; no ADR for
   the obvious.
9. **Rollout plan** — how it ships (migration order, feature flags, rollback
   path, post-deploy watch — ties into S3 `qa-verify`'s watch step).

## Rules

- **Match the project's existing conventions** — the recon note is the
  authority on how things are done here. A design that invents a new pattern
  for no stated reason fails review.
- **The simplest architecture that meets the constraints.** No
  over-engineering: no component without a stated job, no abstraction without
  a second consumer, no queue/registry/service where a function/table/file
  does the job. YAGNI applies to architecture harder than to code.
- **Every component maps to an owned story** — if a component can't be named
  as a story (or a small set of stories), it's either too big (split it) or
  imaginary (delete it). This is the handoff check DEV-2 runs.
- **Design-First is the right mode here** (R8): use it when an existing
  architecture or strict NFRs drive the work; keep behavior known and
  architecture flexible otherwise (Requirements-First).
- **Intent and evidence ahead of implementation** (R8/spec-driven): the doc
  states the *why* and the *what* — implementation detail (the *how* inside a
  component) stays negotiable until the stories are built.
- **Draw the trust boundary.** The homelab's LAN-trust model means "where is
  this reachable from?" is a first-class design question, not an afterthought
  (feeds S11 `security-code-review`'s gate).

## Where the doc lives

Where the project's architecture docs live (the recon note says; e.g.
`docs/architecture/<system>.md` or the project's ARCHITECTURE.md). If the
project has no docs home yet, the board card carries the doc and S5
`docs-housekeeping` files it durably when the work lands.

## Handoff

- **→ DEV-2 `story-breakdown`:** the doc's component list is the story seed —
  every component becomes an owned story (or a split).
- **→ S11 `security-code-review`:** the trust boundary + data flow are the
  context the security gate reviews against.
- **→ S5 `docs-housekeeping`:** the doc is durable state — refresh it when
  the implementation diverges.
