# MCP MySQL Server

Read-only MySQL database access with natural-language-to-SQL translation via LiteLLM. Runs as an MCP server over streamable-http transport.

## Tools

| Tool | Description | Parameters |
|---|---|---|
| `list_databases` | List user-accessible databases (excludes system DBs) | _(none)_ |
| `list_tables` | List tables in a given database | `database` (str) |
| `describe_table` | Show column definitions for a table | `database` (str), `table` (str) |
| `run_query` | Execute a read-only SELECT query | `database` (str), `sql` (str) |
| `explain_sql` | Translate natural language to SQL via LiteLLM | `database` (str), `natural_language` (str) |

## Configuration

| Environment Variable | Default | Description |
|---|---|---|
| `MYSQL_HOST` | `thor.local` | MySQL hostname |
| `MYSQL_PORT` | `3306` | MySQL port |
| `MYSQL_USER` | `ai` | MySQL username |
| `MYSQL_PASSWORD` | _(required)_ | MySQL password |
| `MYSQL_DATABASE` | _(none)_ | Default database |
| `LITELLM_API_BASE` | `http://litellm:4000` | LiteLLM API base URL |
| `LITELLM_API_KEY` | `sk-homelab` | LiteLLM API key |
| `LITELLM_MODEL` | `studio-gemma4-4b` | LiteLLM model for NL-to-SQL |
| `MCPS_HOST` | `0.0.0.0` | Bind address for streamable-http |

## Safety

- **Read-only enforcement**: Blocks INSERT, UPDATE, DELETE, DROP, ALTER, CREATE, TRUNCATE, REPLACE, GRANT, REVOKE, SET (case-insensitive regex)
- **Row limit**: Max 500 rows per query
- **Query timeout**: 30 seconds
- **System DB exclusion**: information_schema, mysql, performance_schema, sys excluded from listing
- **NL-to-SQL guard**: System prompt restricts output to SELECT-only queries; output is re-validated before execution

## Usage

### Docker Compose

Add to `compose/compose.mcp.yml`:

```yaml
mcp_mysql:
  build: ../mcp/servers/mysql
  ports:
    - "8000:8000"
  environment:
    MYSQL_HOST: thor.local
    MYSQL_PORT: "3306"
    MYSQL_USER: ai
    MYSQL_PASSWORD: ${MYSQL_PASSWORD}
    LITELLM_API_BASE: http://litellm:4000
    LITELLM_API_KEY: sk-homelab
    LITELLM_MODEL: studio-gemma4-4b
```

### Local Development

```bash
cd mcp/servers/mysql
pip install -e .
export MYSQL_PASSWORD=your_password
python server.py
```

### Python API

```python
from server import list_databases, list_tables, describe_table, run_query, explain_sql

# List databases
dbs = list_databases()
for db in dbs:
    print(db["name"])

# List tables in a database
tables = list_tables("investorhub")
for t in tables:
    print(t["name"])

# Describe a table
desc = describe_table("investorhub", "User")
for col in desc["columns"]:
    print(f"  {col['Field']} ({col['Type']})")

# Run a query
result = run_query("investorhub", "SELECT * FROM User LIMIT 10")
print(f"Found {result['count']} rows")

# NL-to-SQL
result = explain_sql("investorhub", "Show me all users with their email addresses")
print(f"Generated SQL: {result['sql']}")
```

## Architecture

This server is part of the Thor MCP server family. See [mcp/README.md](../README.md) for the overall architecture.
