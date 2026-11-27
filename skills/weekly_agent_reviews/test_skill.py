#!/usr/bin/env python3
"""Unit tests for the weekly_agent_reviews skill — NO live services.

Covers:
  - non-stacking gate: prior doc with part-7 feedback -> run; prior doc
    with placeholder-only part 7 -> skip (nothing written); no prior doc
    -> bootstrap run; explicit "ack" -> run
  - same-week idempotency guard: this week's doc already exists -> skip
    (doc untouched, no LLM call); force=true -> regenerate
  - guardrail validation: fake evidence refs (task:99999, file that does
    not exist) dropped + noted; real refs kept
  - KR restriction: invented KRs dropped; every charter KR still covered
  - window-date enforcement: out-of-window dates dropped (charter target
    dates allowed)
  - output path/format: docs/agents/<slug>/reviews/YYYY-WW.md (ISO week
    of the run date), 7 parts in order, part 7 is the empty placeholder
  - LLM-failure fallback: deterministic skeleton doc, no crash, no error
  - one LLM call per review doc
  - inactive agents (strategist/marketing/analyst) never targeted
  - zero-activity bootstrap: honest "no board cards assigned yet"
  - spend line + domain-KB line present (deterministic)
  - prior review doc fed to the LLM as the delta input

Run with plain python3 (no pytest, no fastapi, no pymysql, no mem0):
    python3 skills/weekly_agent_reviews/test_skill.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import types
from datetime import datetime, timedelta, timezone
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

    def __init__(self, kb_docs=None, kb_hits=None):
        self.kb_docs = kb_docs or []
        self.kb_hits = kb_hits or []
        self.mcp_calls: list[tuple] = []

    def mcp_call(self, tool: str, args: dict, server_id: str = None) -> dict:
        self.mcp_calls.append((tool, args, server_id))
        if tool == "kb_list_documents":
            kb = str(args.get("kb") or "")
            return {"documents": {kb: self.kb_docs}, "total_docs": len(self.kb_docs)}
        if tool == "kb_search":
            return {"query": args.get("query"), "results": self.kb_hits}
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
        s = self.conn.last_sql
        if "task_events" in s:
            return self.conn.events_rows
        if "GROUP BY" in s:
            return self.conn.done_rows
        return self.conn.tasks_rows


class FakeBoardConn:
    """Routes canned rows by SQL shape (tasks / done-counts / events)."""

    def __init__(self, tasks_rows=(), events_rows=(), done_rows=()):
        self.tasks_rows = list(tasks_rows)
        self.events_rows = list(events_rows)
        self.done_rows = list(done_rows)
        self.last_sql = ""
        self.last_args = None
        self.closed = False

    def cursor(self):
        return FakeBoardCursor(self)

    def close(self):
        self.closed = True


# ---------------------------------------------------------------------------
# Skill module loading (importlib, like the runner does)
# ---------------------------------------------------------------------------


def load_skill(tmp: Path) -> types.ModuleType:
    """Load the skill module with the test env (temp repo root)."""
    os.environ["WEEKLY_AGENT_REVIEWS_REPO_ROOT"] = str(tmp / "repo")
    os.environ["WEEKLY_AGENT_REVIEWS_MODEL_ALIAS"] = "matrix-coder"
    os.environ["LITELLM_BASE_URL"] = "http://127.0.0.1:9"  # unused (patched)
    os.environ["LITELLM_API_KEY"] = "test-key"
    os.environ.pop("LITELLM_MASTER_KEY", None)
    os.environ.pop("LITELLM_KEY_PRODUCT", None)

    spec = importlib.util.spec_from_file_location("skill_weekly_agent_reviews", SKILL_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def wire_fakes(
    mod: types.ModuleType,
    board: FakeBoardConn | None,
    llm_payload,
    kb_client: FakeClient | None = None,
    llm_state: dict | None = None,
):
    """Monkeypatch board conn + LLM call + spend; returns llm_state."""
    if board is None:
        def _db_down():
            raise RuntimeError("board DB unreachable")
        mod._board_conn = _db_down
    else:
        mod._board_conn = lambda: board
    state = llm_state if llm_state is not None else {"calls": 0, "messages": None}

    def fake_llm(messages):
        state["calls"] += 1
        state["messages"] = messages
        if llm_payload is None:
            return None
        return json.dumps(llm_payload)

    mod._llm_chat = fake_llm
    mod._collect_spend = lambda slug: {
        "spend": 0.0,
        "key_created": "2026-11-27",
        "line": "spend: $0.00 (agent-key total — test source)",
    }
    return state


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

CHARTER = """# Charter — product (PM)

## Objectives

- **O1 — Drive the bluebovine product from research to a decision-ready spec.**
- **O2 — Keep the homelab content pipeline moving — ideas groomed to buildable specs.**

## Key results

**O1** (laddered to Bluebovine O2):

| # | KR | Definition | Source | Target | Cadence |
|---|----|------------|--------|--------|---------|
| 1 | Market analysis delivered | Competitive scan + market size & share | repo artifact | 1, by 2026-12-15 | this cycle |
| 2 | Quality (mandatory) | PRDs without acceptance criteria | board specs | 0 | per PRD |

**O2** (laddered to Homelab O1):

| # | KR | Definition | Source | Target | Cadence |
|---|----|------------|--------|--------|---------|
| 1 | Content ideas groomed | Content ideas groomed to board specs | board | ≥ 2/mo | monthly |
| 2 | Quality (mandatory) | Specs missing testable acceptance criteria | board specs | 0 | per spec |
"""

ORG_GOALS = """# Org Goals

### Homelab

**O1 — Personal-interest content ships on a steady rhythm.**

| # | KR | Definition | Source | Target | Cadence |
|---|----|------------|--------|--------|---------|
| 1 | Content output (leading) | Pieces published across the pillars | inventory | 3–4 pieces/mo | monthly |
| 2 | Quality (mandatory) | Published pieces that failed content QA | QA records | 0 | per publish |

### Bluebovine

**O2 — The product is defined and validated, ready to iterate.**

| # | KR | Definition | Source | Target | Cadence |
|---|----|------------|--------|--------|---------|
| 1 | Market analysis | Complete market analysis with evidence | docs/roles/pm | 1, by 2026-12-15 | this cycle |
"""


def write_fixtures(tmp: Path) -> None:
    repo = tmp / "repo"
    (repo / "docs" / "agents" / "product").mkdir(parents=True, exist_ok=True)
    (repo / "docs" / "agents" / "product" / "charter.md").write_text(CHARTER, encoding="utf-8")
    (repo / "docs" / "org").mkdir(parents=True, exist_ok=True)
    (repo / "docs" / "org" / "goals.md").write_text(ORG_GOALS, encoding="utf-8")
    (repo / "docs" / "roles" / "pm").mkdir(parents=True, exist_ok=True)
    (repo / "docs" / "roles" / "pm" / "market-analysis-2026-11-27.md").write_text(
        "# Market analysis (draft)\n", encoding="utf-8"
    )


def prior_week_label() -> str:
    y, w, _ = (datetime.now(timezone.utc) - timedelta(days=7)).isocalendar()
    return f"{y}-W{w:02d}"


def current_week_label() -> str:
    y, w, _ = datetime.now(timezone.utc).isocalendar()
    return f"{y}-W{w:02d}"


def write_prior_doc(tmp: Path, part7: str) -> Path:
    repo = tmp / "repo"
    d = repo / "docs" / "agents" / "product" / "reviews"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{prior_week_label()}.md"
    p.write_text(
        "\n".join(
            [
                f"# Weekly review — product — {prior_week_label()}",
                "",
                "## 1. Prior-week accomplishments (evidence/links)",
                "",
                "- prior week work (MARKER-DELTA-123)",
                "",
                "## 2. KR progress vs trajectory",
                "",
                "- [O1] Market analysis delivered — **no movement**",
                "",
                "## 3. Work-mix check (bau vs OKR vs exec + spend)",
                "",
                "- spend: $0.00 (prior)",
                "",
                "## 4. Quality KR status",
                "",
                "- machine check: 0/0 board spec(s) missing testable acceptance criteria",
                "",
                "## 5. Upcoming plan (proposed cards — suggestions only)",
                "",
                "- none",
                "",
                "## 6. Learnings + domain-KB line",
                "",
                "- none",
                "",
                "## 7. chuck's feedback",
                "",
                part7,
                "",
            ]
        ),
        encoding="utf-8",
    )
    return p


def make_tasks_rows() -> list:
    """Two product-owned tasks: one with acceptance + commit, one without."""
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    day_ms = 86_400_000
    return [
        (
            1, "running", now_ms - 3 * day_ms, now_ms - 1 * day_ms, "abc123def456",
            0, 0, "task/1", None,
            json.dumps(
                {
                    "goal": "Deliver the bluebovine market scan (serves: org/bluebovine/O2-KR1)",
                    "kind": "research",
                    "acceptance": ["scan filed to docs/roles/pm/", "opportunity list with evidence"],
                }
            ),
            6, "Bluebovine",
        ),
        (
            2, "backlog", now_ms - 2 * day_ms, now_ms - 2 * day_ms, None,
            0, 0, None, None,
            json.dumps({"goal": "Groom the PRD to a board spec", "kind": "spec"}),
            6, "Bluebovine",
        ),
    ]


def make_events_rows() -> list:
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    return [
        (1, now_ms - 86_400_000, "state", json.dumps({"from": "running", "to": "qa"})),
        (1, now_ms - 86_400_000 // 2, "qa", json.dumps({"round": 1, "status": "ok"})),
    ]


GOOD_LLM = {
    "accomplishments": [
        {
            "text": "Market scan drafted and filed (task 1 in QA)",
            "evidence": [
                "task:1",
                "commit:abc123def456",
                "file:docs/roles/pm/market-analysis-2026-11-27.md",
            ],
        }
    ],
    "kr_progress": [
        {
            "kr": "Market analysis delivered",
            "objective": "O1",
            "status": "on track",
            "evidence": ["task:1", "file:docs/roles/pm/market-analysis-2026-11-27.md"],
            "note": "scan drafted 2026-11-25; target 1 by 2026-12-15",
        }
    ],
    "work_mix": {
        "bau": "none",
        "okr": "market scan (org/bluebovine/O2-KR1)",
        "exec": "none",
        "note": "OKR-heavy week",
    },
    "quality_krs": [
        {"kr": "Quality (mandatory)", "status": "n/a", "note": "1 spec lacks acceptance (see machine check)"}
    ],
    "upcoming_plan": ["Groom the PRD card (Bluebovine, serves O1-KR3)"],
    "learnings": [
        {"text": "domain KB is empty", "kb_note": "collection does not exist yet"}
    ],
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_bootstrap_no_prior_doc():
    print("test_bootstrap_no_prior_doc")
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        mod = load_skill(tmp)
        write_fixtures(tmp)
        state = wire_fakes(mod, FakeBoardConn(), GOOD_LLM, FakeClient(),
                           {"calls": 0, "messages": None})
        job = FakeJob()
        res = mod.run({"agents": ["product"], "non_stacking": True}, job, FakeClient())
        check("no error", "error" not in res, str(res.get("error")))
        agent = res["agents"][0]
        check("status generated", agent["status"] == "generated", str(agent))
        check("bootstrap gate reason", "bootstrap" in agent.get("gate_reason", ""),
              agent.get("gate_reason"))
        # output path: docs/agents/product/reviews/<current ISO week>.md
        expected = tmp / "repo" / "docs" / "agents" / "product" / "reviews" / f"{current_week_label()}.md"
        check("artifact path matches template", agent["path"] == str(expected), str(agent["path"]))
        check("file exists", expected.is_file())
        doc = expected.read_text()
        check("doc says honest bootstrap state", "no board cards assigned yet" in doc)
        check("spend line present", "spend: $0.00 (agent-key total — test source)" in doc)
        check("part 7 placeholder present", "(pending — appended after chuck responds)" in doc)
        check("exactly one LLM call", state["calls"] == 1, f"got {state['calls']}")
        # the reviews dir was created
        check("reviews dir created", expected.parent.is_dir())


def test_one_llm_call_and_delta_input():
    print("test_one_llm_call_and_delta_input")
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        mod = load_skill(tmp)
        write_fixtures(tmp)
        prior = write_prior_doc(tmp, "Looks good — ship the market analysis card next week.")
        state = wire_fakes(mod, FakeBoardConn(make_tasks_rows(), make_events_rows()),
                           GOOD_LLM, FakeClient(), {"calls": 0, "messages": None})
        job = FakeJob()
        res = mod.run({"agents": ["product"], "non_stacking": True}, job, FakeClient())
        agent = res["agents"][0]
        check("generated (prior doc has feedback)", agent["status"] == "generated", str(agent))
        check("exactly one LLM call", state["calls"] == 1, f"got {state['calls']}")
        user_content = state["messages"][1]["content"] if state["messages"] else ""
        check("prior review fed as delta input", "MARKER-DELTA-123" in user_content)
        check("board data in prompt", "market scan" in user_content)
        check("charter KRs in prompt", "Market analysis delivered" in user_content)
        check("org goals in prompt", "Content output (leading)" in user_content)
        # prior doc untouched
        check("prior doc untouched", "Looks good — ship the market analysis card" in prior.read_text())
        doc = Path(agent["path"]).read_text()
        check("delta mode label", "delta" in doc.splitlines()[6], doc.splitlines()[6])


def test_non_stacking_skip():
    print("test_non_stacking_skip")
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        mod = load_skill(tmp)
        write_fixtures(tmp)
        prior = write_prior_doc(tmp, "(pending — appended after chuck responds)")
        state = wire_fakes(mod, FakeBoardConn(), GOOD_LLM, FakeClient(),
                           {"calls": 0, "messages": None})
        job = FakeJob()
        res = mod.run({"agents": ["product"], "non_stacking": True}, job, FakeClient())
        agent = res["agents"][0]
        check("status skipped", agent["status"] == "skipped", str(agent))
        check("skip reason names non-stacking", "non-stacking" in agent.get("skip_reason", ""),
              agent.get("skip_reason"))
        check("no LLM call on skip", state["calls"] == 0)
        check("nothing written (only the prior doc)",
              [p.name for p in (tmp / "repo" / "docs" / "agents" / "product" / "reviews").iterdir()]
              == [prior.name])
        check("no artifact path", agent["path"] is None)
        check("summary mentions skip", "product=skipped" in res["summary"], res["summary"])


def test_non_stacking_ack():
    print("test_non_stacking_ack")
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        mod = load_skill(tmp)
        write_fixtures(tmp)
        write_prior_doc(tmp, "ack")
        wire_fakes(mod, FakeBoardConn(), GOOD_LLM, FakeClient())
        job = FakeJob()
        res = mod.run({"agents": ["product"], "non_stacking": True}, job, FakeClient())
        agent = res["agents"][0]
        check("explicit ack -> run", agent["status"] == "generated", str(agent))


def test_non_stacking_disabled_by_params():
    print("test_non_stacking_disabled_by_params")
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        mod = load_skill(tmp)
        write_fixtures(tmp)
        write_prior_doc(tmp, "(pending — appended after chuck responds)")
        wire_fakes(mod, FakeBoardConn(), GOOD_LLM, FakeClient())
        job = FakeJob()
        res = mod.run({"agents": ["product"], "non_stacking": False}, job, FakeClient())
        agent = res["agents"][0]
        check("non_stacking=false -> run anyway", agent["status"] == "generated", str(agent))


def test_output_path_and_format():
    print("test_output_path_and_format")
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        mod = load_skill(tmp)
        write_fixtures(tmp)
        wire_fakes(mod, FakeBoardConn(make_tasks_rows(), make_events_rows()),
                   GOOD_LLM, FakeClient())
        job = FakeJob()
        res = mod.run(
            {
                "agents": ["product"],
                "non_stacking": True,
                "output": "docs/agents/<slug>/reviews/YYYY-WW.md",
            },
            job,
            FakeClient(),
        )
        agent = res["agents"][0]
        expected = tmp / "repo" / "docs" / "agents" / "product" / "reviews" / f"{current_week_label()}.md"
        check("ISO week of the run date in the filename",
              agent["path"] == str(expected), str(agent["path"]))
        doc = expected.read_text()
        heads = [
            "## 1. Prior-week accomplishments",
            "## 2. KR progress vs trajectory",
            "## 3. Work-mix check",
            "## 4. Quality KR status",
            "## 5. Upcoming plan",
            "## 6. Learnings + domain-KB line",
            "## 7. chuck's feedback",
        ]
        pos = [doc.index(h) for h in heads]
        check("7 parts present in order", pos == sorted(pos), str(pos))
        check("week label in doc header", f"# Weekly review — product — {current_week_label()}" in doc)
        check("window line present", "window:" in doc)
        # part 7 is the LAST section and holds only the placeholder
        part7 = doc.split("## 7. chuck's feedback", 1)[1]
        check("part 7 holds only the placeholder",
              "(pending — appended after chuck responds)" in part7
              and "## " not in part7.replace("(pending — appended after chuck responds)", ""),
              part7[:200])


def test_guardrail_fake_evidence_dropped():
    print("test_guardrail_fake_evidence_dropped")
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        mod = load_skill(tmp)
        write_fixtures(tmp)
        llm = {
            "accomplishments": [
                {
                    "text": "Market scan drafted (task 1 in QA)",
                    "evidence": [
                        "task:1",
                        "commit:abc123def456",
                        "task:99999",                      # fake board card id
                        "commit:deadbeef0000",             # fake sha
                        "file:docs/roles/pm/market-analysis-2026-11-27.md",
                        "file:docs/roles/pm/does-not-exist.md",  # fake path
                    ],
                },
                {
                    "text": "Invented work on 2020-01-01",
                    "evidence": ["task:1"],
                },
            ],
            "kr_progress": [
                {
                    "kr": "Market analysis delivered",
                    "objective": "O1",
                    "status": "on track",
                    "evidence": ["task:1"],
                    "note": "scan drafted 2026-11-25",
                },
                {
                    "kr": "Invented KR",
                    "objective": "O9",
                    "status": "on track",
                    "evidence": [],
                    "note": "not in the charter",
                },
            ],
            "work_mix": {"bau": "none", "okr": "O1 work", "exec": "none", "note": "OKR-heavy"},
            "quality_krs": [
                {"kr": "Quality (mandatory)", "status": "pass", "note": "ok"},
                {"kr": "Not A Quality KR", "status": "pass", "note": "x"},
            ],
            "upcoming_plan": ["Groom the PRD card (Bluebovine)"],
            "learnings": [{"text": "kb empty", "kb_note": ""}],
        }
        wire_fakes(mod, FakeBoardConn(make_tasks_rows(), make_events_rows()), llm, FakeClient())
        job = FakeJob()
        res = mod.run({"agents": ["product"], "non_stacking": True}, job, FakeClient())
        agent = res["agents"][0]
        check("generated", agent["status"] == "generated", str(agent))
        doc = Path(agent["path"]).read_text()
        notes = agent.get("guardrail_notes") or []
        check("real task ref kept", "task:1" in doc)
        check("real commit ref kept", "commit:abc123def456" in doc)
        check("real file ref kept", "file:docs/roles/pm/market-analysis-2026-11-27.md" in doc)
        check("fake task ref dropped", "task:99999" not in doc)
        check("fake commit ref dropped", "commit:deadbeef0000" not in doc)
        check("fake file ref dropped", "does-not-exist.md" not in doc)
        check("out-of-window accomplishment dropped", "Invented work on 2020-01-01" not in doc)
        check("invented KR dropped", "Invented KR" not in doc)
        check("non-quality KR dropped from part 4", "Not A Quality KR" not in doc)
        check("guardrail notes recorded", any("invalid evidence ref" in n for n in notes),
              str(notes))
        check("window-date drop noted", any("out-of-window" in n for n in notes), str(notes))
        check("KR drop noted", any("not in charter" in n for n in notes), str(notes))
        # every charter KR still covered (honest fill-in)
        check("charter KRs all covered", "Content ideas groomed" in doc)
        check("no-movement fill-in present", "no movement this week (no data in window)" in doc)


def test_charter_target_date_allowed():
    print("test_charter_target_date_allowed")
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        mod = load_skill(tmp)
        write_fixtures(tmp)
        llm = {
            "accomplishments": [],
            "kr_progress": [
                {
                    "kr": "Market analysis delivered",
                    "objective": "O1",
                    "status": "on track",
                    "evidence": [],
                    "note": "target 1 by 2026-12-15 (charter date)",
                }
            ],
            "work_mix": {"bau": "", "okr": "", "exec": "", "note": ""},
            "quality_krs": [],
            "upcoming_plan": [],
            "learnings": [],
        }
        wire_fakes(mod, FakeBoardConn(), llm, FakeClient())
        job = FakeJob()
        res = mod.run({"agents": ["product"], "non_stacking": True}, job, FakeClient())
        agent = res["agents"][0]
        doc = Path(agent["path"]).read_text()
        check("charter target date kept (quoted from input)", "2026-12-15" in doc)


def test_llm_failure_fallback():
    print("test_llm_failure_fallback")
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        mod = load_skill(tmp)
        write_fixtures(tmp)
        wire_fakes(mod, FakeBoardConn(make_tasks_rows(), make_events_rows()), None, FakeClient())
        job = FakeJob()
        res = mod.run({"agents": ["product"], "non_stacking": True}, job, FakeClient())
        check("no error on LLM failure", "error" not in res, str(res.get("error")))
        agent = res["agents"][0]
        check("still generated (deterministic skeleton)", agent["status"] == "generated",
              str(agent))
        doc = Path(agent["path"]).read_text()
        check("fallback mode label", "deterministic-fallback" in doc)
        check("fallback lists the real board task", "task 1 (Bluebovine)" in doc)
        check("fallback KR fill-in", "no movement this week (deterministic fallback" in doc)
        heads = ["## 1.", "## 2.", "## 3.", "## 4.", "## 5.", "## 6.", "## 7."]
        pos = [doc.index(h) for h in heads]
        check("7 parts still in order", pos == sorted(pos))
        check("part 7 placeholder still present",
              "(pending — appended after chuck responds)" in doc)
        check("spend line still present", "spend: $0.00 (agent-key total — test source)" in doc)


def test_quality_machine_check():
    print("test_quality_machine_check")
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        mod = load_skill(tmp)
        write_fixtures(tmp)
        wire_fakes(mod, FakeBoardConn(make_tasks_rows(), make_events_rows()),
                   GOOD_LLM, FakeClient())
        job = FakeJob()
        res = mod.run({"agents": ["product"], "non_stacking": True}, job, FakeClient())
        doc = Path(res["agents"][0]["path"]).read_text()
        part4 = doc.split("## 4. Quality KR status", 1)[1].split("## 5.", 1)[0]
        check("machine check line: 1/2 specs missing acceptance",
              "1/2 board spec(s) missing testable acceptance criteria" in part4, part4[:300])


def test_inactive_agents_never_targeted():
    """The deactivation gate (INACTIVE_AGENTS) is retained for future OFF
    slugs — all 4 standing agents are active by default (2026-11-27)."""
    print("test_inactive_agents_never_targeted")
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        mod = load_skill(tmp)
        write_fixtures(tmp)
        wire_fakes(mod, FakeBoardConn(), GOOD_LLM, FakeClient())
        job = FakeJob()
        # default: all 4 standing agents are ACTIVE (Q13 revised 2026-11-27)
        res = mod.run(
            {"agents": ["product", "strategist", "marketing", "analyst"],
             "non_stacking": True},
            job,
            FakeClient(),
        )
        check("no error", "error" not in res, str(res.get("error")))
        check("all four active by default",
              all(a["status"] == "generated" for a in res["agents"]), str(res["agents"]))
        # future deactivation: a slug in INACTIVE_AGENTS is skipped even if
        # listed (keys + workspaces stay in place; the gate is the switch)
        mod.INACTIVE_AGENTS = {"strategist", "marketing", "analyst"}
        res2 = mod.run(
            {"agents": ["strategist", "marketing", "analyst"], "non_stacking": True},
            job,
            FakeClient(),
        )
        check("no error (deactivated)", "error" not in res2, str(res2.get("error")))
        check("all three skipped when deactivated",
              all(a["status"] == "skipped" for a in res2["agents"]), str(res2["agents"]))
        check("skip reason says OFF",
              all("OFF" in a.get("skip_reason", "") for a in res2["agents"]))


def test_mixed_agents_and_board_down():
    print("test_mixed_agents_and_board_down")
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        mod = load_skill(tmp)
        write_fixtures(tmp)
        # Board DB down + KB client missing -> everything degrades, no crash.
        wire_fakes(mod, None, None, None)
        job = FakeJob()
        res = mod.run({"agents": ["product", "strategist"], "non_stacking": True}, job, None)
        check("no error", "error" not in res, str(res.get("error")))
        by_slug = {a["agent"]: a for a in res["agents"]}
        check("product generated with degraded inputs",
              by_slug["product"]["status"] == "generated", str(by_slug["product"]))
        doc = Path(by_slug["product"]["path"]).read_text()
        check("honest zero-activity line (board down — unverified, nothing claimed)",
              "Board data unavailable this run" in doc and "nothing is claimed" in doc)
        check("KB line degrades honestly", "KB (kb_bluebovine)" in doc)
        check("strategist generated too (active since 2026-11-27)",
              by_slug["strategist"]["status"] == "generated", str(by_slug["strategist"]))


def test_kb_window_facts():
    print("test_kb_window_facts")
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        mod = load_skill(tmp)
        write_fixtures(tmp)
        now_iso = datetime.now(timezone.utc).isoformat()
        client = FakeClient(
            kb_docs=[
                {"source": "bluebovine-positioning.md", "ingested_at": now_iso, "chunks": 3},
                {"source": "old-fact.md", "ingested_at": "2020-01-01T00:00:00", "chunks": 1},
            ],
            kb_hits=[{"source": "market.md", "snippet": "bluebovine = PM consulting"}],
        )
        wire_fakes(mod, FakeBoardConn(), GOOD_LLM, client)
        job = FakeJob()
        res = mod.run({"agents": ["product"], "non_stacking": True}, job, client)
        doc = Path(res["agents"][0]["path"]).read_text()
        part6 = doc.split("## 6. Learnings", 1)[1].split("## 7.", 1)[0]
        check("KB doc added in window reported",
              "bluebovine-positioning.md" in part6, part6[:300])
        check("out-of-window KB doc not reported", "old-fact.md" not in part6)
        check("kb_search called for the owned collection",
              any(c[0] == "kb_search" and c[1].get("kb") == "kb_bluebovine" for c in client.mcp_calls))
        check("kb_list_documents called",
              any(c[0] == "kb_list_documents" for c in client.mcp_calls))


def test_missing_kb_collection_graceful():
    print("test_missing_kb_collection_graceful")
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        mod = load_skill(tmp)
        write_fixtures(tmp)

        class MissingKbClient(FakeClient):
            def mcp_call(self, tool, args, server_id=None):
                if tool == "kb_search":
                    return {
                        "query": args.get("query"),
                        "results": [],
                        "note": "KB 'kb_bluebovine' does not exist yet.",
                    }
                return super().mcp_call(tool, args, server_id)

        client = MissingKbClient()
        wire_fakes(mod, FakeBoardConn(), GOOD_LLM, client)
        job = FakeJob()
        res = mod.run({"agents": ["product"], "non_stacking": True}, job, client)
        check("no error", "error" not in res, str(res.get("error")))
        doc = Path(res["agents"][0]["path"]).read_text()
        check("missing collection reported honestly",
              "collection does not exist yet" in doc)


def test_bad_params():
    print("test_bad_params")
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        mod = load_skill(tmp)
        wire_fakes(mod, FakeBoardConn(), GOOD_LLM, FakeClient())
        job = FakeJob()
        res = mod.run({"agents": []}, job, FakeClient())
        check("empty agents -> error dict", "error" in res, str(res))
        res2 = mod.run({"agents": "not-a-list"}, job, FakeClient())
        check("non-list agents -> error dict", "error" in res2, str(res2))
        # comma-separated string is accepted
        res3 = mod.run({"agents": "product, strategist"}, job, FakeClient())
        check("string agents accepted", "error" not in res3, str(res3))
        check("strategist generated from a string list (active)",
              next(a for a in res3["agents"] if a["agent"] == "strategist")["status"]
              == "generated")


def test_same_week_doc_guard():
    print("test_same_week_doc_guard")
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        mod = load_skill(tmp)
        write_fixtures(tmp)
        state = wire_fakes(mod, FakeBoardConn(), GOOD_LLM, FakeClient(),
                           {"calls": 0, "messages": None})
        job = FakeJob()
        # first run this week: bootstrap -> generated
        res1 = mod.run({"agents": ["product"], "non_stacking": True}, job, FakeClient())
        a1 = res1["agents"][0]
        check("first run generated", a1["status"] == "generated", str(a1))
        first_doc = Path(a1["path"]).read_text()
        # same-week re-fire (no force): skipped, doc untouched, no LLM call
        state2 = wire_fakes(mod, FakeBoardConn(), GOOD_LLM, FakeClient(),
                            {"calls": 0, "messages": None})
        res2 = mod.run({"agents": ["product"], "non_stacking": True}, job, FakeClient())
        a2 = res2["agents"][0]
        check("same-week re-fire skipped", a2["status"] == "skipped", str(a2))
        check("skip reason names the existing doc",
              "already exists" in a2.get("skip_reason", ""), a2.get("skip_reason"))
        check("no LLM call on same-week skip", state2["calls"] == 0)
        check("doc untouched (part-7 feedback safe)",
              Path(a2["path"]).read_text() == first_doc)
        # force=true: regenerates (overwrites) with one LLM call
        state3 = wire_fakes(mod, FakeBoardConn(), GOOD_LLM, FakeClient(),
                            {"calls": 0, "messages": None})
        res3 = mod.run({"agents": ["product"], "non_stacking": True, "force": True},
                       job, FakeClient())
        a3 = res3["agents"][0]
        check("force=true regenerates", a3["status"] == "generated", str(a3))
        check("force run made exactly one LLM call", state3["calls"] == 1)
        check("regenerated doc exists", Path(a3["path"]).is_file())


def main():
    tests = [
        test_bootstrap_no_prior_doc,
        test_one_llm_call_and_delta_input,
        test_non_stacking_skip,
        test_non_stacking_ack,
        test_non_stacking_disabled_by_params,
        test_same_week_doc_guard,
        test_output_path_and_format,
        test_guardrail_fake_evidence_dropped,
        test_charter_target_date_allowed,
        test_llm_failure_fallback,
        test_quality_machine_check,
        test_inactive_agents_never_targeted,
        test_mixed_agents_and_board_down,
        test_kb_window_facts,
        test_missing_kb_collection_graceful,
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
