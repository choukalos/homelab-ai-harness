#!/usr/bin/env python3
"""Unit tests for the harness_reflection skill (Phase 3) — NO live services.

Covers:
  - zero inputs (no sessions/memories/jobs/git) -> completes cleanly,
    digest artifact produced, no LLM call, no writes (must work with
    zero sessions)
  - identity (D10): job runs under the service identity; every memory
    write lands on the TARGET user (chuck), never service
  - planted correction (same correction >=2x) -> preference memory with
    importance=high + provenance (session ref + date)
  - friction lessons -> structured "Lesson (<date>): ..." memory
  - deterministic lesson fallback when the LLM call fails
  - supersede statements -> memory writes with valid evidence
  - proposal guardrails: <=5/run; every proposal >=1 REAL evidence ref;
    no .env / compose restart semantics / memory privacy scoping targets;
    memory-conventions scope changes require a quoted user statement;
    dedup against open proposals by slug, title, same-day file, AND
    evidence overlap (re-worded proposal citing >=50% of an open
    proposal's evidence refs is dropped)
  - staleness: proposals open >14d flagged in the digest (never deleted)
  - LIVE row-shape regression (2026-11-08 dry run): the REAL
    skills/runner/proposals.py module is exercised with rows shaped
    exactly like real MySQL rows (7-tuples, JSON columns as str/bytes/
    pre-parsed/NULL) — the original bug was a module-level ``def list``
    shadowing the builtin ``list``, which broke isinstance() in
    _row_to_dict on every real row while the mocked tests passed
  - no file outside proposals/ + the artifact dir modified by the job
  - invalid target user (service/unknown) rejected

Run with plain python3 (no pytest, no fastapi, no pymysql, no mem0):
    python3 skills/harness_reflection/test_skill.py
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
    """Canned-JSON LLM client (None payload = empty content = LLM failure)."""

    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    def chat_completion(self, model, messages, **kw):
        self.calls += 1
        if self.payload is None:
            return {"choices": [{"message": {"content": ""}}]}
        return {"choices": [{"message": {"content": json.dumps(self.payload)}}]}


class FakeMemoryInterface:
    def __init__(self):
        self.memories: list[dict] = []
        self.writes: list[dict] = []

    def list_memories(self, user, limit=20):
        return self.memories

    def learn_from_turn(self, user_id, messages, source="chat", agent_id=None,
                        run_id=None, importance="normal", confidence="normal",
                        infer=True, prompt=None, household=False):
        self.writes.append(
            {
                "user_id": user_id,
                "content": messages[0]["content"],
                "source": source,
                "importance": importance,
                "infer": infer,
                "agent_id": agent_id,
                "household": household,
            }
        )
        return [f"mem-{len(self.writes)}"]


class FakeProposals:
    def __init__(self):
        self.open: list[dict] = []
        self.inserted: list[dict] = []
        self.db_up = True

    def list_proposals(self, status=None, limit=50):
        if not self.db_up:
            raise RuntimeError("proposals index unavailable (MySQL)")
        return [p for p in self.open if status is None or p.get("status") == status]

    def insert(self, slug, title, evidence, target_files, status="open", created_at=None):
        self.inserted.append(
            {
                "slug": slug,
                "title": title,
                "evidence": evidence,
                "target_files": target_files,
                "status": status,
                "created_at": created_at,
            }
        )
        return True


class FakeSessions:
    def __init__(self):
        self.ingests: list[dict] = []
        self.db_up = True

    def list_ingests(self, user_id, since=None, limit=100):
        if not self.db_up:
            raise RuntimeError("session index unavailable (MySQL)")
        return self.ingests


class FakeCursor:
    def __init__(self, rows):
        self.rows = rows
        self.sql = ""
        self.args = None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, args=None):
        self.sql = sql
        self.args = args

    def fetchall(self):
        return self.rows


class FakeConn:
    def __init__(self, rows):
        self._rows = rows
        self.closed = False

    def cursor(self):
        return FakeCursor(self._rows)

    def close(self):
        self.closed = True


# ---------------------------------------------------------------------------
# Skill module loading (importlib, like the runner does)
# ---------------------------------------------------------------------------


def load_skill(tmp: Path) -> types.ModuleType:
    """Load the skill module with test env (temp dirs, no identity map)."""
    os.environ["HARNESS_REFLECTION_PROPOSALS_DIR"] = str(tmp / "proposals")
    os.environ["HARNESS_REFLECTION_ARTIFACT_DIR"] = str(tmp / "artifacts")
    os.environ["SESSIONS_DATA_ROOT"] = str(tmp / "sessions")
    os.environ["HARNESS_REFLECTION_GIT_REPO"] = str(tmp / "no-such-repo")
    os.environ["MEMORY_USER_KEYS"] = "chuck=FAKE_KEY_CHUCK"

    spec = importlib.util.spec_from_file_location("skill_harness_reflection", SKILL_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def install_fakes(
    mod: types.ModuleType,
    mem: FakeMemoryInterface,
    props: FakeProposals,
    sess: FakeSessions,
    job_rows=None,
):
    """Inject fake memory/proposals/sessions modules + job DB conn."""
    memory_pkg = types.ModuleType("memory")
    memory_pkg.interface = mem
    sys.modules["memory"] = memory_pkg
    sys.modules["memory.interface"] = mem
    sys.modules["proposals"] = props
    sys.modules["sessions"] = sess
    if job_rows is None:
        def _db_down():
            raise RuntimeError("MySQL unreachable")
        mod._db_conn = _db_down
    else:
        mod._db_conn = lambda: FakeConn(job_rows)


def now_iso(offset_days: float = 0.0) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=offset_days)).isoformat()


def make_job_rows() -> list:
    """skill_jobs rows: (skill, status, created_at, data_json)."""
    def data(job_id, skill, created, completed=None, error=None):
        d = {
            "job_id": job_id,
            "skill": skill,
            "user_id": "chuck",
            "created_at": created,
            "completed_at": completed,
            "status": "completed",
            "params": {"prompt": "do the thing"},
        }
        if error:
            d["error"] = error
        return json.dumps(d)

    return [
        # failed job (friction)
        (
            "homelab_report",
            "failed",
            now_iso(2),
            data("job-fail-1", "homelab_report", now_iso(2), now_iso(2), "boom: timeout"),
        ),
        # completed job with duration
        (
            "morning_brief",
            "completed",
            now_iso(1),
            data("job-ok-1", "morning_brief", now_iso(1), now_iso(1) + "01:00:00"),
        ),
        # re-run pattern (retry signal): same skill + intent twice
        (
            "research_brief",
            "completed",
            now_iso(3),
            data("job-retry-1", "research_brief", now_iso(3), now_iso(3), None),
        ),
        (
            "research_brief",
            "completed",
            now_iso(1),
            data("job-retry-2", "research_brief", now_iso(1), now_iso(1), None),
        ),
    ]


def make_memories() -> list[dict]:
    return [
        {
            "id": "mem-old-1",
            "text": "Chuck uses triads for metal tabs (OUTDATED)",
            "created_at": now_iso(40),
            "updated_at": now_iso(2),
            "metadata": {"source": "chat", "importance": "normal"},
        },
        {
            "id": "mem-new-1",
            "text": "The homelab uses a matrix-coder model alias",
            "created_at": now_iso(3),
            "updated_at": now_iso(3),
            "metadata": {"source": "scheduled", "importance": "normal"},
        },
    ]


def make_session_transcript(tmp: Path, user: str, sid: str) -> None:
    """Write a planted-correction transcript (same correction twice)."""
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    d = tmp / "sessions" / user / day
    d.mkdir(parents=True, exist_ok=True)
    turns = [
        {"role": "user", "content": "rip this riff in power chords"},
        {"role": "assistant", "content": "done — power chords throughout"},
        {"role": "user", "content": "no, use triads for metal — I said that last week too"},
        {"role": "assistant", "content": "sorry, redone with triads"},
        {"role": "user", "content": "no, triads for metal — I told you before"},
        {"role": "assistant", "content": "fixed with triads this time"},
    ]
    (d / f"{sid}.jsonl").write_text("\n".join(json.dumps(t) for t in turns))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_zero_inputs():
    print("test_zero_inputs")
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        mod = load_skill(tmp)
        mem, props, sess = FakeMemoryInterface(), FakeProposals(), FakeSessions()
        install_fakes(mod, mem, props, sess)  # job DB down too
        client = FakeClient(None)
        job = FakeJob(user_id="service")
        res = mod.run({"user": "chuck", "days": 7}, job, client)
        check("no error", "error" not in res, str(res.get("error")))
        check("no LLM call with zero signals", client.calls == 0)
        check("no memory writes", len(mem.writes) == 0)
        check("no proposals", len(props.inserted) == 0)
        check("digest artifact produced", bool(res.get("artifact_path")))
        art = Path(res["artifact_path"])
        check("digest file exists", art.is_file())
        check(
            "digest says nothing to maintain",
            "nothing to maintain" in art.read_text(),
        )
        check(
            "pointer file written",
            (tmp / "artifacts" / "latest_pointer.txt").is_file(),
        )
        check("summary mentions user", "user=chuck" in res["summary"])


def test_identity_d10():
    print("test_identity_d10")
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        mod = load_skill(tmp)
        mem, props, sess = FakeMemoryInterface(), FakeProposals(), FakeSessions()
        mem.memories = make_memories()
        install_fakes(mod, mem, props, sess)
        client = FakeClient(
            {
                "supersedes": [
                    {
                        "text": "Chuck uses triads (not power chords) for metal tabs — updated 2026-11-08.",
                        "evidence": ["memory:mem-old-1"],
                    }
                ],
                "corrections": [],
                "lessons": [],
                "proposals": [],
            }
        )
        job = FakeJob(user_id="service")  # scheduled run identity
        res = mod.run({"user": "chuck", "days": 7}, job, client)
        check("no error", "error" not in res, str(res.get("error")))
        check("one memory write", len(mem.writes) == 1, f"got {len(mem.writes)}")
        if mem.writes:
            w = mem.writes[0]
            check("write attributed to chuck (not service)", w["user_id"] == "chuck")
            check("write source=harness_reflection", w["source"] == "harness_reflection")
            check("write verbatim (infer=False)", w["infer"] is False)


def test_planted_correction():
    print("test_planted_correction")
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        mod = load_skill(tmp)
        mem, props, sess = FakeMemoryInterface(), FakeProposals(), FakeSessions()
        mem.memories = make_memories()
        make_session_transcript(tmp, "chuck", "sess-corr-1")
        sess.ingests = [
            {
                "user_id": "chuck",
                "host": "mac",
                "session_id": "sess-corr-1",
                "ingested_at": now_iso(1),
            }
        ]
        install_fakes(mod, mem, props, sess)
        client = FakeClient(
            {
                "supersedes": [],
                "corrections": [
                    {
                        "text": "Use triads (not power chords) for metal riffs.",
                        "evidence": ["session:sess-corr-1"],
                        "count": 2,
                    }
                ],
                "lessons": [],
                "proposals": [],
            }
        )
        job = FakeJob(user_id="service")
        res = mod.run({"user": "chuck", "days": 7}, job, client)
        check("no error", "error" not in res, str(res.get("error")))
        corr = [w for w in mem.writes if w["importance"] == "high"]
        check("correction stored with importance=high", len(corr) == 1, f"got {len(corr)}")
        if corr:
            check(
                "provenance: session ref + date",
                "session:sess-corr-1" in corr[0]["content"]
                and datetime.now(timezone.utc).strftime("%Y-%m-%d") in corr[0]["content"],
                corr[0]["content"][:120],
            )
        check("digest lists the correction", "correction (high)" in res["report"])


def test_lessons_and_fallback():
    print("test_lessons_and_fallback")
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        mod = load_skill(tmp)
        mem, props, sess = FakeMemoryInterface(), FakeProposals(), FakeSessions()
        install_fakes(mod, mem, props, sess, job_rows=make_job_rows())
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        # (a) LLM-provided lesson with real job evidence
        client = FakeClient(
            {
                "supersedes": [],
                "corrections": [],
                "lessons": [
                    {
                        "text": "homelab_report timed out on a large query -> cap the query window",
                        "evidence": ["job:job-fail-1"],
                    }
                ],
                "proposals": [],
            }
        )
        job = FakeJob(user_id="service")
        res = mod.run({"user": "chuck", "days": 7}, job, client)
        lessons = [w for w in mem.writes if w["content"].startswith(f"Lesson ({today}):")]
        check("LLM lesson stored with structured prefix", len(lessons) == 1, str(lessons))
        # (b) LLM failure -> deterministic fallback from the failed job
        mem2, props2, sess2 = FakeMemoryInterface(), FakeProposals(), FakeSessions()
        install_fakes(mod, mem2, props2, sess2, job_rows=make_job_rows())
        client2 = FakeClient(None)  # empty content = LLM failure
        res2 = mod.run({"user": "chuck", "days": 7}, job, client2)
        lessons2 = [
            w for w in mem2.writes if w["content"].startswith(f"Lesson ({today}):")
        ]
        check(
            "deterministic fallback lesson on LLM failure",
            len(lessons2) >= 1,
            str(lessons2)[:200],
        )
        check("no error on LLM failure", "error" not in res2)


def test_proposal_guardrails():
    print("test_proposal_guardrails")
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        mod = load_skill(tmp)
        mem, props, sess = FakeMemoryInterface(), FakeProposals(), FakeSessions()
        mem.memories = make_memories()
        install_fakes(mod, mem, props, sess, job_rows=make_job_rows())
        # 4 good proposals + the conventions-with-quote proposal below =
        # exactly 5 (the cap); one more good proposal (good-proposal-cap,
        # placed AFTER the accepted ones) must be rejected by the cap.
        proposals = []
        for i in range(4):
            proposals.append(
                {
                    "slug": f"good-proposal-{i}",
                    "title": f"Good proposal {i}",
                    "what": f"Do thing {i}",
                    "why": f"Because {i}",
                    "risk": "Low; revert the file",
                    "files": [f"skills/some_skill_{i}/skill.py"],
                    "evidence": ["memory:mem-new-1"],
                }
            )
        # no evidence
        proposals.append(
            {
                "slug": "no-evidence",
                "title": "No evidence proposal",
                "what": "x",
                "why": "y",
                "risk": "z",
                "files": ["skills/x/skill.py"],
                "evidence": [],
            }
        )
        # invented evidence (id not in inputs)
        proposals.append(
            {
                "slug": "invented-evidence",
                "title": "Invented evidence proposal",
                "what": "x",
                "why": "y",
                "risk": "z",
                "files": ["skills/x/skill.py"],
                "evidence": ["memory:mem-does-not-exist"],
            }
        )
        # forbidden: .env
        proposals.append(
            {
                "slug": "touch-env",
                "title": "Touch .env",
                "what": "x",
                "why": "y",
                "risk": "z",
                "files": [".env"],
                "evidence": ["memory:mem-new-1"],
            }
        )
        # forbidden: compose restart semantics
        proposals.append(
            {
                "slug": "touch-compose",
                "title": "Touch compose restart",
                "what": "x",
                "why": "y",
                "risk": "z",
                "files": ["compose/compose.skill-runner.yml"],
                "evidence": ["memory:mem-new-1"],
            }
        )
        # forbidden: memory privacy scoping
        proposals.append(
            {
                "slug": "touch-privacy",
                "title": "Touch memory privacy scoping",
                "what": "x",
                "why": "y",
                "risk": "z",
                "files": ["skills/runner/memory/policy.py"],
                "evidence": ["memory:mem-new-1"],
            }
        )
        # memory-conventions WITHOUT a quoted user statement -> rejected
        proposals.append(
            {
                "slug": "conventions-no-quote",
                "title": "Change conventions scope rules",
                "what": "x",
                "why": "y",
                "risk": "z",
                "files": ["agents-skills/memory-conventions/SKILL.md"],
                "evidence": ["memory:mem-new-1"],
            }
        )
        # memory-conventions WITH a quoted user statement -> allowed
        proposals.append(
            {
                "slug": "conventions-with-quote",
                "title": "Medical voice notes default to private",
                "what": "Default wife's medical content to private",
                "why": "Chuck stated this on 2026-11-08",
                "risk": "Low; revert the SKILL.md",
                "files": ["agents-skills/memory-conventions/SKILL.md"],
                "evidence": [
                    'user:2026-11-08 "my wife\'s medical voice notes should stay private to me"'
                ],
            }
        )
        # one more good proposal, AFTER the 5 accepted above -> cap rejection
        proposals.append(
            {
                "slug": "good-proposal-cap",
                "title": "Good proposal over the cap",
                "what": "x",
                "why": "y",
                "risk": "z",
                "files": ["skills/some_skill_cap/skill.py"],
                "evidence": ["memory:mem-new-1"],
            }
        )
        client = FakeClient(
            {
                "supersedes": [],
                "corrections": [],
                "lessons": [],
                "proposals": proposals,
            }
        )
        job = FakeJob(user_id="service")
        res = mod.run({"user": "chuck", "days": 7}, job, client)
        check("no error", "error" not in res, str(res.get("error")))
        slugs = [p["slug"] for p in res["proposals_new"]]
        check(
            f"<=5 proposals (got {len(slugs)})",
            len(slugs) <= 5,
            str(slugs),
        )
        check("all new proposals have >=1 evidence ref",
              all(p["evidence"] for p in res["proposals_new"]))
        check("no-evidence rejected", "no-evidence" not in slugs)
        check("invented-evidence rejected", "invented-evidence" not in slugs)
        check(".env proposal rejected", "touch-env" not in slugs)
        check("compose proposal rejected", "touch-compose" not in slugs)
        check("privacy-scoping proposal rejected", "touch-privacy" not in slugs)
        check("conventions without quote rejected", "conventions-no-quote" not in slugs)
        check(
            "conventions with quoted user statement allowed",
            "conventions-with-quote" in slugs,
            str(slugs),
        )
        check("cap enforced (6th good proposal rejected)",
              "good-proposal-cap" not in slugs, str(slugs))
        # proposal files on disk: What/Why/Risk/Files sections + evidence refs
        if slugs:
            f = tmp / "proposals" / f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}-{slugs[0]}.md"
            check("proposal file written in proposals/", f.is_file(), str(f))
            if f.is_file():
                text = f.read_text()
                check(
                    "proposal format: What/Why/Risk/Files",
                    all(s in text for s in ("## What", "## Why", "## Risk + rollback", "## Files touched")),
                )
                check("proposal file lists evidence refs", "Evidence refs:" in text)
        # DB rows: same slugs as files, status open
        check(
            "DB rows match files",
            [r["slug"] for r in props.inserted] == slugs,
            str([r["slug"] for r in props.inserted]),
        )
        check("DB rows status=open", all(r["status"] == "open" for r in props.inserted))


def test_proposal_dedup():
    print("test_proposal_dedup")
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        mod = load_skill(tmp)
        mem, props, sess = FakeMemoryInterface(), FakeProposals(), FakeSessions()
        mem.memories = make_memories()
        # Open proposals carry evidence refs (the DB rows do; the disk
        # fallback does not) — the evidence-overlap dedup needs them.
        props.open = [
            {
                "slug": "already-open",
                "title": "Already open proposal",
                "status": "open",
                "evidence": ["job:job-fail-1", "job:job-ok-1"],
            },
            {
                "slug": "other-open",
                "title": "Already open proposal",
                "status": "open",
                "evidence": ["job:job-retry-1"],
            },
        ]
        install_fakes(mod, mem, props, sess, job_rows=make_job_rows())
        client = FakeClient(
            {
                "supersedes": [],
                "corrections": [],
                "lessons": [],
                "proposals": [
                    {
                        "slug": "already-open",
                        "title": "Fresh title",
                        "what": "x",
                        "why": "y",
                        "risk": "z",
                        "files": ["skills/x/skill.py"],
                        "evidence": ["memory:mem-new-1"],
                    },
                    {
                        "slug": "fresh-slug",
                        "title": "Already open proposal",
                        "what": "x",
                        "why": "y",
                        "risk": "z",
                        "files": ["skills/y/skill.py"],
                        "evidence": ["memory:mem-new-1"],
                    },
                    {
                        "slug": "brand-new",
                        "title": "Brand new proposal",
                        "what": "x",
                        "why": "y",
                        "risk": "z",
                        "files": ["skills/z/skill.py"],
                        "evidence": ["memory:mem-new-1"],
                    },
                    # Re-worded finding: new slug/title but cites both of
                    # already-open's evidence refs (>=50% of each set)
                    # -> must be dropped as a duplicate.
                    {
                        "slug": "reworded-finding",
                        "title": "Re-worded title for the same finding",
                        "what": "x",
                        "why": "y",
                        "risk": "z",
                        "files": ["skills/w/skill.py"],
                        "evidence": ["job:job-fail-1", "job:job-ok-1", "memory:mem-new-1"],
                    },
                    # Different evidence (no >=50% overlap with any open
                    # proposal) -> must still land.
                    {
                        "slug": "different-evidence",
                        "title": "Different evidence proposal",
                        "what": "x",
                        "why": "y",
                        "risk": "z",
                        "files": ["skills/v/skill.py"],
                        "evidence": ["job:job-retry-2", "memory:mem-new-1"],
                    },
                ],
            }
        )
        job = FakeJob(user_id="service")
        res = mod.run({"user": "chuck", "days": 7}, job, client)
        slugs = [p["slug"] for p in res["proposals_new"]]
        check("same slug not re-proposed", "already-open" not in slugs)
        check("same title not re-proposed", "fresh-slug" not in slugs)
        check("new proposal still lands", "brand-new" in slugs, str(slugs))
        check(
            "re-worded finding citing the same evidence not re-proposed",
            "reworded-finding" not in slugs,
            str(slugs),
        )
        check("different evidence still lands", "different-evidence" in slugs, str(slugs))
        check(
            "skipped reasons recorded",
            any("already open" in s for s in res["proposals_skipped"]),
            str(res["proposals_skipped"]),
        )
        check(
            "evidence-overlap skip reason recorded",
            any("evidence already open" in s for s in res["proposals_skipped"]),
            str(res["proposals_skipped"]),
        )


def test_staleness():
    print("test_staleness")
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        mod = load_skill(tmp)
        mem, props, sess = FakeMemoryInterface(), FakeProposals(), FakeSessions()
        mem.memories = make_memories()
        props.open = [
            {
                "slug": "ancient-proposal",
                "title": "Ancient proposal",
                "status": "open",
                "created_at": now_iso(20),  # > 14 days
            },
            {
                "slug": "recent-proposal",
                "title": "Recent proposal",
                "status": "open",
                "created_at": now_iso(3),
            },
        ]
        install_fakes(mod, mem, props, sess)
        client = FakeClient({"supersedes": [], "corrections": [], "lessons": [], "proposals": []})
        job = FakeJob(user_id="service")
        res = mod.run({"user": "chuck", "days": 7}, job, client)
        check("no error", "error" not in res, str(res.get("error")))
        check("stale section present", "Stale (open >14d" in res["report"])
        check("stale proposal flagged", "ancient-proposal" in res["report"].split("Stale")[1])
        check("fresh proposal not in stale section",
              "recent-proposal" not in res["report"].split("Stale")[1])
        check("never auto-deleted (no delete API on the fake)",
              not hasattr(props, "delete") and len(props.open) == 2)


def test_no_out_of_scope_writes():
    print("test_no_out_of_scope_writes")
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        mod = load_skill(tmp)
        mem, props, sess = FakeMemoryInterface(), FakeProposals(), FakeSessions()
        mem.memories = make_memories()
        make_session_transcript(tmp, "chuck", "sess-w-1")
        sess.ingests = [
            {"user_id": "chuck", "host": "mac", "session_id": "sess-w-1", "ingested_at": now_iso(1)}
        ]
        install_fakes(mod, mem, props, sess, job_rows=make_job_rows())
        client = FakeClient(
            {
                "supersedes": [],
                "corrections": [],
                "lessons": [],
                "proposals": [
                    {
                        "slug": "scoped-write",
                        "title": "Scoped write",
                        "what": "x",
                        "why": "y",
                        "risk": "z",
                        "files": ["skills/x/skill.py"],
                        "evidence": ["memory:mem-new-1"],
                    }
                ],
            }
        )
        job = FakeJob(user_id="service")
        # Snapshot pre-existing fixture files (test inputs) so the check
        # only flags files the JOB itself created.
        before = {p for p in tmp.rglob("*") if p.is_file()}
        res = mod.run({"user": "chuck", "days": 7}, job, client)
        check("no error", "error" not in res, str(res.get("error")))
        # Every file the job created must live under proposals/ or artifacts/.
        allowed_roots = [tmp / "proposals", tmp / "artifacts"]
        offenders = []
        for p in tmp.rglob("*"):
            if p.is_file() and p not in before:
                if not any(p.is_relative_to(r) for r in allowed_roots):
                    offenders.append(str(p))
        check("no file outside proposals/ + artifact dir", not offenders, str(offenders))
        # The sessions volume (read input) must be untouched (no new files;
        # the single input transcript is still there).
        sess_files = [p for p in (tmp / "sessions").rglob("*") if p.is_file()]
        check("session transcripts untouched (1 input file only)",
              len(sess_files) == 1 and sess_files[0].name == "sess-w-1.jsonl")


def test_invalid_target_user():
    print("test_invalid_target_user")
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        mod = load_skill(tmp)
        mem, props, sess = FakeMemoryInterface(), FakeProposals(), FakeSessions()
        install_fakes(mod, mem, props, sess)
        client = FakeClient(None)
        job = FakeJob(user_id="service")
        res = mod.run({"user": "service", "days": 7}, job, client)
        check("service target rejected", "error" in res, str(res))
        res2 = mod.run({"user": "unknown", "days": 7}, job, client)
        check("unknown target rejected", "error" in res2)
        check("no writes for invalid target", len(mem.writes) == 0)


def test_git_evidence_validation():
    print("test_git_evidence_validation")
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        mod = load_skill(tmp)
        mem, props, sess = FakeMemoryInterface(), FakeProposals(), FakeSessions()
        mem.memories = make_memories()
        install_fakes(mod, mem, props, sess)
        # Canned git log (monkeypatch the collector).
        mod._collect_git = lambda days: [
            {"sha": "abc123def456", "date": now_iso(1)[:10], "author": "Chuck",
             "subject": "skills: fix the thing"}
        ]
        client = FakeClient(
            {
                "supersedes": [],
                "corrections": [],
                "lessons": [],
                "proposals": [
                    {
                        "slug": "git-real-ref",
                        "title": "Proposal citing a real commit",
                        "what": "x",
                        "why": "y",
                        "risk": "z",
                        "files": ["skills/x/skill.py"],
                        "evidence": ["git:abc123def456"],
                    },
                    {
                        "slug": "git-fake-ref",
                        "title": "Proposal citing a fake commit",
                        "what": "x",
                        "why": "y",
                        "risk": "z",
                        "files": ["skills/y/skill.py"],
                        "evidence": ["git:deadbeef0000"],
                    },
                ],
            }
        )
        job = FakeJob(user_id="service")
        res = mod.run({"user": "chuck", "days": 7}, job, client)
        slugs = [p["slug"] for p in res["proposals_new"]]
        check("real git sha accepted", "git-real-ref" in slugs)
        check("invented git sha rejected", "git-fake-ref" not in slugs)


def test_jobs_input_includes_service_jobs():
    print("test_jobs_input_includes_service_jobs")
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        mod = load_skill(tmp)
        mem, props, sess = FakeMemoryInterface(), FakeProposals(), FakeSessions()
        install_fakes(mod, mem, props, sess, job_rows=make_job_rows())
        # Capture the SQL the job query actually runs (D10: scheduled jobs
        # are service-identity; the input must include them, otherwise the
        # jobs input is always empty and friction lessons have no signal).
        conn = FakeConn(make_job_rows())
        seen: list[tuple[str, object]] = []
        orig_cursor = conn.cursor

        def cursor():
            c = orig_cursor()
            orig_exec = c.execute

            def execute(sql, args=None):
                seen.append((sql, args))
                return orig_exec(sql, args)

            c.execute = execute
            return c

        conn.cursor = cursor
        mod._db_conn = lambda: conn
        jobs = mod._collect_jobs("chuck", 7)
        check("job rows returned", len(jobs) == 4, str(len(jobs)))
        sql = " ".join(seen[0][0].split()) if seen else ""
        check(
            "query includes service-identity jobs (D10)",
            "'service'" in sql and "user_id" in sql,
            sql[:200],
        )


def test_live_row_shape_proposals_module():
    """Regression test for the LIVE open-proposal dedup path (Phase 3).

    The real skills/runner/proposals.py module (NOT the FakeProposals
    stub) is exercised end-to-end with rows shaped exactly like real
    MySQL rows from the default pymysql cursor: 7-tuples
    (slug, title, evidence, target_files, status, created_at,
    reviewed_at) with the JSON columns as str / bytes / pre-parsed
    dict-list / NULL. The original bug (2026-11-08 dry run, job
    72afd0cfd2de): the module's ``def list`` shadowed the builtin
    ``list`` in the module globals, so ``isinstance(value, (dict,
    list))`` inside ``_row_to_dict`` raised "isinstance() arg 2 must be
    a type, a tuple of types, or a union" on every real row — the
    mocked unit tests never ran the real module's row conversion.
    """
    print("test_live_row_shape_proposals_module")
    import importlib.util as iul

    proposals_path = os.path.normpath(os.path.join(HERE, "..", "runner", "proposals.py"))
    check("real proposals module exists", os.path.isfile(proposals_path), proposals_path)
    spec = iul.spec_from_file_location("runner_proposals_live_test", proposals_path)
    mod = iul.module_from_spec(spec)
    spec.loader.exec_module(mod)

    # Guard against this class of bug: the module must not shadow the
    # builtin `list` (a module-level `def list` breaks isinstance() in
    # _row_to_dict's _json closure on every real row).
    check(
        "module does not shadow builtin list",
        "list" not in vars(mod),
        str(type(vars(mod).get("list"))),
    )

    # LIVE row shapes (pymysql default cursor): 7-tuples; the JSON
    # columns may come back as str (typical), bytes, pre-parsed
    # dict/list, or NULL (None); reviewed_at is NULL until a transition.
    live_rows = [
        (
            "str-json-row",
            "String JSON columns (typical pymysql shape)",
            '["user:2026-11-08 \\"private by default\\""]',
            '["agents-skills/memory-conventions/SKILL.md"]',
            "open",
            "2026-11-08T19:33:53.740885+00:00",
            None,
        ),
        (
            "bytes-json-row",
            "Bytes JSON columns",
            b'["job:abc-123"]',
            b'["skills/runner/main.py"]',
            "open",
            "2026-11-08T19:33:53.891466+00:00",
            None,
        ),
        (
            "parsed-json-row",
            "Pre-parsed JSON columns (dict/list)",
            ["memory:mem-1"],
            {"weird": True},
            "accepted",
            "2026-11-01T00:00:00+00:00",
            "2026-11-02T00:00:00+00:00",
        ),
        (
            "null-json-row",
            "NULL JSON columns",
            None,
            None,
            "dismissed",
            "2026-11-03T00:00:00+00:00",
            "2026-11-04T00:00:00+00:00",
        ),
    ]
    # Exercise the EXACT live path that failed in the 2026-11-08 dry
    # run: list_proposals() -> fetchall() -> _row_to_dict() -> _json().
    mod._DB_AVAILABLE = True
    mod._db_conn = lambda: FakeConn(live_rows)
    try:
        rows = mod.list_proposals(status=None, limit=50)
    except TypeError as exc:
        check("no isinstance TypeError on live rows", False, str(exc))
        return
    check("rows converted without error", len(rows) == 4, str(len(rows)))
    by_slug = {r["slug"]: r for r in rows}
    check(
        "str JSON columns parsed to list",
        by_slug["str-json-row"]["evidence"] == ['user:2026-11-08 "private by default"'],
        str(by_slug["str-json-row"]["evidence"]),
    )
    check(
        "bytes JSON columns parsed to list",
        by_slug["bytes-json-row"]["evidence"] == ["job:abc-123"],
        str(by_slug["bytes-json-row"]["evidence"]),
    )
    check(
        "pre-parsed JSON columns passed through",
        by_slug["parsed-json-row"]["evidence"] == ["memory:mem-1"]
        and by_slug["parsed-json-row"]["target_files"] == {"weird": True},
    )
    check(
        "NULL JSON columns stay None",
        by_slug["null-json-row"]["evidence"] is None
        and by_slug["null-json-row"]["target_files"] is None,
    )
    check(
        "status/created_at/reviewed_at preserved",
        by_slug["str-json-row"]["status"] == "open"
        and by_slug["str-json-row"]["reviewed_at"] is None
        and by_slug["parsed-json-row"]["reviewed_at"] == "2026-11-02T00:00:00+00:00",
    )
    # The skill's dedup call shape (status filter) must also work.
    mod._db_conn = lambda: FakeConn([live_rows[0]])
    open_rows = mod.list_proposals(status="open", limit=50)
    check(
        "status-filtered call (skill dedup path) works",
        len(open_rows) == 1 and open_rows[0]["slug"] == "str-json-row",
        str(open_rows),
    )


def test_open_proposal_dedup_live_module():
    """End-to-end: the skill's dedup input collector against the REAL
    proposals module (the exact call that logged
    "open-proposal query failed" in the 2026-11-08 live dry run)."""
    print("test_open_proposal_dedup_live_module")
    import importlib.util as iul

    proposals_path = os.path.normpath(os.path.join(HERE, "..", "runner", "proposals.py"))
    spec = iul.spec_from_file_location("runner_proposals_e2e_test", proposals_path)
    real = iul.module_from_spec(spec)
    spec.loader.exec_module(real)
    live_rows = [
        (
            "recent-activity-slow-run-optimization",
            "Optimize recent_activity slow runs",
            '["job:72afd0cfd2de"]',
            '["skills/recent_activity/skill.py"]',
            "open",
            "2026-11-08T19:33:53.891466+00:00",
            None,
        ),
    ]
    real._DB_AVAILABLE = True
    real._db_conn = lambda: FakeConn(live_rows)
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        skill_mod = load_skill(tmp)
        sys.modules["proposals"] = real
        try:
            open_props = skill_mod._collect_open_proposals()
        finally:
            sys.modules.pop("proposals", None)
    check(
        "_collect_open_proposals returns live rows (no query failure)",
        isinstance(open_props, list) and len(open_props) == 1,
        str(open_props),
    )
    check(
        "live row slug + title surfaced for dedup",
        open_props and open_props[0]["slug"] == "recent-activity-slow-run-optimization"
        and open_props[0]["title"] == "Optimize recent_activity slow runs",
        str(open_props),
    )


def main():
    tests = [
        test_zero_inputs,
        test_identity_d10,
        test_planted_correction,
        test_lessons_and_fallback,
        test_proposal_guardrails,
        test_proposal_dedup,
        test_staleness,
        test_no_out_of_scope_writes,
        test_invalid_target_user,
        test_git_evidence_validation,
        test_jobs_input_includes_service_jobs,
        test_live_row_shape_proposals_module,
        test_open_proposal_dedup_live_module,
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