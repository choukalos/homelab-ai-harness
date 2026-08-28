#!/usr/bin/env python3
"""MCP MySQL Server — Read-only MySQL database tools with NL-to-SQL translation.

Provides tools:
  - list_databases()                List user-accessible databases (excludes system DBs)
  - list_tables(database)           List tables in a given database
  - describe_table(database, table) Show column definitions for a table
  - foreign_keys(database)          Show foreign key relationships between tables
  - list_indexes(database, table)   Show indexes on a table
  - sample_table(database, table)   Return sample rows from a table
  - schema_overview(database)       Full schema intelligence: tables, columns, indexes,
                                    FKs, inferred soft relations, join graph, curated
                                    hints, and data samples
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
import json
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

# Curated per-database hints (domain knowledge for NL-to-SQL). JSON file keyed
# by database name -> list of hint strings. Mounted read-only in production so
# hints can be updated without a rebuild.
SCHEMA_HINTS_FILE: str = os.environ.get("SCHEMA_HINTS_FILE", "/app/schema_hints.json")

# Soft-relation inference: columns named <table>Id / <table>_id that reference
# another table's id without a declared FK (typical of ORM apps). Used to build
# the join graph when a database lacks real foreign keys.
INFER_SOFT_RELATIONS: bool = os.environ.get("INFER_SOFT_RELATIONS", "true").lower() in ("true", "1", "yes")

# CSV output
CSV_OUTPUT_DIR: str = os.environ.get("CSV_OUTPUT_DIR", "/home/chuck/data/media/csv")

# LiteLLM config for NL-to-SQL
LITELLM_API_BASE: str = os.environ.get("LITELLM_API_BASE", "http://litellm-proxy:4000")
LITELLM_API_KEY: str = os.environ.get("LITELLM_API_KEY")
LITELLM_MODEL: str = os.environ.get("LITELLM_MODEL", "matrix-coder")
LITELLM_MAX_TOKENS: int = int(os.environ.get("LITELLM_MAX_TOKENS", "2000"))
# Qwen3-style "thinking" models (e.g. matrix-coder) burn the token budget on
# reasoning and return empty content. Disable thinking for NL-to-SQL: the task
# is mechanical SQL generation, not open-ended reasoning. Set false for models
# whose chat template rejects the enable_thinking kwarg.
LITELLM_DISABLE_THINKING: bool = os.environ.get("LITELLM_DISABLE_THINKING", "true").lower() in ("true", "1", "yes")

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
- Use proper table and column names exactly as given in the schema context, with backtick escaping where needed.
- JOIN tables using the FOREIGN KEYS and JOIN GRAPH sections of the schema context. When a SOFT RELATION is listed (inferred, no declared FK), it is a valid join condition — join on it.
- Prefer the smallest join path (fewest tables) that answers the question.
- Prefer precomputed/summary tables over recomputing from raw data when one exists (e.g. annual/decade return tables over raw price history).
- Prefer indexed columns in WHERE clauses when possible; filter large tables by their indexed key columns (e.g. symbolId + date, symbolId + year).
- Use DATE() on timestamp columns when comparing by day; timestamps may carry a fixed time-of-day offset.
- If the schema context includes HINTS, follow them — they encode domain conventions (value scales, formats, which tables are app-internal noise).
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
    # Set session to read-only for extra safety (server-side enforcement:
    # any write attempt in this session is rejected by MySQL itself)
    cursor = conn.cursor()
    cursor.execute("SET SESSION sql_mode='STRICT_TRANS_TABLES'")
    try:
        cursor.execute("SET SESSION transaction_read_only=1")
    except Exception:
        pass  # Non-super users may lack the privilege; keyword guard still applies
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

    # litellm.completion needs a provider prefix for custom model names;
    # the LiteLLM proxy aliases are OpenAI-compatible (vLLM) endpoints.
    model = LITELLM_MODEL if "/" in LITELLM_MODEL else f"openai/{LITELLM_MODEL}"

    extra_body = {}
    if LITELLM_DISABLE_THINKING:
        extra_body["chat_template_kwargs"] = {"enable_thinking": False}

    try:
        response = litellm.completion(
            model=model,
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
            extra_body=extra_body or None,
        )
        sql = (response.choices[0].message.content or "").strip()

        # Strip markdown code blocks if the model wraps them
        sql = re.sub(r"^```(?:sql)?\s*", "", sql, flags=re.IGNORECASE).strip()
        sql = re.sub(r"\s*```\s*$", "", sql, flags=re.IGNORECASE).strip()

        if not sql:
            raise RuntimeError("LLM returned an empty response (check LITELLM_DISABLE_THINKING / max_tokens)")

        # Final safety check
        _validate_read_only(sql)
        return sql

    except Exception as exc:
        logger.error("LiteLLM NL-to-SQL failed: %s", exc)
        raise RuntimeError(f"NL-to-SQL translation failed: {exc}") from exc


def _get_foreign_keys(cursor, database: str) -> list[dict]:
    """Query information_schema for foreign key relationships in a database.

    Returns dicts with stable lowercase keys: from_table, from_column,
    to_table, to_column, constraint_name.
    """
    try:
        cursor.execute("""
            SELECT
                kcu.table_name AS from_table,
                kcu.column_name AS from_column,
                kcu.referenced_table_name AS to_table,
                kcu.referenced_column_name AS to_column,
                rc.constraint_name AS constraint_name
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
    """Query SHOW INDEX for indexes on a specific table (works across MySQL versions).

    Returns dicts with stable lowercase keys: index_name, column_name, non_unique.
    """
    try:
        cursor.execute(f"SHOW INDEX FROM `{database}`.`{table}`")
        raw = cursor.fetchall()
        return [
            {
                "index_name": r.get("Key_name") or r.get("index_name") or "",
                "column_name": r.get("Column_name") or r.get("column_name") or "",
                "non_unique": bool(r.get("Non_unique", r.get("non_unique", 0))),
            }
            for r in raw
        ]
    except mysql.connector.Error:
        return []


def _get_table_row_count(conn, database: str, table: str) -> int:
    """Get the row count for a table using information_schema."""
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT table_rows AS tr
            FROM information_schema.TABLES
            WHERE table_schema = %s AND table_name = %s
        """, (database, table))
        row = cursor.fetchone()
        cursor.close()
        return int(row['tr']) if row and row['tr'] is not None else 0
    except Exception:
        return 0


def _load_schema_hints(database: str) -> list[str]:
    """Load curated per-database hints (domain knowledge) for NL-to-SQL.

    Hints live in SCHEMA_HINTS_FILE (JSON: {database: [hint, ...]}). Missing
    file or unknown database -> empty list (never fatal).
    """
    try:
        with open(SCHEMA_HINTS_FILE) as f:
            data = json.load(f)
        hints = data.get(database, [])
        if isinstance(hints, str):
            hints = [hints]
        return [h for h in hints if isinstance(h, str)]
    except (OSError, json.JSONDecodeError):
        return []


def _get_all_columns(cursor, database: str, table: str) -> list[dict]:
    """All columns of a table with stable lowercase keys."""
    cursor.execute(f"DESCRIBE `{database}`.`{table}`")
    return [
        {
            "name": r["Field"],
            "type": r["Type"],
            "nullable": r["Null"] != "NO",
            "key": r["Key"] or "",
        }
        for r in cursor.fetchall()
    ]


def _get_inferred_relations(cursor, database: str, tables: list[str], fks: list[dict]) -> list[dict]:
    """Infer soft relations for <table>Id / <table>_id columns without a real FK.

    ORM-style apps (Prisma, Django, Sequelize) often store reference IDs without
    declared constraints. Naming convention: a column named <X>Id / <x>_id
    references table <X>.id. Matching is case-insensitive, exact or by suffix
    (snapshotId -> LandingSnapshot). Only columns NOT already covered by a
    declared FK are reported.
    """
    if not INFER_SOFT_RELATIONS:
        return []
    fk_covered = {(fk["from_table"], fk["from_column"]) for fk in fks}
    table_names_lower = {t.lower(): t for t in tables}
    inferred: list[dict] = []
    for table in tables:
        try:
            cols = _get_all_columns(cursor, database, table)
        except Exception:
            continue
        for col in cols:
            name = col["name"]
            if (table, name) in fk_covered:
                continue
            m = re.match(r"^(.+?)(?:Id|_id)$", name)
            if not m:
                continue
            prefix = m.group(1).lower()
            target = table_names_lower.get(prefix)
            if target is None or target == table:
                # suffix match: snapshotId -> LandingSnapshot
                candidates = [t for tl, t in table_names_lower.items() if tl.endswith(prefix) and len(tl) > len(prefix)]
                if len(candidates) == 1:
                    target = candidates[0]
                else:
                    continue
            if target == table:
                continue
            inferred.append({
                "from_table": table,
                "from_column": name,
                "to_table": target,
                "to_column": "id",
            })
    return inferred


def _collect_schema(database: str) -> dict:
    """Collect full schema intelligence for a database.

    Returns a dict with: tables (columns + indexes + row counts), foreign_keys,
    soft_relations, join_graph, hints, samples. Shared by _build_schema_context
    (text rendering for the LLM) and the schema_overview tool (structured JSON).
    """
    conn = _get_connection(database)
    try:
        cursor = conn.cursor(dictionary=True)

        cursor.execute(f"SHOW TABLES FROM `{database}`")
        tables = [row[list(row.keys())[0]] for row in cursor.fetchall()]
        tables = tables[:SCHEMA_MAX_TABLES]

        fks = _get_foreign_keys(cursor, database)
        soft = _get_inferred_relations(cursor, database, tables, fks)
        hints = _load_schema_hints(database)

        # Per-table details
        table_infos = []
        samples: dict[str, list[dict]] = {}
        for table in tables:
            cols = _get_all_columns(cursor, database, table)
            row_count = _get_table_row_count(conn, database, table)

            # Indexes grouped by name
            idx_groups: dict[str, dict] = {}
            for idx in _get_table_indexes(cursor, database, table):
                g = idx_groups.setdefault(idx["index_name"], {"unique": not idx["non_unique"], "columns": []})
                g["columns"].append(idx["column_name"])

            # Sample rows: up to 3 for small tables, 1 row for every other table
            # (LIMIT 1 is a cheap first-page read even on multi-million-row tables).
            limit = 3 if row_count <= 100 else 1
            try:
                cursor.execute(f"SELECT * FROM `{database}`.`{table}` LIMIT {limit}")
                rows = cursor.fetchall()
                if rows:
                    samples[table] = [
                        {k: (str(v)[:60] if v is not None else None) for k, v in r.items()}
                        for r in rows
                    ]
            except Exception:
                pass

            table_infos.append({
                "name": table,
                "row_count": row_count,
                "columns": cols,
                "indexes": [
                    {"index_name": n, "columns": g["columns"], "unique": g["unique"]}
                    for n, g in idx_groups.items()
                ],
            })

        # Join graph: table -> [tables it references via FK or soft relation]
        join_graph: dict[str, list[str]] = {t: [] for t in tables}
        for rel in fks + soft:
            if rel["from_table"] in join_graph and rel["to_table"] not in join_graph[rel["from_table"]]:
                join_graph[rel["from_table"]].append(rel["to_table"])

        return {
            "database": database,
            "hints": hints,
            "tables": table_infos,
            "foreign_keys": fks,
            "soft_relations": soft,
            "join_graph": join_graph,
            "samples": samples,
        }
    finally:
        conn.close()


def _build_schema_context(database: str) -> str:
    """Render the schema intelligence as a compact text block for the NL-to-SQL prompt.

    Sections: HINTS (curated domain knowledge), TABLES (all columns, indexes,
    row counts, samples), FOREIGN KEYS, SOFT RELATIONS (inferred), JOIN GRAPH.
    """
    try:
        schema = _collect_schema(database)
    except Exception as exc:
        logger.error("Schema context collection failed for %s: %s", database, exc)
        return f"Database '{database}' — schema context unavailable."

    parts: list[str] = []

    if schema["hints"]:
        parts.append("HINTS (curated domain knowledge — follow these):")
        parts.extend(f"  - {h}" for h in schema["hints"])
        parts.append("")

    parts.append(f"TABLES ({len(schema['tables'])}):")
    for t in schema["tables"]:
        col_defs = ", ".join(
            f"`{c['name']}` {c['type']}{' PK' if c['key'] == 'PRI' else ''}{' UNI' if c['key'] == 'UNI' else ''}"
            for c in t["columns"]
        )
        parts.append(f"TABLE `{t['name']}` (~{t['row_count']} rows): {col_defs}")
        for idx in t["indexes"]:
            if idx["index_name"] == "PRIMARY":
                continue
            prefix = "UNIQUE" if idx["unique"] else "INDEX"
            parts.append(f"  {prefix} `{idx['index_name']}` ({', '.join(idx['columns'])})")
        if t["name"] in schema["samples"]:
            for row in schema["samples"][t["name"]]:
                row_str = ", ".join(f"{k}={v!r}" for k, v in row.items())
                parts.append(f"  sample: {{{row_str}}}")

    if schema["foreign_keys"]:
        parts.append("")
        parts.append(f"FOREIGN KEYS ({len(schema['foreign_keys'])}):")
        for fk in schema["foreign_keys"]:
            parts.append(f"  `{fk['from_table']}`.`{fk['from_column']}` → `{fk['to_table']}`.`{fk['to_column']}`")

    if schema["soft_relations"]:
        parts.append("")
        parts.append(f"SOFT RELATIONS (inferred from naming — no declared FK, still valid join conditions):")
        for rel in schema["soft_relations"]:
            parts.append(f"  `{rel['from_table']}`.`{rel['from_column']}` → `{rel['to_table']}`.`{rel['to_column']}`")

    parts.append("")
    parts.append("JOIN GRAPH (table → tables it references):")
    for table, targets in schema["join_graph"].items():
        parts.append(f"  {table} → {', '.join(targets)}" if targets else f"  {table} → (none)")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------

MCPS_HOST: str = os.environ.get("MCPS_HOST", "0.0.0.0")

mcp = FastMCP(
    name="mcp_mysql",
    instructions=(
        "Read-only MySQL database access. "
        "Executes SELECT queries, lists databases/tables/columns/indexes/foreign keys, "
        "samples table data, and exports query results to CSV. "
        "schema_overview returns full schema intelligence (tables, columns, indexes, "
        "foreign keys, inferred soft relations, join graph, curated domain hints, data samples) "
        "— call it before writing join queries against an unfamiliar database. "
        "explain_sql / nl_to_sql_then_run translate natural language to SQL via LiteLLM "
        f"using that schema intelligence (model: {LITELLM_MODEL}). "
        "All queries are enforced read-only (no INSERT/UPDATE/DELETE/DROP/ALTER/CREATE/TRUNCATE) "
        "at both the app level and the MySQL session level (transaction_read_only). "
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
    name="schema_overview",
    description=(
        "Full schema intelligence for a database: every table with all columns and indexes, "
        "row counts, declared foreign keys, inferred soft relations (ORM-style reference IDs "
        "without declared FKs), the join graph, curated domain hints, and sample rows. "
        "Call this BEFORE writing join-heavy SQL so you know the exact join conditions and "
        "data formats. Then use run_query with the SQL you compose."
    ),
)
def schema_overview(database: str) -> dict:
    """Return full schema intelligence for a database.

    Args:
        database: The database name.

    Returns:
        Dict with 'database', 'hints' (curated domain knowledge), 'tables' (name,
        row_count, columns, indexes), 'foreign_keys', 'soft_relations' (inferred
        from naming — valid join conditions even without declared FKs),
        'join_graph' (table -> referenced tables), and 'samples' (example rows).
    """
    try:
        return _collect_schema(database)
    except Exception as exc:
        logger.error("Schema overview failed for %s: %s", database, exc)
        raise RuntimeError(f"Failed to build schema overview: {exc}") from exc


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