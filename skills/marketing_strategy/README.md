# marketing_strategy — Go-To-Market (GTM) Strategy Skill

Generates a comprehensive, research-grounded Go-To-Market strategy for a product
or service. It researches the market (competitors, sizing, trends) via the
`mcp_search` MCP server, then synthesizes a full launch plan via the LLM and
saves it as a Markdown artifact.

Design adapted from [langchain-ai/deepagents `deploy-gtm-agent`](https://github.com/langchain-ai/deepagents/tree/main/examples/deploy-gtm-agent) —
the market-researcher subagent becomes the research phase, and the GTM
coordinator becomes the LLM synthesis phase.

## How it works

```
product brief ──► [Phase 1] Market research (mcp_search.search_web)
                        │  - competitors
                        │  - market size / TAM-SAM-SOM
                        │  - trends / buyer personas
                        ▼
                  [Phase 2] LLM synthesis (matrix-coder via LiteLLM)
                        │  Executive summary, market overview,
                        │  competitive landscape, personas,
                        │  value prop, pricing, channels,
                        │  30/60/90 launch plan, risks
                        ▼
                  [Phase 3] Save Markdown artifact
                        └─► /home/chuck/data/media/gtm_strategies/gtm_*.md
```

## Inputs

| Parameter            | Type    | Required | Description                                          |
|----------------------|---------|----------|------------------------------------------------------|
| `prompt`             | string  | **yes**  | Product/service brief to build the strategy for.     |
| `target_market`      | string  | no       | Target market/segment to focus on.                   |
| `competitors`        | string  | no       | Comma-separated known competitors.                   |
| `max_research_queries` | int   | no       | Max research web searches (1-8, default 4).         |

## Outputs

| Field             | Type     | Description                                   |
|-------------------|----------|-----------------------------------------------|
| `summary`         | string   | Short executive summary.                       |
| `report`          | string   | Full GTM strategy in Markdown.                 |
| `artifact_path`   | string   | Path to the saved `.md` artifact.              |
| `research_count`  | integer  | Number of unique research sources gathered.    |
| `model_alias`     | string   | LLM alias used.                                |

## Strategy sections produced

1. Executive Summary
2. Market Overview (TAM/SAM/SOM with methodology)
3. Competitive Landscape (comparison table + gaps)
4. Target Audience (2-3 buyer personas)
5. Value Proposition & Positioning
6. Pricing Strategy
7. Channel Strategy (ranked + sequencing)
8. Launch Plan (30/60/90-day)
9. Risks & Mitigations

## Usage

### Via the skill runner (n8n / MCP)

```
run_skill(name="marketing_strategy",
          prompt="AI home energy monitor that optimizes solar output",
          params={"competitors": "Tesla, Enphase", "target_market": "US residential"})
```

### Standalone CLI

```bash
# Dry run (prints the plan without calling services)
python3 skills/marketing_strategy/skill.py \
  --prompt "AI home energy monitor that optimizes solar output" \
  --competitors "Tesla, Enphase" --dry-run

# Full run
python3 skills/marketing_strategy/skill.py \
  --prompt "AI home energy monitor that optimizes solar output" \
  --competitors "Tesla, Enphase"
```

## Configuration

| Env var                          | Default                                 |
|----------------------------------|-----------------------------------------|
| `MARKETING_STRATEGY_MODEL_ALIAS` | `matrix-coder`                          |
| `MARKETING_STRATEGY_MAX_RUNTIME` | `300` (seconds)                         |
| `MARKETING_STRATEGY_ARTIFACT_DIR`| `/home/chuck/data/media/gtm_strategies` |
| `LITELLM_BASE_URL`               | `http://localhost:4000`                 |
| `LITELLM_API_KEY`                | (empty)                                 |

## Constraints

- Max runtime: 300 seconds.
- Read-only: no writes outside the artifact dir.
- All MCP/LLM calls go through LiteLLM — never direct MCP server access.
- Output format: Markdown.
- Clearly distinguishes hard data from estimates/assumptions.