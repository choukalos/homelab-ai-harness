#!/usr/bin/env python3
"""
weekly_agent_reviews skill — 7-part weekly review for ACTIVE agents.

Purpose:
  Every Friday (15:00 America/Chicago — see the `weekly-agent-reviews`
  schedule in scheduler/schedules.json), produce the 7-part weekly review
  for each ACTIVE agent (Q13: `product` is the only active agent;
  `strategist`/`marketing`/`analyst` are OFF — never targeted, even if
  passed in params):

    1. prior-week accomplishments WITH evidence/links (board card ids +
       states, commit hashes, artifact file paths — only real refs)
    2. KR progress vs trajectory (per charter KR: current evidence vs
       target vs cadence; honest "no movement" is valid)
    3. work-mix check (bau vs OKR vs exec work + the spend line)
    4. quality KR status (the mandatory quality KRs — from board spec
       state, machine-checkable)
    5. upcoming plan (proposed cards — SUGGESTIONS only; the agent does
       NOT create cards here)
    6. learnings + domain-KB line (facts added/corrected/forgotten +
       collision log — from the KB window query)
    7. chuck's feedback — a clearly-marked EMPTY placeholder that the
       non-stacking gate reads next cycle

Non-stacking gate (params.non_stacking, default true):
  Scan docs/agents/<slug>/reviews/ for the most recent prior YYYY-WW.md
  (ISO week, strictly before the current week). If it exists AND its
  part-7 (chuck's feedback) has no substantive feedback and no explicit
  ack marker ("ack" / "no feedback — proceed" / chuck's appended text)
  -> skip this agent this cycle (log the reason, write nothing,
  continue). No prior doc (first cycle) -> run unconditionally
  (bootstrap).

Same-week idempotency guard (params.force, default false):
  If THIS week's review doc already exists, the run is skipped (one
  review per week — a same-week re-fire must not overwrite the doc and
  lose part-7 feedback appended since generation). force=true
  regenerates (overwrites) the current week's doc.

Data collection (deterministic, best-effort — a missing source degrades
to an honest "no data" line, never a failure):
  - board: MySQL `ai_kanban` (KANBAN_DB_* env; harness_reflection
    _db_conn() pattern) — tasks with owner=<slug> (all states,
    state_changed_at, project name, spec summary, created_at,
    last_commit, resolution), task_events in the window, per-project
    done counts. Timestamps are bigint milliseconds (verified 2026-11-27
    against live rows).
  - charter: docs/agents/<slug>/charter.md — KR table (definitions /
    targets / cadence), objectives, mandatory quality KRs, work-mix
    intent.
  - org goals: docs/org/goals.md — ladder targets for the trajectory
    check.
  - prior review doc (delta input).
  - domain KB: via the injected MCP client (server_id="mcp_knowledge") —
    kb_search for the agent's owned collection (product -> kb_bluebovine;
    creates on first write, may not exist yet) + kb_list_documents for
    facts added/updated in the window. Empty/missing collections are
    handled gracefully.
  - spend: the agent's LiteLLM key (LITELLM_KEY_<SLUG>) total spend via
    the admin /spend/keys endpoint (LITELLM_MASTER_KEY). If genuinely
    unavailable the doc says "spend: n/a (source unavailable)" — never
    fabricated.

LLM: ONE synthesis call (urllib to LITELLM_BASE_URL + LITELLM_API_KEY,
model "matrix-coder" — the harness_reflection client-wrapper pattern:
tolerate a stray fence, strict JSON, degrade to a deterministic
skeleton on any failure). Deterministic guardrails on the output (never
trust it): evidence refs must match real board card ids / real commit
shas / real file paths (invalid refs dropped + noted); KRs restricted to
the charter's list; dates must fall in the window (or be a date quoted
from the charter/goals/prior-review inputs); zero-activity agents get a
plain "no board cards assigned yet" doc, not invented activity.

Output:
  docs/agents/<slug>/reviews/YYYY-WW.md (ISO week of the run date; the
  reviews/ dir is created). Part 7 is ALWAYS the empty placeholder:
  "(pending — appended after chuck responds)".

Constraints:
  - Read-only w.r.t. the board and the KB — this skill never creates
    cards, never writes KB facts, never touches org/charter docs.
  - Writes ONLY to docs/agents/<slug>/reviews/ in the repo.
  - Max runtime: 300 seconds.
"""

import hashlib
import json
import logging
import os
import re
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("skill.weekly_agent_reviews")

# ---------------------------------------------------------------------------
# Configuration (env + skill.yml config)
# ---------------------------------------------------------------------------

REPO_ROOT = Path(os.environ.get("WEEKLY_AGENT_REVIEWS_REPO_ROOT", "/home/chuck/homelab"))
MODEL_ALIAS = os.environ.get("WEEKLY_AGENT_REVIEWS_MODEL_ALIAS", "matrix-coder")
LITELLM_BASE_URL = os.environ.get("LITELLM_BASE_URL", "http://litellm-proxy:4000").rstrip("/")
LLM_TIMEOUT = int(os.environ.get("WEEKLY_AGENT_REVIEWS_LLM_TIMEOUT", "120"))
SPEND_TIMEOUT = int(os.environ.get("WEEKLY_AGENT_REVIEWS_SPEND_TIMEOUT", "15"))

WINDOW_DAYS = 7
DEFAULT_AGENTS = ["product"]
# Q13 (revised 2026-11-27): product is the only ACTIVE agent. These are
# OFF — keys + workspaces only; never targeted, even if passed in params.
INACTIVE_AGENTS = {"strategist", "marketing", "analyst"}
# Q15 domain-KB ownership (charter): product owns kb_bluebovine.
AGENT_KB = {"product": "kb_bluebovine"}
DEFAULT_OUTPUT_TEMPLATE = "docs/agents/<slug>/reviews/YYYY-WW.md"

MAX_TASKS = 50
MAX_EVENTS = 200
MAX_KB_HITS = 10
MAX_KB_DOCS_IN_WINDOW = 20
MAX_PAYLOAD_CHARS = 18000
MAX_EVIDENCE_PER_ITEM = 5
MAX_PLAN_ITEMS = 5
MAX_BULLET_CHARS = 300

FEEDBACK_PLACEHOLDER = "(pending — appended after chuck responds)"
WEEK_FILE_RE = re.compile(r"^(\d{4})-W(\d{2})\.md$")
# Evidence-ref grammar (deterministic guardrail):
#   task:<id>    — a real board card id owned by the agent (any state)
#   commit:<sha> — a real last_commit sha collected for the agent
#   file:<path>  — a real repo-relative file path (must exist)
EVIDENCE_REF_RE = re.compile(r"^(task|commit|file):[A-Za-z0-9._/\-]+$")
DATE_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
# part-7 heading variants ("## 7. chuck's feedback", "## chuck's feedback", ...)
PART7_HEADING_RE = re.compile(r"^##\s*(?:7[\.\)]?\s*)?.*chuck.*feedback", re.IGNORECASE)
# Placeholder fragments stripped by the non-stacking gate.
PLACEHOLDER_RE = re.compile(
    r"\(pending[^)]*\)|appended after chuck responds", re.IGNORECASE
)
# "serves:" work-mix tags (docs/org/goals.md convention):
#   org/<domain>/<O#>-KR# | agent/<agent>/<O#>-KR# | exec | bau
SERVES_RE = re.compile(r"serves:\s*([A-Za-z0-9_\-./]+)")

REVIEW_PROMPT = """You are the weekly-review analyst for the '{slug}' agent of a small AI org.
Write parts 1-6 of the 7-part weekly review for ISO week {week} (window {window_start} to {window_end}, {days} days) as STRICT JSON.
Part 7 (chuck's feedback) is a fixed placeholder appended by the code — NEVER invent chuck's feedback.

INPUTS (the ONLY facts you may use — never invent anything else):
- BOARD: the agent's board tasks (all states), task events in the window, per-project done counts
- CHARTER: the agent's objectives + KR table (definition / target / cadence) + mandatory quality KRs
- ORG GOALS: org-level ladder targets (trajectory context)
- PRIOR REVIEW: the previous review doc (write the DELTA since it) — null on bootstrap
- KB: domain-KB window facts (docs added/updated in the window + current facts) — may be empty (the collection may not exist yet)
- SPEND: the deterministic spend line (the code appends it to part 3 — do not write a spend figure of your own)

Return STRICT JSON (no markdown fences, no commentary) with exactly these keys:
{{
  "accomplishments": [{{"text": "<what was done>", "evidence": ["task:<id>", "commit:<sha>", "file:<repo-relative path>"]}}],
  "kr_progress": [{{"kr": "<exact KR name from the charter>", "objective": "<O#>", "status": "on track|behind|no movement|done", "evidence": ["<ref>"], "note": "<one line: current evidence vs target vs cadence>"}}],
  "work_mix": {{"bau": "<one line>", "okr": "<one line>", "exec": "<one line>", "note": "<one-line mix assessment>" }},
  "quality_krs": [{{"kr": "<exact quality KR name from the charter>", "status": "pass|fail|n/a", "note": "<one line vs the machine check>"}}],
  "upcoming_plan": [{{"text": "<proposed card (SUGGESTION only — no cards are created here)>"}}],
  "learnings": [{{"text": "<one learning>", "kb_note": "<optional one-liner on domain-KB facts added/corrected/forgotten>"}}]
}}

Rules (violating items are dropped by deterministic guardrails):
- Evidence refs use ONLY these forms and ONLY real ids/paths from the INPUTS above: task:<board card id>, commit:<commit sha>, file:<repo-relative path that exists>. Never invent refs.
- kr_progress: ONLY KRs from the charter list (exact names). Cover EVERY charter KR — an honest "no movement" is a valid status.
- Dates: only dates inside the window {window_start} to {window_end}, or dates quoted verbatim from the CHARTER / ORG GOALS / PRIOR REVIEW inputs (e.g. target dates).
- If the agent had zero board activity, say so plainly in accomplishments (e.g. "no board cards assigned yet") — do not invent activity.
- work_mix: classify the week's board work as bau / OKR / exec (serves: tags when present; unmapped work is bau-leaning and flagged). No spend figure here (the code appends the spend line).
- upcoming_plan: SUGGESTIONS only (the agent does not create cards here); each item names the target project + the KR it serves.
- learnings: include the domain-KB line (facts added/corrected/forgotten this window, or "no KB writes this window" / "KB collection does not exist yet").
- If an input is empty, write the honest empty state for that part. Do not pad."""


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        ts = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts


def _ms_to_iso(value: Any) -> str:
    """bigint timestamp (milliseconds — verified against live rows) -> ISO.

    Defensively treats values < 1e12 as seconds in case the schema ever
    changes units.
    """
    try:
        v = int(value)
    except (TypeError, ValueError):
        return ""
    if v <= 0:
        return ""
    if v < 10**12:  # seconds, not ms
        v *= 1000
    return datetime.fromtimestamp(v / 1000.0, tz=timezone.utc).isoformat()[:16]


def _parse_json_field(value: Any) -> Any:
    """Parse a MySQL JSON column (str / bytes / pre-parsed / NULL)."""
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    try:
        if isinstance(value, bytes):
            value = value.decode("utf-8", errors="replace")
        return json.loads(value)
    except Exception:  # noqa: BLE001 - tolerate malformed JSON
        return None


def _iso_week_label(dt: datetime) -> str:
    y, w, _ = dt.isocalendar()
    return f"{y}-W{w:02d}"


def _iso_week_tuple(label: str) -> Optional[tuple[int, int]]:
    m = WEEK_FILE_RE.match(label)
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)))


def _output_path(slug: str, week_label: str, template: str) -> Path:
    """Resolve the output template (params.output) against the repo root."""
    t = str(template or DEFAULT_OUTPUT_TEMPLATE)
    t = t.replace("<slug>", slug).replace("YYYY-WW", week_label)
    return REPO_ROOT / t


def _existing_week_doc(slug: str, week_label: str, template: str) -> Optional[Path]:
    """The current week's review doc, if it already exists (same-week
    idempotency guard — one review per week unless force=true)."""
    try:
        path = _output_path(slug, week_label, template)
        return path if path.is_file() else None
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Non-stacking gate
# ---------------------------------------------------------------------------


def _prior_review(reviews_dir: Path, current_week: tuple[int, int]) -> Optional[dict]:
    """Most recent prior YYYY-WW.md (ISO week strictly before the current
    week). Returns {"week", "path", "text"} or None (bootstrap)."""
    best: Optional[dict] = None
    try:
        if not reviews_dir.is_dir():
            return None
        for f in sorted(reviews_dir.iterdir()):
            if not f.is_file():
                continue
            wk = _iso_week_tuple(f.name)
            if wk is None or wk >= current_week:
                continue
            if best is None or wk > best["week"]:
                try:
                    text = f.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                best = {"week": wk, "path": f, "text": text}
    except OSError as exc:
        logger.warning("weekly_agent_reviews: reviews dir scan failed: %s", exc)
    return best


def _extract_part7(text: str) -> str:
    """The section under the part-7 (chuck's feedback) heading, up to the
    next '## ' heading or EOF. '' when the heading is absent."""
    lines = str(text or "").splitlines()
    start: Optional[int] = None
    for i, line in enumerate(lines):
        if PART7_HEADING_RE.match(line.strip()):
            start = i + 1
            break
    if start is None:
        return ""
    end = len(lines)
    for j in range(start, len(lines)):
        if lines[j].startswith("## "):
            end = j
            break
    return "\n".join(lines[start:end])


def _part7_has_feedback(section: str) -> bool:
    """True when chuck appended substantive feedback or an explicit ack
    ("ack" / "no feedback — proceed" / his own text). The deterministic
    placeholder (and its fragments) do NOT count."""
    content = PLACEHOLDER_RE.sub(" ", section)
    return bool(content.strip())


def _non_stacking_gate(
    slug: str, current_week: tuple[int, int], non_stacking: bool, template: str
) -> tuple[bool, str, Optional[dict]]:
    """Returns (should_run, reason, prior_doc)."""
    if not non_stacking:
        return True, "non_stacking disabled by params", None
    reviews_dir = _output_path(slug, "0000-W00", template).parent
    prior = _prior_review(reviews_dir, current_week)
    if prior is None:
        return True, "bootstrap: no prior review doc", None
    if _part7_has_feedback(_extract_part7(prior["text"])):
        return (
            True,
            f"prior review {prior['path'].name} has chuck feedback/ack in part 7",
            prior,
        )
    return (
        False,
        (
            f"non-stacking: prior review {prior['path'].name} part 7 has no "
            "feedback/ack — skipping until chuck responds"
        ),
        prior,
    )


# ---------------------------------------------------------------------------
# Board (MySQL ai_kanban — harness_reflection _db_conn() pattern)
# ---------------------------------------------------------------------------


def _board_conn():
    import pymysql  # lazy

    return pymysql.connect(
        host=os.environ.get("KANBAN_DB_HOST", "thor.local"),
        port=int(os.environ.get("KANBAN_DB_PORT", "3306")),
        user=os.environ.get("KANBAN_DB_USER", ""),
        password=os.environ.get("KANBAN_DB_PASS", ""),
        database=os.environ.get("KANBAN_DB_NAME", "ai_kanban"),
        charset="utf8mb4",
        connect_timeout=5,
        read_timeout=10,
    )


def _acceptance_present(value: Any) -> bool:
    """Machine check: does the spec carry testable acceptance criteria?"""
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict)):
        return len(value) > 0
    return bool(value)


def _extract_serves(spec: Any) -> str:
    """The 'serves:' work-mix tag from the spec (goals.md convention)."""
    if not isinstance(spec, dict):
        return ""
    m = SERVES_RE.search(json.dumps(spec, default=str))
    return m.group(1) if m else ""


def _collect_board(slug: str, window_start_ms: int) -> dict:
    """Board data for the agent: tasks (all states), task_events in the
    window, per-project done counts. Degrades to an empty (available=False)
    dict on any failure — never fails the run."""
    out: dict[str, Any] = {
        "available": False,
        "tasks": [],
        "events": [],
        "done_by_project": {},
    }
    try:
        conn = _board_conn()
    except Exception as exc:  # noqa: BLE001 - degrade, never fail the run
        logger.warning("weekly_agent_reviews: board DB unavailable: %s", exc)
        return out
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT t.id, t.state, t.created_at, t.state_changed_at,
                       t.last_commit, t.qa_rounds, t.paused, t.branch,
                       t.resolution, t.spec, p.id, p.name
                FROM tasks t
                JOIN projects p ON p.id = t.project_id
                WHERE t.owner = %s
                ORDER BY t.id
                LIMIT %s
                """,
                (slug, MAX_TASKS),
            )
            rows = cur.fetchall()
        for r in rows:
            spec = _parse_json_field(r[9])
            goal = str(spec.get("goal") or "") if isinstance(spec, dict) else ""
            out["tasks"].append(
                {
                    "id": int(r[0]),
                    "state": str(r[1]),
                    "created_at": _ms_to_iso(r[2]),
                    "state_changed_at": _ms_to_iso(r[3]),
                    "last_commit": str(r[4] or ""),
                    "qa_rounds": int(r[5] or 0),
                    "paused": bool(r[6]),
                    "branch": str(r[7] or ""),
                    "resolution": str(r[8] or "")[:200],
                    "spec_goal": goal[:200],
                    "spec_kind": str(spec.get("kind") or "") if isinstance(spec, dict) else "",
                    "has_acceptance": _acceptance_present(
                        spec.get("acceptance") if isinstance(spec, dict) else None
                    ),
                    "serves": _extract_serves(spec),
                    "project_id": int(r[10]),
                    "project": str(r[11]),
                }
            )
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT p.name, COUNT(*)
                FROM tasks t
                JOIN projects p ON p.id = t.project_id
                WHERE t.owner = %s AND t.state = 'done'
                GROUP BY p.name
                """,
                (slug,),
            )
            out["done_by_project"] = {str(n): int(c) for n, c in cur.fetchall()}
        if out["tasks"]:
            ids = [t["id"] for t in out["tasks"]]
            fmt = ",".join(["%s"] * len(ids))
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT task_id, ts, type, payload
                    FROM task_events
                    WHERE ts >= %s AND task_id IN ({fmt})
                    ORDER BY ts DESC
                    LIMIT %s
                    """,
                    (window_start_ms, *ids, MAX_EVENTS),
                )
                for r in cur.fetchall():
                    out["events"].append(
                        {
                            "task_id": int(r[0]),
                            "ts": _ms_to_iso(r[1]),
                            "type": str(r[2]),
                            "payload": str(r[3] or "")[:200],
                        }
                    )
        out["available"] = True
    except Exception as exc:  # noqa: BLE001
        logger.warning("weekly_agent_reviews: board query failed for %s: %s", slug, exc)
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass
    return out


# ---------------------------------------------------------------------------
# Charter + org goals (markdown KR-table parsing)
# ---------------------------------------------------------------------------

_KR_TABLE_ROW_RE = re.compile(r"^\s*\|\s*(\d+)\s*\|")
_OBJECTIVE_RE = re.compile(r"^\s*(?:-\s*)?\*\*(O\d+)\*\*")


def _parse_kr_tables(text: str) -> list[dict]:
    """Parse the 6-column KR tables (# | KR | Definition | Source | Target |
    Cadence), tracking the current objective context (**O1** ... lines)."""
    krs: list[dict] = []
    current_obj = ""
    for line in str(text or "").splitlines():
        m = _OBJECTIVE_RE.match(line)
        if m:
            current_obj = m.group(1)
            continue
        if not line.lstrip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 6 or not _KR_TABLE_ROW_RE.match(line):
            continue
        krs.append(
            {
                "objective": current_obj,
                "num": int(cells[0]),
                "name": cells[1],
                "definition": cells[2][:200],
                "source": cells[3][:120],
                "target": cells[4][:120],
                "cadence": cells[5][:60],
            }
        )
    return krs


def _parse_charter(slug: str) -> dict:
    """KR table + objectives + quality KRs from docs/agents/<slug>/charter.md."""
    path = REPO_ROOT / "docs" / "agents" / slug / "charter.md"
    out: dict[str, Any] = {
        "path": str(path),
        "found": False,
        "objectives": [],
        "krs": [],
        "quality_krs": [],
    }
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        logger.warning("weekly_agent_reviews: charter not found for %s: %s", slug, path)
        return out
    out["found"] = True
    for m in re.finditer(r"^\s*-\s*\*\*(O\d+)\s*—\s*(.+?)\*\*", text, re.MULTILINE):
        out["objectives"].append({"id": m.group(1), "text": m.group(2).strip()[:200]})
    out["krs"] = _parse_kr_tables(text)
    out["quality_krs"] = [k for k in out["krs"] if "quality" in k["name"].lower()]
    return out


def _parse_org_goals() -> dict:
    """Ladder targets from docs/org/goals.md (org-level KR tables per domain)."""
    path = REPO_ROOT / "docs" / "org" / "goals.md"
    out: dict[str, Any] = {"path": str(path), "found": False, "goals": []}
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        logger.warning("weekly_agent_reviews: org goals not found: %s", path)
        return out
    out["found"] = True
    domain = ""
    current_obj = ""
    for line in text.splitlines():
        dm = re.match(r"^###\s+(.+?)\s*$", line)
        if dm:
            domain = dm.group(1)
            current_obj = ""
            continue
        om = re.match(r"^\*\*(O\d+)\s*—\s*(.+?)\*\*", line)
        if om:
            current_obj = om.group(1)
            continue
        if not line.lstrip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 6 or not _KR_TABLE_ROW_RE.match(line):
            continue
        out["goals"].append(
            {
                "domain": domain,
                "objective": current_obj,
                "num": int(cells[0]),
                "name": cells[1][:120],
                "target": cells[4][:120],
                "cadence": cells[5][:60],
            }
        )
    return out


# ---------------------------------------------------------------------------
# Domain KB (injected MCP client — mcp_knowledge; best-effort)
# ---------------------------------------------------------------------------


def _kb_name_for(slug: str) -> str:
    return AGENT_KB.get(slug, f"kb_{slug}")


def _kb_doc_list(res: Any) -> list[dict]:
    """Tolerant extraction of the document list from kb_list_documents
    ({"documents": {col: [docs]}} / list / normalized shapes)."""
    if not isinstance(res, dict):
        return []
    docs = res.get("documents")
    collected: list[dict] = []
    if isinstance(docs, dict):
        for v in docs.values():
            if isinstance(v, list):
                collected.extend(d for d in v if isinstance(d, dict))
    elif isinstance(docs, list):
        collected.extend(d for d in docs if isinstance(d, dict))
    return collected


def _kb_search_hits(res: Any) -> tuple[list[dict], str]:
    """Tolerant extraction of kb_search hits (structured / raw MCP shapes)."""
    if not isinstance(res, dict):
        return [], ""
    note = str(res.get("note") or "")
    for cand in (res.get("structuredContent"), res.get("result"), res):
        if isinstance(cand, dict) and isinstance(cand.get("results"), list):
            return [h for h in cand["results"] if isinstance(h, dict)], str(
                cand.get("note") or note
            )
    for item in res.get("content") or []:
        if not (isinstance(item, dict) and item.get("type") == "text"):
            continue
        try:
            parsed = json.loads(item.get("text", ""))
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(parsed, dict) and isinstance(parsed.get("results"), list):
            return [h for h in parsed["results"] if isinstance(h, dict)], str(
                parsed.get("note") or note
            )
    return [], note


def _collect_kb(client: Any, slug: str, window_start: datetime) -> dict:
    """Domain-KB window facts for the agent's owned collection.

    Best-effort: empty/missing collections and client failures degrade to
    honest notes (the collection creates on first write — Q15).
    """
    kb = _kb_name_for(slug)
    out: dict[str, Any] = {
        "kb": kb,
        "available": False,
        "exists": None,  # None = unknown
        "hits": [],
        "docs_in_window": [],
        "note": "",
    }
    if client is None:
        out["note"] = "no MCP client injected — KB unavailable"
        return out
    # 1) kb_list_documents: docs ingested/updated in the window.
    try:
        res = client.mcp_call("kb_list_documents", {"kb": kb}, server_id="mcp_knowledge")
        docs = _kb_doc_list(res)
        for doc in docs[:MAX_KB_DOCS_IN_WINDOW * 5]:
            ing = _parse_iso(doc.get("ingested_at"))
            if ing is not None and ing >= window_start:
                out["docs_in_window"].append(
                    {
                        "source": str(doc.get("source") or "")[:160],
                        "ingested_at": str(doc.get("ingested_at") or "")[:10],
                    }
                )
                if len(out["docs_in_window"]) >= MAX_KB_DOCS_IN_WINDOW:
                    break
        out["available"] = True
    except Exception as exc:  # noqa: BLE001 - degrade, never fail the run
        out["note"] = f"kb_list_documents failed: {str(exc)[:120]}"
    # 2) kb_search: current domain facts (context for learnings/collisions).
    try:
        res = client.mcp_call(
            "kb_search",
            {
                "query": f"{kb} domain facts positioning product market",
                "kb": kb,
                "top_k": MAX_KB_HITS,
            },
            server_id="mcp_knowledge",
        )
        hits, note = _kb_search_hits(res)
        if "does not exist" in note:
            out["exists"] = False
        out["hits"] = [
            {
                "source": str(h.get("source") or "")[:160],
                "snippet": str(h.get("snippet") or "")[:200],
            }
            for h in hits[:MAX_KB_HITS]
        ]
        out["available"] = True
    except Exception as exc:  # noqa: BLE001
        out["note"] = out["note"] or f"kb_search failed: {str(exc)[:120]}"
    return out


def _kb_line(kb: dict) -> str:
    """The deterministic domain-KB line for part 6."""
    if kb.get("exists") is False:
        return f"KB ({kb['kb']}): collection does not exist yet — no facts (creates on first write)"
    if not kb.get("available"):
        return f"KB ({kb['kb']}): n/a ({kb.get('note') or 'source unavailable'})"
    added = kb.get("docs_in_window") or []
    if added:
        bits = ", ".join(f"{d['source']} ({d['ingested_at']})" for d in added[:5])
        line = f"KB ({kb['kb']}): {len(added)} fact(s)/doc(s) added/updated in window: {bits}"
    else:
        line = f"KB ({kb['kb']}): no facts added/updated in window"
    if kb.get("hits"):
        line += f" ({len(kb['hits'])} current fact(s) on file)"
    elif kb.get("note"):
        line += f" ({kb['note']})"
    return line


# ---------------------------------------------------------------------------
# Spend (LiteLLM admin API — never fabricated)
# ---------------------------------------------------------------------------


def _collect_spend(slug: str) -> dict:
    """Agent-key spend via LiteLLM admin /spend/keys (LITELLM_MASTER_KEY),
    matched by sha256(LITELLM_KEY_<SLUG>).

    The endpoint exposes the key's TOTAL spend (per-request window logs are
    not exposed via the API on this LiteLLM version — /key/info is 404), so
    the line says so honestly. Any unavailable source -> n/a, never a
    fabricated number.
    """
    out: dict[str, Any] = {
        "spend": None,
        "key_created": None,
        "line": "spend: n/a (source unavailable)",
    }
    key = os.environ.get(f"LITELLM_KEY_{slug.upper()}", "")
    if not key:
        out["line"] = f"spend: n/a (LITELLM_KEY_{slug.upper()} not configured)"
        return out
    master = os.environ.get("LITELLM_MASTER_KEY", "")
    if not (LITELLM_BASE_URL and master):
        out["line"] = "spend: n/a (LiteLLM admin source unavailable)"
        return out
    key_hash = hashlib.sha256(key.encode("utf-8")).hexdigest()
    try:
        req = urllib.request.Request(LITELLM_BASE_URL + "/spend/keys")
        req.add_header("Authorization", f"Bearer {master}")
        with urllib.request.urlopen(req, timeout=SPEND_TIMEOUT) as r:
            data = json.loads(r.read())
        entry = next(
            (e for e in data if isinstance(e, dict) and e.get("token") == key_hash),
            None,
        )
        if not isinstance(entry, dict):
            out["line"] = "spend: n/a (agent key not found in LiteLLM /spend/keys)"
            return out
        spend = entry.get("spend")
        if spend is None:
            spend = entry.get("total_spend")
        out["spend"] = float(spend or 0.0)
        out["key_created"] = str(entry.get("created_at") or "")[:10] or None
        out["line"] = (
            f"spend: ${out['spend']:.2f} (agent-key total — LiteLLM /spend/keys; "
            f"key created {out['key_created'] or 'n/a'}; windowed per-request spend "
            "not exposed via API)"
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("weekly_agent_reviews: spend source unavailable for %s: %s", slug, exc)
        out["line"] = f"spend: n/a (source unavailable: {str(exc)[:80]})"
    return out


# ---------------------------------------------------------------------------
# LLM synthesis (ONE call — urllib to LITELLM_BASE_URL, matrix-coder)
# ---------------------------------------------------------------------------


def _llm_chat(messages: list[dict]) -> Optional[str]:
    """One chat completion. Returns the content string, or None on any
    failure (the caller degrades to the deterministic skeleton)."""
    api_key = os.environ.get("LITELLM_API_KEY", "")
    if not (LITELLM_BASE_URL and api_key):
        logger.warning(
            "weekly_agent_reviews: LITELLM_BASE_URL/LITELLM_API_KEY unset — LLM unavailable"
        )
        return None
    body = json.dumps(
        {"model": MODEL_ALIAS, "messages": messages, "temperature": 0.2}
    ).encode("utf-8")
    req = urllib.request.Request(LITELLM_BASE_URL + "/chat/completions", data=body, method="POST")
    req.add_header("Authorization", f"Bearer {api_key}")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=LLM_TIMEOUT) as r:
            data = json.loads(r.read())
        return (
            (data.get("choices") or [{}])[0].get("message", {}).get("content") or ""
        ).strip() or None
    except Exception as exc:  # noqa: BLE001 - degrade to deterministic fallback
        logger.warning("weekly_agent_reviews: LLM call failed: %s", exc)
        return None


def _analysis_payload(
    slug: str,
    week: str,
    window_start: datetime,
    window_end: datetime,
    board: dict,
    charter: dict,
    org: dict,
    kb: dict,
    spend: dict,
    prior_text: Optional[str],
) -> str:
    payload = {
        "agent": slug,
        "week": week,
        "window": {"start": window_start.isoformat()[:16], "end": window_end.isoformat()[:16]},
        "board": {
            "available": board["available"],
            "tasks": board["tasks"],
            "events_in_window": board["events"],
            "done_by_project": board["done_by_project"],
        },
        "charter": {
            "found": charter["found"],
            "objectives": charter["objectives"],
            "krs": charter["krs"],
            "quality_krs": charter["quality_krs"],
        },
        "org_goals": {"found": org["found"], "goals": org["goals"][:20]},
        "prior_review": (prior_text or "")[:4000] or None,
        "kb": kb,
        "spend_line": spend["line"],
    }
    return json.dumps(payload, indent=1, default=str)[:MAX_PAYLOAD_CHARS]


def _analyze(
    slug: str,
    week: str,
    window_start: datetime,
    window_end: datetime,
    board: dict,
    charter: dict,
    org: dict,
    kb: dict,
    spend: dict,
    prior_text: Optional[str],
) -> Optional[dict]:
    """ONE LLM call -> the parts 1-6 JSON (None on any failure)."""
    prompt = REVIEW_PROMPT.format(
        slug=slug,
        week=week,
        window_start=window_start.strftime("%Y-%m-%d"),
        window_end=window_end.strftime("%Y-%m-%d"),
        days=WINDOW_DAYS,
    )
    messages = [
        {
            "role": "system",
            "content": (
                "You are a precise, conservative weekly-review analyst. "
                "You output strict JSON only. You never invent evidence, "
                "KRs, dates, or spend figures."
            ),
        },
        {
            "role": "user",
            "content": (
                f"{prompt}\n\nINPUTS:\n"
                + _analysis_payload(
                    slug, week, window_start, window_end, board, charter, org, kb, spend,
                    prior_text,
                )
            ),
        },
    ]
    text = _llm_chat(messages)
    if not text:
        return None
    m = re.match(r"^```(?:json)?\s*(.*?)\s*```\s*$", text, re.DOTALL)
    if m:
        text = m.group(1)
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        logger.warning("weekly_agent_reviews: LLM output was not valid JSON")
        return None
    if not isinstance(data, dict):
        return None
    out: dict[str, Any] = {}
    for key in ("accomplishments", "kr_progress", "work_mix", "quality_krs",
                "upcoming_plan", "learnings"):
        val = data.get(key)
        out[key] = val if isinstance(val, (list, dict)) else ([] if key != "work_mix" else {})
    return out


# ---------------------------------------------------------------------------
# Deterministic guardrails (never trust the LLM output)
# ---------------------------------------------------------------------------


def _allowed_dates(
    slug: str,
    prior_text: Optional[str],
    window_start: datetime,
    now: datetime,
) -> set[str]:
    """Dates quoted verbatim from the inputs (charter / org goals / prior
    review) are allowed in addition to in-window dates (e.g. KR target
    dates like 'by 2026-12-15' must not be dropped as out-of-window)."""
    texts: list[str] = []
    for p in (
        REPO_ROOT / "docs" / "agents" / slug / "charter.md",
        REPO_ROOT / "docs" / "org" / "goals.md",
    ):
        try:
            texts.append(p.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            pass
    if prior_text:
        texts.append(prior_text)
    quoted = {m.group(0) for t in texts for m in DATE_RE.finditer(t)}
    return quoted | {window_start.strftime("%Y-%m-%d"), now.strftime("%Y-%m-%d")}


def _dates_ok(text: str, allowed: set[str], window_start: datetime, now: datetime) -> bool:
    """True when every ISO date in the text is in-window or input-quoted."""
    for m in DATE_RE.finditer(str(text or "")):
        iso = m.group(0)
        if iso in allowed:
            continue
        try:
            d = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)),
                         tzinfo=timezone.utc)
        except ValueError:
            return False
        if d < window_start or d > now:
            return False
    return True


def _validate_evidence(
    refs: Any, board: dict, repo_root: Path
) -> tuple[list[str], list[str]]:
    """Keep only refs matching the grammar AND pointing at real data.
    Returns (valid, dropped)."""
    task_ids = {str(t["id"]) for t in board["tasks"]}
    commits = {t["last_commit"] for t in board["tasks"] if t["last_commit"]}
    valid: list[str] = []
    dropped: list[str] = []
    if not isinstance(refs, list):
        return valid, dropped
    for ref in refs:
        ref = str(ref or "").strip()
        if not EVIDENCE_REF_RE.match(ref):
            dropped.append(ref)
            continue
        kind, target = ref.split(":", 1)
        if kind == "task" and target not in task_ids:
            dropped.append(ref)
            continue
        if kind == "commit" and target not in commits:
            dropped.append(ref)
            continue
        if kind == "file":
            try:
                if not (repo_root / target).is_file():
                    dropped.append(ref)
                    continue
            except OSError:
                dropped.append(ref)
                continue
        if ref not in valid:
            valid.append(ref)
    return valid[:MAX_EVIDENCE_PER_ITEM], dropped


def _kr_known(name: str, charter: dict) -> Optional[dict]:
    """Match a KR name against the charter's list (exact or O#-KR# form)."""
    n = str(name or "").strip().lower()
    if not n:
        return None
    for kr in charter["krs"]:
        if kr["name"].lower() == n:
            return kr
    m = re.match(r"^(o\d+)\s*[-_]?\s*(?:kr\s*)?(\d+)$", n)
    if m:
        for kr in charter["krs"]:
            if kr["objective"] == m.group(1).upper() and kr["num"] == int(m.group(2)):
                return kr
    return None


def _quality_machine_check(board: dict) -> dict:
    """Deterministic quality-KR check from board spec state: specs missing
    testable acceptance criteria (the external predicate, MVV rule 3)."""
    tasks = board.get("tasks") or []
    total = len(tasks)
    missing = sum(1 for t in tasks if not t["has_acceptance"])
    return {
        "total": total,
        "missing": missing,
        "line": f"machine check: {missing}/{total} board spec(s) missing testable acceptance criteria",
    }


def _guardrail_filter(
    analysis: dict,
    board: dict,
    charter: dict,
    allowed_dates: set[str],
    window_start: datetime,
    now: datetime,
    zero_activity: bool = False,
) -> tuple[dict, list[str]]:
    """Apply the deterministic guardrails to the LLM output. Returns
    (filtered, notes)."""
    notes: list[str] = []
    out: dict[str, Any] = {
        "accomplishments": [],
        "kr_progress": [],
        "work_mix": {"bau": "", "okr": "", "exec": "", "note": ""},
        "quality_krs": [],
        "upcoming_plan": [],
        "learnings": [],
    }

    # --- accomplishments: evidence refs + window dates ---
    # Zero board activity (verified against the board, not the LLM): the
    # doc must say so plainly — LLM accomplishments are unsupported claims
    # and are replaced by the honest deterministic line in the renderer.
    if zero_activity:
        if analysis.get("accomplishments"):
            notes.append(
                "zero board activity — LLM accomplishments replaced with the "
                "honest deterministic line"
            )
    else:
        for item in analysis.get("accomplishments") or []:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text") or "").strip()[:MAX_BULLET_CHARS]
            if not text:
                continue
            if not _dates_ok(text, allowed_dates, window_start, now):
                notes.append(f"dropped accomplishment (out-of-window date): {text[:80]}")
                continue
            valid, dropped = _validate_evidence(item.get("evidence"), board, REPO_ROOT)
            if dropped:
                notes.append(
                    f"dropped {len(dropped)} invalid evidence ref(s) "
                    f"({', '.join(dropped[:3])}) on: {text[:60]}"
                )
            out["accomplishments"].append({"text": text, "evidence": valid})

    # --- kr_progress: charter KR list + window dates ---
    covered = set()
    for item in analysis.get("kr_progress") or []:
        if not isinstance(item, dict):
            continue
        kr = _kr_known(item.get("kr"), charter)
        if kr is None:
            notes.append(f"dropped KR progress (not in charter): {str(item.get('kr'))[:60]}")
            continue
        key = (kr["objective"], kr["num"])
        if key in covered:
            notes.append(f"dropped duplicate KR progress: {kr['name'][:60]}")
            continue
        note = str(item.get("note") or "").strip()[:200]
        status = str(item.get("status") or "no movement").strip().lower()
        if status not in ("on track", "behind", "no movement", "done", "at risk"):
            status = "no movement"
        blob = f"{note} {item.get('kr') or ''}"
        if not _dates_ok(blob, allowed_dates, window_start, now):
            notes.append(f"dropped KR progress (out-of-window date): {kr['name'][:60]}")
            continue
        valid, dropped = _validate_evidence(item.get("evidence"), board, REPO_ROOT)
        if dropped:
            notes.append(
                f"dropped {len(dropped)} invalid evidence ref(s) "
                f"({', '.join(dropped[:3])}) on KR: {kr['name'][:50]}"
            )
        covered.add(key)
        out["kr_progress"].append(
            {
                "kr": kr["name"],
                "objective": kr["objective"],
                "status": status,
                "evidence": valid,
                "note": note or "no note",
                "target": kr["target"],
                "cadence": kr["cadence"],
            }
        )
    # Every charter KR must appear (honest "no movement" fill-in).
    for kr in charter["krs"]:
        if (kr["objective"], kr["num"]) in covered:
            continue
        out["kr_progress"].append(
            {
                "kr": kr["name"],
                "objective": kr["objective"],
                "status": "no movement",
                "evidence": [],
                "note": "no movement this week (no data in window)",
                "target": kr["target"],
                "cadence": kr["cadence"],
            }
        )

    # --- work_mix: bounded strings (the spend line is appended by code) ---
    wm = analysis.get("work_mix") or {}
    if isinstance(wm, dict):
        out["work_mix"] = {
            k: str(wm.get(k) or "").strip()[:200] for k in ("bau", "okr", "exec", "note")
        }

    # --- quality_krs: charter quality KRs only ---
    quality_names = {k["name"].lower() for k in charter["quality_krs"]}
    for item in analysis.get("quality_krs") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("kr") or "").strip()
        if name.lower() not in quality_names:
            notes.append(f"dropped quality KR (not a charter quality KR): {name[:60]}")
            continue
        status = str(item.get("status") or "n/a").strip().lower()
        if status not in ("pass", "fail", "n/a"):
            status = "n/a"
        out["quality_krs"].append(
            {
                "kr": name,
                "status": status,
                "note": str(item.get("note") or "").strip()[:200],
            }
        )

    # --- upcoming_plan: suggestions only, capped ---
    for item in (analysis.get("upcoming_plan") or [])[:MAX_PLAN_ITEMS]:
        text = str(item.get("text") if isinstance(item, dict) else item or "").strip()
        text = text[:MAX_BULLET_CHARS]
        if not text:
            continue
        if not _dates_ok(text, allowed_dates, window_start, now):
            notes.append(f"dropped plan item (out-of-window date): {text[:80]}")
            continue
        out["upcoming_plan"].append(text)

    # --- learnings: window dates ---
    for item in analysis.get("learnings") or []:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()[:MAX_BULLET_CHARS]
        kb_note = str(item.get("kb_note") or "").strip()[:200]
        if not text:
            continue
        if not _dates_ok(f"{text} {kb_note}", allowed_dates, window_start, now):
            notes.append(f"dropped learning (out-of-window date): {text[:80]}")
            continue
        out["learnings"].append({"text": text, "kb_note": kb_note})

    return out, notes


# ---------------------------------------------------------------------------
# Doc rendering (7 parts; part 7 is ALWAYS the placeholder)
# ---------------------------------------------------------------------------


def _refs(evidence: list[str]) -> str:
    return f" ({'; '.join(evidence)})" if evidence else ""


def _render_doc(
    slug: str,
    week: str,
    window_start: datetime,
    window_end: datetime,
    parts: dict,
    spend: dict,
    kb: dict,
    board: dict,
    charter: dict,
    mode: str,
    prior_label: Optional[str],
    guardrail_notes: list[str],
) -> str:
    now = _now()
    zero_activity = not board["tasks"] and not board["events"]
    lines: list[str] = [
        f"# Weekly review — {slug} — {week}",
        "",
        f"- agent: {slug}",
        f"- week: {week} (ISO)",
        f"- window: {window_start.strftime('%Y-%m-%d')} → {window_end.strftime('%Y-%m-%d')} ({WINDOW_DAYS}d)",
        f"- generated: {now.isoformat()[:16]} by weekly_agent_reviews",
        f"- mode: {mode}",
        f"- prior review: {prior_label or 'none (bootstrap)'}",
        "",
        "## 1. Prior-week accomplishments (evidence/links)",
        "",
    ]
    if parts["accomplishments"]:
        for a in parts["accomplishments"]:
            lines.append(f"- {a['text']}{_refs(a['evidence'])}")
    elif zero_activity and board["available"]:
        stood_up = spend.get("key_created") or "n/a"
        lines.append(
            f"- Agent stood up {stood_up}; no board cards assigned yet "
            "(honest bootstrap state — nothing was done this window)."
        )
    elif zero_activity:
        lines.append(
            "- Board data unavailable this run — no board activity could be "
            "verified (nothing is claimed)."
        )
    else:
        lines.append("- No accomplishments recorded this window.")

    lines += ["", "## 2. KR progress vs trajectory", ""]
    if parts["kr_progress"]:
        for k in parts["kr_progress"]:
            lines.append(
                f"- [{k['objective']}] {k['kr']} — **{k['status']}** "
                f"(target: {k.get('target') or 'n/a'}; cadence: {k.get('cadence') or 'n/a'}) — {k['note']}{_refs(k['evidence'])}"
            )
    else:
        lines.append("- No charter KRs found (charter missing?) — nothing to track.")

    wm = parts["work_mix"]
    lines += [
        "",
        "## 3. Work-mix check (bau vs OKR vs exec + spend)",
        "",
        f"- bau: {wm.get('bau') or 'no board work classified as bau this window'}",
        f"- OKR: {wm.get('okr') or 'no OKR-tagged board work this window'}",
        f"- exec: {wm.get('exec') or 'no exec work this window'}",
        f"- mix note: {wm.get('note') or 'no mix assessment'}",
        f"- {spend.get('line') or 'spend: n/a (source unavailable)'}",
        "",
        "## 4. Quality KR status",
        "",
    ]
    qc = _quality_machine_check(board)
    lines.append(f"- {qc['line']}")
    for q in parts["quality_krs"]:
        lines.append(f"- {q['kr']} — **{q['status']}** — {q['note']}")
    if not parts["quality_krs"] and charter["quality_krs"]:
        for q in charter["quality_krs"]:
            status = "pass" if qc["missing"] == 0 else ("n/a" if qc["total"] == 0 else "fail")
            lines.append(
                f"- {q['name']} — **{status}** — {qc['line']} "
                f"(deterministic; no LLM note)"
            )
    if not parts["quality_krs"] and not charter["quality_krs"]:
        lines.append("- No mandatory quality KRs found in the charter.")

    lines += ["", "## 5. Upcoming plan (proposed cards — suggestions only)", ""]
    if parts["upcoming_plan"]:
        for p in parts["upcoming_plan"]:
            lines.append(f"- {p}")
    else:
        lines.append("- None proposed this window (suggestions only — no cards created here).")

    lines += ["", "## 6. Learnings + domain-KB line", ""]
    if parts["learnings"]:
        for l in parts["learnings"]:
            lines.append(f"- {l['text']}" + (f" — KB: {l['kb_note']}" if l["kb_note"] else ""))
    else:
        lines.append("- No learnings recorded this window.")
    lines.append(f"- {_kb_line(kb)}")

    lines += [
        "",
        "## 7. chuck's feedback",
        "",
        FEEDBACK_PLACEHOLDER,
        "",
    ]
    if guardrail_notes:
        # Count only — the raw dropped refs are kept in the returned
        # guardrail_notes (run log), never echoed into the review doc.
        lines += [
            "---",
            f"_guardrails: {len(guardrail_notes)} deterministic note(s) applied "
            "(invalid evidence refs / non-charter KRs / out-of-window dates "
            "dropped — details in the run log)_",
            "",
        ]
    return "\n".join(lines)


def _fallback_parts(board: dict, charter: dict, kb: dict) -> dict:
    """Deterministic skeleton parts (LLM failure / zero signals)."""
    parts: dict[str, Any] = {
        "accomplishments": [],
        "kr_progress": [],
        "work_mix": {"bau": "", "okr": "", "exec": "", "note": ""},
        "quality_krs": [],
        "upcoming_plan": [],
        "learnings": [],
    }
    for t in board["tasks"]:
        ev = [f"task:{t['id']}"]
        if t["last_commit"]:
            ev.append(f"commit:{t['last_commit']}")
        parts["accomplishments"].append(
            {
                "text": (
                    f"task {t['id']} ({t['project']}): {t['state']} — {t['spec_goal'] or 'no spec goal'}"
                ),
                "evidence": ev,
            }
        )
    for kr in charter["krs"]:
        parts["kr_progress"].append(
            {
                "kr": kr["name"],
                "objective": kr["objective"],
                "status": "no movement",
                "evidence": [],
                "note": "no movement this week (deterministic fallback — no LLM)",
                "target": kr["target"],
                "cadence": kr["cadence"],
            }
        )
    parts["work_mix"] = {
        "bau": "no board work in window" if not board["tasks"] else "see board tasks",
        "okr": "no OKR-tagged board work in window",
        "exec": "no exec work in window",
        "note": "deterministic fallback (LLM unavailable)",
    }
    parts["learnings"] = [
        {"text": "no learnings recorded (deterministic fallback — no LLM)", "kb_note": ""}
    ]
    return parts


def _write_doc(slug: str, week: str, doc: str, template: str) -> Optional[str]:
    try:
        path = _output_path(slug, week, template)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(doc, encoding="utf-8")
        return str(path)
    except OSError as exc:
        logger.warning("weekly_agent_reviews: doc write failed for %s: %s", slug, exc)
        return None


# ---------------------------------------------------------------------------
# Per-agent review + entry point
# ---------------------------------------------------------------------------


def _review_one_agent(
    slug: str, non_stacking: bool, template: str, client: Any, now: datetime,
    force: bool = False,
) -> dict:
    week = _iso_week_label(now)
    current_week = (now.isocalendar()[0], now.isocalendar()[1])

    # --- non-stacking gate ---
    should_run, reason, prior = _non_stacking_gate(slug, current_week, non_stacking, template)
    if not should_run:
        logger.info("weekly_agent_reviews: %s — %s", slug, reason)
        return {
            "agent": slug,
            "status": "skipped",
            "week": week,
            "skip_reason": reason,
            "path": None,
        }

    # --- same-week idempotency guard (one review per week; force to regenerate) ---
    existing = _existing_week_doc(slug, week, template)
    if existing is not None and not force:
        logger.info(
            "weekly_agent_reviews: %s — this week's review already exists (%s); "
            "force=true to regenerate", slug, existing,
        )
        return {
            "agent": slug,
            "status": "skipped",
            "week": week,
            "skip_reason": f"this week's review already exists ({existing}) — pass force=true to regenerate",
            "path": str(existing),
        }

    window_start = now - timedelta(days=WINDOW_DAYS)
    window_start_ms = int(window_start.timestamp() * 1000)

    # --- deterministic collection (all best-effort) ---
    board = _collect_board(slug, window_start_ms)
    charter = _parse_charter(slug)
    org = _parse_org_goals()
    kb = _collect_kb(client, slug, window_start)
    spend = _collect_spend(slug)
    prior_text = prior["text"] if prior else None
    prior_label = f"{prior['path'].name} (week {prior['week'][0]}-W{prior['week'][1]:02d})" if prior else None

    # --- ONE LLM synthesis call (deterministic fallback on failure) ---
    analysis = _analyze(
        slug, week, window_start, now, board, charter, org, kb, spend, prior_text
    )
    if analysis is None:
        parts = _fallback_parts(board, charter, kb)
        synthesis = "deterministic-fallback"
        notes: list[str] = ["LLM synthesis unavailable — deterministic skeleton written"]
    else:
        allowed = _allowed_dates(slug, prior_text, window_start, now)
        zero_activity = not board["tasks"] and not board["events"]
        parts, notes = _guardrail_filter(
            analysis, board, charter, allowed, window_start, now, zero_activity
        )
        synthesis = "llm"

    mode = f"{'bootstrap' if prior is None else 'delta'} + {synthesis}"
    doc = _render_doc(
        slug, week, window_start, now, parts, spend, kb, board, charter, mode,
        prior_label, notes,
    )
    path = _write_doc(slug, week, doc, template)
    if path is None:
        return {
            "agent": slug,
            "status": "error",
            "error": "failed to write the review doc",
            "week": week,
            "path": None,
        }
    return {
        "agent": slug,
        "status": "generated",
        "week": week,
        "mode": mode,
        "gate_reason": reason,
        "path": path,
        "guardrail_notes": notes,
        "inputs": {
            "board_tasks": len(board["tasks"]),
            "board_events": len(board["events"]),
            "charter_krs": len(charter["krs"]),
            "kb_docs_in_window": len(kb["docs_in_window"]),
            "spend": spend.get("spend"),
        },
    }


def run(params: dict, job: Any, client: Any = None) -> dict:
    """Weekly 7-part review for each ACTIVE agent (non-stacking gated).

    Conforms to the `weekly-agent-reviews` schedule params: agents list,
    output template docs/agents/<slug>/reviews/YYYY-WW.md, the 7-part parts
    list (informational — the doc format is canonical so the gate can read
    part 7), non_stacking=true.
    """
    agents = params.get("agents")
    if agents is None:
        agents = DEFAULT_AGENTS
    if isinstance(agents, str):
        if "," in agents:  # tolerate a comma-separated string (n8n convenience)
            agents = [p.strip() for p in agents.split(",") if p.strip()]
        else:
            return {
                "error": "params.agents must be a list of agent slugs "
                f"(got a bare string: {agents!r} — pass e.g. [\"product\"])"
            }
    if not isinstance(agents, list):
        return {"error": f"params.agents must be a list (got {type(agents).__name__})"}
    agents = [str(a).strip().lower() for a in agents if str(a).strip()]
    if not agents:
        return {"error": "no agents to review (params.agents empty)"}
    non_stacking = bool(params.get("non_stacking", True))
    force = bool(params.get("force", False))
    template = str(params.get("output") or DEFAULT_OUTPUT_TEMPLATE)
    now = _now()
    week = _iso_week_label(now)

    if job is not None and hasattr(job, "add_log"):
        job.add_log(
            f"weekly_agent_reviews: agents={agents} week={week} "
            f"non_stacking={non_stacking} force={force} output={template}"
        )

    results: list[dict] = []
    for slug in agents:
        if slug in INACTIVE_AGENTS:
            logger.info(
                "weekly_agent_reviews: %s is OFF (Q13) — never targeted; skipping", slug
            )
            results.append(
                {
                    "agent": slug,
                    "status": "skipped",
                    "week": week,
                    "skip_reason": "agent is OFF (Q13 — not active; never targeted)",
                    "path": None,
                }
            )
            continue
        try:
            results.append(_review_one_agent(slug, non_stacking, template, client, now, force))
        except Exception as exc:  # noqa: BLE001 - one agent's failure never kills the run
            logger.exception("weekly_agent_reviews: unhandled error for %s", slug)
            results.append(
                {"agent": slug, "status": "error", "error": str(exc), "week": week, "path": None}
            )

    generated = [r for r in results if r.get("status") == "generated"]
    skipped = [r for r in results if r.get("status") == "skipped"]
    errors = [r for r in results if r.get("status") == "error"]
    summary = (
        f"weekly_agent_reviews {week}: {len(generated)} generated, "
        f"{len(skipped)} skipped, {len(errors)} error(s) — "
        + ", ".join(
            f"{r['agent']}={r['status']}" + (f" ({r.get('skip_reason') or r.get('error') or ''})" if r["status"] != "generated" else "")
            for r in results
        )
    )
    if job is not None and hasattr(job, "add_log"):
        job.add_log(summary)
    logger.info(summary)

    result: dict[str, Any] = {
        "summary": summary,
        "agents": results,
        "week": week,
        "artifact_path": generated[0]["path"] if generated else None,
    }
    if errors and not generated:
        result["error"] = f"all agents failed: {'; '.join(r.get('error', '?') for r in errors)}"
    return result
