#!/usr/bin/env python3
"""
harness_reflection skill — weekly closed-loop reflection (Tier 0 + Tier 1).

Purpose:
  Every week (Sunday 23:00 UTC, user=chuck, days=7 — see
  scheduler/schedules.json), analyze the last 7 days of:
    1. new/updated memories (in-process memory interface, both scopes)
    2. ingested pi session transcripts (session_ingests + /data/sessions)
    3. skill_jobs (failures, retries, durations, approvals/cancels)
    4. git log of the homelab repo (what changed, by whom)
    5. existing open proposals (dedup — never re-propose something open)
  and produce three outputs:

  A. Memory maintenance (Tier 0 writes, add-only semantics — written as
     the TARGET USER via the in-process interface, never as service):
       - contradictions / superseded facts -> `memory_remember`-style
         supersede statements (self-contained, per memory-conventions)
       - corrections detected in sessions (user corrected the agent,
         same correction >=2x) -> preference memory, importance=high,
         provenance (session ref + date)
       - friction lessons (failed jobs, lost work, restarts, retries)
         -> structured lesson memory:
         "Lesson (<date>): <what happened> -> <what to do differently>."

  B. Harness change proposals (Tier 1 — PROPPOSE ONLY, never apply):
       - proposals/YYYY-MM-DD-<slug>.md in the homelab repo
       - row in the `proposals` MySQL table (homelab DB)
       - format: What / Why (evidence) / Risk + rollback / Files touched
       - guardrails (enforced deterministically in code, not just prompt):
         <=5 proposals/run; every proposal >=1 evidence ref that points
         at a REAL input (memory id / job id / session id / git sha /
         quoted user statement); no proposal may touch .env, compose
         restart semantics, or memory privacy scoping; a
         memory-conventions scope-rule change is allowed only when it
         quotes the user's statement as evidence; dedup against open
         proposals by slug, title, same-day file, AND evidence overlap
         (a re-worded proposal citing >=50% of an open proposal's
         evidence refs is dropped).

  C. Review digest (<=1 page artifact) + a short pointer pushed into the
     next morning_brief context (minimal documented context hook — the
     brief reads {ARTIFACT_DIR}/latest_pointer.txt; see
     skills/morning_brief/skill.py::_reflection_pointer_block).
     Staleness: proposals open >14 days are flagged in the digest (never
     auto-deleted — pruning is a human decision).

Identity (D10): scheduled jobs run under the `service` identity — the
ANALYSIS is service-scoped, but every memory WRITE goes to the target
user (default chuck) via the in-process interface, exactly like
recent_activity. The interface's _valid_user rejects service/unknown
writers, so this skill cannot accidentally write personal memory as
service.

Constraints:
  - Propose only: this skill NEVER applies harness changes, never
    restarts/recreates anything, never touches .env / compose files /
    memory privacy scoping (Tier 2/3 actions are out of scope by design).
  - The job writes ONLY to the proposals/ repo dir and its own artifact
    dir (enforced by the read-only repo mount + the code).
  - All writes are best-effort; a failed write never fails the job.
  - Max runtime: 600 seconds.
"""

import json
import logging
import os
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("skill.harness_reflection")

# ---------------------------------------------------------------------------
# Configuration (env + skill.yml config)
# ---------------------------------------------------------------------------

DEFAULT_USER = os.environ.get("HARNESS_REFLECTION_USER", "chuck")
GIT_REPO = os.environ.get("HARNESS_REFLECTION_GIT_REPO", "/home/chuck/homelab")
PROPOSALS_DIR = Path(
    os.environ.get("HARNESS_REFLECTION_PROPOSALS_DIR", "/home/chuck/homelab/proposals")
)
ARTIFACT_DIR = Path(
    os.environ.get(
        "HARNESS_REFLECTION_ARTIFACT_DIR",
        "/home/chuck/data/media/homelab_reports/harness_reflection",
    )
)
MODEL_ALIAS = os.environ.get("HARNESS_REFLECTION_MODEL_ALIAS", "matrix-coder")
MAX_PROPOSALS = int(os.environ.get("HARNESS_REFLECTION_MAX_PROPOSALS", "5"))
STALE_DAYS = int(os.environ.get("HARNESS_REFLECTION_STALE_DAYS", "14"))
MAX_MEMORIES = int(os.environ.get("HARNESS_REFLECTION_MAX_MEMORIES", "60"))
MAX_JOBS = int(os.environ.get("HARNESS_REFLECTION_MAX_JOBS", "50"))
MAX_GIT_COMMITS = int(os.environ.get("HARNESS_REFLECTION_MAX_GIT_COMMITS", "40"))
MAX_SESSIONS = int(os.environ.get("HARNESS_REFLECTION_MAX_SESSIONS", "4"))
MAX_SESSION_CHARS = int(os.environ.get("HARNESS_REFLECTION_MAX_SESSION_CHARS", "12000"))
MAX_LESSONS = int(os.environ.get("HARNESS_REFLECTION_MAX_LESSONS", "6"))
MAX_SUPERSEDES = int(os.environ.get("HARNESS_REFLECTION_MAX_SUPERSEDES", "5"))
MAX_CORRECTIONS = int(os.environ.get("HARNESS_REFLECTION_MAX_CORRECTIONS", "5"))

# Where transcripts live (mirrors sessions.SESSIONS_ROOT; the env var is
# read directly so the skill degrades cleanly when the runner module is
# not importable, e.g. standalone unit tests).
SESSIONS_ROOT = Path(os.environ.get("SESSIONS_DATA_ROOT", "/data/sessions"))

# Evidence-ref grammar (deterministic guardrail):
#   memory:<id>  — a memory id from input 1
#   job:<id>     — a job_id from input 3
#   session:<id> — a session_id from input 2
#   git:<sha>    — a commit sha from input 4
#   user:<date> "<quoted statement>" — a verbatim user statement (required
#                  for memory-conventions scope-rule proposals)
EVIDENCE_RE = re.compile(
    r"^(memory|job|session|git):[A-Za-z0-9._-]+"
    r'|^user:\d{4}-\d{2}-\d{2}\s+"[^"]{3,400}"\Z'
)
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}\Z")

# Guardrail: files a proposal may NEVER touch (privacy invariant +
# no-restart standing rule + secrets).
FORBIDDEN_FILE_RE = re.compile(
    r"(^|/)\.env(\.|$)|^compose/|docker-compose|(^|/)docker\.yml($|\.)"
    r"|^litellm/|qdrant|(^|/)memory/(policy|config|identity)\.py"
    r"|MEMORY_HOUSEHOLD|privacy",
    re.IGNORECASE,
)
# memory-conventions scope-rule changes are allowed ONLY with a quoted
# user statement as evidence.
CONVENTIONS_FILE = "agents-skills/memory-conventions/SKILL.md"

ANALYSIS_PROMPT = """You are the weekly harness-reflection analyst for a personal homelab assistant.
You analyze one week of signals and propose improvements. You are PROPPOSE-ONLY:
you never apply changes, never restart services, never edit config files.

Below are the signals from the last {days} days for user '{user}':
- MEMORIES: new/updated memory facts (id, date, scope, text)
- SESSIONS: ingested pi session transcripts (user/assistant turns, excerpts)
- JOBS: skill jobs (status, duration, errors, retries, approvals/cancels)
- GIT: commits to the homelab repo (sha, date, author, subject)
- OPEN PROPOSALS: already-open harness change proposals with their evidence refs (NEVER re-propose these — including with a different slug/title that cites the same evidence)

Return STRICT JSON (no markdown fences, no commentary) with exactly these keys:
{{
  "supersedes": [{{"text": "<self-contained supersede statement>", "evidence": ["memory:<id>"]}}],
  "corrections": [{{"text": "<durable preference statement>", "evidence": ["session:<session_id>"], "count": <int>}}],
  "lessons": [{{"text": "<what happened> -> <what to do differently>", "evidence": ["job:<job_id>"]}}],
  "proposals": [{{"slug": "<kebab-slug>", "title": "<one line>", "what": "<concrete diff or instruction>", "why": "<evidence summary>", "risk": "<risk + rollback>", "files": ["<repo-relative paths>"], "evidence": ["<ref>"]}}]
}}

Rules:
- supersedes: ONLY for contradictions or superseded facts among the memories (or a memory contradicted by session/job evidence). Each text must be self-contained (readable without the old fact) and state the current truth.
- corrections: the user corrected the assistant in a session ("no, ...", "I told you ...", "I said that last week"). Only when the SAME correction appears >=2 times (across turns/sessions). text = the durable preference.
- lessons: friction signals (failed jobs, lost work, restarts, retries, long durations). text = "<what happened> -> <what to do differently>" WITHOUT a "Lesson" prefix (it is added automatically).
- proposals: harness changes that would reduce friction or close a captured gap. AT MOST 5. Every proposal needs >=1 evidence ref.
- Evidence ref grammar (use ONLY these forms, and ONLY ids that appear in the inputs above — never invent refs): memory:<id>, job:<job_id>, session:<session_id>, git:<sha>, user:<YYYY-MM-DD> "<quoted user statement>".
- FORBIDDEN (drop any proposal that would touch these): .env files, compose/ files or restart semantics, memory privacy scoping (skills/runner/memory/*, household scope), litellm/ or qdrant config.
- {conventions} scope-rule changes ARE allowed ONLY when the proposal carries a user:<date> "<quoted user statement>" evidence ref quoting the user.
- If a signal is empty, return an empty list for that key. Do not invent evidence or signals."""

CONVENTIONS_CLAUSE = (
    f"agents-skills/memory-conventions/SKILL.md"
)


# ---------------------------------------------------------------------------
# Input collectors (each degrades to []/None on error — never fail the job)
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        ts = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts


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


def _collect_memories(user: str, days: int) -> list[dict]:
    """New/updated memories for the user in the window (both scopes).

    Uses the in-process interface (READ as the target user — the service
    identity has no personal memory; reading the target user's own
    private+household view is the same data the scheduled memory_review
    digest uses).
    """
    try:
        from memory import interface  # lazy: keep the skill importable standalone

        hits = interface.list_memories(user, limit=MAX_MEMORIES)
    except Exception as exc:  # noqa: BLE001 - degrade, never fail the job
        logger.warning("harness_reflection: memory list failed for %s: %s", user, exc)
        return []
    cutoff = _now() - timedelta(days=days)
    out: list[dict] = []
    for h in hits:
        ts = _parse_ts(h.get("updated_at")) or _parse_ts(h.get("created_at"))
        if ts is not None and ts < cutoff:
            continue  # outside the window (dated facts only)
        meta = h.get("metadata") or {}
        out.append(
            {
                "id": str(h.get("id") or ""),
                "text": str(h.get("text") or "")[:300],
                "ts": (ts.isoformat()[:16] if ts else ""),
                "scope": h.get("source") or "private",
                "importance": str(meta.get("importance") or "normal"),
                "source": str(meta.get("source") or ""),
            }
        )
    return out


def _collect_sessions(user: str, days: int) -> list[dict]:
    """Ingested sessions for the user in the window (metadata + excerpts).

    Primary: the session_ingests index (sessions.list_ingests). Fallback
    (index down / no rows): scan the transcript dirs on disk for the
    window's days. Works with zero sessions (returns []).
    """
    cutoff = _now() - timedelta(days=days)
    cutoff_iso = cutoff.isoformat()
    rows: list[dict] = []
    try:
        import sessions  # lazy: runner module (container: /app on sys.path)

        rows = sessions.list_ingests(user, since=cutoff_iso, limit=20)
    except Exception as exc:  # noqa: BLE001 - degrade to disk scan
        logger.warning(
            "harness_reflection: session index unavailable (%s); scanning disk",
            exc,
        )

    out: list[dict] = []
    seen: set[str] = set()
    for row in rows:
        sid = str(row.get("session_id") or "")
        if not sid or sid in seen:
            continue
        seen.add(sid)
        ingested_at = str(row.get("ingested_at") or "")
        day = ingested_at[:10]
        out.append(
            {
                "session_id": sid,
                "host": str(row.get("host") or ""),
                "ingested_at": ingested_at[:16],
                "excerpts": _read_transcript_excerpts(user, day, sid),
            }
        )
        if len(out) >= MAX_SESSIONS:
            break

    # Disk fallback (index down or empty): scan the user's day dirs.
    if not out:
        try:
            user_dir = SESSIONS_ROOT / user
            if user_dir.is_dir():
                for day_dir in sorted(user_dir.iterdir()):
                    if not day_dir.is_dir() or not re.match(r"^\d{4}-\d{2}-\d{2}$", day_dir.name):
                        continue
                    try:
                        day_ts = datetime.strptime(day_dir.name, "%Y-%m-%d").replace(
                            tzinfo=timezone.utc
                        )
                    except ValueError:
                        continue
                    if day_ts < cutoff:
                        continue
                    for f in sorted(day_dir.glob("*.jsonl")):
                        if len(out) >= MAX_SESSIONS:
                            break
                        if f.stem in seen:
                            continue
                        seen.add(f.stem)
                        out.append(
                            {
                                "session_id": f.stem,
                                "host": "disk-scan",
                                "ingested_at": day_dir.name,
                                "excerpts": _read_transcript_excerpts(user, day_dir.name, f.stem),
                            }
                        )
        except Exception as exc:  # noqa: BLE001
            logger.warning("harness_reflection: session disk scan failed: %s", exc)
    return out


def _read_transcript_excerpts(user: str, day: str, session_id: str) -> list[dict]:
    """Read a transcript jsonl and extract user/assistant turns (capped).

    Tolerant of shape: direct {"role","content"} lines (chat format) and
    nested {"message": {...}} lines (pi session jsonl). Returns
    [{"role","text"}] capped at MAX_SESSION_CHARS total.
    """
    path = SESSIONS_ROOT / user / day / f"{session_id}.jsonl"
    try:
        if not path.is_file():
            return []
        raw = path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001
        logger.warning("harness_reflection: transcript read failed %s: %s", path, exc)
        return []
    turns: list[dict] = []
    total = 0
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:  # noqa: BLE001 - not JSON; skip
            continue
        if not isinstance(obj, dict):
            continue
        candidates: list[Any] = [obj]
        msg = obj.get("message")
        if isinstance(msg, dict):
            candidates.append(msg)
        for cand in candidates:
            role = str(cand.get("role") or "").lower()
            if role not in ("user", "assistant"):
                continue
            content = cand.get("content")
            if isinstance(content, list):
                content = " ".join(
                    str(p.get("text", "")) for p in content if isinstance(p, dict)
                )
            content = str(content or "").strip()
            if not content:
                continue
            # Skip tool-result / system-ish user turns (pi wraps tool
            # output in user-role lines).
            if role == "user" and content.startswith("[tool"):
                continue
            turns.append({"role": "user" if role == "user" else "assistant", "text": content})
            total += len(content)
            break
        if total >= MAX_SESSION_CHARS:
            break
    # Cap each turn and the total budget.
    for t in turns:
        t["text"] = t["text"][:2000]
    budget = MAX_SESSION_CHARS
    out: list[dict] = []
    for t in turns:
        if budget <= 0:
            break
        t["text"] = t["text"][:budget]
        budget -= len(t["text"])
        out.append(t)
    return out


def _db_conn():
    """Open a short-lived MySQL connection (same pattern as recent_activity)."""
    import pymysql  # lazy

    return pymysql.connect(
        host=os.environ.get("MYSQL_DB_HOST", "thor.local"),
        port=int(os.environ.get("MYSQL_DB_PORT", "3306")),
        user=os.environ.get("AI_DB_USER", ""),
        password=os.environ.get("AI_DB_PASS", ""),
        database=os.environ.get("AI_DB_NAME", "homelab"),
        charset="utf8mb4",
        connect_timeout=5,
        read_timeout=10,
    )


def _collect_jobs(user: str, days: int) -> list[dict]:
    """skill_jobs for the user in the window: failures, retries, durations,
    approvals/cancels.

    Includes service-identity jobs (D10): scheduled runs (recent_activity,
    memory_review, morning_brief, this skill) run under ``service`` but are
    the harness's weekly activity for the target user — friction signals
    (failures, retries, restarts) live there, so a strict user filter would
    leave the jobs input empty on this homelab.
    """
    try:
        conn = _db_conn()
    except Exception as exc:  # noqa: BLE001 - degrade, never fail the job
        logger.warning("harness_reflection: MySQL unavailable: %s", exc)
        return []
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT skill, status, created_at, data
                FROM skill_jobs
                WHERE (JSON_UNQUOTE(JSON_EXTRACT(data, '$.user_id')) = %s
                       OR JSON_UNQUOTE(JSON_EXTRACT(data, '$.user_id')) = 'service')
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
            created = _parse_ts(d.get("created_at") or created_at)
            completed = _parse_ts(d.get("completed_at"))
            duration_s = (
                int((completed - created).total_seconds())
                if (created and completed)
                else None
            )
            params = d.get("params") or {}
            intent = next(
                (str(params[k])[:120] for k in ("prompt", "query", "topic", "interests") if params.get(k)),
                "",
            )
            out.append(
                {
                    "job_id": str(d.get("job_id") or ""),
                    "skill": skill,
                    "status": status,
                    "intent": intent,
                    "error": str(d.get("error") or "")[:200],
                    "duration_s": duration_s,
                    "created_at": str(created_at)[:16],
                }
            )
        return out
    except Exception as exc:  # noqa: BLE001
        logger.warning("harness_reflection: job query failed for %s: %s", user, exc)
        return []
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass


def _job_signals(jobs: list[dict]) -> dict:
    """Derive friction signals from the raw job list (deterministic)."""
    failed = [j for j in jobs if j["status"] in ("failed", "interrupted")]
    cancelled = [j for j in jobs if j["status"] == "cancelled"]
    approvals = [j for j in jobs if j["status"] == "awaiting_approval"]
    # Retries: same skill + same intent re-run >=2 times in the window.
    by_key: dict[tuple, list[dict]] = {}
    for j in jobs:
        by_key.setdefault((j["skill"], j["intent"]), []).append(j)
    retried = [
        {"skill": k[0], "intent": k[1], "runs": len(v), "job_ids": [x["job_id"] for x in v]}
        for k, v in by_key.items()
        if len(v) >= 2
    ]
    durations = sorted(
        (j["duration_s"] for j in jobs if j["duration_s"] is not None), reverse=True
    )
    return {
        "failed": failed,
        "cancelled": cancelled,
        "awaiting_approval": approvals,
        "retried": retried,
        "slowest": durations[:3],
    }


def _collect_git(days: int) -> list[dict]:
    """Git log of the homelab repo in the window (what changed, by whom).

    Best-effort: the repo must be reachable (mounted read-only in the
    container). Degrades to [] when absent (e.g. standalone runs).
    """
    if not GIT_REPO or not Path(GIT_REPO).is_dir():
        logger.info("harness_reflection: git repo %s not reachable — skipping", GIT_REPO)
        return []
    try:
        env = dict(os.environ)
        env["GIT_OPTIONAL_LOCKS"] = "0"  # never write to the (ro) repo
        res = subprocess.run(
            [
                "git",
                f"-C",
                GIT_REPO,
                "log",
                f"--since={days} days ago",
                f"-n",
                str(MAX_GIT_COMMITS),
                "--date=short",
                "--pretty=format:%H%x1f%ad%x1f%an%x1f%s",
            ],
            capture_output=True,
            text=True,
            timeout=20,
            env=env,
        )
        if res.returncode != 0:
            logger.warning("harness_reflection: git log failed: %s", res.stderr[:200])
            return []
        out: list[dict] = []
        for line in res.stdout.splitlines():
            parts = line.split("\x1f")
            if len(parts) < 4:
                continue
            out.append(
                {
                    "sha": parts[0][:12],
                    "date": parts[1],
                    "author": parts[2],
                    "subject": parts[3][:160],
                }
            )
        return out
    except Exception as exc:  # noqa: BLE001
        logger.warning("harness_reflection: git log error: %s", exc)
        return []


def _collect_open_proposals() -> list[dict]:
    """Existing open proposals (dedup input). Degrades to [] when the
    index is down (file-only mode: dedup then uses the proposals/ dir)."""
    try:
        import proposals  # lazy: runner module

        return proposals.list_proposals(status="open", limit=50)
    except Exception as exc:  # noqa: BLE001
        logger.warning("harness_reflection: open-proposal query failed: %s", exc)
        return _open_proposals_from_disk()


def _open_proposals_from_disk() -> list[dict]:
    """File-only fallback for dedup (index down): scan proposals/*.md."""
    out: list[dict] = []
    try:
        if not PROPOSALS_DIR.is_dir():
            return out
        for f in sorted(PROPOSALS_DIR.glob("*.md")):
            m = re.match(r"^(\d{4}-\d{2}-\d{2})-(.+)\.md$", f.name)
            if not m:
                continue
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                continue
            title = ""
            for line in text.splitlines():
                if line.startswith("# "):
                    title = line[2:].strip()
                    break
            out.append({"slug": m.group(2), "title": title, "created_at": m.group(1)})
    except Exception as exc:  # noqa: BLE001
        logger.warning("harness_reflection: proposals dir scan failed: %s", exc)
    return out


# ---------------------------------------------------------------------------
# Analysis (one LLM call; deterministic guardrails applied to the output)
# ---------------------------------------------------------------------------


def _analysis_payload(inputs: dict[str, Any]) -> str:
    """Serialize the inputs for the LLM (size-capped)."""
    payload = {
        "memories": inputs["memories"][:MAX_MEMORIES],
        "sessions": [
            {
                "session_id": s["session_id"],
                "host": s["host"],
                "ingested_at": s["ingested_at"],
                "turns": s["excerpts"],
            }
            for s in inputs["sessions"]
        ],
        "jobs": inputs["jobs"][:MAX_JOBS],
        "job_signals": {
            "failed": [
                {"job_id": j["job_id"], "skill": j["skill"], "error": j["error"]}
                for j in inputs["signals"]["failed"]
            ],
            "retried": inputs["signals"]["retried"],
            "cancelled": [j["job_id"] for j in inputs["signals"]["cancelled"]],
            "awaiting_approval": [j["job_id"] for j in inputs["signals"]["awaiting_approval"]],
            "slowest_durations_s": inputs["signals"]["slowest"],
        },
        "git": inputs["git"],
        "open_proposals": [
            {
                "slug": p["slug"],
                "title": p["title"],
                "evidence": [str(r) for r in (p.get("evidence") or [])][:10],
            }
            for p in inputs["open_proposals"]
        ],
    }
    return json.dumps(payload, indent=1, default=str)[:18000]


def _analyze(client: Any, user: str, days: int, inputs: dict[str, Any]) -> dict:
    """One LLM call -> the four output classes ({} on any failure)."""
    prompt = ANALYSIS_PROMPT.format(
        days=days,
        user=user,
        conventions=CONVENTIONS_CLAUSE,
    )
    try:
        res = client.chat_completion(
            MODEL_ALIAS,
            [
                {
                    "role": "system",
                    "content": "You are a precise, conservative harness analyst. "
                    "You output strict JSON only. You never invent evidence.",
                },
                {"role": "user", "content": f"{prompt}\n\nSIGNALS:\n{_analysis_payload(inputs)}"},
            ],
            temperature=0.2,
        )
        text = (res.get("choices", [{}])[0].get("message", {}).get("content") or "").strip()
        if not text:
            return {}
        # Tolerate a stray markdown fence.
        m = re.match(r"^```(?:json)?\s*(.*?)\s*```\s*$", text, re.DOTALL)
        if m:
            text = m.group(1)
        data = json.loads(text)
        if not isinstance(data, dict):
            return {}
        out: dict[str, list] = {}
        for key in ("supersedes", "corrections", "lessons", "proposals"):
            items = data.get(key) or []
            out[key] = items if isinstance(items, list) else []
        return out
    except Exception as exc:  # noqa: BLE001 - degrade: deterministic fallback only
        logger.warning("harness_reflection: LLM analysis failed: %s", exc)
        return {}


# ---------------------------------------------------------------------------
# Deterministic guardrails (never trust the LLM output)
# ---------------------------------------------------------------------------


def _valid_evidence_refs(refs: Any, inputs: dict[str, Any]) -> list[str]:
    """Keep only evidence refs that match the grammar AND point at a real
    input (no invented refs). Returns the validated refs."""
    if not isinstance(refs, list):
        return []
    memory_ids = {m["id"] for m in inputs["memories"] if m.get("id")}
    job_ids = {j["job_id"] for j in inputs["jobs"] if j.get("job_id")}
    session_ids = {s["session_id"] for s in inputs["sessions"] if s.get("session_id")}
    git_shas = {g["sha"] for g in inputs["git"] if g.get("sha")}
    valid: list[str] = []
    for ref in refs:
        ref = str(ref or "").strip()
        if not EVIDENCE_RE.match(ref):
            continue
        kind = ref.split(":", 1)[0]
        target = ref.split(":", 1)[1].strip()
        if kind == "memory" and target not in memory_ids:
            continue
        if kind == "job" and target not in job_ids:
            continue
        if kind == "session" and target not in session_ids:
            continue
        if kind == "git" and target not in git_shas:
            continue
        # user:<date> "<statement>" — verbatim statement; validated by the
        # grammar (quoted, >=3 chars). No input check possible (it is a
        # quote of the user, not a store id).
        valid.append(ref)
    return valid


def _proposal_allowed(p: dict, inputs: dict[str, Any]) -> tuple[bool, str]:
    """Apply the proposal guardrails. Returns (allowed, reason)."""
    evidence = _valid_evidence_refs(p.get("evidence"), inputs)
    if not evidence:
        return False, "no valid evidence ref"
    files = [str(f) for f in (p.get("files") or []) if str(f).strip()]
    if not files:
        return False, "no target files"
    for f in files:
        if FORBIDDEN_FILE_RE.search(f):
            return False, f"forbidden target: {f}"
        if f == CONVENTIONS_FILE and not any(r.startswith("user:") for r in evidence):
            return False, "memory-conventions change requires a quoted user statement"
    return True, ""


def _dedupe_proposal(p: dict, open_proposals: list[dict], date_str: str) -> tuple[bool, str]:
    """Never re-propose something already open (slug, title, or
    evidence match).

    Returns (is_duplicate, reason) — True when the proposal must be
    skipped (already open / file exists), False when it may proceed.
    """
    slug = str(p.get("slug") or "").strip().lower()
    title = str(p.get("title") or "").strip().lower()
    # Evidence refs this proposal would cite. Raw refs are fine here:
    # invented refs cannot match the real refs of an open proposal.
    new_refs = {str(r).strip() for r in (p.get("evidence") or []) if str(r or "").strip()}
    for op in open_proposals:
        op_slug = str(op.get("slug") or "").strip().lower()
        if slug and slug == op_slug:
            return True, f"slug already open: {op.get('slug')}"
        if title and title == str(op.get("title") or "").strip().lower():
            return True, f"title already open: {op.get('slug')}"
        # Evidence overlap: the LLM can re-word a finding (new slug/title)
        # while citing the same jobs/memories. If the two proposals share
        # at least half of each other's evidence refs (>=1), it is the
        # same underlying finding — skip it; the reviewer can extend the
        # open proposal instead. (Disk-fallback rows carry no evidence,
        # so this never fires in file-only mode.)
        op_refs = {str(r).strip() for r in (op.get("evidence") or []) if str(r or "").strip()}
        if new_refs and op_refs:
            overlap = len(new_refs & op_refs)
            if overlap >= 1 and overlap * 2 >= len(new_refs) and overlap * 2 >= len(op_refs):
                return True, f"evidence already open in {op.get('slug')}"
    # Same-day file already exists?
    if slug:
        try:
            if (PROPOSALS_DIR / f"{date_str}-{slug}.md").is_file():
                return True, f"proposal file already exists: {slug}"
        except Exception:  # noqa: BLE001
            pass
    return False, ""


def _slugify(value: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", str(value).lower()).strip("-")
    return s[:64].strip("-")


# ---------------------------------------------------------------------------
# Writes (all best-effort; a failure never fails the job)
# ---------------------------------------------------------------------------


def _write_memory_fact(
    user: str,
    text: str,
    importance: str = "normal",
    source: str = "harness_reflection",
    job: Any = None,
) -> bool:
    """Store one durable fact for the TARGET USER (never service).

    infer=False: the text is stored verbatim (no extraction LLM) — the
    reflection output is already distilled and must not be paraphrased.
    """
    try:
        from memory import interface  # lazy

        ids = interface.learn_from_turn(
            user,
            [{"role": "user", "content": text}],
            source=source,
            importance=importance,
            confidence="high" if importance == "high" else "normal",
            infer=False,
            agent_id="harness_reflection",
        )
        if job is not None and hasattr(job, "add_log"):
            job.add_log(f"Memory write ({source}, {importance}): stored={len(ids)}")
        return bool(ids)
    except Exception as exc:  # noqa: BLE001 - writes are non-fatal
        logger.warning("harness_reflection: memory write failed for %s: %s", user, exc)
        return False


def _apply_maintenance(
    user: str, analysis: dict, inputs: dict[str, Any], job: Any
) -> dict:
    """Tier 0 writes: supersede statements, correction preferences,
    friction lessons. Returns per-class counts + the stored texts."""
    result = {"supersedes": [], "corrections": [], "lessons": []}

    # --- supersede statements (contradictions / superseded facts) ---
    for item in analysis.get("supersedes", [])[:MAX_SUPERSEDES]:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        refs = _valid_evidence_refs(item.get("evidence"), inputs)
        if len(text) < 10 or not refs:
            continue
        if _write_memory_fact(user, text, importance="normal", job=job):
            result["supersedes"].append(text)

    # --- corrections (same correction >=2x -> preference, importance=high) ---
    for item in analysis.get("corrections", [])[:MAX_CORRECTIONS]:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        refs = _valid_evidence_refs(item.get("evidence"), inputs)
        try:
            count = int(item.get("count") or 0)
        except (TypeError, ValueError):
            count = 0
        if len(text) < 10 or not refs or count < 2:
            continue
        # Provenance: session ref + date (per the contract).
        session_ref = next((r for r in refs if r.startswith("session:")), refs[0])
        text = f"{text} (preference; corrected the assistant {count}x — {session_ref}, {inputs['date_str']})"
        if _write_memory_fact(user, text, importance="high", job=job):
            result["corrections"].append(text)

    # --- friction lessons (LLM first, deterministic fallback) ---
    lessons: list[tuple[str, list[str]]] = []
    for item in analysis.get("lessons", []):
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        refs = _valid_evidence_refs(item.get("evidence"), inputs)
        if len(text) < 10 or not refs:
            continue
        lessons.append((text, refs))
    if not lessons:
        # Deterministic fallback: one lesson per unique failed skill and
        # per re-run pattern (no LLM needed; keeps the run useful even
        # when the model call fails).
        signals = inputs["signals"]
        seen_skills: set[str] = set()
        for j in signals["failed"]:
            if j["skill"] in seen_skills:
                continue
            seen_skills.add(j["skill"])
            err = j["error"][:100] or "unknown error"
            lessons.append(
                (
                    f"{j['skill']} job failed ({err}) -> check the skill's inputs and "
                    f"logs before re-running; capture the failing case in a test.",
                    [f"job:{j['job_id']}"] if j["job_id"] else [],
                )
            )
            if len(lessons) >= 3:
                break
        for r in signals["retried"][:2]:
            lessons.append(
                (
                    f"{r['skill']} was re-run {r['runs']}x in one week "
                    f"(intent: {r['intent'][:80] or 'n/a'}) -> the first run likely "
                    f"misfired; tighten the skill's input validation or defaults.",
                    r["job_ids"][:2],
                )
            )
    for text, refs in lessons[:MAX_LESSONS]:
        # Structured lesson format (per the contract).
        if not re.match(r"^Lesson \(\d{4}-\d{2}-\d{2}\):", text):
            text = f"Lesson ({inputs['date_str']}): {text}"
        if _write_memory_fact(user, text, importance="normal", job=job):
            result["lessons"].append(text)

    return result


def _proposal_markdown(date_str: str, p: dict, evidence: list[str]) -> str:
    """Render one proposal (What / Why / Risk + rollback / Files touched)."""
    files = [str(f) for f in (p.get("files") or [])]
    lines = [
        f"# {p.get('title', p.get('slug', 'proposal')).strip()}",
        "",
        f"- slug: {p.get('slug', '')}",
        f"- date: {date_str}",
        f"- status: open",
        f"- target user: {p.get('target_user', 'chuck')}",
        "",
        "## What",
        str(p.get("what", "")).strip(),
        "",
        "## Why (evidence)",
        str(p.get("why", "")).strip(),
        "",
        "Evidence refs:",
    ]
    lines += [f"- {r}" for r in evidence]
    lines += [
        "",
        "## Risk + rollback",
        str(p.get("risk", "")).strip(),
        "",
        "## Files touched",
    ]
    lines += [f"- {f}" for f in files]
    lines += [
        "",
        "---",
        "_Proposed by the weekly harness_reflection run (Tier 1, propose-only). "
        "Review with `cli/proposals.sh`; applying is a human decision (Tier 2)._",
        "",
    ]
    return "\n".join(lines)


def _apply_proposals(
    analysis: dict, inputs: dict[str, Any], date_str: str, job: Any, target_user: str = "chuck"
) -> dict:
    """Tier 1: write proposal files + DB rows (propose only, never apply)."""
    result: dict[str, Any] = {"new": [], "skipped": []}
    open_proposals = inputs["open_proposals"]
    accepted: list[dict] = []
    for p in analysis.get("proposals", []):
        if not isinstance(p, dict):
            continue
        if len(accepted) >= MAX_PROPOSALS:
            result["skipped"].append(f"cap {MAX_PROPOSALS}/run reached")
            break
        slug = _slugify(p.get("slug") or p.get("title") or "")
        if not slug or not SLUG_RE.match(slug):
            result["skipped"].append(f"unsafe slug: {slug!r}")
            continue
        p = dict(p)
        p["slug"] = slug
        p["title"] = str(p.get("title") or slug).strip()[:512]
        p["target_user"] = target_user
        allowed, reason = _proposal_allowed(p, inputs)
        if not allowed:
            result["skipped"].append(f"{slug}: {reason}")
            continue
        dup, reason = _dedupe_proposal(p, open_proposals, date_str)
        if dup:
            result["skipped"].append(f"{slug}: {reason}")
            continue
        accepted.append(p)

    for p in accepted:
        evidence = _valid_evidence_refs(p.get("evidence"), inputs)
        files = [str(f) for f in (p.get("files") or [])]
        # (a) file in the repo (best-effort; the file is the source of truth)
        try:
            PROPOSALS_DIR.mkdir(parents=True, exist_ok=True)
            path = PROPOSALS_DIR / f"{date_str}-{p['slug']}.md"
            path.write_text(_proposal_markdown(date_str, p, evidence), encoding="utf-8")
            p["path"] = str(path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("harness_reflection: proposal file write failed: %s", exc)
        # (b) row in the proposals table (best-effort; idempotent on slug)
        try:
            import proposals  # lazy: runner module

            proposals.insert(
                p["slug"],
                p["title"],
                evidence,
                files,
                status="open",
                created_at=_now().isoformat(),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("harness_reflection: proposal insert failed: %s", exc)
        result["new"].append(
            {
                "slug": p["slug"],
                "title": p["title"],
                "evidence": evidence,
                "files": files,
                "path": p.get("path"),
            }
        )
        if job is not None and hasattr(job, "add_log"):
            job.add_log(f"Proposal (open): {p['slug']} — {p['title'][:100]}")
    return result


# ---------------------------------------------------------------------------
# Digest + pointer
# ---------------------------------------------------------------------------


def _stale_proposals(open_proposals: list[dict]) -> list[dict]:
    """Proposals open > STALE_DAYS (flagged in the digest; never deleted)."""
    stale: list[dict] = []
    for p in open_proposals:
        ts = _parse_ts(p.get("created_at"))
        if ts is not None and (_now() - ts).days > STALE_DAYS:
            stale.append(p)
    return stale


def _build_digest(
    user: str,
    days: int,
    inputs: dict[str, Any],
    maintenance: dict,
    proposals_result: dict,
) -> str:
    """The <=1-page review digest (markdown)."""
    stale = _stale_proposals(inputs["open_proposals"])
    open_count = len(inputs["open_proposals"])
    lines = [
        f"# Harness reflection — {inputs['date_str']} (user {user}, window {days}d)",
        "",
        "## Memory maintenance",
        f"- {len(maintenance['supersedes']) + len(maintenance['corrections']) + len(maintenance['lessons'])} memories maintained "
        f"({len(maintenance['supersedes'])} supersede, {len(maintenance['corrections'])} corrections, {len(maintenance['lessons'])} lessons)",
    ]
    for t in maintenance["supersedes"]:
        lines.append(f"- supersede: {t[:160]}")
    for t in maintenance["corrections"]:
        lines.append(f"- correction (high): {t[:160]}")
    for t in maintenance["lessons"]:
        lines.append(f"- lesson: {t[:160]}")
    if not (maintenance["supersedes"] or maintenance["corrections"] or maintenance["lessons"]):
        lines.append("- nothing to maintain this week")
    lines += [
        "",
        "## Proposals",
        f"- {len(proposals_result['new'])} new this run, {open_count} open before this run",
    ]
    for p in proposals_result["new"]:
        lines.append(f"- NEW open: {p['slug']} — {p['title'][:120]}")
    for p in inputs["open_proposals"]:
        lines.append(f"- open: {p.get('slug')} — {str(p.get('title'))[:120]}")
    if stale:
        lines += ["", f"## Stale (open >{STALE_DAYS}d — review, never auto-deleted)"]
        for p in stale:
            lines.append(f"- {p.get('slug')} (opened {str(p.get('created_at'))[:10]})")
    lines += [
        "",
        "## Signals (window)",
        f"- memories new/updated: {len(inputs['memories'])}",
        f"- sessions ingested: {len(inputs['sessions'])}",
        f"- jobs: {len(inputs['jobs'])} total, "
        f"{len(inputs['signals']['failed'])} failed, "
        f"{len(inputs['signals']['retried'])} re-run pattern(s), "
        f"{len(inputs['signals']['cancelled'])} cancelled, "
        f"{len(inputs['signals']['awaiting_approval'])} awaiting approval",
        f"- git commits: {len(inputs['git'])}",
        "",
        "_Propose-only run: no harness changes were applied. Review with "
        "`cli/proposals.sh list`._",
    ]
    return "\n".join(lines)


def _write_digest_artifact(
    digest: str, date_str: str, counts: dict, job: Any
) -> Optional[str]:
    """Save the digest (private artifact dir) + the morning_brief pointer."""
    try:
        ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
        stamp = _now().strftime("%Y%m%d_%H%M")
        path = ARTIFACT_DIR / f"harness_reflection_{stamp}.md"
        path.write_text(digest, encoding="utf-8")
        # Pointer for the next morning_brief (minimal documented context
        # hook — see morning_brief._reflection_pointer_block). One short
        # line; the brief only surfaces it while fresh (7d TTL).
        pointer = (
            f"Harness reflection {date_str}: "
            f"{counts.get('maintained', 0)} memories maintained, "
            f"{counts.get('lessons', 0)} lessons, "
            f"{counts.get('proposals_new', 0)} new proposal(s), "
            f"{counts.get('proposals_open', 0)} open. Full digest: {path}. "
            f"Review with cli/proposals.sh list."
        )
        (ARTIFACT_DIR / "latest_pointer.txt").write_text(pointer[:500], encoding="utf-8")
        return str(path)
    except Exception as exc:  # noqa: BLE001
        logger.warning("harness_reflection: digest artifact write failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Skill entry point
# ---------------------------------------------------------------------------


def run(params: dict, job: Any, client: Any) -> dict:
    """Weekly closed-loop reflection for the target user (default chuck).

    Identity (D10): the job runs under the service identity (scheduled) —
    the analysis is service-scoped; every memory write goes to the target
    user via the in-process interface (like recent_activity).
    """
    # --- resolve the target user (never service/unknown) ---
    target = str(params.get("user") or DEFAULT_USER).strip().lower()
    if not target or target in ("service", "unknown"):
        return {
            "error": f"Invalid target user {target!r} — must be a personal user "
            "(e.g. chuck). Scheduled runs pass user=chuck explicitly."
        }
    known = _known_users()
    if known and target not in known:
        logger.warning(
            "harness_reflection: target user %r not in MEMORY_USER_KEYS %s — "
            "proceeding (writes will no-op if the interface rejects it).",
            target,
            known,
        )
    days = max(1, min(int(params.get("days", 7) or 7), 30))
    date_str = _now().strftime("%Y-%m-%d")

    if job is not None and hasattr(job, "add_log"):
        job.add_log(
            f"harness_reflection: target user={target} window={days}d "
            f"(job identity: {getattr(job, 'user_id', '?')})"
        )

    # --- inputs (all best-effort) ---
    inputs: dict[str, Any] = {
        "date_str": date_str,
        "memories": _collect_memories(target, days),
        "sessions": _collect_sessions(target, days),
        "jobs": _collect_jobs(target, days),
        "git": _collect_git(days),
        "open_proposals": _collect_open_proposals(),
    }
    inputs["signals"] = _job_signals(inputs["jobs"])
    if job is not None and hasattr(job, "add_log"):
        job.add_log(
            "Inputs: memories=%d sessions=%d jobs=%d git=%d open_proposals=%d "
            "(failed=%d retried=%d)"
            % (
                len(inputs["memories"]),
                len(inputs["sessions"]),
                len(inputs["jobs"]),
                len(inputs["git"]),
                len(inputs["open_proposals"]),
                len(inputs["signals"]["failed"]),
                len(inputs["signals"]["retried"]),
            )
        )

    # --- Tier 0 + Tier 1 analysis (one LLM call; deterministic fallbacks) ---
    # No signals in the window -> no LLM call (like recent_activity: skip
    # users with no inputs). The digest is still written (all zeros).
    n_signals = (
        len(inputs["memories"])
        + len(inputs["sessions"])
        + len(inputs["jobs"])
        + len(inputs["git"])
    )
    if n_signals == 0:
        logger.info("harness_reflection: no signals in window — skipping LLM analysis")
        analysis = {}
    else:
        analysis = _analyze(client, target, days, inputs)

    maintenance = _apply_maintenance(target, analysis, inputs, job)
    proposals_result = _apply_proposals(analysis, inputs, date_str, job, target)

    # Learning metrics (Phase 4): count this run + the maintenance items
    # stored (source of the "correction rate / week" north star on the
    # harness-learning dashboard). Best-effort; never fails the run.
    try:
        import learning_metrics  # lazy: runner module

        learning_metrics.record_run()
        learning_metrics.record_maintenance(
            "supersede", len(maintenance["supersedes"])
        )
        learning_metrics.record_maintenance(
            "correction", len(maintenance["corrections"])
        )
        learning_metrics.record_maintenance("lesson", len(maintenance["lessons"]))
    except Exception:  # noqa: BLE001 - metrics must never fail a run
        pass

    # --- digest + pointer ---
    digest = _build_digest(target, days, inputs, maintenance, proposals_result)
    maintained = (
        len(maintenance["supersedes"])
        + len(maintenance["corrections"])
        + len(maintenance["lessons"])
    )
    artifact_path = _write_digest_artifact(
        digest,
        date_str,
        {
            "maintained": maintained,
            "lessons": len(maintenance["lessons"]),
            "proposals_new": len(proposals_result["new"]),
            "proposals_open": len(inputs["open_proposals"]),
        },
        job,
    )

    summary_line = (
        f"harness_reflection: user={target} window={days}d — "
        f"{maintained} memories maintained ({len(maintenance['lessons'])} lessons), "
        f"{len(proposals_result['new'])} new proposal(s), "
        f"{len(inputs['open_proposals'])} open before run"
    )
    logger.info(summary_line)
    return {
        "summary": summary_line,
        "report": digest,
        "artifact_path": artifact_path,
        "target_user": target,
        "window_days": days,
        "memory_maintenance": {
            "supersedes": len(maintenance["supersedes"]),
            "corrections": len(maintenance["corrections"]),
            "lessons": len(maintenance["lessons"]),
        },
        "proposals_new": proposals_result["new"],
        "proposals_skipped": proposals_result["skipped"],
        "inputs": {
            "memories": len(inputs["memories"]),
            "sessions": len(inputs["sessions"]),
            "jobs": len(inputs["jobs"]),
            "git": len(inputs["git"]),
            "open_proposals": len(inputs["open_proposals"]),
        },
    }