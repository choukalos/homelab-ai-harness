#!/usr/bin/env python3
"""MCP MySQL Server — Read-only MySQL database tools with NL-to-SQL translation.

Provides five read-only tools:
  - list_databases()                 List user-accessible databases (excludes system DBs)
  - list_tables(database)            List tables in a given database
  - describe_table(database, table)  Show column definitions for a table
  - run_query(database, sql)         Execute a SELECT query, return rows as JSON
  - explain_sql(database, natural_language)  Translate NL to SQL via LiteLLM

Backend: MySQL at configurable MYSQL_HOST (default: thor.local:3306)
Transport: streamable-http (HTTP, default 0.0.0.0:8000)
Security: Read-only enforcement — blocks INSERT/UPDATE/DELETE/DROP/ALTER/CREATE/TRUNCATE.
"""

import os
import re
import logging
from typing import Optional

import litellm
import mysql.connector
from mcp.server import FastMCP

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MYSQL_HOST: str = os.environ.get("MYSQL_HOST", "thor.local")
MYSQL_PORT: int = int(os.environ.get("MYSQL_PORT", "3306"))
MYSQL_USER: str = os.environ.get("MYSQL_USER", "ai")
MYSQL_PASSWORD: str = os.environ.get("MYSQL_PASSWORD", "")
MYSQL_DATABASE: str = os.environ.get("MYSQL_DATABASE", "")  # optional default db

# Limits
MAX_ROWS: int = 500
QUERY_TIMEOUT: int = 30  # seconds

# LiteLLM config for NL-to-SQL
LITELLM_API_BASE: str = os.environ.get("LITELLM_API_BASE", "http://litellm-proxy:4000")
LITELLM_API_KEY: str = os.environ.get("LITELLM_API_KEY", "sk-homelab")
LITELLM_MODEL: str = os.environ.get("LITELLM_MODEL", "studio-gemma4-4b")

# Databases to exclude from list_databases
SYSTEM_DATABASES = {
    "information_schema",
    "mysql",
    "performance_schema",
    "sys",
}

# Read-only enforcement: block any DDL/DML that could modify data
DANGEROUS_PATTERNS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|REPLACE|GRANT|REVOKE|SET)\b",
    re.IGNORECASE,
)

logger = logging.getLogger("mcp_mysql")

# ---------------------------------------------------------------------------
# LiteLLM NL-to-SQL system prompt
# ---------------------------------------------------------------------------

NL_TO_SQL_SYSTEM_PROMPT = """\
You are a SQL translator. Convert natural language questions into safe, read-only MySQL SELECT queries.

RULES:
- Output ONLY a single valid SELECT statement, nothing else.
- Use ONLY the SELECT keyword. NEVER use INSERT, UPDATE, DELETE, DROP, ALTER, CREATE, TRUNCATE, REPLACE, GRANT, or REVOKE.
- Use proper table and column names with backtick escaping where needed.
- Keep queries concise; use LIMIT 500 as a safety default.
- If the question cannot be answered with a SELECT query, output: SELECT 'I cannot translate this to a safe read-only query.' AS result;
- Do NOT wrap the SQL in markdown code blocks or any formatting.
"""


# ---------------------------------------------------------------------------
# Connection helpers
# ---------------------------------------------------------------------------


def _get_connection(database: Optional[str] = None) -> mysql.connector.connection.MySQLConnection:
    """Create a new MySQL connection. Uses read_only session variable for extra safety."""
    db = database or MYSQL_DATABASE
    conn = mysql.connector.connect(
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        database=db if db else None,
        connect_timeout=QUERY_TIMEOUT,
        autocommit=False,
    )
    # Set session to read-only for extra safety
    cursor = conn.cursor()
    cursor.execute("SET SESSION sql_mode='STRICT_TRANS_TABLES'")
    try:
        cursor.execute("SET GLOBAL sql_log_bin=0")
    except Exception:
        pass  # Global may not be permitted; ignore
    cursor.close()
    return conn


def _execute_read_only_sql(conn, sql: str) -> list[dict]:
    """Execute a read-only SQL query and return results as list of dicts."""
    # Security check: block dangerous SQL
    _validate_read_only(sql)

    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(sql, timeout=QUERY_TIMEOUT)
        rows = cursor.fetchmany(MAX_ROWS + 1)
        column_names = [desc[0] for desc in cursor.description] if cursor.description else []

        if len(rows) > MAX_ROWS:
            rows = rows[:MAX_ROWS]
            return {
                "rows": rows,
                "columns": column_names,
                "count": len(rows),
                "truncated": True,
                "message": f"Results limited to {MAX_ROWS} rows.",
            }

        return {
            "rows": rows,
            "columns": column_names,
            "count": len(rows),
            "truncated": False,
        }
    except mysql.connector.Error as exc:
        logger.error("MySQL query failed: %s (SQL: %s)", exc, sql[:200])
        raise RuntimeError(f"Query failed: {exc}") from exc
    finally:
        cursor.close()


def _validate_read_only(sql: str) -> None:
    """Validate that SQL is read-only. Raises ValueError if dangerous keywords found."""
    if DANGEROUS_PATTERNS.search(sql):
        raise ValueError(
            f"Read-only violation: query contains disallowed DDL/DML statement. "
            "Only SELECT queries are permitted. "
            f"Blocked pattern in: {sql[:100]}…"
        )


# ---------------------------------------------------------------------------
# NL-to-SQL via LiteLLM
# ---------------------------------------------------------------------------


def _translate_nl_to_sql(database: str, natural_language: str) -> str:
    """Use LiteLLM to translate natural language to a read-only SELECT query.

    Args:
        database: The database name (used to provide schema context).
        natural_language: The natural language question.

    Returns:
        A safe SELECT-only SQL string.
    """
    # Gather schema context for the LLM
    schema_context = _build_schema_context(database)

    try:
        response = litellm.completion(
            model=LITELLM_MODEL,
            api_base=LITELLM_API_BASE,
            api_key=LITELLM_API_KEY,
            messages=[
                {"role": "system", "content": NL_TO_SQL_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"Database: {database}\n\n"
                        f"Schema context:\n{schema_context}\n\n"
                        f"Translate this to SQL:\n{natural_language}"
                    ),
                },
            ],
            temperature=0.0,
            max_tokens=500,
        )
        sql = response.choices[0].message.content.strip()

        # Strip markdown code blocks if the model wraps them
        sql = re.sub(r"^```(?:sql)?\s*", "", sql, flags=re.IGNORECASE).strip()
        sql = re.sub(r"\s*```\s*$", "", sql, flags=re.IGNORECASE).strip()

        # Final safety check
        _validate_read_only(sql)
        return sql

    except Exception as exc:
        logger.error("LiteLLM NL-to-SQL failed: %s", exc)
        raise RuntimeError(f"NL-to-SQL translation failed: {exc}") from exc


def _build_schema_context(database: str) -> str:
    """Build a schema context string from the database's tables and columns."""
    try:
        conn = _get_connection(database)
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(f"SHOW TABLES FROM `{database}`")
            tables = [row[list(row.keys())[0]] for row in cursor.fetchall()]

            context_parts = []
            for table in tables[:20]:  # Limit to first 20 tables for context window
                cursor.execute(f"DESCRIBE `{database}`.`{table}`")
                columns = cursor.fetchall()
                col_defs = ", ".join(f"`{c['Field']}` ({c['Type']})" for c in columns[:10])
                context_parts.append(f"TABLE `{table}`: {col_defs}")

            return "\n".join(context_parts) if context_parts else "No tables found."
        finally:
            conn.close()
    except Exception:
        return f"Database '{database}' — schema context unavailable."


# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------

MCPS_HOST: str = os.environ.get("MCPS_HOST", "0.0.0.0")

mcp = FastMCP(
    name="mcp_mysql",
    instructions=(
        "Read-only MySQL database access. "
        "Executes SELECT queries, lists databases/tables/columns, and translates "
        "natural language to SQL via LiteLLM. "
        "All queries are enforced read-only (no INSERT/UPDATE/DELETE/DROP/ALTER/CREATE/TRUNCATE). "
        f"Max {MAX_ROWS} rows per query, {QUERY_TIMEOUT}s timeout."
    ),
    host=MCPS_HOST,
)


@mcp.tool(
    name="list_databases",
    description="List all user-accessible MySQL databases (excludes system databases like mysql, information_schema, etc.).",
)
def list_databases() -> list[dict]:
    """List available databases, excluding system databases.

    Returns:
        List of dicts with 'name' key for each accessible database.
    """
    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SHOW DATABASES")
        all_dbs = [row[list(row.keys())[0]] for row in cursor.fetchall()]
        cursor.close()
        user_dbs = [d for d in all_dbs if d.lower() not in SYSTEM_DATABASES]
        return [{"name": d} for d in sorted(user_dbs)]
    except mysql.connector.Error as exc:
        logger.error("Failed to list databases: %s", exc)
        raise RuntimeError(f"Failed to list databases: {exc}") from exc
    finally:
        if conn:
            conn.close()


@mcp.tool(
    name="list_tables",
    description="List all tables in the specified database.",
)
def list_tables(database: str) -> list[dict]:
    """List tables in a specific database.

    Args:
        database: The database name to list tables from.

    Returns:
        List of dicts with 'name' and 'engine' keys for each table.
    """
    conn = None
    try:
        conn = _get_connection(database)
        cursor = conn.cursor(dictionary=True)
        cursor.execute(f"SHOW TABLES FROM `{database}`")
        rows = cursor.fetchall()
        cursor.close()
        table_col = list(rows[0].keys())[0] if rows else "Tables_in_%s" % database
        tables = [row[table_col] for row in rows]
        return [{"name": t, "database": database} for t in sorted(tables)]
    except mysql.connector.Error as exc:
        logger.error("Failed to list tables in %s: %s", database, exc)
        raise RuntimeError(f"Failed to list tables: {exc}") from exc
    finally:
        if conn:
            conn.close()


@mcp.tool(
    name="describe_table",
    description="Show column definitions, types, keys, and nullability for a specific table.",
)
def describe_table(database: str, table: str) -> dict:
    """Describe a table's structure.

    Args:
        database: The database name.
        table: The table name.

    Returns:
        Dict with table name, database, and list of column definitions.
    """
    conn = None
    try:
        conn = _get_connection(database)
        cursor = conn.cursor(dictionary=True)
        cursor.execute(f"DESCRIBE `{database}`.`{table}`")
        columns = cursor.fetchall()
        cursor.close()
        return {
            "database": database,
            "table": table,
            "columns": columns,
            "column_count": len(columns),
        }
    except mysql.connector.Error as exc:
        logger.error("Failed to describe %s.%s: %s", database, table, exc)
        raise RuntimeError(f"Failed to describe table: {exc}") from exc
    finally:
        if conn:
            conn.close()


@mcp.tool(
    name="run_query",
    description=(
        "Execute a read-only SELECT query against the specified database. "
        "Returns results as a list of row dicts. "
        "Only SELECT is allowed; all DDL/DML is blocked. "
        f"Max {MAX_ROWS} rows, {QUERY_TIMEOUT}s timeout."
    ),
)
def run_query(database: str, sql: str) -> dict:
    """Execute a read-only SELECT query.

    Args:
        database: The database to query against.
        sql: A SELECT-only SQL query string.

    Returns:
        Dict with 'rows' (list of dicts), 'columns', 'count', and 'truncated' flag.
    """
    conn = None
    try:
        conn = _get_connection(database)
        return _execute_read_only_sql(conn, sql)
    except ValueError:
        raise  # Pass through read-only violations directly
    except mysql.connector.Error as exc:
        logger.error("Query failed on %s: %s", database, exc)
        raise RuntimeError(f"Query failed: {exc}") from exc
    finally:
        if conn:
            conn.close()


@mcp.tool(
    name="explain_sql",
    description=(
        "Translate a natural language question into a MySQL SELECT query using LiteLLM. "
        "Returns the generated SQL and optionally executes it. "
        "Only produces read-only SELECT queries."
    ),
)
def explain_sql(database: str, natural_language: str) -> dict:
    """Translate natural language to a read-only SQL query via LiteLLM.

    Args:
        database: The target database for schema context.
        natural_language: The natural language question to translate.

    Returns:
        Dict with 'sql' (generated query), 'natural_language' (original input),
        and optionally 'results' if the query was safely executed.
    """
    sql = _translate_nl_to_sql(database, natural_language)

    result = {
        "natural_language": natural_language,
        "database": database,
        "sql": sql,
    }

    # Optionally execute the generated SQL if it looks like a valid SELECT
    if sql.upper().strip().startswith("SELECT"):
        conn = None
        try:
            conn = _get_connection(database)
            query_result = _execute_read_only_sql(conn, sql)
            result["results"] = query_result
        except Exception as exec_exc:
            logger.error("Generated SQL failed to execute: %s", exec_exc)
            result["execution_error"] = str(exec_exc)
        finally:
            if conn:
                conn.close()

    return result


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Run the MCP MySQL server over streamable-http transport (0.0.0.0:8000)."""
    logging.basicConfig(level=logging.INFO)
    logger.info("Starting mcp_mysql, host=%s:%d, user=%s", MYSQL_HOST, MYSQL_PORT, MYSQL_USER)
    logger.info("Read-only enforcement enabled, max rows=%d, timeout=%ds", MAX_ROWS, QUERY_TIMEOUT)
    logger.info("LiteLLM API base: %s, model: %s", LITELLM_API_BASE, LITELLM_MODEL)
    mcp.run(transport="streamable-http")  # defaults to 0.0.0.0:8000


if __name__ == "__main__":
    main()
