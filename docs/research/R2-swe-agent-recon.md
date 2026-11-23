# R2 — How SWE agents orient in unfamiliar repos (repo-map generation, recon artifacts, time-boxing)

- **Question (R2):** How do SWE agents orient in unfamiliar repos — repo-map generation, recon artifacts that help downstream, time-boxing?
- **Date:** 2026-11-23
- **Status:** done
- **Feeds:** S2 `codebase-recon` (primary), DEV-1 `architecture`, DEV-2 `story-breakdown` (grounding)
- **Method note:** The MCP web tools named in the TODO (`mcp_search_search_web`, `mcp_crawl_crawl_page`) were not available in this worker session. All sources were therefore verified by direct HTTP fetch (curl/python urllib) of the primary pages, with content read in full or in the relevant sections. Failed fetches and alternate-source attempts are noted in `## Sources` and `## Open questions / gaps`.
- **Honesty convention:** `[verified: fetched]` = claim read directly in a fetched page (listed in Sources). `[inferred]` = synthesis/judgment by the researcher, flagged as such.

## Sources

All fetched 2026-11-23. "Date" = publication/modification date of the source (or fetch date when the source is undated).

| # | URL | Date | What it provided | Fetched-verified |
|---|-----|------|------------------|------------------|
| S1 | https://aider.chat/docs/repomap.html | Last-Modified 2026-04-25 | Aider repo-map: files + key symbols + critical lines; graph ranking over file-dependency graph; `--map-tokens` budget (default 1k); dynamic map expansion when no files are in chat | yes |
| S2 | https://aider.chat/2023/10/22/repomap.html | 2023-10-22 | Aider blog "Building a better repository map with tree sitter": 3-step framing (find code / understand relations / make change); tree-sitter tags replace ctags; map as a "menu" the LLM uses to pick files to read; token-efficiency rationale | yes |
| S3 | https://aider.chat/2024/06/02/main-swe-bench.html | 2024-06-02 | Aider SOTA on SWE-bench main (18.9%, 2024): "interactive, not agentic" — deliberately limited agentic behavior to avoid delays/costs; no RAG/vector search/tools; `--test-cmd pytest`; plausibility-retry harness | yes |
| S4 | https://arxiv.org/abs/2310.06770 | v1 2023-10-10, v3 2024-11-11 (ICLR 2024) | SWE-bench paper: 2,294 real GitHub issues / 12 Python repos; resolving issues "frequently requires understanding and coordinating changes across multiple functions, classes, and even files"; Claude 2 solved 1.96% (2023 baseline) | yes |
| S5 | https://arxiv.org/abs/2405.15793 | v1 2024-05-06, v3 2024-11-11 (NeurIPS 2024) | SWE-agent paper: the agent-computer interface (ACI) "significantly enhances an agent's ability to create and edit code files, navigate entire repositories, and execute tests"; 12.5% SWE-bench pass@1 | yes |
| S6 | https://raw.githubusercontent.com/SWE-agent/SWE-agent/main/README.md | undated (news items through 2025-07-24) | mini-swe-agent: "100 lines of python", 65% on SWE-bench Verified (2025-07); "free-flowing & generalizable: leaves maximal agency to the LM"; single YAML config | yes |
| S7 | https://arxiv.org/abs/2407.16741 | v1 2024-07-23, v3 2025-04-18 (ICLR 2025) | OpenHands paper: agents interact "similar ways to those of a human developer: by writing code, interacting with a command line, and browsing the web"; sandboxed execution; multi-agent coordination | yes |
| S8 | https://docs.openhands.dev/overview/introduction | fetched 2026-11-23 (docs moved from docs.all-hands.dev) | Current OpenHands component map (Canvas / SDK / Agent Server / Sandbox); docs instruct agents: "Fetch the complete documentation index at: /llms.txt … before exploring further" | yes |
| S9 | https://docs.openhands.dev/llms.txt | fetched 2026-11-23 | Machine-readable page index of the whole docs site (real-world llms.txt in use); pointed at Context Condenser, Persistent Memory, Task Tool Set, Design Principles pages | yes |
| S10 | https://docs.openhands.dev/sdk/guides/context-condenser.md | Last-Modified 2026-11-23 | `LLMSummarizingCondenser`: keeps recent messages, preserves user goals/specs/critical files, summarizes older history; up to 2x per-turn API cost reduction; "equivalent or better performance" on SWE tasks; `max_size`/`keep_first` thresholds | yes |
| S11 | https://docs.openhands.dev/sdk/guides/persistent-memory.md | fetched 2026-11-23 | Two-tier Markdown memory (user `~/.openhands/memory/`, project `/.openhands/memory/`); `MEMORY.md` index injected into system prompt (~6,000-char budget); daily logs read on demand; agent maintains files itself; opt-in, off by default; untrusted-by-design | yes |
| S12 | https://docs.openhands.dev/sdk/guides/task-tool-set.md | fetched 2026-11-23 | Sub-agents run synchronously, return results to parent, resumable by task ID; "isolating sub-task complexity from the parent agent's context" | yes |
| S13 | https://docs.openhands.dev/sdk/arch/agent.md | fetched 2026-11-23 | Reasoning-action loop; context management via skills + condensers; security validation of proposed actions before execution | yes |
| S14 | https://docs.openhands.dev/sdk/arch/design.md | fetched 2026-11-23 | V1 design principles from V0 lessons: stateless by default, one source of truth for state (conversation state), opt-in sandboxing | yes |
| S15 | https://code.claude.com/docs/en/best-practices | lastModified 2026-11-21 (live URL anthropic.com/engineering/claude-code-best-practices redirects here) | "Claude starts every task by reading your code… usually faster than you could explain them"; two-question test for what to write down; CLAUDE.md template (Commands/Conventions/Gotchas); four failure modes; `--max-turns`/`--max-budget-usd`; "What you can stop doing" (context window no longer the main constraint; don't describe architecture/file layout in CLAUDE.md) | yes |
| S16 | https://code.claude.com/docs/en/how-claude-code-works | fetched 2026-11-23 | Agentic loop = gather context → take action → verify results; what loads at startup (CLAUDE.md/AGENTS.md, auto memory 200 lines/25KB, MCP tool names, skill descriptions); tool categories incl. code intelligence (type errors, jump-to-definition, find-references) | yes |
| S17 | https://code.claude.com/docs/en/context-window | fetched 2026-11-23 | Token-budget table (system prompt 4.2k, project CLAUDE.md 1.8k, file reads 1.1–2.4k each); subagent keeps large reads out of main context (9.9k tokens in subagent window → 420-token summary back); what survives compaction (CLAUDE.md re-injected from disk, up to 5 most-recently-modified files re-read, skill bodies capped 5k/25k) | yes |
| S18 | https://code.claude.com/docs/en/memory | fetched 2026-11-23 | When to add to CLAUDE.md (same mistake twice; review finding; same correction twice; new teammate would need it); concrete verifiable instructions; <200 lines; path-scoped rules + nested CLAUDE.md load on demand; AGENTS.md fallback; auto memory types (user/feedback/project/reference) and "skips anything it can derive from the codebase" | yes |
| S19 | https://www.anthropic.com/engineering/claude-code-best-practices | published 2025-04-18 (verified via Wayback snapshot 2025-10-02; live URL now redirects to S15) | "context gathering consumes time and tokens"; CLAUDE.md contents list (bash commands, core files, code style, testing instructions, repo etiquette, env setup, unexpected behaviors) + template; "Explore, plan, code, commit" workflow with early subagent use; "Steps #1-2 are crucial—without them, Claude tends to jump straight to coding"; `/clear` between tasks; checklists/scratchpads; course-correct early and often | yes (via archive snapshot) |
| S20 | https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents | published 2025-09-29 | Context rot (recall degrades as context grows; "attention budget"; diminishing marginal returns); just-in-time retrieval (lightweight identifiers loaded at runtime) vs embedding-based pre-inference retrieval; Claude Code hybrid "effectively bypassing the issues of stale indexing and complex syntax trees"; progressive disclosure (file size/naming/timestamps as signals); compaction; structured note-taking (NOTES.md); sub-agent architectures (explore with tens of thousands of tokens → return 1,000–2,000-token summary) | yes |
| S21 | https://cognition.ai/blog/dont-build-multi-agents | 2025-06-12 (Walden Yan) | Context engineering is "the #1 job"; share full traces not just messages; "actions carry implicit decisions, and conflicting decisions carry bad results"; single-threaded linear agent by default; compression model for long context; Claude Code subagents answer questions (not write code) so investigative work stays out of the main history | yes |
| S22 | https://agents.md/ | fetched 2026-11-23 (page undated; project launched 2025, now stewarded by the Agentic AI Foundation under the Linux Foundation) | AGENTS.md open format "README for agents", 60k+ OSS projects; popular sections (project overview, build and test commands, code style, testing instructions, security considerations); nested AGENTS.md for monorepos (nearest wins); agents run listed test commands automatically; Aider can be configured to read it | yes |
| S23 | https://cursor.com/docs/agent/tools/search | fetched 2026-11-23 (docs.cursor.com/context/codebase-indexing redirects to docs root; this is the current search/context-gathering page) | Instant Grep (regex/word-boundary, faster than ripgrep, local index, "does not store embeddings of your codebase for search"); Explore subagent (own context window, faster model, parallel searches, "returning only the relevant findings"; "Searching through many files generates a lot of context. The subagent keeps the main conversation focused by summarizing results instead of dumping raw file contents") | yes |
| S24 | https://llmstxt.org/ | published 2024-09-03, modified 2026-08-10 (Jeremy Howard) | llms.txt v2: /llms.txt as the standard agent-facing site map; "thousands of sites publish an llms.txt file, documentation platforms generate one automatically"; AI labs publish them for their developer docs; clean `.md` versions at page URLs | yes |

**Failed fetches / alternates (all resolved):**
- `https://aider.chat/2023/10/22/ranking.html` → 404. Found the correct post via the aider sitemap: `https://aider.chat/2023/10/22/repomap.html` (fetched, S2).
- `https://aider.chat/docs/usage/` → 404 (docs restructured). Not needed — the repomap docs page (S1) covers the same material.
- `https://docs.cursor.com/context/codebase-indexing` → redirects to the Cursor docs root; no dedicated codebase-indexing page exists in current docs. Fetched the current equivalent (`cursor.com/docs/agent/tools/search`, S23). See Open questions.
- `https://www.anthropic.com/engineering/claude-code-best-practices` → live URL now redirects to the Claude Code docs best-practices page (S15). Original post content verified via Wayback Machine snapshot 2025-10-02 (S19).
- `https://docs.all-hands.dev/` → redirects to `docs.openhands.dev/overview/introduction` (docs moved); fetched at the new URL (S8).

## Findings

### Q1 — Orientation/recon steps production SWE agents perform before touching code

**The verified common shape.** Across the production agents examined, orientation before the first edit has the same five moves, in roughly this order:

1. **Load durable project knowledge if it exists** — instruction/memory files that survive across sessions. Claude Code loads CLAUDE.md/AGENTS.md, auto memory (first 200 lines or 25KB of MEMORY.md), MCP tool names, and skill descriptions before the first prompt [verified: fetched, S16][S17]. OpenHands V1 injects an opt-in two-tier memory index the same way [verified: fetched, S11]. AGENTS.md is the cross-tool standard for this ("used by over 60k open-source projects") [verified: fetched, S22].
2. **Build a cheap whole-repo view** — Aider sends a repo map (files + key symbols + critical lines) with every request so the LLM "can see classes, methods and function signatures from everywhere in the repo" before deciding what to read [verified: fetched, S1][S2]. Cursor's agent uses an exact-match grep engine (Instant Grep) for symbol/regex lookups [verified: fetched, S23]. Claude Code's tools include search (regex), file operations, and code intelligence (type errors, jump-to-definition, find-references) for the same job [verified: fetched, S16].
3. **Targeted reads of the task's files, with noisy exploration delegated to subagents** — Claude Code's documented workflow is "Explore, plan, code, commit": "Ask Claude to read relevant files… but explicitly tell it not to write any code just yet. This is the part of the workflow where you should consider strong use of subagents… especially early on in a conversation or task, tends to preserve context availability without much downside in terms of lost efficiency" [verified: fetched, S19]. Cursor's Explore subagent "runs in its own context window… executes many parallel searches without bloating the main conversation, returning only the relevant findings" [verified: fetched, S23]. Anthropic's context-engineering post generalizes this: subagents "might explore extensively, using tens of thousands of tokens or more, but return[] only a condensed, distilled summary of their work (often 1,000-2,000 tokens)" [verified: fetched, S20].
4. **Find the build/test/deploy commands and verify them** — Aider's SWE-bench harness runs with `--test-cmd pytest` so the agent knows the test command from the start [verified: fetched, S3]. Claude Code's best-practices list the exact test/typecheck/lint commands and "how to run a single test file" as the first thing a persistent instruction file should hold [verified: fetched, S15][S19]. AGENTS.md's popular sections are the same list: build and test commands, testing instructions, security considerations [verified: fetched, S22].
5. **Plan before editing** — "Steps #1-2 [explore + plan] are crucial—without them, Claude tends to jump straight to coding a solution… asking Claude to research and plan first significantly improves performance for problems requiring deeper thinking upfront" [verified: fetched, S19]. Claude Code's whole loop is formalized as **gather context → take action → verify results** [verified: fetched, S16].

**Why orientation matters (the benchmark evidence).** SWE-bench exists because "resolving issues… frequently requires understanding and coordinating changes across multiple functions, classes, and even files simultaneously" — i.e., the hard part is orientation, not typing code [verified: fetched, S4]. The SWE-agent paper's central finding is that the *interface* the agent uses to navigate the repo is itself the orientation mechanism: a purpose-built ACI "significantly enhances an agent's ability to create and edit code files, navigate entire repositories, and execute tests" [verified: fetched, S5]. And the mini-swe-agent result (≈100 lines of Python, minimal toolset, 65% on SWE-bench Verified in 2025) shows a simple loop + good navigation tools beats elaborate scaffolding [verified: fetched, S6].

**Agent-design contrast (useful for S2's positioning).** Aider's SOTA SWE-bench result (2024) was achieved *without* agentic exploration: "Aider intentionally has quite limited and narrow 'agentic behavior' to avoid long delays, high token costs and the need for users to repeatedly code review incorrect solutions… aider currently does not use RAG, vector search, tools or give the LLM access to search the web or unilaterally execute code" [verified: fetched, S3]. OpenHands, by contrast, gives the agent a full human-developer surface (code, command line, browser) inside a sandbox [verified: fetched, S7][S13]. [inferred] Both ends work because the orientation artifacts (repo map vs. sandbox + shell) do the same job: make the repo navigable with a bounded context cost.

### Q2 — Repo-map generation techniques: what works, what it costs, when to use which

**Aider's repo-map (tree-sitter + graph ranking).** Verified mechanics:
- tree-sitter parses every source file into an AST; the parser extracts symbol *definitions* (classes, functions, types, variables) and *references* (where each symbol is used) [verified: fetched, S2].
- A graph is built with each source file as a node and edges connecting files with dependencies; a "graph ranking algorithm" selects the most important identifiers — "the ones which are most often referenced by other portions of the code" — to fit a token budget [verified: fetched, S1].
- The map shows only the critical lines for each definition (signatures, class/function headers) with elided bodies (`⋮...`), grouped per file [verified: fetched, S1][S2].
- Budget: `--map-tokens`, **default 1k tokens**; the map "stays within that setting's value" but "expands… significantly at times, especially when no files have been added to the chat and aider needs to understand the entire repo as best as possible" [verified: fetched, S1].
- Cost: local, fast, deterministic, no index to maintain (computed per request); replaces ctags for richer signatures and broad language support [verified: fetched, S2].
- Role: the map is a *menu* — "GPT can use the map to figure out by itself which files it needs to look at in more detail. GPT will then ask to see these specific files, and aider will automatically add them to the chat context" [verified: fetched, S2].

**Exact-match search (grep) as a map substitute.** Cursor's current agent search is grep-first: Instant Grep "outperforms ripgrep on large codebases", supports full regex and word-boundary matching, runs locally, and — notably — "Cursor does not… store embeddings of your codebase for search" [verified: fetched, S23]. Claude Code's just-in-time approach is the same idea with shell primitives: "primitives like glob and grep allow it to navigate its environment and retrieve files just-in-time" [verified: fetched, S20].

**Embedding-based retrieval.** Anthropic's context-engineering post frames the trade directly: many AI-native apps use "embedding-based pre-inference time retrieval to surface important context", but the field is moving toward "just in time" strategies where agents "maintain lightweight identifiers (file paths, stored queries, web links, etc.) and use these references to dynamically load data into context at runtime" [verified: fetched, S20]. Claude Code's hybrid (CLAUDE.md up front + glob/grep at runtime) is described as "effectively bypassing the issues of stale indexing and complex syntax trees" [verified: fetched, S20]. Aider hit SOTA on SWE-bench (2024) with no RAG/vector search at all [verified: fetched, S3].

**When to use which [inferred, from the verified trade-offs above]:**
- **Small–medium repos (homelab scale): tree-sitter symbol map or grep.** Cheap, deterministic, always current, fits in ~1k tokens. Aider's design is the reference implementation.
- **Very large repos / semantic (not syntactic) queries: embedding retrieval** — when "find the code that handles payment retries" can't be expressed as a regex. Accept the index-build cost and the staleness risk (re-index on change).
- **Noisy broad exploration in any repo: subagent with a summary budget.** Verified across Cursor (Explore subagent, S23), Claude Code (subagents keep large reads out of the main context, S17), OpenHands (Task Tool Set, S12), and Anthropic's guidance (S20).
- **What actually works in 2025–2026 production agents:** static symbol maps (Aider), exact-match grep (Cursor), just-in-time reads (Claude Code). [inferred] Embedding indexes are the least common choice in the fetched sources — the trend is toward cheap deterministic orientation + just-in-time reads because current models navigate well; embeddings remain the right tool when the query is semantic and the repo is too big to map.

### Q3 — Recon artifacts that help downstream: format and granularity that works

**The canonical artifact is a short, persistent, agent-maintained instruction file** (CLAUDE.md / AGENTS.md / MEMORY.md), and the sources are remarkably consistent about what goes in it:

- **Contents (Anthropic, 2025-04):** "Common bash commands; Core files and utility functions; Code style guidelines; Testing instructions; Repository etiquette (e.g., branch naming, merge vs. rebase); Developer environment setup (e.g., pyenv use, which compilers work); Any unexpected behaviors or warnings particular to the project" [verified: fetched, S19].
- **Contents (Claude Code, 2026):** "How to confirm work in this repo: the exact test, typecheck, and lint commands, and how to run a single test file; Places where the code is misleading: an old pattern that's everywhere but that new code must not copy, or a directory that looks unused but isn't; Decisions that aren't in the repo: which error helper the team settled on, how deploys work, what needs a migration review; Anything you've had to correct twice already" [verified: fetched, S15].
- **AGENTS.md popular sections:** project overview, build and test commands, code style guidelines, testing instructions, security considerations — plus "anything you'd tell a new teammate" (commit/PR guidelines, security gotchas, deploy steps) [verified: fetched, S22].
- **OpenHands persistent memory contents:** "root causes, environment quirks, project decisions, user preferences" [verified: fetched, S11].

**Format and granularity that works (all verified):**
- **Short, structured markdown: headers + bullets.** Verified templates: `# Commands / # Conventions / # Gotchas` [S15] and `# Bash commands / # Code style / # Workflow` [S19].
- **Size budget: under 200 lines per file** — "Longer files consume more context and reduce adherence" [verified: fetched, S18]; OpenHands caps its injected memory index at ~6,000 characters [verified: fetched, S11].
- **Concrete, verifiable instructions, not adjectives:** "Use 2-space indentation" instead of "Format code properly"; "Run `npm test` before committing" instead of "Test your changes"; "API handlers live in `src/api/handlers/`" instead of "Keep files organized" [verified: fetched, S18].
- **Only what can't be re-derived from the repo.** The two-question test: "1. Could it find this by reading the code? 2. Would it actually go and look? If both are yes, leave it out" [verified: fetched, S15]. Claude Code's auto memory "skips anything it can derive from the codebase, such as architecture, file paths, or debugging fixes" [verified: fetched, S18]. And the 2026 best-practices page explicitly retires the old advice: "Describe your architecture and file layout in CLAUDE.md → Claude reads the repo itself. Only write down what isn't in there" [verified: fetched, S15].
- **Trigger for writing an entry:** "Claude makes the same mistake a second time; A code review catches something Claude should have known; You type the same correction… that you typed last session; A new teammate would need the same context" [verified: fetched, S18].
- **Split by scope:** multi-step procedures → skills; rules that apply to one part of the codebase → path-scoped rules that "load only when Claude works with matching files" (nested CLAUDE.md/AGENTS.md load on demand when a file in that subdirectory is touched) [verified: fetched, S18][S22].

**Two more verified artifact patterns:**
- **Scratchpad/checklist for in-flight work:** "improve performance by having Claude use a Markdown file (or even a GitHub issue!) as a checklist and working scratchpad" [verified: fetched, S19]; Anthropic's "structured note-taking" — "the agent regularly writes notes persisted to memory outside of the context window… Like Claude Code creating a to-do list, or your custom agent maintaining a NOTES.md file" [verified: fetched, S20].
- **Machine-readable map for docs sites:** llms.txt v2 — "/llms.txt markdown file to websites to provide LLM-friendly content… brief background information, guidance, and links to detailed markdown files"; thousands of sites publish one, and AI labs publish them for their developer docs [verified: fetched, S24]. OpenHands' docs use it in practice: "Fetch the complete documentation index at: /llms.txt. Use this file to discover all available pages before exploring further" [verified: fetched, S8][S9]. [inferred] The repo-level analog of llms.txt is exactly the recon note: a one-file map of where everything is, with links (paths) instead of content.

### Q4 — Time-boxing: recon time/context budget and concrete stopping rules

**Verified budgets (the numbers production systems actually use):**
- Aider repo-map: **1k tokens default** per request (`--map-tokens`), expanded only when nothing else is in context [verified: fetched, S1].
- Claude Code startup baseline: system prompt ~4.2k tokens, project CLAUDE.md ~1.8k, auto memory ~0.7k, skill descriptions ~0.45k — i.e., a few k tokens are spent on orientation before the first prompt; each file read adds ~1–2.4k [verified: fetched, S17].
- CLAUDE.md/AGENTS.md: **<200 lines** [verified: fetched, S15][S18]; OpenHands injected memory index: **~6,000 characters** [verified: fetched, S11].
- Subagent recon: explore with "tens of thousands of tokens or more" internally, **return only 1,000–2,000 tokens** [verified: fetched, S20]; Claude Code's own example: 9.9k tokens of subagent work → 420-token summary back [verified: fetched, S17].
- Hard caps for unattended work: `--max-turns`, `--max-budget-usd` [verified: fetched, S15]; OpenHands condenser triggers at a `max_size` event threshold [verified: fetched, S10].

**Verified stopping rules (concrete, quotable):**
1. **Recon ends when the plan is stateable without more reads.** Claude Code's workflow gates coding on an explicit plan: "Explicitly tell it not to code until you've confirmed its plan looks good" [verified: fetched, S19].
2. **The two-question test prunes the artifact, which ends the recon:** if the agent can find it in the code and would actually look, it doesn't belong in the note [verified: fetched, S15].
3. **Corrected-twice rule → reset, not extend:** "If you've corrected the same thing twice and it's still wrong, a third correction mostly adds to a conversation that already contains two failed attempts. `/clear` plus one new prompt that folds in what you learned works better almost every time" [verified: fetched, S15]; "Use the /clear command frequently between tasks to reset the context window" [verified: fetched, S19].
4. **Delegate, don't absorb:** when broad search is needed, spawn a subagent that "keeps the main conversation focused by summarizing results instead of dumping raw file contents" [verified: fetched, S23]; the main agent "never does work in parallel with the subtask agent, and the subtask agent is usually only tasked with answering a question, not writing any code… all the subagent's investigative work does not need to remain in the history of the main agent, allowing for longer traces before running out of context" [verified: fetched, S21].
5. **Compaction as the last-resort budget valve:** summarize the conversation when it nears the limit, preserving "architectural decisions, unresolved bugs, and implementation details while discarding redundant tool outputs", continuing "plus the five most recently accessed files" [verified: fetched, S20]; Claude Code re-injects CLAUDE.md from disk and re-reads up to 5 most-recently-modified files after compaction [verified: fetched, S17]. OpenHands does the same with `LLMSummarizingCondenser` (up to 2x per-turn cost reduction, "equivalent or better performance" on SWE tasks) [verified: fetched, S10].
6. **Context rot is the hard limit:** "as the number of tokens in the context window increases, the model's ability to accurately recall information from that context decreases… Context, therefore, must be treated as a finite resource with diminishing marginal returns" [verified: fetched, S20].

**What's changed (2025 → 2026):** "The context window is your main constraint, manage it aggressively" is listed under "What you can stop doing" — "Most current models have a 1M-token window and compaction happens on its own, so running out is rare. `/clear` between tasks is still worth doing, because a focused context gets you better answers and costs less" [verified: fetched, S15]. [inferred] For a homelab-sized repo the binding constraint on recon is therefore *time and attention*, not raw window capacity: the budget should be a small number of minutes/tool-calls plus a small note, not a token ceiling.

### Q5 — Failure modes: over-recon and under-recon

**Over-recon (verified evidence):**
- **Context bloat / context rot:** recall degrades with context length; "every new token introduced depletes[s] this budget" [verified: fetched, S20]. "During long sessions, Claude's context window can fill with irrelevant conversation, file contents, and commands. This can reduce performance and sometimes distract Claude" [verified: fetched, S19].
- **Cost and latency:** "This context gathering consumes time and tokens" [verified: fetched, S19]; Aider deliberately limits agentic behavior "to avoid long delays, high token costs and the need for users to repeatedly code review incorrect solutions" [verified: fetched, S3]; "Claude got it right, but it took more time, tokens, or permission prompts than the task was worth" is one of Claude Code's four named failure modes [verified: fetched, S15].
- **Analysis paralysis / dead ends:** "Without proper guidance, an agent can waste context by misusing tools, chasing dead-ends, or failing to identify key information" [verified: fetched, S20]; "Searching through many files generates a lot of context" — the reason Cursor built the Explore subagent [verified: fetched, S23]; "bloated tool sets that cover too much functionality or lead to ambiguous decision points" [verified: fetched, S20].
- **Stale/over-built orientation:** pre-computed embedding indexes go stale ("stale indexing" named as the issue just-in-time retrieval bypasses) [verified: fetched, S20]; over-long instruction files "consume more context and reduce adherence" [verified: fetched, S18].

**Under-recon (verified evidence):**
- **Confident wrong assumptions from missing non-repo knowledge:** "Claude built something different from what you had in mind, or it has to rediscover the same fact at the start of every session. It's missing information it can't get from reading the repo" [verified: fetched, S15].
- **Skipping orientation entirely:** "without them [explore + plan], Claude tends to jump straight to coding a solution" [verified: fetched, S19]; SWE-bench's core finding is that real issues require coordinating changes across multiple functions/classes/files — models that don't build that understanding fail (1.96% for the best model in 2023) [verified: fetched, S4].
- **Bad navigation interfaces:** the SWE-agent result shows that without a purpose-built ACI, agents can't reliably "navigate entire repositories" or "execute tests" — orientation failure is an interface failure, not just a model failure [verified: fetched, S5].
- **Conflicting implicit decisions (the multi-agent version of under-recon):** subagents given subtasks without full context "started building a background that looks like Super Mario Bros." — "actions carry implicit decisions, and conflicting decisions carry bad results" [verified: fetched, S21].
- **Speed cost of under-recon at runtime:** "runtime exploration is slower than retrieving pre-computed data" — skipping orientation means rediscovering facts on every task [verified: fetched, S20].

[inferred] The two failure modes are the same failure at different times: over-recon spends the context budget before the work starts; under-recon spends it (or worse, spends wrong edits) during the work. The verified mitigation is identical in both cases: a small, high-signal, persistent orientation artifact (the recon note) plus a hard budget on how much exploration leaks into the main context.

## Implications for the S2 codebase-recon build

Concrete design inputs for the S2 `codebase-recon` skill. Cite this section; every item is grounded in a verified source (S#) or flagged [inferred].

### 1. Recon steps (ordered, each with a done-criterion)

| Step | Action | Done when | Grounding |
|------|--------|-----------|-----------|
| 0 | **Consume existing recon** — read AGENTS.md / CLAUDE.md / `docs/llms.txt` (or repo docs index) / a prior task's recon note. Update only what's stale; never re-derive what's already written. | Existing artifact answers ≥ half of the six questions below | [S15][S18][S22][S24] |
| 1 | **What is this** — README → docs/ (list the tree; don't cat large files) | One-paragraph "what it is" is stateable | [S15][S19] |
| 2 | **Cheap whole-repo view** — directory tree + file types/LOC; symbol map (tree-sitter tags if available, else `git ls-files` + grep for definitions) capped at ~1k tokens equivalent | Map covers top-level layout + key symbols of likely-relevant modules | [S1][S2][S23] |
| 3 | **Build/install commands** — from package.json / pyproject / Makefile / compose files | Install + build commands found and dry-run-verified where cheap | [S19][S22] |
| 4 | **Test command** — find the framework + the *single-test* command; run one fast test to verify it works | A real test passes under the recorded command | [S15][S22][S3] |
| 5 | **Deploy path** — CI workflows, deploy scripts, project constraints (e.g., kanban project constraints) | Deploy path named (script/CI step + gate) | [S19][S22] |
| 6 | **Entry points** — main/app files, route handlers, CLI entry | Entry points listed for the subsystem the task touches | [S2][S23] |
| 7 | **Targeted reads** — read the files the task will touch; delegate any noisy broad search to a subagent that returns a ≤1–2k-token summary | The task's target files are identified and a plan is stateable **without more reads** | [S19][S20][S23] |
| 8 | **Write the recon note** (template below) | Note answers the six questions; every entry passes the two-question test | [S15][S18] |

The six questions (stop when all are answered or explicitly marked "could not verify"): **what is it / how do I build it / how do I test it (one test) / how does it deploy / where's the code for this task / what's misleading or non-obvious.** [inferred, synthesized from S15, S19, S22]

### 2. Recon note artifact (template)

Adapted from the verified CLAUDE.md/AGENTS.md templates [S15][S19][S22]:

```markdown
# Recon: <repo> — <date> — <task>
## What it is
<1–3 lines>
## Commands            <!-- concrete, verified by running where cheap -->
- Install: ...
- Build: ...
- Test (all / one): ...
- Lint/typecheck: ...
## Layout              <!-- top-level map only, 5–10 lines -->
## Entry points        <!-- for the subsystem this task touches -->
## Conventions         <!-- ONLY non-obvious: "Use X, never Y" -->
## Gotchas             <!-- misleading code, env vars, live-but-dead-looking dirs, deploy gates -->
## Deploy path         <!-- script/CI + gate -->
## Could not verify    <!-- honest gaps: what, why, what would be needed -->
```

Artifact rules (all verified): <200 lines [S15][S18]; headers + bullets, no dense prose [S18]; concrete verifiable commands, not adjectives ("Run `npm test` before committing", not "Test your changes") [S18]; only what fails the two-question test ("Could it find this by reading the code? Would it actually go and look?" — both yes → cut it) [S15]; procedures → skill, per-subsystem rules → note section scoped to that subsystem [S18]; add an entry when a fact has to be re-explained a second time [S18]. The `## Could not verify` section mirrors the S3 `qa-verify` "Could not verify" discipline (internal consistency, [inferred]).

### 3. Time-box rules

- **Budget:** ~10–15 minutes / ≤ ~30 tool calls for homelab-sized repos; recon note ≤ 200 lines; symbol map ≤ ~1k tokens equivalent. [inferred — scaled from the verified budgets: Aider 1k-token map [S1], <200-line instruction files [S15][S18], 1–2k-token subagent summaries [S20]]
- **Stop rules (in priority order):**
  1. Six questions answered (or gaps declared in `## Could not verify`) → stop. [inferred]
  2. Plan is stateable without more reads (the "not to write any code just yet" gate) → stop. [S19]
  3. Broad/noisy search needed → spawn a subagent with a ≤1–2k-token summary return instead of reading files in the main context. [S20][S23]
  4. Budget exhausted with gaps remaining → write the note with explicit gaps and proceed; declared under-recon beats unbounded over-recon. [inferred — consistent with S3's honesty rule and S20's "smallest set of high-signal tokens"]
  5. Same fact corrected twice across sessions → fold it into the durable artifact (AGENTS.md/recon note) and `/clear`-equivalent reset; don't keep re-deriving it. [S15][S18]
- **Context hygiene:** keep raw exploration out of the main session (subagent summaries); after a long recon, the note — not the transcript — is what downstream steps (DEV-1, DEV-2, implementation) consume. [S12][S17][S20][S21]

### 4. Repo-map approach for S2

- Default: **tree-sitter symbol map if a parser is available; else `git ls-files` + grep-based definition extraction**; budget ~1k tokens; elide bodies, keep signatures (Aider's format). [S1][S2]
- **Do not build an embedding index** for homelab repos: verified trade-offs favor grep + just-in-time reads (no stale indexing; deterministic; free) at this scale; Aider's SWE-bench SOTA used no RAG/vector search. [S3][S20][S23] [inferred: revisit only for a repo too large to map or for semantic queries grep can't express]
- The map is a **menu, not the work**: its job is to let the agent pick the 3–5 files to actually read [S2].

### 5. What S2 should NOT do (verified anti-patterns)

- Don't write architecture/file layout into the durable note — "Claude reads the repo itself. Only write down what isn't in there" [S15].
- Don't let recon grow unbounded to "be thorough" — context rot + cost [S20][S3][S15].
- Don't skip the plan gate to start editing faster — under-recon is the more expensive failure [S19][S4][S5].
- Don't dump raw search results into the main context — subagent summaries only [S23][S20].

## Open questions / gaps

1. **Cursor's old embedding-based codebase indexing** — the current docs only describe grep + Explore subagent (the old `codebase-indexing` URL now redirects to the docs root). [inferred] Cursor appears to have moved from embedding indexes to grep-first search, but the old design wasn't verified; a Wayback fetch of the old page would close this.
2. **SWE-bench full-text failure analysis** — only the abstract was verified (S4). The paper's qualitative failure categories (e.g., wrong-file edits, partial fixes) were not read; relevant to Q5 but not load-bearing for S2's design.
3. **Aider repo-map implementation details** — the docs verified the graph-ranking approach and the 1k-token budget, but exact algorithm parameters (e.g., PageRank specifics, `--map-format` options, lazy-map mode) were not verified. [inferred: not needed for S2, which will implement a simpler grep/tree-sitter map]
4. **No empirical "how much recon is enough" benchmark** — no fetched source measured recon time vs. success rate; all stopping rules are practitioner heuristics from docs/blogs. [inferred: S2's budget (10–15 min / ≤30 calls) is a starting hypothesis to tune on the first real Bluebovine/Invest Hub tasks]
5. **Devin/Cognition internals** — only the public blog principles (S21) were verified; Cognition's actual recon behavior in Devin is not public.
6. **Source dates** — agents.md and the Cursor docs pages carry no publication date (fetch date recorded instead); the Claude Code docs pages are continuously updated (best-practices lastModified 2026-11-21).
7. **Tooling gap** — MCP search/crawl tools unavailable in this session; URL discovery relied on known/guessed primary URLs + sitemap/llms.txt navigation rather than web search. All 24 cited sources were fetched and read directly, so no claim rests on a snippet.
