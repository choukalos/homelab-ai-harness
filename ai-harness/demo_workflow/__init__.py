"""
One-page clickable demo workflow module (Coordinator pattern).

Uses a per-phase coordinator in service.run_demo() that invokes separate
short-lived LLM calls per phase, passing structured JSON state between
them via DemoState. This avoids the 70K context window limit of vLLM.

SSE Streaming (Session 10): POST /demos/run/stream emits real-time phase
progress via the coordinator pipeline. Events include phase_start,
phase_progress, phase_complete, and pipeline_complete with elapsed time,
summary data, and final metadata. Replaces the legacy single-agent stream.

Level 3 Mock Behavior (Session 7): All demos include simulated async
patterns — loading spinners, toast notifications, confirmation dialogs,
data persistence via localStorage, and optimistic UI updates — to create
the illusion of a real application.

Product Insights (Session 8): Each demo captures discovery notes (MVP
features, nice-to-have, research insights) and a complexity score with
breakdown (screen count, interactive elements, estimated build effort)
for product discovery prioritization.

Resumption & Checkpointing (Session 9): The pipeline saves checkpoints
after each phase to ~/.ai-harness/demo_checkpoints/{thread_id}.json. If
interrupted, call POST /demos/jobs/{thread_id}/resume to continue from
the last completed phase. Checkpoints auto-expire after 24 hours.

Phases:
  1. Parse Request     — chat_completion_sync (PHASE_PARSE_SYSTEM)
  2. KB Lookup         — kb_lookup tool
  3. Web Research      — search_and_crawl tool
  4. Requirements/Design — chat_completion_sync (PHASE_DESIGN_SYSTEM) + discovery_notes
  5. Build Plan        — chat_completion_sync (PHASE_PLAN_SYSTEM) + complexity_score
  6a. Core Structure   — generate_html (BUILD_STRUCTURE_SYSTEM) + Level 3 foundation
  6b. Interactive Features — generate_html (BUILD_FEATURES_SYSTEM) + Level 3 async
  6c. Polish           — generate_html (BUILD_POLISH_SYSTEM) + Level 3 animations
  7. Functional Verification — verify_interactivity (incl. Level 3 checks) / fix_html
  8. Polish & Critique — critique_demo (incl. Level 3 realism score) / fix_html
  9. Save Final        — save_demo with Level 3 + product insights metadata

Endpoints:
  POST /demos/run              — Sync demo creation (coordinator pattern)
  POST /demos/run/stream       — SSE streaming (coordinator, phase-level events)
  GET  /demos/jobs             — List recent jobs
  GET  /demos/jobs/{thread_id} — Get job status
  GET  /demos/jobs/{thread_id}/checkpoint — Checkpoint status
  POST /demos/jobs/{thread_id}/resume     — Resume from checkpoint
  DELETE /demos/jobs/{thread_id}/checkpoint — Remove checkpoint
  POST /demos/jobs/{thread_id}/cancel     — Cancel a running job
  GET  /demos/                 — List all demos
  GET  /demos/search           — Search demos
  GET  /demos/{slug}           — Demo metadata
  GET  /demos/{slug}/html      — Serve final HTML
"""

# Re-export checkpointer init — shared with deep_research module
from demo_workflow.service import ensure_checkpointer_tables

# Re-export state model for cross-module use
from demo_workflow.state import DemoState

# Re-export checkpoint utilities
from demo_workflow.service import CheckpointManager

__all__ = ["ensure_checkpointer_tables", "DemoState", "CheckpointManager"]
