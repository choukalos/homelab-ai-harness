"""
One-page clickable demo workflow module (Deep Agents harness).

Uses the deepagents framework with a single orchestrator agent that follows
the 8-phase demo creation pipeline. Research is delegated to a sub-agent.
MySQL checkpointing is shared with the deep_research module.

The orchestrator uses these tools:
  - search_and_crawl, think_tool   (direct research)
  - kb_lookup                      (family knowledge base)
  - generate_html, validate_html   (Phase 6 build loop)
  - fix_html                       (Phase 6-7 fixes)
  - critique_demo                  (Phase 7 polish)
  - save_demo                      (Phase 8 final save)
  - write_file, read_file          (deepagents framework)

Endpoints:
  POST /demos/run              — Sync demo creation
  POST /demos/run/stream       — SSE streaming
  GET  /demos/jobs             — List recent jobs
  GET  /demos/jobs/{thread_id} — Get job status
  POST /demos/jobs/{thread_id}/cancel
  GET  /demos/                 — List all demos
  GET  /demos/search           — Search demos
  GET  /demos/{slug}           — Demo metadata
  GET  /demos/{slug}/html      — Serve final HTML
"""

# Re-export checkpointer init — shared with deep_research module
from demo_workflow.service import ensure_checkpointer_tables

__all__ = ["ensure_checkpointer_tables"]
