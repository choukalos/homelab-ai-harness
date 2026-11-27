#!/usr/bin/env python3
"""Unit tests for the monthly_org_review skill — NO live services.

Covers:
  - first-Friday gate (deterministic date arithmetic):
      2026-11-27 (4th Friday) -> skip, nothing written, no LLM call
      2026-12-04 (first Friday) -> run
      boundary cases: 2027-01-01 (1st is a Friday) -> run;
      2026-02-06 (first Friday) -> run; 2026-02-01 (Sunday) -> skip;
      2026-03-13 (2nd Friday) -> skip; non-Friday date -> skip
  - conservative-apply defaults: goals.md NOT overwritten, sidecar
    written, NO kb_forget called without the params
  - apply params: apply_goals=true overwrites goals.md with the
    guardrail-valid rewrite; apply_kb_forget=true runs the two-step
    kb_forget (step 1 no confirm, step 2 confirm + ids)
  - guardrails: fake evidence refs dropped (task/commit/file/review),
    out-of-month review ref dropped, invented KRs dropped, scores
    clamped to [0,1], non-numeric scores dropped, missing KRs filled
    with n/a, proposed rewrite missing a domain rejected (sidecar says
    no change; goals.md untouched even with apply_goals=true), kb
    candidates without valid evidence / unknown collection dropped
  - output path/format: docs/org/reviews/YYYY-MM.md + sidecar
    docs/org/goals.proposed-YYYY-MM.md, 4 parts in order
  - LLM-failure fallback: deterministic skeleton doc, no crash, no
    error, sidecar = "no change proposed" + baseline
  - collection: alignment report + in-month weekly reviews fed to the
    LLM (out-of-month reviews excluded); board done-in-month data
  - board down + no client -> degrades honestly, still generated
  - bad force_date -> error dict

Run with plain python3 (no pytest, no fastapi, no pymysql, no mem0):
    python3 skills/monthly_org_review/test_skill.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import types
from datetime import date, datetime, timezone
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_PATH = os.path.join(HERE, "skill.py")

PASS = 0
FAIL = 0
FAILURES = []


def check(name: str, cond: bool, detail: str = ""):
    global PASS, FAIL
    print(f"  {'PASS' if cond else 'FAIL'}: {name}" + (f" — {detail}" if detail else ""))
    if cond:
        PASS += 1
    else:
        FAIL += 1
        FAILURES.append(name)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeJob:
    def __init__(self, user_id: str = "service"):
        self.user_id = user_id
        self.run_id = "test-run-1"
        self.logs: list[str] = []

    def add_log(self, msg: str) -> None:
        self.logs.append(msg)


class FakeClient:
    """MCP client fake (KB calls). The LLM path is monkeypatched
    separately (the skill calls LiteLLM via urllib, not the client)."""

    def __init__(self, kb_docs=None, kb_hits=None, forget_matches=None):
        self.kb_docs = kb_docs or []
        self.kb_hits = kb_hits or []
        self.forget_matches = forget_matches or []
        self.mcp_calls: list[tuple] = []

    def mcp_call(self, tool: str, args: dict, server_id: str = None) -> dict:
        self.mcp_calls.append((tool, dict(args or {}), server_id))
        if tool == "kb_list_documents":
            if self.kb_docs:
                return {"documents": {"kb_bluebovine": self.kb_docs}}
            return {"documents": {}}
        if tool == "kb_search":
            return {"results": self.kb_hits, "note": ""}
        if tool == "kb_forget":
            if args.get("confirm"):
                ids = args.get("ids") or []
                return {
                    "deleted": {"kb_bluebovine": len(ids)},
                    "total": len(ids),
                    "not_found": [],
                    "note": "Deleted (permanent — no undo).",
                }
            return {
                "matches": self.forget_matches,
                "note": "Nothing deleted. Review the matches, then call "
                "kb_forget again with confirm=true and ids=[...].",
            }
        return {}


class FakeBoardCursor:
    def __init__(self, conn: "FakeBoardConn"):
        self.conn = conn

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql: str, args=None):
        self.conn.last_sql = " ".join(sql.split())
        self.conn.last_args = args

    def fetchall(self):
        if "state = 'done'" in self.conn.last_sql:
            return self.conn.done_rows
        return self.conn.agent_rows


class FakeBoardConn:
    """Routes canned rows by SQL shape (done-in-month / agent-owned)."""

    def __init__(self, done_rows=(), agent_rows=()):
        self.done_rows = list(done_rows)
        self.agent_rows = list(agent_rows)
        self.last_sql = ""
        self.last_args = None

    def cursor(self):
        return FakeBoardCursor(self)

    def close(self):
        pass


# ---------------------------------------------------------------------------
# Skill module loading (importlib, like the runner does)
# ---------------------------------------------------------------------------


def load_skill(tmp: Path) -> types.ModuleType:
    """Load the skill module with the test env (temp repo root)."""
    os.environ["MONTHLY_ORG_REVIEW_REPO_ROOT"] = str(tmp / "repo")
    os.environ["MONTHLY_ORG_REVIEW_MODEL_ALIAS"] = "matrix-coder"
    os.environ["LITELLM_BASE_URL"] = "http://127.0.0.1:9"  # unused (patched)
    os.environ["LITELLM_API_KEY"] = "test-key"

    spec = importlib.util.spec_from_file_location("skill_monthly_org_review", SKILL_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def wire_fakes(
    mod: types.ModuleType,
    board: FakeBoardConn | None,
    llm_payload,
    kb_client: FakeClient | None = None,
) -> dict:
    """Monkeypatch board conn + LLM call; returns llm_state."""
    if board is None:
        def _db_down():
            raise RuntimeError("board DB unreachable")
        mod._db_conn = _db_down
    else:
        mod._db_conn = lambda: board
    state = {"calls": 0, "messages": None}

    def fake_llm(messages):
        state["calls"] += 1
        state["messages"] = messages
        if llm_payload is None:
            return None
        return json.dumps(llm_payload)

    mod._llm_chat = fake_llm
    return state


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

GOALS = """# Org Goals

> Living doc — org-level OKRs per domain.

## Cycle 2026-12 (test cycle)

### Homelab

**O1 — Personal-interest content ships on a steady rhythm.**

| # | KR | Definition | Source | Target | Cadence |
|---|----|------------|--------|--------|---------|
| 1 | Content output (leading) | Pieces published across the pillars | content inventory | 3-4 pieces/mo | monthly |
| 2 | Quality (mandatory) | Published pieces that failed content QA | QA records | 0 | per publish |

### Bluebovine

**O2 — The product is defined and validated, ready to iterate.**

| # | KR | Definition | Source | Target | Cadence |
|---|----|------------|--------|--------|---------|
| 1 | Market analysis | Complete market analysis with evidence | docs/roles/pm | 1, by 2026-12-15 | this cycle |
| 2 | Quality (mandatory) | PRDs without acceptance criteria | board specs | 0 | per PRD |

## Coverage (who serves what)

| Org goal | Agents serving | Notes |
|---|---|---|
| Homelab O1 | marketing (producer) | main goal this cycle |
"""

REVIEW_W49 = """# Weekly review — product — 2026-W49

MARKER-REVIEW-W49

## 1. Prior-week accomplishments (evidence/links)

- market scan drafted
"""

REVIEW_W40 = """# Weekly review — product — 2026-W40

MARKER-REVIEW-W40 (September — out of month)
"""

ALIGNMENT = """# OKR alignment report — 2026-11-26 — first pass

MARKER-ALIGN-123

Board state at pass time: 14 done.
"""

PROPOSED_GOALS = (
    "# Org Goals\n\n"
    "## Cycle 2026-01 (proposed)\n\n"
    "### Homelab\n\n"
    "**O1 — Personal-interest content ships on a steady rhythm.**\n\n"
    "| # | KR | Definition | Source | Target | Cadence |\n"
    "|---|----|------------|--------|--------|---------|\n"
    "| 1 | Content output (leading) | Pieces published | inventory | 3-4/mo | monthly |\n\n"
    "### Bluebovine\n\n"
    "**O2 — The product is defined and validated.**\n\n"
    "| # | KR | Definition | Source | Target | Cadence |\n"
    "|---|----|------------|--------|--------|---------|\n"
    "| 1 | Market analysis | Complete market analysis | docs/roles/pm | 1, by 2026-01-15 | this cycle |\n"
)

GOOD_LLM = {
    "kr_scores": [
        {
            "domain": "Homelab",
            "objective": "O1",
            "num": 1,
            "kr": "Content output (leading)",
            "score": 0.5,
            "evidence": [
                "task:15",
                "commit:abc123def456",
                "file:docs/roles/pm/market-analysis-2026-11-27.md",
            ],
            "note": "1 piece published vs 3-4/mo target",
        },
        {
            "domain": "Bluebovine",
            "objective": "O2",
            "num": 1,
            "kr": "Market analysis",
            "score": 0.8,
            "evidence": ["review:product/2026-W49"],
            "note": "scan drafted and filed per the W49 review",
        },
    ],
    "retro": {
        "worked": ["board specs carry acceptance criteria"],
        "didnt": ["no KB writes this month"],
        "friction": ["Plausible not wired — traffic KRs stay proxy"],
    },
    "goal_adaptation": {
        "rationale": "Cycle 2026-12 closes; carry the open Bluebovine O2 KRs into 2026-01.",
        "changes": ["carry Market analysis into 2026-01", "keep Homelab O1 targets"],
        "proposed_goals_md": PROPOSED_GOALS,
    },
    "kb_staleness": [
        {
            "kb": "kb_bluebovine",
            "fact": "market analysis not started",
            "reason": "superseded — scan drafted per the W49 review",
            "evidence": ["review:product/2026-W49"],
        }
    ],
}


def write_fixtures(tmp: Path) -> None:
    repo = tmp / "repo"
    (repo / "docs" / "org").mkdir(parents=True, exist_ok=True)
    (repo / "docs" / "org" / "goals.md").write_text(GOALS, encoding="utf-8")
    (repo / "docs" / "org" / "alignment").mkdir(parents=True, exist_ok=True)
    (repo / "docs" / "org" / "alignment" / "2026-11-26-first-pass.md").write_text(
        ALIGNMENT, encoding="utf-8"
    )
    (repo / "docs" / "agents" / "product" / "reviews").mkdir(parents=True, exist_ok=True)
    (repo / "docs" / "agents" / "product" / "reviews" / "2026-W49.md").write_text(
        REVIEW_W49, encoding="utf-8"
    )
    (repo / "docs" / "agents" / "product" / "reviews" / "2026-W40.md").write_text(
        REVIEW_W40, encoding="utf-8"
    )
    (repo / "docs" / "roles" / "pm").mkdir(parents=True, exist_ok=True)
    (repo / "docs" / "roles" / "pm" / "market-analysis-2026-11-27.md").write_text(
        "# Market analysis (draft)\n", encoding="utf-8"
    )


def make_done_rows() -> list:
    """Two done cards whose state_changed_at falls in Dec 2026."""
    return [
        (
            15,
            "chuck",
            int(datetime(2026, 12, 3, 12, 0, tzinfo=timezone.utc).timestamp() * 1000),
            "Homelab",
        ),
        (
            16,
            "product",
            int(datetime(2026, 12, 10, 9, 30, tzinfo=timezone.utc).timestamp() * 1000),
            "Bluebovine",
        ),
    ]


def make_agent_rows() -> list:
    return [
        (15, "chuck", "done", "abc123def456", "Homelab"),
        (16, "product", "running", None, "Bluebovine"),
    ]


def make_client() -> FakeClient:
    return FakeClient(
        kb_docs=[
            {"source": "bluebovine-positioning.md", "ingested_at": "2026-12-02T10:00:00Z", "chunks": 3},
            {"source": "old-fact.md", "ingested_at": "2026-09-01T00:00:00Z", "chunks": 1},
        ],
        kb_hits=[
            {"id": "pt-1", "kb": "kb_bluebovine", "source": "market.md",
             "snippet": "market analysis not started"}
        ],
        forget_matches=[
            {"id": "pt-1", "kb": "kb_bluebovine", "score": 0.9,
             "source": "market.md", "snippet": "market analysis not started"}
        ],
    )


def run_dec(mod: types.ModuleType, extra: dict, job: FakeJob, client) -> dict:
    """First-Friday-of-December forced run (the standard test run date)."""
    return mod.run({"force_date": "2026-12-04", **extra}, job, client)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_gate_first_friday_unit():
    print("test_gate_first_friday_unit")
    with tempfile.TemporaryDirectory() as t:
        mod = load_skill(Path(t))
        cases = [
            (date(2026, 11, 27), False),  # 4th Friday of November
            (date(2026, 11, 6), True),    # first Friday of November
            (date(2026, 12, 4), True),    # first Friday of December
            (date(2027, 1, 1), True),     # the 1st is a Friday
            (date(2026, 2, 6), True),     # first Friday of February
            (date(2026, 2, 1), False),    # Sunday
            (date(2026, 3, 6), True),     # first Friday of March
            (date(2026, 3, 13), False),   # 2nd Friday of March
        ]
        for d, expected in cases:
            check(f"{d.isoformat()} -> {expected}", mod._is_first_friday(d) == expected)
        run, reason = mod._gate(datetime(2026, 11, 27, 15, 0, tzinfo=timezone.utc))
        check("gate skip reason (4th Friday)",
              (not run) and reason.startswith("not the first Friday of November 2026")
              and "4th Friday" in reason, reason)
        run, reason = mod._gate(datetime(2026, 12, 4, 15, 0, tzinfo=timezone.utc))
        check("gate run (first Friday)", run, reason)
        run, reason = mod._gate(datetime(2026, 12, 7, 15, 0, tzinfo=timezone.utc))
        check("gate skip (non-Friday date)", (not run) and "not a Friday" in reason, reason)


def test_gate_skip_2026_11_27():
    print("test_gate_skip_2026_11_27")
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        mod = load_skill(tmp)
        write_fixtures(tmp)
        state = wire_fakes(mod, FakeBoardConn(), GOOD_LLM, make_client())
        job = FakeJob()
        res = mod.run({"force_date": "2026-11-27"}, job, make_client())
        check("status skipped", res.get("status") == "skipped", str(res.get("status")))
        check("reason starts with the required prefix",
              res.get("reason", "").startswith("not the first Friday of November 2026"),
              res.get("reason"))
        check("reason names the 4th Friday", "4th Friday" in res.get("reason", ""))
        check("no LLM call on skip", state["calls"] == 0)
        check("nothing written (no reviews dir)",
              not (tmp / "repo" / "docs" / "org" / "reviews").exists())
        check("no sidecar written",
              not (tmp / "repo" / "docs" / "org" / "goals.proposed-2026-11.md").exists())
        check("artifact_path None", res.get("artifact_path") is None)
        check("summary mentions skip", "skipped" in res.get("summary", ""), res.get("summary"))


def test_gate_run_first_friday():
    print("test_gate_run_first_friday")
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        mod = load_skill(tmp)
        write_fixtures(tmp)
        state = wire_fakes(mod, FakeBoardConn(make_done_rows(), make_agent_rows()),
                           GOOD_LLM, make_client())
        job = FakeJob()
        res = run_dec(mod, {}, job, make_client())
        check("status generated", res.get("status") == "generated", str(res))
        check("month label", res.get("month") == "2026-12")
        expected = tmp / "repo" / "docs" / "org" / "reviews" / "2026-12.md"
        check("artifact path matches template", res.get("artifact_path") == str(expected),
              str(res.get("artifact_path")))
        check("review doc exists", expected.is_file())
        sidecar = tmp / "repo" / "docs" / "org" / "goals.proposed-2026-12.md"
        check("sidecar path matches template", res.get("goals_sidecar") == str(sidecar))
        check("sidecar exists", sidecar.is_file())
        check("exactly one LLM call", state["calls"] == 1, f"got {state['calls']}")
        check("gate reason says first Friday",
              "first Friday of December 2026" in res.get("gate", ""), res.get("gate"))


def test_gate_boundaries():
    print("test_gate_boundaries")
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        mod = load_skill(tmp)
        write_fixtures(tmp)
        wire_fakes(mod, FakeBoardConn(), GOOD_LLM, make_client())
        job = FakeJob()
        res = mod.run({"force_date": "2027-01-01"}, job, make_client())
        check("2027-01-01 (1st is a Friday) -> run",
              res.get("status") == "generated" and res.get("month") == "2027-01", str(res))
        check("2027-01 artifact path",
              res.get("artifact_path") == str(tmp / "repo" / "docs" / "org" / "reviews" / "2027-01.md"))
        res = mod.run({"force_date": "2026-02-06"}, job, make_client())
        check("2026-02-06 (first Friday) -> run",
              res.get("status") == "generated" and res.get("month") == "2026-02", str(res))
        res = mod.run({"force_date": "2026-02-01"}, job, make_client())
        check("2026-02-01 (Sunday) -> skip",
              res.get("status") == "skipped" and "not a Friday" in res.get("reason", ""),
              str(res.get("reason")))
        res = mod.run({"force_date": "2026-03-13"}, job, make_client())
        check("2026-03-13 (2nd Friday) -> skip",
              res.get("status") == "skipped" and "2nd Friday" in res.get("reason", ""),
              str(res.get("reason")))


def test_conservative_apply_defaults():
    print("test_conservative_apply_defaults")
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        mod = load_skill(tmp)
        write_fixtures(tmp)
        wire_fakes(mod, FakeBoardConn(make_done_rows(), make_agent_rows()),
                   GOOD_LLM, make_client())
        job = FakeJob()
        client = make_client()
        goals_path = tmp / "repo" / "docs" / "org" / "goals.md"
        before = goals_path.read_text(encoding="utf-8")
        res = run_dec(mod, {}, job, client)
        check("generated", res.get("status") == "generated", str(res))
        check("goals.md NOT overwritten",
              goals_path.read_text(encoding="utf-8") == before)
        check("goals_applied False", res.get("goals_applied") is False)
        sidecar_text = (tmp / "repo" / "docs" / "org" / "goals.proposed-2026-12.md").read_text(
            encoding="utf-8")
        check("sidecar carries the PROPOSED rewrite",
              "PROPOSED rewrite" in sidecar_text and "Cycle 2026-01" in sidecar_text)
        check("sidecar is NOT applied language",
              "NOT applied" in sidecar_text)
        check("no kb_forget called by default",
              not any(c[0] == "kb_forget" for c in client.mcp_calls),
              str([c[0] for c in client.mcp_calls]))
        check("kb_forget_applied empty", res.get("kb_forget_applied") == [])
        doc = Path(res["artifact_path"]).read_text(encoding="utf-8")
        check("doc says NOT applied (goals)",
              "NOT applied (params.apply_goals=false" in doc)
        check("doc says candidates only (kb)",
              "candidates only (params.apply_kb_forget=false" in doc)


def test_apply_params():
    print("test_apply_params")
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        mod = load_skill(tmp)
        write_fixtures(tmp)
        wire_fakes(mod, FakeBoardConn(make_done_rows(), make_agent_rows()),
                   GOOD_LLM, make_client())
        job = FakeJob()
        client = make_client()
        res = run_dec(mod, {"apply_goals": True, "apply_kb_forget": True}, job, client)
        check("generated", res.get("status") == "generated", str(res))
        goals_path = tmp / "repo" / "docs" / "org" / "goals.md"
        check("goals.md overwritten with the proposed rewrite",
              goals_path.read_text(encoding="utf-8").startswith(PROPOSED_GOALS[:60]))
        check("goals_applied True", res.get("goals_applied") is True)
        forget_calls = [c for c in client.mcp_calls if c[0] == "kb_forget"]
        check("kb_forget two-step (2 calls for 1 candidate)", len(forget_calls) == 2,
              str(len(forget_calls)))
        check("step 1 has no confirm", not forget_calls[0][1].get("confirm"))
        check("step 2 confirm + ids",
              forget_calls[1][1].get("confirm") is True
              and forget_calls[1][1].get("ids") == ["pt-1"],
              str(forget_calls[1][1]))
        check("kb_forget_applied has 1 entry", len(res.get("kb_forget_applied") or []) == 1)
        doc = Path(res["artifact_path"]).read_text(encoding="utf-8")
        check("doc says kb_forget applied 1/1", "kb_forget applied for 1/1" in doc)
        check("doc says goals APPLIED",
              "APPLIED to docs/org/goals.md (params.apply_goals=true)" in doc)


def test_output_path_and_format():
    print("test_output_path_and_format")
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        mod = load_skill(tmp)
        write_fixtures(tmp)
        wire_fakes(mod, FakeBoardConn(make_done_rows(), make_agent_rows()),
                   GOOD_LLM, make_client())
        job = FakeJob()
        res = run_dec(mod, {}, job, make_client())
        doc = Path(res["artifact_path"]).read_text(encoding="utf-8")
        heads = [
            "## 1. KR scoring (0-1)",
            "## 2. Retro",
            "## 3. Goal adaptation",
            "## 4. Domain-KB staleness pass",
        ]
        pos = [doc.index(h) for h in heads]
        check("4 parts present in order", pos == sorted(pos), str(pos))
        check("month label in doc header", "# Monthly org review — 2026-12" in doc)
        check("window line (calendar month)", "window: 2026-12-01 → 2026-12-31" in doc)
        check("gate line", "gate: first Friday of December 2026 (2026-12-04)" in doc)
        check("domains as sub-sections", "### Homelab" in doc and "### Bluebovine" in doc)
        check("KR scores rendered", "**0.50**" in doc and "**0.80**" in doc)
        check("evidence refs rendered", "task:15" in doc and "review:product/2026-W49" in doc)
        check("retro rendered", "Plausible not wired" in doc)
        check("sidecar referenced in part 3",
              "docs/org/goals.proposed-2026-12.md" in doc)


def test_llm_failure_fallback():
    print("test_llm_failure_fallback")
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        mod = load_skill(tmp)
        write_fixtures(tmp)
        wire_fakes(mod, FakeBoardConn(make_done_rows(), make_agent_rows()), None, make_client())
        job = FakeJob()
        res = run_dec(mod, {}, job, make_client())
        check("no error on LLM failure", "error" not in res, str(res.get("error")))
        check("still generated (deterministic skeleton)",
              res.get("status") == "generated", str(res))
        doc = Path(res["artifact_path"]).read_text(encoding="utf-8")
        check("fallback mode label", "deterministic-fallback" in doc)
        check("every KR still listed with n/a",
              "Content output (leading)" in doc and "Market analysis" in doc
              and "no LLM — score n/a (deterministic fallback)" in doc)
        heads = ["## 1.", "## 2.", "## 3.", "## 4."]
        pos = [doc.index(h) for h in heads]
        check("4 parts still in order", pos == sorted(pos))
        sidecar_text = (tmp / "repo" / "docs" / "org" / "goals.proposed-2026-12.md").read_text(
            encoding="utf-8")
        check("sidecar says NO CHANGE PROPOSED", "NO CHANGE PROPOSED" in sidecar_text)
        check("sidecar carries the baseline", "Baseline" in sidecar_text and "Cycle 2026-12" in sidecar_text)
        check("goals.md untouched", "test cycle" in (tmp / "repo" / "docs" / "org" / "goals.md").read_text())
        check("no kb_forget called", not any(c[0] == "kb_forget" for c in res.get("kb_forget_results", [])))


def test_guardrails():
    print("test_guardrails")
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        mod = load_skill(tmp)
        write_fixtures(tmp)
        llm = {
            "kr_scores": [
                {
                    "domain": "Homelab",
                    "objective": "O1",
                    "num": 1,
                    "kr": "Content output (leading)",
                    "score": 1.7,  # -> clamped to 1.0
                    "evidence": [
                        "task:15",
                        "task:99999",                        # fake board card id
                        "commit:deadbeef0000",               # fake sha
                        "file:docs/roles/pm/does-not-exist.md",  # fake path
                        "review:product/2026-W40",          # out-of-month review
                    ],
                    "note": "x",
                },
                {
                    "domain": "Nowhere",
                    "objective": "O9",
                    "num": 1,
                    "kr": "Invented KR",
                    "score": 0.5,
                    "evidence": [],
                    "note": "not in goals.md",
                },
                {
                    "domain": "Homelab",
                    "objective": "O1",
                    "num": 2,
                    "kr": "Quality (mandatory)",
                    "score": "high",  # non-numeric -> dropped
                    "evidence": [],
                    "note": "bad score",
                },
            ],
            "retro": {"worked": ["ok"], "didnt": [], "friction": []},
            "goal_adaptation": {
                "rationale": "x",
                "changes": [],
                # missing the Bluebovine domain heading -> rejected
                "proposed_goals_md": "# Org Goals\n\n## Cycle 2026-01\n\n### Homelab\n\n(second domain section omitted)",
            },
            "kb_staleness": [
                {"kb": "kb_unknown", "fact": "stale fact A", "reason": "r",
                 "evidence": ["task:15"]},
                {"kb": "kb_bluebovine", "fact": "stale fact B", "reason": "r",
                 "evidence": ["task:99999"]},
            ],
        }
        wire_fakes(mod, FakeBoardConn(make_done_rows(), make_agent_rows()), llm, make_client())
        job = FakeJob()
        client = make_client()
        goals_path = tmp / "repo" / "docs" / "org" / "goals.md"
        before = goals_path.read_text(encoding="utf-8")
        res = run_dec(mod, {"apply_goals": True}, job, client)
        check("generated", res.get("status") == "generated", str(res))
        doc = Path(res["artifact_path"]).read_text(encoding="utf-8")
        check("real task ref kept", "task:15" in doc)
        check("fake task ref dropped", "task:99999" not in doc)
        check("fake commit ref dropped", "commit:deadbeef0000" not in doc)
        check("fake file ref dropped", "does-not-exist.md" not in doc)
        check("out-of-month review ref dropped", "review:product/2026-W40" not in doc)
        check("score clamped to 1.00", "**1.00**" in doc)
        check("invented KR dropped", "Invented KR" not in doc)
        check("non-numeric score dropped (fill-in n/a instead)",
              "no evidence this cycle (deterministic fill-in)" in doc)
        notes = res.get("guardrail_notes") or []
        check("clamp noted", any("clamped" in n for n in notes), str(notes))
        check("non-numeric noted", any("non-numeric" in n for n in notes))
        check("not-in-goals noted", any("not in goals.md" in n for n in notes))
        check("missing-domain rejection noted", any("missing domain(s)" in n for n in notes))
        check("unknown collection noted", any("unknown collection" in n for n in notes))
        check("no-valid-evidence noted", any("no valid evidence" in n for n in notes))
        check("kb candidate A dropped (unknown collection)", "stale fact A" not in doc)
        check("kb candidate B dropped (no valid evidence)", "stale fact B" not in doc)
        sidecar_text = (tmp / "repo" / "docs" / "org" / "goals.proposed-2026-12.md").read_text(
            encoding="utf-8")
        check("sidecar says NO CHANGE PROPOSED (rejected rewrite)",
              "NO CHANGE PROPOSED" in sidecar_text)
        check("goals.md untouched even with apply_goals=true (invalid rewrite)",
              goals_path.read_text(encoding="utf-8") == before)
        check("goals_applied False", res.get("goals_applied") is False)
        check("no kb_forget called (defaults)",
              not any(c[0] == "kb_forget" for c in client.mcp_calls))


def test_alignment_and_reviews_collected():
    print("test_alignment_and_reviews_collected")
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        mod = load_skill(tmp)
        write_fixtures(tmp)
        state = wire_fakes(mod, FakeBoardConn(make_done_rows(), make_agent_rows()),
                           GOOD_LLM, make_client())
        job = FakeJob()
        res = run_dec(mod, {}, job, make_client())
        check("generated", res.get("status") == "generated", str(res))
        user_content = state["messages"][1]["content"] if state["messages"] else ""
        check("alignment report fed to the LLM", "MARKER-ALIGN-123" in user_content)
        check("in-month weekly review fed to the LLM", "MARKER-REVIEW-W49" in user_content)
        check("out-of-month weekly review excluded", "MARKER-REVIEW-W40" not in user_content)
        check("goals KRs in prompt", "Content output (leading)" in user_content)
        check("board done-in-month in prompt", '"id": 15' in user_content)
        check("kb facts in prompt", "market analysis not started" in user_content)
        check("inputs summary", res.get("inputs", {}).get("weekly_reviews") == 1,
              str(res.get("inputs")))
        check("inputs summary (alignment)",
              res.get("inputs", {}).get("alignment")
              == "docs/org/alignment/2026-11-26-first-pass.md",
              str(res.get("inputs")))
        doc = Path(res["artifact_path"]).read_text(encoding="utf-8")
        check("board line rendered", "2 done card(s) this month" in doc)
        check("kb line rendered", "KB collections: kb_bluebovine (2 doc(s))" in doc)


def test_board_down_degrades():
    print("test_board_down_degrades")
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        mod = load_skill(tmp)
        write_fixtures(tmp)
        wire_fakes(mod, None, GOOD_LLM, None)
        job = FakeJob()
        res = run_dec(mod, {}, job, None)
        check("no error", "error" not in res, str(res.get("error")))
        check("still generated", res.get("status") == "generated", str(res))
        doc = Path(res["artifact_path"]).read_text(encoding="utf-8")
        check("honest board-down line", "board: unavailable this run" in doc)
        check("KB degrades honestly", "KB: n/a (no MCP client injected" in doc)
        # evidence refs from the LLM are all invalid now (no board data)
        check("invalid refs dropped (no board)", "task:15" not in doc)


def test_bad_params():
    print("test_bad_params")
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        mod = load_skill(tmp)
        wire_fakes(mod, FakeBoardConn(), GOOD_LLM, make_client())
        job = FakeJob()
        res = mod.run({"force_date": "2026-13-99"}, job, make_client())
        check("invalid calendar date -> error dict", "error" in res, str(res))
        res = mod.run({"force_date": 20261204}, job, make_client())
        check("non-string force_date -> error dict", "error" in res, str(res))
        res = mod.run({"force_date": "not-a-date"}, job, make_client())
        check("malformed force_date -> error dict", "error" in res, str(res))


def main():
    tests = [
        test_gate_first_friday_unit,
        test_gate_skip_2026_11_27,
        test_gate_run_first_friday,
        test_gate_boundaries,
        test_conservative_apply_defaults,
        test_apply_params,
        test_output_path_and_format,
        test_llm_failure_fallback,
        test_guardrails,
        test_alignment_and_reviews_collected,
        test_board_down_degrades,
        test_bad_params,
    ]
    for fn in tests:
        fn()
    print()
    print(f"{'=' * 60}")
    print(f"PASS: {PASS}  FAIL: {FAIL}")
    if FAILURES:
        print("Failures:")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)


if __name__ == "__main__":
    main()
