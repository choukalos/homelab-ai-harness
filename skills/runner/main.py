#!/usr/bin/env python3
"""
Thor Skill Runner — Lightweight skill orchestration API.

Runs on dev port 8091 alongside the current AI Harness (8090).
Provides the job lifecycle API: launch, status, and artifact retrieval.
"""

import logging
import os
import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG_DIR = Path(os.environ.get("SKILL_RUNNER_LOG_DIR", "/home/chuck/homelab/logs/skill_runner"))
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_DIR / "skill_runner.log"),
    ],
)
logger = logging.getLogger("skill_runner")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ARTIFACT_ROOT = Path(os.environ.get("ARTIFACT_ROOT", "/home/chuck/data/media"))
APP_PORT = int(os.environ.get("SKILL_RUNNER_PORT", "8091"))
APP_HOST = os.environ.get("SKILL_RUNNER_HOST", "0.0.0.0")
DRY_RUN_MODE = os.environ.get("SKILL_RUNNER_DRY_RUN", "").lower() in ("true", "1", "yes")

# ---------------------------------------------------------------------------
# Job Model
# ---------------------------------------------------------------------------


class JobStatus(str, Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"
    awaiting_approval = "awaiting_approval"
    cancelled = "cancelled"


class Job(BaseModel):
    """Complete job record for a skill invocation."""

    job_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    skill: str
    status: JobStatus = JobStatus.pending
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    completed_at: Optional[str] = None
    summary: Optional[str] = None
    artifact_path: Optional[str] = None
    requester: Optional[str] = None
    channel: Optional[str] = None
    params: dict[str, Any] = Field(default_factory=dict)
    dry_run: bool = False
    tool_bundle: Optional[str] = None
    model_alias: Optional[str] = None
    error: Optional[str] = None
    logs: list[str] = Field(default_factory=list)

    def add_log(self, message: str) -> None:
        self.logs.append(f"[{datetime.now(timezone.utc).isoformat()}] {message}")
        logger.info("Job %s: %s", self.job_id, message)


# ---------------------------------------------------------------------------
# In-memory job store (dev only — no database)
# ---------------------------------------------------------------------------
jobs: dict[str, Job] = {}

# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class SkillLaunchRequest(BaseModel):
    """POST /skills/{skill_name} body."""

    params: dict[str, Any] = Field(default_factory=dict)
    requester: Optional[str] = None
    channel: Optional[str] = None
    dry_run: bool = False
    tool_bundle: Optional[str] = None
    model_alias: Optional[str] = None


class SkillJobResponse(BaseModel):
    """GET /skills/jobs/{job_id} response."""

    job_id: str
    skill: str
    status: str
    created_at: str
    completed_at: Optional[str] = None
    summary: Optional[str] = None
    artifact_path: Optional[str] = None
    requester: Optional[str] = None
    channel: Optional[str] = None
    params: dict[str, Any] = Field(default_factory=dict)
    dry_run: bool = False
    tool_bundle: Optional[str] = None
    model_alias: Optional[str] = None
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Skill Registry
# ---------------------------------------------------------------------------

# Known skill names (populated from manifest files in sibling directories).
# For now, any skill_name is accepted; production will validate against manifests.
KNOWN_SKILLS = [
    "siri_ask",
    "deep_research",
    "investment_brief",
    "presentation_build",
    "code_review",
    "repo_maintenance",
    "family_kb_ingest",
    "morning_brief",
    "homelab_report",
]


# ---------------------------------------------------------------------------
# Skill Execution
# ---------------------------------------------------------------------------

def _find_skill_module(skill_name: str) -> Optional[Path]:
    """Locate a skill's __init__.py or run.py in the skills/ directory."""
    base = Path(__file__).resolve().parent.parent
    skill_dir = base / skill_name
    for entry in ("run.py", "skill.py", "__init__.py"):
        p = skill_dir / entry
        if p.is_file():
            return p
    return None


def _execute_skill(job: Job) -> None:
    """
    Execute a skill job.

    In skeleton form this logs the job details and marks it completed.
    Phase 9 will add real skill execution logic here.
    """
    job.status = JobStatus.running
    job.add_log(f"Executing skill '{job.skill}'")

    if job.dry_run:
        job.add_log("DRY RUN — skipping actual execution")
        job.add_log(f"Params: {job.params}")
        job.add_log(f"Tool bundle: {job.tool_bundle or 'none'}")
        job.add_log(f"Model alias: {job.model_alias or 'none'}")
        job.status = JobStatus.completed
        job.completed_at = datetime.now(timezone.utc).isoformat()
        job.summary = "Dry run completed — no action taken."
        logger.info("DRY RUN job %s completed.", job.job_id)
        return

    # Check approval gate
    if job.status == JobStatus.awaiting_approval:
        job.add_log("Approval gate — job paused awaiting manual approval")
        return

    # Find and execute the skill module
    skill_path = _find_skill_module(job.skill)
    if skill_path is None:
        job.status = JobStatus.failed
        job.completed_at = datetime.now(timezone.utc).isoformat()
        job.error = f"Skill '{job.skill}' module not found (expected {skill_path})"
        job.add_log(job.error)
        logger.error("Skill not found: %s", job.skill)
        return

    job.add_log(f"Skill module found at: {skill_path}")
    job.add_log("Skeleton runner — skill execution placeholder. Phase 9 will implement real logic.")

    # For now, mark as completed with a summary
    job.status = JobStatus.completed
    job.completed_at = datetime.now(timezone.utc).isoformat()
    job.summary = f"Skill '{job.skill}' executed successfully (skeleton placeholder)."

    # Compute artifact path if applicable
    if job.skill in KNOWN_SKILLS:
        artifact_subdir = _artifact_subdir_for_skill(job.skill)
        if artifact_subdir:
            slug = job.params.get("query", job.params.get("topic", "output"))
            slug = _slugify(slug)
            ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
            ext = "md" if job.skill != "presentation_build" else "json"
            art_name = f"{job.skill}_{ts}_{slug}.{ext}"
            job.artifact_path = str(ARTIFACT_ROOT / artifact_subdir / art_name)
            job.add_log(f"Artifact path: {job.artifact_path}")


def _artifact_subdir_for_skill(skill: str) -> Optional[str]:
    mapping = {
        "deep_research": "research_reports",
        "investment_brief": "investment_briefs",
        "presentation_build": "presentations",
        "code_review": "code_reviews",
        "repo_maintenance": "code_reviews",
        "morning_brief": "homelab_reports",
        "homelab_report": "homelab_reports",
        "siri_ask": "siri_outputs",
        "family_kb_ingest": None,  # ingests into Qdrant, no file artifact
    }
    return mapping.get(skill)


def _slugify(value: str) -> str:
    return "".join(c if c.isalnum() or c == "-" else "-" for c in value[:50]).strip("-")


# ---------------------------------------------------------------------------
# FastAPI Application
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Thor Skill Runner",
    description="Skill orchestration API — runs on dev port 8091.",
    version="0.1.0",
)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "port": APP_PORT, "jobs_total": len(jobs)}


@app.post("/skills/{skill_name}")
async def launch_skill(skill_name: str, body: SkillLaunchRequest) -> SkillJobResponse:
    """
    Launch a skill job.

    - **skill_name**: The skill to execute (e.g. `deep_research`, `siri_ask`).
    - **body**: JSON with `params`, `requester`, `channel`, `dry_run`, `tool_bundle`, `model_alias`.
    """
    job = Job(
        skill=skill_name,
        params=body.params,
        requester=body.requester,
        channel=body.channel,
        dry_run=body.dry_run,
        tool_bundle=body.tool_bundle,
        model_alias=body.model_alias,
    )

    job.add_log(f"Job created for skill '{skill_name}'")
    if body.dry_run:
        job.add_log("Dry run mode enabled")

    # Approval gate: if the skill requires approval, pause here
    # In skeleton form, no skills require approval by default.
    # Phase 9 will add per-skill approval gate configuration.
    if skill_name in ("family_kb_ingest", "repo_maintenance"):
        job.status = JobStatus.awaiting_approval
        job.add_log("Awaiting approval gate")
        jobs[job.job_id] = job
        logger.info("Job %s awaiting approval.", job.job_id)
        return _job_to_response(job)

    # Execute (synchronously in skeleton; Phase 9 will add async background tasks)
    _execute_skill(job)
    jobs[job.job_id] = job

    logger.info("Job %s launched for skill '%s'.", job.job_id, skill_name)
    return _job_to_response(job)


@app.get("/skills/jobs/{job_id}")
async def get_job_status(job_id: str) -> SkillJobResponse:
    """Get the status of a skill job."""
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return _job_to_response(job)


@app.get("/skills/jobs/{job_id}/artifact")
async def get_job_artifact(job_id: str):
    """
    Retrieve the output artifact file for a completed skill job.

    Returns the file content with appropriate media type.
    """
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    if not job.artifact_path:
        raise HTTPException(
            status_code=404, detail=f"Job {job_id} has no artifact"
        )

    artifact_file = Path(job.artifact_path)
    if not artifact_file.is_file():
        raise HTTPException(
            status_code=404,
            detail=f"Artifact file not found: {artifact_file}",
        )

    content = artifact_file.read_bytes()

    # Determine media type
    ext = artifact_file.suffix.lower()
    media_types = {
        ".md": "text/markdown",
        ".txt": "text/plain",
        ".json": "application/json",
        ".html": "text/html",
        ".csv": "text/csv",
        ".pdf": "application/pdf",
    }
    media_type = media_types.get(ext, "application/octet-stream")

    return Response(content=content, media_type=media_type)


@app.post("/skills/jobs/{job_id}/approve")
async def approve_job(job_id: str) -> SkillJobResponse:
    """Approve a job waiting at an approval gate and resume execution."""
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    if job.status != JobStatus.awaiting_approval:
        raise HTTPException(
            status_code=400,
            detail=f"Job {job_id} is not awaiting approval (status: {job.status})",
        )

    job.add_log("Approval granted — resuming execution")
    _execute_skill(job)
    logger.info("Job %s approved and resumed.", job.job_id)
    return _job_to_response(job)


@app.post("/skills/jobs/{job_id}/cancel")
async def cancel_job(job_id: str) -> SkillJobResponse:
    """Cancel a pending or running job."""
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    terminal_states = {JobStatus.completed, JobStatus.failed, JobStatus.cancelled}
    if job.status in terminal_states:
        raise HTTPException(
            status_code=400,
            detail=f"Job {job_id} is already {job.status}",
        )

    job.status = JobStatus.cancelled
    job.completed_at = datetime.now(timezone.utc).isoformat()
    job.add_log("Job cancelled by requester")
    logger.info("Job %s cancelled.", job.job_id)
    return _job_to_response(job)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _job_to_response(job: Job) -> SkillJobResponse:
    return SkillJobResponse(
        job_id=job.job_id,
        skill=job.skill,
        status=job.status.value,
        created_at=job.created_at,
        completed_at=job.completed_at,
        summary=job.summary,
        artifact_path=job.artifact_path,
        requester=job.requester,
        channel=job.channel,
        params=job.params,
        dry_run=job.dry_run,
        tool_bundle=job.tool_bundle,
        model_alias=job.model_alias,
        error=job.error,
    )


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


def main():
    import uvicorn

    logger.info("Starting Thor Skill Runner on %s:%d", APP_HOST, APP_PORT)
    logger.info("Artifact root: %s", ARTIFACT_ROOT)
    logger.info("Dry-run global mode: %s", DRY_RUN_MODE)
    logger.info("Log directory: %s", LOG_DIR)

    uvicorn.run(
        "main:app",
        host=APP_HOST,
        port=APP_PORT,
        log_level="info",
    )


if __name__ == "__main__":
    main()
