"""
MySQL database layer for workflow run state persistence.

Uses `mysql.connector` (or `pymysql` as fallback) with raw SQL.
Tables are created automatically on first access via `ensure_tables()`.
"""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

# ---------------------------------------------------------------------------
# Connection helpers
# ---------------------------------------------------------------------------

_DB_CONFIG: dict[str, Any] | None = None


def _load_config() -> dict[str, Any]:
    global _DB_CONFIG
    if _DB_CONFIG is not None:
        return _DB_CONFIG

    _DB_CONFIG = {
        "host": os.getenv("MYSQL_DB_HOST", "host.docker.internal"),
        "port": int(os.getenv("MYSQL_DB_PORT", "3306")),
        "user": os.getenv("AI_DB_USER", "root"),
        "password": os.getenv("AI_DB_PASS", ""),
        "database": os.getenv("AI_DB_NAME", "ai_harness"),
        "charset": "utf8mb4",
        "autocommit": False,
    }
    return _DB_CONFIG


def _create_conn():
    """Create a MySQL connection using pymysql (our actual dependency)."""
    import pymysql

    return pymysql.connect(**_load_config())


@contextmanager
def get_cursor(dictionary=True):
    """Yield a cursor; auto-commits on success, rolls back on exception."""
    import pymysql

    conn = _create_conn()
    try:
        cursor_class = pymysql.cursors.DictCursor if dictionary else pymysql.cursors.Cursor
        cursor = conn.cursor(cursor=cursor_class)
        yield cursor
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()


# ---------------------------------------------------------------------------
# Schema initialization
# ---------------------------------------------------------------------------

_DDL_WORKFLOWS = """
CREATE TABLE IF NOT EXISTS workflows (
    workflow_id      CHAR(36)     NOT NULL PRIMARY KEY,
    name             VARCHAR(255) NOT NULL,
    description      TEXT,
    tags             JSON,
    steps            JSON         NOT NULL,
    created_at       TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at       TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""

_DDL_RUNS = """
CREATE TABLE IF NOT EXISTS workflow_runs (
    run_id           CHAR(36)     NOT NULL PRIMARY KEY,
    workflow_id      CHAR(36)     NOT NULL,
    status           VARCHAR(20)  NOT NULL DEFAULT 'pending',
    overrides        JSON,
    step_kwargs_overrides JSON,
    metadata         JSON,
    current_step     INT,         -- index of the step currently executing
    started_at       TIMESTAMP    NULL,
    finished_at      TIMESTAMP    NULL,
    created_at       TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at       TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_run_workflow (workflow_id),
    INDEX idx_run_status (status),
    CONSTRAINT fk_run_workflow
        FOREIGN KEY (workflow_id) REFERENCES workflows(workflow_id)
        ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""

_DDL_STEPS = """
CREATE TABLE IF NOT EXISTS workflow_steps (
    step_id          CHAR(36)     NOT NULL PRIMARY KEY,
    run_id           CHAR(36)     NOT NULL,
    step_index       INT          NOT NULL,
    name             VARCHAR(255) NOT NULL,
    status           VARCHAR(20)  NOT NULL DEFAULT 'pending',
    celery_task_id   CHAR(36),
    model            VARCHAR(128),
    input_payload    JSON,
    output           JSON,
    error            TEXT,
    retry_count      INT          NOT NULL DEFAULT 0,
    cost             DECIMAL(10,6) NULL,
    input_tokens     INT          NULL,
    output_tokens    INT          NULL,
    artifacts        JSON,
    started_at       TIMESTAMP    NULL,
    finished_at      TIMESTAMP    NULL,
    created_at       TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at       TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_step_run (run_id),
    INDEX idx_step_status (run_id, status),
    CONSTRAINT fk_step_run
        FOREIGN KEY (run_id) REFERENCES workflow_runs(run_id)
        ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""

_DDL_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_step_celery
    ON workflow_steps (celery_task_id);
"""


def ensure_tables():
    """Create the three tables and indexes if they do not exist yet."""
    with get_cursor() as cursor:
        cursor.execute(_DDL_WORKFLOWS)
        cursor.execute(_DDL_RUNS)
        cursor.execute(_DDL_STEPS)
        try:
            cursor.execute(_DDL_INDEXES)
        except Exception:
            # "CREATE INDEX IF NOT EXISTS" not supported on older MySQL;
            # benign — index may already exist or will be created next attempt.
            pass
