#!/usr/bin/env python3
"""
recent_activity skill — distill each user's recent activity into durable facts.

Purpose:
  Answer "what have I been doing recently?" consistently on every surface.
  For each known user, gather recent CONVERSATION activity with the assistant
  (skill jobs + recently stored Mem0 facts), plus GitHub events ONLY for users
  with a known GitHub identity (config github_users + GITHUB_ACCESS_TOKEN —
  users without one, e.g. dylan today, get conversation-only summaries).
  Distill via LLM into a dated "recent activity" summary and write it:
    (a) as a fact to kb_user (mcp_knowledge.kb_add_fact) — durable, KB-searchable
    (b) to Mem0 for that user (source="scheduled") — memory-searchable

Runs in-process inside skill-runner (importlib), so it uses the job's
LiteLLM client for LLM + MCP and the in-process memory interface directly.

Workflow (per user):
  1. Collect inputs within the lookback window (`days`, default 7):
       - skill_jobs (MySQL durable index, JSON user_id filter)
       - recent Mem0 memories (in-process interface.list_memories)
       - GitHub public events (if user has a known GitHub identity + token)
  2. Skip users with no inputs (no LLM call, no writes).
  3. Distill via LLM into 5-10 grouped bullets.
  4. Write the dated summary to kb_user + Mem0 (both best-effort, non-fatal).
  5. Save the full per-user report as an artifact.

Constraints:
  - Max runtime: 240 seconds.
  - Per-user isolation: a user's summary only uses that user's inputs.
  - GitHub is opt-in per user (known identity only) — no scanning of
    accounts whose identity/credentials we don't have.
  - Writes are non-fatal: a failed KB or Mem0 write never fails the job.
"""

import json
import logging
import os
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("skill.recent_activity")

# ---------------------------------------------------------------------------
# Configuration (env + skill.yml config)
# ---------------------------------------------------------------------------

GITHUB_TOKEN = os.environ.get("GITHUB_ACCESS_TOKEN", "")
# user_id -> GitHub login. ONLY users with a known identity are scanned.
GITHUB_USERS: dict[str, str] = {
    "chuck": os.environ.get("GITHUB_USER_CHUCK", "choukalos"),
    # Dylan onboarding (memory_todo 2b): empty until his login is set in
    # .env (GITHUB_USER_DYLAN) — empty login is skipped by the sweep.
    "dylan": os.environ.get("GITHUB_USER_DYLAN", ""),
}
KB_NAME = os.environ.get("RECENT_ACTIVITY_KB", "user")  # kb_user collection
MAX_JOBS = int(os.environ.get("RECENT_ACTIVITY_MAX_JOBS", "40"))
MAX_MEMORIES = int(os.environ.get("RECENT_ACTIVITY_MAX_MEMORIES", "25"))
MAX_GITHUB_EVENTS = int(os.environ.get("RECENT_ACTIVITY_MAX_GITHUB", "30"))
ARTIFACT_DIR = Path(
    os.environ.get(
        "RECENT_ACTIVITY_ARTIFACT_DIR", "/home/chuck/data/media/homelab_reports"
    )
)

MODEL_ALIAS = os.environ.get("RECENT_ACTIVITY_MODEL_ALIAS", "matrix-coder")

DISTILL_PROMPT = """You are distilling a user's recent activity for their personal assistant.
Below are raw inputs from the last {days} days for user '{user}':
skill jobs (tasks they asked the assistant to do), recently stored memory
facts, and GitHub events (if any).

Write a concise "recent activity" summary:
- 5-10 short markdown bullets, grouped by project/topic, most recent first.
- Each bullet: what happened, one line, max ~15 words; include a date or
  "this week" when known.
- Keep durable, cross-session-useful activity: projects worked on, decisions
  made, things shipped, ongoing themes.
- Drop noise: one-off trivial jobs, duplicates, questions with no outcome.
- Merge overlapping items from different sources (e.g. a job + commits on
  the same project become one bullet).
- Output ONLY the bullets. No preamble, no title, no closing line.
"""


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# User discovery
# ---------------------------------------------------------------------------


def _known_users() -> list[str]:
    """All real users from the identity map (excludes 'service')."""
    users: list[str] = []
    for part in os.environ.get("MEMORY_USER_KEYS", "").split(","):
        part = part.strip()
        if "=" not in part:
            continue
        user = part.split("=", 1)[0].strip()
        if user and user != "service" and user not in users:
            users.append(user)
    return users


# ---------------------------------------------------------------------------
# Input collectors
# ---------------------------------------------------------------------------


def _recent_jobs(user: str, days: int) -> list[dict]:
    """Recent skill jobs for this user from the durable MySQL index."""
    try:
        import pymysql
    except ImportError:
        logger.warning("recent_activity: pymysql unavailable; skipping jobs")
        return []
    try:
        conn = pymysql.connect(
            host=os.environ.get("MYSQL_DB_HOST", "thor.local"),
            port=int(os.environ.get("MYSQL_DB_PORT", "3306")),
            user=os.environ.get("AI_DB_USER", ""),
            password=os.environ.get("AI_DB_PASS", ""),
            database=os.environ.get("AI_DB_NAME", "homelab"),
            charset="utf8mb4",
            connect_timeout=5,
            read_timeout=10,
        )
    except Exception as exc:  # noqa: BLE001 - degrade, never fail the job
        logger.warning("recent_activity: MySQL unavailable: %s", exc)
        return []
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT skill, status, created_at, data
                FROM skill_jobs
                WHERE JSON_UNQUOTE(JSON_EXTRACT(data, '$.user_id')) = %s
                  AND created_at >= %s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (user, (_now() - timedelta(days=days)).isoformat(), MAX_JOBS),
            )
            rows = cur.fetchall()
        out: list[dict] = []
        for skill, status, created_at, data in rows:
            try:
                d = json.loads(data) if isinstance(data, str) else (data or {})
            except Exception:  # noqa: BLE001
                d = {}
            params = d.get("params") or {}
            intent = next(
                (str(params[k])[:160] for k in ("prompt", "query", "topic", "interests") if params.get(k)),
                "",
            )
            out.append(
                {
                    "skill": skill,
                    "status": status,
                    "created_at": created_at[:16],
                    "intent": intent,
                    "summary": str(d.get("summary") or "")[:160],
                }
            )
        return out
    except Exception as exc:  # noqa: BLE001
        logger.warning("recent_activity: job query failed for %s: %s", user, exc)
        return []
    finally:
        conn.close()


def _recent_memories(user: str, days: int) -> list[dict]:
    """Recently stored Mem0 facts for this user (in-process)."""
    try:
        from memory import interface

        hits = interface.list_memories(user, limit=MAX_MEMORIES)
        cutoff = (_now() - timedelta(days=days)).isoformat()
        recent: list[dict] = []
        for h in hits:
            meta = h.get("metadata") or {}
            # mem0 2.0.19 get_all hits carry created_at/updated_at at the
            # TOP LEVEL of the hit (metadata is a passthrough copy without
            # them). Check both so the 7-day cutoff actually filters.
            ts = str(
                h.get("updated_at")
                or h.get("created_at")
                or meta.get("updated_at")
                or meta.get("created_at")
                or ""
            )
            # Keep recent items; keep undated items too (context beats none).
            if not ts or ts >= cutoff:
                recent.append({"text": str(h.get("text") or "")[:300], "ts": ts[:16]})
        return recent[:15]
    except Exception as exc:  # noqa: BLE001
        logger.warning("recent_activity: memory list failed for %s: %s", user, exc)
        return []


def _github_api(url: str) -> Any:
    """GET a GitHub API URL with the token; return parsed JSON or None."""
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"token {GITHUB_TOKEN}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "homelab-recent-activity",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode())
    except Exception as exc:  # noqa: BLE001
        logger.warning("recent_activity: GitHub API failed for %s: %s", url, exc)
        return None


def _github_events(login: str, days: int) -> list[dict]:
    """GitHub activity for a known identity (token required).

    Pushes: the public events API returns truncated ``PushEvent`` payloads
    (``payload.commits`` empty, ``size`` null) since ~2026-10, so pushes
    come from the repos API instead: recently-pushed public repos owned by
    the login, then per-repo commit messages. PRs/issues: still from the
    events API (those payloads are intact).
    """
    if not GITHUB_TOKEN:
        return []
    cutoff = _now() - timedelta(days=days)
    cutoff_iso = cutoff.isoformat().replace("+00:00", "Z")
    out: list[dict] = []

    # --- pushes via repos + commits API (events PushEvents are truncated) ---
    repos = _github_api(
        f"https://api.github.com/users/{login}/repos?sort=pushed&per_page=30&type=owner"
    )
    if isinstance(repos, list):
        for r in repos:
            if len(out) >= MAX_GITHUB_EVENTS:
                break
            if r.get("private"):
                continue
            pa = r.get("pushed_at") or ""
            try:
                if datetime.fromisoformat(pa.replace("Z", "+00:00")) < cutoff:
                    continue
            except Exception:  # noqa: BLE001
                continue
            full_name = r.get("full_name") or r.get("name") or ""
            if not full_name:
                continue
            commits = _github_api(
                f"https://api.github.com/repos/{full_name}/commits?since={cutoff_iso}&per_page=30"
            )
            if not isinstance(commits, list):
                continue
            msgs = [
                (c.get("commit", {}).get("message") or "").split("\n")[0]
                for c in commits
                if (c.get("commit", {}).get("message") or "").strip()
            ][:5]
            if msgs:
                out.append({"repo": full_name, "commits": msgs, "ts": pa[:10]})

    # --- PRs + issues via events API (payloads intact) ---
    events = _github_api(f"https://api.github.com/users/{login}/events/public?per_page=100")
    if isinstance(events, list):
        for ev in events:
            if len(out) >= MAX_GITHUB_EVENTS:
                break
            try:
                ts = datetime.fromisoformat(ev["created_at"].replace("Z", "+00:00"))
            except Exception:  # noqa: BLE001
                continue
            if ts < cutoff:
                continue
            et = ev.get("type")
            repo = ev.get("repo", {}).get("name", "")
            if et == "PullRequestEvent":
                action = ev.get("payload", {}).get("action")
                if action in ("opened", "closed", "merged"):
                    out.append(
                        {
                            "repo": repo,
                            "what": f"PR {action}: "
                            + str(ev.get("payload", {}).get("pull_request", {}).get("title", ""))[:100],
                            "ts": ev["created_at"][:10],
                        }
                    )
            elif et == "IssuesEvent":
                action = ev.get("payload", {}).get("action")
                if action in ("opened", "closed"):
                    out.append(
                        {
                            "repo": repo,
                            "what": f"issue {action}: "
                            + str(ev.get("payload", {}).get("issue", {}).get("title", ""))[:100],
                            "ts": ev["created_at"][:10],
                        }
                    )
    return out


# ---------------------------------------------------------------------------
# Distillation
# ---------------------------------------------------------------------------


def _distill(client: Any, user: str, days: int, inputs: dict[str, Any]) -> Optional[str]:
    """LLM distillation of raw inputs into the dated summary bullets."""
    payload = json.dumps(inputs, indent=1, default=str)[:6000]
    prompt = DISTILL_PROMPT.format(days=days, user=user)
    try:
        res = client.chat_completion(
            MODEL_ALIAS,
            [
                {"role": "system", "content": "You are a precise activity summarizer."},
                {"role": "user", "content": f"{prompt}\n\nRAW INPUTS:\n{payload}"},
            ],
            temperature=0.2,
        )
        text = (res.get("choices", [{}])[0].get("message", {}).get("content") or "").strip()
        if not text:
            return None
        return text
    except Exception as exc:  # noqa: BLE001
        logger.warning("recent_activity: distillation failed for %s: %s", user, exc)
        return None


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------


def _write_kb(client: Any, user: str, date_str: str, summary: str) -> bool:
    """Dated recent-activity fact into kb_user (best-effort)."""
    try:
        res = client.mcp_call(
            "kb_add_fact",
            {
                "text": f"{user.capitalize()}'s recent activity (as of {date_str}): {summary}",
                "kb": KB_NAME,
            },
            server_id="mcp_knowledge",
        )
        if res.get("is_error"):
            logger.warning("recent_activity: kb_add_fact error for %s: %s", user, res)
            return False
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("recent_activity: kb_add_fact failed for %s: %s", user, exc)
        return False


def _write_memory(user: str, date_str: str, summary: str) -> bool:
    """Mem0 write for the user (source=scheduled; LLM-extracted facts).

    Uses a work-log extraction prompt: the default mem0 prompt treats a
    dense, dated activity summary as "no personal facts" and stores 0
    (observed live 2026-10-21), while the work-log prompt reliably extracts
    durable project facts (shipped features, infra changes).
    """
    try:
        from memory import interface

        ids = interface.learn_from_turn(
            user,
            [
                {
                    "role": "user",
                    "content": f"Recent activity summary for {user} (as of {date_str}): {summary}",
                }
            ],
            source="scheduled",
            importance="normal",
            prompt=(
                "The user message is a weekly work-activity summary of the user's own "
                "project work. Extract durable facts about the user's ongoing projects "
                "and work: what they are building, features shipped, and infrastructure "
                "changes. These ARE worth remembering as user facts. Merge related items "
                "into concise facts. Keep meaningful dates. Do not invent details."
            ),
        )
        logger.info("recent_activity: mem0 stored %d fact(s) for %s", len(ids), user)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("recent_activity: mem0 write failed for %s: %s", user, exc)
        return False


# ---------------------------------------------------------------------------
# Skill entry point
# ---------------------------------------------------------------------------


def run(params: dict, job: Any, client: Any) -> dict:
    """Distill recent activity for each known user (or one user if given)."""
    days = max(1, min(int(params.get("days", 7) or 7), 30))
    target = str(params.get("user") or "").strip().lower() or None
    users = [target] if target else _known_users()
    if not users:
        return {"error": "No known users (MEMORY_USER_KEYS empty?) and no 'user' param."}

    date_str = _now().strftime("%Y-%m-%d")
    per_user: dict[str, Any] = {}
    written: list[str] = []

    for user in users:
        inputs = {
            "skill_jobs": _recent_jobs(user, days),
            "recent_memories": _recent_memories(user, days),
        }
        login = GITHUB_USERS.get(user)
        if login:
            inputs["github_events"] = _github_events(login, days)
        else:
            inputs["github_events"] = None  # no known GitHub identity -> skip

        n_in = len(inputs["skill_jobs"]) + len(inputs["recent_memories"]) + len(
            inputs["github_events"] or []
        )
        logger.info(
            "recent_activity: %s — %d inputs (jobs=%d, memories=%d, github=%d)",
            user,
            n_in,
            len(inputs["skill_jobs"]),
            len(inputs["recent_memories"]),
            len(inputs["github_events"] or []),
        )
        if n_in == 0:
            per_user[user] = {"skipped": "no recent activity"}
            continue

        summary = _distill(client, user, days, inputs)
        if not summary:
            per_user[user] = {"skipped": "distillation failed"}
            continue

        kb_ok = _write_kb(client, user, date_str, summary)
        mem_ok = _write_memory(user, date_str, summary)
        per_user[user] = {
            "inputs": n_in,
            "kb_written": kb_ok,
            "mem0_written": mem_ok,
            "summary": summary,
        }
        if kb_ok or mem_ok:
            written.append(user)

    # Artifact: full per-user report.
    artifact_path = None
    try:
        ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
        p = ARTIFACT_DIR / f"recent_activity_{_now().strftime('%Y%m%d_%H%M')}.md"
        lines = [f"# Recent activity — {date_str} (lookback {days}d)", ""]
        for user, res in per_user.items():
            lines.append(f"## {user}")
            if "skipped" in res:
                lines.append(f"_(skipped: {res['skipped']})_")
            else:
                lines.append(res["summary"])
            lines.append("")
        p.write_text("\n".join(lines))
        artifact_path = str(p)
    except Exception as exc:  # noqa: BLE001
        logger.warning("recent_activity: artifact write failed: %s", exc)

    summary_line = (
        f"recent_activity: {len(written)}/{len(users)} user(s) updated "
        f"({', '.join(written) if written else 'none'}); window={days}d"
    )
    logger.info(summary_line)
    return {
        "summary": summary_line,
        "per_user": per_user,
        "artifact_path": artifact_path,
    }