"""market_research — LLM-driven market research report generator.

Orchestrates a multi-stage workflow that:
  1. Looks up the Knowledge Base for existing research
  2. Discovers and tiers competitors via web search
  3. Deep-dives each competitor (parallel crawler + LLM analysis)
  4. Identifies comparison vectors / themes
  5. Populates a comparison matrix
  6. Writes tier analysis summaries
  7. Generates an executive summary
  8. Scouts innovation & whitespace opportunities
  9. Plans visual assets (charts, tables, images)
 10. Assembles the final report via the Layout Engine and exports PDF

Each stage is a Celery task registered under the ``market_research.*``
namespace and wired into the existing workflow run-state engine.
"""
