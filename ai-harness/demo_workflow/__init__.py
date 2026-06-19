"""
One-page clickable demo workflow module (Deep Agents with MySQL checkpointing).

Uses the same pattern as deep_research:
  User Prompt → FastAPI → run_demo(req) → get_deep_agent().ainvoke(input_state, config)

The orchestrator agent follows DEMO_WORKFLOW_INSTRUCTIONS to:
  1. Parse the request and create a demo brief
  2. Search the knowledge base for prior information
  3. Delegate web research to a sub-agent
  4. Synthesize a design specification
  5. Create a numbered build plan
  6. Build the demo in progressive steps (structure → features → polish)
  7. Verify interactivity with static analysis
  8. Run a quality critique
  9. Save the final HTML + metadata to disk

MySQL checkpointing (shared with deep_research) auto-persists after each
agent step, enabling resume after interruption via thread_id.

Level 3 Mock Behavior: All demos include simulated async patterns — loading
spinners, toast notifications, confirmation dialogs, data persistence via
localStorage, and optimistic UI updates — to create the illusion of a real
application.

Product Insights: Each demo captures discovery notes (MVP features, nice-to-have,
research insights) and a complexity score with breakdown for prioritization.

Endpoints:
  POST /demos/run              — Sync demo creation (deep agent ainvoke)
  POST /demos/run/stream       — SSE streaming (deep agent astream)
  GET  /demos/jobs             — List recent jobs
  GET  /demos/jobs/{thread_id} — Get job status
  GET  /demos/jobs/{thread_id}/checkpoint — Checkpoint status (MySQL)
  POST /demos/jobs/{thread_id}/resume     — Resume from checkpoint (MySQL)
  DELETE /demos/jobs/{thread_id}/checkpoint — Remove checkpoint
  POST /demos/jobs/{thread_id}/cancel     — Cancel a running job
  GET  /demos/                 — List all demos
  GET  /demos/search           — Search demos
  GET  /demos/{slug}           — Demo metadata
  GET  /demos/{slug}/html      — Serve final HTML
"""

# Re-export checkpointer init — shared with deep_research module
from demo_workflow.service import ensure_checkpointer_tables

__all__ = ["ensure_checkpointer_tables"]
