#!/usr/bin/env python3
"""
monthly_org_review skill — monthly org review (KR scoring + retro + goal
adaptation + domain-KB staleness pass).

Purpose:
  The cron `monthly-org-review` (scheduler/schedules.json) fires every
  Friday 15:00 America/Chicago. CAVEAT (from the schedule note): the
  skill-runner scheduler uses standard-cron OR semantics for
  day/day-of-week, so `0 15 1-7 * 5` fires EVERY Friday. THIS SKILL OWNS
  THE GATE: it runs only on the FIRST Friday of the month (UTC); on any
  other Friday it returns
      {"status": "skipped", "reason": "not the first Friday of <Month YYYY> ..."}
  and writes nothing. The gate is deterministic (date arithmetic only —
  no I/O, no LLM) and is the skill's responsibility, not the cron's.

  When it runs (first Friday), it produces the monthly org review — the
  ONLY scheduled place org goals may change (docs/org/goals.md cadence
  note, 2026-11-24):

    1. KR scoring 0-1 per org KR (WITH evidence refs — only real refs)
    2. Retro (what worked / what didn't / process friction)
    3. Goal adaptation — a full PROPOSED rewrite of docs/org/goals.md
       for the next cycle (rewrite at the cycle boundary, don't append)
    4. Domain-KB staleness pass — superseded/stale KB facts listed as
       kb_forget CANDIDATES with evidence

Conservative application (safety — the default is PROPOSALS ONLY):
  - the review doc is written to docs/org/reviews/YYYY-MM.md
  - the proposed goals rewrite is written to the sidecar
    docs/org/goals.proposed-YYYY-MM.md
  - docs/org/goals.md is NOT overwritten UNLESS params.apply_goals=true
  - kb_forget is NOT called UNLESS params.apply_kb_forget=true
  Both params default to false — chuck applies them after reading the
  review (org-doc edits are single-approval per the Q7 autonomy table;
  the review doc is the approval record). If apply_goals=true but the
  proposed rewrite failed the guardrail checks, goals.md is NOT touched.

force_date (ops/test override): params.force_date="YYYY-MM-DD" runs the
review for that date INSTEAD OF TODAY (the cron never sets it; forced
runs use it together with a TEMP output path). The first-Friday gate
STILL APPLIES to the forced date — it must be the first Friday of its
month (e.g. force_date="2026-12-04" from a 4th-Friday run day).

Data collection (deterministic, best-effort — a missing source degrades
to an honest "no data" line, never a failure):
  - docs/org/goals.md — all domains, all objectives, all KRs
    (definition / source / target / cadence)
  - the month's agent weekly reviews (docs/agents/*/reviews/*.md whose
    ISO week overlaps the calendar month)
  - board (MySQL ai_kanban, KANBAN_DB_* env; bigint ms timestamps —
    verified 2026-11-27 against live rows): done cards in the month
    (state='done' + state_changed_at in month), per-project done counts,
    agent-owned cards (owner = executor identity) per project/state
  - the latest alignment report (docs/org/alignment/<date>-*.md) if present
  - domain KB: via the injected MCP client (server_id="mcp_knowledge") —
    kb_list_documents (all KBs) for collections/recency + one kb_search
    per goals domain for current facts. Empty/missing collections are
    handled gracefully.

LLM: ONE synthesis call (urllib to LITELLM_BASE_URL + LITELLM_API_KEY,
model "matrix-coder" — the harness_reflection client-wrapper pattern:
tolerate a stray fence, strict JSON, degrade to a deterministic skeleton
on any failure). Deterministic guardrails on the output (never trust it):
KRs restricted to the goals.md list (domain+objective+num, or exact name
within the domain); scores must be numeric and are clamped to [0,1];
evidence refs must match real board card ids / real commit shas / real
file paths / real weekly-review paths (invalid refs dropped + noted);
the proposed goals rewrite must cover every domain in the current
goals.md (else it is rejected and the sidecar says "no change proposed");
every kb_forget candidate needs a known KB collection (when collections
are known) + at least one valid evidence ref.

kb_forget application (only with params.apply_kb_forget=true): the
server's two-step semantic delete per candidate — step 1
kb_forget(query=fact, kb) returns matches and deletes NOTHING; step 2
kb_forget(confirm=true, ids=[top match id]) deletes at most ONE point per
candidate. Manifests are never deleted (the server enforces it).

Output:
  docs/org/reviews/YYYY-MM.md (calendar month of the run date) + the
  sidecar docs/org/goals.proposed-YYYY-MM.md (banner + proposed rewrite,
  or an explicit "no change proposed" + the current baseline).

Constraints:
  - Writes ONLY to docs/org/reviews/, the goals sidecar, and (explicit
    params only) docs/org/goals.md.
  - Read-only w.r.t. the board. KB writes ONLY via the two-step
    kb_forget with the explicit param.
  - Max runtime: 300 seconds.
"""

import json
import logging
import os
import re
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("skill.monthly_org_review")

# ---------------------------------------------------------------------------
# Configuration (env + skill.yml config)
# ---------------------------------------------------------------------------

REPO_ROOT = Path(os.environ.get("MONTHLY_ORG_REVIEW_REPO_ROOT", "/home/chuck/homelab"))
MODEL_ALIAS = os.environ.get("MONTHLY_ORG_REVIEW_MODEL_ALIAS", "matrix-coder")
LITELLM_BASE_URL = os.environ.get("LITELLM_BASE_URL", "http://litellm-proxy:4000").rstrip("/")
LLM_TIMEOUT = int(os.environ.get("MONTHLY_ORG_REVIEW_LLM_TIMEOUT", "120"))

DEFAULT_OUTPUT = "docs/org/reviews/YYYY-MM.md"
DEFAULT_SIDECAR = "docs/org/goals.proposed-YYYY-MM.md"

MAX_WEEKLY_REVIEWS = 12
MAX_REVIEW_CHARS = 2500
MAX_ALIGNMENT_CHARS = 4000
MAX_BOARD_CARDS = 100
MAX_DONE_IN_MONTH = 50
MAX_KB_HITS_PER_DOMAIN = 10
MAX_PAYLOAD_CHARS = 20000
MAX_PROPOSED_GOALS_CHARS = 20000
MAX_KB_CANDIDATES = 10
MAX_BULLET_CHARS = 300
MAX_EVIDENCE_PER_ITEM = 5
MAX_GOALS_CHANGE_ITEMS = 10

# Evidence-ref grammar (deterministic guardrail):
#   task:<id>    — a real board card id collected for the month
#   commit:<sha> — a real last_commit sha collected for the agent-owned cards
#   file:<path>  — a real repo-relative file path (must exist)
#   review:<agent>/<YYYY-WW> — a real weekly review collected for the month
EVIDENCE_REF_RE = re.compile(r"^(task|commit|file|review):[A-Za-z0-9._/\-]+$")
WEEK_FILE_RE = re.compile(r"^(\d{4})-W(\d{2})\.md$")
_KR_TABLE_ROW_RE = re.compile(r"^\s*\|\s*(\d+)\s*\|")
_OBJECTIVE_LINE_RE = re.compile(r"^\*\*(O\d+)\s*—\s*(.*)$")
_FORCE_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

REVIEW_PROMPT = """You are the monthly org-review analyst for a small AI org.
Write the monthly org review for {month} (window {mstart} to {mend}, calendar month) as STRICT JSON.

INPUTS (the ONLY facts you may use — never invent anything else):
- ORG GOALS: docs/org/goals.md — every domain, objective, and KR (definition / source / target / cadence)
- WEEKLY REVIEWS: the month's agent weekly reviews (7-part docs; part 7 may be an empty placeholder)
- BOARD: done cards in the month (per project) + agent-owned cards (owner = executor identity)
- ALIGNMENT: the latest OKR alignment report (may be null)
- KB: domain-KB collections + current facts (may be empty or not exist yet)

Return STRICT JSON (no markdown fences, no commentary) with exactly these keys:
{{
  "kr_scores": [{{"domain": "<exact domain name>", "objective": "O#", "num": <int>, "kr": "<exact KR name>", "score": <number 0.0-1.0>, "evidence": ["task:<id>", "commit:<sha>", "file:<repo path>", "review:<agent>/<YYYY-WW>"], "note": "<one line: evidence vs target vs cadence>"}}],
  "retro": {{"worked": ["<one line>"], "didnt": ["<one line>"], "friction": ["<one line>"]}},
  "goal_adaptation": {{"rationale": "<2-3 lines: what changes for the next cycle and why>", "changes": ["<one line per change>"], "proposed_goals_md": "<the FULL proposed markdown rewrite of docs/org/goals.md for the next cycle>"}},
  "kb_staleness": [{{"kb": "<collection name from the KB input, or null>", "fact": "<the stale/superseded fact text>", "reason": "<one line: why stale>", "evidence": ["<ref>"]}}]
}}

Rules (violating items are dropped by deterministic guardrails):
- kr_scores: cover EVERY KR in the ORG GOALS input (exact domain / objective / num / name). score is a NUMBER 0.0-1.0 (0.0 = no evidence of progress toward the target; 1.0 = target met with evidence). Honest low scores are the norm early in a cycle — do not inflate.
- Evidence refs use ONLY these forms and ONLY real ids/paths from the INPUTS: task:<board card id from the BOARD input>, commit:<commit sha from the BOARD input>, file:<repo-relative path that exists>, review:<agent>/<ISO week> for a weekly review in the WEEKLY REVIEWS input. Never invent refs.
- retro: grounded in the inputs only (weekly reviews + board + alignment); one line per item; an empty list is valid.
- goal_adaptation.proposed_goals_md: a FULL rewrite of docs/org/goals.md for the next cycle (next calendar month) — same document structure ('# Org Goals' header, a '## Cycle <YYYY-MM>' header, '### <domain>' sections, '**O# — ...**' objectives, 6-column KR tables with # / KR / Definition / Source / Target / Cadence). Rewrite at the cycle boundary — do NOT append. Keep every domain from the current goals.md; keep a mandatory quality KR on every objective; keep 'proxy' marks where data sources are not wired; carry forward KRs that are still open (update target/cadence as justified by the inputs).
- kb_staleness: only facts genuinely superseded/stale per the inputs (newer weekly reviews or board state contradicting them); each candidate needs at least one evidence ref. An empty list is valid.
- If an input is empty, write the honest empty state. Do not pad."""


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


def _month_bounds(ref: datetime) -> tuple[datetime, datetime]:
    """[month start, next month start) in UTC for ref's calendar month."""
    mstart = datetime(ref.year, ref.month, 1, tzinfo=timezone.utc)
    if ref.month == 12:
        mend = datetime(ref.year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        mend = datetime(ref.year, ref.month + 1, 1, tzinfo=timezone.utc)
    return mstart, mend


def _month_end_date(ref: datetime) -> date:
    mstart, _ = _month_bounds(ref)
    return (mstart + timedelta(days=32)).replace(day=1).date() - timedelta(days=1)


def _resolve_template(template: str, month_label: str) -> Path:
    t = str(template or DEFAULT_OUTPUT).replace("YYYY-MM", month_label)
    return REPO_ROOT / t


# ---------------------------------------------------------------------------
# First-Friday gate (deterministic — the skill's responsibility)
# ---------------------------------------------------------------------------


def _first_friday_of_month(year: int, month: int) -> date:
    """The first Friday of the given month (Friday = weekday 4)."""
    first = date(year, month, 1)
    return first + timedelta(days=(4 - first.weekday()) % 7)


def _is_first_friday(d: date) -> bool:
    return d.weekday() == 4 and d.day == _first_friday_of_month(d.year, d.month).day


def _ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _gate(ref: datetime) -> tuple[bool, str]:
    """(should_run, reason) for the reference datetime (UTC)."""
    d = ref.date()
    if _is_first_friday(d):
        return True, f"first Friday of {d.strftime('%B %Y')} ({d.isoformat()})"
    ff = _first_friday_of_month(d.year, d.month)
    if d.weekday() != 4:
        return (
            False,
            f"not the first Friday of {d.strftime('%B %Y')} (today "
            f"{d.isoformat()} is a {d.strftime('%A')}, not a Friday; first "
            f"Friday was {ff.isoformat()})",
        )
    n = (d.day - ff.day) // 7 + 1
    return (
        False,
        f"not the first Friday of {d.strftime('%B %Y')} (today "
        f"{d.isoformat()} is the {_ordinal(n)} Friday; first Friday was "
        f"{ff.isoformat()})",
    )


# ---------------------------------------------------------------------------
# Org goals (docs/org/goals.md — markdown KR-table parsing)
# ---------------------------------------------------------------------------


def _clean_cell(value: str) -> str:
    return re.sub(r"\*{1,2}", "", str(value or "")).strip()


def _parse_org_goals() -> dict:
    """All domains / objectives / KRs from docs/org/goals.md.

    Structure (see the live doc): '### <domain>' sections, '**O# — text**'
    objective lines (may span two lines), 6-column KR tables
    (# | KR | Definition | Source | Target | Cadence). Other tables
    (e.g. the 3-column 'Coverage' table) are ignored by the 6-column
    check. A '## ' heading ends the current domain context.
    """
    path = REPO_ROOT / "docs" / "org" / "goals.md"
    out: dict[str, Any] = {
        "path": str(path),
        "found": False,
        "cycle": "",
        "domains": {},
        "all_krs": [],
    }
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        logger.warning("monthly_org_review: org goals not found: %s", path)
        return out
    out["found"] = True
    domain = ""
    current_obj = ""
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        dm = re.match(r"^###\s+(.+?)\s*$", line)
        if dm:
            domain = dm.group(1)
            current_obj = ""
            i += 1
            continue
        if re.match(r"^##\s+", line):
            hm = re.match(r"^##\s+Cycle\s+(\S+)", line)
            if hm:
                out["cycle"] = hm.group(1)
            domain = ""
            current_obj = ""
            i += 1
            continue
        om = _OBJECTIVE_LINE_RE.match(line.strip())
        if om:
            current_obj = om.group(1)
            obj_text = om.group(2)
            j = i + 1
            while j < len(lines) and "**" not in obj_text and j - i < 4:
                obj_text += " " + lines[j].strip()
                j += 1
            if domain:
                out["domains"].setdefault(domain, {}).setdefault("objectives", []).append(
                    {"id": current_obj, "text": _clean_cell(obj_text)[:200]}
                )
            i = j
            continue
        if line.lstrip().startswith("|") and _KR_TABLE_ROW_RE.match(line):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) >= 6 and domain and current_obj:
                kr = {
                    "domain": domain,
                    "objective": current_obj,
                    "num": int(cells[0]),
                    "name": _clean_cell(cells[1])[:120],
                    "definition": _clean_cell(cells[2])[:200],
                    "source": _clean_cell(cells[3])[:120],
                    "target": _clean_cell(cells[4])[:120],
                    "cadence": _clean_cell(cells[5])[:60],
                }
                out["all_krs"].append(kr)
                out["domains"].setdefault(domain, {}).setdefault("krs", []).append(kr)
        i += 1
    return out


# ---------------------------------------------------------------------------
# Agent weekly reviews for the month (docs/agents/*/reviews/*.md)
# ---------------------------------------------------------------------------


def _collect_weekly_reviews(year: int, month: int) -> list[dict]:
    """Weekly review docs whose ISO week overlaps the calendar month."""
    out: list[dict] = []
    agents_dir = REPO_ROOT / "docs" / "agents"
    if not agents_dir.is_dir():
        return out
    mstart = date(year, month, 1)
    if month == 12:
        mend = date(year + 1, 1, 1)
    else:
        mend = date(year, month + 1, 1)
    try:
        agent_dirs = sorted(p for p in agents_dir.iterdir() if p.is_dir())
    except OSError:
        return out
    for ad in agent_dirs:
        reviews = ad / "reviews"
        if not reviews.is_dir():
            continue
        try:
            files = sorted(reviews.iterdir())
        except OSError:
            continue
        for f in files:
            if not f.is_file():
                continue
            m = WEEK_FILE_RE.match(f.name)
            if not m:
                continue
            y, w = int(m.group(1)), int(m.group(2))
            try:
                monday = date.fromisocalendar(y, w, 1)
            except ValueError:
                continue
            sunday = monday + timedelta(days=6)
            if sunday < mstart or monday >= mend:
                continue  # no overlap with the month
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            out.append(
                {
                    "agent": ad.name,
                    "week": f"{y}-W{w:02d}",
                    "path": str(f.relative_to(REPO_ROOT)),
                    "text": text[:MAX_REVIEW_CHARS],
                }
            )
            if len(out) >= MAX_WEEKLY_REVIEWS:
                return out
    return out


# ---------------------------------------------------------------------------
# Board (MySQL ai_kanban — harness_reflection _db_conn() pattern)
# ---------------------------------------------------------------------------


def _db_conn():
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


def _collect_board(mstart_ms: int, mend_ms: int) -> dict:
    """Board state for the month: done cards (state_changed_at in month),
    per-project done counts, agent-owned cards (owner = executor identity).
    Degrades to an empty (available=False) dict on any failure."""
    out: dict[str, Any] = {
        "available": False,
        "cards": [],
        "done_in_month": [],
        "done_by_project": {},
        "agent_owned": [],
    }
    try:
        conn = _db_conn()
    except Exception as exc:  # noqa: BLE001 - degrade, never fail the run
        logger.warning("monthly_org_review: board DB unavailable: %s", exc)
        return out
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT t.id, t.owner, t.state_changed_at, p.name
                FROM tasks t
                JOIN projects p ON p.id = t.project_id
                WHERE t.state = 'done'
                  AND t.state_changed_at >= %s AND t.state_changed_at < %s
                ORDER BY t.id
                LIMIT %s
                """,
                (mstart_ms, mend_ms, MAX_DONE_IN_MONTH),
            )
            for r in cur.fetchall():
                out["done_in_month"].append(
                    {
                        "id": int(r[0]),
                        "owner": str(r[1]),
                        "state_changed_at": _ms_to_iso(r[2]),
                        "project": str(r[3]),
                    }
                )
            out["done_by_project"] = {}
            for d in out["done_in_month"]:
                out["done_by_project"][d["project"]] = out["done_by_project"].get(d["project"], 0) + 1
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT t.id, t.owner, t.state, t.last_commit, p.name
                FROM tasks t
                JOIN projects p ON p.id = t.project_id
                ORDER BY t.id
                LIMIT %s
                """,
                (MAX_BOARD_CARDS,),
            )
            for r in cur.fetchall():
                out["cards"].append(
                    {
                        "id": int(r[0]),
                        "owner": str(r[1]),
                        "state": str(r[2]),
                        "last_commit": str(r[3] or ""),
                        "project": str(r[4]),
                    }
                )
        grouped: dict[tuple[str, str, str], int] = {}
        for c in out["cards"]:
            key = (c["project"], c["owner"], c["state"])
            grouped[key] = grouped.get(key, 0) + 1
        out["agent_owned"] = [
            {"project": k[0], "owner": k[1], "state": k[2], "count": v}
            for k, v in sorted(grouped.items())
        ]
        out["available"] = True
    except Exception as exc:  # noqa: BLE001
        logger.warning("monthly_org_review: board query failed: %s", exc)
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass
    return out


# ---------------------------------------------------------------------------
# Alignment report (docs/org/alignment/<date>-*.md — latest)
# ---------------------------------------------------------------------------


def _latest_alignment_report() -> dict:
    d = REPO_ROOT / "docs" / "org" / "alignment"
    out: dict[str, Any] = {"found": False, "path": None, "text": None}
    try:
        if not d.is_dir():
            return out
        files = sorted(f for f in d.iterdir() if f.is_file() and f.suffix == ".md")
    except OSError:
        return out
    if not files:
        return out
    f = files[-1]  # dated filenames sort lexicographically
    try:
        text = f.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    out.update({"found": True, "path": str(f.relative_to(REPO_ROOT)), "text": text[:MAX_ALIGNMENT_CHARS]})
    return out


# ---------------------------------------------------------------------------
# Domain KB (injected MCP client — mcp_knowledge; best-effort)
# ---------------------------------------------------------------------------


def _kb_doc_list(res: Any) -> list[dict]:
    """Tolerant extraction of the document list from kb_list_documents
    ({"documents": {col: [docs]}} / list / docs carrying their own 'kb')."""
    if not isinstance(res, dict):
        return []
    docs = res.get("documents")
    out: list[dict] = []
    if isinstance(docs, dict):
        for kb, v in docs.items():
            if isinstance(v, list):
                for d in v:
                    if isinstance(d, dict):
                        d2 = dict(d)
                        d2.setdefault("kb", str(kb))
                        out.append(d2)
    elif isinstance(docs, list):
        out.extend(d for d in docs if isinstance(d, dict))
    return out


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


def _collect_kb(client: Any, domains: list[str], mstart: datetime, mend: datetime) -> dict:
    """Domain-KB state for the staleness pass: collections + recency
    (kb_list_documents, all KBs) + current facts (one kb_search per goals
    domain, all-KB scope). Best-effort — failures degrade to honest notes.
    """
    out: dict[str, Any] = {
        "available": False,
        "collections": {},
        "ingested_in_month": {},
        "facts": [],
        "note": "",
    }
    if client is None:
        out["note"] = "no MCP client injected — KB unavailable"
        return out
    try:
        res = client.mcp_call("kb_list_documents", {}, server_id="mcp_knowledge")
        for doc in _kb_doc_list(res):
            kb = str(doc.get("kb") or "unknown")
            out["collections"][kb] = out["collections"].get(kb, 0) + 1
            ing = _parse_iso(doc.get("ingested_at"))
            if ing is not None and mstart <= ing < mend:
                out["ingested_in_month"][kb] = out["ingested_in_month"].get(kb, 0) + 1
        out["available"] = True
    except Exception as exc:  # noqa: BLE001 - degrade, never fail the run
        out["note"] = f"kb_list_documents failed: {str(exc)[:120]}"
    for domain in domains[:4]:
        try:
            res = client.mcp_call(
                "kb_search",
                {
                    "query": f"{domain} domain facts targets decisions status",
                    "top_k": MAX_KB_HITS_PER_DOMAIN,
                },
                server_id="mcp_knowledge",
            )
            hits, note = _kb_search_hits(res)
            for h in hits[:MAX_KB_HITS_PER_DOMAIN]:
                out["facts"].append(
                    {
                        "kb": str(h.get("kb") or ""),
                        "source": str(h.get("source") or "")[:160],
                        "snippet": str(h.get("snippet") or "")[:200],
                    }
                )
            if note and not out["note"]:
                out["note"] = note[:160]
        except Exception as exc:  # noqa: BLE001
            out["note"] = out["note"] or f"kb_search failed: {str(exc)[:120]}"
    return out


def _kb_line(kb: dict) -> str:
    """The deterministic domain-KB line for part 4."""
    if not kb.get("available"):
        return f"KB: n/a ({kb.get('note') or 'source unavailable'})"
    if not kb.get("collections"):
        return "KB: no collections exist yet — nothing to check for staleness"
    bits = ", ".join(f"{k} ({v} doc(s))" for k, v in sorted(kb["collections"].items()))
    line = f"KB collections: {bits}"
    ing = kb.get("ingested_in_month") or {}
    if ing:
        line += "; ingested this month: " + ", ".join(f"{k} ({v})" for k, v in sorted(ing.items()))
    line += f"; {len(kb.get('facts') or [])} current fact(s) sampled"
    return line


# ---------------------------------------------------------------------------
# LLM synthesis (ONE call — urllib to LITELLM_BASE_URL, matrix-coder)
# ---------------------------------------------------------------------------


def _llm_chat(messages: list[dict]) -> Optional[str]:
    """One chat completion. Returns the content string, or None on any
    failure (the caller degrades to the deterministic skeleton)."""
    api_key = os.environ.get("LITELLM_API_KEY", "")
    if not (LITELLM_BASE_URL and api_key):
        logger.warning(
            "monthly_org_review: LITELLM_BASE_URL/LITELLM_API_KEY unset — LLM unavailable"
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
        logger.warning("monthly_org_review: LLM call failed: %s", exc)
        return None


def _analysis_payload(
    month_label: str,
    mstart: datetime,
    mend: datetime,
    goals: dict,
    reviews: list[dict],
    board: dict,
    alignment: dict,
    kb: dict,
) -> str:
    payload = {
        "month": month_label,
        "window": {"start": mstart.strftime("%Y-%m-%d"), "end": _month_end_date(mstart).isoformat()},
        "org_goals": {
            "found": goals["found"],
            "cycle": goals["cycle"],
            "domains": goals["domains"],
        },
        "weekly_reviews": reviews,
        "board": {
            "available": board["available"],
            "done_in_month": board["done_in_month"],
            "done_by_project": board["done_by_project"],
            "agent_owned": board["agent_owned"],
        },
        "alignment": alignment,
        "kb": kb,
    }
    return json.dumps(payload, indent=1, default=str)[:MAX_PAYLOAD_CHARS]


def _analyze(
    month_label: str,
    mstart: datetime,
    mend: datetime,
    goals: dict,
    reviews: list[dict],
    board: dict,
    alignment: dict,
    kb: dict,
) -> Optional[dict]:
    """ONE LLM call -> the 4-part review JSON (None on any failure)."""
    prompt = REVIEW_PROMPT.format(
        month=month_label,
        mstart=mstart.strftime("%Y-%m-%d"),
        mend=_month_end_date(mstart).isoformat(),
    )
    messages = [
        {
            "role": "system",
            "content": (
                "You are a precise, conservative monthly org-review analyst. "
                "You output strict JSON only. You never invent KRs, scores, "
                "evidence refs, or KB facts. You propose — you never apply."
            ),
        },
        {
            "role": "user",
            "content": (
                f"{prompt}\n\nINPUTS:\n"
                + _analysis_payload(month_label, mstart, mend, goals, reviews, board, alignment, kb)
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
        logger.warning("monthly_org_review: LLM output was not valid JSON")
        return None
    if not isinstance(data, dict):
        return None
    out: dict[str, Any] = {}
    for key in ("kr_scores", "goal_adaptation", "kb_staleness"):
        val = data.get(key)
        out[key] = val if isinstance(val, (list, dict)) else ([] if key != "goal_adaptation" else {})
    retro = data.get("retro")
    out["retro"] = retro if isinstance(retro, dict) else {}
    return out


# ---------------------------------------------------------------------------
# Deterministic guardrails (never trust the LLM output)
# ---------------------------------------------------------------------------


def _validate_evidence(
    refs: Any, board: dict, reviews: list[dict], repo_root: Path
) -> tuple[list[str], list[str]]:
    """Keep only refs matching the grammar AND pointing at real data.
    Returns (valid, dropped)."""
    task_ids = {str(c["id"]) for c in board.get("cards") or []}
    commits = {c["last_commit"] for c in board.get("cards") or [] if c.get("last_commit")}
    review_refs = {f"review:{r['agent']}/{r['week']}" for r in reviews or []}
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
        if kind == "review" and ref not in review_refs:
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


def _guardrail_filter(
    analysis: dict, goals: dict, board: dict, reviews: list[dict], kb: dict
) -> tuple[dict, list[str]]:
    """Apply the deterministic guardrails to the LLM output. Returns
    (filtered, notes)."""
    notes: list[str] = []
    out: dict[str, Any] = {
        "kr_scores": [],
        "retro": {"worked": [], "didnt": [], "friction": []},
        "goal_adaptation": {
            "rationale": "",
            "changes": [],
            "proposed_goals_md": "",
            "proposed_ok": False,
        },
        "kb_staleness": [],
    }

    # --- kr_scores: goals.md KR list + numeric clamped scores + real refs ---
    kr_by_key: dict[tuple[str, str, int], dict] = {
        (k["domain"], k["objective"], k["num"]): k for k in goals["all_krs"]
    }
    covered: set[tuple[str, str, int]] = set()
    for item in analysis.get("kr_scores") or []:
        if not isinstance(item, dict):
            continue
        dom = str(item.get("domain") or "").strip()
        obj = str(item.get("objective") or "").strip().upper()
        num_raw = item.get("num")
        kr: Optional[dict] = None
        try:
            if dom and obj and num_raw is not None:
                kr = kr_by_key.get((dom, obj, int(num_raw)))
        except (TypeError, ValueError):
            kr = None
        if kr is None:
            name = str(item.get("kr") or "").strip().lower()
            for k in goals["all_krs"]:
                if k["name"].lower() == name and (not dom or k["domain"] == dom):
                    kr = k
                    break
        if kr is None:
            notes.append(
                "dropped KR score (not in goals.md): "
                f"{str(item.get('kr') or item.get('domain'))[:60]}"
            )
            continue
        key = (kr["domain"], kr["objective"], kr["num"])
        if key in covered:
            notes.append(f"dropped duplicate KR score: {kr['name'][:60]}")
            continue
        try:
            score = float(item.get("score"))
        except (TypeError, ValueError):
            notes.append(f"dropped KR score (non-numeric score): {kr['name'][:60]}")
            continue
        if score < 0 or score > 1:
            score = max(0.0, min(1.0, score))
            notes.append(f"clamped KR score to [0,1]: {kr['name'][:60]}")
        valid, dropped = _validate_evidence(item.get("evidence"), board, reviews, REPO_ROOT)
        if dropped:
            notes.append(
                f"dropped {len(dropped)} invalid evidence ref(s) "
                f"({', '.join(dropped[:3])}) on KR: {kr['name'][:50]}"
            )
        covered.add(key)
        out["kr_scores"].append(
            {
                "domain": kr["domain"],
                "objective": kr["objective"],
                "num": kr["num"],
                "kr": kr["name"],
                "score": round(score, 2),
                "evidence": valid,
                "note": str(item.get("note") or "").strip()[:200] or "no note",
                "target": kr["target"],
                "cadence": kr["cadence"],
            }
        )
    # Every goals.md KR must appear (honest n/a fill-in).
    for k in goals["all_krs"]:
        key = (k["domain"], k["objective"], k["num"])
        if key in covered:
            continue
        out["kr_scores"].append(
            {
                "domain": k["domain"],
                "objective": k["objective"],
                "num": k["num"],
                "kr": k["name"],
                "score": None,
                "evidence": [],
                "note": "no evidence this cycle (deterministic fill-in)",
                "target": k["target"],
                "cadence": k["cadence"],
            }
        )

    # --- retro: bounded strings ---
    retro = analysis.get("retro") or {}
    for k in ("worked", "didnt", "friction"):
        for item in retro.get(k) or []:
            t = str(item).strip()[:MAX_BULLET_CHARS]
            if t:
                out["retro"][k].append(t)

    # --- goal_adaptation: proposed rewrite must cover every domain ---
    ga = analysis.get("goal_adaptation") or {}
    rationale = str(ga.get("rationale") or "").strip()[:400]
    changes = [
        str(c).strip()[:200] for c in (ga.get("changes") or []) if str(c).strip()
    ][:MAX_GOALS_CHANGE_ITEMS]
    proposed = str(ga.get("proposed_goals_md") or "").strip()
    proposed_ok = False
    if proposed and len(proposed) <= MAX_PROPOSED_GOALS_CHARS:
        # The rewrite must carry every current domain as a '### <domain>'
        # heading line (the required doc structure) — a prose mention is
        # not enough.
        missing = [
            d for d in goals["domains"]
            if not re.search(rf"^###\s+{re.escape(d)}\s*$", proposed, re.MULTILINE)
        ]
        if not missing:
            proposed_ok = True
        else:
            notes.append(
                f"proposed goals rewrite missing domain(s) {missing} — rejected "
                "(sidecar says 'no change proposed')"
            )
    elif proposed:
        notes.append(
            f"proposed goals rewrite too large ({len(proposed)} chars) — rejected"
        )
    out["goal_adaptation"] = {
        "rationale": rationale,
        "changes": changes,
        "proposed_goals_md": proposed if proposed_ok else "",
        "proposed_ok": proposed_ok,
    }

    # --- kb_staleness: known collections + at least one valid evidence ref ---
    known_kbs = set((kb.get("collections") or {}).keys())
    for item in (analysis.get("kb_staleness") or [])[:MAX_KB_CANDIDATES]:
        if not isinstance(item, dict):
            continue
        kbname = str(item.get("kb") or "").strip()
        fact = str(item.get("fact") or "").strip()[:300]
        reason = str(item.get("reason") or "").strip()[:200]
        if not fact:
            continue
        if kbname and known_kbs and kbname not in known_kbs:
            notes.append(f"dropped kb candidate (unknown collection {kbname})")
            continue
        valid, dropped = _validate_evidence(item.get("evidence"), board, reviews, REPO_ROOT)
        if dropped:
            notes.append(
                f"dropped {len(dropped)} invalid evidence ref(s) "
                f"({', '.join(dropped[:3])}) on kb candidate: {fact[:50]}"
            )
        if not valid:
            notes.append(f"dropped kb candidate (no valid evidence): {fact[:60]}")
            continue
        out["kb_staleness"].append(
            {"kb": kbname or None, "fact": fact, "reason": reason, "evidence": valid}
        )

    return out, notes


# ---------------------------------------------------------------------------
# kb_forget application (TWO-STEP — only with params.apply_kb_forget=true)
# ---------------------------------------------------------------------------


def _apply_kb_forget(client: Any, candidates: list[dict]) -> list[dict]:
    """Two-step semantic delete per candidate (the server's contract):
    step 1 kb_forget(query, kb) -> matches (deletes nothing); step 2
    kb_forget(confirm=true, ids=[top match]) -> deletes at most one point.
    Never raises — per-candidate failures are recorded."""
    results: list[dict] = []
    for cand in candidates:
        kb = cand.get("kb")
        args: dict[str, Any] = {"query": cand["fact"]}
        if kb:
            args["kb"] = kb
        try:
            step1 = client.mcp_call("kb_forget", args, server_id="mcp_knowledge")
            matches = (step1 or {}).get("matches") or []
            matches = [m for m in matches if isinstance(m, dict) and m.get("id")]
            if not matches:
                results.append(
                    {
                        "kb": kb or None,
                        "fact": cand["fact"][:120],
                        "applied": False,
                        "note": "no semantic match — nothing deleted",
                    }
                )
                continue
            top = matches[0]
            args2 = dict(args)
            args2["confirm"] = True
            args2["ids"] = [str(top["id"])]
            step2 = client.mcp_call("kb_forget", args2, server_id="mcp_knowledge")
            deleted = int((step2 or {}).get("total") or 0)
            results.append(
                {
                    "kb": str(top.get("kb") or kb or ""),
                    "fact": cand["fact"][:120],
                    "applied": bool(deleted),
                    "note": (
                        f"deleted {deleted} point(s) (permanent — no undo)"
                        if deleted
                        else "step 2 reported 0 deleted"
                    ),
                }
            )
        except Exception as exc:  # noqa: BLE001
            results.append(
                {
                    "kb": kb or None,
                    "fact": cand["fact"][:120],
                    "applied": False,
                    "note": f"kb_forget failed: {str(exc)[:100]}",
                }
            )
    return results


# ---------------------------------------------------------------------------
# Doc rendering (4 parts) + sidecar
# ---------------------------------------------------------------------------


def _refs(evidence: list[str]) -> str:
    return f" ({'; '.join(evidence)})" if evidence else ""


def _render_doc(
    month_label: str,
    mstart: datetime,
    goals: dict,
    parts: dict,
    kb: dict,
    board: dict,
    mode: str,
    gate_reason: str,
    sidecar_rel: str,
    apply_goals: bool,
    apply_kb: bool,
    goals_applied: bool,
    kb_results: list[dict],
    guardrail_notes: list[str],
) -> str:
    now = _now()
    mend = _month_end_date(mstart)
    lines: list[str] = [
        f"# Monthly org review — {month_label}",
        "",
        f"- generated: {now.isoformat()[:16]} by monthly_org_review",
        f"- mode: {mode}",
        f"- window: {mstart.strftime('%Y-%m-%d')} → {mend.isoformat()} (calendar month)",
        f"- gate: {gate_reason}",
        "",
        "## 1. KR scoring (0-1)",
        "",
    ]
    if parts["kr_scores"]:
        last_domain = None
        for k in parts["kr_scores"]:
            if k["domain"] != last_domain:
                lines.append(f"### {k['domain']}")
                lines.append("")
                last_domain = k["domain"]
            score = f"**{k['score']:.2f}**" if k["score"] is not None else "**n/a**"
            lines.append(
                f"- [{k['objective']}] {k['kr']} — {score} "
                f"(target: {k.get('target') or 'n/a'}; cadence: {k.get('cadence') or 'n/a'}) "
                f"— {k['note']}{_refs(k['evidence'])}"
            )
    else:
        lines.append("- No org KRs found (goals.md missing?) — nothing to score.")

    lines += ["", "## 2. Retro", ""]
    retro = parts["retro"]
    for label, key in (("worked", "worked"), ("didn't work", "didnt"), ("friction", "friction")):
        items = retro.get(key) or []
        lines.append(f"- {label}: " + ("; ".join(items) if items else "none recorded"))

    ga = parts["goal_adaptation"]
    lines += [
        "",
        "## 3. Goal adaptation (cycle boundary — proposals only by default)",
        "",
        f"- rationale: {ga['rationale'] or 'no rationale recorded'}",
    ]
    if ga["changes"]:
        lines.append("- changes: " + "; ".join(ga["changes"]))
    lines.append(f"- proposed rewrite: {sidecar_rel} (sidecar)")
    if apply_goals:
        lines.append(
            f"- status: {'APPLIED to docs/org/goals.md (params.apply_goals=true)' if goals_applied else 'NOT applied — the proposed rewrite failed the guardrail checks; docs/org/goals.md untouched'}"
        )
    else:
        lines.append(
            "- status: NOT applied (params.apply_goals=false — chuck applies after "
            "reading the review; org-doc edits are single-approval)"
        )

    lines += ["", "## 4. Domain-KB staleness pass", ""]
    cands = parts["kb_staleness"]
    lines.append(f"- {_kb_line(kb)}")
    if cands:
        lines.append(f"- kb_forget candidates ({len(cands)}):")
        for c in cands:
            lines.append(
                f"  - [{c['kb'] or 'any'}] {c['fact']} — {c['reason'] or 'no reason'}{_refs(c['evidence'])}"
            )
    else:
        lines.append("- kb_forget candidates: none (no stale/superseded facts found)")
    if apply_kb:
        applied = [r for r in kb_results if r.get("applied")]
        lines.append(
            f"- status: kb_forget applied for {len(applied)}/{len(kb_results)} candidate(s) "
            "(params.apply_kb_forget=true — permanent, no undo)"
        )
        for r in kb_results:
            lines.append(f"  - [{r.get('kb') or 'any'}] {r['fact']} — {r['note']}")
    else:
        lines.append(
            "- status: candidates only (params.apply_kb_forget=false — no kb_forget called)"
        )

    if board.get("available"):
        done = board.get("done_by_project") or {}
        lines += [
            "",
            f"_board: {len(board.get('done_in_month') or [])} done card(s) this month "
            f"({', '.join(f'{k}: {v}' for k, v in sorted(done.items())) or 'none'}); "
            f"{len(board.get('cards') or [])} board card(s) collected for evidence validation_",
        ]
    else:
        lines += ["", "_board: unavailable this run — no board evidence could be verified_"]

    if guardrail_notes:
        # Count only — the raw dropped refs stay in the returned
        # guardrail_notes (run log), never echoed into the review doc.
        lines += [
            "",
            f"_guardrails: {len(guardrail_notes)} deterministic note(s) applied "
            "(invalid evidence refs / non-goals KRs / out-of-range scores / "
            "rejected rewrites dropped — details in the run log)_",
        ]
    lines.append("")
    return "\n".join(lines)


def _sidecar_content(
    parts: dict, goals: dict, month_label: str, next_cycle: str, notes: list[str]
) -> tuple[str, str]:
    """(content, status) for the goals sidecar."""
    ga = parts["goal_adaptation"]
    if ga["proposed_ok"]:
        banner = (
            f"<!-- PROPOSED rewrite of docs/org/goals.md for cycle {next_cycle} — "
            f"generated by monthly_org_review on {_now().strftime('%Y-%m-%d')} "
            f"(review doc: docs/org/reviews/{month_label}.md). NOT applied "
            f"(params.apply_goals=false by default). Apply by copying the body "
            f"below (after this banner) over docs/org/goals.md after review. -->\n\n"
        )
        return banner + ga["proposed_goals_md"] + "\n", "proposed"
    reason = (
        "LLM synthesis unavailable — deterministic skeleton"
        if not notes or "deterministic skeleton" in notes[-1]
        else "the proposed rewrite was rejected by the deterministic guardrails"
    )
    baseline = ""
    try:
        baseline = (REPO_ROOT / "docs" / "org" / "goals.md").read_text(
            encoding="utf-8", errors="replace"
        )
    except OSError:
        baseline = "(current docs/org/goals.md not found)"
    content = (
        f"# Proposed goals rewrite — cycle {next_cycle}\n\n"
        f"NO CHANGE PROPOSED this cycle ({reason}).\n\n"
        f"Baseline (current docs/org/goals.md, unchanged):\n\n"
        f"---\n\n{baseline}\n"
    )
    return content, "no-change"


def _fallback_parts(goals: dict, kb: dict) -> dict:
    """Deterministic skeleton parts (LLM failure)."""
    kr_scores = [
        {
            "domain": k["domain"],
            "objective": k["objective"],
            "num": k["num"],
            "kr": k["name"],
            "score": None,
            "evidence": [],
            "note": "no LLM — score n/a (deterministic fallback)",
            "target": k["target"],
            "cadence": k["cadence"],
        }
        for k in goals["all_krs"]
    ]
    return {
        "kr_scores": kr_scores,
        "retro": {
            "worked": ["no LLM — no retro (deterministic fallback)"],
            "didnt": [],
            "friction": [],
        },
        "goal_adaptation": {
            "rationale": "no LLM — no change proposed (deterministic fallback)",
            "changes": [],
            "proposed_goals_md": "",
            "proposed_ok": False,
        },
        "kb_staleness": [],
    }


def _write_file(path: Path, content: str) -> Optional[str]:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return str(path)
    except OSError as exc:
        logger.warning("monthly_org_review: write failed for %s: %s", path, exc)
        return None


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run(params: dict, job: Any, client: Any = None) -> dict:
    """Monthly org review (first-Friday gated; proposals by default).

    Conforms to the `monthly-org-review` schedule params: output
    "docs/org/reviews/YYYY-MM.md", includes [KR scoring 0-1, retro, goal
    adaptation, domain-KB staleness pass]. The schedule's note documents
    the cron caveat (fires every Friday) — the first-Friday gate is this
    skill's responsibility.

    Conservative application: the review doc + the goals sidecar are
    always written; docs/org/goals.md is overwritten ONLY with
    params.apply_goals=true (and a guardrail-valid proposed rewrite), and
    kb_forget is called ONLY with params.apply_kb_forget=true (two-step,
    one point per candidate). Both default to false. params.force_date
    overrides the run date (the first-Friday gate still applies to it).
    """
    params = params or {}
    output = str(params.get("output") or DEFAULT_OUTPUT)
    sidecar_tpl = str(params.get("goals_sidecar") or DEFAULT_SIDECAR)
    apply_goals = bool(params.get("apply_goals", False))
    apply_kb = bool(params.get("apply_kb_forget", False))

    # --- first-Friday gate (deterministic) ---
    force = params.get("force_date")
    if force is not None:
        if not isinstance(force, str) or not _FORCE_DATE_RE.match(str(force).strip()):
            return {
                "error": f"params.force_date must be a 'YYYY-MM-DD' string (got {force!r})"
            }
        try:
            ref = datetime.fromisoformat(str(force).strip()).replace(tzinfo=timezone.utc)
        except ValueError:
            return {"error": f"params.force_date is not a valid date: {force!r}"}
    else:
        ref = _now()
    gate_run, gate_reason = _gate(ref)

    month_label = f"{ref.year:04d}-{ref.month:02d}"
    if job is not None and hasattr(job, "add_log"):
        job.add_log(f"monthly_org_review: month={month_label} gate: {gate_reason}")

    if not gate_run:
        summary = f"monthly_org_review {month_label}: skipped — {gate_reason}"
        if job is not None and hasattr(job, "add_log"):
            job.add_log(summary)
        logger.info(summary)
        return {
            "status": "skipped",
            "reason": gate_reason,
            "summary": summary,
            "month": month_label,
            "artifact_path": None,
            "goals_sidecar": None,
        }

    mstart, mend = _month_bounds(ref)
    mstart_ms = int(mstart.timestamp() * 1000)
    mend_ms = int(mend.timestamp() * 1000)

    # --- deterministic collection (all best-effort) ---
    goals = _parse_org_goals()
    reviews = _collect_weekly_reviews(ref.year, ref.month)
    board = _collect_board(mstart_ms, mend_ms)
    alignment = _latest_alignment_report()
    kb = _collect_kb(client, list(goals["domains"].keys()), mstart, mend)

    # --- ONE LLM synthesis call (deterministic fallback on failure) ---
    analysis = _analyze(month_label, mstart, mend, goals, reviews, board, alignment, kb)
    if analysis is None:
        parts = _fallback_parts(goals, kb)
        synthesis = "deterministic-fallback"
        notes: list[str] = ["LLM synthesis unavailable — deterministic skeleton written"]
    else:
        parts, notes = _guardrail_filter(analysis, goals, board, reviews, kb)
        synthesis = "llm"
    mode = f"{'forced' if force is not None else 'first-friday'} + {synthesis}"

    # --- sidecar (always written — the proposal record) ---
    next_cycle = f"{(mstart + timedelta(days=32)).replace(day=1).year:04d}-{(mstart + timedelta(days=32)).replace(day=1).month:02d}"
    sidecar_text, sidecar_status = _sidecar_content(parts, goals, month_label, next_cycle, notes)
    sidecar_path = _write_file(_resolve_template(sidecar_tpl, month_label), sidecar_text)

    # --- conservative application: goals.md ONLY with the explicit param ---
    goals_applied = False
    if apply_goals:
        if parts["goal_adaptation"]["proposed_ok"]:
            goals_path = REPO_ROOT / "docs" / "org" / "goals.md"
            if _write_file(goals_path, parts["goal_adaptation"]["proposed_goals_md"] + "\n"):
                goals_applied = True
            else:
                notes.append("apply_goals=true but the goals.md write failed")
        else:
            notes.append(
                "apply_goals=true but no guardrail-valid proposed rewrite — "
                "docs/org/goals.md NOT modified"
            )

    # --- conservative application: kb_forget ONLY with the explicit param ---
    kb_results: list[dict] = []
    if apply_kb and parts["kb_staleness"]:
        if client is None:
            notes.append("apply_kb_forget=true but no MCP client injected — no kb_forget called")
        else:
            kb_results = _apply_kb_forget(client, parts["kb_staleness"])

    # --- review doc ---
    sidecar_rel = str(Path(sidecar_tpl).as_posix().replace("YYYY-MM", month_label))
    doc = _render_doc(
        month_label, mstart, goals, parts, kb, board, mode, gate_reason,
        sidecar_rel, apply_goals, apply_kb, goals_applied, kb_results, notes,
    )
    path = _write_file(_resolve_template(output, month_label), doc)
    if path is None:
        return {
            "status": "error",
            "error": "failed to write the review doc",
            "summary": f"monthly_org_review {month_label}: failed to write the review doc",
            "month": month_label,
            "artifact_path": None,
            "goals_sidecar": sidecar_path,
        }

    applied_kb = [r for r in kb_results if r.get("applied")]
    summary = (
        f"monthly_org_review {month_label}: generated ({mode}); "
        f"{len(parts['kr_scores'])} KR(s) scored; sidecar={sidecar_status}; "
        f"goals {'APPLIED' if goals_applied else 'not applied'}; "
        f"kb_forget {len(applied_kb)}/{len(parts['kb_staleness'])} applied"
    )
    if job is not None and hasattr(job, "add_log"):
        job.add_log(summary)
    logger.info(summary)
    return {
        "status": "generated",
        "summary": summary,
        "month": month_label,
        "gate": gate_reason,
        "mode": mode,
        "artifact_path": path,
        "goals_sidecar": sidecar_path,
        "goals_applied": goals_applied,
        "kb_forget_applied": applied_kb,
        "kb_forget_results": kb_results,
        "guardrail_notes": notes,
        "inputs": {
            "goals_krs": len(goals["all_krs"]),
            "weekly_reviews": len(reviews),
            "board_done_in_month": len(board.get("done_in_month") or []),
            "board_cards": len(board.get("cards") or []),
            "alignment": alignment.get("path"),
            "kb_collections": sorted((kb.get("collections") or {}).keys()),
        },
    }
