# business_analyst — Business/Product Data Analyst Skill

Answers natural-language questions against the existing MySQL databases by
translating the question to SQL, executing it, and synthesizing insights via
the LLM. Produces a Markdown report with the SQL, results, key insights,
follow-up suggestions, and suggested Grafana queries.

This is the "Business/Product Analyst" agent. It uses the existing databases
**as-is** — no new schema is designed.

## Available databases

| Database     | Domain        | Example tables                                        |
|--------------|---------------|-------------------------------------------------------|
| `investorhub`| Financial     | `Symbol`, `SymbolFundamentals`, `Position`, `Portfolio`, `DividendHistory`, `PriceHistory`, `IndexMembership` |
| `homelab`    | Operational   | `skill_jobs`, `workflows`, `workflow_runs`, `workflow_steps`, `checkpoints` |

If `database` is not specified, the skill auto-detects (prefers `investorhub`).

## How it works

```
question ──► [1] Resolve database (mcp_mysql.list_databases)
                │
                ▼
              [2] Schema overview (mcp_mysql.schema_overview)
                │
                ▼
              [3] NL->SQL + execute
                │     primary: mcp_mysql.nl_to_sql_then_run
                │     fallback: mcp_mysql.run_query (retry the SQL)
                │     fallback: mcp_mysql.explain_sql
                ▼
              [4] LLM insight synthesis (matrix-coder via LiteLLM)
                │     Key insights, interpretation, follow-ups,
                │     Grafana suggestions
                ▼
              [5] Save Markdown report
                └─► /home/chuck/data/media/analyses/analysis_*.md
```

## Inputs

| Parameter  | Type   | Required | Description                                          |
|------------|--------|----------|------------------------------------------------------|
| `prompt`   | string | **yes**  | Natural-language question to answer.                 |
| `database` | string | no       | Target database. Default: auto-detect.               |

## Outputs

| Field           | Type     | Description                                   |
|-----------------|----------|-----------------------------------------------|
| `summary`       | string   | Short summary of the analysis.                 |
| `report`        | string   | Full analysis report in Markdown.              |
| `sql`           | string   | The SQL query that was executed.               |
| `row_count`     | integer  | Number of result rows.                         |
| `rows`          | array    | Result rows (capped at 50).                    |
| `database`      | string   | The database queried.                          |
| `query_method`  | string   | Which mcp_mysql method produced the data.      |
| `query_error`   | string   | Query error, if any.                           |
| `artifact_path` | string   | Path to the saved `.md` artifact.              |
| `model_alias`   | string   | LLM alias used.                                |

## Report sections produced

1. **Query** — the SQL in a fenced block (+ any execution error).
2. **Results** — a Markdown table of the rows (truncated to 20).
3. **Key Insights** — 3-5 specific takeaways with numbers.
4. **Interpretation** — plain-English read of what the data means.
5. **Suggested Follow-ups** — 2-3 deeper questions.
6. **Grafana Suggestions** — 1-3 concrete panel/query ideas.

## Usage

### Via the skill runner (n8n / MCP)

```
run_skill(name="business_analyst",
          prompt="What are the top 5 stocks by market cap?",
          params={"database": "investorhub"})
```

### Standalone CLI

```bash
# Dry run
python3 skills/business_analyst/skill.py \
  --prompt "What are the top 5 stocks by market cap?" \
  --database investorhub --dry-run

# Full run (auto-detect database)
python3 skills/business_analyst/skill.py \
  --prompt "How many skill jobs ran in the last 7 days?" \
  --database homelab
```

## Configuration

| Env var                          | Default                             |
|----------------------------------|-------------------------------------|
| `BUSINESS_ANALYST_MODEL_ALIAS`   | `matrix-coder`                      |
| `BUSINESS_ANALYST_MAX_RUNTIME`   | `300` (seconds)                     |
| `BUSINESS_ANALYST_ARTIFACT_DIR`  | `/home/chuck/data/media/analyses`   |
| `LITELLM_BASE_URL`               | `http://localhost:4000`             |
| `LITELLM_API_KEY`                | (empty)                             |

## Note on full-table scans

The `mcp_mysql` server guards against full-table scans by default
(`BLOCK_FULL_TABLE_SCANS=true`). For a functional business analyst on this
small family dataset, `compose/compose.mcp.yml` sets `BLOCK_FULL_TABLE_SCANS=false`
so analytical queries can run. Other safety guards remain active:
`MAX_ROWS_EXAMINED`, `MAX_JOIN_TABLES`, a 500-row result cap, a 30s timeout,
and SELECT-only enforcement. **Restart the `mcp_mysql` container** after
changing this for it to take effect.

## Constraints

- Max runtime: 300 seconds.
- Read-only: only SELECT queries (enforced by mcp_mysql).
- All MCP/LLM calls go through LiteLLM — never direct MCP server access.
- Output format: Markdown.
- Uses existing databases as-is; no schema changes.