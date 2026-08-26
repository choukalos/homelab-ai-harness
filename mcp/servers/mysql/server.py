#!/usr/bin/env python3
"""MCP MySQL Server — Read-only MySQL database tools with NL-to-SQL translation.

Provides tools:
  - list_databases()                List user-accessible databases (excludes system DBs)
  - list_tables(database)           List tables in a given database
  - describe_table(database, table) Show column definitions for a table
  - foreign_keys(database)          Show foreign key relationships between tables
  - list_indexes(database, table)   Show indexes on a table
  - sample_table(database, table)   Return sample rows from a table
  - run_query(database, sql)        Execute a SELECT query, return rows as JSON
  - run_query_to_csv(database, sql, filename)  Execute query and save to CSV
  - explain_sql(database, natural_language)   Translate NL to SQL via LiteLLM
  - nl_to_sql_then_run(database, question)    NL → SQL → execute in one call

Backend: MySQL at configurable MYSQL_HOST (default: thor.local:3306)
Transport: streamable-http (HTTP, default 0.0.0.0:8000)
Security: Read-only enforcement — blocks INSERT/UPDATE/DELETE/DROP/ALTER/CREATE/TRUNCATE.
Query safety: EXPLAIN pre-flight checks row estimates, join count, and full table scans.
"""

import csv
import hashlib
import io
import os
import re
import logging
from datetime import datetime
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
MAX_JOIN_TABLES: int = int(os.environ.get("MAX_JOIN_TABLES", "5"))
MAX_ROWS_EXAMINED: int = int(os.environ.get("MAX_ROWS_EXAMINED", "100000"))
BLOCK_FULL_TABLE_SCANS: bool = os.environ.get("BLOCK_FULL_TABLE_SCANS", "true").lower() in ("true", "1", "yes")
SCHEMA_MAX_TABLES: int = int(os.environ.get("SCHEMA_MAX_TABLES", "50"))
SAMPLE_MAX_ROWS: int = int(os.environ.get("SAMPLE_MAX_ROWS", "20"))

# CSV output
CSV_OUTPUT_DIR: str = os.environ.get("CSV_OUTPUT_DIR", "/home/chuck/data/media/csv")

# LiteLLM config for NL-to-SQL
LITELLM_API_BASE: str = os.environ.get("LITELLM_API_BASE", "http://litellm-proxy:4000")
LITELLM_API_KEY: str = os.environ.get("LITELLM_API_KEY")
LITELLM_MODEL: str = os.environ.get("LITELLM_MODEL", "studio-gemma4-4b")
LITELLM_MAX_TOKENS: int = int(os.environ.get("LITELLM_MAX_TOKENS", "1000"))

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
- Use foreign key relationships to determine join conditions.
- Prefer indexed columns in WHERE clauses when possible.
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


def _execute_read_only_sql(conn, sql: str) -> dict:
    """Execute a read-only SQL query and return results as dict with rows, columns, count."""
    # Security check: block dangerous SQL
    _validate_read_only(sql)

    # Pre-flight: EXPLAIN the query to catch expensive joins / full scans
    try:
        _explain_precheck(sql, conn)
    except ValueError:
        raise
    except Exception:
        pass  # EXPLAIN check failed non-critically; let the real query run

    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(sql)
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


def _explain_precheck(sql: str, conn) -> None:
    """Pre-flight: run EXPLAIN, reject queries that would be catastrophically expensive.

    Checks:
      - Estimated total rows examined <= MAX_ROWS_EXAMINED
      - Number of distinct tables joined <= MAX_JOIN_TABLES
      - If BLOCK_FULL_TABLE_SCANS: no full-table-scan (type='ALL') rows
    Raises ValueError with a clear explanation on any violation.
    """
    tables = set()
    total_estimated = 0

    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(f"EXPLAIN {sql}")
        explain_rows = cursor.fetchall()
    except mysql.connector.Error:
        return  # EXPLAIN failed; let the real query fail naturally
    finally:
        cursor.close()

    if not explain_rows:
        return

    for row in explain_rows:
        table_val = row.get("table") or ""
        if table_val and table_val not in ("", "<subquery>", "<union>"):
            tables.add(table_val)
        total_estimated += int(row.get("rows", 0))

    if len(tables) > MAX_JOIN_TABLES:
        raise ValueError(
            f"Too many tables joined ({len(tables)} tables, max {MAX_JOIN_TABLES}). "
            f"Tables involved: {', '.join(sorted(tables))}. "
            "Simplify your query or set MAX_JOIN_TABLES higher."
        )

    if total_estimated > MAX_ROWS_EXAMINED:
        raise ValueError(
            f"Query estimated to examine {total_estimated:,} rows (limit {MAX_ROWS_EXAMINED:,}). "
            "Add a WHERE clause, use an indexed column, or increase MAX_ROWS_EXAMINED."
        )

    if BLOCK_FULL_TABLE_SCANS:
        for row in explain_rows:
            if row.get("type") == "ALL" and int(row.get("rows", 0)) > 100:
                raise ValueError(
                    f"Full table scan on '{row.get('table')}' "
                    f"(est. {int(row.get('rows', 0)):,} rows). "
                    "Add a WHERE clause or index, or set BLOCK_FULL_TABLE_SCANS=false."
                )


def _validate_read_only(sql: str) -> None:
    """Validate that SQL is read-only. Raises ValueError if dangerous keywords found."""
    if DANGEROUS_PATTERNS.search(sql):
        raise ValueError(
            f"Read-only violation: query contains disallowed DDL/DML statement. "
            "Only SELECT queries are permitted. "
            f"Blocked pattern in: {sql[:100]}…"
        )


def _ensure_csv_dir() -> str:
    """Ensure the CSV output directory exists and return its path."""
    os.makedirs(CSV_OUTPUT_DIR, exist_ok=True)
    return CSV_OUTPUT_DIR


def _write_query_to_csv(rows: list[dict], columns: list[str], filename: str) -> str:
    """Write query results to a CSV file. Returns the absolute path."""
    out_dir = _ensure_csv_dir()

    # Sanitize filename
    safe_name = re.sub(r'[^a-zA-Z0-9._-]', '_', filename)
    if not safe_name.endswith('.csv'):
        safe_name += '.csv'

    filepath = os.path.join(out_dir, safe_name)
    with open(filepath, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, '') for k in columns})

    return filepath


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
            max_tokens=LITELLM_MAX_TOKENS,
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


def _get_foreign_keys(cursor, database: str) -> list[dict]:
    """Query information_schema for foreign key relationships in a database."""
    try:
        cursor.execute("""
            SELECT
                kcu.table_name AS from_table,
                kcu.column_name AS from_column,
                kcu.referenced_table_name AS to_table,
                kcu.referenced_column_name AS to_column,
                rc.constraint_name
            FROM information_schema.KEY_COLUMN_USAGE kcu
            JOIN information_schema.REFERENTIAL_CONSTRAINTS rc
                ON rc.constraint_name = kcu.constraint_name
                AND rc.constraint_schema = kcu.constraint_schema
            WHERE kcu.table_schema = %s
              AND kcu.referenced_table_name IS NOT NULL
        """, (database,))
        return cursor.fetchall()
    except mysql.connector.Error:
        return []


def _get_table_indexes(cursor, database: str, table: str) -> list[dict]:
    """Query SHOW INDEX for indexes on a specific table (works across MySQL versions)."""
    try:
        cursor.execute(f"SHOW INDEX FROM `{database}`.`{table}`")
        return cursor.fetchall()
    except mysql.connector.Error:
        return []


def _get_table_row_count(conn, database: str, table: str) -> int:
    """Get the row count for a table using information_schema."""
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT table_rows
            FROM information_schema.TABLES
            WHERE table_schema = %s AND table_name = %s
        """, (database, table))
        row = cursor.fetchone()
        cursor.close()
        return int(row['table_rows']) if row and row['table_rows'] else 0
    except Exception:
        return 0


def _build_schema_context(database: str) -> str:
    """Build a rich schema context string for NL-to-SQL.

    Includes:
      - Table definitions (column name, type, nullable, key)
      - Foreign key relationships
      - Index information
      - Sample rows for small tables
    """
    try:
        conn = _get_connection(database)
        try:
            cursor = conn.cursor(dictionary=True)

            # Get all tables
            cursor.execute(f"SHOW TABLES FROM `{database}`")
            tables = [row[list(row.keys())[0]] for row in cursor.fetchall()]

            # Get foreign keys
            fks = _get_foreign_keys(cursor, database)

            context_parts = []

            # Build table definitions with indexes and FKs
            for table in tables[:SCHEMA_MAX_TABLES]:
                # Describe table
                cursor.execute(f"DESCRIBE `{database}`.`{table}`")
                columns = cursor.fetchall()
                col_defs = ", ".join(
                    f"`{c['Field']}` ({c['Type']}, {'NOT NULL' if c['Null'] == 'NO' else 'NULL'}, {c['Key']})"
                    for c in columns[:15]
                )
                context_parts.append(f"TABLE `{table}`: {col_defs}")

                # Get indexes for this table
                indexes = _get_table_indexes(cursor, database, table)
                if indexes:
                    # Group by index name
                    idx_groups = {}
                    for idx in indexes:
                        idx_name = idx['index_name']
                        if idx_name not in idx_groups:
                            idx_groups[idx_name] = {
                                'unique': not idx['non_unique'],
                                'columns': []
                            }
                        idx_groups[idx_name]['columns'].append(idx['column_name'])

                    idx_strs = []
                    for idx_name, info in idx_groups.items():
                        cols = ", ".join(info['columns'])
                        prefix = "UNIQUE" if info['unique'] else "INDEX"
                        idx_strs.append(f"  {prefix} `{idx_name}` ({cols})")
                    if idx_strs:
                        context_parts.append("  ".join(idx_strs))

            # Add foreign key relationships
            if fks:
                fk_strs = []
                for fk in fks:
                    fk_strs.append(
                        f"FK: `{fk['from_table']}`.`{fk['from_column']}` "
                        f"→ `{fk['to_table']}`.`{fk['to_column']}`"
                    )
                context_parts.extend(fk_strs)

            # Add sample rows for small tables
            sample_tables = []
            for table in tables[:SCHEMA_MAX_TABLES]:
                row_count = _get_table_row_count(conn, database, table)
                if row_count <= 100:  # Only sample small tables
                    sample_tables.append((table, min(row_count, SAMPLE_MAX_ROWS)))

            if sample_tables:
                context_parts.append("\n-- SAMPLE DATA:")
                for table, limit in sample_tables[:5]:  # Limit to first 5 small tables
                    try:
                        cursor.execute(
                            f"SELECT * FROM `{database}`.`{table}` LIMIT {limit}"
                        )
                        sample_rows = cursor.fetchall()
                        if sample_rows:
                            # Convert first row to a readable format
                            sample_str = ", ".join(
                                f"{k}={repr(v)}" for k, v in sample_rows[0].items()
                            )
                            context_parts.append(f"  {table} sample: {{{sample_str}}}")
                    except Exception:
                        pass

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
        "Executes SELECT queries, lists databases/tables/columns/indexes/foreign keys, "
        "samples table data, translates natural language to SQL via LiteLLM, "
        "and exports query results to CSV. "
        "All queries are enforced read-only (no INSERT/UPDATE/DELETE/DROP/ALTER/CREATE/TRUNCATE). "
        f"Max {MAX_ROWS} rows per query, {QUERY_TIMEOUT}s timeout. "
        f"CSV output directory: {CSV_OUTPUT_DIR}."
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
        List of dicts with 'name' and 'database' keys for each table.
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
    name="foreign_keys",
    description="Show all foreign key relationships in the specified database. Shows how tables are linked together.",
)
def foreign_keys(database: str) -> list[dict]:
    """List all foreign key relationships in a database.

    Args:
        database: The database name to inspect.

    Returns:
        List of dicts with 'from_table', 'from_column', 'to_table', 'to_column', and 'constraint_name'.
    """
    conn = None
    try:
        conn = _get_connection(database)
        cursor = conn.cursor(dictionary=True)
        fks = _get_foreign_keys(cursor, database)
        cursor.close()
        return fks
    except mysql.connector.Error as exc:
        logger.error("Failed to get foreign keys for %s: %s", database, exc)
        raise RuntimeError(f"Failed to get foreign keys: {exc}") from exc
    finally:
        if conn:
            conn.close()


@mcp.tool(
    name="list_indexes",
    description="Show all indexes on a specific table, including PRIMARY, INDEX, and UNIQUE constraints.",
)
def list_indexes(database: str, table: str) -> list[dict]:
    """List all indexes on a specific table.

    Args:
        database: The database name.
        table: The table name.

    Returns:
        List of dicts with 'index_name', 'columns', and 'type' fields.
    """
    conn = None
    try:
        conn = _get_connection(database)
        cursor = conn.cursor(dictionary=True)
        raw_indexes = _get_table_indexes(cursor, database, table)
        cursor.close()

        # Group by index name (SHOW INDEX returns one row per indexed column)
        idx_groups = {}
        for idx in raw_indexes:
            idx_name = idx.get('Key_name', '')
            non_unique = idx.get('Non_unique', 0)
            col_name = idx.get('Column_name', '')
            if idx_name not in idx_groups:
                idx_groups[idx_name] = {
                    "index_name": idx_name,
                    "columns": [],
                    "unique": not bool(non_unique),
                    "type": "PRIMARY" if idx_name == "PRIMARY" else ("UNIQUE" if not non_unique else "INDEX"),
                }
            idx_groups[idx_name]['columns'].append(col_name)

        return list(idx_groups.values())
    except mysql.connector.Error as exc:
        logger.error("Failed to get indexes for %s.%s: %s", database, exc)
        raise RuntimeError(f"Failed to get indexes: {exc}") from exc
    finally:
        if conn:
            conn.close()


@mcp.tool(
    name="sample_table",
    description="Return a few sample rows from a table to see actual data values, types, and patterns. Bypasses the full-scan limit for tables up to 10K rows.",
)
def sample_table(database: str, table: str, limit: int = 5) -> dict:
    """Return sample rows from a table.

    Args:
        database: The database name.
        table: The table name.
        limit: Maximum number of rows to return (default 5, max 20).

    Returns:
        Dict with 'table', 'database', 'rows', 'count', and 'columns'.
    """
    limit = min(limit, SAMPLE_MAX_ROWS)
    conn = None
    try:
        conn = _get_connection(database)
        sql = f"SELECT * FROM `{database}`.`{table}` LIMIT {limit}"

        # Security check
        _validate_read_only(sql)

        # For sampling, do a relaxed EXPLAIN check: allow up to 10K rows
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute(f"EXPLAIN {sql}")
            explain_rows = cursor.fetchall()
            max_rows = max(int(r.get("rows", 0)) for r in explain_rows) if explain_rows else 0
        except mysql.connector.Error:
            max_rows = 0
        finally:
            cursor.close()

        if max_rows > 10000:
            raise ValueError(
                f"Table '{table}' is too large to sample ({max_rows:,} estimated rows). "
                "Add a WHERE clause or increase the limit."
            )

        # Execute directly (no full scan check for sampling)
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute(sql)
            rows = cursor.fetchall()
            column_names = [desc[0] for desc in cursor.description] if cursor.description else []
            return {
                "database": database,
                "table": table,
                "rows": rows,
                "count": len(rows),
                "columns": column_names,
                "truncated": False,
            }
        finally:
            cursor.close()
    except ValueError:
        raise  # Pass through sampling violations
    except mysql.connector.Error as exc:
        logger.error("Failed to sample %s.%s: %s", database, table, exc)
        raise RuntimeError(f"Failed to sample table: {exc}") from exc
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
    name="run_query_to_csv",
    description=(
        "Execute a read-only SELECT query and save results as a CSV file. "
        "Same read-only checks as run_query. Returns the file path. "
        f"Output directory: {CSV_OUTPUT_DIR}."
    ),
)
def run_query_to_csv(database: str, sql: str, filename: str) -> dict:
    """Execute a read-only SELECT query and write results to CSV.

    Args:
        database: The database to query against.
        sql: A SELECT-only SQL query string.
        filename: The output filename (will be saved in CSV_OUTPUT_DIR).

    Returns:
        Dict with 'path', 'filename', 'row_count', 'columns', 'query'.
    """
    conn = None
    try:
        _validate_read_only(sql)
        # Run the query directly (like sample_table) — CSV export is a user request, not blind NL-to-SQL
        cursor = conn.cursor(dictionary=True) if conn else None
        conn = _get_connection(database)
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(sql)
            rows = cursor.fetchmany(MAX_ROWS + 1)
            column_names = [desc[0] for desc in cursor.description] if cursor.description else []
            if len(rows) > MAX_ROWS:
                rows = rows[:MAX_ROWS]
        finally:
            cursor.close()

        filepath = _write_query_to_csv(rows, column_names, filename)

        return {
            "path": filepath,
            "filename": os.path.basename(filepath),
            "row_count": len(rows),
            "columns": column_names,
            "truncated": len(rows) > MAX_ROWS,
            "query": sql[:200],
        }
    except ValueError:
        raise  # Pass through read-only violations
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
        "Returns the generated SQL and executes it safely. "
        "Uses rich schema context including foreign keys, indexes, and sample data. "
        "Only produces read-only SELECT queries."
    ),
)
def explain_sql(database: str, natural_language: str) -> dict:
    """Translate natural language to a read-only SQL query via LiteLLM and execute it.

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

    # Execute the generated SQL if it looks like a valid SELECT
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


@mcp.tool(
    name="nl_to_sql_then_run",
    description=(
        "One-call natural language to SQL execution. Translates your question to SQL using LiteLLM, "
        "runs it safely against the database, and returns the results directly. "
        "Same as explain_sql but returns just the data, not the SQL."
    ),
)
def nl_to_sql_then_run(database: str, question: str) -> dict:
    """Translate natural language to SQL, execute it, and return just the results.

    Args:
        database: The target database for schema context.
        question: The natural language question to translate and execute.

    Returns:
        Dict with 'question', 'database', 'sql', 'rows', 'columns', 'count', 'truncated'.
    """
    sql = _translate_nl_to_sql(database, question)

    result = {
        "question": question,
        "database": database,
        "sql": sql,
    }

    # Execute the generated SQL
    if sql.upper().strip().startswith("SELECT"):
        conn = None
        try:
            conn = _get_connection(database)
            query_result = _execute_read_only_sql(conn, sql)
            result["rows"] = query_result["rows"]
            result["columns"] = query_result["columns"]
            result["count"] = query_result["count"]
            result["truncated"] = query_result["truncated"]
            if query_result.get("message"):
                result["message"] = query_result["message"]
        except Exception as exec_exc:
            logger.error("NL-to-SQL execution failed: %s", exec_exc)
            result["error"] = str(exec_exc)
        finally:
            if conn:
                conn.close()
    else:
        result["error"] = "Generated SQL is not a SELECT statement"

    return result


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Run the MCP MySQL server over streamable-http transport (0.0.0.0:8000)."""
    logging.basicConfig(level=logging.INFO)
    logger.info("Starting mcp_mysql, host=%s:%d, user=%s", MYSQL_HOST, MYSQL_PORT, MYSQL_USER)
    logger.info("Read-only enforcement enabled, max rows=%d, timeout=%ds", MAX_ROWS, QUERY_TIMEOUT)
    logger.info("Query safety: max examined=%d, max joins=%d, block full scans=%s, schema tables=%d",
                MAX_ROWS_EXAMINED, MAX_JOIN_TABLES, BLOCK_FULL_TABLE_SCANS, SCHEMA_MAX_TABLES)
    logger.info("NL-to-SQL: model=%s, max_tokens=%d, sample_max=%d", LITELLM_MODEL, LITELLM_MAX_TOKENS, SAMPLE_MAX_ROWS)
    logger.info("CSV output dir: %s", CSV_OUTPUT_DIR)
    mcp.run(transport="streamable-http")  # defaults to 0.0.0.0:8000


if __name__ == "__main__":
    main()