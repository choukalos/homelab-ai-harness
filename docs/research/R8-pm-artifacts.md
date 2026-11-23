# R8 — Product-management artifacts (PRD, story breakdown, prioritization) for a one-operator + LLM-agent homelab team

- **Question (R8):** What PM artifacts and frameworks should the skill set encode — PRD format, story breakdown / acceptance criteria / definition of ready, dependency mapping (kanban + icebox + LLM-identified gating), competitive-analysis frameworks, opportunity sizing, ideation + prioritization (RICE/ICE/Kano + lighter options) — for a small homelab team (one operator + LLM agents) where LLM grooming of board ideas into specs IS the PRD process?
- **Date:** 2026-11-23
- **Status:** done
- **Feeds:** PM-1 `pm-market-analysis`, PM-2 `pm-product-requirements`, PM-3 `pm-exec-pitch`, PM-4 `pm-ideation`, PM-5 `pm-prioritization`, DEV-2 `story-breakdown`
- **Method note:** The MCP web tools named in the TODO (`mcp_search_search_web`, `mcp_crawl_crawl_page`) were not available in this worker session (same situation as R2/R6). All sources were verified by direct HTTP fetch (curl / local crawl script) and read in the relevant sections. Web search via curl (Bing, DuckDuckGo HTML) was bot-blocked (no usable organic results), so source discovery relied on known canonical URLs plus a few search-result files from the prior attempt; every source below was actually fetched, and failures are listed under `## Sources` → "Failed fetches".
- **Honesty convention:** `[verified: fetched]` = claim read directly in a fetched page (listed in Sources). `[inferred]` = synthesis/judgment by the researcher, flagged as such.
- **Audience note:** everything is filtered for a solo operator + LLM agents on a kanban board; "worth it for a solo operator" judgments are `[inferred]` unless the source says so.

## Sources

All fetched 2026-11-23 (except where noted). "Date" = publication/edition date of the source (fetch date when undated).

| # | URL | Date | What it provided | Fetched-verified |
|---|-----|------|------------------|------------------|
| S1 | https://www.atlassian.com/agile/product-management/requirements | undated (current page) | PRD structure: consistent template; sections = project specifics (participants, status, target release) + team goals/business objectives + "just enough" context for requirements and user impact | yes |
| S2 | https://productschool.com/blog/product-strategy/product-template-requirements-document-prd | 2024-05-20 | PRD definition (purpose, features, functionality, behavior; written to communicate what/who/why to business + technical teams); full template from idea → action incl. USPs and GTM strategy | yes |
| S3 | https://en.wikipedia.org/wiki/Product_requirements_document | current | PRD definition; PRD (user/client POV) → functional specification (technical POV) pipeline; "form of the PRD will vary from project to project" | yes |
| S4 | https://workingbackwards.com/concepts/working-backwards-pr-faq-process/ | undated (book *Working Backwards*, Bryar & Carr, 2021) | Amazon PR/FAQ process: created 2005 after SWOT/market-size/pro-forma P&L tools failed to force customer thinking; PR structure (Heading, Subheading, Summary Paragraph with launch date, Problem Paragraph from customer POV…); FAQ = External (customer/press questions) + Internal (harder team questions) | yes |
| S5 | https://docs.superhuman.com/@colin-bryar/working-backwards-how-write-an-amazon-pr-faq | undated | Colin Bryar's (co-author of *Working Backwards*) PR/FAQ templates + how to run PR/FAQ review meetings | yes |
| S6 | https://github.github.com/spec-kit/ | 2025–2026 (current docs) | GitHub Spec Kit: Spec-Driven Development (SDD) = structured process keeping "intent and evidence ahead of implementation"; idea assessment = intake → research → define → shape → decide (go / clarify / stop) | yes |
| S7 | https://github.github.com/spec-kit/quickstart.html | 2025–2026 (current docs) | SDD step sequence: constitution once per project, then `/speckit-specify` → `/speckit-plan` → `/speckit-tasks` → `/speckit-implement` → `/speckit-converge`; full path adds `/speckit-clarify`, `/speckit-checklist`, `/speckit-analyze` | yes |
| S8 | https://developer.microsoft.com/blog/spec-driven-development-spec-kit/ | 2025-09-24 | Why specs for AI agents: "code is inherently a binding artifact"; code is not the right medium for requirements negotiation; spec establishes context before implementation | yes |
| S9 | https://kiro.dev/docs/specs/ | 2025–2026 (current docs) | Kiro specs: every spec = `requirements.md` + `design.md` + `tasks.md`; "break down requirements into user stories with acceptance criteria"; track implementation across discrete tasks | yes |
| S10 | https://kiro.dev/docs/specs/best-practices.md | 2025–2026 (current docs) | Requirements-First vs Design-First workflow choice criteria (behavior-known/flexible-architecture vs existing-design/strict-NFRs) | yes |
| S11 | https://www.atlassian.com/agile/project-management/user-stories | undated (current page) | 3 C's of user stories (Card, Conversation, Confirmation = acceptance criteria); standard format "As a [user], I want [goal] so that [reason]" | yes |
| S12 | https://www.atlassian.com/work-management/project-management/acceptance-criteria | undated (current page) | AC = "conditions that a product, user story, or increment of work must satisfy to be complete"; good AC: clear/concise, testable (maps to executable tests), outcome-focused ("describe the result, not the recipe") | yes |
| S13 | https://martinfowler.com/bliki/GivenWhenThen.html | 2013-08-21 | Given-When-Then = style for representing tests / specifying a system's behavior (Specification by Example); canonical reference for GWT AC format | yes |
| S14 | https://www.atlassian.com/agile/project-management/definition-of-ready | undated (current page) | DoR = "set of criteria that ensures backlog items are actionable, clear, and feasible before work begins"; key components = independence, negotiability, value, estimability, small size, testability (INVEST) | yes |
| S15 | https://www.atlassian.com/agile/project-management/fibonacci-story-points | undated (current page) | Story points = relative effort/complexity; "traditional time-based estimates often fail because they create false precision"; Fibonacci sequence for relative sizing | yes |
| S16 | https://www.atlassian.com/agile/project-management/project-management-dependencies | undated (current page) | Dependency types: finish-to-start, start-to-start, finish-to-finish, start-to-finish; dependency mapping = identify, map, communicate dependencies to keep projects on track | yes |
| S17 | https://thoughtbot.com/blog/the-icebox-is-where-stories-go-to-die | undated (older post) | Icebox (term popularized by Pivotal Tracker) = backlog of things not to work on soon but kept for the future; two legitimate kinds of icebox stories (need more discussion/planning; out of scope/low priority); failure mode = "stories go to die", cognitive overhead; advice: needs-discussion stories belong in the priority-ordered backlog with a tag, not the icebox; use an "Inbox"/"Ideas" staging area with regular grooming | yes |
| S18 | https://www.linkedin.com/pulse/building-icebox-jira-will-helliwell | undated (older post) | Practical icebox in Jira: labels + JQL filter (e.g. exclude `icebox` label from the working board); separate board view for icebox issues | yes |
| S19 | https://en.wikipedia.org/wiki/Porter%27s_five_forces_analysis | current | Porter's Five Forces: method of analysing the competitive environment; rooted in industrial-organization economics; five forces determine competitive intensity and industry profitability | yes |
| S20 | https://www.atlassian.com/agile/product-management/product-positioning | undated (current page) | Product positioning = how customers perceive your product + what differentiates it from competitors; "strong positioning helps you stand out by showing customers why they should choose you"; turns features into measurable outcomes | yes |
| S21 | https://productside.com/free-competitive-matrix-feature-comparison-chart/ | 2015-03-23 | Feature comparison matrix: template + instructions for prioritizing features by cost and value against competitors (lightweight competitive analysis) | yes |
| S22 | https://foundationinc.co/lab/tam-sam-som | last updated 2026-07-29 | TAM/SAM/SOM definitions (TAM = total revenue opportunity at 100% market share; SAM = portion realistically servable with current offerings/channels/target market; SOM = share realistically achievable within SAM in a specific timeframe); top-down vs bottom-up calculation methods; "it's smart to use both approaches" | yes |
| S23 | https://www.intercom.com/blog/rice-scoring/ | 2018-01-05 (Intercom, Sean McBride) | RICE origin post: formula (Reach × Impact × Confidence) / Effort = "total impact per time worked"; scales: Impact 3/2/1/0.5/0.25, Confidence 100/80/50%, Effort in whole person-months (min 0.5); misuses: pet ideas/clever ideas bias, "RICE scores shouldn't be used as a hard and fast rule" — dependencies may force a lower-scored project first | yes |
| S24 | https://www.productplan.com/glossary/ice-scoring-model | undated (current page) | ICE Scoring Model: Impact × Confidence × Ease (Ease = inverse of effort), each rated on a 1–10 scale, product = ICE score; "relatively quick way" to prioritize when data is thin | yes |
| S25 | https://www.atlassian.com/agile/product-management/prioritization-framework | undated (current page) | Six common frameworks: RICE, Kano, MoSCoW, value vs. effort, opportunity scoring, cost of delay; per-framework pros/cons (e.g. RICE "time-consuming and cumbersome… subjective, inconsistent, and potentially misleading"; Kano "highly quantitative and potentially time-consuming"); choice depends on team, project, available data | yes |
| S26 | https://thedecisionlab.com/reference-guide/design/kano-model | refs retrieved 2023-12-20 (page current) | Kano model: prioritize by customers' emotional responses, not benefit/cost; categories incl. must-be (expected), performance, attractive, indifferent; history: Noriaki Kano, 1980s, Tokyo University of Science; cites Kano, Seraku, Takahashi, Tsuji (1984) "Attractive Quality and Must-Be Quality", J. Japanese Society for Quality Control 14(2) | yes |
| S27 | https://en.wikipedia.org/wiki/Kano_model | current | Kano model developed in 1980s by Noriaki Kano; full 1984 citation (in Japanese, *Journal of the Japanese Society for Quality Control* 14(2): 39–48); category table (must-be / attractive / one-dimensional / indifferent + reverse/harmful) and synonym mappings | yes |
| S28 | https://www.nngroup.com/articles/dot-voting/ | 2019-07-07, last reviewed 2026-08-07 | Dot voting: each participant gets tokens ("dots") assigned to alternatives; board becomes a heat map; simple democratic prioritization that "works well in any situation"; process, when-to-use, facilitation tips | yes |
| S29 | https://akfpartners.com/growth-blog/1-10-100-rule-in-quality-software-development/ | 2022-03-24 (AKF Partners) | 1-10-100 rule **as cost-of-quality**: cost to fix a defect grows ~10× per lifecycle phase (cheap in code, ~10× in test, ~100× post-deploy). NOTE: this is a different "1-10-100" from Marty Cagan's prioritization rule (see Open questions) | yes |

**Failed fetches / alternates (all resolved or noted):**
- `https://www.amazon.com/Working-Backwards-Insights-Stories-Secrets/dp/0593550495` → cookie wall, no content. Amazon PR/FAQ verified instead via S4/S5 (Bryar's own template doc + workingbackwards.com).
- `https://hbr.org/2014/07/why-amazons-culture-of-invention-is-so-different` → 404. Not needed (S4/S5 cover PR/FAQ).
- `https://www.mckinsey.com/…` (Porter's five forces) → blocked by Akamai anti-bot. Five forces verified via S19 (Wikipedia); Porter's original HBR 1979 article is paywalled and was not fetched.
- `https://cucumber.io/docs/cucumber/given-when-then/` → 404 (docs restructured). GWT verified via S13 (Fowler) + S12 (Atlassian).
- `https://www.investopedia.com/terms/t/tam.asp` → 404 (page moved). TAM/SAM/SOM verified via S22.
- `https://www.aconity.com/user-story-invest/` and `https://www.aconity.com/articles/user-story-invest/` → 404; `https://c2.com/cgi/wiki/InvestInUserStories.html` → 404. Bill Wake's original INVEST post (2003) unreachable; INVEST components verified via S14 (Atlassian DoR page).
- `https://scispace.com/papers/attractive-quality-and-must-be-quality-2uvbgvliyt` → empty response. Kano 1984 original (Japanese) not fetched; verified via secondary citations in S26/S27.
- `https://www.svpg.com/the-1-10-100-rule/` → HTTP 200 but soft-redirects to the SVPG homepage (article no longer at that path); no Wayback snapshot exists (checked availability API + CDX, 2026-11-23). Cagan's prioritization 1-10-100 rule is therefore **not verified from a primary source** — see Open questions.
- `https://www.amazon.jobs/en/faqs` → fetched but irrelevant (careers FAQ, not the product-FAQ concept). Excluded.
- Atlassian old URLs that 404'd (correct current URLs used instead): `/agile/models/user-stories` → S11; `/agile/product-development/invest` → S14; `/agile/kpis-metrics/story-points`, `/agile/estimating/story-points` → S15; `/agile/kanban/definition-of-ready` → S14; `/agile/glossary/icebox` → S17/S18.
- Web search (Bing / DuckDuckGo HTML via curl) → bot-blocked or dictionary-level results; no 2024–2026 practitioner posts on LLM-specific story sizing or icebox dependency gating could be located. Those findings below are marked `[inferred]`.

## Findings

### Q1 — PRD formats for small teams / solo operators

**What a PRD is and how heavy it gets.** A PRD defines a product's requirements — purpose, features, functionality, behavior — and communicates what is being built, who it is for, and why, to both business and technical teams [verified: fetched, S2]. Its form "will vary from project to project" [verified: fetched, S3]; the classic pipeline is PRD (user/client POV) → functional specification (technical POV) [verified: fetched, S3]. Atlassian's guidance for a working PRD: use a consistent template and include "just enough" context — project specifics (participants, status, target release), team goals and business objectives, then requirements [verified: fetched, S1].

**Amazon PR/FAQ (lightweight, customer-first).** Amazon's Working Backwards process (created 2005, after SWOT analysis, market-size research, and pro-forma P&Ls "none of these tools required us to think deeply enough about the needs of customers") uses a written narrative instead of a deck: a Press Release followed by FAQs [verified: fetched, S4]. The PR has a fixed shape: Heading (one sentence a target customer will understand), Subheading (who the customer is and what they gain — "if you think your product is for everyone, you are mistaken"), Summary Paragraph (city, outlet, launch date, product + benefits), Problem Paragraph (written from the customer's point of view) [verified: fetched, S4]. The FAQ has two sections: External FAQs (questions the press and customers will ask — how does it work, warranty, install) and Internal FAQs (the harder questions the team must answer) [verified: fetched, S4]. Bryar publishes ready-to-copy PR/FAQ templates plus review-meeting instructions [verified: fetched, S5].

**Spec-driven development (the 2025-era lightweight format for LLM agents).** GitHub Spec Kit's SDD keeps "intent and evidence ahead of implementation": a project constitution, then `/speckit-specify` → `/speckit-plan` → `/speckit-tasks` → `/speckit-implement` → `/speckit-converge`, with `/speckit-clarify`, `/speckit-checklist`, `/speckit-analyze` added for production features [verified: fetched, S6, S7]. Its separate *idea assessment* process (intake → research → define → shape → decide, ending in go / clarify / stop) is a lightweight "is this worth it" gate before any spec work [verified: fetched, S6]. Kiro's specs are the same shape: every spec generates `requirements.md`, `design.md`, `tasks.md`, with requirements broken "into user stories with acceptance criteria" [verified: fetched, S9], and a Requirements-First vs Design-First workflow choice (requirements-first when behavior is known and architecture is flexible; design-first when there's an existing architecture or strict NFRs) [verified: fetched, S10]. Microsoft's rationale for AI-agent teams: "code is inherently a binding artifact" and "code is really not the best medium for requirements negotiation" — the spec is where negotiation happens [verified: fetched, S8].

**Include vs cut for a one-operator + LLM team** `[inferred, grounded in S1, S2, S4, S6, S9]`:
- **Keep:** why/problem (customer POV, 1–3 sentences), one-paragraph press-release summary for anything non-trivial (S4 shape), requirements as user stories + acceptance criteria, non-goals, dependencies, open questions, sizing + priority score.
- **Cut:** exhaustive requirements matrices, change logs, org/stakeholder maps, marketing plans (one operator, no org), formal sign-off workflows.
- **Length target:** 1–2 pages for a typical board feature; PR/FAQ-style narrative only for big bets (new services/pipelines).
- The 2025 spec-driven pattern (spec → plan → tasks, with an explicit clarify step) is the best fit for an LLM groomer: the board card is the spec, grooming is clarify, and DEV-2's story breakdown is the tasks step [inferred, grounded in S6, S7, S9].

### Q2 — Story breakdown: AC formats, definition of ready, sizing, INVEST

**Story shape.** The standard format is "As a [user], I want [goal] so that [reason]" [verified: fetched, S11]. The 3 C's: Card (written description), Conversation (discussions that clarify details), Confirmation (the acceptance criteria that define when the story is complete) — "ensures that user stories are clear, collaborative, and testable" [verified: fetched, S11].

**Acceptance criteria.** AC are "the conditions that a product, user story, or increment of work must satisfy to be complete… clear, concise, and testable statements" focused on positive customer results; they describe the outcome, not the implementation [verified: fetched, S12]. Characteristics of good AC: clarity and conciseness (plain, unambiguous, same interpretation across engineering/QA/design/product), testability (every criterion "maps cleanly to one or more executable tests"), outcome-focus ("describe the result, not the recipe") [verified: fetched, S12]. Two concrete formats in common use:
- **Checklist** of testable outcome statements — the default; works for most stories [verified: fetched, S12].
- **Given/When/Then** — "a style of representing tests — or as its advocates would say — specifying a system's behavior" (Specification by Example) [verified: fetched, S13]. Best for concrete behavioral scenarios (state → action → observable result); not every criterion needs GWT [inferred, grounded in S13].

**Definition of ready.** DoR is "a set of criteria that ensures backlog items are actionable, clear, and feasible before work begins"; it improves communication and reduces errors by aligning expectations upfront [verified: fetched, S14]. Its key components are exactly the INVEST letters: independence, negotiability, value, estimability, small size, testability [verified: fetched, S14].

**INVEST.** Independently, Negotiable, Valuable, Estimable, Small, Testable — the six properties a good story should have; the components are verified via the Atlassian DoR page [verified: fetched, S14]. The original source (Bill Wake, 2003) could not be fetched (aconity.com and c2.com pages 404) — see Open questions.

**Sizing.** Story points estimate *relative* effort/complexity rather than calendar time: "traditional time-based estimates often fail because they create false precision around inherently uncertain work"; Fibonacci numbers (1, 2, 3, 5, 8…) are the common scale [verified: fetched, S15]. T-shirt sizes (S/M/L) are the lighter alternative widely used for rough backlog grooming [inferred; no fetched source — the Atlassian t-shirt page was not located, S15 covers the points-vs-time argument].

**What of INVEST holds up in practice** `[inferred, grounded in S11, S12, S14, S15, S17]`:
- **Independent, Small, Testable** are the ones that actually gate work — a story that can't be tested can't be accepted (S12), a story that can't be started without another story is a dependency problem, not a story problem (S16), and stories that are too big are the ones that die in the icebox (S17).
- **Negotiable** is the protection against over-specification: the card states the *what* and *why*; the LLM/developer conversation decides the *how* (S11's Conversation C).
- **Valuable** and **Estimable** are checked at grooming time (priority score + t-shirt/points), not per-story ceremony [inferred].
- For a solo operator + LLM, a 3-item hard gate (independent / small / testable) plus a negotiable-by-default convention covers most of the practical value of the full INVEST checklist [inferred].

### Q3 — Dependency mapping for a kanban board with icebox + LLM-identified dependency gating

**Dependency basics.** Dependencies are tasks that provide output or information necessary for other tasks, affecting sequencing and scheduling; the four relationship types are finish-to-start, start-to-start, finish-to-finish, start-to-finish [verified: fetched, S16]. Dependency management = identify, map, and communicate dependencies [verified: fetched, S16]. For a kanban board with one operator, finish-to-start ("B can't start until A is done") is the only type that matters in practice [inferred, grounded in S16].

**Icebox semantics.** The icebox (term popularized by Pivotal Tracker) "is the backlog of things that you aren't going to work on any time soon but you don't want to get rid of" [verified: fetched, S17]. It legitimately holds two kinds of stories: (a) features/issues that need more discussion or planning before they can be started, and (b) features/issues that are out of scope or very low priority [verified: fetched, S17]. The failure mode: "the Icebox becomes a place where stories go to die. It becomes cognitive overhead that slows down the team and makes the roadmap unclear" [verified: fetched, S17]. Thoughtbot's guidance: stories needing more discussion should sit in the priority-ordered backlog with a tag ("needs definition"), not in the icebox; use a separate "Inbox"/"Ideas" staging area for raw new ideas, groomed on a regular cadence [verified: fetched, S17]. In Jira, an icebox is implemented as a label + JQL filter that excludes it from the working board, optionally with a separate board view [verified: fetched, S18].

**Dependencies beat scores.** Intercom's RICE post explicitly notes that "one project may be a dependency for another project, so it needs to happen first" even with a lower score [verified: fetched, S23].

**Gating design for this board** `[inferred, grounded in S16, S17, S18, S23]`:
- Represent dependencies as explicit fields on each card: `blocked_by: [<card id>]` / `blocks: [<card id>]` (finish-to-start only).
- LLM grooming proposes dependency edges when it writes the spec (it sees the whole board); the operator confirms them — LLM-identified, human-approved.
- Gate rule: a card may move icebox → backlog (or backlog → In Progress) only when every `blocked_by` card is done/accepted; blocked cards are excluded from WIP and from priority scoring until unblocked.
- Icebox hygiene: two sub-states — `needs-definition` (stays visible in backlog view with a tag, per S17) and `parked` (low priority/out of scope, hidden from the working board, per S18); a periodic "icebox review" promotes or kills parked items to prevent the "stories go to die" failure mode (S17).

### Q4 — Competitive-analysis frameworks: lightweight vs heavy

**Heavy: Porter's Five Forces.** A method of analysing the competitive environment of a business, rooted in industrial-organization economics; five forces (competitive rivalry, threat of new entrants, threat of substitutes, bargaining power of suppliers, bargaining power of buyers) determine competitive intensity and industry profitability [verified: fetched, S19]. It is an *industry-level* analysis — built for deciding whether an industry is attractive, not for choosing between features or products [inferred, grounded in S19]. Porter's original 1979 HBR article is paywalled and the McKinsey page was bot-blocked, so this is verified via the Wikipedia treatment [verified: fetched, S19; original not fetched].

**Lightweight: positioning statement.** Product positioning = defining how customers perceive your product and what differentiates it from competitors; "strong positioning helps you stand out by showing customers why they should choose you over competitors"; effective positioning requires knowing who you're serving and what problem you're solving, and "turns product features into measurable outcomes" [verified: fetched, S20].

**Lightweight: feature comparison matrix.** A features × competitors table with a prioritization layer — Productside's matrix template helps "identify and prioritize features based on their cost and value" against competitors [verified: fetched, S21].

**What is worth it for a solo operator** `[inferred, grounded in S19, S20, S21]`:
- **Skip Porter's five forces** for homelab tooling: it answers "is this industry profitable?", which a one-operator shop with internal users doesn't need to answer; the effort-to-signal ratio is poor.
- **Do a one-page competitive note per idea:** (1) positioning statement — who it's for, what problem, why this over the alternatives (S20); (2) feature matrix against the 2–3 closest alternatives (S21) — enough to spot gaps and avoid building table-stakes features; (3) a "why them / why us" answer for the top alternative.
- For homelab ideas the "competitor" is often *doing nothing* or a shell one-liner; the matrix should include that column [inferred].

### Q5 — Opportunity sizing: TAM/SAM/SOM without analyst data

**Definitions.** TAM = "the total revenue opportunity available for a product or service in a specific market… the maximum revenue a company could generate if it held 100% market share"; SAM = "the portion of TAM that a company can realistically serve with its current product offerings, distribution channels, and target market"; SOM = "the market share a company can realistically achieve within its SAM in a specific timeframe… the most conservative estimate" [verified: fetched, S22].

**Two calculation approaches.** "There are two primary approaches to calculating TAM, SAM, and SOM: top-down and bottom-up. Each method has its advantages and limitations, and it's smart to use both approaches for a more accurate and comprehensive [estimate]" [verified: fetched, S22]. Top-down starts from market reports and slices down; bottom-up starts from countable units (e.g., users × price) and multiplies up [verified: fetched, S22; the bottom-up "users × price" form is the standard reading of the page's examples].

**Stating uncertainty honestly** `[inferred, grounded in S22]`:
- For a homelab team the "market" is internal: 1 operator + N LLM agents. Bottom-up is the only honest method — users × (time saved or value per use) — and the numbers are small and self-reported; report them as **ranges with the assumption list attached**, never point estimates.
- Top-down analyst data is mostly irrelevant for internal tooling (no analyst covers "homelab kanban grooming"); it only becomes relevant if an artifact might be published or monetized, in which case cite the report, its date, and that the slice is a guess.
- SOM for an internal tool = "what will we actually use next quarter" — i.e., the next 2–3 board cards. The TAM/SAM/SOM exercise's real value here is forcing the assumption list into the PRD, not producing a number [inferred].

### Q6 — Ideation + prioritization: RICE, ICE, Kano, and lighter options

**RICE (the actual formula).** `RICE score = (Reach × Impact × Confidence) / Effort`, which "measures total impact per time worked" [verified: fetched, S23]. Scales from the origin post: **Reach** = how many people the project affects within a defined time period (e.g., "800 customers per quarter"); **Impact** = per-person effect on the goal, multiple-choice 3 (massive) / 2 (high) / 1 (medium) / 0.5 (low) / 0.25 (minimal); **Confidence** = 100% (high) / 80% (medium) / 50% (low); **Effort** = total person-months across product/design/engineering, whole numbers, minimum 0.5, "don't get into the weeds of estimation" [verified: fetched, S23]. Documented misuses: bias toward pet ideas/clever ideas, and "RICE scores shouldn't be used as a hard and fast rule" — a lower-scoring project may have to go first because it's a dependency, or another feature may be table stakes [verified: fetched, S23]. Atlassian's added caveat: RICE "can be time-consuming and cumbersome… methods for determining each evaluation factor can change, making this method subjective, inconsistent, and potentially misleading" [verified: fetched, S25].

**ICE (the actual formula).** `ICE score = Impact × Confidence × Ease`, each rated 1–10; "a relatively quick way to assign a numerical value to different potential projects or ideas" [verified: fetched, S24]. Impact = how much the project moves the target metric; Confidence = certainty it will have the predicted impact; Ease = level of effort (inverse of RICE's Effort) [verified: fetched, S24]. ICE is RICE with Reach dropped and Effort inverted — the right default when you have no usage data to estimate Reach [inferred, grounded in S23, S24].

**Kano (the actual model).** Developed by Noriaki Kano (Tokyo University of Science) in the 1980s; original paper: Kano, Seraku, Takahashi, Tsuji, "Attractive Quality and Must-Be Quality", *Journal of the Japanese Society for Quality Control* 14(2), April 1984 (in Japanese) [verified: fetched, S26, S27]. It prioritizes features by customers' *emotional responses* rather than benefit/cost [verified: fetched, S26]. Categories: **must-be** (expected; absence causes dissatisfaction, presence is taken for granted), **performance/one-dimensional** (more = more satisfaction, linear), **attractive/exciting** (delighters; absence doesn't hurt, presence delights), **indifferent** (no effect), plus **reverse** and **harmful** in the full model [verified: fetched, S26, S27]. Strategic use: "build a competitive customer experience by providing features customers expect, adding a few unexpected but exciting features, and reducing the number of features that customers don't like" [verified: fetched, S26]. Misuses: it is "highly quantitative and potentially time-consuming" [verified: fetched, S25]; categories drift over time (today's delighter becomes tomorrow's must-be) [inferred, grounded in S26]; and without real customer data it just encodes the operator's own preferences [inferred].

**Lighter options.**
- **Value/impact vs effort** (2×2 quadrant) — listed among the six common frameworks alongside RICE, Kano, MoSCoW, opportunity scoring, and cost of delay; "the one you use should depend on your team and project needs" [verified: fetched, S25].
- **Dot voting** — each participant gets a fixed number of tokens ("dots") to assign to alternatives; the board becomes a heat map showing where votes concentrate; "a simple tool used to democratically prioritize items… one of the few UX workshop activities that work well in any situation" [verified: fetched, S28]. Cheap convergence method for operator + LLM-agent idea lists [inferred, grounded in S28].
- **1-10-100 rule (prioritization, Marty Cagan)** — the rule that the value of ideas is distributed in orders of magnitude (roughly: for every one idea that is 10×, there are ten that are 1× and a hundred that are 0.1×), so the job of prioritization is to find the 10× ideas rather than rank the 1× ones. **Status: NOT verified from a primary source** — the SVPG article soft-redirects to the homepage and no Wayback snapshot exists (2026-11-23); the rule is described in Cagan's book *Inspired* (2017), which was not fetched. Treat as `[inferred / secondary]`. Do **not** confuse it with the 1-10-100 *cost-of-quality* rule (defect-fix cost grows ~10× per lifecycle phase), which is a different rule and was verified [verified: fetched, S29].

**When each fits** `[inferred, grounded in S23, S24, S25, S26, S28]`:
- No data, many ideas, fast decision → **ICE** (or dot voting for convergence, then ICE for the shortlist).
- Real usage data exists (e.g., Plausible counts) → **RICE**, because Reach becomes measurable.
- Long feature list, need to know what's table stakes vs delighter → **Kano** classification (must-be = build all, they're cheap; attractive = pick a few; indifferent = cut).
- Two ideas, gut call → **value/effort quadrant** or operator judgment; record the rationale either way (PM-3 needs it).

## Implications for the PM + DEV-2 skill builds

Concrete design inputs the skill builds should cite. (All "should" statements here are `[inferred]` design recommendations grounded in the verified findings above.)

### PM-2 `pm-product-requirements` — PRD template shape

The board spec → PRD template (1–2 pages for typical features; narrative PR/FAQ section only for big bets):

```markdown
# <Feature name> — PRD
- Status: draft | grooming | approved | in-progress | done
- Participants: operator + <agent roles>
- Target date: <date or "unscheduled">

## Why (problem, customer POV, 1–3 sentences)
<PR/FAQ Problem Paragraph shape [S4]>

## Summary (one-paragraph "press release")
<Heading + who it's for + what they gain [S4]; optional for small features>

## Requirements
<user stories: "As a [user], I want [goal] so that [reason]" [S11],
each with acceptance criteria [S12]:
  - default: checklist of testable, outcome-focused statements [S12]
  - Given/When/Then for concrete behavioral scenarios [S13]>

## Non-goals / out of scope
<explicit list — the "negotiable" boundary [S14]>

## Dependencies
blocked_by: [<card ids>] / blocks: [<card ids>]   [S16]

## Sizing & priority
size: S|M|L (or points) [S15] | score: <ICE or RICE with inputs> [S23, S24]

## Open questions
<unresolved items; gates "approved" status>
```

- Cut from legacy PRDs: requirements matrices, change logs, org/stakeholder maps, sign-off workflows [S1, S2].
- For LLM agents, mirror the spec-driven pipeline: spec (this doc) → clarify (grooming pass) → plan/tasks (DEV-2) [S6, S7, S9]; keep the constitution-level rules (repo conventions, quality gates) out of per-feature PRDs [S7].
- Requirements-First is the default workflow; use Design-First only when an existing architecture or strict NFRs drive the work [S10].

### DEV-2 `story-breakdown` — AC format, DoR, sizing

- **AC format:** default = checklist of testable, outcome-focused statements ("describe the result, not the recipe") [S12]; use Given/When/Then for state→action→observable-result scenarios [S13]. Every AC must map to an executable test or check [S12] — stories carry their tests (per the program's G5 decision).
- **Definition of Ready (hard gate before a story enters In Progress):** actionable, clear, feasible [S14], operationalized as: (1) independent — no unresolved `blocked_by` [S16]; (2) small — splittable further if it exceeds the team's t-shirt ceiling [S15]; (3) testable — every AC maps to a check [S12, S14]. Soft checks at grooming: negotiable (card states what/why, not how) [S11, S14], valuable (has a priority score with rationale) [S14], estimable (has a size) [S14, S15].
- **Sizing:** t-shirt S/M/L by default (relative, not calendar time — time estimates "create false precision") [S15]; record the basis for the size (complexity, unknowns, scope) so the LLM's estimate is auditable.
- **Breakdown rule:** if a story fails "small" or "independent", split it or record the dependency edge — don't start it [inferred, grounded in S14, S16, S17].

### PM-5 `pm-prioritization` — RICE/ICE/Kano decision rule

1. **Default: ICE** (Impact × Confidence × Ease, each 1–10) when no usage data exists — the homelab default [S24].
2. **Upgrade to RICE** ((Reach × Impact × Confidence) / Effort) when real usage data exists (Plausible etc.) so Reach is measured, not guessed; use the origin-post scales (Impact 3/2/1/0.5/0.25; Confidence 100/80/50%; Effort in whole person-months, min 0.5) [S23].
3. **Use Kano** only for long feature lists: classify must-be / performance / attractive / indifferent; build all must-be (cheap, expected), pick a few attractive, cut indifferent [S26, S27].
4. **Overrides that beat the score:** dependency prerequisites ("one project may be a dependency for another project, so it needs to happen first") [S23], strategic/operator veto, and table-stakes features [S23].
5. **Record inputs, not just the score:** store Reach/Impact/Confidence/Effort (or I/C/E) separately with the rationale text — PM-3's pitch and future re-scoring need them; scores are "not a hard and fast rule" [S23].
6. **Calibration guard:** re-score after the first sort and challenge outliers ("Are there projects where the score seems too high or too low?") [S23]; flag that the method is "subjective, inconsistent, and potentially misleading" if inputs change between items [S25].

### Dependency representation (board schema, feeds DEV-2 + all PM skills)

- Card fields: `blocked_by: [ids]`, `blocks: [ids]` — finish-to-start only [S16].
- LLM grooming proposes edges (it reads the whole board); operator approves [inferred].
- Gate: icebox → backlog and backlog → In Progress require all `blocked_by` done/accepted; blocked cards are excluded from WIP and from scoring until unblocked [inferred, grounded in S16, S23].
- Icebox: two sub-states — `needs-definition` (visible in backlog view with a tag, per Thoughtbot's "tag it, don't icebox it") and `parked` (hidden from the working board, Jira-label pattern) [S17, S18]; periodic icebox review promotes or kills parked items ("stories go to die" is the named failure mode) [S17].

### PM-1 `pm-market-analysis` — competitive + sizing inputs

- Per-idea competitive note (one page): positioning statement (who/what problem/why this over alternatives) [S20] + feature matrix vs the 2–3 closest alternatives including a "do nothing / shell script" column [S21] + "why them / why us" for the top alternative [inferred].
- Skip Porter's five forces for homelab tooling [inferred, grounded in S19].
- Opportunity sizing: bottom-up only (users × value per use) as **ranges with an explicit assumption list**; top-down analyst data only if the artifact might be published/monetized, then cite report + date [S22, inferred].

### PM-4 `pm-ideation` — ideation inputs

- Idea capture: raw ideas go to an Inbox/Ideas staging area, groomed on a regular cadence (not directly into the backlog) [S17].
- Convergence: dot voting (tokens per participant; works "in any situation") for operator + agent lists [S28].
- Classification: Kano pass on the shortlist (must-be / performance / attractive / indifferent) [S26, S27].
- 1-10-100 heuristic (find the 10× idea, don't rank the 1× ones) is available as a framing device but is **unverified** (see Open questions) — mark it as such in skill output.

### PM-3 `pm-exec-pitch` — pitch inputs

- Pitch skeleton: Why/problem paragraph (customer POV) [S4] + one-paragraph press-release summary [S4] + ICE/RICE score with inputs [S23, S24] + bottom-up opportunity range [S22] + competitive one-pager (positioning + matrix) [S20, S21]. The PR/FAQ press release *is* the pitch narrative for a solo operator [inferred].

## Open questions / gaps

Honest list of what could not be verified:

1. **Kano 1984 original paper** ("Attractive Quality and Must-Be Quality", *J. Japanese Society for Quality Control* 14(2): 39–48, in Japanese) — not fetched (scispace empty response; original is Japanese and behind ci.nii.ac.jp). Verified only via secondary citations in S26/S27. The category names and 1984 date are consistent across both secondaries.
2. **Bill Wake's original INVEST post (2003)** — aconity.com (both URL variants) and c2.com wiki page all 404. INVEST components verified via the Atlassian DoR page (S14) instead; the attribution "Bill Wake, 2003" is standard knowledge and is marked `[inferred]` where used.
3. **Cagan's 1-10-100 prioritization rule** — `svpg.com/the-1-10-100-rule/` soft-redirects to the SVPG homepage (2026-11-23) and no Wayback snapshot exists (availability API + CDX checked). The rule as stated in Q6/PM-4 is `[inferred / secondary]` from Cagan's book *Inspired* (2017, not fetched). Needs a primary-source re-verify before the PM-4 build cites it as fact.
4. **Amazon PR/FAQ primary chapter** — the *Working Backwards* book page on amazon.com is cookie-walled; verified via Bryar's own published template doc (S5) and workingbackwards.com (S4) instead. PR section names (Heading/Subheading/Summary/Problem) come from S4's fetched text.
5. **Porter's Five Forces original (HBR, 1979)** — paywalled; McKinsey page Akamai-blocked. Verified via Wikipedia (S19) only.
6. **Investopedia TAM page** — 404 (moved). TAM/SAM/SOM verified via Foundation Inc. (S22) only; a second independent source on bottom-up heuristics would strengthen Q5.
7. **Cucumber GWT docs** — `cucumber.io/docs/cucumber/given-when-then/` 404 (docs restructured). GWT verified via Fowler (S13) + Atlassian (S12).
8. **2024–2026 practitioner sources on LLM-specific story sizing / icebox dependency gating** — web search (Bing/DDG via curl) was bot-blocked, so none could be located. All LLM-workflow adaptations in Q2/Q3 and the Implications section are `[inferred]` from general agile sources + the 2025 spec-driven tooling docs (S6–S10), which are the closest fetched analogue for "LLM as groomer/breakdown agent".
9. **T-shirt sizing** — no fetched source; the points-vs-time argument (S15) is verified, but the t-shirt convention itself is `[inferred]`.
10. **Atlassian glossary "icebox" page** — 404; icebox semantics verified via Thoughtbot (S17) + LinkedIn (S18) instead.
11. **`akfpartners.com` 1-10-100 (S29)** is the *cost-of-quality* rule — deliberately kept distinct from Cagan's prioritization rule; if a future fetch verifies Cagan's version, S29 should not be cited for it.
12. **Dot voting with LLM agents** — S28 covers human groups; applying tokens to an operator + agent panel is `[inferred]`.
